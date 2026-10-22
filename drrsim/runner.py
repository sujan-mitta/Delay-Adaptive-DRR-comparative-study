"""Parallel, resumable, append-only experiment runner."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sys
import time
import traceback
from dataclasses import asdict
from datetime import datetime
from multiprocessing import Pool
from pathlib import Path

import numpy as np

from . import run_one
from .config import SimConfig

ROOT = Path(__file__).resolve().parent.parent


def code_hash() -> str:
    h = hashlib.sha256()
    for f in sorted((ROOT / "drrsim").glob("*.py")):
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))   # same hash on Windows and Unix checkouts
    return h.hexdigest()[:16]


def task(exp, point, scheduler, seed, cfg: SimConfig, params=None, tags=None):
    return {"exp": exp, "point": point, "scheduler": scheduler, "seed": seed,
            "cfg": cfg, "params": params or {}, "tags": tags or {}}


def key(t) -> str:
    return f"{t['exp']}|{t['point']}|{t['scheduler']}|{t['seed']}"


def _execute(t):
    try:
        m, _, tr = run_one(t["cfg"], t["scheduler"], t["seed"], t["params"])
        cfg = t["cfg"]
        row = {"key": key(t), "exp": t["exp"], "point": t["point"], "scheduler": t["scheduler"],
               "seed": t["seed"], "trace": tr.digest(),
               "load": cfg.traffic.load, "arrival": cfg.traffic.arrival, "on_mean": cfg.traffic.on_mean,
               "mix": "/".join(str(x) for x in cfg.traffic.mix),
               "class_loads": "" if cfg.traffic.class_loads is None else "/".join(str(x) for x in cfg.traffic.class_loads),
               "buffer": cfg.buffer_bytes, "buffer_policy": cfg.buffer_policy, "params": json.dumps(t["params"], sort_keys=True)}
        row.update(t["tags"])
        row.update(m)
        return True, row
    except Exception:
        return False, {"key": key(t), "error": traceback.format_exc()}


def _done_keys(path: Path) -> set:
    if not path.exists():
        return set()
    with open(path, newline="") as f:
        return {r["key"] for r in csv.DictReader(f)}


def run_tasks(exp_dir, tasks, workers=None, chunksize=4):
    exp_dir = Path(exp_dir)
    exp_dir.mkdir(parents=True, exist_ok=True)
    runs, fails = exp_dir / "runs.csv", exp_dir / "failures.csv"
    done = _done_keys(runs)
    todo = [t for t in tasks if key(t) not in done]
    keys = [key(t) for t in tasks]
    if len(set(keys)) != len(keys):
        raise ValueError("duplicate task keys")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    manifest = {
        "started": stamp, "code_hash": code_hash(), "python": sys.version, "platform": platform.platform(),
        "numpy": np.__version__, "n_tasks": len(tasks), "n_skipped_already_done": len(tasks) - len(todo),
        "configs": sorted({json.dumps({"point": t["point"], "cfg": asdict(t["cfg"])}, default=str) for t in tasks}),
        "params": sorted({json.dumps({"scheduler": t["scheduler"], "params": t["params"]}, sort_keys=True) for t in tasks}),
    }
    mpath, n = exp_dir / f"manifest_{stamp}.json", 1
    while mpath.exists():                                   # never overwrite an earlier manifest
        mpath, n = exp_dir / f"manifest_{stamp}_{n}.json", n + 1
    mpath.write_text(json.dumps(manifest, indent=1))
    print(f"[{exp_dir.name}] {len(todo)} to run, {len(tasks) - len(todo)} already done", flush=True)
    if not todo:
        return
    header = None
    if runs.exists():
        with open(runs, newline="") as f:
            header = next(csv.reader(f))
    t0 = time.time()
    n_ok = n_fail = 0
    workers = workers or max(1, (os.cpu_count() or 2) - 2)
    with Pool(workers) as pool, open(runs, "a", newline="") as fr, open(fails, "a", newline="") as ff:
        w = None
        for i, (ok, row) in enumerate(pool.imap_unordered(_execute, todo, chunksize=chunksize), 1):
            if ok:
                if header is None:
                    header = list(row)
                if w is None:
                    w = csv.DictWriter(fr, fieldnames=header, extrasaction="raise")
                    if fr.tell() == 0:
                        w.writeheader()
                w.writerow(row)
                fr.flush()
                n_ok += 1
            else:
                fw = csv.DictWriter(ff, fieldnames=["key", "error"])
                if ff.tell() == 0:
                    fw.writeheader()
                fw.writerow(row)
                ff.flush()
                n_fail += 1
            if i % 200 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  ok={n_ok} failed={n_fail}  {time.time() - t0:.0f}s", flush=True)
