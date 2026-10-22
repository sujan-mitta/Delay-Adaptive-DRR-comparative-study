"""Record quanta and per-class backlog over time for the four adaptive schedulers (Figure 5 data).

One reported seed (101), ON/OFF-medium, load 0.95. Saves results/TIMESERIES/quanta.csv.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim import CLASSES, generate_trace, make, simulate  # noqa: E402
from drrsim.experiments import load_tuned, onoff  # noqa: E402
from drrsim.runner import ROOT, code_hash  # noqa: E402
from drrsim.schedulers import ADAPTIVE  # noqa: E402

SEED, T0, T1 = 101, 20.0, 24.0


def backlog_at(times, tr, log, k):
    m = (tr.cls == k) & ~log.dropped
    a, s, sz = tr.t[m], log.start[m], tr.size[m]
    # bytes that have arrived by t and not yet started service
    ca = np.concatenate([[0], np.cumsum(sz)])
    order = np.argsort(s)
    cs = np.concatenate([[0], np.cumsum(sz[order])])
    return ca[np.searchsorted(a, times, "right")] - cs[np.searchsorted(s[order], times, "right")]


def main():
    out = ROOT / "results" / "TIMESERIES"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "quanta.csv"
    if path.exists():
        print(f"{path} exists; not overwriting")
        return
    tuned = load_tuned()
    cfg = onoff(0.95)
    tr = generate_trace(cfg.traffic, SEED)
    rows = []
    for name in ADAPTIVE:
        log = simulate(tr, make(name, **tuned.get(name, {})), cfg)
        sel = (log.q_times >= T0) & (log.q_times < T1)
        t = log.q_times[sel]
        for k, c in enumerate(CLASSES):
            b = backlog_at(t, tr, log, k)
            rows += [{"scheduler": name, "t": ti, "cls": c.name, "quantum": q, "backlog": bb}
                     for ti, q, bb in zip(t, log.q_values[sel, k], b)]
    pd.DataFrame(rows).to_csv(path, index=False)
    (out / "meta.json").write_text(json.dumps({"seed": SEED, "window": [T0, T1], "load": 0.95,
                                               "arrival": "onoff-medium", "code_hash": code_hash(),
                                               "trace": tr.digest()}, indent=1))
    print("wrote", path)


if __name__ == "__main__":
    main()
