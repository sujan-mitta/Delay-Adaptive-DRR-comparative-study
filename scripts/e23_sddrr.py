"""E23: SD-DRR (delay-risk boost on a static base), pre-registered in docs/EXPERIMENT_PROTOCOL.md (E23).

  python scripts/e23_sddrr.py   -> results/E23TUNE (dev seeds), config/tuned_sddrr.json,
                                   results/E23 (fresh seeds 201-220, 14 E1 points), results/E23R (other link rates)
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
from drrsim import SimConfig, TrafficConfig  # noqa: E402
from drrsim.config import CLASSES  # noqa: E402
from drrsim.experiments import BURSTS, DEV_SEEDS, HELDOUT_SEEDS, LINK_RATES, LOADS, SEEDS, load_static_tuned, onoff, poisson  # noqa: E402
from drrsim.runner import run_tasks, task  # noqa: E402
from drrsim.schedulers import REGISTRY  # noqa: E402

GRID = {"kappa": [1, 2, 4, 8, 16], "theta": [0.5, 0.75, 1.0]}
JAIN_MIN, TIE = 0.98, 0.01
OUT = ROOT / "config" / "tuned_sddrr.json"
TWO_KNOB = json.loads((ROOT / "config" / "tuned_2knob.json").read_text())["params"]


def combos():
    return [dict(zip(GRID, v)) for v in itertools.product(*GRID.values())]


def label(c):
    return ",".join(f"{k}={v}" for k, v in c.items())


def tune_tasks():
    return [task("E23TUNE", f"{label(c)}|load={load}", "SD-DRR", s, onoff(load), c, {"combo": label(c)})
            for c in combos() for load in (0.95, 1.2) for s in DEV_SEEDS]


def contenders(chosen):
    q = tuple(load_static_tuned())
    return [("SD-DRR", chosen), ("DR-DRR", TWO_KNOB["DR-DRR"]), ("RevenueDRR", TWO_KNOB["RevenueDRR"]),
            ("FuzzyDRR", TWO_KNOB["FuzzyDRR"]), ("DRR", {"quanta": q})]       # the static DRR; plain DRR is E15's DRR on the same seeds


def eval_tasks(chosen):
    t = []
    for load in LOADS:
        for pt, cfg in ((f"poisson|{load}", poisson(load)), (f"onoff|{load}", onoff(load))):
            for name, params in contenders(chosen):
                t += [task("E23", pt, name, s, cfg, params) for s in HELDOUT_SEEDS]
    return t


def rate_tasks(chosen):
    t = []
    for rname, (rate, dur, warm, buf) in LINK_RATES.items():
        for pt, load, kind in (("onoff|0.95", 0.95, "onoff"), ("onoff|1.2", 1.2, "onoff"), ("poisson|1.2", 1.2, "poisson")):
            cfg = SimConfig(TrafficConfig(load=load, arrival=kind, on_mean=BURSTS["medium"], link_rate=rate,
                                          duration=dur, warmup=warm), buffer_bytes=buf)
            for name, params in (("SD-DRR", chosen), ("DRR", {})):
                t += [task("E23R", f"{rname}|{pt}", name, s, cfg, params) for s in SEEDS[:10]]
    return t


def main():
    run_tasks(ROOT / "results" / "E23TUNE", tune_tasks())
    df = pd.read_csv(ROOT / "results" / "E23TUNE" / "runs.csv")
    df["load_pt"] = df["point"].str.split("load=").str[1].astype(float)
    rows = []
    for c in combos():
        dv = df[df.combo == label(c)]
        a = dv[dv.load_pt == 0.95]
        w = np.max([a[f"{k.name}_p95"] / k.delay_target for k in CLASSES], axis=0).mean()
        rows.append((c, w, dv[dv.load_pt == 1.2].jain.mean()))
    feas = [r for r in rows if r[2] >= JAIN_MIN] or [max(rows, key=lambda r: r[2])]
    best = min(r[1] for r in feas)
    tied = [r for r in feas if r[1] <= best * (1 + TIE)]
    d = REGISTRY["SD-DRR"].defaults
    pick = min(tied, key=lambda r: sum(abs(math.log(r[0][k] / d[k])) for k in r[0]))
    chosen = pick[0]
    print("chosen", chosen, "W@0.95", round(pick[1], 3))
    if OUT.exists():
        assert json.loads(OUT.read_text())["params"] == chosen, "tuned_sddrr.json exists with different values"
    else:
        OUT.write_text(json.dumps({"rule": "see docs/EXPERIMENT_PROTOCOL.md E23", "params": chosen}, indent=1))
    run_tasks(ROOT / "results" / "E23", eval_tasks(chosen))
    run_tasks(ROOT / "results" / "E23R", rate_tasks(chosen))


if __name__ == "__main__":
    main()
