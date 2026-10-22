"""IMIX packet-size distributions and RED active queue management (E12)."""
import random

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st
from scipy import stats

from conftest import ALL_SCHEDULERS, WORK_CONSERVING, cfg_for, trace_from
from reference import RefDRR, RefFIFO, RefRLSP, RefSP, ref_simulate
from test_properties import SETTINGS, check_common, check_work_conserving, scenarios
from drrsim import SimConfig, TrafficConfig, generate_trace, make, simulate

IMIX = ((40, 7), (576, 4), (1500, 1))


# ---------------- IMIX ----------------
def test_imix_sizes_proportions_and_byte_load():
    tc = TrafficConfig(load=0.9, arrival="poisson", size_dist=(None, IMIX, IMIX), duration=100.0, warmup=0.0)
    tr = generate_trace(tc, 3)
    for k in (1, 2):
        s = tr.size[tr.cls == k]
        assert set(np.unique(s)) == {40, 576, 1500}
        counts = np.array([(s == v).sum() for v in (40, 576, 1500)])
        assert stats.chisquare(counts, f_exp=counts.sum() * np.array([7, 4, 1]) / 12).pvalue > 0.001
        got = s.sum() * 8 / tc.horizon / tc.link_rate
        assert got == pytest.approx(tc.per_class_load()[k], rel=0.03)
    assert tc.class_mean_size(1) == pytest.approx((7 * 40 + 4 * 576 + 1500) / 12)
    assert set(np.unique(tr.size[tr.cls == 0])) == {200}


@pytest.mark.parametrize("kw", [
    dict(size_dist=(None, IMIX)), dict(size_dist=(None, ((0, 1),), None)), dict(size_dist=(None, ((40, 0),), None)),
    dict(size_dist=(None, ((40, -1),), None)), dict(size_dist=(None, (), None)), dict(size_dist=(None, ((40.5, 1),), None)),
    dict(size_dist=(None, IMIX, None), size_override=(None, (100, 200), None)),
])
def test_imix_validation(kw):
    with pytest.raises(ValueError):
        TrafficConfig(**kw)


def test_default_traffic_unchanged_by_size_dist_support():
    a = generate_trace(TrafficConfig(duration=5.0, warmup=0.0), 4)
    b = generate_trace(TrafficConfig(duration=5.0, warmup=0.0, size_dist=(None, None, None)), 4)
    assert a.digest() == b.digest()


# ---------------- RED ----------------
@pytest.mark.parametrize("red", [(-1, 100, 0.1, 0.1), (100, 50, 0.1, 0.1), (0, 200_000, 0.1, 0.1), (0, 100, 0, 0.1),
                                 (0, 100, 1.5, 0.1), (0, 100, 0.1, 0), (0, float("nan"), 0.1, 0.1)])
def test_red_validation(red):
    with pytest.raises(ValueError):
        SimConfig(buffer_policy="red", red=red)


def test_red_hand_trace_with_known_random_draws():
    # link 1000 B/s; w_q = 1 makes avg equal the instantaneous queue; min 100 B, max 300 B, max_p 0.5
    tr = trace_from([(0.0, 0, 100), (0.01, 0, 100), (0.02, 0, 100), (0.03, 0, 100), (0.04, 0, 100), (0.05, 0, 100)])
    cfg = cfg_for(buffer=1500, buffer_policy="red", red=(100.0, 300.0, 0.5, 1.0), red_seed=7)
    log = simulate(tr, make("FIFO"), cfg)
    # expected, step by step (p0 goes to the link; queue seen by p1..p5 = 0, 100, ...):
    rng, avg, count, dropped, q = random.Random(7), 0.0, -1, [], 0
    for i in range(6):
        avg = q                                     # w_q = 1
        if avg < 100:
            drop, count = False, -1
        elif avg >= 300:
            drop, count = True, 0
        else:
            count += 1
            pb = 0.5 * (avg - 100) / 200
            drop = rng.random() < (pb / (1 - count * pb) if count * pb < 1 else 1.0)
            if drop:
                count = 0
        dropped.append(drop)
        if not drop and i > 0:
            q += 100                                # p0 is in service; later admitted packets queue
    assert log.dropped.tolist() == dropped


def test_red_with_unreachable_thresholds_equals_tail_drop():
    cfg_t = SimConfig(TrafficConfig(load=1.2, arrival="onoff", duration=5.0, warmup=0.0), buffer_bytes=40_000)
    cfg_r = SimConfig(cfg_t.traffic, buffer_bytes=40_000, buffer_policy="red", red=(39_999.0, 40_000.0, 0.1, 0.002))
    tr = generate_trace(cfg_t.traffic, 5)
    for name in ("FIFO", "DRR", "DR-DRR"):
        a, b = simulate(tr, make(name), cfg_t), simulate(tr, make(name), cfg_r)
        assert np.array_equal(a.dropped, b.dropped)


def test_red_seed_pairs_runs_and_changes_draws():
    cfg = SimConfig(TrafficConfig(load=1.1, arrival="onoff", duration=5.0, warmup=0.0), buffer_policy="red")
    tr = generate_trace(cfg.traffic, 6)
    a, b = simulate(tr, make("DRR"), cfg), simulate(tr, make("DRR"), cfg)
    c = simulate(tr, make("DRR"), SimConfig(cfg.traffic, buffer_policy="red", red_seed=99))
    assert np.array_equal(a.dropped, b.dropped) and not np.array_equal(a.dropped, c.dropped)


def test_red_drops_early_and_shortens_queues():
    tc = TrafficConfig(load=0.95, arrival="onoff", duration=30.0, warmup=0.0)
    tr = generate_trace(tc, 7)
    tail = simulate(tr, make("FIFO"), SimConfig(tc))
    red = simulate(tr, make("FIFO"), SimConfig(tc, buffer_policy="red"))
    w_t, w_r = (tail.start - tr.t)[~tail.dropped], (red.start - tr.t)[~red.dropped]
    assert red.dropped.sum() > tail.dropped.sum() and np.percentile(w_r, 95) < np.percentile(w_t, 95)


@SETTINGS
@given(sc=scenarios(), seed=st.integers(0, 1000), red=st.sampled_from([(0.0, 3000.0, 0.5, 0.2), (1000.0, 1500.0, 1.0, 1.0),
                                                                       (500.0, 4000.0, 0.1, 0.002)]))
def test_red_matches_reference(sc, seed, red):
    tr, cfg = sc
    if red[1] > cfg.buffer_bytes:
        return
    cfg = SimConfig(cfg.traffic, buffer_bytes=cfg.buffer_bytes, buffer_policy="red", red=red, red_seed=seed)
    rate = cfg.traffic.link_rate
    for ours, ref in [(make("FIFO"), RefFIFO()), (make("SP"), RefSP()), (make("DRR"), RefDRR((1500.0,) * 3)),
                      (make("RL-SP+DRR", rate_frac=0.3), RefRLSP(0.3 * rate / 8, (1500.0,) * 3))]:
        log = simulate(tr, ours, cfg)
        start, dropped = ref_simulate(tr.t, tr.cls, tr.size, rate, cfg.buffer_bytes, "red", ref, red=red, red_seed=seed)
        assert np.array_equal(log.dropped, dropped)
        assert np.array_equal(np.nan_to_num(log.start, nan=-1.0), np.nan_to_num(start, nan=-1.0))


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
@SETTINGS
@given(sc=scenarios())
def test_invariants_under_red(name, sc):
    tr, cfg = sc
    if cfg.buffer_bytes < 4000:
        return
    cfg = SimConfig(cfg.traffic, buffer_bytes=cfg.buffer_bytes, buffer_policy="red",
                    red=(1000.0, float(cfg.buffer_bytes), 0.3, 0.05), update_interval=cfg.update_interval)
    log = simulate(tr, make(name), cfg)
    check_common(tr, log, cfg)
    if name in WORK_CONSERVING:
        check_work_conserving(tr, log)
