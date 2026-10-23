"""Discrete-event simulator: one bottleneck link, per-class FIFO queues, shared byte buffer.

Buffer policy: "shared" = one byte pool, tail drop on the total; "partitioned" = each class
may queue at most buffer/K bytes.

A non-work-conserving scheduler may return None from select() and name a wake_time();
the link then stays idle until that time or the next event. A wake-up within TIE_EPS after an
arrival is processed first (at the arrival's time), consistent with the scheduler's eligibility test.

Event order at equal timestamps: link completion, then wake-up, then scheduler update, then arrivals
(arrivals in packet-id order). After every event, an idle link with a non-empty buffer
immediately starts the packet chosen by the scheduler.
"""
from __future__ import annotations

import random
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .config import K, SimConfig
from .traffic import Trace

INF = float("inf")
# Times within TIE_EPS are treated as simultaneous where float rounding would otherwise split an exact tie
# (shaped departure times vs. completion/arrival instants); order stays completion, wake, update, arrival.
TIE_EPS = 1e-12


class View:
    """What a scheduler may observe. Read-only by convention."""

    def __init__(self, arr_t, size, link_rate, buffer_bytes, update_interval, n_classes=K):
        self.arr_t = arr_t
        self.size = size
        self.link_rate = link_rate
        self.buffer_bytes = buffer_bytes
        self.update_interval = update_interval
        self.queues = [deque() for _ in range(n_classes)]
        self.qbytes = [0] * n_classes
        self.arrived_bytes = [0] * n_classes     # cumulative offered bytes (incl. dropped)
        self.t_free = 0.0                # end of the most recent service (in the past while the link is idle)

    def hol(self, c: int, now: float) -> float:
        q = self.queues[c]
        return now - self.arr_t[q[0]] if q else 0.0


@dataclass
class RunLog:
    start: np.ndarray        # service start per packet (nan if dropped / pending)
    end: np.ndarray          # service end per packet
    dropped: np.ndarray      # bool
    q_times: np.ndarray      # update instants (adaptive only)
    q_values: np.ndarray     # (n_updates, n_classes) quanta after each update
    decisions: int
    wall_time: float
    pending: int


def simulate(trace: Trace, scheduler, cfg: SimConfig) -> RunLog:
    k = getattr(scheduler, "k", K)       # number of traffic classes (3 except in the literature benchmarks)
    trace.validate(k)
    if scheduler.adaptive:
        span = max(cfg.traffic.horizon, float(trace.t[-1]) if len(trace) else 0.0)
        if span / cfg.update_interval > 5e7:
            raise ValueError(f"update_interval {cfg.update_interval} s would need {span / cfg.update_interval:.3g} "
                             "quantum updates (limit 5e7)")
    arr_t = trace.t.tolist()
    cls = trace.cls.tolist()
    size = trace.size.tolist()
    n = len(arr_t)
    tc = cfg.traffic
    rate_Bps = tc.link_rate / 8.0
    buffer_bytes = cfg.buffer_bytes
    partitioned = cfg.buffer_policy == "partitioned"
    red = cfg.buffer_policy == "red"
    if red:   # classic RED (Floyd & Jacobson 1993), queue measured in bytes, evaluated at each arrival
        red_min, red_max, red_maxp, red_wq = cfg.red
        red_avg, red_count, red_rng = 0.0, -1, random.Random(cfg.red_seed)
    part = buffer_bytes // k

    view = View(arr_t, size, tc.link_rate, buffer_bytes, cfg.update_interval, k)
    scheduler.bind(view)
    queues, qbytes, arrived = view.queues, view.qbytes, view.arrived_bytes

    start = [np.nan] * n
    end = [np.nan] * n
    dropped = bytearray(n)
    q_times, q_values = [], []

    upd = cfg.update_interval if scheduler.adaptive else INF
    next_upd = upd
    t_wake = INF          # set when a non-work-conserving scheduler leaves the link idle
    total = 0
    t_free = INF          # completion time of the packet on the link; INF while the link is idle
    decisions = 0
    i = 0
    now = 0.0
    # hot-loop locals (bound after bind(), so per-instance overrides are honoured)
    select, on_enqueue, update, quanta = scheduler.select, scheduler.on_enqueue, scheduler.update, scheduler.quanta
    drain, horizon = cfg.drain, tc.horizon
    rate_factor = cfg.rate_factor if cfg.capacity else None      # time-varying link (E11); None = constant
    arr_ext = arr_t + [INF]                                       # sentinel: no bounds check per event
    wall0 = time.perf_counter()

    while True:
        ta = arr_ext[i]
        if t_free == INF and total == 0 and ta == INF:
            break
        if not drain and min(ta, t_free, next_upd, t_wake) > horizon:
            break
        if t_free <= ta and t_free <= next_upd and t_free <= t_wake and t_free != INF:
            now = t_free
            t_free = INF
        elif t_wake <= ta + TIE_EPS and t_wake <= next_upd:
            now = t_wake if t_wake <= ta else ta     # a wake-up within TIE_EPS of an arrival goes first
            t_wake = INF
        elif next_upd <= ta:
            now = next_upd
            update(now)
            q_times.append(now)
            q_values.append(tuple(quanta()))
            next_upd += upd
        else:
            now = ta
            c = cls[i]
            s = size[i]
            arrived[c] += s
            if red:
                red_avg = (1 - red_wq) * red_avg + red_wq * total
                if total + s > buffer_bytes:                     # physical buffer full: tail drop
                    drop = True
                elif red_avg < red_min:
                    drop, red_count = False, -1
                elif red_avg >= red_max:
                    drop, red_count = True, 0
                else:
                    red_count += 1
                    pb = red_maxp * (red_avg - red_min) / (red_max - red_min)
                    pa = pb / (1 - red_count * pb) if red_count * pb < 1 else 1.0
                    drop = red_rng.random() < pa
                    if drop:
                        red_count = 0
            else:
                drop = (qbytes[c] + s > part) if partitioned else (total + s > buffer_bytes)
            if drop:
                dropped[i] = 1
            else:
                queues[c].append(i)
                qbytes[c] += s
                total += s
                on_enqueue(c, now)
            i += 1
        if t_free == INF and total > 0:
            c = select(now)
            if c is None:     # backlog exists but nothing is eligible yet
                t_wake = scheduler.wake_time()
                if not t_wake > now:
                    raise RuntimeError(f"{scheduler.name}: idle with backlog but no future wake time")
                continue
            t_wake = INF
            j = queues[c].popleft()
            s = size[j]
            qbytes[c] -= s
            total -= s
            start[j] = now
            t_free = now + s / rate_Bps if rate_factor is None else now + s / (rate_Bps * rate_factor(now))
            if t_free == INF:    # INF means "idle" in this loop: an overflowing completion time must never pass as one
                raise ValueError(f"completion time overflows (packet {j} of {s} B starting at {now} s)")
            end[j] = t_free
            view.t_free = t_free
            decisions += 1

    wall = time.perf_counter() - wall0
    pending = sum(len(q) for q in queues) + (n - i)
    return RunLog(
        start=np.array(start),
        end=np.array(end),
        dropped=np.frombuffer(bytes(dropped), dtype=np.uint8).astype(bool),
        q_times=np.array(q_times),
        q_values=np.array(q_values, dtype=float).reshape(-1, k),
        decisions=decisions,
        wall_time=wall,
        pending=pending,
    )
