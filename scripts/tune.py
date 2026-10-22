"""Tune each parameterised scheduler's primary knob on development seeds 1–5 only.

Rule v2 (see docs/EXPERIMENT_PROTOCOL.md, deviation log):
  objective W = mean over seeds of max_i (p95_i / D_i) at load 0.95, ON/OFF-medium;
  constraint mean Jain >= 0.98 at load 1.2;
  values within 1 % of the best W count as tied -> pick the one closest to the spec default;
  if the pick lies on a grid edge, the grid is extended once in that direction (2 values).
Writes config/tuned_params.json (refuses to overwrite different values unless --force).
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim.config import CLASSES  # noqa: E402
from drrsim.experiments import TUNE_GRID, TUNED_PATH, tuning_tasks  # noqa: E402
from drrsim.runner import ROOT, code_hash, run_tasks  # noqa: E402
from drrsim.schedulers import REGISTRY  # noqa: E402

JAIN_MIN = 0.98
TIE = 0.01


def summarise(df, name, knob, values):
    d = df[df.scheduler == name]
    rows = []
    for v in values:
        dv = d[np.isclose(d.value.astype(float), v)]
        a = dv[dv.load_pt == 0.95]
        w = np.max([a[f"{c.name}_p95"] / c.delay_target for c in CLASSES], axis=0).mean()
        rows.append({"scheduler": name, "knob": knob, "value": v, "n_seeds": len(a),
                     "W@0.95": w, "lat_p95_ms": a.lat_p95.mean() * 1e3, "vid_p95_ms": a.vid_p95.mean() * 1e3,
                     "blk_p95_ms": a.blk_p95.mean() * 1e3, "jain@1.2": dv[dv.load_pt == 1.2].jain.mean()})
    t = pd.DataFrame(rows)
    t["feasible"] = t["jain@1.2"] >= JAIN_MIN
    return t


def pick(t, default):
    feas = t[t.feasible]
    if not len(feas):
        return float(t.loc[t["jain@1.2"].idxmax()].value)
    best = feas["W@0.95"].min()
    tied = feas[feas["W@0.95"] <= best * (1 + TIE)]
    return float(tied.iloc[(tied.value - default).abs().argsort().iloc[0]].value)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    out = ROOT / "results" / "TUNE"
    run_tasks(out, tuning_tasks())

    def load():
        df = pd.read_csv(out / "runs.csv")
        df["load_pt"] = df["point"].str.split("load=").str[1].astype(float)
        return df

    df = load()
    extra = {}
    for name, (knob, values, lo, hi) in TUNE_GRID.items():
        v = pick(summarise(df, name, knob, values), REGISTRY[name].defaults[knob])
        if v == min(values) and lo:
            extra[name] = lo
        elif v == max(values) and hi:
            extra[name] = hi
    if extra:
        print("edge picks, extending once:", extra)
        run_tasks(out, tuning_tasks(extra))
        df = load()

    chosen, tables = {}, []
    for name, (knob, values, lo, hi) in TUNE_GRID.items():
        vals = sorted(set(values) | set(extra.get(name, [])))
        t = summarise(df, name, knob, vals)
        chosen[name] = {knob: pick(t, REGISTRY[name].defaults[knob])}
        t["chosen"] = np.isclose(t.value, chosen[name][knob])
        tables.append(t)
    ref = df[df.scheduler == "DRR"]
    r = ref[ref.load_pt == 0.95]
    tables.append(pd.DataFrame([{"scheduler": "DRR (reference)", "knob": "", "value": np.nan, "n_seeds": len(r),
                                 "W@0.95": np.max([r[f"{c.name}_p95"] / c.delay_target for c in CLASSES], axis=0).mean(),
                                 "lat_p95_ms": r.lat_p95.mean() * 1e3, "vid_p95_ms": r.vid_p95.mean() * 1e3,
                                 "blk_p95_ms": r.blk_p95.mean() * 1e3,
                                 "jain@1.2": ref[ref.load_pt == 1.2].jain.mean()}]))
    tbl = pd.concat(tables, ignore_index=True)
    tbl.to_csv(out / "tuning_summary.csv", index=False)
    with pd.option_context("display.width", 200):
        print(tbl.round(4).to_string(index=False))
    print("chosen:", chosen)
    if TUNED_PATH.exists() and not a.force:
        old = json.loads(TUNED_PATH.read_text())["params"]
        if old != chosen:
            raise SystemExit(f"{TUNED_PATH} exists with different values; use --force to replace")
        return
    TUNED_PATH.parent.mkdir(exist_ok=True)
    TUNED_PATH.write_text(json.dumps({
        "created": datetime.now().isoformat(timespec="seconds"), "code_hash": code_hash(),
        "rule": f"v2: min mean max_i(p95_i/D_i)@0.95 s.t. Jain@1.2>={JAIN_MIN}; ties within {TIE:.0%} -> closest to default; edge -> extend once",
        "seeds": "1-5", "params": chosen}, indent=1))


if __name__ == "__main__":
    main()
