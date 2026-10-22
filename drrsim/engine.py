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

    def __init__(self, arr_t, size, link_rate, buffer_bytes, update_interval):
        self.arr_t = arr_t
        self.size = size
        self.link_rate = link_rate
        self.buffer_bytes = buffer_bytes
        self.update_interval = update_interval
        self.queues = [deque() for _ in range(K)]
        self.qbytes = [0] * K
        self.arrived_bytes = [0] * K     # cumulative offered bytes (incl. dropped)

    def hol(self, c: int, now: float) -> float:
        q = self.queues[c]
        return now - self.arr_t[q[0]] if q else 0.0


@dataclass
class RunLog:
    start: np.ndarray        # service start per packet (nan if dropped / pending)
    end: np.ndarray          # service end per packet
    dropped: np.ndarray      # bool
    q_times: np.ndarray      # update instants (adaptive only)
    q_values: np.ndarray     # (n_updates, K) quanta after each update
    decisions: int
    wall_time: float
    pending: int


def simulate(trace: Trace, scheduler, cfg: SimConfig) -> RunLog:
    trace.validate(K)
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
    part = buffer_bytes // K

    view = View(arr_t, size, tc.link_rate, buffer_bytes, cfg.update_interval)
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
    busy = False
    t_free = 0.0
    decisions = 0
    i = 0
    now = 0.0
    # hot-loop locals (bound after bind(), so per-instance overrides are honoured)
    select, on_enqueue, update, quanta = scheduler.select, scheduler.on_enqueue, scheduler.update, scheduler.quanta
    drain, horizon = cfg.drain, tc.horizon
    rate_factor = cfg.rate_factor if cfg.capacity else None      # time-varying link (E11); None = constant
    wall0 = time.perf_counter()

    while True:
        ta = arr_t[i] if i < n else INF
        if not busy and total == 0 and ta == INF:
            break
        tcmp = t_free if busy else INF
        if not drain and min(ta, tcmp, next_upd, t_wake) > horizon:
            break
        if busy and tcmp <= ta and tcmp <= next_upd and tcmp <= t_wake:
            now = tcmp
            busy = False
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
            if (qbytes[c] + s > part) if partitioned else (total + s > buffer_bytes):
                dropped[i] = 1
            else:
                queues[c].append(i)
                qbytes[c] += s
                total += s
                on_enqueue(c, now)
            i += 1
        if not busy and total > 0:
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
            end[j] = t_free
            busy = True
            decisions += 1

    wall = time.perf_counter() - wall0
    pending = sum(len(q) for q in queues) + (n - i)
    return RunLog(
        start=np.array(start),
        end=np.array(end),
        dropped=np.frombuffer(bytes(dropped), dtype=np.uint8).astype(bool),
        q_times=np.array(q_times),
        q_values=np.array(q_values, dtype=float).reshape(-1, K),
        decisions=decisions,
        wall_time=wall,
        pending=pending,
    )
