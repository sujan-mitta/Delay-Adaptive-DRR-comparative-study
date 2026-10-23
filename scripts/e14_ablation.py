"""E14 (DR-DRR ablation) and E15 (held-out seeds), pre-registered in docs/EXPERIMENT_PROTOCOL.md.

1. Tune kappa of DR-DRR-backlog and DR-DRR-hol with DR-DRR's own rule (scripts/tune.py, rule v2) on dev seeds 1-5:
   base grid first; the extension below or above is used only if the pick lies on that edge.
2. Write config/tuned_ablation.json (refuses to overwrite different values).
3. Run E14 (14 E1 points, seeds 101-120) and E15 (8 schedulers, 14 E1 points, seeds 201-220).
"""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from drrsim.experiments import ABLATION, ABLATION_TUNED_PATH, TUNE_GRID, experiment_tasks, load_tuned  # noqa: E402
from drrsim.runner import ROOT, code_hash, run_tasks  # noqa: E402
from drrsim.schedulers import REGISTRY  # noqa: E402
from tune import JAIN_MIN, TIE, pick, summarise  # noqa: E402


def main():
    out = ROOT / "results" / "E14TUNE"
    run_tasks(out, experiment_tasks("E14TUNE", {}))
    df = pd.read_csv(out / "runs.csv")
    df["load_pt"] = df["point"].str.split("load=").str[1].astype(float)
    knob, values, lo, hi = TUNE_GRID["DR-DRR"]
    chosen, tables = {}, []
    for name in ABLATION:
        default = REGISTRY[name].defaults[knob]
        v = pick(summarise(df, name, knob, values), default)
        vals = list(values) + (list(lo) if v == min(values) else list(hi) if v == max(values) else [])
        t = summarise(df, name, knob, sorted(vals))
        chosen[name] = {knob: pick(t, default)}
        t["chosen"] = np.isclose(t.value, chosen[name][knob])
        tables.append(t)
    tbl = pd.concat(tables, ignore_index=True)
    tbl.to_csv(out / "tuning_summary.csv", index=False)
    print(tbl.round(4).to_string(index=False))
    print("chosen:", chosen)
    if ABLATION_TUNED_PATH.exists():
        old = json.loads(ABLATION_TUNED_PATH.read_text())["params"]
        if old != chosen:
            raise SystemExit(f"{ABLATION_TUNED_PATH} exists with different values")
    else:
        ABLATION_TUNED_PATH.write_text(json.dumps({
            "created": datetime.now().isoformat(timespec="seconds"), "code_hash": code_hash(),
            "rule": f"same as DR-DRR (tune.py v2): min W@0.95 s.t. Jain@1.2>={JAIN_MIN}; ties within {TIE:.0%}",
            "seeds": "1-5", "params": chosen}, indent=1))
    run_tasks(ROOT / "results" / "E14", experiment_tasks("E14", load_tuned()))
    run_tasks(ROOT / "results" / "E15", experiment_tasks("E15", load_tuned()))


if __name__ == "__main__":
    main()
