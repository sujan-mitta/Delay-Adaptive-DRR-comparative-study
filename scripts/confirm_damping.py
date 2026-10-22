"""Apply the pre-registered E1D confirmation rule to the DEVD dev-seed runs (seeds 1-5).

Writes results/DEVD/decision.json. Exit code 0 = confirmed, 3 = not confirmed.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim.analysis import load  # noqa: E402
from drrsim.runner import ROOT  # noqa: E402


def main():
    d = load("DEVD")
    m = d.groupby(["base_point", "smooth"]).W.mean().unstack()
    m["ratio"] = m[0.5] / m[1.0]
    m["load"] = [float(i.split("|")[1]) for i in m.index]
    worst = float(m.ratio.max())
    high = m[m.load >= 0.9]
    better = int((high.ratio < 1).sum())
    ok = worst <= 1.05 and better >= len(high) / 2
    print(m.sort_values(["load"]).round(4).to_string())
    res = {"confirmed": bool(ok), "worst_ratio": worst, "worst_point": m.ratio.idxmax(),
           "better_at_load_ge_0.9": f"{better}/{len(high)}",
           "rule": "no point worse than +5% AND lower W at >= half of load>=0.9 points (dev seeds 1-5)"}
    (ROOT / "results" / "DEVD" / "decision.json").write_text(json.dumps(res, indent=1))
    print(res)
    sys.exit(0 if ok else 3)


if __name__ == "__main__":
    main()
