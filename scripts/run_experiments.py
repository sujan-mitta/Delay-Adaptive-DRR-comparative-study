"""Run E1–E7 on reported seeds 101–120 with frozen tuned parameters. Resumable; never overwrites."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim.experiments import EXPERIMENTS, experiment_tasks, load_tuned  # noqa: E402
from drrsim.runner import ROOT, run_tasks  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exps", nargs="*", default=EXPERIMENTS)
    ap.add_argument("--workers", type=int, default=None)
    a = ap.parse_args()
    tuned = load_tuned()
    for e in a.exps:
        run_tasks(ROOT / "results" / e, experiment_tasks(e, tuned), workers=a.workers)


if __name__ == "__main__":
    main()
