"""E24: tune DR-DRR, FuzzyDRR and RevenueDRR on two knobs each (dev seeds), then run them at the 14 E1 points on seeds 101-120.
Pre-registered in docs/EXPERIMENT_PROTOCOL.md (E24).

  python scripts/e24_retune.py    -> results/E24TUNE/, config/tuned_2knob.json, results/E24/runs.csv
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
from drrsim.experiments import DEV_SEEDS, LOADS, SEEDS, load_tuned, onoff, poisson  # noqa: E402
from drrsim.runner import run_tasks, task  # noqa: E402
from drrsim.schedulers import REGISTRY  # noqa: E402

GRIDS = {
    "DR-DRR": {"kappa": [1, 2, 4, 8, 16], "theta": [0.25, 0.5, 0.75, 1.0]},
    "FuzzyDRR": {"gain": [0.1, 0.5, 1.0, 2.0, 3.0], "delay_span": [1.0, 2.0, 4.0]},
    "RevenueDRR": {"tau": [0.0125, 0.05, 0.1, 0.4], "guar_scale": [0.25, 0.5, 1.0, 1.5]},
}
JAIN_MIN, TIE = 0.98, 0.01
OUT = ROOT / "config" / "tuned_2knob.json"


def combos(name):
    g = GRIDS[name]
    return [dict(zip(g, v)) for v in itertools.product(*g.values())]


def tune_tasks():
    t = []
    for name in GRIDS:
        for c in combos(name):
            lab = ",".join(f"{k}={v}" for k, v in c.items())
            for load in (0.95, 1.2):
                t += [task("E24TUNE", f"{lab}|load={load}", name, s, onoff(load), c, {"combo": lab}) for s in DEV_SEEDS]
    return t


def eval_tasks(chosen):
    t = []
    for load in LOADS:
        for pt, cfg in ((f"poisson|{load}", poisson(load)), (f"onoff|{load}", onoff(load))):
            t += [task("E24", pt, n, s, cfg, chosen[n]) for n in GRIDS for s in SEEDS]
    return t


def main():
    out = ROOT / "results" / "E24TUNE"
    run_tasks(out, tune_tasks())
    df = pd.read_csv(out / "runs.csv")
    df["load_pt"] = df["point"].str.split("load=").str[1].astype(float)
    chosen = {}
    for name in GRIDS:
        d = df[df.scheduler == name]
        rows = []
        for c in combos(name):
            lab = ",".join(f"{k}={v}" for k, v in c.items())
            dv = d[d.combo == lab]
            a = dv[dv.load_pt == 0.95]
            w = np.max([a[f"{k.name}_p95"] / k.delay_target for k in CLASSES], axis=0).mean()
            rows.append((c, w, dv[dv.load_pt == 1.2].jain.mean()))
        feas = [r for r in rows if r[2] >= JAIN_MIN] or [max(rows, key=lambda r: r[2])]
        best = min(r[1] for r in feas)
        tied = [r for r in feas if r[1] <= best * (1 + TIE)]
        defaults = REGISTRY[name].defaults
        dist = lambda r: sum(abs(math.log(r[0][k] / defaults[k])) for k in r[0])
        chosen[name] = min(tied, key=dist)[0]
        print(name, chosen[name], "W@0.95", round(min(tied, key=dist)[1], 3))
    if OUT.exists():
        assert json.loads(OUT.read_text())["params"] == chosen, "config/tuned_2knob.json exists with different values"
    else:
        OUT.write_text(json.dumps({"rule": "see docs/EXPERIMENT_PROTOCOL.md E24", "params": chosen}, indent=1))
    run_tasks(ROOT / "results" / "E24", eval_tasks(chosen))


if __name__ == "__main__":
    main()
