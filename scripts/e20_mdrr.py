"""E20: Modified DRR baselines (MDRR-SP, MDRR-ALT) at the 14 E1 points, seeds 101-120. Pre-registered in the protocol (E20).

  python scripts/e20_mdrr.py     -> results/E20/runs.csv
  python scripts/e20_mdrr.py e21 -> results/E21/runs.csv (other link rates, pre-registered E21)
  python scripts/e20_mdrr.py b   -> results/E20B/runs.csv (post-hoc turn-level alternate mode, labelled as such)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from drrsim.experiments import experiment_tasks, load_tuned  # noqa: E402
from drrsim.runner import run_tasks  # noqa: E402

if __name__ == "__main__":
    exp = {"b": "E20B", "e21": "E21"}.get(sys.argv[1] if len(sys.argv) > 1 else "", "E20")
    run_tasks(ROOT / "results" / exp, experiment_tasks(exp, load_tuned()))
