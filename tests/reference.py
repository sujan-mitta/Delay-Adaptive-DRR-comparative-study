"""Independent reference implementations, written differently from drrsim on purpose.

- Event handling: a heap of (time, kind, seq) events instead of the engine's three-way comparison.
- DRR: the textbook "visit" formulation (pop the class off the active list, add its quantum once,
  serve while the deficit allows, then re-append or drop it), not drrsim's one-packet-per-call form.
Used only by tests/test_reference.py.
"""
import heapq
import random
from collections import deque

import numpy as np

K = 3
COMPLETION, WAKE, ARRIVAL = 0, 1, 2          # processing order for equal timestamps
TIE_EPS = 1e-12                               # same tie tolerance as drrsim (written out, not imported)


class RefFIFO:
    def __init__(self):
        self.q = deque()

    def arrive(self, i, c, t):
        self.q.append(i)

    def next(self, t, queues, size):
        if not self.q:
            return None, None
        i = self.q.popleft()
        return i, None


class RefSP:
    def arrive(self, i, c, t):
        pass

    def next(self, t, queues, size):
        for c in range(K):
            if queues[c]:
                return queues[c][0], None
        return None, None


class RefDRR:
    def __init__(self, quanta, classes=(0, 1, 2)):
        self.Q = list(quanta)
        self.classes = set(classes)
        self.active = deque()
        self.deficit = [0.0] * K
        self.cur = None

    def arrive(self, i, c, t):
        if c in self.classes and c != self.cur and c not in self.active:
            self.deficit[c] = 0.0
            self.active.append(c)

    def next(self, t, queues, size):
        while True:
            if self.cur is None:
                if not self.active:
                    return None, None
                self.cur = self.active.popleft()
                self.deficit[self.cur] += self.Q[self.cur]
            c = self.cur
            q = queues[c]
            if q and self.deficit[c] >= size[q[0]]:
                self.deficit[c] -= size[q[0]]
                i = q[0]
                if len(q) == 1:                     # last packet: visit ends, class leaves the list
                    self.deficit[c] = 0.0
                    self.cur = None
                return i, None
            if q:
                self.active.append(c)
            else:
                self.deficit[c] = 0.0
            self.cur = None


class RefRLSP:
    """Class 0 shaped by departure times d = max(arrival, d_prev + size / r); DRR over classes 1, 2."""

    def __init__(self, rate_Bps, quanta):
        self.rate = rate_Bps
        self.drr = RefDRR(quanta, classes=(1, 2))
        self.dep = deque()
        self.last = -np.inf
        self.size = None

    def arrive(self, i, c, t):
        if c == 0:
            d = max(t, self.last + self.size[i] / self.rate)
            self.dep.append(d)
            self.last = d
        else:
            self.drr.arrive(i, c, t)

    def next(self, t, queues, size):
        if self.dep and self.dep[0] <= t + TIE_EPS:
            self.dep.popleft()
            return queues[0][0], None
        if queues[1] or queues[2]:
            return self.drr.next(t, queues, size)
        return None, (self.dep[0] if self.dep else None)


def ref_simulate(t, cls, size, link_rate, buffer_bytes, policy, sched, capacity=(), red=None, red_seed=0):
    """red: (min_th, max_th, max_p, w_q) when policy == "red" (classic RED, written out independently)."""
    n = len(t)
    avg, count, rng = 0.0, -1, random.Random(red_seed)
    rate = link_rate / 8.0
    part = buffer_bytes // K
    if isinstance(sched, RefRLSP):
        sched.size = size
    start = np.full(n, np.nan)
    dropped = np.zeros(n, bool)
    queues = [deque() for _ in range(K)]
    qbytes = [0] * K
    # events: (heap time, kind, seq, exact time). A wake-up is keyed TIE_EPS early so that it precedes any
    # arrival within TIE_EPS before it; it then fires at that arrival's time (or its own, if no such arrival).
    ev = [(t[i], ARRIVAL, i, t[i]) for i in range(n)]
    heapq.heapify(ev)
    seq = n
    busy = False
    wake_pending = None
    arrivals_done = 0
    while ev:
        key, kind, x, exact = heapq.heappop(ev)
        now = key
        if kind == COMPLETION:
            busy = False
        elif kind == WAKE:
            if wake_pending != exact:
                continue
            wake_pending = None
            ta = t[arrivals_done] if arrivals_done < n else np.inf
            now = ta if ta < exact else exact
        else:
            arrivals_done += 1
            i, c, s = x, cls[x], size[x]
            if policy == "red":
                lo, hi, maxp, wq = red
                q = sum(qbytes)
                avg = avg * (1 - wq) + wq * q
                if q + s > buffer_bytes:
                    full = True
                elif avg < lo:
                    full, count = False, -1
                elif avg >= hi:
                    full, count = True, 0
                else:
                    count += 1
                    pb = maxp * (avg - lo) / (hi - lo)
                    full = rng.random() < (pb / (1 - count * pb) if count * pb < 1 else 1.0)
                    if full:
                        count = 0
            else:
                full = (qbytes[c] + s > part) if policy == "partitioned" else (sum(qbytes) + s > buffer_bytes)
            if full:
                dropped[i] = True
            else:
                queues[c].append(i)
                qbytes[c] += s
                sched.arrive(i, c, now)
        if not busy and any(queues):
            i, wake = sched.next(now, queues, size)
            if i is None:
                if wake is not None and wake_pending != wake:
                    wake_pending = wake
                    heapq.heappush(ev, (wake - TIE_EPS, WAKE, seq, wake))
                    seq += 1
                continue
            c = cls[i]
            assert queues[c][0] == i
            queues[c].popleft()
            qbytes[c] -= size[i]
            start[i] = now
            busy = True
            f = 1.0
            for t0, t1, factor in capacity:              # rate in force when transmission starts
                if t0 <= now < t1:
                    f = factor
            heapq.heappush(ev, (now + size[i] / (rate * f) if capacity else now + size[i] / rate, COMPLETION, seq, None))
            seq += 1
    return start, dropped
