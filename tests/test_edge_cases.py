"""Edge cases and boundary conditions, module by module."""
import math

import numpy as np
import pytest

from conftest import ALL_SCHEDULERS, WORK_CONSERVING, cfg_for, trace_from
from drrsim import SimConfig, TrafficConfig, compute, generate_trace, make, simulate
from drrsim.config import CLASSES, K
from drrsim.engine import RunLog
from drrsim.metrics import jain, maxmin_share, starvation_gaps
from drrsim.schedulers import FUZZY_RULES, REGISTRY, _memberships, alpha_fair, mm1k_blocking


# ============================== config ==============================
@pytest.mark.parametrize("kw", [
    dict(load=0.0), dict(load=-1.0), dict(link_rate=0.0), dict(duration=0.0), dict(warmup=-1.0),
    dict(duty=0.0), dict(duty=1.5), dict(on_mean=0.0), dict(mix=(0.5, 0.5)), dict(mix=(1.2, -0.1, -0.1)),
    dict(class_loads=(0.1, 0.1)), dict(class_loads=(0.1, -0.1, 0.1)), dict(arrival="uniform"),
])
def test_traffic_config_rejects(kw):
    with pytest.raises(ValueError):
        TrafficConfig(**kw)


@pytest.mark.parametrize("kw", [
    dict(buffer_bytes=1499), dict(update_interval=0.0), dict(starvation_T=0.0),
    dict(buffer_policy="codel"), dict(buffer_bytes=4499, buffer_policy="partitioned"),
])
def test_sim_config_rejects(kw):
    with pytest.raises(ValueError):
        SimConfig(**kw)


def test_config_accepts_boundaries():
    TrafficConfig(duty=1.0, warmup=0.0, mix=(1.0, 0.0, 0.0), class_loads=(0.0, 0.0, 0.5))
    SimConfig(buffer_bytes=1500)
    SimConfig(buffer_bytes=4500, buffer_policy="partitioned")


def test_config_helpers():
    tc = TrafficConfig(load=0.5, mix=(0.2, 0.3, 0.5), warmup=2, duration=3)
    assert tc.horizon == 5
    assert tc.per_class_load() == pytest.approx((0.1, 0.15, 0.25))
    assert TrafficConfig(class_loads=(0.8, 0.2, 0.3)).per_class_load() == (0.8, 0.2, 0.3)
    assert tc.key() == TrafficConfig(load=0.5, mix=(0.2, 0.3, 0.5), warmup=2, duration=3).key()
    assert tc.key() != TrafficConfig(load=0.51, mix=(0.2, 0.3, 0.5), warmup=2, duration=3).key()
    c = SimConfig().with_traffic(load=0.33)
    assert c.traffic.load == 0.33 and c.buffer_bytes == SimConfig().buffer_bytes


# ============================== traffic ==============================
def test_zero_load_class_has_no_packets():
    tr = generate_trace(TrafficConfig(class_loads=(0.0, 0.5, 0.0), duration=5, warmup=0), 3)
    assert set(np.unique(tr.cls)) == {1}


@pytest.mark.parametrize("arrival", ["poisson", "onoff"])
def test_tiny_horizon_and_empty_trace(arrival):
    tr = generate_trace(TrafficConfig(arrival=arrival, load=0.01, duration=1e-6, warmup=0), 1)
    assert len(tr) <= 2


def test_onoff_with_duty_one_equals_poisson():
    a = generate_trace(TrafficConfig(arrival="poisson", duration=5, warmup=0), 9)
    b = generate_trace(TrafficConfig(arrival="onoff", duty=1.0, duration=5, warmup=0), 9)
    assert a.digest() == b.digest()


def test_packet_sizes_within_class_bounds_and_hit_both_ends():
    tr = generate_trace(TrafficConfig(duration=60, warmup=0), 2)
    for k, c in enumerate(CLASSES):
        s = tr.size[tr.cls == k]
        assert s.min() >= c.size_min and s.max() <= c.size_max
        if c.size_min != c.size_max:
            assert s.min() == c.size_min and s.max() == c.size_max


def test_trace_ties_ordered_by_class():
    tr = trace_from([(0.0, 2, 100), (0.0, 0, 100), (0.0, 1, 100)])
    assert tr.cls.tolist() == [0, 1, 2]


def test_classes_independent_streams():
    # changing one class's load must not change another class's arrivals (per-class RNG streams)
    a = generate_trace(TrafficConfig(class_loads=(0.2, 0.3, 0.3), duration=5, warmup=0), 4)
    b = generate_trace(TrafficConfig(class_loads=(0.2, 0.3, 0.9), duration=5, warmup=0), 4)
    for k in (0, 1):
        assert np.array_equal(a.t[a.cls == k], b.t[b.cls == k])


def test_seeds_give_different_traces_for_many_seeds():
    tc = TrafficConfig(duration=1, warmup=0)
    digests = {generate_trace(tc, s).digest() for s in range(30)}
    assert len(digests) == 30


# ============================== engine ==============================
@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_empty_trace_every_scheduler(name):
    tr = trace_from([])
    log = simulate(tr, make(name), cfg_for())
    assert log.decisions == 0 and log.pending == 0 and len(log.start) == 0
    m = compute(tr, log, cfg_for())
    assert m["n_packets"] == 0 and m["tput_total"] == 0
    assert math.isnan(m["lat_p95"]) and math.isnan(m["jain"])


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_single_packet_every_scheduler(name):
    tr = trace_from([(0.25, 1, 500)])
    log = simulate(tr, make(name), cfg_for())
    assert log.start.tolist() == [0.25] and log.end.tolist() == [0.75]


def test_buffer_exactly_full_is_admitted_one_more_byte_is_dropped():
    # link 1000 B/s; p0 goes straight to the link; p1 fills the 1500 B buffer exactly; p2 overflows
    tr = trace_from([(0.0, 2, 1500), (0.1, 2, 1500), (0.2, 2, 1)])
    log = simulate(tr, make("FIFO"), cfg_for(buffer=1500))
    assert log.dropped.tolist() == [False, False, True]


def test_partitioned_exact_boundary():
    # partition = 4500 // 3 = 1500 per class; class 1 fills its own partition, class 0 still admitted
    tr = trace_from([(0.0, 2, 1500), (0.1, 1, 1500), (0.2, 1, 1), (0.3, 0, 1500)])
    log = simulate(tr, make("FIFO"), cfg_for(buffer=4500, buffer_policy="partitioned"))
    assert log.dropped.tolist() == [False, False, True, False]


def test_packet_in_service_does_not_count_against_buffer():
    tr = trace_from([(0.0, 0, 1500), (0.0, 0, 1500)])
    log = simulate(tr, make("FIFO"), cfg_for(buffer=1500))
    assert not log.dropped.any()


def test_completion_before_arrival_at_equal_time():
    # p0 ends exactly when two packets arrive; the completion is processed first
    tr = trace_from([(0.0, 0, 1500), (0.5, 0, 1500), (1.5, 0, 1500), (1.5, 0, 1500)])
    log = simulate(tr, make("FIFO"), cfg_for(buffer=1500))
    # p1 starts at 1.5 (completion first); p2 then fits the empty buffer, p3 overflows it
    assert log.start[1] == 1.5 and log.dropped.tolist() == [False, False, False, True]


def test_no_drain_leaves_pending_and_never_serves_after_horizon():
    tr = trace_from([(0.0, 0, 1000)] + [(0.0001 * i, 1, 1000) for i in range(1, 6)])
    cfg = cfg_for(duration=2.0, drain=False)
    log = simulate(tr, make("DRR"), cfg)
    assert log.pending > 0
    assert np.nanmax(log.start) <= 2.0
    assert len(tr) == (~np.isnan(log.start)).sum() + log.dropped.sum() + log.pending


def test_adaptive_update_clock_is_regular_including_idle_time():
    tr = trace_from([(0.0, 0, 100), (0.5, 0, 100)])
    log = simulate(tr, make("DR-DRR"), cfg_for())
    d = np.diff(log.q_times)
    assert np.allclose(d, 0.01) and log.q_times[0] == pytest.approx(0.01)


def test_engine_rejects_idle_scheduler_without_wake():
    class Stuck(REGISTRY["FIFO"]):
        def select(self, now):
            return None

        def wake_time(self):
            return 0.0
    with pytest.raises(RuntimeError):
        simulate(trace_from([(0.0, 0, 100)]), Stuck(), cfg_for())


def test_simultaneous_burst_of_many_packets():
    tr = trace_from([(0.0, i % 3, 100) for i in range(300)])
    log = simulate(tr, make("DRR"), cfg_for(buffer=10**6))
    assert (~np.isnan(log.start)).all() and log.end.max() == pytest.approx(300 * 0.1)


# ============================== schedulers ==============================
@pytest.mark.parametrize("name", WORK_CONSERVING)
@pytest.mark.parametrize("only", [0, 1, 2])
def test_single_class_traffic_equals_fifo(name, only):
    rng = np.random.default_rng(only)
    tr = trace_from([(float(t), only, int(rng.integers(64, 1501))) for t in np.sort(rng.uniform(0, 2, 200))])
    cfg = cfg_for(link_rate=80_000.0, buffer=10**6, duration=3.0)
    ref = simulate(tr, make("FIFO"), cfg).start
    assert np.array_equal(simulate(tr, make(name), cfg).start, ref)


def test_unknown_scheduler_and_parameter():
    with pytest.raises(KeyError):
        make("WFQ")
    for name in ALL_SCHEDULERS:
        with pytest.raises(ValueError):
            make(name, definitely_not_a_parameter=1)


def test_drr_one_byte_quantum_still_progresses():
    tr = trace_from([(0.0, 0, 1500), (0.0, 1, 1500), (0.0, 2, 1500)])
    log = simulate(tr, make("DRR", quanta=(1, 1, 1)), cfg_for())
    assert (~np.isnan(log.start)).all()


def test_rlsp_rejects_nonpositive_rate():
    for r in (0.0, -0.1):
        with pytest.raises(ValueError):
            simulate(trace_from([(0.0, 0, 100)]), make("RL-SP+DRR", rate_frac=r), cfg_for())


def test_rlsp_idle_class0_gets_no_burst_credit():
    # after a long idle period, two back-to-back class-0 packets are still spaced by size / r
    tr = trace_from([(0.0, 0, 100), (5.0, 0, 100), (5.0, 0, 100)])
    log = simulate(tr, make("RL-SP+DRR", rate_frac=0.5), cfg_for(duration=6.0))
    assert log.start.tolist() == pytest.approx([0.0, 5.0, 5.2])


def test_cqdrr_tiny_quantum_regression():
    # regression test for the fixed iteration cap (quanta far below the packet size)
    tr = trace_from([(0.05, 2, 1500)] * 3 + [(0.05, 1, 1500)] * 2)
    for q in (5.0, 0.5, 0.1):          # 0.1 B needs ~45 000 visits: exercises the lazily computed bound
        log = simulate(tr, make("CQDRR", qmin=q, qmax=q), cfg_for())
        assert (~np.isnan(log.start)).all()


@pytest.mark.parametrize("alpha", [0.0, 0.5, 1.0, 2.0])
def test_cqdrr_alpha_fair_variants_stay_bounded(alpha):
    cfg = SimConfig(TrafficConfig(load=1.3, arrival="onoff", duration=4, warmup=0))
    tr = generate_trace(cfg.traffic, 1)
    log = simulate(tr, make("CQDRR", alpha_fair=alpha), cfg)
    assert np.isfinite(log.q_values).all() and log.q_values.min() >= 64 and log.q_values.max() <= 64000


def test_alpha_fair_and_blocking_helpers():
    assert alpha_fair(1.0, 1) == 0.0 and alpha_fair(2.0, 0) == 2.0 and alpha_fair(4.0, 0.5) == pytest.approx(4.0)
    for rho in (0.0, 0.3, 0.999999, 1.0, 1.000001, 3.0, 1e6):
        for k in (1, 10, 1000):
            b = mm1k_blocking(rho, k)
            assert 0.0 <= b <= 1.0 and math.isfinite(b)
    assert mm1k_blocking(0.999999, 10) == pytest.approx(1 / 11, rel=1e-4)   # continuity at rho = 1


def test_fuzzy_memberships_partition_of_unity_and_rule_table_shape():
    for x in np.linspace(0, 1, 201):
        mu = _memberships(float(x))
        assert all(m >= 0 for m in mu) and sum(mu) == pytest.approx(1.0)
    assert _memberships(-1.0) == (1.0, 0.0, 0.0) and _memberships(2.0) == (0.0, 0.0, 1.0)
    assert len(FUZZY_RULES) == 3 and all(len(r) == 3 for r in FUZZY_RULES)


def test_fuzzy_multiplier_monotone_in_both_inputs():
    f = make("FuzzyDRR")
    grid = np.linspace(0, 1, 21)
    for x in grid:
        ys = [f.multiplier(float(x), float(y)) for y in grid]
        assert all(b >= a - 1e-12 for a, b in zip(ys, ys[1:]))
    for y in grid:
        xs = [f.multiplier(float(x), float(y)) for x in grid]
        assert all(b >= a - 1e-12 for a, b in zip(xs, xs[1:]))


def test_revenue_extreme_guarantees_stay_bounded():
    cfg = SimConfig(TrafficConfig(load=1.2, arrival="onoff", duration=3, warmup=0))
    tr = generate_trace(cfg.traffic, 2)
    for g in (0.0, 5.0):
        log = simulate(tr, make("RevenueDRR", guar_scale=g), cfg)
        assert log.q_values.min() >= 150 and log.q_values.max() <= 4500


def test_scrr_virtual_clock_never_goes_backwards():
    cfg = SimConfig(TrafficConfig(load=1.1, arrival="onoff", duration=3, warmup=0))
    tr = generate_trace(cfg.traffic, 3)
    sch = make("SCRR")
    clocks = []
    orig = sch.select

    def spy(now):
        c = orig(now)
        clocks.append(sch.virtual_clock)
        return c
    sch.select = spy
    simulate(tr, sch, cfg)
    assert all(b >= a for a, b in zip(clocks, clocks[1:]))


# ============================== metrics ==============================
def handmade_log(start, end, dropped, q_times=(), q_values=None):
    n = len(start)
    return RunLog(np.array(start, float), np.array(end, float), np.array(dropped, bool),
                  np.array(q_times, float), np.array(q_values if q_values is not None else [], float).reshape(-1, K),
                  decisions=n, wall_time=1.0, pending=0)


def test_metrics_only_count_the_measurement_window():
    tr = trace_from([(0.5, 0, 100), (1.5, 0, 100), (3.5, 0, 100)])   # window = [1, 3)
    cfg = cfg_for(warmup=1.0, duration=2.0)
    log = handmade_log([0.5, 1.6, 3.5], [0.6, 1.7, 3.6], [0, 0, 0])
    m = compute(tr, log, cfg)
    assert m["lat_offered"] == 1 and m["lat_delay_mean"] == pytest.approx(0.1)
    assert m["lat_tput"] == pytest.approx(100 * 8 / 2.0)


def test_metrics_class_without_packets_is_nan_not_crash():
    tr = trace_from([(0.1, 0, 100)])
    m = compute(tr, handmade_log([0.1], [0.2], [0]), cfg_for())
    assert m["vid_offered"] == 0 and math.isnan(m["vid_p95"]) and math.isnan(m["vid_drop_rate"]) and m["vid_tput"] == 0


def test_starvation_threshold_is_strict():
    # class 0: arrives 0, served at exactly T = 0.1 -> gap == T, not counted; at 0.1+eps -> counted
    for s0, expect in [(0.1, 0), (0.1000001, 1)]:
        tr = trace_from([(0.0, 0, 100)])
        m = compute(tr, handmade_log([s0], [s0 + 0.1], [0]), cfg_for())
        assert m["lat_starv_count"] == expect


def test_starvation_gap_starts_after_previous_service():
    arr = np.array([0.0, 0.0])
    gs, gap = starvation_gaps(arr, np.array([0.0, 0.5]), np.array([0.1, 0.6]))
    assert gs.tolist() == [0.0, 0.1] and gap.tolist() == pytest.approx([0.0, 0.4])


def test_oscillation_metrics_hand_values():
    tr = trace_from([(0.1, 0, 100)])
    q = [[1500, 1500, 1500], [3000, 1500, 1500], [1500, 1500, 1500], [3000, 1500, 1500]]
    m = compute(tr, handmade_log([0.1], [0.2], [0], [0.1, 0.2, 0.3, 0.4], q), cfg_for())
    assert m["lat_osc_mag"] == pytest.approx(1.0)          # |dQ| = 1500 each step, / base 1500
    assert m["lat_osc_flips"] == pytest.approx(2 / 1.0)     # +, -, + -> 2 sign flips over 1 s
    assert m["vid_osc_mag"] == 0 and m["vid_osc_flips"] == 0


def test_maxmin_and_jain_edges():
    assert np.allclose(maxmin_share([0, 0, 0], 10), [0, 0, 0])
    assert np.allclose(maxmin_share([5, 5, 5], 0), [0, 0, 0])
    assert np.allclose(maxmin_share([2, 2, 100], 10), [2, 2, 6])
    assert np.allclose(maxmin_share([4, 4, 4], 12), [4, 4, 4])
    assert math.isnan(jain([0, 0])) and jain([5]) == 1.0
    assert jain([1, 2, 3]) == pytest.approx(36 / (3 * 14))


def test_delay_percentiles_with_one_sample():
    tr = trace_from([(0.1, 2, 100)])
    m = compute(tr, handmade_log([0.3], [0.4], [0]), cfg_for())
    assert m["blk_p95"] == pytest.approx(0.2) and m["blk_p99"] == pytest.approx(0.2)


def test_wake_is_processed_before_an_arrival_at_the_same_instant():
    # link 1000 B/s, RL-SP shaper 500 B/s: class-0 p1 (1400 B) is held until exactly t = 2.8 and fills the
    # 1500 B buffer; p2 (class 1, 500 B) arrives at exactly 2.8. Wake first: p1 leaves the buffer, p2 fits.
    tr = trace_from([(0.0, 0, 100), (0.0, 0, 1400), (2.8, 1, 500)])
    log = simulate(tr, make("RL-SP+DRR", rate_frac=0.5), cfg_for(buffer=1500, duration=5.0))
    assert log.start[1] == 2.8 and not log.dropped.any() and log.start[2] == pytest.approx(4.2)


def test_oscillation_flip_count_ignores_unchanged_steps():
    tr = trace_from([(0.1, 0, 100)])
    q = [[1500, 1500, 1500], [3000, 1500, 1500], [3000, 1500, 1500], [1500, 1500, 1500]]   # +, 0, -
    m = compute(tr, handmade_log([0.1], [0.2], [0], [0.1, 0.2, 0.3, 0.4], q), cfg_for())
    assert m["lat_osc_flips"] == pytest.approx(1.0)          # one reversal; the flat step is not a flip
