"""Hostile, out-of-bound and extreme inputs: every bad input must be refused with a clear ValueError,
and every accepted input must simulate correctly and terminate."""
import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import ALL_SCHEDULERS, cfg_for, trace_from
from test_properties import check_common
from drrsim import SimConfig, TrafficConfig, compute, generate_trace, make, simulate
from drrsim.schedulers import REGISTRY
from drrsim.traffic import Trace

FUZZ = settings(max_examples=120, deadline=None, suppress_health_check=list(HealthCheck), database=None)


def raw_trace(t, c, s, tdtype=float, cdtype=np.int8, sdtype=np.int32):
    return Trace(np.array(t, dtype=tdtype), np.array(c, dtype=cdtype), np.array(s, dtype=sdtype))


# ---------------- hostile traces ----------------
@pytest.mark.parametrize("trace,msg", [
    (raw_trace([0.5, 0.1], [0, 0], [100, 100]), "sorted"),
    (raw_trace([0.0, math.nan], [0, 0], [100, 100]), "finite"),
    (raw_trace([0.0, math.inf], [0, 0], [100, 100]), "finite"),
    (raw_trace([-1.0, 0.0], [0, 0], [100, 100]), ">= 0"),
    (raw_trace([0.0], [7], [100]), "class indices"),
    (raw_trace([0.0], [-1], [100]), "class indices"),
    (raw_trace([0.0], [0.5], [100], cdtype=float), "class indices"),
    (raw_trace([0.0, 0.0], [0, 0], [0, 100]), "sizes"),
    (raw_trace([0.0], [0], [-5]), "sizes"),
    (raw_trace([0.0], [0], [99.5], sdtype=float), "sizes"),
    (Trace(np.array([0.0, 1.0]), np.array([0], np.int8), np.array([100, 100], np.int32)), "equal length"),
    (Trace(np.zeros((2, 2)), np.zeros((2, 2), np.int8), np.zeros((2, 2), np.int32)), "1-D"),
])
@pytest.mark.parametrize("name", ["FIFO", "DRR", "SCRR", "DR-DRR"])
def test_hostile_traces_are_refused(trace, msg, name):
    with pytest.raises(ValueError, match=msg):
        simulate(trace, make(name), cfg_for())


# ---------------- hostile configurations ----------------
BAD_TRAFFIC = [dict(load=math.inf), dict(load=math.nan), dict(link_rate=math.inf), dict(duration=math.inf),
               dict(warmup=math.nan), dict(on_mean=math.inf), dict(duty=math.nan), dict(mix=(math.nan, 0.5, 0.5)),
               dict(class_loads=(math.inf, 0, 0)), dict(load="0.5"), dict(load=None)]


@pytest.mark.parametrize("kw", BAD_TRAFFIC)
def test_hostile_traffic_configs_are_refused(kw):
    with pytest.raises((ValueError, TypeError)):
        TrafficConfig(**kw)


@pytest.mark.parametrize("kw", [dict(buffer_bytes=math.nan), dict(buffer_bytes=125000.5), dict(buffer_bytes="1e5"),
                                dict(buffer_bytes=True), dict(update_interval=math.inf), dict(starvation_T=math.nan),
                                dict(update_interval=-1.0)])
def test_hostile_sim_configs_are_refused(kw):
    with pytest.raises(ValueError):
        SimConfig(**kw)


def test_absurd_scale_is_refused_before_allocating():
    with pytest.raises(ValueError, match="packets"):
        generate_trace(TrafficConfig(load=1e6, duration=10.0), 1)
    with pytest.raises(ValueError, match="quantum updates"):
        simulate(trace_from([(0.0, 0, 100)]), make("DR-DRR"), cfg_for(update_interval=1e-9, duration=60.0))


# ---------------- fuzzing every scheduler parameter ----------------
garbage = st.one_of(
    st.floats(allow_nan=True, allow_infinity=True), st.integers(-10**12, 10**12),
    st.sampled_from([0, 0.0, -0.0, 1e-300, 1e300, -1e-300, 0.009, 0.01, 1e9, 1e9 + 1, 0.5, 1.0, 2.0]),
    st.none(), st.booleans(), st.text(max_size=3))
vec_garbage = st.one_of(garbage, st.lists(garbage, max_size=4), st.tuples(garbage, garbage, garbage),
                        st.tuples(*[st.floats(0.005, 2e9)] * 3))
FUZZ_TRACE_CFG = SimConfig(TrafficConfig(load=1.3, arrival="onoff", duration=1.5, warmup=0.0), buffer_bytes=40_000)
FUZZ_TRACE = generate_trace(FUZZ_TRACE_CFG.traffic, 3)


@st.composite
def fuzzed_params(draw, name):
    defaults = REGISTRY[name].defaults
    keys = draw(st.lists(st.sampled_from(sorted(defaults)), unique=True)) if defaults else []
    return {k: draw(vec_garbage if isinstance(defaults[k], tuple) else garbage) for k in keys}


@pytest.mark.parametrize("name", [n for n in ALL_SCHEDULERS if REGISTRY[n].defaults])
@FUZZ
@given(data=st.data())
def test_fuzzed_parameters_are_refused_or_simulate_correctly(name, data):
    params = data.draw(fuzzed_params(name))
    try:
        sched = make(name, **params)
    except ValueError:
        return                                            # refused cleanly: fine
    log = simulate(FUZZ_TRACE, sched, FUZZ_TRACE_CFG)     # accepted: must terminate and be correct
    check_common(FUZZ_TRACE, log, FUZZ_TRACE_CFG)
    if len(log.q_values):
        assert np.isfinite(log.q_values).all() and (log.q_values > 0).all()
    m = compute(FUZZ_TRACE, log, FUZZ_TRACE_CFG)
    assert all(not isinstance(v, float) or not math.isinf(v) for v in m.values())


@FUZZ
@given(load=st.floats(1e-4, 20), rate=st.floats(1e3, 1e9), duty=st.floats(0.05, 1.0), on=st.floats(1e-4, 5.0),
       arrival=st.sampled_from(["poisson", "onoff"]), seed=st.integers(0, 2**32 - 1))
def test_fuzzed_traffic_configs_generate_valid_traces(load, rate, duty, on, arrival, seed):
    tc = TrafficConfig(load=load, link_rate=rate, duty=duty, on_mean=on, arrival=arrival, warmup=0.0,
                       duration=min(2.0, 2e5 / (load * rate / 8 / 200 + 1)))
    try:
        tr = generate_trace(tc, seed)
    except ValueError:
        return
    tr.validate()
    assert len(tr) == 0 or (tr.t.min() >= 0 and tr.t.max() < tc.horizon)


# ---------------- extreme but valid real-world inputs ----------------
@pytest.mark.parametrize("name", ALL_SCHEDULERS)
@pytest.mark.parametrize("case", ["overload_x50", "trickle", "slow_link", "fast_link", "one_packet_buffer",
                                  "jumbo", "one_byte_packets", "burst_10k", "tie_storm"])
def test_extreme_but_valid_inputs(name, case):
    if case == "overload_x50":
        cfg = SimConfig(TrafficConfig(load=50.0, arrival="onoff", duration=0.3, warmup=0.0))
        tr = generate_trace(cfg.traffic, 1)
    elif case == "trickle":
        cfg = SimConfig(TrafficConfig(load=1e-4, duration=30.0, warmup=0.0))
        tr = generate_trace(cfg.traffic, 1)
    elif case == "slow_link":                                             # 1 kb/s: a 1500 B packet takes 12 s
        cfg = SimConfig(TrafficConfig(load=0.9, link_rate=1e3, duration=300.0, warmup=0.0))
        tr = generate_trace(cfg.traffic, 1)
    elif case == "fast_link":                                             # 100 Gb/s
        cfg = SimConfig(TrafficConfig(load=0.9, link_rate=1e11, duration=2e-4, warmup=0.0))
        tr = generate_trace(cfg.traffic, 1)
    elif case == "one_packet_buffer":
        cfg = SimConfig(TrafficConfig(load=1.2, arrival="onoff", duration=2.0, warmup=0.0), buffer_bytes=1500)
        tr = generate_trace(cfg.traffic, 1)
    elif case == "jumbo":                                                 # 9000 B frames, quanta stay 1500 B
        rng = np.random.default_rng(2)
        tr = trace_from((float(t), int(rng.integers(0, 3)), 9000) for t in np.sort(rng.uniform(0, 1, 400)))
        cfg = cfg_for(link_rate=1e7, buffer=100_000, duration=1.0)
    elif case == "one_byte_packets":
        rng = np.random.default_rng(3)
        tr = trace_from((float(t), int(rng.integers(0, 3)), 1) for t in np.sort(rng.uniform(0, 1, 3000)))
        cfg = cfg_for(link_rate=8e3, buffer=1500, duration=1.0)
    elif case == "burst_10k":                                             # everything at the same instant
        tr = trace_from((0.0, i % 3, 1 + (i * 37) % 1500) for i in range(10_000))
        cfg = cfg_for(link_rate=1e7, buffer=10**9, duration=1.0)
    else:                                                                 # every arrival lands on a completion time
        tr = trace_from((k * 2.0 ** -10, k % 3, 128) for k in range(2000))
        cfg = cfg_for(link_rate=8.0 * 128 * 1024, buffer=1500, duration=2.0)
    log = simulate(tr, make(name), cfg)
    check_common(tr, log, cfg)
    if len(log.q_values):
        assert np.isfinite(log.q_values).all() and (log.q_values > 0).all()
    compute(tr, log, cfg)


def test_extreme_update_intervals():
    tr = generate_trace(TrafficConfig(load=1.0, arrival="onoff", duration=3.0, warmup=0.0), 4)
    for dt in (1e-5, 100.0):                       # 300k updates, or none at all within the run
        cfg = SimConfig(TrafficConfig(load=1.0, arrival="onoff", duration=3.0, warmup=0.0), update_interval=dt)
        for name in ("DR-DRR", "CQDRR", "FuzzyDRR", "RevenueDRR"):
            log = simulate(tr, make(name), cfg)
            check_common(tr, log, cfg)
