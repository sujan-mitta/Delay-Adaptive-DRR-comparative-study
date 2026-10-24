"""Adversarial search for a counterexample to Proposition 1 (docs/PROPOSITION.md): the head-of-line wait of any backlogged
class never exceeds G_i = 8 * sum_{j != i} (M Q0 + L_j - 1) / C when Q0 <= Q_j <= M Q0 and Q0 >= every packet."""
import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from drrsim import SimConfig, TrafficConfig, make, simulate
from drrsim.metrics import starvation_gaps
from drrsim.traffic import Trace

Q0 = 1500
VARIANTS = ["DR-DRR", "DR-DRR+damping", "DR-DRR-backlog", "DR-DRR-hol"]
SIZES = [1, 40, 576, 1499, 1500]


@st.composite
def scenario(draw):
    n = draw(st.integers(1, 90))
    grid = draw(st.sampled_from([1e-4, 1e-3, 0.0123]))          # coarse grid: simultaneous arrivals are common
    t = sorted(draw(st.integers(0, 60)) * grid for _ in range(n))
    cls = [draw(st.integers(0, 2)) for _ in range(n)]
    size = [draw(st.sampled_from(SIZES)) for _ in range(n)]
    return t, cls, size


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(sc=scenario(), name=st.sampled_from(VARIANTS), M=st.sampled_from([1.0, 2.0, 8.0, 20.0]),
       kappa=st.sampled_from([0.0, 4.0, 100.0]), theta=st.sampled_from([0.0, 0.5]),
       rate=st.sampled_from([2e5, 1e6, 1e7]), update=st.sampled_from([0.001, 0.01]))
def test_no_counterexample_to_the_service_gap_bound(sc, name, M, kappa, theta, rate, update):
    t, cls, size = sc
    o = np.lexsort((cls, t))
    tr = Trace(np.asarray(t, float)[o], np.asarray(cls, np.int8)[o], np.asarray(size, np.int32)[o])
    cfg = SimConfig(TrafficConfig(link_rate=rate, warmup=0.0, duration=1.0), buffer_bytes=10 ** 9, update_interval=update)
    log = simulate(tr, make(name, qmax_mult=M, kappa=kappa, theta=theta), cfg)
    lmax = [int(tr.size[tr.cls == c].max()) if np.any(tr.cls == c) else 0 for c in range(3)]
    for c in range(3):
        idx = np.flatnonzero(tr.cls == c)
        if not len(idx):
            continue
        _, gap = starvation_gaps(tr.t[idx], log.start[idx], log.end[idx])
        bound = sum(M * Q0 + lmax[j] - 1 for j in range(3) if j != c) * 8 / rate
        assert gap.max() <= bound * (1 + 1e-9), (name, c, gap.max(), bound)


def test_the_bound_needs_assumption_a():
    """With 9000 B packets and Q0 = 1500 B the proposition's assumption fails, and so does the bound: a class waits for several
    visits. This documents why the paper states the assumption."""
    t = np.zeros(8)
    cls = np.array([0, 0, 1, 1, 1, 1, 2, 2], np.int8)
    size = np.array([1500, 1500, 9000, 9000, 9000, 9000, 1500, 1500], np.int32)
    cfg = SimConfig(TrafficConfig(link_rate=1e6, warmup=0.0, duration=1.0), buffer_bytes=10 ** 9)
    log = simulate(Trace(t, cls, size), make("DR-DRR", qmax_mult=1.0), cfg)
    idx = np.flatnonzero(cls == 1)
    _, gap = starvation_gaps(t[idx], log.start[idx], log.end[idx])
    bound = sum(1.0 * Q0 + (9000 if j == 1 else 1500) - 1 for j in (0, 2)) * 8 / 1e6       # L_j of the OTHER classes
    assert gap.max() > bound


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large])
@given(sc=scenario(), M=st.sampled_from([1.0, 2.0, 5.0]), kappa=st.sampled_from([0.0, 4.0, 100.0]),
       rate=st.sampled_from([2e5, 1e6, 1e7]))
def test_sd_drr_respects_the_gap_bound_with_its_own_caps(sc, M, kappa, rate):
    """SD-DRR (E23): quanta in [B_i, M B_i], so the head wait of class i is at most 8 sum_{j != i} (M B_j + L_j - 1) / C."""
    base = (6000.0, 6000.0, 1500.0)
    t, cls, size = sc
    o = np.lexsort((cls, t))
    tr = Trace(np.asarray(t, float)[o], np.asarray(cls, np.int8)[o], np.asarray(size, np.int32)[o])
    cfg = SimConfig(TrafficConfig(link_rate=rate, warmup=0.0, duration=1.0), buffer_bytes=10 ** 9, update_interval=0.01)
    log = simulate(tr, make("SD-DRR", qmax_mult=M, kappa=kappa, base=base), cfg)
    lmax = [int(tr.size[tr.cls == c].max()) if np.any(tr.cls == c) else 0 for c in range(3)]
    for c in range(3):
        idx = np.flatnonzero(tr.cls == c)
        if not len(idx):
            continue
        _, gap = starvation_gaps(tr.t[idx], log.start[idx], log.end[idx])
        bound = sum(M * base[j] + lmax[j] - 1 for j in range(3) if j != c) * 8 / rate
        assert gap.max() <= bound * (1 + 1e-9), (c, gap.max(), bound)
