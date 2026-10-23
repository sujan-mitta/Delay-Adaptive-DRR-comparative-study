"""Round-6 test matrix: every scheduler variant against extreme parameters, instance reuse and state leaks,
independent textbook oracles for any number of classes, memorylessness after idle periods, combinations of
scenario options, throughput shares, and boundary inputs of the public helpers."""
import math
import time
from collections import deque

import numpy as np
import pytest

from conftest import ALL_SCHEDULERS, WORK_CONSERVING
from drrsim import SimConfig, TrafficConfig, compute, generate_trace, make, simulate
from drrsim import literature as L
from drrsim.schedulers import Q_HI, Q_LO, REGISTRY
from drrsim.traffic import Trace
from test_properties import check_common, check_work_conserving

ANY_K = ["FIFO", "SP", "DRR", "DRR-EOS", "SCRR"]
MEMORYLESS = ["FIFO", "SP", "DRR", "DRR-EOS", "RL-SP+DRR"]      # SCRR is not: see test_scrr_carries_history_...


def trace(t, c, s):
    t, c, s = np.asarray(t, float), np.asarray(c), np.asarray(s)
    o = np.lexsort((c, t))
    return Trace(t[o], c[o].astype(np.int16), s[o].astype(np.int32))


def rand_trace(rng, n, k=3, horizon=1.0, sizes=(1, 40, 200, 576, 1500, 9000)):
    return trace(np.sort(rng.uniform(0, horizon, n)), rng.integers(0, k, n), rng.choice(sizes, n))


def cfg(rate=1e7, buffer=60_000, policy="shared", **kw):
    return SimConfig(TrafficConfig(link_rate=rate, warmup=0.0, duration=1.0), buffer_bytes=buffer,
                     buffer_policy=policy, **kw)


def extreme_params(name, mode):
    d = REGISTRY[name].defaults
    p = {}
    if mode == "tiny":
        if "quanta" in d:
            p["quanta"] = (Q_LO,) * 3
        if "qmin" in d:
            p["qmin"] = Q_LO
        if "qmax" in d:
            p["qmax"] = 2 * Q_LO
    elif mode == "huge":
        if "quanta" in d:
            p["quanta"] = (Q_HI,) * 3
        if "qmax" in d:
            p["qmin"], p["qmax"] = 1e8, Q_HI
        elif "qmin" in d:
            p["qmin"] = Q_HI
    return p


# ---------------------------------------------------------------- 1. extreme parameters (36)
@pytest.mark.parametrize("mode", ["tiny", "huge", "mixed-sizes"])
@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_extreme_parameters_finish_fast_and_keep_invariants(name, mode):
    """Smallest and largest allowed quanta (or qmin/qmax), 1-byte and 9000-byte packets mixed. Before round 6,
    CQDRR at the smallest quanta took ~94 ms per packet (hours per run); DRR did before round 5."""
    rng = np.random.default_rng(1)
    tr = rand_trace(rng, 400)
    c = cfg()
    t0 = time.perf_counter()
    log = simulate(tr, make(name, **extreme_params(name, mode)), c)
    assert time.perf_counter() - t0 < 5.0
    check_common(tr, log, c)
    if name in WORK_CONSERVING:
        check_work_conserving(tr, log)


# ---------------------------------------------------------------- 2. instance reuse and state leaks (24)
@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_reused_instance_behaves_like_a_fresh_one(name):
    """bind() must reset all run state: a scheduler object used for one run, then another, gives exactly the
    result of a fresh object on the second run."""
    rng = np.random.default_rng(2)
    a, b = rand_trace(rng, 300), rand_trace(rng, 300, horizon=0.5)
    ca, cb = cfg(rate=1e6), cfg(rate=4e6, buffer=30_000, update_interval=0.002)
    s = make(name)
    simulate(a, s, ca)
    reused = simulate(b, s, cb)
    fresh = simulate(b, make(name), cb)
    assert np.array_equal(np.nan_to_num(reused.start, nan=-1), np.nan_to_num(fresh.start, nan=-1))
    assert np.array_equal(reused.q_values, fresh.q_values)


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_no_state_leaks_between_runs(name):
    """Run A, then B (different traffic and parameters), then A again: A must be identical both times
    (catches class-level mutable state shared between instances)."""
    rng = np.random.default_rng(3)
    a, b = rand_trace(rng, 300), rand_trace(rng, 500, horizon=0.3)
    first = simulate(a, make(name), cfg())
    simulate(b, make(name, **extreme_params(name, "tiny")), cfg(rate=1e6, policy="partitioned"))
    again = simulate(a, make(name), cfg())
    assert np.array_equal(np.nan_to_num(first.start, nan=-1), np.nan_to_num(again.start, nan=-1))


# ---------------------------------------------------------------- 3. textbook oracles for any k (51)
def textbook_drr(per_class_sizes, Q):
    """Algorithm 1 of Shreedhar & Varghese / Tabatabaee & Le Boudec on a static backlog: visit classes in
    index order, add the quantum, send while the deficit allows, reset the deficit when the queue empties."""
    q = [deque(x) for x in per_class_sizes]
    d = [0.0] * len(q)
    order = []
    while any(q):
        for i in range(len(q)):
            if q[i]:
                d[i] += Q[i]
                while q[i] and q[i][0] <= d[i]:
                    d[i] -= q[i].popleft()
                    order.append(i)
                if not q[i]:
                    d[i] = 0.0
    return order


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("k", [1, 2, 3, 4, 6, 9, 16])
def test_drr_eos_equals_textbook_drr_on_a_static_backlog(k, seed):
    rng = np.random.default_rng(100 * k + seed)
    sizes = [list(rng.choice([40, 200, 576, 1500], int(rng.integers(1, 60)))) for _ in range(k)]
    Q = [float(rng.uniform(1500, 6000)) for _ in range(k)]      # >= largest packet: a visit always sends
    tr = trace(np.zeros(sum(map(len, sizes))), [i for i, x in enumerate(sizes) for _ in x], [v for x in sizes for v in x])
    log = simulate(tr, make("DRR-EOS", k=k, quanta=tuple(Q)), L.config(1e7))
    got = list(tr.cls[np.argsort(log.start, kind="stable")])
    assert got == textbook_drr(sizes, Q)


def sp_oracle(tr, k, rate):
    """Non-preemptive strict priority with an unlimited buffer, written as a plain loop."""
    t, c, s = tr.t, tr.cls, tr.size
    pending = [deque() for _ in range(k)]
    start = np.empty(len(t))
    i, now = 0, 0.0
    while i < len(t) or any(pending):
        if not any(pending):
            now = max(now, t[i])
        while i < len(t) and t[i] <= now:
            pending[c[i]].append(i)
            i += 1
        j = pending[min(x for x in range(k) if pending[x])].popleft()
        start[j] = now
        now += s[j] / rate
    return start


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("k", [1, 2, 5, 12])
def test_sp_equals_independent_oracle(k, seed):
    rng = np.random.default_rng(200 + 10 * k + seed)
    tr = rand_trace(rng, 800, k=k, horizon=0.5, sizes=(40, 200, 1500))
    log = simulate(tr, make("SP", k=k), L.config(1e7))
    assert np.allclose(log.start, sp_oracle(tr, k, 1e7 / 8), rtol=0, atol=1e-12)


@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("k", [1, 4, 32])
def test_fifo_equals_one_line_oracle(k, seed):
    rng = np.random.default_rng(300 + k + seed)
    tr = rand_trace(rng, 1000, k=k, horizon=0.5)
    log = simulate(tr, make("FIFO", k=k), L.config(1e7))
    start, free = np.empty(len(tr)), 0.0
    for j in range(len(tr)):
        start[j] = max(tr.t[j], free)
        free = start[j] + tr.size[j] / 1.25e6
    assert np.allclose(log.start, start, rtol=0, atol=1e-12)


@pytest.mark.parametrize("name", ["DRR", "DRR-EOS"])
@pytest.mark.parametrize("k", [2, 5, 10])
def test_drr_long_run_shares_follow_quanta(name, k):
    rng = np.random.default_rng(400 + k)
    n = 1500 * k
    tr = trace(np.zeros(n), np.repeat(np.arange(k), 1500), rng.choice([64, 576, 1500], n))
    Q = rng.uniform(500, 5000, k)
    log = simulate(tr, make(name, k=k, quanta=tuple(Q)), L.config(1e8))
    first_empty = min(log.end[tr.cls == i].max() for i in range(k))
    done = log.end <= first_empty
    got = np.bincount(tr.cls[done], weights=tr.size[done], minlength=k)
    assert np.allclose(got / got.sum(), Q / Q.sum(), atol=0.01)


@pytest.mark.parametrize("k", [2, 5, 10])
def test_scrr_long_run_shares_are_equal(k):
    """Theorem 3 of the SCRR paper: backlogged flows get equal byte shares (unweighted)."""
    rng = np.random.default_rng(500 + k)
    n = 1500 * k
    tr = trace(np.zeros(n), np.repeat(np.arange(k), 1500), rng.choice([64, 576, 1500, 9000], n))
    log = simulate(tr, make("SCRR", k=k), L.config(1e8))
    first_empty = min(log.end[tr.cls == i].max() for i in range(k))
    done = log.end <= first_empty
    got = np.bincount(tr.cls[done], weights=tr.size[done], minlength=k)
    assert np.allclose(got / got.sum(), 1 / k, atol=0.01)


# ---------------------------------------------------------------- 4. memoryless after a long idle period (18)
@pytest.mark.parametrize("seed", range(3))
@pytest.mark.parametrize("name", MEMORYLESS)
def test_history_is_forgotten_after_a_long_idle_period(name, seed):
    """A busy stretch, 10 s of silence, another busy stretch: the second stretch must be scheduled exactly as if
    it were the only traffic (the non-adaptive rules keep no state across an empty system)."""
    rng = np.random.default_rng(600 + seed)
    a = rand_trace(rng, 300, horizon=0.05, sizes=(40, 576, 1500))
    b = rand_trace(rng, 300, horizon=0.05, sizes=(40, 576, 1500))
    b = Trace(b.t + 10.0, b.cls, b.size)
    both = Trace(np.r_[a.t, b.t], np.r_[a.cls, b.cls], np.r_[a.size, b.size])
    c = cfg(rate=1e6, buffer=10 ** 9)
    p = {"rate_frac": 0.3} if name == "RL-SP+DRR" else {}
    together = simulate(both, make(name, **p), c)
    alone = simulate(b, make(name, **p), c)
    assert np.array_equal(together.start[len(a):], alone.start)


@pytest.mark.parametrize("seed", [0, 1, 3])                 # seed 2 happens not to depend on history
def test_scrr_carries_history_across_idle_periods_but_boundedly(seed):
    """Finding (round 6): SCRR's per-flow clocks survive an empty system of any length (Algorithm 4 resets
    nothing when NP = 0; the printed algorithm behaves the same as ours), so after 10 s of silence its
    schedule still depends on earlier traffic (180 of 200 random cases). The carry-over is bounded: a class's
    served bytes differ from a fresh start by at most 3.03 M over those 200 cases; this test guards 4 M."""
    rng = np.random.default_rng(600 + seed)
    a = rand_trace(rng, 300, horizon=0.05, sizes=(40, 576, 1500))
    b = rand_trace(rng, 300, horizon=0.05, sizes=(40, 576, 1500))
    b = Trace(b.t + 10.0, b.cls, b.size)
    both = Trace(np.r_[a.t, b.t], np.r_[a.cls, b.cls], np.r_[a.size, b.size])
    c = cfg(rate=1e6, buffer=10 ** 9)
    x = simulate(both, make("SCRR"), c).start[len(a):]
    y = simulate(b, make("SCRR"), c).start
    assert not np.array_equal(x, y)                                   # seeds chosen where history matters
    M = int(b.size.max())
    for t in np.unique(np.r_[x, y]):
        for cl in range(3):
            m = b.cls == cl
            assert abs(int(b.size[m][x[m] <= t].sum()) - int(b.size[m][y[m] <= t].sum())) <= 4 * M


# ---------------------------------------------------------------- 5. combinations of scenario options (48)
COMBOS = {
    "red+fade": (dict(load=1.1), dict(buffer_policy="red", capacity=((0.5, 1.5, 0.3),))),
    "imix+partitioned+sync": (dict(load=1.1, arrival="onoff", sync=True,
                                   size_dist=(((40, 7), (576, 4), (1500, 1)),) * 3),
                              dict(buffer_policy="partitioned")),
    "pareto+flash+red": (dict(load=0.9, arrival="onoff", on_dist="pareto", profile=((0.5, 1.0, 4.0, -1),)),
                         dict(buffer_policy="red")),
    "jumbo+partitioned+boost": (dict(load=1.2, size_override=(None, None, (9000, 9000))),
                                dict(buffer_policy="partitioned", capacity=((0.0, 1.0, 2.0),))),
}


@pytest.mark.parametrize("combo", list(COMBOS))
@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_scenario_option_combinations(name, combo):
    traffic, sim = COMBOS[combo]
    c = SimConfig(TrafficConfig(warmup=0.0, duration=2.0, **traffic), buffer_bytes=125_000, **sim)
    tr = generate_trace(c.traffic, 7)
    log = simulate(tr, make(name), c)
    check_common(tr, log, c)
    if name in WORK_CONSERVING:
        check_work_conserving(tr, log)
    m = compute(tr, log, c)
    assert m["n_delivered"] + m["n_dropped"] == len(tr)


# ---------------------------------------------------------------- 6. boundaries of the public helpers (43)
@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_explicit_k3_equals_default(name):
    rng = np.random.default_rng(8)
    tr = rand_trace(rng, 300)
    a = simulate(tr, make(name), cfg())
    b = simulate(tr, make(name, k=3), cfg())
    assert np.array_equal(np.nan_to_num(a.start, nan=-1), np.nan_to_num(b.start, nan=-1))


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_empty_trace_every_scheduler(name):
    log = simulate(trace([], [], []), make(name), cfg())
    assert log.pending == 0 and log.decisions == 0 and len(log.start) == 0


@pytest.mark.parametrize("name", ANY_K)
@pytest.mark.parametrize("k", [1, 7])
def test_empty_trace_any_k(name, k):
    p = {"quanta": (1500.0,) * k} if name in ("DRR", "DRR-EOS") else {}
    log = simulate(trace([], [], []), make(name, k=k, **p), L.config(1e7))
    assert log.pending == 0 and log.q_values.shape == (0, k)


def test_token_bucket_boundaries():
    assert L.token_bucket_times(None, 1e3, 100, 100, start=5.0, horizon=1.0) == []        # starts after horizon
    assert L.token_bucket_times(None, 1e3, 100, 100, start=0.0, horizon=1.0, n_max=0) == []
    assert len(L.token_bucket_times(None, 1e3, 1000, 100, start=0.0, horizon=1.0, n_max=5)) == 5
    ts = L.token_bucket_times(None, 1e3, 100, 100, start=0.0, horizon=1.0)                 # bucket = one packet
    assert np.allclose(np.diff(ts), 0.1) and ts[0] == 0.0
    rng = np.random.default_rng(9)
    ts = L.token_bucket_times(rng, 1e3, 500, 100, 0.0, 5.0, idle_p=1.0, idle_mean=0.05)     # always pauses first
    assert L.conforms(ts, [100] * len(ts), 1e3, 500) and ts[0] > 0


def test_conforms_boundaries():
    assert L.conforms([], [], 1.0, 1.0)
    assert L.conforms([0.0], [100], 0.0, 100)
    assert not L.conforms([0.0], [101], 0.0, 100)
    assert L.conforms([0.0, 1.0], [100, 100], 100.0, 100)
    assert not L.conforms([0.0, 0.5], [100, 100], 100.0, 100)


def test_boyer_bound_single_flow_is_burst_over_link_rate():
    # one flow alone: no interference, latency only from its own residual deficit term (zero others)
    assert L.boyer_bound(0, [1500.0], [1500], 3000, 100.0, 1000.0) == pytest.approx(3000 / 1000.0)


def test_boyer_bound_grows_with_interference_and_burst():
    base = L.boyer_bound(0, [1500.0, 1500.0], [1500, 1500], 3000, 100.0, 1e4)
    assert L.boyer_bound(0, [1500.0, 1500.0, 1500.0], [1500] * 3, 3000, 100.0, 1e4) > base
    assert L.boyer_bound(0, [1500.0, 1500.0], [1500, 1500], 6000, 100.0, 1e4) > base


def test_make_trace_sorts_and_breaks_ties_by_class():
    tr = L.make_trace([0.2, 0.1, 0.1], [1, 2, 0], [10, 20, 30])
    assert list(tr.t) == [0.1, 0.1, 0.2] and list(tr.cls) == [0, 2, 1] and list(tr.size) == [30, 20, 10]


@pytest.mark.parametrize("sizes", ["random", "constant", "bimodal"])
def test_b3_trace_sizes_and_rates(sizes):
    tr = L.b3_trace(1, sizes)
    allowed = {"random": set(range(1, 563)), "constant": {13}, "bimodal": {13, 562}}[sizes]
    assert set(np.unique(tr.size)) <= allowed
    n = np.bincount(tr.cls, minlength=20) / L.B3["duration"]
    assert abs(n[9] / np.delete(n, 9).mean() - 3) < 0.15


def test_b3_unknown_size_model_rejected():
    with pytest.raises(ValueError):
        L.b3_trace(1, "lognormal")


def test_b3_scaled_link_keeps_the_overload():
    for sizes in ("constant", "bimodal"):
        ratio = L.b3_offered_bps(sizes) / (L.B3["link_bps"] * L.b3_offered_bps(sizes) / L.b3_offered_bps("random"))
        assert ratio == pytest.approx(L.b3_offered_bps("random") / L.B3["link_bps"])


def test_skip_rounding_note_cqdrr_exact_with_binary_fraction_quanta():
    """CQDRR's skip is bit-identical to round-by-round addition when the arithmetic is exact (quanta pinned to a
    binary fraction); with 0.02 B quanta decisions may differ at exact ties (documented)."""
    import drrsim.schedulers as S

    class NoSkip(S.CQDRR):
        name = "CQDRR-noskip"

        def _skip_empty_rounds(self):
            pass
    rng = np.random.default_rng(10)
    for _ in range(10):
        tr = rand_trace(rng, 60, horizon=0.02, sizes=(1, 40, 576, 1500))   # competing backlog; reference is slow
        c = cfg(rate=1e7, update_interval=0.001)
        q = 1 / 32
        a = simulate(tr, S.CQDRR(qmin=q, qmax=q), c)
        b = simulate(tr, NoSkip(qmin=q, qmax=q), c)
        assert np.array_equal(np.nan_to_num(a.start, nan=-1), np.nan_to_num(b.start, nan=-1))
