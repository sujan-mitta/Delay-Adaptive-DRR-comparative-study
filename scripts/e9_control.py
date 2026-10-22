"""E9 control (exploratory, added after seeing E9): static DRR fixed at DR-DRR's mean quanta.

For each E9 point and each λ, DRR runs with quanta = mean (over seeds and updates) of DR-DRR's
quanta at that λ. Same seeds and traces. If static DRR at the λ=1 means matches DR-DRR λ=1, the
λ effect is explained by mean quantum size/shares; if it is much better, oscillation itself costs.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim.analysis import load  # noqa: E402
from drrsim.experiments import SEEDS, SQ_SMOOTH, onoff, poisson  # noqa: E402
from drrsim.runner import ROOT, run_tasks, task  # noqa: E402

CFG = {"onoff|0.95": onoff(0.95), "onoff|1.2": onoff(1.2), "poisson|1.2": poisson(1.2)}


def main():
    e9 = load("E9")
    out = ROOT / "results" / "E9C"
    out.mkdir(parents=True, exist_ok=True)
    qfile = out / "control_quanta.json"
    means = {f"{bp}|{lam}": [round(float(g[f"{c}_q_mean"].mean()), 3) for c in ("lat", "vid", "blk")]
             for (bp, lam), g in e9.groupby(["base_point", "smooth"])}
    if qfile.exists() and json.loads(qfile.read_text()) != means:
        raise SystemExit("control_quanta.json differs from current E9 means; move results/E9C aside first")
    qfile.write_text(json.dumps(means, indent=1))
    tasks = [task("E9C", f"{bp}|smooth={lam}", "DRR", s, cfg, {"quanta": tuple(means[f"{bp}|{lam}"])},
                  {"base_point": bp, "smooth": lam})
             for bp, cfg in CFG.items() for lam in SQ_SMOOTH for s in SEEDS]
    run_tasks(out, tasks)


if __name__ == "__main__":
    main()
