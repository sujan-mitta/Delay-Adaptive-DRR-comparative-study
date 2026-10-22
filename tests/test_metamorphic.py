"""Metamorphic tests: laws relating different runs, which must hold whatever the exact numbers are."""
import numpy as np
import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from conftest import ALL_SCHEDULERS, trace_from
from test_properties import SETTINGS, scenarios
from drrsim import SimConfig, TrafficConfig, generate_trace, make, simulate
from drrsim.runner import run_tasks, task

NO_CLOCK = ["FIFO", "SP", "DRR", "RL-SP+DRR", "SCRR"]       # no absolute-time parameters or update clock
SYMMETRIC = ["FIFO", "DRR", "SCRR"]                        # treat classes identically (equal quanta for DRR)


def same(a, b):
    return np.array_equal(np.nan_to_num(a, nan=-1.0), np.nan_to_num(b, nan=-1.0))


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
@SETTINGS
@given(sc=scenarios(), cut=st.floats(0.0, 1.0))
def test_causality_future_arrivals_cannot_change_the_past(name, sc, cut):
    # removing every arrival at or after T leaves every decision taken before T unchanged
    tr, cfg = sc
    if len(tr) == 0:
        return
    T = float(tr.t.max()) * cut
    keep = tr.t < T
    past = trace_from(zip(tr.t[keep], tr.cls[keep], tr.size[keep]))
    full, part = simulate(tr, make(name), cfg), simulate(past, make(name), cfg)
    started_before = full.start[keep] < T
    assert np.array_equal(full.dropped[keep], part.dropped)
    assert same(full.start[keep][started_before], part.start[started_before])


@pytest.mark.parametrize("name", SYMMETRIC)
@pytest.mark.parametrize("perm", [(1, 2, 0), (2, 0, 1), (1, 0, 2)])
def test_class_relabelling_permutes_nothing_else(name, perm):
    tc = TrafficConfig(load=1.1, arrival="onoff", duration=8.0, warmup=0.0)
    tr = generate_trace(tc, 11)
    assert len(np.unique(tr.t)) == len(tr)                     # no simultaneous arrivals: no class tie-breaks
    relabelled = trace_from(zip(tr.t, np.array(perm)[tr.cls], tr.size))
    for policy in ("shared", "partitioned"):
        cfg = SimConfig(tc, buffer_bytes=45_000, buffer_policy=policy)
        a, b = simulate(tr, make(name), cfg), simulate(relabelled, make(name), cfg)
        assert np.array_equal(a.dropped, b.dropped) and same(a.start, b.start)


@pytest.mark.parametrize("name", NO_CLOCK)
@SETTINGS
@given(sc=scenarios(), shift=st.sampled_from([1.0, 4.0, 1024.0]))
def test_time_shift_invariance(name, sc, shift):
    tr, cfg = sc
    if cfg.traffic.link_rate != 8192.0:                       # exact-arithmetic scenarios only (binary times)
        return
    moved = trace_from(zip(tr.t + shift, tr.cls, tr.size))
    # RL-SP: a shaping rate of 0.5 C keeps departure times binary-exact (0.3 C would introduce rounding)
    params = {"rate_frac": 0.5} if name == "RL-SP+DRR" else {}
    a, b = simulate(tr, make(name, **params), cfg), simulate(moved, make(name, **params), cfg)
    assert np.array_equal(a.dropped, b.dropped) and same(a.start + shift, b.start)


def test_runner_rows_identical_for_any_worker_count(tmp_path):
    cfg = SimConfig(TrafficConfig(load=1.0, arrival="onoff", duration=1.0, warmup=0.2))
    tasks = [task("W", "p", n, s, cfg) for n in ("FIFO", "DRR", "CQDRR", "SCRR") for s in (1, 2, 3)]
    frames = []
    for w in (1, 3):
        run_tasks(tmp_path / f"w{w}", tasks, workers=w)
        df = pd.read_csv(tmp_path / f"w{w}" / "runs.csv", float_precision="round_trip").set_index("key").sort_index()
        frames.append(df.drop(columns=["wall_time", "decisions_per_s"]))
    pd.testing.assert_frame_equal(frames[0], frames[1])
