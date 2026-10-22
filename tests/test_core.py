import math

import numpy as np
import pytest

from drrsim import SimConfig, TrafficConfig, generate_trace, make, simulate
from drrsim.config import K
from drrsim.metrics import compute, jain, maxmin_share, starvation_gaps
from drrsim.schedulers import ADAPTIVE, SCHEDULERS
from drrsim.traffic import Trace


def toy_trace(scale=1):
    # (time, class, bytes); at link 8000*scale b/s, 1 byte*scale = 1 ms
    rows = [(0.0, 2, 100), (0.02, 1, 200), (0.05, 0, 100), (0.4, 2, 100), (0.5, 0, 50)]
    t, c, s = zip(*rows)
    return Trace(np.array(t), np.array(c, dtype=np.int8), np.array(s, dtype=np.int32) * scale)


def toy_cfg(scale=1, buffer=100_000):
    return SimConfig(TrafficConfig(link_rate=8000.0 * scale, warmup=0.0, duration=1.0), buffer_bytes=buffer)


# ---------- configuration ----------
def test_config_validation():
    with pytest.raises(ValueError):
        TrafficConfig(mix=(0.5, 0.5, 0.5))
    with pytest.raises(ValueError):
        TrafficConfig(arrival="pareto")
    with pytest.raises(ValueError):
        SimConfig(buffer_bytes=100)
    with pytest.raises(ValueError):
        make("DRR", nonsense=1)


# ---------- traffic ----------
@pytest.mark.parametrize("arrival", ["poisson", "onoff"])
def test_trace_deterministic_and_sorted(arrival):
    tc = TrafficConfig(arrival=arrival, duration=5.0, warmup=1.0)
    a, b = generate_trace(tc, 7), generate_trace(tc, 7)
    assert a.digest() == b.digest()
    assert generate_trace(tc, 8).digest() != a.digest()
    assert np.all(np.diff(a.t) >= 0)
    assert a.t.min() >= 0 and a.t.max() < tc.horizon


@pytest.mark.parametrize("arrival", ["poisson", "onoff"])
def test_trace_offered_load(arrival):
    tc = TrafficConfig(arrival=arrival, load=0.8, duration=200.0, warmup=0.0)
    tr = generate_trace(tc, 3)
    for k, target in enumerate(tc.per_class_load()):
        got = tr.size[tr.cls == k].sum() * 8 / tc.horizon / tc.link_rate
        assert got == pytest.approx(target, rel=0.08 if arrival == "onoff" else 0.03)


def test_trace_save_load(tmp_path):
    tr = generate_trace(TrafficConfig(duration=2.0, warmup=0.0), 1)
    tr.save(tmp_path / "t.npz")
    assert Trace.load(tmp_path / "t.npz").digest() == tr.digest()


def test_onoff_is_burstier_than_poisson():
    def idc(tr):  # index of dispersion of counts in 50 ms bins
        counts = np.histogram(tr.t, bins=np.arange(0, 60, 0.05))[0]
        return counts.var() / counts.mean()
    p = generate_trace(TrafficConfig(arrival="poisson", duration=60, warmup=0), 1)
    o = generate_trace(TrafficConfig(arrival="onoff", duration=60, warmup=0), 1)
    assert idc(o) > 3 * idc(p)


# ---------- engine: hand-calculated 5-packet toy ----------
def test_toy_fifo_exact():
    log = simulate(toy_trace(), make("FIFO"), toy_cfg())
    assert np.allclose(log.start, [0.0, 0.1, 0.3, 0.4, 0.5])
    assert np.allclose(log.end, [0.1, 0.3, 0.4, 0.5, 0.55])
    assert not log.dropped.any() and log.pending == 0


def test_toy_sp_exact():
    log = simulate(toy_trace(), make("SP"), toy_cfg())
    assert np.allclose(log.start, [0.0, 0.2, 0.1, 0.4, 0.5])
    assert np.allclose(log.end, [0.1, 0.4, 0.2, 0.5, 0.55])


def test_toy_tail_drop_exact():
    # sizes x10, link x10: same times. Buffer 2500 B: p2 (1000 B) arrives with p1 (2000 B) queued -> drop.
    log = simulate(toy_trace(10), make("FIFO"), toy_cfg(10, buffer=2500))
    assert log.dropped.tolist() == [False, False, True, False, False]
    assert np.allclose(log.start[[0, 1, 3, 4]], [0.0, 0.1, 0.4, 0.5])
    assert math.isnan(log.start[2])


def test_toy_metrics_exact():
    tr, cfg = toy_trace(), toy_cfg()
    m = compute(tr, simulate(tr, make("FIFO"), cfg), cfg)
    # class 0 delays: p2 0.25, p4 0.0 ; class 1: p1 0.08 ; class 2: p0 0, p3 0
    assert m["lat_delay_mean"] == pytest.approx(0.125)
    assert m["lat_p95"] == pytest.approx(np.percentile([0.25, 0.0], 95))
    assert m["vid_delay_mean"] == pytest.approx(0.08)
    assert m["blk_delay_mean"] == pytest.approx(0.0)
    assert m["lat_tput"] == pytest.approx(150 * 8 / 1.0)
    assert m["blk_tput"] == pytest.approx(200 * 8 / 1.0)


# ---------- engine invariants on realistic traffic ----------
@pytest.fixture(scope="module")
def overload():
    cfg = SimConfig(TrafficConfig(load=1.2, arrival="onoff", duration=8.0, warmup=1.0), buffer_bytes=60_000)
    return cfg, generate_trace(cfg.traffic, 11)


@pytest.mark.parametrize("name", SCHEDULERS)
def test_accounting_and_fifo_within_class(overload, name):
    cfg, tr = overload
    log = simulate(tr, make(name), cfg)
    delivered = (~log.dropped & ~np.isnan(log.start)).sum()
    assert len(tr) == delivered + log.dropped.sum() + log.pending
    assert log.pending == 0
    assert np.all(log.start[~log.dropped] >= tr.t[~log.dropped] - 1e-12)
    for k in range(K):
        s = log.start[(tr.cls == k) & ~log.dropped]
        assert np.all(np.diff(s) > 0)
    # link never transmits two packets at once
    order = np.argsort(log.start[~log.dropped])
    st, en = log.start[~log.dropped][order], log.end[~log.dropped][order]
    assert np.all(st[1:] >= en[:-1] - 1e-9)


@pytest.mark.parametrize("name", SCHEDULERS)
def test_no_drain_accounting(overload, name):
    cfg, tr = overload
    cfg = SimConfig(cfg.traffic, buffer_bytes=cfg.buffer_bytes, drain=False)
    log = simulate(tr, make(name), cfg)
    delivered = (~log.dropped & ~np.isnan(log.start)).sum()
    assert len(tr) == delivered + log.dropped.sum() + log.pending


def test_work_conserving_same_busy_time():
    cfg = SimConfig(TrafficConfig(load=0.95, arrival="onoff", duration=5.0, warmup=0.0), buffer_bytes=10**9)
    tr = generate_trace(cfg.traffic, 5)
    # RL-SP+DRR shapes class 0 and is not work-conserving by design (tested separately)
    last = {n: np.nanmax(simulate(tr, make(n), cfg).end) for n in SCHEDULERS if n != "RL-SP+DRR"}
    assert max(last.values()) - min(last.values()) < 1e-9


# ---------- schedulers ----------
def saturating_trace(n_per_class, sizes):
    t = np.concatenate([np.arange(n_per_class) * 1e-9 for _ in range(K)])
    c = np.concatenate([np.full(n_per_class, k, dtype=np.int8) for k in range(K)])
    s = np.concatenate([np.full(n_per_class, sizes[k], dtype=np.int32) for k in range(K)])
    o = np.lexsort((c, t))
    return Trace(t[o], c[o], s[o])


def test_drr_shares_match_quanta():
    tr = saturating_trace(3000, (500, 500, 500))
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=1.0), buffer_bytes=10**9)
    log = simulate(tr, make("DRR", quanta=(500, 1000, 1500)), cfg)
    t_cut = np.nanmax(log.end[tr.cls == 2])        # class 2 empties first
    served = [tr.size[(tr.cls == k) & (log.end <= t_cut)].sum() for k in range(K)]
    share = np.array(served) / sum(served)
    assert np.allclose(share, [1 / 6, 2 / 6, 3 / 6], atol=0.005)


def test_drr_small_quantum_still_serves_large_packets():
    tr = saturating_trace(200, (200, 1500, 1500))
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=1.0), buffer_bytes=10**9)
    log = simulate(tr, make("DRR", quanta=(1500, 150, 300)), cfg)
    assert not np.isnan(log.start).any()


def test_sp_strict_order():
    tr = saturating_trace(100, (200, 1000, 1500))
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=1.0), buffer_bytes=10**9)
    log = simulate(tr, make("SP"), cfg)
    # after the first packet, all class 0 before any class 1, all class 1 before class 2
    s = log.start
    assert np.nanmax(s[tr.cls == 0]) < np.nanmin(s[(tr.cls == 1)][1:])
    assert np.nanmax(s[tr.cls == 1]) < np.nanmin(s[(tr.cls == 2)][1:])


def rl_toy(rows):
    t, c, z = zip(*rows)
    return Trace(np.array(t, dtype=float), np.array(c, dtype=np.int8), np.array(z, dtype=np.int32))


def test_rlsp_toy_exact():
    # link 1000 B/s, shaper 500 B/s: 100-B class-0 packets may leave every 0.2 s
    cfg = toy_cfg()
    log = simulate(rl_toy([(0, 0, 100), (0, 0, 100), (0, 1, 100)]), make("RL-SP+DRR", rate_frac=0.5), cfg)
    assert np.allclose(log.start, [0.0, 0.2, 0.1])      # held class-0 packet does not go to DRR


def test_rlsp_not_work_conserving():
    cfg = toy_cfg()
    log = simulate(rl_toy([(0, 0, 100), (0, 0, 100)]), make("RL-SP+DRR", rate_frac=0.5), cfg)
    assert np.allclose(log.start, [0.0, 0.2]) and np.allclose(log.end, [0.1, 0.3])   # link idles 0.1-0.2
    log = simulate(rl_toy([(0, 0, 100), (1.0, 0, 100)]), make("RL-SP+DRR", rate_frac=0.5), cfg)
    assert np.allclose(log.start, [0.0, 1.0])                                         # idle gap: no extra wait


def test_rlsp_rate_limits_priority():
    tr = saturating_trace(20000, (200, 1500, 1500))
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=1.0), buffer_bytes=10**9)
    log = simulate(tr, make("RL-SP+DRR", rate_frac=0.5), cfg)
    served = [tr.size[(tr.cls == k) & (log.end <= 2.0)].sum() for k in range(K)]
    # class 0 gets its shaped rate (no DRR share on top); classes 1, 2 split the rest equally
    assert served[0] / sum(served) == pytest.approx(0.5, abs=0.005)
    assert served[1] / served[2] == pytest.approx(1.0, abs=0.01)
    with pytest.raises(ValueError):
        simulate(tr, make("RL-SP+DRR", rate_frac=0.0), cfg)


@pytest.mark.parametrize("name", ADAPTIVE)
def test_adaptive_quanta_bounded(overload, name):
    cfg, tr = overload
    log = simulate(tr, make(name), cfg)
    Q = log.q_values
    assert len(Q) > 100
    assert np.all(np.isfinite(Q)) and Q.min() > 0 and Q.max() <= 64000
    assert Q.std(axis=0).max() > 0     # it actually adapts


def test_fuzzy_multiplier_corners():
    f = make("FuzzyDRR")
    assert f.multiplier(0.0, 0.0) == pytest.approx(0.75)
    assert f.multiplier(1.0, 1.0) == pytest.approx(4.0)
    assert f.multiplier(0.5, 0.5) == pytest.approx(1.5)
    assert f.multiplier(0.25, 0.0) == pytest.approx(0.5 * 0.75 + 0.5 * 1.0)


# ---------- metric helpers ----------
def test_maxmin_and_jain():
    assert np.allclose(maxmin_share([1, 5, 5], 7), [1, 3, 3])
    assert np.allclose(maxmin_share([1, 1, 1], 7), [1, 1, 1])
    assert jain([1, 1, 1]) == pytest.approx(1.0)
    assert jain([1, 0, 0]) == pytest.approx(1 / 3)


def test_starvation_gaps_hand():
    arr = np.array([0.0, 0.1, 1.0])
    start = np.array([0.5, 0.6, 1.0])
    end = np.array([0.6, 0.7, 1.1])
    gs, gap = starvation_gaps(arr, start, end)
    assert np.allclose(gs, [0.0, 0.6, 1.0])
    assert np.allclose(gap, [0.5, 0.0, 0.0])


def test_partitioned_buffer_isolates_classes():
    # class 2 sends 3 x 1000 B at once; partition = 4500/3 = 1500 B per class
    tr = Trace(np.array([0.0, 0.0, 0.0, 0.001]), np.array([2, 2, 2, 0], dtype=np.int8),
               np.array([1000, 1000, 1000, 1000], dtype=np.int32))
    tc = TrafficConfig(link_rate=8e6, warmup=0.0, duration=1.0)
    shared = simulate(tr, make("FIFO"), SimConfig(tc, buffer_bytes=4500))
    part = simulate(tr, make("FIFO"), SimConfig(tc, buffer_bytes=4500, buffer_policy="partitioned"))
    assert shared.dropped.tolist() == [False, False, False, False]
    # p0 goes straight to the link; p1 queued (1000 <= 1500); p2 would make 2000 > 1500 -> drop;
    # the class-0 packet has its own partition and is admitted
    assert part.dropped.tolist() == [False, False, True, False]
    with pytest.raises(ValueError):
        SimConfig(buffer_bytes=3000, buffer_policy="partitioned")


def test_ci95_and_paired():
    import pandas as pd
    from drrsim.analysis import ci95, paired_vs
    m, h, n = ci95([1.0, 2.0, 3.0])
    assert (m, n) == (2.0, 3) and h == pytest.approx(4.302653 * 1.0 / np.sqrt(3), rel=1e-5)
    df = pd.DataFrame({"point": "p", "seed": [1, 2, 3] * 2, "scheduler": ["DRR"] * 3 + ["SP"] * 3,
                       "x": [5.0, 6.0, 7.0, 4.0, 5.0, 5.0]})
    r = paired_vs(df, "x").set_index("scheduler").loc["SP"]
    assert r["diff"] == pytest.approx(-4 / 3) and r["wins"] == 3


def test_sqdrr_smoothing_default_unchanged_and_damps(overload):
    cfg, tr = overload
    a = simulate(tr, make("DR-DRR"), cfg)
    b = simulate(tr, make("DR-DRR", smooth=1.0), cfg)
    c = simulate(tr, make("DR-DRR", smooth=0.1), cfg)
    assert np.array_equal(a.q_values, b.q_values)
    assert np.abs(np.diff(c.q_values, axis=0)).mean() < np.abs(np.diff(a.q_values, axis=0)).mean()
    assert c.q_values.min() >= 1500 - 1e-9 and c.q_values.max() <= 8 * 1500 + 1e-9


def test_damped_variant_equals_sqdrr_smooth_half(overload):
    from drrsim.schedulers import SCHEDULERS as S
    cfg, tr = overload
    a = simulate(tr, make("DR-DRR+damping"), cfg)
    b = simulate(tr, make("DR-DRR", smooth=0.5), cfg)
    assert np.array_equal(a.q_values, b.q_values)
    assert "DR-DRR+damping" not in S and len(S) == 8


def test_mm1k_blocking_hand_values():
    from drrsim.schedulers import mm1k_blocking
    assert mm1k_blocking(0.5, 1) == pytest.approx(0.5 * 0.5 / (1 - 0.25))
    assert mm1k_blocking(1.0, 9) == pytest.approx(0.1)
    assert mm1k_blocking(2.0, 1) == pytest.approx(2 / 3)
    assert mm1k_blocking(50.0, 400) == pytest.approx(49 / 50)        # stable for huge rho^K
    assert mm1k_blocking(0.0, 5) == 0.0


def test_cqdrr_fixed_priority_rounds_and_shares():
    tr = saturating_trace(3000, (500, 500, 500))
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=1.0), buffer_bytes=10**9)
    sch = make("CQDRR")
    sch.update = lambda now: None                   # freeze quanta at base: plain fixed-order DRR
    log = simulate(tr, sch, cfg)
    first = np.argsort(log.start)[:10]
    # p0 meets an empty system and empties its queue (round moves on); then 3 packets per visit, order 1,2,0
    assert tr.cls[first].tolist() == [0, 1, 1, 1, 2, 2, 2, 0, 0, 0]
    t_cut = 1.0
    served = [tr.size[(tr.cls == k) & (log.end <= t_cut)].sum() for k in range(K)]
    assert np.allclose(np.array(served) / sum(served), 1 / 3, atol=0.005)


def test_cqdrr_single_tt_class_delay_term_is_inert(overload):
    # with one TT class h = eta*D, so exp((eta*D - h)/(1+sqrt h)) = 1: TT quantum must not depend on p_viol
    cfg, tr = overload
    a = simulate(tr, make("CQDRR", p_viol=0.05), cfg)
    b = simulate(tr, make("CQDRR", p_viol=0.001), cfg)
    assert np.array_equal(a.q_values, b.q_values)


def test_scrr_byte_fair_with_unequal_packet_sizes():
    tr = saturating_trace(6000, (200, 1500, 1500))
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=1.0), buffer_bytes=10**9)
    log = simulate(tr, make("SCRR"), cfg)
    t_cut = 0.9 * np.nanmax(log.end[tr.cls == 0])      # all three still backlogged
    served = [tr.size[(tr.cls == k) & (log.end <= t_cut)].sum() for k in range(K)]
    assert np.allclose(np.array(served) / sum(served), 1 / 3, atol=0.01)   # bytes, not packets


def test_scrr_sparse_class_jumps_ahead():
    # classes 1 and 2 backlogged; one class-0 packet arrives later and must be the next one sent
    tr = saturating_trace(50, (0, 1500, 1500))
    keep = tr.cls != 0
    t = np.concatenate([tr.t[keep], [0.01]])
    c = np.concatenate([tr.cls[keep], [0]]).astype(np.int8)
    z = np.concatenate([tr.size[keep], [200]]).astype(np.int32)
    o = np.lexsort((c, t))
    trace = Trace(t[o], c[o], z[o])
    cfg = SimConfig(TrafficConfig(warmup=0.0, duration=1.0), buffer_bytes=10**9)
    log = simulate(trace, make("SCRR"), cfg)
    s0 = log.start[trace.cls == 0][0]
    in_service_end = np.nanmin(log.end[(log.end > 0.01) & (trace.cls != 0)])
    assert s0 == pytest.approx(in_service_end)            # served at the very next decision


def test_scrr_accounting_and_work_conserving(overload):
    cfg, tr = overload
    log = simulate(tr, make("SCRR"), cfg)
    delivered = (~log.dropped & ~np.isnan(log.start)).sum()
    assert len(tr) == delivered + log.dropped.sum() + log.pending and log.pending == 0
    for k in range(K):
        assert np.all(np.diff(log.start[(tr.cls == k) & ~log.dropped]) > 0)
    cfg2 = SimConfig(TrafficConfig(load=0.95, arrival="onoff", duration=5.0, warmup=0.0), buffer_bytes=10**9)
    tr2 = generate_trace(cfg2.traffic, 5)
    assert np.nanmax(simulate(tr2, make("SCRR"), cfg2).end) == pytest.approx(np.nanmax(simulate(tr2, make("DRR"), cfg2).end))
