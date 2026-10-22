"""Property-based tests: random small scenarios, invariants checked against independent oracles."""
import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import ALL_SCHEDULERS, WORK_CONSERVING, trace_from
from drrsim import SimConfig, TrafficConfig, compute, make, simulate
from drrsim.config import K

SETTINGS = settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@st.composite
def scenarios(draw):
    n = draw(st.integers(0, 60))
    # times on a coarse grid so that exact ties (simultaneous arrivals, completion == arrival) are common
    # "exact" mode: binary-fraction times and a link of 1024 B/s, so packet durations are exact binary
    # fractions too and completion == arrival ties happen often; otherwise decimal grids
    exact = draw(st.booleans())
    grid = 2.0 ** -10 if exact else draw(st.sampled_from([1e-3, 1e-4, 0.0123]))
    rows = [(draw(st.integers(0, 2000 if exact else 200)) * grid, draw(st.integers(0, K - 1)), draw(st.integers(1, 1500)))
            for _ in range(n)]
    policy = draw(st.sampled_from(["shared", "partitioned"]))
    buffer = draw(st.integers(4500 if policy == "partitioned" else 1500, 12_000))
    rate = 8192.0 if exact else draw(st.sampled_from([8e4, 1e6, 1e7]))
    cfg = SimConfig(TrafficConfig(link_rate=rate, warmup=0.0, duration=1.0), buffer_bytes=buffer,
                    buffer_policy=policy, update_interval=draw(st.sampled_from([0.001, 0.01])))
    return trace_from(rows), cfg


def occupancy_oracle(tr, log, cfg):
    """Queued bytes seen by each arriving packet, recomputed from the logs only.

    A packet j is queued when i arrives iff j was admitted, arrived earlier in event order (j < i), and
    starts strictly after i's arrival time (a start at the same instant always precedes the arrival:
    completions and wake-ups are processed before arrivals, and an arrival only starts itself).
    """
    t, c, s = tr.t, tr.cls, tr.size
    admitted = ~log.dropped
    occ = np.zeros(len(t))
    for i in range(len(t)):
        mask = admitted[:i] & (log.start[:i] > t[i])
        if cfg.buffer_policy == "partitioned":
            mask &= c[:i] == c[i]
        occ[i] = s[:i][mask].sum()
    return occ


def check_common(tr, log, cfg):
    n = len(tr)
    rate = cfg.traffic.link_rate / 8
    served = ~log.dropped
    assert log.pending == 0
    assert np.isnan(log.start[log.dropped]).all() and not np.isnan(log.start[served]).any()
    assert n == served.sum() + log.dropped.sum()
    assert (log.start[served] >= tr.t[served]).all()
    f = np.array([cfg.rate_factor(x) for x in log.start[served]]) if cfg.capacity else 1.0
    assert np.allclose(log.end[served] - log.start[served], tr.size[served] / (rate * f))
    order = np.argsort(log.start[served], kind="stable")
    st_, en_ = log.start[served][order], log.end[served][order]
    assert (st_[1:] >= en_[:-1] - 1e-12).all()                         # one packet on the link at a time
    for k in range(K):
        sk = log.start[served & (tr.cls == k)]
        assert (np.diff(sk) >= 0).all()                                 # FIFO within a class
    # tail-drop decisions match the independently recomputed occupancy
    occ = occupancy_oracle(tr, log, cfg)
    limit = cfg.buffer_bytes // K if cfg.buffer_policy == "partitioned" else cfg.buffer_bytes
    if cfg.buffer_policy == "red":           # RED may drop early, but must drop whenever the buffer is full
        assert log.dropped[occ + tr.size > limit].all()
    else:
        assert np.array_equal(log.dropped, occ + tr.size > limit)


def check_work_conserving(tr, log):
    served = ~log.dropped
    order = np.argsort(log.start[served], kind="stable")
    st_, en_ = log.start[served][order], log.end[served][order]
    gaps = [(en_[i], st_[i + 1]) for i in range(len(st_) - 1) if st_[i + 1] > en_[i] + 1e-12]
    waits = [(a, b) for a, b in zip(tr.t[served], log.start[served]) if b > a + 1e-12]
    for g0, g1 in gaps:                    # an idle link while some admitted packet waits is forbidden
        for a, b in waits:
            assert not (a < g1 - 1e-12 and b > g0 + 1e-12)


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
@SETTINGS
@given(sc=scenarios())
def test_invariants_every_scheduler(name, sc):
    tr, cfg = sc
    log = simulate(tr, make(name), cfg)
    check_common(tr, log, cfg)
    if name in WORK_CONSERVING:
        check_work_conserving(tr, log)
    again = simulate(tr, make(name), cfg)                                # deterministic
    assert np.array_equal(np.nan_to_num(again.start, nan=-1), np.nan_to_num(log.start, nan=-1))
    m = compute(tr, log, cfg)                                            # metrics never crash
    assert m["n_delivered"] + m["n_dropped"] == len(tr)


@SETTINGS
@given(sc=scenarios())
def test_work_conserving_schedulers_share_the_same_busy_periods(sc):
    tr, cfg = sc
    cfg = SimConfig(cfg.traffic, buffer_bytes=10**9)                     # no drops: identical workload
    ref = simulate(tr, make("FIFO"), cfg).end
    for name in WORK_CONSERVING:
        assert np.nanmax(simulate(tr, make(name), cfg).end, initial=0) == pytest.approx(np.nanmax(ref, initial=0))


@SETTINGS
@given(sc=scenarios(), r=st.sampled_from([0.1, 0.3, 0.5, 0.9]))
def test_rlsp_class0_never_leaves_before_its_shaped_departure_time(sc, r):
    tr, cfg = sc
    log = simulate(tr, make("RL-SP+DRR", rate_frac=r), cfg)
    rate = r * cfg.traffic.link_rate / 8
    idx = np.flatnonzero((tr.cls == 0) & ~log.dropped)
    d_prev = -np.inf
    for i in idx:                                       # recompute the paper's departure times independently
        d = max(tr.t[i], d_prev + tr.size[i] / rate)
        assert log.start[i] >= d - 1e-12                 # never earlier than the engine tie tolerance TIE_EPS
        d_prev = d


@pytest.mark.parametrize("name", ["DR-DRR", "CQDRR", "FuzzyDRR", "RevenueDRR", "DR-DRR+damping", "CQDRR-draft"])
@SETTINGS
@given(sc=scenarios())
def test_adaptive_quanta_finite_positive_bounded(name, sc):
    tr, cfg = sc
    log = simulate(tr, make(name), cfg)
    if len(log.q_values):
        assert np.isfinite(log.q_values).all() and (log.q_values > 0).all() and log.q_values.max() <= 64000
        assert (np.diff(log.q_times) > 0).all()


@SETTINGS
@given(sc=scenarios())
def test_partitioned_buffer_isolates_classes(sc):
    # in a partitioned buffer, a class's drops depend only on its own traffic and the link schedule;
    # FIFO with a single class present must give the same drops as a shared buffer of size B/3
    tr, cfg = sc
    if cfg.buffer_policy != "partitioned" or len(tr) == 0:
        return
    k = int(tr.cls[0])
    keep = tr.cls == k
    one = trace_from(zip(tr.t[keep], tr.cls[keep], tr.size[keep]))
    part = simulate(one, make("FIFO"), cfg)
    shared = simulate(one, make("FIFO"), SimConfig(cfg.traffic, buffer_bytes=cfg.buffer_bytes // K))
    assert np.array_equal(part.dropped, shared.dropped)
