"""E22: two links in tandem (pre-registered in docs/EXPERIMENT_PROTOCOL.md, E22).

  python scripts/e22_tandem.py     -> results/E22/runs.csv

Link 1 serves the through traffic; its departures become the through arrivals at link 2, which also carries independent cross
traffic. The same scheduler (same tuned parameters) runs on both links. Score W2 uses end-to-end queueing delay (wait on both
links) against 2 x the single-hop target.
"""
import csv
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from drrsim import SimConfig, TrafficConfig, make, simulate  # noqa: E402
from drrsim.config import CLASSES  # noqa: E402
from drrsim.experiments import BURSTS, SEEDS, load_tuned  # noqa: E402
from drrsim.schedulers import SCHEDULERS  # noqa: E402
from drrsim.traffic import Trace, generate_trace  # noqa: E402

LOADS = (0.8, 0.95)
CROSS_LOAD = 0.3
SEEDS_E22 = SEEDS[:10]
D = [c.delay_target for c in CLASSES]


def tandem(name, params, load, seed):
    cfg1 = SimConfig(TrafficConfig(load=load, arrival="onoff", on_mean=BURSTS["medium"]))
    tr1 = generate_trace(cfg1.traffic, seed)
    log1 = simulate(tr1, make(name, **params), cfg1)
    passed = ~log1.dropped & ~np.isnan(log1.end)
    cfg2 = SimConfig(TrafficConfig(load=CROSS_LOAD, arrival="poisson"))
    cross = generate_trace(cfg2.traffic, seed + 1000)
    t = np.concatenate([log1.end[passed], cross.t])
    c = np.concatenate([tr1.cls[passed], cross.cls])
    s = np.concatenate([tr1.size[passed], cross.size])
    through = np.concatenate([np.ones(passed.sum(), bool), np.zeros(len(cross), bool)])
    arr1 = np.concatenate([tr1.t[passed], np.full(len(cross), np.nan)])
    start1 = np.concatenate([log1.start[passed], np.full(len(cross), np.nan)])
    o = np.lexsort((c, t))
    tr2 = Trace(t[o], c[o].astype(np.int8), s[o].astype(np.int32))
    log2 = simulate(tr2, make(name, **params), cfg2)
    through, arr1, start1 = through[o], arr1[o], start1[o]
    w0, w1 = cfg1.traffic.warmup, cfg1.traffic.horizon
    ok = through & ~log2.dropped & ~np.isnan(log2.start) & (arr1 >= w0) & (arr1 < w1)
    row = {"scheduler": name, "point": f"through={load}", "seed": seed, "load": load, "dropped_hop1": int(log1.dropped.sum()),
           "dropped_hop2_through": int((through & log2.dropped).sum())}
    ws = []
    for k, spec in enumerate(CLASSES):
        m = ok & (tr2.cls == k)
        d1 = start1[m] - arr1[m]
        d2 = log2.start[m] - tr2.t[m]
        e2e = d1 + d2
        p = float(np.percentile(e2e, 95)) if len(e2e) else float("nan")
        row[f"{spec.name}_e2e_p95"] = p
        row[f"{spec.name}_hop1_p95"] = float(np.percentile(d1, 95)) if len(d1) else float("nan")
        row[f"{spec.name}_hop2_p95"] = float(np.percentile(d2, 95)) if len(d2) else float("nan")
        ws.append(p / (2 * D[k]))
    row["W2"] = max(ws)
    return row


def one(a):
    name, params, load, seed = a
    return tandem(name, params, load, seed)


def main():
    tuned = load_tuned()
    tasks = [(n, tuned.get(n, {}), L, s) for L in LOADS for n in SCHEDULERS for s in SEEDS_E22]
    with Pool() as p:
        rows = p.map(one, tasks, chunksize=2)
    out = ROOT / "results" / "E22"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "runs.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print("wrote", out / "runs.csv", len(rows), "runs")


if __name__ == "__main__":
    main()
