"""E19: tuned static DRR (pre-registered, protocol section E19). Tunes (Q_lat, Q_vid) with the main tuning rule on dev
seeds (min W at ON/OFF 0.95 subject to Jain >= 0.98 at 1.2; ties within 1 % go to the smallest quanta), writes
config/tuned_static_drr.json, then runs the chosen quanta at the 14 E1 points with seeds 101-120."""
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim.config import CLASSES  # noqa: E402
from drrsim.experiments import STATIC_TUNED_PATH, experiment_tasks, load_tuned  # noqa: E402
from drrsim.runner import ROOT, code_hash, run_tasks  # noqa: E402

JAIN_MIN, TIE = 0.98, 0.01


def main():
    out = ROOT / "results" / "E19TUNE"
    run_tasks(out, experiment_tasks("E19TUNE", {}))
    df = pd.read_csv(out / "runs.csv")
    df["load_pt"] = df["point"].str.split("load=").str[1].astype(float)
    df["W"] = np.max([df[f"{c.name}_p95"] / c.delay_target for c in CLASSES], axis=0)
    t = df.groupby(["q_lat", "q_vid"]).apply(lambda g: pd.Series({
        "W@0.95": g[g.load_pt == 0.95].W.mean(), "jain@1.2": g[g.load_pt == 1.2].jain.mean()})).reset_index()
    feas = t[t["jain@1.2"] >= JAIN_MIN]
    pool = feas if len(feas) else t
    best = pool["W@0.95"].min()
    tied = pool[pool["W@0.95"] <= best * (1 + TIE)].copy()
    tied["total"] = tied.q_lat + tied.q_vid
    pick = tied.sort_values(["total", "q_lat"]).iloc[0]
    quanta = [float(pick.q_lat), float(pick.q_vid), 1500.0]
    t.to_csv(out / "tuning_summary.csv", index=False)
    print(t.round(4).to_string(index=False))
    print("chosen static quanta:", quanta)
    if STATIC_TUNED_PATH.exists():
        if json.loads(STATIC_TUNED_PATH.read_text())["quanta"] != quanta:
            raise SystemExit(f"{STATIC_TUNED_PATH} exists with different quanta")
    else:
        STATIC_TUNED_PATH.write_text(json.dumps({"created": datetime.now().isoformat(timespec="seconds"),
                                                 "code_hash": code_hash(), "rule": "min W@0.95 s.t. Jain@1.2>=0.98; "
                                                 "ties within 1% -> smallest quanta", "seeds": "1-5",
                                                 "quanta": quanta}, indent=1))
    run_tasks(ROOT / "results" / "E19", experiment_tasks("E19", load_tuned()))
    run_tasks(ROOT / "results" / "E19H", experiment_tasks("E19H", load_tuned()))


if __name__ == "__main__":
    main()
