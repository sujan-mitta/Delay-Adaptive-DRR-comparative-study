"""Differential tests: drrsim must agree exactly with independent reference implementations."""
import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from reference import RefDRR, RefFIFO, RefRLSP, RefSP, ref_simulate
from test_properties import SETTINGS, scenarios
from drrsim import generate_trace, make, simulate, SimConfig, TrafficConfig


def compare(tr, cfg, ours, ref):
    log = simulate(tr, ours, cfg)
    start, dropped = ref_simulate(tr.t, tr.cls, tr.size, cfg.traffic.link_rate, cfg.buffer_bytes,
                                  cfg.buffer_policy, ref)
    assert np.array_equal(log.dropped, dropped)
    assert np.array_equal(np.nan_to_num(log.start, nan=-1.0), np.nan_to_num(start, nan=-1.0))


@SETTINGS
@given(sc=scenarios())
def test_fifo_matches_reference(sc):
    compare(*sc, make("FIFO"), RefFIFO())


@SETTINGS
@given(sc=scenarios())
def test_sp_matches_reference(sc):
    compare(*sc, make("SP"), RefSP())


quanta = st.tuples(*[st.sampled_from([1.0, 100.0, 333.0, 1500.0, 2999.0, 9000.0])] * 3)


@SETTINGS
@given(sc=scenarios(), q=quanta)
def test_drr_matches_textbook_reference(sc, q):
    compare(*sc, make("DRR", quanta=q), RefDRR(q))


@SETTINGS
@given(sc=scenarios(), r=st.sampled_from([0.05, 0.2, 0.4, 0.8, 1.0]))
def test_rlsp_matches_reference(sc, r):
    tr, cfg = sc
    compare(tr, cfg, make("RL-SP+DRR", rate_frac=r), RefRLSP(r * cfg.traffic.link_rate / 8, (1500.0,) * 3))


@pytest.mark.parametrize("arrival", ["poisson", "onoff"])
@pytest.mark.parametrize("load", [0.6, 1.2])
def test_reference_agreement_on_realistic_traces(arrival, load):
    cfg = SimConfig(TrafficConfig(load=load, arrival=arrival, duration=3.0, warmup=0.0), buffer_bytes=60_000)
    tr = generate_trace(cfg.traffic, 7)
    compare(tr, cfg, make("FIFO"), RefFIFO())
    compare(tr, cfg, make("SP"), RefSP())
    compare(tr, cfg, make("DRR"), RefDRR((1500.0,) * 3))
    compare(tr, cfg, make("RL-SP+DRR", rate_frac=0.4), RefRLSP(0.4 * cfg.traffic.link_rate / 8, (1500.0,) * 3))
