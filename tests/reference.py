"""Independent reference implementations, written differently from drrsim on purpose.

- Event handling: a heap of (time, kind, seq) events instead of the engine's three-way comparison.
- DRR: the textbook "visit" formulation (pop the class off the active list, add its quantum once,
  serve while the deficit allows, then re-append or drop it), not drrsim's one-packet-per-call form.
Used only by tests/test_reference.py.
"""
import heapq
from collections import deque

import numpy as np

K = 3
COMPLETION, WAKE, ARRIVAL = 0, 1, 2          # processing order for equal timestamps


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
        if self.dep and self.dep[0] <= t + 1e-12:
            self.dep.popleft()
            return queues[0][0], None
        if queues[1] or queues[2]:
            return self.drr.next(t, queues, size)
        return None, (self.dep[0] if self.dep else None)


def ref_simulate(t, cls, size, link_rate, buffer_bytes, policy, sched):
    n = len(t)
    rate = link_rate / 8.0
    part = buffer_bytes // K
    if isinstance(sched, RefRLSP):
        sched.size = size
    start = np.full(n, np.nan)
    dropped = np.zeros(n, bool)
    queues = [deque() for _ in range(K)]
    qbytes = [0] * K
    ev = [(t[i], ARRIVAL, i) for i in range(n)]
    heapq.heapify(ev)
    seq = n
    busy = False
    wake_pending = None
    while ev:
        now, kind, x = heapq.heappop(ev)
        if kind == COMPLETION:
            busy = False
        elif kind == WAKE:
            if wake_pending != now:
                continue
            wake_pending = None
        else:
            i, c, s = x, cls[x], size[x]
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
                    heapq.heappush(ev, (wake, WAKE, seq))
                    seq += 1
                continue
            c = cls[i]
            assert queues[c][0] == i
            queues[c].popleft()
            qbytes[c] -= size[i]
            start[i] = now
            busy = True
            heapq.heappush(ev, (now + size[i] / rate, COMPLETION, seq))
            seq += 1
    return start, dropped
