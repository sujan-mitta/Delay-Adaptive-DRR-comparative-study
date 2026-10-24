"""Proposition 1 (docs/PROPOSITION.md) checked exhaustively on a small abstract model, independent of the simulator.

The model is DRR written from its definition. A class joins the tail of the active list with deficit 0 when a packet arrives at
its empty queue. A visit adds a quantum, chosen once at the start of the visit, to the carried deficit and sends head packets while
they fit. It ends when the head no longer fits (the class goes to the tail with the remainder) or the queue empties (the class
leaves, deficit 0). The link sends one byte per time unit, non-preemptively, and is work-conserving; arrivals up to the instant a
transmission ends are queued before the next decision. The quantum of EVERY visit is chosen adversarially: the search tries every
integer value in [Q0, M Q0] at every visit, which covers every quantum-update schedule.

Scope: 3 classes, Q0 = 2, M = 2 (quanta 2, 3, 4), packet sizes 1 or 2 (so Q0 >= every packet), arrivals at time 0 or 1, every
multiset of 1 to 4 packets (1,819 traces). A packet's head-of-line wait is the time from max(its arrival, end of service of its
predecessor in the class) to the start of its service; it must be at most G_i = sum over the other classes j that have traffic of
(M Q0 + L_j - 1). A negative control uses packets of size 7 > Q0 and shows the bound can then fail, so the check can fail.
"""
import itertools

K, Q0, M = 3, 2, 2
QUANTA = tuple(range(Q0, M * Q0 + 1))


def worst_wait(packets):
    """Largest head-of-line wait per class over every trace-fixed arrival pattern and every quantum schedule."""
    pk = sorted(packets)
    n = len(pk)
    worst = [0] * K

    def put(t, v, i, x):
        return t[:i] + (x,) + t[i + 1:]

    def admit(upto, nxt, queues, active, deficit, hs, last_end):
        while nxt < n and pk[nxt][0] <= upto:
            ta, c, _ = pk[nxt]
            if not queues[c]:
                active = active + (c,)
                deficit = put(deficit, K, c, 0)
                hs = put(hs, K, c, max(ta, last_end[c]))
            queues = put(queues, K, c, queues[c] + (nxt,))
            nxt += 1
        return nxt, queues, active, deficit, hs

    def decide(now, nxt, queues, active, deficit, cur, hs, last_end):
        nxt, queues, active, deficit, hs = admit(now, nxt, queues, active, deficit, hs, last_end)
        if not any(queues):
            if nxt >= n:
                return
            return decide(pk[nxt][0], nxt, queues, active, deficit, cur, hs, last_end)
        if cur is not None:
            if deficit[cur] >= pk[queues[cur][0]][2]:
                return send(now, nxt, queues, active, deficit, cur, hs, last_end)
            active = active + (cur,)                                    # visit over, queue non-empty: to the tail
            cur = None
        c, rest = active[0], active[1:]
        for q in QUANTA:                                                 # adversarial quantum for this visit
            d = deficit[c] + q
            dd = put(deficit, K, c, d)
            if d >= pk[queues[c][0]][2]:
                send(now, nxt, queues, rest, dd, c, hs, last_end)
            else:                                                       # head does not fit: class to the tail
                decide(now, nxt, queues, rest + (c,), dd, None, hs, last_end)

    def send(now, nxt, queues, active, deficit, c, hs, last_end):
        i = queues[c][0]
        s = pk[i][2]
        worst[c] = max(worst[c], now - hs[c])
        end = now + s
        deficit = put(deficit, K, c, deficit[c] - s)
        queues = put(queues, K, c, queues[c][1:])
        last_end = put(last_end, K, c, end)
        cur = c
        if queues[c]:
            hs = put(hs, K, c, end)
        else:                                                           # last packet taken: the class leaves
            deficit = put(deficit, K, c, 0)
            cur = None
        decide(end, nxt, queues, active, deficit, cur, hs, last_end)

    z = (0,) * K
    decide(0, 0, ((),) * K, (), z, None, z, z)
    return worst


def bound(packets, cls):
    lmax = {}
    for _, c, s in packets:
        lmax[c] = max(lmax.get(c, 0), s)
    return sum(M * Q0 + l - 1 for j, l in lmax.items() if j != cls)


def all_traces(sizes, times, nmax):
    cells = [(t, c, s) for t in times for c in range(K) for s in sizes]
    for n in range(1, nmax + 1):
        yield from itertools.combinations_with_replacement(cells, n)


def test_bound_holds_for_every_trace_and_every_quantum_schedule():
    checked, ratio = 0, 0.0
    for tr in all_traces(sizes=(1, 2), times=(0, 1), nmax=4):
        w = worst_wait(list(tr))
        for c in range(K):
            if any(p[1] == c for p in tr):
                b = bound(tr, c)
                assert w[c] <= b, (tr, c, w[c], b)
                if b:
                    ratio = max(ratio, w[c] / b)
        checked += 1
    assert checked == 1819
    assert ratio > 0.5            # not vacuous: some run waits more than half the bound


def test_the_model_reproduces_the_waits_it_should_on_hand_cases():
    # Two classes, one 2-byte packet each, both at t = 0: class 1 can wait at most the 2 bytes of class 0.
    w = worst_wait([(0, 0, 2), (0, 1, 2)])
    assert w[0] == 0 and w[1] == 2
    # A single class never waits.
    assert worst_wait([(0, 2, 1), (0, 2, 2), (1, 2, 1)]) == [0, 0, 0]


def test_negative_control_the_bound_can_fail_when_a_packet_exceeds_the_base_quantum():
    """A 7-byte packet with Q0 = 2 breaks Assumption A: its class needs four visits, so its wait can exceed the bound."""
    broke = False
    for tr in all_traces(sizes=(2, 7), times=(0,), nmax=4):
        w = worst_wait(list(tr))
        for c in range(K):
            if any(p[1] == c for p in tr) and w[c] > bound(tr, c):
                broke = True
    assert broke
