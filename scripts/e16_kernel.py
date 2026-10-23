"""E16: the real Linux kernel schedulers (FIFO / prio / drr under a 10 Mb/s tbf) against the simulator, same packets.

Pre-registered in docs/EXPERIMENT_PROTOCOL.md (section E16). Needs WSL2 (or Linux) with root; see testbed/.
Writes results/E16/<stamp>/ (traces, raw kernel captures, summary.csv, results.json).
Delay compared = waiting time before service: simulator start - arrival; kernel receive time - scheduled send time
(tbf releases a packet when its tokens are available, i.e. at the start of its virtual transmission).
"""
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from drrsim import SimConfig, TrafficConfig, generate_trace, make, simulate  # noqa: E402
from drrsim.runner import code_hash  # noqa: E402

POINTS = {"onoff|0.8": dict(arrival="onoff", load=0.8), "onoff|0.95": dict(arrival="onoff", load=0.95),
          "poisson|0.9": dict(arrival="poisson", load=0.9)}
SEEDS = [101, 102, 103]
MODES = {"fifo": ("FIFO", "shared"), "sp": ("SP", "partitioned"), "drr": ("DRR", "partitioned")}
CLS = ("lat", "vid", "blk")


def wsl_path(p: Path) -> str:
    s = str(p.resolve()).replace("\\", "/")
    return "/mnt/" + s[0].lower() + s[2:]


def main(rate_mbit=10, scale=1, duration=10.0):
    """scale > 1 (E16b): trace times multiplied by `scale` and the link slowed by the same factor; the prediction is
    the simulator at 10 Mb/s on the unscaled trace, times `scale` (exact scale invariance for FIFO, SP and DRR)."""
    exp = "E16" if scale == 1 else "E16b"
    out = ROOT / "results" / exp / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    rows = []
    for pt, kw in POINTS.items():
        for seed in SEEDS:
            tc = TrafficConfig(warmup=0.0, duration=duration, **kw)
            tr = generate_trace(tc, seed)
            tpath = out / f"trace_{pt.replace('|', '_')}_{seed}.csv"
            tpath.write_text("\n".join(f"{t * scale:.9f},{c},{s}" for t, c, s in zip(tr.t, tr.cls, tr.size)) + "\n")
            for mode, (name, policy) in MODES.items():
                cap = out / f"kernel_{mode}_{pt.replace('|', '_')}_{seed}.csv"
                r = subprocess.run(["wsl.exe", "-u", "root", "--", "bash", wsl_path(ROOT / "testbed" / "run.sh"), mode,
                                    wsl_path(tpath), wsl_path(cap), f"{rate_mbit}mbit"], capture_output=True,
                               text=True, timeout=900)
                print(pt, seed, mode, r.stdout.strip().replace("\n", " | "), flush=True)
                k = np.loadtxt(cap, delimiter=",", dtype=np.int64, ndmin=2)
                kdelay = np.full(len(tr), np.nan)
                kdelay[k[:, 0]] = (k[:, 3] - k[:, 2]) / 1e9
                log = simulate(tr, make(name), SimConfig(tc, buffer_bytes=125_000, buffer_policy=policy))
                sdelay = (log.start - tr.t) * scale
                order_k = k[np.argsort(k[:, 3], kind="stable"), 1]
                order_s = tr.cls[np.argsort(log.start)][~log.dropped[np.argsort(log.start)]]
                n = min(len(order_k), len(order_s))
                for c in range(3):
                    m = tr.cls == c
                    kd, sd = kdelay[m], sdelay[m]
                    rows.append({"point": pt, "seed": seed, "scheduler": name, "class": CLS[c], "packets": int(m.sum()),
                                 "kernel_drop": float(np.isnan(kd).mean()), "sim_drop": float(log.dropped[m].mean()),
                                 "kernel_mean_ms": float(np.nanmean(kd) * 1e3), "sim_mean_ms": float(np.nanmean(sd) * 1e3),
                                 "kernel_p95_ms": float(np.nanpercentile(kd, 95) * 1e3),
                                 "sim_p95_ms": float(np.nanpercentile(sd, 95) * 1e3),
                                 "same_next_class": float((order_k[:n] == order_s[:n]).mean())})
    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (out / "results.json").write_text(json.dumps({"code_hash": code_hash(), "rows": rows}, indent=1))
    print("wrote", out)


if __name__ == "__main__":
    if "--e16b" in sys.argv:
        main(rate_mbit=1, scale=10, duration=3.0)
    else:
        main()
