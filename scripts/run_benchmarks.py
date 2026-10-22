"""E13: re-create published examples and compare with the published numbers.

Writes results/E13/<timestamp>/results.json and summary.csv (a new folder per run; nothing is overwritten).
Usage: python scripts/run_benchmarks.py [--quick]
"""
from __future__ import annotations

import csv
import json
import sys
import time
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from drrsim import literature as L          # noqa: E402
from drrsim.runner import code_hash         # noqa: E402

SEEDS = list(range(101, 121))


def _b2_chunk(args):
    seed, n, mode = args
    rng = np.random.default_rng([seed, 2022])
    worst = {"DRR-EOS": [0.0] * 4, "DRR": [0.0] * 4}
    for _ in range(n):
        r = L.b2_trial(rng, mode)
        for s in worst:
            worst[s] = [max(a, b) for a, b in zip(worst[s], r[s])]
    return worst


def _b3(args):
    seed, sch, sizes, buf = args
    kw = {"unlimited": {}, "shared": {"buffer_bytes": 140_000}, "partitioned": {"buffer_bytes": 140_000, "policy": "partitioned"},
          "unlimited, link scaled (post hoc)": {"scaled": True}}[buf]
    return args, L.b3_throughput(seed, sch, sizes, **kw).tolist()


def _b4(args):
    seed, sch = args
    return args, L.b4_throughput(seed, sch)


def _b5_chunk(args):
    seed, n, backlogged, probe = args
    rng = np.random.default_rng([seed, 2025])
    pr = {"as printed": L.SCRRProbe, "round-first": L.SCRRRoundFirstProbe}[probe]
    w = [0.0, 0.0, 0.0]
    viol = [0, 0]
    for _ in range(n):
        M, a, e, b = L.b5_trial(rng, backlogged, pr)
        w = [max(w[0], a / M), max(w[1], e / M), max(w[2], b / M)]
        viol[0] += a > M * (1 + 1e-12)
        viol[1] += b > 2 * M
    return w, viol


def main(quick=False):
    t0 = time.time()
    rows, res = [], {"code_hash": code_hash(), "started": datetime.now().isoformat(timespec="seconds")}

    def row(bench, case, scheduler, quantity, ours, published, unit, verdict=""):
        rows.append({"benchmark": bench, "case": case, "scheduler": scheduler, "quantity": quantity,
                     "ours": ours, "published": published, "unit": unit, "verdict": verdict})

    # B1 --------------------------------------------------------------------------------------------
    p = L.B1
    for sch in ("DRR-EOS", "DRR"):
        d = L.b1_run(sch)
        ok = abs(d - p["published_us"]) <= 0.01 and d < p["boyer_us"] and d > p["soni_us"]
        row("B1", "paper trajectory", sch, "delay of packet of interest", round(d, 4), p["published_us"], "us",
            "pass" if ok else "fail")
    n1 = 200 if quick else 2000
    worst = L.b1_random_max(np.random.default_rng([1, 2022]), n1)
    row("B1", f"{n1} random token-bucket inputs", "DRR-EOS", "max flow-1 delay (<= Boyer bound)", round(worst, 3),
        p["boyer_us"], "us", "pass" if worst <= p["boyer_us"] else "fail")

    with Pool() as pool:
        # B2 ----------------------------------------------------------------------------------------
        per = 50 if quick else 500
        tasks = [(s, per, m) for m in ("greedy", "offset", "random") for s in range(1, 3)]
        w2 = {"DRR-EOS": [0.0] * 4, "DRR": [0.0] * 4}
        for w in pool.map(_b2_chunk, tasks):
            for s in w2:
                w2[s] = [max(a, b) for a, b in zip(w2[s], w[s])]
        res["B2_trials"] = per * len(tasks)
        for s in w2:
            for k in range(4):
                bound = L.B2["bound_s"][k]
                row("B2", f"{res['B2_trials']} token-bucket inputs", s, f"max delay, {L.B2['names'][k]}",
                    round(w2[s][k] * 1e6, 3), round(bound * 1e6, 3), "us",
                    f"{'pass' if w2[s][k] <= bound else 'fail'} (tightness {w2[s][k] / bound:.3f})")

        # B3 ----------------------------------------------------------------------------------------
        seeds = SEEDS[:3] if quick else SEEDS
        tasks = [(s, sch, sz, buf) for s in seeds for sch in ("FIFO", "DRR", "SCRR")
                 for sz in ("random", "constant", "bimodal") for buf in ("unlimited", "shared", "partitioned")
                 if sz == "random" or buf == "unlimited"]
        tasks += [(s, sch, sz, "unlimited, link scaled (post hoc)") for s in seeds for sch in ("FIFO", "DRR", "SCRR")
                  for sz in ("constant", "bimodal")]
        b3 = {}
        for (s, sch, sz, buf), thr in pool.imap_unordered(_b3, tasks):
            b3.setdefault((sch, sz, buf), []).append(thr)
        res["B3"] = {"|".join(k): np.mean(v, axis=0).tolist() for k, v in b3.items()}
        bad = L.B3["bad_flow"]
        for (sch, sz, buf), v in sorted(b3.items()):
            v = np.array(v)                                  # seeds x flows
            ratio = v[:, bad] / np.delete(v, bad, axis=1).mean(axis=1)
            dev = np.abs(np.delete(v, bad, axis=1) / np.delete(v, bad, axis=1).mean(axis=1, keepdims=True) - 1).max(axis=1)
            m, h = ratio.mean(), 2.093 * ratio.std(ddof=1) / np.sqrt(len(ratio)) if len(ratio) > 1 else 0.0
            if buf == "unlimited" and sz == "random" and sch in ("FIFO", "DRR"):
                verdict = ("pass" if abs(m - 1) <= 0.10 else "fail") if sch == "DRR" else ("pass" if m >= 2 else "fail")
            else:
                verdict = "descriptive"
            row("B3", f"{sz} sizes, {buf} buffer, {len(v)} seeds", sch, "ill-behaved / mean of others",
                f"{m:.3f} ± {h:.3f}", "FCFS: 'arbitrary share'; DRR: 'nearly perfect fairness'", "ratio", verdict)
            if sch == "DRR" and buf.startswith("unlimited"):
                row("B3", f"{sz} sizes, {buf} buffer", sch, "max deviation of well-behaved flows from their mean",
                    f"{dev.mean():.4f}", L.B3["published_dev"][sz], "fraction", "descriptive")

        # B4 ----------------------------------------------------------------------------------------
        tasks = [(s, sch) for s in seeds for sch in ("FIFO", "SP", "DRR", "RL-SP+DRR")]
        b4 = {}
        for (s, sch), r in pool.imap_unordered(_b4, tasks):
            b4.setdefault(sch, []).append(r)
        res["B4"] = {}
        for sch, rs in sorted(b4.items()):
            on = np.mean([r["on"] for r in rs], axis=0) / 1e6
            off = np.mean([r["off"] for r in rs], axis=0) / 1e6
            res["B4"][sch] = {"on": on.tolist(), "off": off.tolist()}
            verdict = "descriptive"
            if sch == "RL-SP+DRR":
                ok = (abs(on[0] - 6.0) <= 0.06 and all(abs(x - 2.0) <= 0.1 for x in on[1:])
                      and all(abs(x - 5.0) <= 0.25 for x in off[1:]))
                verdict = "pass" if ok else "fail"
            row("B4", f"high priority on, {len(rs)} seeds", sch, "high / medium / low throughput",
                " / ".join(f"{x:.3f}" for x in on), "high 5.3 (RL-SP-DRR and STRICT)", "Mb/s", verdict)
            row("B4", f"high priority off, {len(rs)} seeds", sch, "high / medium / low throughput",
                " / ".join(f"{x:.3f}" for x in off), "-", "Mb/s", "descriptive")

        # B5 ----------------------------------------------------------------------------------------
        n5 = 100 if quick else 500
        for probe in ("as printed", "round-first"):
            for backlogged in (True, False):
                outs = pool.map(_b5_chunk, [(s, n5, backlogged, probe) for s in range(1, 3)])
                w = [max(o[0][i] for o in outs) for i in range(3)]
                viol = [sum(o[1][i] for o in outs) for i in range(2)]
                case = f"{2 * n5} random traces, {'backlogged' if backlogged else 'dynamic arrivals'}"
                registered = probe == "as printed" and backlogged
                row("B5", case, f"SCRR ({probe})", "max clock advance per round / M (Thm 1: <= 1)", round(w[0], 3), 1,
                    "M", ("pass" if viol[0] == 0 else f"fail ({viol[0]} traces)") if registered else f"descriptive ({viol[0]} traces exceed)")
                row("B5", case, f"SCRR ({probe})", "max burst of one visit / M (Thm 2: <= 2)", round(w[2], 3), 2,
                    "M", ("pass" if viol[1] == 0 else f"fail ({viol[1]} traces)") if registered else f"descriptive ({viol[1]} traces exceed)")
                row("B5", case, f"SCRR ({probe})", "max advance when the queue empties / M (no theorem)", round(w[1], 3),
                    "-", "M", "descriptive")

    res["rows"] = rows
    res["seconds"] = round(time.time() - t0, 1)
    out = ROOT / "results" / "E13" / (datetime.now().strftime("%Y%m%d-%H%M%S") + ("-quick" if quick else ""))
    out.mkdir(parents=True, exist_ok=False)
    (out / "results.json").write_text(json.dumps(res, indent=1))
    with open(out / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    for r in rows:
        print(f"{r['benchmark']:3} {r['scheduler']:22} {r['quantity'][:44]:44} ours={r['ours']}  pub={r['published']}  {r['verdict']}")
    print(f"wrote {out} in {res['seconds']} s")
    return out


if __name__ == "__main__":
    main(quick="--quick" in sys.argv)
