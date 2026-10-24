"""E25: alternative readings of the reconstructed baselines (RevenueDRR spare-capacity order, FuzzyDRR second input).
Pre-registered in docs/EXPERIMENT_PROTOCOL.md (E25).

  python scripts/e25_readings.py   -> results/E25TUNE, config/tuned_readings.json, results/E25
"""
import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from drrsim.config import CLASSES  # noqa: E402
from drrsim.experiments import DEV_SEEDS, LOADS, SEEDS, onoff, poisson  # noqa: E402
from drrsim.runner import run_tasks, task  # noqa: E402
from drrsim.schedulers import REGISTRY  # noqa: E402

JAIN_MIN, TIE = 0.98, 0.01
OUT = ROOT / "config" / "tuned_readings.json"
TWO_KNOB = json.loads((ROOT / "config" / "tuned_2knob.json").read_text())["params"]
GRIDS = {
    "RevenueDRR": {"order": [list(o) for o in itertools.permutations(range(3))], "guar_scale": [0.25, 0.5, 1.0], "tau": [0.0125, 0.1]},
    "FuzzyDRR": {"input2": ["occupancy", "throughput"], "gain": [0.1, 0.5, 1.0, 2.0, 3.0], "delay_span": [1.0, 2.0, 4.0]},
}
OURS = {"RevenueDRR": {"order": [0, 1, 2], "guar_scale": 1.0, "tau": 0.1}, "FuzzyDRR": {"input2": "occupancy", "gain": 1.0, "delay_span": 2.0}}


def combos(name):
    g = GRIDS[name]
    return [dict(zip(g, v)) for v in itertools.product(*g.values())]


def label(c):
    return json.dumps(c, sort_keys=True)


def params(c):
    return {k: (tuple(v) if k == "order" else v) for k, v in c.items()}


def tune_tasks():
    t = []
    for name in GRIDS:
        for c in combos(name):
            for load in (0.95, 1.2):
                t += [task("E25TUNE", f"{label(c)}|load={load}", name, s, onoff(load), params(c), {"combo": label(c)}) for s in DEV_SEEDS]
    return t


def eval_tasks(chosen):
    t = []
    for load in LOADS:
        for pt, cfg in ((f"poisson|{load}", poisson(load)), (f"onoff|{load}", onoff(load))):
            t += [task("E25", pt, n, s, cfg, params(chosen[n])) for n in GRIDS for s in SEEDS]
    return t


def distance(c, name):
    d = 0.0
    for k, v in c.items():
        o = OURS[name][k]
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            d += abs(math.log(v / o))
        elif v != o:
            d += 1.0
    return d


def main():
    out = ROOT / "results" / "E25TUNE"
    run_tasks(out, tune_tasks())
    df = pd.read_csv(out / "runs.csv")
    df["load_pt"] = df["point"].str.rsplit("|load=", n=1).str[1].astype(float)
    chosen = {}
    for name in GRIDS:
        d = df[df.scheduler == name]
        rows = []
        for c in combos(name):
            dv = d[d.combo == label(c)]
            a = dv[dv.load_pt == 0.95]
            w = np.max([a[f"{k.name}_p95"] / k.delay_target for k in CLASSES], axis=0).mean()
            rows.append((c, w, dv[dv.load_pt == 1.2].jain.mean()))
        feas = [r for r in rows if r[2] >= JAIN_MIN] or [max(rows, key=lambda r: r[2])]
        best = min(r[1] for r in feas)
        tied = [r for r in feas if r[1] <= best * (1 + TIE)]
        pick = min(tied, key=lambda r: distance(r[0], name))
        chosen[name] = pick[0]
        print(name, pick[0], "W@0.95", round(pick[1], 3))
    if OUT.exists():
        assert json.loads(OUT.read_text())["params"] == chosen, "tuned_readings.json exists with different values"
    else:
        OUT.write_text(json.dumps({"rule": "see docs/EXPERIMENT_PROTOCOL.md E25", "params": chosen}, indent=1))
    run_tasks(ROOT / "results" / "E25", eval_tasks(chosen))


if __name__ == "__main__":
    main()
