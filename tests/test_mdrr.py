"""E20: the two Modified DRR reconstructions behave as described (hand cases and properties)."""
import numpy as np
import pytest
from conftest import cfg_for, trace_from

from drrsim import make, simulate


def order(name, rows):
    tr = trace_from(rows)
    log = simulate(tr, make(name), cfg_for(link_rate=8000.0))
    idx = np.argsort(log.start)
    return [int(tr.cls[i]) for i in idx]


def test_strict_mode_serves_the_low_latency_queue_first():
    rows = [(0.0, 1, 500), (0.0, 2, 500), (0.0, 0, 500), (0.0, 0, 500), (0.0, 0, 500)]
    assert order("MDRR-SP", rows)[:3] == [0, 0, 0]


def test_alternate_mode_interleaves_when_both_sides_are_backlogged():
    rows = [(0.0, 1, 500)] * 3 + [(0.0, 0, 500)] * 3
    seq = order("MDRR-ALT", rows)
    assert seq == [0, 1, 0, 1, 0, 1]            # strict alternation while both sides have packets


def test_both_modes_are_work_conserving_and_serve_everything():
    rows = [(0.1 * i, i % 3, 500 + 500 * (i % 2)) for i in range(40)]
    for name in ("MDRR-SP", "MDRR-ALT"):
        tr = trace_from(rows)
        log = simulate(tr, make(name), cfg_for(link_rate=8000.0, buffer=10 ** 7))
        assert np.all(~log.dropped) and np.all(np.isfinite(log.end))


def test_strict_mode_is_sp_for_class_zero():
    rows = [(0.05 * i, i % 3, 1000) for i in range(60)]
    tr = trace_from(rows)
    cfg = cfg_for(link_rate=8000.0, buffer=10 ** 7)
    a, b = simulate(tr, make("MDRR-SP"), cfg), simulate(tr, make("SP"), cfg)
    m = tr.cls == 0
    assert np.allclose(a.start[m], b.start[m])          # class 0 is served exactly as under SP


@pytest.mark.parametrize("name", ["MDRR-SP", "MDRR-ALT"])
def test_defined_for_three_classes_only(name):
    with pytest.raises(ValueError):
        make(name, k=4)


def test_turn_level_alternate_gives_the_latency_queue_a_whole_turn():
    rows = [(0.0, 2, 500)] + [(0.01, 1, 500)] * 4 + [(0.01, 0, 500)] * 6      # a blocker, then both sides queue up at once
    seq = order("MDRR-ALT-V", rows)[1:]
    assert seq[:3] == [0, 0, 0]                  # quantum 1500 B = three 500 B packets in one low-latency turn
    assert seq[3:6] == [1, 1, 1]                 # then one DRR turn (quantum 1500 B)
    assert seq[6:9] == [0, 0, 0]


def test_turn_level_alternate_is_work_conserving_on_mixed_traffic():
    rows = [(0.07 * i, i % 3, [200, 1000, 1500][i % 3]) for i in range(90)]
    tr = trace_from(rows)
    log = simulate(tr, make("MDRR-ALT-V"), cfg_for(link_rate=8000.0, buffer=10 ** 7))
    assert np.all(~log.dropped) and np.all(np.isfinite(log.end))
