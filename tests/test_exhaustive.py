"""Exhaustive small-scope checking: EVERY trace of up to 4 packets on a small grid, not a sample.

Grid: arrival times {0, 0.5, 1.0} s, classes {0, 1, 2}, sizes {500, 1500} B on a 1000 B/s link, so service
times are 0.5 s or 1.5 s and completions coincide with arrivals all the time (exact ties are the hard cases).
Three buffers: shared 2000 B (drops happen), partitioned 4500 B (1500 B per class), and unlimited.
That is 7,315 traces x 3 buffers = 21,945 cases per scheduler. Every scheduler must satisfy every invariant on
every case, and FIFO, SP, DRR (three quanta settings) and RL-SP+DRR (two rates) must agree packet for packet
with the independent reference simulator (tests/reference.py) on every case.
"""
import itertools
import os

import numpy as np
import pytest

from conftest import ALL_SCHEDULERS, WORK_CONSERVING, trace_from
from drrsim import SimConfig, TrafficConfig, make, simulate
from reference import RefDRR, RefFIFO, RefMDRR, RefRLSP, RefSP, ref_simulate
from test_properties import check_common, check_work_conserving

CELLS = [(t, c, s) for t in (0.0, 0.5, 1.0) for c in (0, 1, 2) for s in (500, 1500)]
MAX_N = int(os.environ.get("EXHAUSTIVE_N", "4"))     # 5 = 33,649 traces: run once per release (~6 min)
TRACES = [trace_from(rows) for n in range(MAX_N + 1) for rows in itertools.combinations_with_replacement(CELLS, n)]
CONFIGS = [SimConfig(TrafficConfig(link_rate=8000.0, warmup=0.0, duration=1.0), buffer_bytes=b, buffer_policy=p,
                     update_interval=0.25)
           for b, p in ((2000, "shared"), (4500, "partitioned"), (10 ** 6, "shared"))]


def test_scope_size():
    assert len(TRACES) == {4: 7315, 5: 33649}.get(MAX_N, len(TRACES)) and len(CONFIGS) == 3


@pytest.mark.parametrize("name", ALL_SCHEDULERS)
def test_every_small_case_keeps_every_invariant(name):
    for cfg in CONFIGS:
        for tr in TRACES:
            log = simulate(tr, make(name), cfg)
            check_common(tr, log, cfg)
            if name in WORK_CONSERVING:
                check_work_conserving(tr, log)


REFERENCES = {
    "FIFO": (lambda: make("FIFO"), lambda cfg: RefFIFO()),
    "SP": (lambda: make("SP"), lambda cfg: RefSP()),
    "DRR q=500": (lambda: make("DRR", quanta=(500.0,) * 3), lambda cfg: RefDRR((500.0,) * 3)),
    "DRR q=1500": (lambda: make("DRR", quanta=(1500.0,) * 3), lambda cfg: RefDRR((1500.0,) * 3)),
    "DRR q=mixed": (lambda: make("DRR", quanta=(100.0, 1500.0, 3000.0)), lambda cfg: RefDRR((100.0, 1500.0, 3000.0))),
    "MDRR-SP": (lambda: make("MDRR-SP"), lambda cfg: RefMDRR((1500.0,) * 3, False)),
    "MDRR-ALT": (lambda: make("MDRR-ALT"), lambda cfg: RefMDRR((1500.0,) * 3, True)),
    "RL-SP r=0.25": (lambda: make("RL-SP+DRR", rate_frac=0.25),
                     lambda cfg: RefRLSP(0.25 * cfg.traffic.link_rate / 8, (1500.0,) * 3)),
    "RL-SP r=1": (lambda: make("RL-SP+DRR", rate_frac=1.0),
                  lambda cfg: RefRLSP(1.0 * cfg.traffic.link_rate / 8, (1500.0,) * 3)),
}


@pytest.mark.parametrize("which", list(REFERENCES))
def test_every_small_case_matches_the_reference(which):
    ours, ref = REFERENCES[which]
    for cfg in CONFIGS:
        for tr in TRACES:
            log = simulate(tr, ours(), cfg)
            start, dropped = ref_simulate(tr.t, tr.cls, tr.size, cfg.traffic.link_rate, cfg.buffer_bytes,
                                          cfg.buffer_policy, ref(cfg))
            assert np.array_equal(log.dropped, dropped), (which, tr)
            assert np.array_equal(np.nan_to_num(log.start, nan=-1.0), np.nan_to_num(start, nan=-1.0)), (which, tr)
