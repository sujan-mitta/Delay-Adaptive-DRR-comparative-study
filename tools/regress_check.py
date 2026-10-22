"""Regression guard: re-simulate saved runs and require every metric to match exactly.

Usage:  python tools/regress_check.py [--sample N] [--scheduler NAME ...] [--exp EXP ...]
Exit code 0 = all identical. Saved CSVs are read with exact float round-tripping (pandas' default fast
parser is not exact). Wall-clock fields are ignored.
"""
import argparse
import random
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from drrsim.experiments import EXPERIMENTS, experiment_tasks, load_tuned, tuning_tasks  # noqa: E402
from drrsim.runner import _execute, key  # noqa: E402

ALL_EXPS = ["TUNE"] + EXPERIMENTS + ["DEVD", "E1D", "E1V", "ES", "E11", "E12"]
SKIP = {"wall_time", "decisions_per_s"}


def saved_tasks(exps=None, schedulers=None):
    tuned = load_tuned()
    out = []
    for e in exps or ALL_EXPS:
        path = ROOT / "results" / e / "runs.csv"
        if not path.exists():
            continue
        saved = pd.read_csv(path, float_precision="round_trip").set_index("key").to_dict("index")
        ts = tuning_tasks() if e == "TUNE" else experiment_tasks(e, tuned)
        out += [(t, saved[key(t)]) for t in ts if key(t) in saved and (not schedulers or t["scheduler"] in schedulers)]
    return out


def compare(item):
    t, s = item
    ok, row = _execute(t)
    if not ok:
        return key(t), ["FAILED: " + row["error"].splitlines()[-1]]
    bad = [c for c, v in row.items() if c not in SKIP and c in s and isinstance(v, (int, float))
           and not (v == s[c] or (isinstance(v, float) and np.isnan(v) and pd.isna(s[c])))]
    return key(t), bad


def run(sample=None, exps=None, schedulers=None, workers=None):
    items = saved_tasks(exps, schedulers)
    if sample and sample < len(items):
        items = random.Random(12345).sample(items, sample)
    with Pool(workers) as p:
        res = list(p.imap_unordered(compare, items, chunksize=4))
    return len(items), [(k, b) for k, b in res if b]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int)
    ap.add_argument("--scheduler", nargs="*")
    ap.add_argument("--exp", nargs="*")
    a = ap.parse_args()
    n, diffs = run(a.sample, a.exp, a.scheduler)
    print(f"{n} saved runs re-simulated; {len(diffs)} differ")
    for k, b in diffs[:20]:
        print("  ", k, b[:5])
    sys.exit(1 if diffs else 0)
