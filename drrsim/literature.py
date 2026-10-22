"""Published examples re-created in the simulator (experiment E13).

Sources, setups and pass criteria are pre-registered in docs/EXPERIMENT_PROTOCOL.md (section E13).
Every function here only builds inputs or measures outputs; scheduling is done by the normal engine.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from .config import SimConfig, TrafficConfig
from .engine import simulate
from .schedulers import SCRR, make
from .traffic import Trace

UNLIMITED = 10 ** 12      # bytes: a buffer that never fills in these benchmarks


def make_trace(times, classes, sizes) -> Trace:
    """Sorted Trace from unsorted per-packet lists (ties broken by class index, as the engine expects)."""
    t = np.asarray(times, dtype=float)
    c = np.asarray(classes, dtype=np.int16)
    s = np.asarray(sizes, dtype=np.int32)
    o = np.lexsort((c, t))
    return Trace(t[o], c[o], s[o])


def config(link_rate, buffer_bytes=UNLIMITED, policy="shared", horizon=1.0) -> SimConfig:
    return SimConfig(traffic=TrafficConfig(link_rate=link_rate, warmup=0.0, duration=horizon),
                     buffer_bytes=buffer_bytes, buffer_policy=policy)


def run(trace, cfg, scheduler, k, **params):
    """Simulate; return the log. Delay of packet j = log.end[j] - trace.t[j] (arrival to last bit out)."""
    log = simulate(trace, make(scheduler, k=k, **params), cfg)
    return log


# ---------------------------------------------------------------- token buckets
def token_bucket_times(rng, r_Bps, b, size, start, horizon, idle_p=0.0, idle_mean=0.0, n_max=None):
    """Packet arrival times of one flow that conforms to the token bucket (rate r_Bps bytes/s, burst b bytes):
    greedy (send as soon as tokens allow) except that, before each packet, with probability idle_p the source
    stays silent for an Exp(idle_mean) time (tokens accumulate, capped at b). Packets of `size` bytes arrive
    instantaneously. idle_p = 0 gives the greedy source of network calculus."""
    if size > b:
        raise ValueError("packet larger than the bucket can never be sent")
    t, tokens, out = start, float(b), []
    while t <= horizon and (n_max is None or len(out) < n_max):
        if idle_p > 0 and rng.random() < idle_p:
            gap = rng.exponential(idle_mean)
            t += gap
            tokens = min(float(b), tokens + r_Bps * gap)
        if tokens < size:
            t += (size - tokens) / r_Bps
            tokens = float(size)
        if t > horizon:
            break
        out.append(t)
        tokens -= size
    return out


def conforms(times, sizes, r_Bps, b, tol=1e-6) -> bool:
    """True if the cumulative arrivals satisfy A(s, t] <= b + r (t - s) for all s <= t (packets instantaneous)."""
    tokens, last = float(b), None
    for t, s in zip(times, sizes):
        if last is not None:
            tokens = min(float(b), tokens + r_Bps * (t - last))
        last = t
        tokens -= s
        if tokens < -tol:
            return False
    return True


# ---------------------------------------------------------------- network-calculus bound
def boyer_bound(i, quanta, lmax, burst, rate_Bps, link_Bps, eps=1):
    """Delay bound (s) of flow i under DRR from the strict service curve of Boyer et al. (2012), as restated by
    Tabatabaee & Le Boudec (2022, Sec. 2.3): rate R_i = c Q_i / Q_tot, latency
    T_i = [sum_{j!=i} d_j + (1 + d_i / Q_i) sum_{j!=i} Q_j] / c with d_j = lmax_j - eps (eps = 1 byte here).
    For a token-bucket flow (rate r_i <= R_i, burst b_i) the bound is T_i + b_i / R_i. All sizes in bytes."""
    d = [l - eps for l in lmax]
    others = [j for j in range(len(quanta)) if j != i]
    R = link_Bps * quanta[i] / sum(quanta)
    if rate_Bps > R:
        raise ValueError("flow rate above its DRR guaranteed rate: no finite bound")
    T = (sum(d[j] for j in others) + (1 + d[i] / quanta[i]) * sum(quanta[j] for j in others)) / link_Bps
    return T + burst / R


# ---------------------------------------------------------------- B1
B1 = {"source": "Tabatabaee & Le Boudec, IEEE/ACM ToN 2022, Sec. 3 (arXiv:2106.01034)",
      "l": 100, "c": 100e6, "quanta": (10_000.0, 500.0, 1_000.0),
      "r": (0.86, 0.0401), "published_us": 119.256, "boyer_us": 146.228, "soni_us": 112.172}


def b1_trace(eps=1e-10):
    """The paper's trajectory: flow 3 has 20 packets at t=0; flow 1 (63 packets, rate 0.86c) and flow 2
    (4 packets, rate 0.0401c) start 'shortly after' (eps, 2 eps). Flows 1-3 are classes 0-2.
    Returns (trace, index of the packet of interest = flow 1's 63rd packet)."""
    l, c = B1["l"], B1["c"]
    tau = l * 8 / c
    times = [0.0] * 20 + [eps + k * tau / B1["r"][0] for k in range(63)] + [2 * eps + k * tau / B1["r"][1] for k in range(4)]
    classes = [2] * 20 + [0] * 63 + [1] * 4
    tr = make_trace(times, classes, [l] * len(times))
    poi = int(np.flatnonzero(tr.cls == 0)[-1])
    return tr, poi


def b1_run(scheduler="DRR-EOS"):
    tr, poi = b1_trace()
    log = run(tr, config(B1["c"]), scheduler, 3, quanta=B1["quanta"])
    return (log.end[poi] - tr.t[poi]) * 1e6


def b1_random_max(rng, trials, scheduler="DRR-EOS"):
    """Largest flow-1 delay (µs) over random token-bucket-constrained inputs of the B1 system
    (flow 3 at rate 0.08c < Q3/Qtot c, burst 20 l, as allowed by the paper's constraint on r3)."""
    l, c = B1["l"], B1["c"]
    Bps = c / 8
    spec = [(0.86 * Bps, l), (0.0401 * Bps, l), (0.08 * Bps, 20 * l)]
    worst = 0.0
    for _ in range(trials):
        times, classes = [], []
        for k, (r, b) in enumerate(spec):
            ts = token_bucket_times(rng, r, b, l, start=rng.uniform(0, 30 * l / Bps), horizon=400 * l / Bps,
                                    idle_p=rng.choice([0.0, 0.05, 0.3]), idle_mean=rng.uniform(1, 20) * l / Bps)
            times += ts
            classes += [k] * len(ts)
        tr = make_trace(times, classes, [l] * len(times))
        log = run(tr, config(c), scheduler, 3, quanta=B1["quanta"])
        d = (log.end - tr.t)[tr.cls == 0]
        worst = max(worst, float(d.max()) * 1e6)
    return worst


# ---------------------------------------------------------------- B2
B2 = {"source": "Tabatabaee & Le Boudec 2022, Sec. 6.1 / Table 1 (Bouillard's single-server example)",
      "c": 5e9, "quantum": 2_000.0,                                     # 16 000 bit
      "names": ("electric protection", "VR games", "video conference", "4k video"),
      "l": (380, 1500, 1500, 1500),                                     # 3.04 kb, 12 kb
      "b": (5_320, 270_000, 405_000, 900_000),                          # 42.56, 2160, 3240, 7200 kb
      "r_bps": (8.521e6, 180e6, 162e6, 180e6),
      "bound_s": (44.51e-6, 1.32e-3, 1.81e-3, 2.72e-3),                 # best published bounds (Thm 5)
      "boyer_s": (52e-6, 1.75e-3, 2.61e-3, 5.78e-3)}


def b2_trial(rng, mode):
    """One input pattern; returns per-class maximum delay (s) under DRR-EOS and DRR.
    mode 'greedy': every class greedy from t=0 (random tie order via tiny offsets);
    mode 'offset': greedy with random start offsets up to 1 ms;  mode 'random': random silences too."""
    times, classes, sizes = [], [], []
    for k in range(4):
        r, b, l = B2["r_bps"][k] / 8, B2["b"][k], B2["l"][k]
        if mode == "greedy":
            start, idle_p = rng.uniform(0, 1e-9), 0.0
        elif mode == "offset":
            start, idle_p = rng.uniform(0, 1e-3), 0.0
        else:
            start, idle_p = rng.uniform(0, 1e-3), rng.choice([0.01, 0.1, 0.3])
        ts = token_bucket_times(rng, r, b, l, start=start, horizon=6e-3, idle_p=idle_p,
                                idle_mean=rng.uniform(0.01, 1.0) * b / r)
        times += ts
        classes += [k] * len(ts)
        sizes += [l] * len(ts)
    tr = make_trace(times, classes, sizes)
    out = {}
    for sch in ("DRR-EOS", "DRR"):
        log = run(tr, config(B2["c"]), sch, 4, quanta=(B2["quantum"],) * 4)
        d = log.end - tr.t
        out[sch] = [float(d[tr.cls == k].max()) if np.any(tr.cls == k) else 0.0 for k in range(4)]
    return out


# ---------------------------------------------------------------- B3
B3 = {"source": "Shreedhar & Varghese, IEEE/ACM ToN 1996 (SIGCOMM '95), Sec. 5.1-5.3, Figs. 7 and 9",
      "flows": 20, "rate_pps": 10.0, "bad_flow": 9, "bad_rate_pps": 30.0,   # flow 10 = index 9
      "max_bytes": 562, "small_bytes": 13,                                  # 4500 bit, 100 bit (rounded up)
      "link_bps": 400e3, "duration": 2000.0,                                # link rate assumed (not given)
      "published_dev": {"random": 0.004699, "constant": 0.003, "bimodal": 0.0032}}


def b3_trace(seed, sizes="random"):
    rng = np.random.default_rng([seed, 1996])
    times, classes, szs = [], [], []
    for f in range(B3["flows"]):
        lam = B3["bad_rate_pps"] if f == B3["bad_flow"] else B3["rate_pps"]
        n = rng.poisson(lam * B3["duration"])
        ts = np.sort(rng.uniform(0, B3["duration"], n))
        if sizes == "random":
            s = rng.integers(1, B3["max_bytes"] + 1, n)
        elif sizes == "constant":
            s = np.full(n, B3["small_bytes"])
        elif sizes == "bimodal":
            s = rng.choice([B3["small_bytes"], B3["max_bytes"]], n)
        else:
            raise ValueError(sizes)
        times.append(ts)
        classes.append(np.full(n, f))
        szs.append(s)
    return make_trace(np.concatenate(times), np.concatenate(classes), np.concatenate(szs))


def b3_offered_bps(sizes):
    mean = {"random": (1 + B3["max_bytes"]) / 2, "constant": B3["small_bytes"],
            "bimodal": (B3["small_bytes"] + B3["max_bytes"]) / 2}[sizes]
    return (19 * B3["rate_pps"] + B3["bad_rate_pps"]) * mean * 8


def b3_throughput(seed, scheduler, sizes="random", buffer_bytes=UNLIMITED, policy="shared", scaled=False):
    """Per-flow delivered bits/s within the 2000 s interval. scaled=True sets the link so that the offered load is
    the same overload as with random sizes (post hoc: with 13 B packets a 400 kb/s link is never congested)."""
    tr = b3_trace(seed, sizes)
    link = B3["link_bps"] * b3_offered_bps(sizes) / b3_offered_bps("random") if scaled else B3["link_bps"]
    params = {"quanta": (float(B3["max_bytes"]),) * B3["flows"]} if scheduler in ("DRR", "DRR-EOS") else {}
    log = run(tr, config(link, buffer_bytes, policy, B3["duration"]), scheduler, B3["flows"], **params)
    ok = (~log.dropped) & (log.end <= B3["duration"])
    bits = np.bincount(tr.cls[ok], weights=tr.size[ok] * 8.0, minlength=B3["flows"])
    return bits / B3["duration"]


# ---------------------------------------------------------------- B4
B4 = {"source": "Tokmakov et al., IEEE CloudNet 2019 (arXiv:2002.07027), PROACTIVE scenario",
      "link_bps": 10e6, "hp_share": 0.6, "size": 1500, "N": 90.0, "published_hp_bps": 5.3e6}


def b4_trace(seed):
    """Classes 0/1/2 = high/medium/low priority UDP, each offered at the full link rate (saturating);
    high priority only during [N, 2N)."""
    rng = np.random.default_rng([seed, 2019])
    N, lam = B4["N"], B4["link_bps"] / 8 / B4["size"]
    times, classes = [], []
    for c, (t0, t1) in enumerate([(N, 2 * N), (0.0, 2 * N), (0.0, 2 * N)]):
        n = rng.poisson(lam * (t1 - t0))
        times.append(np.sort(rng.uniform(t0, t1, n)))
        classes.append(np.full(n, c))
    t = np.concatenate(times)
    return make_trace(t, np.concatenate(classes), np.full(len(t), B4["size"]))


def b4_throughput(seed, scheduler):
    """Per-class throughput (bit/s) while high priority is off [10, N) and on [N + 10, 2N)."""
    tr = b4_trace(seed)
    params = {"RL-SP+DRR": {"rate_frac": B4["hp_share"], "quanta": (1500.0,) * 3},
              "DRR": {"quanta": (1500.0,) * 3}}.get(scheduler, {})
    cfg = config(B4["link_bps"], 125_000, "partitioned", 2 * B4["N"])     # per-queue buffers, as in bmv2
    log = run(tr, cfg, scheduler, 3, **params)
    N = B4["N"]
    out = {}
    for name, (a, b) in {"off": (10.0, N), "on": (N + 10.0, 2 * N)}.items():
        ok = (~log.dropped) & (log.end >= a) & (log.end < b)
        out[name] = (np.bincount(tr.cls[ok], weights=tr.size[ok] * 8.0, minlength=3) / (b - a)).tolist()
    return out


# ---------------------------------------------------------------- B5
class _CountingDeque(deque):
    def popleft(self):
        self.pops += 1
        return super().popleft()


class SCRRRoundFirst(SCRR):
    """Diagnostic variant (added after B5's first result, see the E13 notes): identical to SCRR except that a
    finished round is closed BEFORE the next packet is dequeued. Algorithm 4 as printed closes it one dequeue
    later, after that packet has already raised virtual_dequeue, so the next round's first packet is folded
    into the previous round's clock advance. Not a compared scheduler and not registered."""
    name = "SCRR-round-first"
    any_k = True

    def bind(self, view):
        super().bind(view)
        self.round_over = False

    def select(self, now):
        if self.round_over:                                # close the finished round first
            self.virtual_previous = self.virtual_clock
            self.virtual_clock = max(self.virtual_clock, self.virtual_dequeue)
            self.rounds = self.nq
            self.round_over = False
        lst = self.new_q if self.new_q else self.old_q
        c = lst[0]
        q = self.v.queues[c]
        length = float(self.v.size[q[0]])
        empty_after = len(q) == 1
        self.np_ -= 1
        v_pkt = self.virtual_previous + length if self.clock[c] < self.virtual_previous else self.clock[c]
        v_next = v_pkt + length
        self.clock[c] = v_next
        if self.np_ == 0:
            self.virtual_dequeue = v_pkt + length
            self.virtual_previous = self.virtual_clock
            self.virtual_clock = max(self.virtual_clock, self.virtual_dequeue)
        elif v_pkt > self.virtual_dequeue:
            self.virtual_dequeue = v_pkt
        if v_next > self.virtual_clock or empty_after:
            self.rounds -= 1
            if self.rounds <= 0:
                self.round_over = True
            lst.popleft()
            if not empty_after:
                self.old_q.append(c)
            else:
                self.in_sched[c] = False
                self.nq -= 1
        return c


class _ProbeMixin:
    """Records the largest global-clock advance while packets remain queued (Theorem 1 of the paper), the
    largest advance when the last queued packet leaves (the system empties, no sub-queue is backlogged, so
    Theorem 1 does not apply; recorded separately), and the largest burst of one sub-queue visit (Theorem 2).
    Scheduling decisions are unchanged (tested)."""
    any_k = True

    def bind(self, view):
        super().bind(view)
        self.new_q, self.old_q = _CountingDeque(), _CountingDeque()
        self.new_q.pops = self.old_q.pops = 0
        self.max_advance = 0.0
        self.max_advance_empty = 0.0
        self.max_burst = 0
        self._visit, self._burst = None, 0

    def select(self, now):
        vc0, pops0 = self.virtual_clock, self.new_q.pops + self.old_q.pops
        c = super().select(now)
        s = self.v.size[self.v.queues[c][0]]
        if self.np_ == 0:
            self.max_advance_empty = max(self.max_advance_empty, self.virtual_clock - vc0)
        else:
            self.max_advance = max(self.max_advance, self.virtual_clock - vc0)
        self._burst = (self._burst if self._visit == c else 0) + s
        self._visit = c
        self.max_burst = max(self.max_burst, self._burst)
        if self.new_q.pops + self.old_q.pops > pops0:      # this sub-queue's visit ended
            self._visit, self._burst = None, 0
        return c


class SCRRProbe(_ProbeMixin, SCRR):
    name = "SCRR-probe"
    any_k = True


class SCRRRoundFirstProbe(_ProbeMixin, SCRRRoundFirst):
    name = "SCRR-round-first-probe"
    any_k = True


def b5_trial(rng, backlogged=True, probe=SCRRProbe):
    """Random flows (2-16), random packet-size mixes up to 9000 B.
    Returns (M, max round-boundary advance, max advance when emptying, max burst)."""
    n = int(rng.integers(2, 17))
    menu = rng.choice([64, 200, 576, 1000, 1500, 4000, 9000], size=int(rng.integers(1, 5)), replace=False)
    times, classes, sizes = [], [], []
    for f in range(n):
        m = int(rng.integers(5, 200))
        s = rng.choice(menu, m)
        ts = np.zeros(m) if backlogged else np.sort(rng.uniform(0, 0.05, m))
        times.append(ts)
        classes.append(np.full(m, f))
        sizes.append(s)
    tr = make_trace(np.concatenate(times), np.concatenate(classes), np.concatenate(sizes))
    p = probe(k=n)
    simulate(tr, p, config(10e6))
    return int(tr.size.max()), p.max_advance, p.max_advance_empty, p.max_burst
