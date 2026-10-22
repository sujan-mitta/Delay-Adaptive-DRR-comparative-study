"""Shared helpers for the test suite."""
import numpy as np
import pytest

from drrsim import SimConfig, TrafficConfig
from drrsim.schedulers import REGISTRY
from drrsim.traffic import Trace

ALL_SCHEDULERS = sorted(REGISTRY)                       # the 8 compared + SCRR + variants
WORK_CONSERVING = [n for n in ALL_SCHEDULERS if n != "RL-SP+DRR"]


def trace_from(rows):
    """rows: iterable of (time, class, bytes). Sorted by (time, class) like generate_trace."""
    rows = list(rows)
    if not rows:
        return Trace(np.empty(0), np.empty(0, dtype=np.int8), np.empty(0, dtype=np.int32))
    t, c, s = (np.array(x) for x in zip(*rows))
    o = np.lexsort((c, t))
    return Trace(t[o].astype(float), c[o].astype(np.int8), s[o].astype(np.int32))


def cfg_for(link_rate=8000.0, buffer=100_000, duration=1.0, warmup=0.0, **kw):
    return SimConfig(TrafficConfig(link_rate=link_rate, warmup=warmup, duration=duration), buffer_bytes=buffer, **kw)


@pytest.fixture
def make_trace():
    return trace_from
