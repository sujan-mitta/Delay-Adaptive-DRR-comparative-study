"""The eight schedulers, one interface. Rules are specified in docs/ALGORITHM_SPEC.md.

Interface: bind(view); on_enqueue(c, now); select(now) -> class with a non-empty queue;
update(now) (adaptive only, every update_interval); quanta() -> current per-class quanta.
"""
from __future__ import annotations

from collections import deque

from .config import CLASSES, K

BASE_Q = (1500.0, 1500.0, 1500.0)
FRAME = sum(BASE_Q)
D_TARGET = tuple(c.delay_target for c in CLASSES)
PRICE = tuple(c.price for c in CLASSES)


class Scheduler:
    name = "base"
    adaptive = False
    defaults: dict = {}

    def __init__(self, **params):
        unknown = set(params) - set(self.defaults)
        if unknown:
            raise ValueError(f"{self.name}: unknown parameters {sorted(unknown)}")
        self.p = {**self.defaults, **params}

    def bind(self, view):
        self.v = view

    def on_enqueue(self, c, now):
        pass

    def update(self, now):
        pass

    def quanta(self):
        return (float("nan"),) * K


class FIFO(Scheduler):
    name = "FIFO"

    def select(self, now):
        best, best_id = -1, None
        for c, q in enumerate(self.v.queues):
            if q and (best_id is None or q[0] < best_id):
                best, best_id = c, q[0]
        return best


class StrictPriority(Scheduler):
    name = "SP"

    def select(self, now):
        for c, q in enumerate(self.v.queues):
            if q:
                return c
        raise RuntimeError("select() called with empty buffer")


class DRR(Scheduler):
    name = "DRR"
    defaults = {"quanta": BASE_Q}

    def bind(self, view):
        super().bind(view)
        self.Q = [float(x) for x in self.p["quanta"]]
        self.deficit = [0.0] * K
        self.active = deque()
        self.in_active = [False] * K
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

    def _serve(self, c):
        q = self.v.queues[c]
        self.deficit[c] -= self.v.size[q[0]]
        if len(q) == 1:          # queue empties with this packet
            self._leave_front(c)
        else:
            self.current = c
        return c

    def select(self, now):
        queues, size = self.v.queues, self.v.size
        c = self.current
        if c is not None:
            q = queues[c]
            if q and self.deficit[c] >= size[q[0]]:
                return self._serve(c)
            self.current = None
            if q:
                self.active.rotate(-1)
            else:                # emptied by someone else (RL-SP bypass)
                self._leave_front(c)
        while self.active:
            c = self.active[0]
            q = queues[c]
            if not q:
                self._leave_front(c)
                continue
            self.deficit[c] += self.Q[c]
            if self.deficit[c] >= size[q[0]]:
                return self._serve(c)
            self.active.rotate(-1)
        raise RuntimeError("DRR select() with no backlogged class")


class RLSPDRR(DRR):
    """RL-SP-DRR, Algorithm 1 of Tokmakov et al. (CloudNet 2019, arXiv:2002.07027).

    Class 0 is the high-priority queue (HPQ). At enqueue each HPQ packet gets a departure time
    d = max(arrival, d_prev + size / r) (virtual-clock shaper at rate r); the HPQ head is sent
    once d <= now, otherwise it is held. DRR runs over classes 1..K-1 only. Not work-conserving.
    The max(arrival, .) clamp is our interpretation (the paper writes d = last_sent + size/r).
    """
    name = "RL-SP+DRR"
    defaults = {"quanta": BASE_Q, "rate_frac": 0.3}

    def bind(self, view):
        super().bind(view)
        if not self.p["rate_frac"] > 0:
            raise ValueError("RL-SP+DRR needs rate_frac > 0 (class 0 is only ever served by the shaper)")
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
        if self.dep and self.dep[0] <= now + 1e-12:
            self.dep.popleft()
            return 0
        if any(self.v.queues[c] for c in range(1, K)):
            return super().select(now)
        return None


class _AdaptiveDRR(DRR):
    adaptive = True


class SQDRR(_AdaptiveDRR):
    name = "DR-DRR"
    defaults = {"kappa": 4.0, "theta": 0.5, "qmax_mult": 8.0, "smooth": 1.0}

    def bind(self, view):
        self.p = {**self.p, "quanta": BASE_Q}
        super().bind(view)

    def update(self, now):
        v, p = self.v, self.p
        tot = sum(self.Q)
        for c in range(K):
            phi = self.Q[c] / tot
            drain = 8.0 * v.qbytes[c] / (v.link_rate * phi)
            risk = max(v.hol(c, now), drain) / D_TARGET[c]
            q = BASE_Q[c] * (1.0 + p["kappa"] * max(0.0, risk - p["theta"]))
            target = min(max(q, BASE_Q[c]), p["qmax_mult"] * BASE_Q[c])
            lam = p["smooth"]   # E9 damping ablation; 1 = rule as specified
            self.Q[c] = target if lam == 1.0 else (1 - lam) * self.Q[c] + lam * target


class CQDRRVariant(_AdaptiveDRR):
    """Our first-draft CQDRR reading (queue share x delay-requirement weight). Kept as a labelled
    variant outside the main 8 after the paper turned out to use a different rule (deviation 5)."""
    name = "CQDRR-draft"
    defaults = {"alpha": 1.0, "beta": 0.5, "qmin": 300.0, "smooth": 1.0}
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
        if c is not None:
            q = queues[c]
            if q and self.deficit[c] >= size[q[0]]:
                self.deficit[c] -= size[q[0]]
                if len(q) == 1:
                    self.deficit[c] = 0.0
                    self.current = None
                    self.cursor = (c + 1) % K
                return c
            if not q:
                self.deficit[c] = 0.0
            self.current = None
            self.cursor = (c + 1) % K
        for _ in range(64 * K):
            c = self.cursor
            q = queues[c]
            if not q:
                self.deficit[c] = 0.0
                self.cursor = (c + 1) % K
                continue
            self.deficit[c] += self.Q[c]
            if self.deficit[c] >= size[q[0]]:
                self.deficit[c] -= size[q[0]]
                if len(q) == 1:
                    self.deficit[c] = 0.0
                    self.cursor = (c + 1) % K
                else:
                    self.current = c
                return c
            self.cursor = (c + 1) % K
        raise RuntimeError("CQDRR select() found no servable class")

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
    more round' refinement of SFO is not in Algorithm 4 and is not modelled).
    """
    name = "SCRR"

    def bind(self, view):
        super().bind(view)
        self.new_q, self.old_q = deque(), deque()
        self.in_sched = [False] * K
        self.clock = [0.0] * K
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
            self.virtual_clock = self.virtual_dequeue
        elif v_pkt > self.virtual_dequeue:
            self.virtual_dequeue = v_pkt
        if v_next > self.virtual_clock or empty_after:                   # sub-queue round robin
            if self.rounds <= 0:
                self.virtual_previous = self.virtual_clock
                self.virtual_clock = self.virtual_dequeue
                self.rounds = self.nq
            self.rounds -= 1
            lst.popleft()
            if not empty_after:
                self.old_q.append(c)
            else:
                self.in_sched[c] = False
                self.nq -= 1
        return c


MAIN = (FIFO, StrictPriority, DRR, RLSPDRR, SQDRR, CQDRR, FuzzyDRR, RevenueDRR)
REGISTRY = {cls.name: cls for cls in MAIN + (SQDRRDamped, CQDRRVariant, SCRR)}
SCHEDULERS = [cls.name for cls in MAIN]   # the 8 compared schedulers; variants are run separately
ADAPTIVE = [c.name for c in MAIN if c.adaptive]


def make(name: str, **params) -> Scheduler:
    return REGISTRY[name](**params)
