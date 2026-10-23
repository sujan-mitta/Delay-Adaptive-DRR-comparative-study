"""The run ledger (tools/run_ledger.py) is the single source of every run count quoted in the paper."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("run_ledger", ROOT / "tools" / "run_ledger.py")
ledger = importlib.util.module_from_spec(spec)
sys.modules["run_ledger"] = ledger
spec.loader.exec_module(ledger)

pytestmark = pytest.mark.skipif(not (ROOT / "results" / "E1" / "runs.csv").exists(), reason="needs saved results")


@pytest.fixture(scope="module")
def built():
    return ledger.build()


def test_every_group_has_one_trace_digest(built):
    rows, _ = built
    assert rows and all(r["runs"] >= r["groups"] for r in rows.values())     # stats() asserts one digest per group


def test_main_matrix_counts_reconcile(built):
    rows, t = built
    assert t["main"] == t["main_paired_runs"] + t["main_single_runs"]
    assert t["main_paired_runs"] == 8 * t["main_paired_groups"]               # eight schedulers per paired group
    assert t["main_groups"] == t["main_paired_groups"] + t["main_single_runs"]  # E6: one run per group
    assert rows["E6"]["distinct_traces"] == 40 and rows["E6"]["unpaired_runs"] == rows["E6"]["runs"]


def test_simulator_total_is_the_sum_of_its_categories(built):
    rows, t = built
    assert t["simulator_total"] == t["main"] + t["further"] + t["tuning"] == sum(r["runs"] for r in rows.values())


def test_paired_experiments_have_eight_schedulers(built):
    """E10 is deliberately excluded: its update-interval sweep runs only the four adaptive schedulers at most points."""
    rows, _ = built
    for e in ("E1", "E2", "E3", "E4", "E5", "E7", "E8", "E15"):
        assert rows[e]["schedulers"] == 8 and rows[e]["runs"] == 8 * rows[e]["groups"], e


def test_ledger_file_is_current():
    rows, t = ledger.build()
    text = (ROOT / "docs" / "RUN_LEDGER.md").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert text == ledger.render(rows, t), "docs/RUN_LEDGER.md is stale: run python tools/run_ledger.py"
