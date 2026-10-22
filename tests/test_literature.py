"""E13 literature benchmarks: the any-number-of-classes generalisation, DRR-EOS, token buckets, probes,
and each published example at small scale (full runs: scripts/run_benchmarks.py)."""
import itertools

import numpy as np
import pytest

from drrsim import literature as L
from drrsim.engine import simulate
from drrsim.schedulers import SCRR, make


def order(trace, log):
    o = np.argsort(log.start, kind="stable")
    return [(int(c), len(list(g))) for c, g in itertools.groupby(trace.cls[o])]


# ---------------------------------------------------------------- k classes
@pytest.mark.parametrize("name", ["FIFO", "SP", "DRR", "DRR-EOS", "SCRR"])
def test_any_k_schedulers_serve_everything_in_class_fifo_order(name):
    rng = np.random.default_rng(5)
    k = 17
    n = 3000
    tr = L.make_trace(rng.uniform(0, 1, n), rng.integers(0, k, n), rng.integers(40, 1500, n))
    params = {"quanta": tuple(rng.uniform(200, 3000, k))} if name in ("DRR", "DRR-EOS") else {}
    log = simulate(tr, make(name, k=k, **params), L.config(10e6))
    assert not np.isnan(log.end).any() and log.pending == 0
    for c in range(k):
        s = log.start[tr.cls == c]
        assert np.all(np.diff(s) > 0)
    busy = np.sort(log.start)
    assert np.all(np.diff(busy) > 0)


@pytest.mark.parametrize("name", ["RL-SP+DRR", "DR-DRR", "CQDRR", "FuzzyDRR", "RevenueDRR", "DR-DRR+damping", "CQDRR-draft"])
def test_three_class_schedulers_refuse_other_k(name):
    with pytest.raises(ValueError, match="exactly 3 classes"):
        make(name, k=4)
    make(name, k=3)          # explicit 3 is the default


@pytest.mark.parametrize("k", [0, -1, 4097, 2.0, True, "3"])
def test_bad_k_rejected(k):
    with pytest.raises(ValueError, match="number of classes"):
        make("DRR", k=k)


def test_quanta_length_must_match_k():
    with pytest.raises(ValueError, match="needs 5 values"):
        make("DRR", k=5)                     # default quanta have 3 entries
    make("DRR", k=5, quanta=(1500.0,) * 5)


def test_scheduler_and_trace_class_counts_must_agree():
    tr = L.make_trace([0.0, 0.1], [0, 4], [100, 100])
    with pytest.raises(ValueError, match="class indices"):
        simulate(tr, make("FIFO"), L.config(10e6))          # 3 classes, class 4 present
    sch = make("FIFO", k=5)
    simulate(tr, sch, L.config(10e6))
    from drrsim.engine import View
    with pytest.raises(ValueError, match="built for 5 classes"):
        sch.bind(View([0.0], [1], 1e6, 10**6, 0.01))


# ---------------------------------------------------------------- DRR-EOS
def test_drr_eos_differs_from_drr_exactly_when_a_packet_arrives_during_the_last_one():
    # class 0: packet at 0, a second one while the first is on the link; class 1: one packet just after 0
    tau = 1000 * 8 / 1e6
    tr = L.make_trace([0.0, 1e-9, tau / 2], [0, 1, 0], [1000, 1000, 1000])
    cfg = L.config(1e6)
    q = (5000.0, 5000.0)
    assert order(tr, simulate(tr, make("DRR", k=2, quanta=q), cfg)) == [(0, 1), (1, 1), (0, 1)]       # dequeue-time rule
    assert order(tr, simulate(tr, make("DRR-EOS", k=2, quanta=q), cfg)) == [(0, 2), (1, 1)]          # end-of-service rule


def test_drr_eos_opportunity_ends_when_the_link_goes_idle():
    tau = 1000 * 8 / 1e6
    tr = L.make_trace([0.0, 3 * tau], [0, 0], [1000, 1000])
    s = make("DRR-EOS", k=2, quanta=(5000.0, 5000.0))
    simulate(tr, s, L.config(1e6))
    assert s.deficit[0] == 4000.0          # fresh quantum for the second packet, not the 4000 left over (8000 - 1000)


def test_drr_eos_equals_drr_without_arrivals_during_service():
    rng = np.random.default_rng(9)
    times = np.repeat(np.arange(30) * 1.0, 4)          # bursts at whole seconds, link drains in between
    tr = L.make_trace(times, np.tile([0, 1, 2, 3], 30), rng.integers(100, 1500, 120))
    q = (1500.0, 700.0, 3000.0, 1200.0)
    a = simulate(tr, make("DRR", k=4, quanta=q), L.config(1e6))
    b = simulate(tr, make("DRR-EOS", k=4, quanta=q), L.config(1e6))
    # one packet per class per burst and the link drains between bursts: no packet arrives while its class's
    # last queued packet is on the link, so the two rules must make identical decisions
    assert np.array_equal(a.start, b.start)


# ---------------------------------------------------------------- token buckets
@pytest.mark.parametrize("idle_p", [0.0, 0.1, 0.5])
def test_token_bucket_sources_conform(idle_p):
    rng = np.random.default_rng(int(idle_p * 10))
    ts = L.token_bucket_times(rng, 1e5, 5000, 400, 0.0, 2.0, idle_p, 0.01)
    assert L.conforms(ts, [400] * len(ts), 1e5, 5000)
    assert not L.conforms(ts, [401] * len(ts), 1e5, 5000) or idle_p > 0


def test_greedy_token_bucket_shape():
    ts = L.token_bucket_times(None, 1e5, 5000, 400, 1.0, 1.1)
    assert ts[:12] == [1.0] * 12                        # floor(5000 / 400) packets in the burst
    assert ts[12] == pytest.approx(1.0 + (13 * 400 - 5000) / 1e5)
    assert np.allclose(np.diff(ts[13:]), 400 / 1e5)


def test_conforms_detects_violation():
    assert not L.conforms([0.0, 0.0, 0.0], [100] * 3, 1.0, 250)
    assert L.conforms([0.0, 0.0, 50.0], [100] * 3, 1.0, 250)


def test_oversized_packet_rejected():
    with pytest.raises(ValueError):
        L.token_bucket_times(None, 1.0, 100, 101, 0.0, 1.0)


# ---------------------------------------------------------------- B1
def test_b1_reproduces_published_trajectory_delay():
    for sch in ("DRR-EOS", "DRR"):
        assert L.b1_run(sch) == pytest.approx(119.256, abs=0.001)
    assert L.b1_run() == pytest.approx((15 - 0.08 / 0.86) * 8 - 1e-4, abs=1e-6)    # 15 l/c - 0.08 l/r1 - eps


def test_b1_service_order_matches_the_paper():
    tr, poi = L.b1_trace()
    log = simulate(tr, make("DRR-EOS", quanta=L.B1["quanta"]), L.config(1e8))
    assert order(tr, log) == [(2, 10), (0, 62), (1, 4), (2, 10), (0, 1)]
    assert log.end[poi] * 1e8 / 800 == pytest.approx(87)      # departs at 87 l/c, as in the paper


def test_b1_random_inputs_respect_boyer_bound():
    assert L.b1_random_max(np.random.default_rng(3), 30) <= L.B1["boyer_us"]


# ---------------------------------------------------------------- B2
def test_b2_greedy_inputs_respect_published_bounds():
    rng = np.random.default_rng(4)
    for mode in ("greedy", "offset", "random"):
        r = L.b2_trial(rng, mode)
        for sch in r:
            assert all(d <= b for d, b in zip(r[sch], L.B2["bound_s"]))


def test_b2_inputs_conform_to_their_token_buckets():
    rng = np.random.default_rng(6)
    for k in range(4):
        r, b, l = L.B2["r_bps"][k] / 8, L.B2["b"][k], L.B2["l"][k]
        ts = L.token_bucket_times(rng, r, b, l, 0.0, 6e-3, 0.3, 0.5 * b / r)
        assert L.conforms(ts, [l] * len(ts), r, b)


# ---------------------------------------------------------------- B3, B4
def test_b3_fifo_unfair_drr_fair_one_seed():
    fifo = L.b3_throughput(101, "FIFO")
    drr = L.b3_throughput(101, "DRR")
    bad = L.B3["bad_flow"]
    assert fifo[bad] / np.delete(fifo, bad).mean() > 2.5
    assert abs(drr[bad] / np.delete(drr, bad).mean() - 1) < 0.02
    assert drr.sum() == pytest.approx(L.B3["link_bps"], rel=0.01)      # link saturated


def test_b3_shared_buffer_breaks_drr_isolation():
    drr = L.b3_throughput(101, "DRR", buffer_bytes=140_000)
    bad = L.B3["bad_flow"]
    assert drr[bad] / np.delete(drr, bad).mean() > 2.5


def test_b4_rlsp_shares():
    r = L.b4_throughput(101, "RL-SP+DRR")
    assert r["on"] == pytest.approx([6e6, 2e6, 2e6], rel=0.01)
    assert r["off"] == pytest.approx([0, 5e6, 5e6], rel=0.02)


def test_b4_traces_switch_high_priority_on_at_N():
    tr = L.b4_trace(1)
    assert tr.t[tr.cls == 0].min() >= L.B4["N"]


# ---------------------------------------------------------------- B5
def test_probe_does_not_change_scrr_decisions():
    rng = np.random.default_rng(8)
    n = 2000
    tr = L.make_trace(rng.uniform(0, 0.5, n), rng.integers(0, 6, n), rng.choice([64, 1500, 9000], n))
    a = simulate(tr, SCRR(k=6), L.config(1e8))
    b = simulate(tr, L.SCRRProbe(k=6), L.config(1e8))
    assert np.array_equal(a.start, b.start)


def test_scrr_as_printed_exceeds_theorem1_on_a_minimal_case():
    # 3 flows, sizes 1 and 3, all queued at t = 0 (found by exhaustive search; see the E13 notes)
    sizes = [1, 1, 1, 3, 3, 1, 3, 1, 1]
    tr = L.make_trace([0.0] * 9, [0, 0, 0, 1, 1, 1, 2, 2, 2], sizes)
    p = L.SCRRProbe(k=3)
    simulate(tr, p, L.config(1e6))
    assert p.max_advance == 4.0 > max(sizes)
    q = L.SCRRRoundFirstProbe(k=3)
    simulate(tr, q, L.config(1e6))
    assert q.max_advance <= max(sizes)


def test_scrr_round_first_meets_theorems_on_random_traces():
    rng = np.random.default_rng(10)
    for backlogged in (True, False):
        for _ in range(40):
            M, adv, _, burst = L.b5_trial(rng, backlogged, L.SCRRRoundFirstProbe)
            assert adv <= M and burst <= 2 * M


def test_partitioned_buffer_splits_by_the_scheduler_class_count():
    # 6 classes, 6000 B partitioned -> 1000 B each. The first 400 B packet starts service at once (leaves the
    # buffer); the next two queue (800 B); the fourth would make 1200 B and is dropped (with 3 classes: 2000 B, kept)
    tr = L.make_trace([0.0] * 4, [0] * 4, [400] * 4)
    log = simulate(tr, make("FIFO", k=6), L.config(1e6, 6000, "partitioned"))
    assert log.dropped.tolist() == [False, False, False, True]
    assert not simulate(tr, make("FIFO"), L.config(1e6, 6000, "partitioned")).dropped.any()
