"""The eight schedulers, one interface. Rules are specified in docs/ALGORITHM_SPEC.md.

Interface: bind(view); on_enqueue(c, now); select(now) -> class with a non-empty queue;
update(now) (adaptive only, every update_interval); quanta() -> current per-class quanta.
"""
from __future__ import annotations

import math
from collections import deque

from .config import CLASSES, K
from .engine import TIE_EPS

BASE_Q = (1500.0, 1500.0, 1500.0)
# physically meaningful limits for byte quanta: below 0.01 B a packet needs > 10^5 rounds per byte of size
# (effectively a hang); above 1e9 B deficits stop being representable without overflow risk
Q_LO, Q_HI = 0.01, 1e9
FRAME = sum(BASE_Q)
# DRR skips ahead after a full pass in which no class could send, if every class still needs at least this many more
# passes (tiny quanta, e.g. 0.01 B against 1500 B packets, would otherwise cost 150 000 passes per packet)
SKIP_MIN = 32
D_TARGET = tuple(c.delay_target for c in CLASSES)
PRICE = tuple(c.price for c in CLASSES)


class Scheduler:
    name = "base"
    adaptive = False
    defaults: dict = {}
    any_k = False      # True only where a class declares it: rule defined for any number of classes

    def __init__(self, k=None, **params):
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"{self.name}: unknown parameters {sorted(unknown)}")
        if k is None:
            k = K
        if not (isinstance(k, int) and not isinstance(k, bool) and 1 <= k <= 4096):
            raise ValueError(f"{self.name}: number of classes must be an integer in [1, 4096], got {k!r}")
        if k != K and not vars(type(self)).get("any_k", False):
            raise ValueError(f"{self.name} is defined for exactly {K} classes, got k={k}")
        self.k = k
        self.p = {**self.defaults, **params}
        self.validate()

    def validate(self):
        """Raise ValueError for parameters that would hang or corrupt the simulation."""

    def _need(self, ok, msg):
        if not ok:
            raise ValueError(f"{self.name}: {msg}")

    def _num(self, key, lo=None, hi=None, lo_open=False, hi_open=False):
        x = self.p[key]
        self._need(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x),
                   f"{key} must be a finite number, got {x!r}")
        if lo is not None:
            self._need(x > lo if lo_open else x >= lo, f"{key} must be {'>' if lo_open else '>='} {lo}, got {x}")
        if hi is not None:
            self._need(x < hi if hi_open else x <= hi, f"{key} must be {'<' if hi_open else '<='} {hi}, got {x}")

    def _vector(self, key, positive):
        v = self.p[key]
        self._need(isinstance(v, (tuple, list)), f"{key} must be a tuple/list of {self.k} numbers, got {v!r}")
        self._need(len(v) == self.k, f"{key} needs {self.k} values, got {len(v)}")
        self._need(all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                       and (Q_LO <= x <= Q_HI if positive else 0 <= x <= 1e6) for x in v),
                   f"{key} values must be finite and in {'[0.01, 1e9] bytes' if positive else '[0, 1e6]'}, got {v}")

    def bind(self, view):
        if len(view.queues) != self.k:
            raise ValueError(f"{self.name}: built for {self.k} classes, view has {len(view.queues)}")
        self.v = view

    def on_enqueue(self, c, now):
        pass

    def update(self, now):
        pass

    def quanta(self):
        return (float("nan"),) * self.k


class FIFO(Scheduler):
    """Serve the oldest queued packet. Admitted packets are enqueued in arrival order and FIFO always serves the
    oldest, so remembering the class of each queued packet in that order gives the answer in O(1) per decision
    (the same packet as scanning every queue head for the smallest packet id)."""
    name = "FIFO"
    any_k = True

    def bind(self, view):
        super().bind(view)
        self.order = deque()

    def on_enqueue(self, c, now):
        self.order.append(c)

    def select(self, now):
        return self.order.popleft()


class StrictPriority(Scheduler):
    name = "SP"
    any_k = True

    def select(self, now):
        for c, q in enumerate(self.v.queues):
            if q:
                return c
        raise RuntimeError("select() called with empty buffer")


class DRR(Scheduler):
    name = "DRR"
    defaults = {"quanta": BASE_Q}
    any_k = True

    def validate(self):
        self._vector("quanta", positive=True)

    def bind(self, view):
        super().bind(view)
        self.Q = [float(x) for x in self.p["quanta"]]
        self.deficit = [0.0] * self.k
        self.active = deque()
        self.in_active = [False] * self.k
        self.current = None   # class whose visit is in progress (always active[0])

    def quanta(self):
        return tuple(self.Q)

    def on_enqueue(self, c, now):
        if not self.in_active[c]:
            self.in_active[c] = True
            self.deficit[c] = 0.0
            self.active.append(c)

    def _leave_front(self, c):
        self.active.popleft()
        self.in_active[c] = False
        self.deficit[c] = 0.0
        self.current = None

    def _skip_empty_passes(self):
        """Called after a full pass over the active list in which no class could send. Adds r quanta to every
        active class at once, r = (fewest passes any class still needs) - 2, so the passes in which some class
        can send are still taken one at a time and in order. Identical to adding one quantum per pass whenever
        that float arithmetic is exact (whole-byte or binary-fraction quanta). Otherwise one multiplication
        replaces r roundings; decisions can then differ only where the exact deficit equals a packet size
        (e.g. 10 000 x 0.02 B = 200 B), and there the single rounding is the more accurate of the two."""
        queues, size, deficit, Q = self.v.queues, self.v.size, self.deficit, self.Q
        r = min(math.ceil((size[queues[c][0]] - deficit[c]) / Q[c]) for c in self.active) - 2
        if r >= SKIP_MIN:
            for c in self.active:
                deficit[c] += r * Q[c]

    def select(self, now):
        queues, size, deficit, active = self.v.queues, self.v.size, self.deficit, self.active
        # invariant: a class is on the active list exactly while its queue is non-empty (it joins on
        # enqueue and leaves when its last packet is served), so every head below exists
        c = self.current
        if c is not None:                         # continue the visit in progress
            q = queues[c]
            head = size[q[0]]
            if deficit[c] >= head:
                deficit[c] -= head
                if len(q) == 1:                   # queue empties with this packet
                    self._leave_front(c)
                return c
            self.current = None
            active.rotate(-1)
        if not active:
            raise RuntimeError("DRR select() with no backlogged class")
        Q = self.Q
        misses = 0
        while True:                               # start the next visit: add the quantum once
            c = active[0]
            deficit[c] += Q[c]
            q = queues[c]
            head = size[q[0]]
            if deficit[c] >= head:
                deficit[c] -= head
                if len(q) == 1:
                    self._leave_front(c)
                else:
                    self.current = c
                return c
            active.rotate(-1)
            misses += 1
            if misses == len(active):             # a full pass without a send
                misses = 0
                self._skip_empty_passes()


class DRREndOfService(DRR):
    """DRR as modelled in network calculus (Boyer et al. 2012; Tabatabaee & Le Boudec 2022): a class's
    emission opportunity ends when its queue is empty at the END of a service, so a packet that arrives while
    the class's last queued packet is on the link is still served in the same opportunity. The DRR class above
    decides when the packet is dequeued at the start of its service, as Linux sch_drr does. The two differ
    only in that case. Used by the literature benchmarks (E13); not one of the compared schedulers."""
    name = "DRR-EOS"
    any_k = True

    def on_enqueue(self, c, now):
        if c == self.current and len(self.v.queues[c]) == 1 and self.v.t_free <= now:
            self._leave_front(c)       # its last packet finished before this arrival: the opportunity had ended
        super().on_enqueue(c, now)

    def select(self, now):
        queues, size, deficit, active = self.v.queues, self.v.size, self.deficit, self.active
        # invariant: every class on the active list except possibly the current one has a non-empty queue
        c = self.current
        if c is not None:
            q = queues[c]
            if not q:                             # empty at the end of its service: the opportunity ends
                self._leave_front(c)
            elif deficit[c] >= size[q[0]]:
                deficit[c] -= size[q[0]]
                return c
            else:
                self.current = None
                active.rotate(-1)
        if not active:
            raise RuntimeError("DRR-EOS select() with no backlogged class")
        Q = self.Q
        misses = 0
        while True:
            c = active[0]
            deficit[c] += Q[c]
            head = size[queues[c][0]]
            if deficit[c] >= head:
                deficit[c] -= head
                self.current = c
                return c
            active.rotate(-1)
            misses += 1
            if misses == len(active):             # a full pass without a send
                misses = 0
                self._skip_empty_passes()


class RLSPDRR(DRR):
    """RL-SP-DRR, Algorithm 1 of Tokmakov et al. (CloudNet 2019, arXiv:2002.07027).

    Class 0 is the high-priority queue (HPQ). At enqueue each HPQ packet gets a departure time
    d = max(arrival, d_prev + size / r) (virtual-clock shaper at rate r); the HPQ head is sent
    once d <= now, otherwise it is held. DRR runs over classes 1..K-1 only. Not work-conserving.
    The max(arrival, .) clamp is our interpretation (the paper writes d = last_sent + size/r).
    """
    name = "RL-SP+DRR"
    defaults = {"quanta": BASE_Q, "rate_frac": 0.3}
    any_k = False                     # one shaped high-priority class plus DRR: defined for the 3-class model

    def validate(self):
        super().validate()
        self._num("rate_frac", lo=1e-6, hi=1e3)   # below 1e-6 C, shaped departure times outgrow float precision

    def bind(self, view):
        super().bind(view)
        self.rate_Bps = self.p["rate_frac"] * view.link_rate / 8
        self.last_dep = float("-inf")
        self.dep = deque()          # departure times of queued HPQ packets, FIFO

    def on_enqueue(self, c, now):
        if c == 0:
            d = max(now, self.last_dep + self.v.size[self.v.queues[0][-1]] / self.rate_Bps)
            self.dep.append(d)
            self.last_dep = d
        else:
            super().on_enqueue(c, now)

    def wake_time(self):
        return self.dep[0] if self.dep else float("inf")

    def select(self, now):
        if self.dep and self.dep[0] <= now + TIE_EPS:   # same tie tolerance as the engine
            self.dep.popleft()
            return 0
        if any(self.v.queues[c] for c in range(1, self.k)):
            return super().select(now)
        return None


class _AdaptiveDRR(DRR):
    adaptive = True


class SQDRR(_AdaptiveDRR):
    name = "DR-DRR"
    defaults = {"kappa": 4.0, "theta": 0.5, "qmax_mult": 8.0, "smooth": 1.0}

    def validate(self):
        self._num("kappa", lo=0)
        self._num("theta", lo=0)
        self._num("qmax_mult", lo=1, hi=1e6)
        self._num("smooth", lo=0, hi=1, lo_open=True)

    def bind(self, view):
        self.p = {**self.p, "quanta": BASE_Q}
        super().bind(view)

    def update(self, now):
        v, p = self.v, self.p
        tot = sum(self.Q)
        for c in range(K):
            phi = self.Q[c] / tot
            drain = 8.0 * v.qbytes[c] / (v.link_rate * phi)
            risk = self._delay_estimate(v.hol(c, now), drain) / D_TARGET[c]
            q = BASE_Q[c] * (1.0 + p["kappa"] * max(0.0, risk - p["theta"]))
            target = min(max(q, BASE_Q[c]), p["qmax_mult"] * BASE_Q[c])
            lam = p["smooth"]   # E9 damping ablation; 1 = rule as specified
            self.Q[c] = target if lam == 1.0 else (1 - lam) * self.Q[c] + lam * target

    @staticmethod
    def _delay_estimate(hol, drain):
        """DR-DRR's delay estimate: the larger of the head-of-line wait and the predicted drain time."""
        return max(hol, drain)


class SQDRRStatic(SQDRR):
    """SD-DRR (E23): DR-DRR's delay-risk rule applied on top of a static base quantum per class (default: the E19 static
    optimum) instead of 1500 B. Quanta stay in [B_i, M B_i], so the service-gap argument of Proposition 1 holds with M B_j."""
    name = "SD-DRR"
    defaults = {"kappa": 4.0, "theta": 0.5, "qmax_mult": 2.0, "smooth": 1.0, "base": (6000.0, 6000.0, 1500.0)}

    def validate(self):
        super().validate()
        self._vector("base", positive=True)

    def bind(self, view):
        self.p = {**self.p, "quanta": tuple(float(x) for x in self.p["base"])}
        DRR.bind(self, view)

    def update(self, now):
        v, p = self.v, self.p
        base = p["base"]
        tot = sum(self.Q)
        for c in range(K):
            phi = self.Q[c] / tot
            drain = 8.0 * v.qbytes[c] / (v.link_rate * phi)
            risk = self._delay_estimate(v.hol(c, now), drain) / D_TARGET[c]
            q = base[c] * (1.0 + p["kappa"] * max(0.0, risk - p["theta"]))
            target = min(max(q, base[c]), p["qmax_mult"] * base[c])
            lam = p["smooth"]
            self.Q[c] = target if lam == 1.0 else (1 - lam) * self.Q[c] + lam * target


class CQDRRVariant(_AdaptiveDRR):
    """Our first-draft CQDRR reading (queue share x delay-requirement weight). Kept as a labelled
    variant outside the main 8 after the paper turned out to use a different rule (deviation 5)."""
    name = "CQDRR-draft"
    defaults = {"alpha": 1.0, "beta": 0.5, "qmin": 300.0, "smooth": 1.0}

    def validate(self):
        self._num("alpha", lo=0, hi=50)
        self._num("beta", lo=0, hi=50)
        self._num("qmin", lo=Q_LO, hi=Q_HI)
        self._num("smooth", lo=0, hi=1, lo_open=True)
    EPS = 1500.0

    def bind(self, view):
        self.p = {**self.p, "quanta": BASE_Q}
        super().bind(view)

    def update(self, now):
        v, p = self.v, self.p
        dmin = min(D_TARGET)
        tot_b = sum(v.qbytes) + K * self.EPS
        w = [((v.qbytes[c] + self.EPS) / tot_b) ** p["alpha"] * (dmin / D_TARGET[c]) ** p["beta"]
             for c in range(K)]
        sw = sum(w)
        lam = p["smooth"]
        for c in range(K):
            target = max(p["qmin"], FRAME * w[c] / sw)
            self.Q[c] = (1 - lam) * self.Q[c] + lam * target


def mm1k_blocking(rho, k):
    """M/M/1/K blocking probability (1-rho) rho^K / (1 - rho^(K+1)), evaluated stably."""
    if rho <= 0:
        return 0.0
    if abs(rho - 1.0) < 1e-9:
        return 1.0 / (k + 1)
    if rho < 1:
        return (1 - rho) * rho ** k / (1 - rho ** (k + 1))
    return (rho - 1) / (rho - rho ** (-k))


def alpha_fair(x, a):
    import math
    return math.log(x) if a == 1 else (x ** (1 - a)) / (1 - a)


class CQDRR(_AdaptiveDRR):
    """CQDRR of Zhang & Lu, Electronics Letters 61(1) e70418, 2025 (Eqs. 1-8, 12-13), wired reading.

    Classes map to TT (0), AVB (1), BE (2); DRR rounds visit classes in that priority order.
    Every update, with R_i = C Q_i / sum Q (channel factor constant on a wired link),
    Rbar_i <- (1-g) Rbar_i + g R_i, D_i = 8 (Q_i + Lmax_i) / R_i, eta_i = -ln(p) / Dc_i,
    h = mean of eta_i D_i over TT classes, W_i = M/M/1/K blocking at rho_i = lambda_i / R_i:
        TT : Q = S a_i exp((eta D - h) / (1 + sqrt h)) U(R/Rbar) + b_i L_i W_i
        AVB: Q = S (-a_i ln D_i)            U(R/Rbar) + b_i L_i W_i
        BE : Q = S U(R/Rbar)
    with L_i the backlog in bytes. Scale S (bytes), a_i = b_i, U's alpha, g and the floor are
    our choices where the paper is silent (docs/ALGORITHM_SPEC.md section 6).
    """
    name = "CQDRR"
    defaults = {"scale": 1500.0, "w": 0.5, "alpha_fair": 0.0, "rbar_gain": 0.1, "p_viol": 0.05,
                "rate_ewma": 0.1, "qmin": 64.0, "qmax": 64000.0}

    def validate(self):
        self._num("scale", lo=0, hi=Q_HI)
        self._num("w", lo=0, hi=1)
        self._num("alpha_fair", lo=0, hi=10)   # the alpha-fair family is numerically degenerate far beyond this
        self._num("rbar_gain", lo=0, hi=1, lo_open=True)
        self._num("p_viol", lo=0, hi=1, lo_open=True, hi_open=True)
        self._num("rate_ewma", lo=0, hi=1, lo_open=True)
        self._num("qmin", lo=Q_LO, hi=Q_HI)
        self._num("qmax", lo=self.p["qmin"], hi=Q_HI)
    LMAX = tuple(float(c.size_max) for c in CLASSES)
    MEAN = tuple(c.mean_size for c in CLASSES)

    def bind(self, view):
        self.p = {**self.p, "quanta": BASE_Q}
        super().bind(view)
        C = view.link_rate
        self.rbar = [C * q / FRAME for q in self.Q]
        self.lam = [0.0] * K
        self.last_arrived = [0] * K
        self.k_cap = [max(1, int(view.buffer_bytes // m)) for m in self.MEAN]
        self.cursor = 0

    def select(self, now):
        """DRR with rounds in fixed priority order 0, 1, 2 (paper: 'prioritise CurrentList')."""
        queues, size = self.v.queues, self.v.size
        c = self.current
        if c is not None:                    # 'current' is only kept while its queue still has packets
            q = queues[c]
            if self.deficit[c] >= size[q[0]]:
                self.deficit[c] -= size[q[0]]
                if len(q) == 1:
                    self.deficit[c] = 0.0
                    self.current = None
                    self.cursor = (c + 1) % K
                return c
            self.current = None
            self.cursor = (c + 1) % K
        if not any(queues):
            raise RuntimeError("CQDRR select() with empty buffer")
        deficit, Q = self.deficit, self.Q
        c = self.cursor
        visits, limit = 0, None
        while True:
            q = queues[c]
            if q:
                d = deficit[c] + Q[c]
                head = size[q[0]]
                if d >= head:
                    if len(q) == 1:
                        deficit[c] = 0.0
                        self.cursor = (c + 1) % K
                    else:
                        deficit[c] = d - head
                        self.current = c
                        self.cursor = c
                    return c
                deficit[c] = d
            else:
                deficit[c] = 0.0
            c = (c + 1) % K
            visits += 1
            if visits % K == 0:      # a full round without a send: skip the rounds in which none can send
                self._skip_empty_rounds()
            if visits >= 10_000:     # safety net only: every visit adds Q_c > 0, so a head becomes servable
                if limit is None:    # within ceil(largest head / smallest quantum) rounds; reaching this
                    limit = K * (int(max(size[x[0]] for x in queues if x) // min(Q)) + 2)   # means limit > 10 000
                if visits > limit:   # pragma: no cover  (unreachable by the bound)
                    raise RuntimeError("CQDRR select() found no servable class")

    def _skip_empty_rounds(self):
        """As DRR._skip_empty_passes, for CQDRR's fixed-order rounds: add r quanta to every non-empty class,
        r = (fewest rounds any class still needs) - 2 (empty classes keep deficit 0, as each visit sets it)."""
        queues, size, deficit, Q = self.v.queues, self.v.size, self.deficit, self.Q
        live = [c for c in range(K) if queues[c]]
        r = min(math.ceil((size[queues[c][0]] - deficit[c]) / Q[c]) for c in live) - 2
        if r >= SKIP_MIN:
            for c in live:
                deficit[c] += r * Q[c]

    def on_enqueue(self, c, now):
        pass   # fixed-order rounds: no active list needed

    def update(self, now):
        import math
        v, p = self.v, self.p
        C, dt = v.link_rate, v.update_interval
        tot = sum(self.Q)
        R = [C * q / tot for q in self.Q]
        g = p["rbar_gain"]
        U, D, W = [], [], []
        for c in range(K):
            self.rbar[c] = (1 - g) * self.rbar[c] + g * R[c]
            inst = 8.0 * (v.arrived_bytes[c] - self.last_arrived[c]) / dt
            self.last_arrived[c] = v.arrived_bytes[c]
            self.lam[c] = (1 - p["rate_ewma"]) * self.lam[c] + p["rate_ewma"] * inst
            U.append(alpha_fair(R[c] / self.rbar[c], p["alpha_fair"]))
            D.append(8.0 * (self.Q[c] + self.LMAX[c]) / R[c])
            W.append(mm1k_blocking(self.lam[c] / R[c], self.k_cap[c]))
        eta0 = -math.log(p["p_viol"]) / D_TARGET[0]
        h = eta0 * D[0]                                   # one TT class: mean over a single flow
        S, wgt = p["scale"], p["w"]
        q_tt = S * wgt * math.exp((eta0 * D[0] - h) / (1 + math.sqrt(h))) * U[0] + wgt * v.qbytes[0] * W[0]
        q_avb = S * (-wgt * math.log(D[1])) * U[1] + wgt * v.qbytes[1] * W[1]
        q_be = S * U[2]
        for c, q in enumerate((q_tt, q_avb, q_be)):
            self.Q[c] = min(p["qmax"], max(p["qmin"], q))


def _tri(x, a, b, c):
    if x < a or x > c:
        return 0.0
    if x == b:
        return 1.0
    if x < b:
        return (x - a) / (b - a)
    return (c - x) / (c - b)


def _memberships(x):
    return (
        1.0 if x <= 0 else _tri(x, 0.0, 0.0, 0.5) if x < 0.5 else 0.0,
        _tri(x, 0.0, 0.5, 1.0),
        1.0 if x >= 1 else _tri(x, 0.5, 1.0, 1.0) if x > 0.5 else 0.0,
    )


FUZZY_RULES = ((0.75, 1.0, 1.5),
               (1.0, 1.5, 2.5),
               (1.5, 2.5, 4.0))


class FuzzyDRR(_AdaptiveDRR):
    name = "FuzzyDRR"
    defaults = {"gain": 1.0, "delay_span": 2.0, "qmin": 300.0}

    def validate(self):
        self._num("gain", lo=0, hi=100)
        self._num("delay_span", lo=0, lo_open=True)
        self._num("qmin", lo=Q_LO, hi=Q_HI)

    def bind(self, view):
        self.p = {**self.p, "quanta": BASE_Q}
        super().bind(view)

    def multiplier(self, x, y):
        g = self.p["gain"]
        mx, my = _memberships(x), _memberships(y)
        num = den = 0.0
        for a in range(3):
            for b in range(3):
                w = mx[a] * my[b]
                if w:
                    num += w * (1.0 + g * (FUZZY_RULES[a][b] - 1.0))
                    den += w
        return num / den

    def update(self, now):
        v, p = self.v, self.p
        share = v.buffer_bytes / K
        for c in range(K):
            x = min(1.0, v.qbytes[c] / share)
            y = min(1.0, v.hol(c, now) / (p["delay_span"] * D_TARGET[c]))
            self.Q[c] = max(p["qmin"], BASE_Q[c] * self.multiplier(x, y))


class RevenueDRR(_AdaptiveDRR):
    name = "RevenueDRR"
    defaults = {"guar": (0.2, 0.3, 0.2), "tau": 0.1, "ewma": 0.1, "qmin": 150.0, "guar_scale": 1.0}

    def validate(self):
        self._vector("guar", positive=False)
        self._num("tau", lo=0, lo_open=True)
        self._num("ewma", lo=0, hi=1, lo_open=True)
        self._num("qmin", lo=Q_LO, hi=Q_HI)
        self._num("guar_scale", lo=0, hi=1e6)

    def bind(self, view):
        self.p = {**self.p, "quanta": BASE_Q}
        super().bind(view)
        self.R = [0.0] * K
        self.last_arrived = [0] * K
        self.order = sorted(range(K), key=lambda c: -PRICE[c])

    def update(self, now):
        v, p = self.v, self.p
        C = v.link_rate
        dt = v.update_interval
        a = p["ewma"]
        demand = []
        for c in range(K):
            inst = 8.0 * (v.arrived_bytes[c] - self.last_arrived[c]) / dt
            self.last_arrived[c] = v.arrived_bytes[c]
            self.R[c] = (1 - a) * self.R[c] + a * inst
            demand.append(self.R[c] + 8.0 * v.qbytes[c] / p["tau"])
        alloc = [min(demand[c], p["guar_scale"] * p["guar"][c] * C) for c in range(K)]
        spare = C - sum(alloc)
        for c in self.order:
            if spare <= 0:
                break
            give = min(spare, demand[c] - alloc[c])
            if give > 0:
                alloc[c] += give
                spare -= give
        if spare > 0:
            for c in range(K):
                alloc[c] += spare / K
        for c in range(K):
            self.Q[c] = min(FRAME, max(p["qmin"], FRAME * alloc[c] / C))


class SQDRRBacklog(SQDRR):
    """E14 ablation: DR-DRR whose delay estimate uses the predicted drain time of the backlog only."""
    name = "DR-DRR-backlog"

    @staticmethod
    def _delay_estimate(hol, drain):
        return drain


class SQDRRHol(SQDRR):
    """E14 ablation: DR-DRR whose delay estimate uses the head-of-line waiting time only."""
    name = "DR-DRR-hol"

    @staticmethod
    def _delay_estimate(hol, drain):
        return hol


class SQDRRDamped(SQDRR):
    """DR-DRR with quanta smoothing λ = 0.5 (E9 finding, confirmed on dev seeds; protocol section E1D)."""
    name = "DR-DRR+damping"
    defaults = {**SQDRR.defaults, "smooth": 0.5}


class SCRR(Scheduler):
    """Self-Clocked Round-Robin with enhancements (Sharafzadeh et al., NSDI 2025, Appendix A,
    Algorithms 3-4: No Packet Metadata, Sparse Flow Optimization, Initial Advance, No Empty).

    Parameter-free; unweighted. Each traffic class is one sub-queue. Virtual times are in bytes.
    Our reading where the pseudo-code is implicit: nq = number of sub-queues in the schedule;
    a sub-queue leaves the schedule when it empties (the paper's 'keep newly empty sub-queues one
    more round' refinement of SFO is not in Algorithm 4 and is not modelled); global-clock updates
    take max(old, new) because the paper states the clock "can only go forward" (Appendix A.1)
    while Algorithm 4's idle-reset line can otherwise move it back after Initial Advance.
    """
    name = "SCRR"
    any_k = True

    def bind(self, view):
        super().bind(view)
        self.new_q, self.old_q = deque(), deque()
        self.in_sched = [False] * self.k
        self.clock = [0.0] * self.k
        self.virtual_clock = 0.0
        self.virtual_previous = 0.0
        self.virtual_dequeue = 0.0
        self.rounds = 0
        self.nq = 0
        self.np_ = 0

    def on_enqueue(self, c, now):
        self.np_ += 1
        if not self.in_sched[c]:
            self.in_sched[c] = True
            if self.clock[c] <= self.virtual_clock or self.nq == 0:     # No Empty -> SFO list
                self.new_q.append(c)
                self.rounds += 1
            else:
                self.old_q.append(c)
            self.nq += 1

    def select(self, now):
        lst = self.new_q if self.new_q else self.old_q
        c = lst[0]
        q = self.v.queues[c]
        length = float(self.v.size[q[0]])
        empty_after = len(q) == 1
        self.np_ -= 1
        if self.clock[c] < self.virtual_previous:                        # No Packet Metadata
            v_pkt = self.virtual_previous + length                       # Initial Advance
        else:
            v_pkt = self.clock[c]
        v_next = v_pkt + length
        self.clock[c] = v_next
        if self.np_ == 0:                                                 # global clock advance
            self.virtual_dequeue = v_pkt + length
            self.virtual_previous = self.virtual_clock
            self.virtual_clock = max(self.virtual_clock, self.virtual_dequeue)   # "clock can only go forward" (§A.1)
        elif v_pkt > self.virtual_dequeue:
            self.virtual_dequeue = v_pkt
        if v_next > self.virtual_clock or empty_after:                   # sub-queue round robin
            if self.rounds <= 0:
                self.virtual_previous = self.virtual_clock
                self.virtual_clock = max(self.virtual_clock, self.virtual_dequeue)
                self.rounds = self.nq
            self.rounds -= 1
            lst.popleft()
            if not empty_after:
                self.old_q.append(c)
            else:
                self.in_sched[c] = False
                self.nq -= 1
        return c


class MDRRStrict(DRR):
    """Modified DRR in its strict-priority (low-latency) mode, as router vendors describe it (our reconstruction; E20).
    Class 0 is the low-latency queue and is served first whenever it is backlogged; classes 1..K-1 share the link by DRR.
    Work-conserving and not rate-limited, so the low-latency queue can starve the others."""
    name = "MDRR-SP"
    any_k = False

    def on_enqueue(self, c, now):
        if c != 0:
            super().on_enqueue(c, now)

    def select(self, now):
        if self.v.queues[0]:
            return 0
        if any(self.v.queues[c] for c in range(1, self.k)):
            return super().select(now)
        return None


class MDRRAlternate(MDRRStrict):
    """Modified DRR in its alternate-priority mode (our reconstruction; E20): packets alternate between the low-latency
    queue (class 0) and the DRR classes. A side with nothing queued is skipped."""
    name = "MDRR-ALT"

    def bind(self, view):
        super().bind(view)
        self.last_low = False

    def select(self, now):
        others = any(self.v.queues[c] for c in range(1, self.k))
        if self.v.queues[0] and (not self.last_low or not others):
            self.last_low = True
            return 0
        if others:
            self.last_low = False
            return DRR.select(self, now)
        return None


class MDRRAlternateVisit(MDRRStrict):
    """Modified DRR, alternate-priority mode read at the level of turns (post-hoc variant, E20b): the low-latency queue (class 0)
    takes one DRR turn (its own quantum, 1500 B) between consecutive turns of the other classes, instead of one packet.
    Added after E20 showed that per-packet alternation starves small latency packets of bytes; not pre-registered."""
    name = "MDRR-ALT-V"
    defaults = {"quanta": BASE_Q}

    def bind(self, view):
        super().bind(view)
        self.d0 = 0.0
        self.low_active = False     # a turn of the low-latency queue is in progress
        self.low_next = True        # the low-latency queue takes the next turn
        self.served_rest = False    # the last packet came from the DRR classes

    def select(self, now):
        queues, size = self.v.queues, self.v.size
        q0 = queues[0]
        rest = any(queues[c] for c in range(1, self.k))
        if self.low_active:                                   # continue the low-latency turn
            if q0 and self.d0 >= size[q0[0]]:
                self.d0 -= size[q0[0]]
                if len(q0) == 1:
                    self.d0, self.low_active = 0.0, False
                return 0
            self.low_active = False
            if not q0:
                self.d0 = 0.0
        c = self.current
        if c is not None and self.deficit[c] >= size[queues[c][0]]:
            self.served_rest = True
            return DRR.select(self, now)                      # the DRR turn in progress continues
        if self.served_rest:                                  # a DRR turn just ended
            self.served_rest, self.low_next = False, True
        if q0 and (self.low_next or not rest):
            self.low_next = False
            self.d0 += self.Q[0]
            if not rest and self.d0 < size[q0[0]]:            # nothing else to serve: take the missing quanta at once
                self.d0 += math.ceil((size[q0[0]] - self.d0) / self.Q[0]) * self.Q[0]
            if self.d0 >= size[q0[0]]:
                self.d0 -= size[q0[0]]
                if len(q0) == 1:
                    self.d0 = 0.0
                else:
                    self.low_active = True
                return 0
        if rest:
            self.served_rest = True
            return DRR.select(self, now)
        return None


MAIN = (FIFO, StrictPriority, DRR, RLSPDRR, SQDRR, CQDRR, FuzzyDRR, RevenueDRR)
REGISTRY = {cls.name: cls for cls in MAIN + (SQDRRDamped, CQDRRVariant, SCRR, DRREndOfService, SQDRRBacklog, SQDRRHol, MDRRStrict, MDRRAlternate, MDRRAlternateVisit, SQDRRStatic)}
SCHEDULERS = [cls.name for cls in MAIN]   # the 8 compared schedulers; variants are run separately
ADAPTIVE = [c.name for c in MAIN if c.adaptive]


def make(name: str, k: int | None = None, **params) -> Scheduler:
    """k = number of traffic classes; None = the study's 3. Only FIFO, SP, DRR, DRR-EOS and SCRR accept others."""
    return REGISTRY[name](k=k, **params)
