"""Metrics computed from raw run logs. One definition for every scheduler.

Window W = [warmup, warmup + duration).
- delay: queueing delay = service start - arrival, over delivered packets that arrived in W.
- throughput: payload bits of packets whose transmission ends in W, divided by |W|.
- drop rate: dropped / offered, over packets that arrived in W.
- fairness: Jain's index of x_i = throughput_i / maxmin_i, where maxmin_i is the
  equal-weight max-min fair share of the link given the offered rates in W.
- starvation: for each delivered packet, gap = start - max(arrival, end of the previous
  delivered packet of the same class) is time the class was backlogged with zero service.
  Gaps > T whose start lies in W are starvation episodes (count, total, max duration).
- oscillation (adaptive only): mean |dQ_i| per update relative to the base quantum, and
  sign flips of dQ_i per second, over updates in W.
- overhead: scheduling decisions per wall-clock second.
"""
from __future__ import annotations

import numpy as np

from .config import CLASSES, K, SimConfig
from .engine import RunLog
from .schedulers import BASE_Q
from .traffic import Trace


def maxmin_share(demand, capacity):
    demand = np.asarray(demand, dtype=float)
    alloc = np.zeros_like(demand)
    left = capacity
    unsat = list(range(len(demand)))
    while unsat and left > 1e-12:
        fair = left / len(unsat)
        sat = [i for i in unsat if demand[i] - alloc[i] <= fair]
        if not sat:
            for i in unsat:
                alloc[i] += fair
            break
        for i in sat:
            left -= demand[i] - alloc[i]
            alloc[i] = demand[i]
            unsat.remove(i)
    return alloc


def jain(x):
    x = np.asarray(x, dtype=float)
    return float(x.sum() ** 2 / (len(x) * (x ** 2).sum())) if (x ** 2).sum() > 0 else float("nan")


def starvation_gaps(arr, start, end):
    """arr/start/end for one class's delivered packets, in FIFO (id) order."""
    prev_end = np.concatenate([[-np.inf], end[:-1]])
    gap_start = np.maximum(arr, prev_end)
    return gap_start, start - gap_start


def compute(trace: Trace, log: RunLog, cfg: SimConfig) -> dict:
    tc = cfg.traffic
    w0, w1 = tc.warmup, tc.horizon
    dur = tc.duration
    out = {}
    arr_in = (trace.t >= w0) & (trace.t < w1)
    delivered = ~log.dropped & ~np.isnan(log.start)
    thr, offered_bps = [], []
    for k, spec in enumerate(CLASSES):
        n = spec.name
        mk = trace.cls == k
        off = mk & arr_in
        dl = off & delivered
        d = log.start[dl] - trace.t[dl]
        out[f"{n}_offered"] = int(off.sum())
        out[f"{n}_drop_rate"] = float(log.dropped[off].sum() / off.sum()) if off.sum() else float("nan")
        out[f"{n}_n_delay"] = int(len(d))
        if len(d):
            out[f"{n}_delay_mean"] = float(d.mean())
            out[f"{n}_p95"] = float(np.percentile(d, 95))
            out[f"{n}_p99"] = float(np.percentile(d, 99))
        else:
            out[f"{n}_delay_mean"] = out[f"{n}_p95"] = out[f"{n}_p99"] = float("nan")
        fin = mk & delivered & (log.end >= w0) & (log.end < w1)
        tput = float(trace.size[fin].sum()) * 8 / dur
        thr.append(tput)
        offered_bps.append(float(trace.size[off].sum()) * 8 / dur)
        out[f"{n}_tput"] = tput

        # starvation
        idx = np.flatnonzero(mk & delivered)
        gs, gap = starvation_gaps(trace.t[idx], log.start[idx], log.end[idx])
        sel = (gs >= w0) & (gs < w1) & (gap > cfg.starvation_T)
        out[f"{n}_starv_count"] = int(sel.sum())
        out[f"{n}_starv_total"] = float(gap[sel].sum())
        out[f"{n}_starv_max"] = float(gap[sel].max()) if sel.any() else 0.0
        out[f"{n}_gap_max"] = float(gap[(gs >= w0) & (gs < w1)].max()) if ((gs >= w0) & (gs < w1)).any() else 0.0

    out["tput_total"] = float(sum(thr))
    fair = maxmin_share(offered_bps, tc.link_rate)
    x = [thr[k] / fair[k] for k in range(K) if fair[k] > 0]
    out["jain"] = jain(x)

    # oscillation
    if len(log.q_times):
        inw = (log.q_times >= w0) & (log.q_times < w1)
        Q = log.q_values[inw]
        dQ = np.diff(Q, axis=0)
        for k, spec in enumerate(CLASSES):
            dq = dQ[:, k]
            out[f"{spec.name}_osc_mag"] = float(np.abs(dq).mean() / BASE_Q[k]) if len(dq) else float("nan")
            s = np.sign(dq[np.abs(dq) > 1e-9])
            out[f"{spec.name}_osc_flips"] = float((s[1:] != s[:-1]).sum() / dur)
            out[f"{spec.name}_q_mean"] = float(Q[:, k].mean()) if len(Q) else float("nan")
        out["osc_mag_mean"] = float(np.mean([out[f"{c.name}_osc_mag"] for c in CLASSES]))
        out["osc_flips_mean"] = float(np.mean([out[f"{c.name}_osc_flips"] for c in CLASSES]))
    else:
        for spec in CLASSES:
            out[f"{spec.name}_osc_mag"] = out[f"{spec.name}_osc_flips"] = out[f"{spec.name}_q_mean"] = float("nan")
        out["osc_mag_mean"] = out["osc_flips_mean"] = float("nan")

    out["decisions"] = log.decisions
    out["wall_time"] = log.wall_time
    out["decisions_per_s"] = log.decisions / log.wall_time if log.wall_time > 0 else float("nan")
    out["n_packets"] = len(trace)
    out["n_dropped"] = int(log.dropped.sum())
    out["n_delivered"] = int(delivered.sum())
    out["pending"] = log.pending
    return out
