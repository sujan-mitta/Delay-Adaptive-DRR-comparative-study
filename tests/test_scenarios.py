"""Real-life scenario features (E11): exact, statistical, differential and property tests."""
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from conftest import ALL_SCHEDULERS, WORK_CONSERVING, cfg_for, trace_from
from reference import RefDRR, RefFIFO, RefRLSP, RefSP, ref_simulate
from test_properties import SETTINGS, check_common, check_work_conserving, scenarios
from drrsim import SimConfig, TrafficConfig, generate_trace, make, simulate
from drrsim.traffic import _onoff_periods


# ---------------- validation of the new options ----------------
@pytest.mark.parametrize("kw", [
    dict(on_dist="weibull"), dict(pareto_alpha=1.0), dict(pareto_alpha=0.5), dict(pareto_alpha=float("inf")),
    dict(sync=1), dict(size_override=((64, 64), None)), dict(size_override=((0, 64), None, None)),
    dict(size_override=((100, 50), None, None)), dict(size_override=((64.5, 64.5), None, None)),
    dict(size_override=((1, 70000), None, None)), dict(profile=((5, 1, 2.0, -1),)), dict(profile=((1, 5, -1.0, -1),)),
    dict(profile=((1, 5, 2.0, 3),)), dict(profile=((1, 5, 2.0),)), dict(profile=((1, float("nan"), 2.0, 0),)),
])
def test_scenario_traffic_options_validated(kw):
    with pytest.raises(ValueError):
        TrafficConfig(**kw)


@pytest.mark.parametrize("cap", [((2, 1, 0.5),), ((0, 1, 0.0),), ((0, 1, 1e4),), ((0, 1),), ((0, float("inf"), 0.5),)])
def test_capacity_schedule_validated(cap):
    with pytest.raises(ValueError):
        SimConfig(capacity=cap)


# ---------------- size overrides ----------------
def test_size_override_exact_and_byte_load_preserved():
    tc = TrafficConfig(load=0.8, size_override=((64, 64), None, (9000, 9000)), duration=100.0, warmup=0.0)
    tr = generate_trace(tc, 5)
    assert set(tr.size[tr.cls == 0]) == {64} and set(tr.size[tr.cls == 2]) == {9000}
    s1 = tr.size[tr.cls == 1]
    assert s1.min() >= 1000 and s1.max() <= 1500
    for k, target in enumerate(tc.per_class_load()):
        got = tr.size[tr.cls == k].sum() * 8 / tc.horizon / tc.link_rate
        assert got == pytest.approx(target, rel=0.05)


# ---------------- Pareto ON/OFF ----------------
@pytest.mark.parametrize("dist", ["exp", "pareto"])
def test_onoff_period_means(dist):
    s, e = _onoff_periods(np.random.default_rng(1), 20_000.0, 0.05, 0.5, dist, 1.5)
    on = (e - s)[:-1]
    assert on.mean() == pytest.approx(0.05, rel=0.15 if dist == "pareto" else 0.03)


def test_pareto_periods_are_heavy_tailed():
    s, e = _onoff_periods(np.random.default_rng(2), 20_000.0, 0.05, 0.5, "pareto", 1.5)
    on = (e - s)[:-1]
    s2, e2 = _onoff_periods(np.random.default_rng(2), 20_000.0, 0.05, 0.5, "exp", 1.5)
    on2 = (e2 - s2)[:-1]
    assert (on > 0.5).mean() > 20 * max((on2 > 0.5).mean(), 1e-6)          # P(ON > 10 x mean)
    assert on.min() >= 0.05 * 0.5 / 1.5 - 1e-12                           # Pareto lower bound x_m


# ---------------- synchronised ON/OFF ----------------
def test_sync_all_classes_share_one_onoff_process():
    tc = TrafficConfig(load=0.9, arrival="onoff", sync=True, duration=30.0, warmup=0.0)
    tr = generate_trace(tc, 7)
    s, e = _onoff_periods(np.random.default_rng([7, 99, 7919]), tc.horizon, tc.on_mean, tc.duty)
    idx = np.searchsorted(s, tr.t, side="right") - 1
    assert (idx >= 0).all() and (tr.t < e[idx]).all()                     # every packet inside a shared ON period
    unsynced = generate_trace(TrafficConfig(load=0.9, arrival="onoff", duration=30.0, warmup=0.0), 7)
    assert tr.digest() != unsynced.digest()


# ---------------- load profiles ----------------
def test_profile_scales_rate_inside_segment_only():
    tc = TrafficConfig(class_loads=(0.0, 0.3, 0.0), arrival="poisson", warmup=0.0, duration=200.0,
                       profile=((50.0, 150.0, 3.0, 1),))
    t = generate_trace(tc, 8).t
    inside = ((t >= 50) & (t < 150)).sum() / 100.0
    outside = ((t < 50) | (t >= 150)).sum() / 100.0
    assert inside / outside == pytest.approx(3.0, rel=0.05)


def test_profile_factor_zero_silences_and_other_classes_untouched():
    base = TrafficConfig(load=0.9, arrival="onoff", warmup=0.0, duration=20.0)
    prof = TrafficConfig(load=0.9, arrival="onoff", warmup=0.0, duration=20.0, profile=((5.0, 10.0, 0.0, 1),))
    a, b = generate_trace(base, 9), generate_trace(prof, 9)
    vb = b.t[b.cls == 1]
    assert not ((vb >= 5) & (vb < 10)).any()
    for k in (0, 2):
        assert np.array_equal(a.t[a.cls == k], b.t[b.cls == k]) and np.array_equal(a.size[a.cls == k], b.size[b.cls == k])


# ---------------- capacity schedule ----------------
def test_capacity_fade_exact_and_non_preemptive():
    # link 1000 B/s; factor 0.5 during [1, 2). 100-B packets.
    tr = trace_from([(0.95, 0, 100), (1.5, 0, 100), (1.95, 0, 100), (2.5, 0, 100)])
    log = simulate(tr, make("FIFO"), cfg_for(capacity=((1.0, 2.0, 0.5),), duration=3.0))
    assert log.start.tolist() == pytest.approx([0.95, 1.5, 1.95, 2.5])
    # started before the fade: full rate; inside: half rate; at 1.95 still inside -> 0.2 s; after: full rate
    assert (log.end - log.start).tolist() == pytest.approx([0.1, 0.2, 0.2, 0.1])


def test_capacity_boundary_is_half_open():
    tr = trace_from([(1.0, 0, 100), (2.0, 0, 100)])
    log = simulate(tr, make("FIFO"), cfg_for(capacity=((1.0, 2.0, 0.5),), duration=3.0))
    assert (log.end - log.start).tolist() == pytest.approx([0.2, 0.1])


caps = st.lists(st.tuples(st.integers(0, 150), st.integers(1, 100), st.sampled_from([0.1, 0.25, 0.5, 2.0])),
                max_size=3).map(lambda xs: tuple((a * 2.0 ** -10, (a + b) * 2.0 ** -10, f) for a, b, f in xs))


def with_capacity(cfg, cap):
    return SimConfig(cfg.traffic, buffer_bytes=cfg.buffer_bytes, buffer_policy=cfg.buffer_policy,
                     update_interval=cfg.update_interval, capacity=cap)


@SETTINGS
@given(sc=scenarios(), cap=caps, q=st.sampled_from([(1500.0,) * 3, (100.0, 1500.0, 9000.0)]),
       r=st.sampled_from([0.2, 0.5]))
def test_capacity_matches_reference(sc, cap, q, r):
    tr, cfg = sc
    cfg = with_capacity(cfg, cap)
    for ours, ref in [(make("FIFO"), RefFIFO()), (make("SP"), RefSP()), (make("DRR", quanta=q), RefDRR(q)),
                      (make("RL-SP+DRR", rate_frac=r), RefRLSP(r * cfg.traffic.link_rate / 8, (1500.0,) * 3))]:
        log = simulate(tr, ours, cfg)
        start, dropped = ref_simulate(tr.t, tr.cls, tr.size, cfg.traffic.link_rate, cfg.buffer_bytes,
                                      cfg.buffer_policy, ref, capacity=cap)
        assert np.array_equal(log.dropped, dropped)
        assert np.array_equal(np.nan_to_num(log.start, nan=-1.0), np.nan_to_num(start, nan=-1.0))


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
@SETTINGS
@given(sc=scenarios(), cap=caps)
def test_invariants_with_capacity_schedule(name, sc, cap):
    tr, cfg = sc
    cfg = with_capacity(cfg, cap)
    log = simulate(tr, make(name), cfg)
    check_common(tr, log, cfg)
    if name in WORK_CONSERVING:
        check_work_conserving(tr, log)


# ---------------- every E11 scenario runs cleanly for every scheduler ----------------
def test_e11_definition():
    from drrsim.experiments import SCENARIOS, experiment_tasks, load_tuned
    t = experiment_tasks("E11", load_tuned())
    assert len(SCENARIOS) == 8 and len(t) == 8 * 9 * 20 and len({x["point"] for x in t}) == 8


@pytest.mark.parametrize("scenario", ["jumbo", "tiny", "heavy-tail", "sync", "flash-crowd", "link-fade", "abuse", "ramp"])
def test_each_scenario_short_run_all_schedulers(scenario):
    from dataclasses import replace
    from drrsim.experiments import SCENARIOS, load_tuned
    tuned = load_tuned()
    cfg = SCENARIOS[scenario]
    short = SimConfig(replace(cfg.traffic, duration=4.0, warmup=0.0,
                              profile=tuple((a / 15, b / 15, f, c) for a, b, f, c in cfg.traffic.profile)),
                      buffer_bytes=cfg.buffer_bytes, capacity=tuple((a / 15, b / 15, f) for a, b, f in cfg.capacity))
    tr = generate_trace(short.traffic, 1)
    for name in ALL_SCHEDULERS:
        log = simulate(tr, make(name, **tuned.get(name, {})), short)
        check_common(tr, log, short)
