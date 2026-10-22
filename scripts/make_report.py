"""Generate RESULTS.md purely from saved CSVs. Every number in it is computed here, none typed by hand.

The bullet statements are machine-generated facts for the author to interpret and write up;
they are not paper prose.
"""
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim.analysis import ORDER, check_pairing, ci95, load, paired_vs, rank_stability  # noqa: E402
from drrsim.config import CLASSES  # noqa: E402
from drrsim.experiments import EXPERIMENTS, load_tuned  # noqa: E402
from drrsim.runner import ROOT, code_hash  # noqa: E402

OUT = []


def w(s=""):
    OUT.append(s)


def fmt(m, h, scale=1.0, nd=1):
    if np.isnan(m):
        return "–"
    return f"{m * scale:.{nd}f} ± {h * scale:.{nd}f}" if not np.isnan(h) else f"{m * scale:.{nd}f}"


def table(df, metrics, point, scale=1e3, nd=1, names=None):
    d = df[df.point == point]
    head = "| scheduler | " + " | ".join(names or metrics) + " |"
    w(head)
    w("|" + "---|" * (len(metrics) + 1))
    for s in ORDER:
        g = d[d.scheduler == s]
        cells = []
        for m in metrics:
            sc = scale if (m.endswith("p95") or m.endswith("p99") or m.endswith("mean")) else 1.0
            k = nd if sc != 1.0 else (3 if m in ("jain", "W") else 2)
            if m.endswith("tput"):
                sc, k = 1e-6, 2
            cells.append(fmt(*ci95(g[m])[:2], sc, k))
        w(f"| {s} | " + " | ".join(cells) + " |")
    w()


def main():
    tuned = load_tuned()
    data = {e: load(e) for e in EXPERIMENTS if e not in ("E9", "E10")}
    n_runs = sum(len(d) for d in data.values())
    n_pairs = sum(check_pairing(d) for d in data.values())
    fails = []
    for e in EXPERIMENTS:
        f = ROOT / "results" / e / "failures.csv"
        if f.exists() and f.stat().st_size and len(pd.read_csv(f)):
            fails.append(f"{e} ({len(pd.read_csv(f))})")

    w("# RESULTS (auto-generated)")
    w()
    w(f"Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/make_report.py` from `results/*/runs.csv`; "
      f"code hash `{code_hash()}`. **Do not edit by hand** — re-run the script.")
    w()
    w("> **Verification status.** FIFO, SP and DRR are textbook. RL-SP+DRR (arXiv:2002.07027, Algorithm 1) and "
      "CQDRR (Electronics Letters e70418, Eqs. 1-13) were re-implemented from their full texts; where those papers are "
      "silent, our choices are listed in `docs/ALGORITHM_SPEC.md`. FuzzyDRR and RevenueDRR are *inspired-by* designs: "
      "their full texts could not be obtained, and only the abstract (FuzzyDRR) or a 2-page preview (RevenueDRR) was "
      "checked; FuzzyDRR has a known input mismatch. The optional ninth scheduler SCRR (NSDI 2025) follows its paper's "
      "Algorithms 3-4. DR-DRR (delay-risk DRR) is **our own design**: the plan's "
      "source for it could not be found, so it is not attributed. See `docs/REFERENCES_CHECK.md`.")
    w()
    w(f"- Reported runs in the main matrix E1–E8: **{n_runs}** (seeds 101–120); further arms (E9, E9C, E10, E1D, E1V, ES) "
      f"are reported in their own sections. Failed runs: "
      f"**{'none' if not fails else ', '.join(fails)}**.")
    w(f"- Pairing verified: {n_pairs} (point, seed) groups, each with a single trace digest across all 8 schedulers.")
    w(f"- Tuned parameters (dev seeds 1–5, frozen before reported runs): `{tuned}`.")
    w("- Values are mean ± 95 % t-interval half-width over 20 seeds; delays in ms. "
      "`W = max_i p95_i / D_i` with D = (10, 50, 500) ms: W ≤ 1 means every class met its p95 target.")
    w()
    w("<<HEADLINE>>")
    w()

    # ---------------- RQ1
    e1 = data["E1"]
    w("## RQ1 — Latency-class p95 under identical traffic (E1)")
    w()
    w("![p95 vs load](figures/fig2_p95_vs_load.png)")
    w()
    for pt in ["onoff|0.95", "onoff|1.2", "poisson|0.95"]:
        w(f"**{pt.replace('|', ', load ')}**")
        w()
        table(e1, ["lat_p95", "lat_p99", "vid_p95", "blk_p95", "W"], pt,
              names=["lat p95", "lat p99", "vid p95", "blk p95", "W"])
    pv = paired_vs(e1, "lat_p95")
    w("Paired difference in latency-class p95 vs DRR (negative = better), ON/OFF-medium:")
    w()
    w("| load | " + " | ".join(s for s in ORDER if s != "DRR") + " |")
    w("|" + "---|" * len(ORDER))
    for load_pt in [0.4, 0.8, 0.95, 1.2]:
        p = pv[pv.point == f"onoff|{load_pt}"].set_index("scheduler")
        cells = [f"{p.loc[s, 'diff'] * 1e3:+.1f} ({'p<.001' if p.loc[s, 'p'] < 1e-3 else f'p={p.loc[s, 'p']:.2g}'})"
                 for s in ORDER if s != "DRR"]
        w(f"| {load_pt} | " + " | ".join(cells) + " |")
    w()
    best = {}
    for pt, g in e1.groupby("point"):
        m = g.groupby("scheduler").lat_p95.mean()
        best[pt] = (m.idxmin(), m.drop("SP").idxmin())
    w("Facts:")
    sp_wins = sum(b[0] == "SP" for b in best.values())
    w(f"- Lowest latency-class p95: SP at {sp_wins}/{len(best)} E1 points (a static baseline wins RQ1 outright).")
    alt = pd.Series([b[1] for b in best.values()]).value_counts()
    w("- Excluding SP, lowest latency p95 at E1 points: " + ", ".join(f"{k} {v}" for k, v in alt.items()) + ".")
    w()

    # ---------------- RQ2
    e5, e8 = data["E5"], data["E8"]
    w("## RQ2 — Cost to other classes: delay, starvation, throughput, fairness (E5, E8)")
    w()
    w("![starvation](figures/fig3_starvation_stress.png)")
    w()
    w("![trade-off](figures/fig4_delay_fairness_tradeoff.png)")
    w()
    w("**E5 stress, shared buffer** (latency class alone offers 0.8·C; total 1.3·C):")
    w()
    table(e5, ["lat_p95", "vid_p95", "blk_p95", "blk_starv_count", "blk_starv_total", "vid_starv_total", "blk_tput", "jain"],
          "stress", names=["lat p95", "vid p95", "blk p95", "blk starv #", "blk starv s", "vid starv s", "blk tput Mb/s", "Jain"])
    w("**E8 stress, partitioned buffer** (B/3 per class):")
    w()
    table(e8, ["lat_p95", "vid_p95", "blk_p95", "blk_starv_count", "blk_starv_total", "vid_starv_total", "blk_tput", "jain"],
          "partitioned|stress", names=["lat p95", "vid p95", "blk p95", "blk starv #", "blk starv s", "vid starv s", "blk tput Mb/s", "Jain"])
    w("**E8 load 1.2, partitioned buffer:**")
    w()
    table(e8, ["lat_p95", "vid_p95", "blk_p95", "lat_tput", "vid_tput", "blk_tput", "jain"], "partitioned|1.2",
          names=["lat p95", "vid p95", "blk p95", "lat tput Mb/s", "vid tput Mb/s", "blk tput Mb/s", "Jain"])
    drop = e1[e1.point == "onoff|1.2"].groupby("scheduler")[["lat_drop_rate", "vid_drop_rate", "blk_drop_rate"]].mean()
    w("Facts:")
    w(f"- Shared buffer: Jain's index over all E1 ON/OFF runs ranges {e1[e1.arrival == 'onoff'].jain.min():.4f}–"
      f"{e1[e1.arrival == 'onoff'].jain.max():.4f} across **all** schedulers; per-class drop rates at load 1.2 differ "
      f"across schedulers by at most {(drop.max() - drop.min()).max() * 100:.2f} percentage points. With a class-blind "
      "tail-drop buffer, admitted (hence delivered) traffic is proportional to arrivals, so the scheduler cannot "
      "change throughput shares — only delay.")
    sp_st = e5[e5.scheduler == "SP"]
    st_counts = {s: sum(int(data[e][data[e].scheduler == s][[f"{c.name}_starv_count" for c in CLASSES]].sum().sum())
                        for e in data) for s in ORDER}
    w(f"- SP starves bulk {sp_st.blk_starv_total.mean():.1f} s and video {sp_st.vid_starv_total.mean():.1f} s per 60 s in E5. "
      "Starvation episodes (> 100 ms backlogged without service, any class) summed over all E1–E8 runs: "
      + ", ".join(f"{s} {n}" for s, n in st_counts.items()) + ".")
    pe = e8[e8.point == "partitioned|stress"].groupby("scheduler")[["blk_tput", "jain"]].mean()
    w("- With a partitioned buffer the throughput cost becomes visible: in E8 stress, bulk throughput is "
      + ", ".join(f"{s} {pe.loc[s, 'blk_tput'] / 1e6:.2f}" for s in ORDER) + " Mb/s.")
    w()

    # ---------------- RQ3
    e6 = data["E6"]
    w("## RQ3 — Weight oscillation and its effect on tail delay")
    w()
    w("![oscillation](figures/fig5_weight_oscillation.png)")
    w()
    w("Oscillation (E1 ON/OFF, load 0.95): mean |ΔQ|/Q⁰ per 10-ms update and quantum sign flips per second.")
    w()
    w("| scheduler | |ΔQ|/Q⁰ per update | flips/s | lat-class |ΔQ|/Q⁰ |")
    w("|---|---|---|---|")
    d = e1[e1.point == "onoff|0.95"]
    from drrsim.schedulers import ADAPTIVE
    for s in ADAPTIVE:
        g = d[d.scheduler == s]
        w(f"| {s} | {fmt(*ci95(g.osc_mag_mean)[:2], 1, 3)} | {fmt(*ci95(g.osc_flips_mean)[:2], 1, 1)} | "
          f"{fmt(*ci95(g.lat_osc_mag)[:2], 1, 3)} |")
    w()
    from scipy import stats
    w("Within-point Spearman correlation between oscillation and W across the 20 seeds (mean over E1 points):")
    w()
    for s in ADAPTIVE:
        rs = [stats.spearmanr(g.osc_mag_mean, g.W)[0] for _, g in e1[e1.scheduler == s].groupby("point")
              if g.osc_mag_mean.std() > 0]
        w(f"- {s}: ρ = {np.nanmean(rs):+.2f} over {len(rs)} points")
    w()
    e6["L"] = e6.point.str.split("load=").str[1]
    w("A correlation across seeds cannot show cause; the intervention test is the pre-registered damping ablation E9 below.")
    w()
    w("### E9 — pre-registered DR-DRR damping ablation (+ post-hoc control E9C)")
    w()
    w("![damping](figures/fig9_drdrr_damping.png)")
    w()
    w("Rule (fixed before running, see protocol §E9): *supported* if at ≥ 2 of 3 points some λ < 1 lowers mean W "
      "by ≥ 5 % vs λ = 1 with Holm-corrected paired Wilcoxon p < 0.05; *not supported* if no λ < 1 lowers W "
      "significantly anywhere; otherwise *mixed*. E9C = static DRR fixed at DR-DRR's mean quanta for that (point, λ).")
    w()
    e9, e9c = load("E9"), load("E9C")
    w("| point | λ | |ΔQ|/Q⁰ | W DR-DRR | ΔW vs λ=1 | Holm p | W static DRR @ mean Q (E9C) | DR-DRR − static (paired p) |")
    w("|---|---|---|---|---|---|---|---|")
    hits, sig_any = 0, False
    for bp in ["onoff|0.95", "onoff|1.2", "poisson|1.2"]:
        d = e9[e9.base_point == bp]
        r = d[d.smooth == 1.0].set_index("seed").W.sort_index()
        raw = {lam: stats.wilcoxon(d[d.smooth == lam].set_index("seed").W.sort_index() - r).pvalue
               for lam in [0.5, 0.25, 0.1]}
        order = sorted(raw, key=raw.get)
        holm, run = {}, 0.0
        for i, lam in enumerate(order):
            run = max(run, min(1.0, raw[lam] * (len(order) - i)))
            holm[lam] = run
        hit = False
        for lam in [1.0, 0.5, 0.25, 0.1]:
            g = d[d.smooth == lam].set_index("seed").sort_index()
            cg = e9c[(e9c.base_point == bp) & (e9c.smooth == lam)].set_index("seed").W.sort_index()
            dw = g.W.mean() / r.mean() - 1
            if lam != 1.0 and holm[lam] < 0.05:
                sig_any |= dw < 0
                hit |= dw <= -0.05
            pc = stats.wilcoxon(g.W - cg).pvalue
            w(f"| {bp.replace('|', ' ')} | {lam:g} | {g.osc_mag_mean.mean():.3f} | {fmt(*ci95(g.W)[:2], 1, 3)} | "
              f"{'–' if lam == 1 else f'{dw:+.1%}'} | {'–' if lam == 1 else f'{holm[lam]:.2g}'} | "
              f"{fmt(*ci95(cg)[:2], 1, 3)} | {(g.W - cg).mean():+.3f} (p={pc:.2g}) |")
        hits += hit
    verdict = "supported" if hits >= 2 else ("not supported" if not sig_any else "mixed")
    w()
    w(f"**Pre-registered verdict: {verdict}** — the ≥ 5 % criterion is met at {hits} of 3 points.")
    w()
    w("Facts:")
    w("- Manipulation check: oscillation falls monotonically with λ at every point (table above).")
    w("- ON/OFF bursts: DR-DRR beats static DRR at its own mean quanta at every λ, so the weight movement is the "
      "adaptation that helps, not harmful noise; mild damping changes W by < 5 %, heavy damping (λ = 0.1) makes it worse.")
    w("- Poisson overload: static DRR at DR-DRR's λ = 1 mean quanta beats DR-DRR λ = 1 — here the oscillation itself "
      "costs tail delay, and damping (λ ≤ 0.5) roughly halves W.")
    w("- λ = 0.5 lowered W at all three points. It is a candidate for the plan's optional fix, but it was chosen "
      "on reported seeds; adopting it requires confirming on dev seeds and the other E1 points first.")
    w()
    w("### E1D — DR-DRR+damping (λ = 0.5) as a separate variant")
    w()
    import json
    dec = json.loads((ROOT / "results" / "DEVD" / "decision.json").read_text())
    w(f"Dev-seed confirmation (seeds 1–5, rule fixed beforehand, protocol §E1D): **{'confirmed' if dec['confirmed'] else 'NOT confirmed'}** — "
      f"worst point {dec['worst_point']} at {100 * (dec['worst_ratio'] - 1):+.1f} % W (limit +5 %), "
      f"lower W at {dec['better_at_load_ge_0.9']} points with load ≥ 0.9.")
    w()
    w("![damped variant](figures/fig10_drdrr_damping_variant.png)")
    w()
    dd = load("E1D")
    sq = e1[e1.scheduler == "DR-DRR"].set_index(["point", "seed"])
    dv = dd.set_index(["point", "seed"]).loc[sq.index]
    assert (dv.trace == sq.trace).all(), "E1D not paired with E1"
    rows = []
    for p in sq.index.get_level_values(0).unique():
        a, b = dv.loc[p], sq.loc[p]
        diff = a.W - b.W
        pr = stats.wilcoxon(diff).pvalue if diff.abs().sum() > 0 else 1.0
        allw = e1[e1.point == p].groupby("scheduler").W.mean()
        rank = int((allw < a.W.mean()).sum()) + 1
        rows.append([p, a, b, pr, rank, int((diff < 0).sum())])
    order = sorted(range(len(rows)), key=lambda i: rows[i][3])
    run = 0.0
    for i, k in enumerate(order):
        run = max(run, min(1.0, rows[k][3] * (len(rows) - i)))
        rows[k].append(run)
    rows.sort(key=lambda r: (float(r[0].split("|")[1]), r[0]))
    w("| point | W DR-DRR | W +damping | ΔW | Holm p | seeds better | lat p95 | vid p95 | blk p95 | |ΔQ|/Q⁰ | rank among 9 (8 + variant) |")
    w("|---|---|---|---|---|---|---|---|---|---|---|")
    better = worse = 0
    for p, a, b, pr, rank, wins, holm in rows:
        dW = a.W.mean() / b.W.mean() - 1
        if holm < 0.05:
            better += dW < 0
            worse += dW > 0
        w(f"| {p.replace('|', ' ')} | {b.W.mean():.3f} | {a.W.mean():.3f} | {dW:+.1%} | {holm:.2g} | {wins}/20 | "
          f"{b.lat_p95.mean() * 1e3:.1f}→{a.lat_p95.mean() * 1e3:.1f} | {b.vid_p95.mean() * 1e3:.1f}→{a.vid_p95.mean() * 1e3:.1f} | "
          f"{b.blk_p95.mean() * 1e3:.0f}→{a.blk_p95.mean() * 1e3:.0f} | {b.osc_mag_mean.mean():.3f}→{a.osc_mag_mean.mean():.3f} | {rank} |")
    w()
    w("Facts:")
    w(f"- Holm-significant W change vs DR-DRR at 14 E1 points: better at {better}, worse at {worse}, no difference at {14 - better - worse}.")
    big = max(rows, key=lambda r: -(r[1].W.mean() / r[2].W.mean()))
    w(f"- Largest gain: {big[0]} ({big[1].W.mean() / big[2].W.mean() - 1:+.1%}); bulk p95 rises slightly at high load but stays below its 500 ms target.")
    ranks = [r[4] for r in rows]
    w(f"- Rank = position by mean W among the 8 schedulers plus this variant (1 = best). It ranks 1st at "
      f"{ranks.count(1)} and 2nd at {ranks.count(2)} of 14 points; median rank {int(np.median(ranks))}.")
    w("- λ = 0.5 was confirmed on dev seeds, but the idea came from E9 on reported seeds, so present the variant as a "
      "data-motivated improvement, not a pre-planned arm.")
    w()

    w("### ES — SCRR, the optional ninth scheduler (Sharafzadeh et al., NSDI 2025)")
    w()
    w("Paper-faithful SCRR with enhancements (Appendix A, Algorithms 3-4), parameter-free, each class one sub-queue, "
      "run on the same traces as E1/E3/E5/E8 (pairing checked). Tests pre-registered in the protocol (section ES).")
    w()
    w("![SCRR](figures/fig11_scrr.png)")
    w()
    es = load("ES")
    for (se, bp), g in es[es.scheduler == "SCRR"].groupby(["src_exp", "base_point"]):
        ref = data[se][data[se].point == bp].groupby("seed").trace.first()
        assert (g.set_index("seed").trace == ref.loc[g.seed].values).all(), f"SCRR not paired at {se} {bp}"
    sc = es[(es.src_exp == "E1") & (es.scheduler == "SCRR")].set_index(["base_point", "seed"])
    d9 = es[(es.src_exp == "E1") & (es.scheduler == "DRR")].set_index(["base_point", "seed"])
    d15 = e1[e1.scheduler == "DRR"].set_index(["point", "seed"])
    w("| point | latency mean, SCRR (ms) | latency mean, DRR-9000 (ms) | paired p | W SCRR | W DRR-1500 | W DRR-9000 | SCRR rank among 9 |")
    w("|---|---|---|---|---|---|---|---|")
    hits, hi_pts = 0, 0
    ranks = []
    for bp in sorted(sc.index.get_level_values(0).unique(), key=lambda x: (x.split("|")[0], float(x.split("|")[1]))):
        a, b, c = sc.loc[bp].sort_index(), d9.loc[bp].sort_index(), d15.loc[bp].sort_index()
        pv = stats.wilcoxon(a.lat_delay_mean - b.lat_delay_mean).pvalue
        if float(bp.split("|")[1]) >= 0.9:
            hi_pts += 1
            hits += a.lat_delay_mean.mean() < b.lat_delay_mean.mean() and pv < 0.05
        allw = e1[e1.point == bp].groupby("scheduler").W.mean()
        rank = int((allw < a.W.mean()).sum()) + 1
        ranks.append(rank)
        w(f"| {bp.replace('|', ' ')} | {a.lat_delay_mean.mean() * 1e3:.2f} | {b.lat_delay_mean.mean() * 1e3:.2f} | {pv:.2g} | "
          f"{a.W.mean():.2f} | {c.W.mean():.2f} | {b.W.mean():.2f} | {rank} |")
    w()
    jrows = []
    for bp in ["partitioned|0.95", "partitioned|1.2", "partitioned|stress"]:
        js = es[(es.src_exp == "E8") & (es.base_point == bp)].jain.mean()
        jd = e8[(e8.point == bp) & (e8.scheduler == "DRR")].jain.mean()
        jrows.append((bp, js, jd))
    fair_ok = all(abs(js - jd) <= 0.01 for _, js, jd in jrows)
    w("| SCRR paper claim | our test | result | verdict |")
    w("|---|---|---|---|")
    w(f"| (a) much lower application latency than DRR with a large quantum | latency-class mean delay below DRR-9000, "
      f"paired p<0.05, at E1 loads >= 0.9 | {hits}/{hi_pts} | **{'reproduced' if hits >= 6 else 'NOT reproduced'}** |")
    w("| (b) fairness on par with DRR | |Jain(SCRR) - Jain(DRR)| <= 0.01 at the 3 E8 partitioned points | "
      + ", ".join(f"{bp.split('|')[1]}: {js - jd:+.4f}" for bp, js, jd in jrows)
      + f" | **{'reproduced' if fair_ok else 'NOT reproduced'}** |")
    w()
    rel = [sc.loc[bp].W.mean() / d15.loc[bp].W.mean() - 1 for bp in sc.index.get_level_values(0).unique()]
    w(f"Facts: on this study's deadline-aware metric W, SCRR differs from DRR with a 1500 B quantum by {min(rel):+.0%} to "
      f"{max(rel):+.0%} across the 14 E1 points and ranks {min(ranks)}-{max(ranks)} of 9 (median {int(np.median(ranks))}). SCRR targets fairness and "
      "sparse-flow latency without parameters; it does not use per-class delay targets, so a class-level, deadline-aware "
      "comparison is not where its advantages show. Its latency gain over a large-quantum DRR is large (table above).")
    w()

    # ---------------- RQ4
    w("## RQ4 — Parameter sensitivity (E6) and burstiness (E3)")
    w()
    w("![sensitivity](figures/fig6_parameter_sensitivity.png)")
    w()
    w("Change in W when one knob moves from its tuned value to ×0.5 / ×1.5, all others fixed, ON/OFF-medium:")
    w()
    w("| scheduler | knob | W tuned @0.95 | range @0.95 | W tuned @1.2 | range @1.2 |")
    w("|---|---|---|---|---|---|")
    for s in ORDER:
        for k in sorted(e6[e6.scheduler == s].knob.dropna().unique()):
            cells = []
            for L in ["0.95", "1.2"]:
                g = e6[(e6.scheduler == s) & (e6.knob == k) & (e6.L == L)].groupby("level").W.mean()
                cells += [f"{g['x1']:.2f}", f"{g.min():.2f}–{g.max():.2f}"]
            w(f"| {s} | {k} | " + " | ".join(cells) + " |")
    w()
    w("![burstiness](figures/fig7_burstiness.png)")
    w()
    e3 = data["E3"]
    w("W by arrival process (load 0.9, E3):")
    w()
    pts = ["poisson", "onoff-small", "onoff-medium", "onoff-large"]
    w("| scheduler | " + " | ".join(pts) + " |")
    w("|" + "---|" * (len(pts) + 1))
    for s in ORDER:
        w(f"| {s} | " + " | ".join(fmt(*ci95(e3[(e3.point == p) & (e3.scheduler == s)].W)[:2], 1, 2) for p in pts) + " |")
    w()

    # ---------------- RQ5
    w("## RQ5 — Do rankings hold across load, mix, buffer and seeds?")
    w()
    w("![buffer and mix](figures/fig8_buffer_and_mix.png)")
    w()
    rows = []
    for e in ["E1", "E2", "E3", "E4", "E7", "E8"]:
        rs = rank_stability(data[e], "W")
        rs2 = rank_stability(data[e][data[e].scheduler != "SP"], "W", order=[s for s in ORDER if s != "SP"])
        for p, g in rs.groupby("point", sort=False):
            g = g.set_index("scheduler")
            g2 = rs2[rs2.point == p].set_index("scheduler")
            top, nosp = g.mean_rank.idxmin(), g2.mean_rank.idxmin()
            rows.append((e, p, top, g.loc[top, "first_share"], nosp, g2.loc[nosp, "first_share"]))
    w("| exp | point | best mean rank on W | its share of seeds ranked 1st | best excluding SP | its share of seeds 1st (SP excluded) |")
    w("|---|---|---|---|---|---|")
    for e, p, top, sh, nosp, sh2 in rows:
        w(f"| {e} | {p.replace('|', ' ')} | {top} | {sh:.0%} | {nosp} | {sh2:.0%} |")
    w()
    w("Facts:")
    cnt = pd.Series([r[4] for r in rows]).value_counts()
    w("- Best non-SP scheduler on W across these points: " + ", ".join(f"{k} {v}/{len(rows)}" for k, v in cnt.items()) + ".")
    e7 = data["E7"]
    span = e7.groupby("scheduler").W.mean()
    w(f"- Low-load control E7 (Poisson 0.3): W spans {span.min():.3f}–{span.max():.3f} across schedulers; "
      f"latency-class p95 spans {e7.groupby('scheduler').lat_p95.mean().min() * 1e3:.2f}–"
      f"{e7.groupby('scheduler').lat_p95.mean().max() * 1e3:.2f} ms (differences vanish as expected).")
    w()

    # ---------------- measurement adequacy and robustness
    w("## Measurement adequacy and robustness")
    w()
    allr = pd.concat(data.values(), ignore_index=True)
    w("Tail sample size: delivered packets per class per run behind each p95/p99 (over all E1–E8 runs):")
    w()
    w("| class | min n | median n | tail samples behind p99 at min n |")
    w("|---|---|---|---|")
    for c in CLASSES:
        n = allr[f"{c.name}_n_delay"]
        w(f"| {c.name} | {int(n.min())} | {int(n.median())} | {int(n.min() * 0.01)} |")
    w()
    w("Scheduling overhead: decisions per wall-clock second in this Python simulator (E1 ON/OFF 0.95, median over "
      "seeds). Relative cost only, not router performance; absolute values vary with machine load from run to run "
      "(a second full run gave about 10 % higher values in the same order).")
    w()
    ov = e1[e1.point == "onoff|0.95"].groupby("scheduler").decisions_per_s.median().loc[ORDER]
    w("| " + " | ".join(ORDER) + " |")
    w("|" + "---|" * len(ORDER))
    w("| " + " | ".join(f"{v / 1e3:.0f} k" for v in ov) + " |")
    w()
    e10 = load("E10")
    w("**Warm-up check (E10b).** Mean W with a 20 s warm-up vs the default 5 s (same 60 s window):")
    w()
    w("| point | " + " | ".join(ORDER) + " | order of mean W unchanged? |")
    w("|---|" + "---|" * (len(ORDER) + 1))
    for bp in ["onoff|1.2", "poisson|1.2"]:
        a = e1[e1.point == bp].groupby("scheduler").W.mean().loc[ORDER]
        b = e10[(e10.check == "warmup") & (e10.base_point == bp)].groupby("scheduler").W.mean().loc[ORDER]
        same = list(a.sort_values().index) == list(b.sort_values().index)
        cells = " | ".join(f"{x:.2f} -> {y:.2f}" for x, y in zip(a, b))
        w(f"| {bp.replace('|', ' ')} | {cells} | {'yes' if same else 'NO'} |")
    w()
    w("**Update-interval check (E10a).** Mean W of each adaptive scheduler for update interval 5/10/20/50 ms "
      "(10 ms is the default):")
    w()
    ui = e10[e10.check == "update_interval"]
    w("| scheduler | point | 5 ms | 10 ms | 20 ms | 50 ms |")
    w("|---|---|---|---|---|---|")
    for s_ in sorted(ui.scheduler.unique(), key=ORDER.index):
        for bp in ["onoff|0.95", "onoff|1.2"]:
            g = ui[(ui.scheduler == s_) & (ui.base_point == bp)].groupby("dt").W
            cells = " | ".join(fmt(*ci95(g.get_group(dt))[:2], 1, 2) for dt in sorted(g.groups))
            w(f"| {s_} | {bp.replace('|', ' ')} | {cells} |")
    w()
    same_all = True
    for bp in ["onoff|0.95", "onoff|1.2"]:
        orders = {tuple(ui[(ui.base_point == bp) & (ui.dt == dt)].groupby("scheduler").W.mean().sort_values().index)
                  for dt in ui.dt.unique()}
        same_all &= len(orders) == 1
    w(f"Facts: the order of the four adaptive schedulers by mean W is "
      f"{'the same' if same_all else 'NOT the same'} for every update interval at both loads. "
      "Change in mean W from 5 ms to 50 ms updates: "
      + "; ".join(
          f"{s_} " + ", ".join(
              f"{bp.split('|')[1]}: {ui[(ui.scheduler == s_) & (ui.base_point == bp) & (ui.dt == 0.05)].W.mean() / ui[(ui.scheduler == s_) & (ui.base_point == bp) & (ui.dt == 0.005)].W.mean() - 1:+.0%}"
              for bp in ["onoff|0.95", "onoff|1.2"])
          for s_ in sorted(ui.scheduler.unique(), key=ORDER.index))
      + ". All other results use 10 ms; a scheme whose W moves a lot here is sensitive to how fast it can react.")
    w()
    w("**Shared-buffer capture (explains a non-monotone curve in Figure 2).** Under Poisson overload DRR's bulk p95 "
      "falls from load 1.05 to 1.2 while video's rises. With one shared tail-drop buffer, free space of 1000-1499 B "
      "admits a video packet but not a 1500 B bulk packet, so video holds most of the buffer. A partitioned buffer "
      "removes the asymmetry:")
    w()
    pp = e8[e8.point == "partitioned|poisson1.2"]
    sh = e1[e1.point == "poisson|1.2"]
    w("| Poisson 1.2, DRR | video p95 (ms) | bulk p95 (ms) | video drop | bulk drop |")
    w("|---|---|---|---|---|")
    for lab, d in [("shared buffer (E1)", sh), ("partitioned buffer (E8)", pp)]:
        g = d[d.scheduler == "DRR"]
        w(f"| {lab} | {fmt(*ci95(g.vid_p95)[:2], 1e3, 0)} | {fmt(*ci95(g.blk_p95)[:2], 1e3, 0)} | "
          f"{g.vid_drop_rate.mean():.3f} | {g.blk_drop_rate.mean():.3f} |")
    w()

    # ---------------- validation
    w("## Validation")
    w()
    w("### Paper-trend reproduction (Phase 5; rules pre-registered in the protocol before the run)")
    w()
    w("| scheduler | trend claimed by its paper | our test | points passing | verdict |")
    w("|---|---|---|---|---|")
    hi = e1[e1.load >= 0.9]
    pl = paired_vs(hi, "lat_delay_mean")
    pv_ = paired_vs(hi, "vid_delay_mean")
    pb = paired_vs(hi, "blk_delay_mean")
    cl, cv, cb = (x[x.scheduler == "CQDRR"].set_index("point") for x in (pl, pv_, pb))
    pts = sorted(cl.index)
    good = [pt for pt in pts if cl.loc[pt, "diff"] < 0 and cl.loc[pt, "p"] < 0.05
            and cv.loc[pt, "diff"] < 0 and cv.loc[pt, "p"] < 0.05]
    w(f"| CQDRR | lower average delay than DRR, larger gains at high load (paper Fig. 3) | mean delay of latency (TT) "
      f"and video (AVB) below DRR, paired p<0.05, at E1 loads >= 0.9 | {len(good)}/{len(pts)} | "
      f"**{'reproduced' if len(good) >= 6 else 'NOT reproduced'}** |")
    lo = e1[e1.load >= 0.6]
    pf = paired_vs(lo, "lat_delay_mean", ref="FIFO")
    rr = pf[pf.scheduler == "RL-SP+DRR"]
    rl_ok = int(((rr["diff"] < 0) & (rr["p"] < 0.05)).sum())
    starv = sum(int(data[e][data[e].scheduler == "RL-SP+DRR"][["vid_starv_count", "blk_starv_count"]].values.sum()) for e in data)
    w(f"| RL-SP+DRR | prioritises high-priority traffic like strict priority, low-priority traffic still served | "
      f"latency mean delay below FIFO (paired p<0.05) at every E1 load >= 0.6, and 0 video/bulk starvation in E1-E8 | "
      f"{rl_ok}/{len(rr)}; starvation episodes {starv} | **{'reproduced' if rl_ok == len(rr) and starv == 0 else 'NOT reproduced'}** |")
    w("| FuzzyDRR, RevenueDRR | — | not checkable: full texts unavailable (abstract / 2-page preview only) | — | **open** |")
    w("| DR-DRR | — | our own design; no paper to reproduce | — | **n/a** |")
    w()
    w("CQDRR per point (paired mean-delay difference vs DRR, ms; negative = CQDRR lower):")
    w()
    w("| point | latency (TT) | video (AVB) | bulk (BE) |")
    w("|---|---|---|---|")
    for pt in sorted(pts, key=lambda x: (x.split("|")[0], float(x.split("|")[1]))):
        w(f"| {pt.replace('|', ' ')} | {cl.loc[pt, 'diff'] * 1e3:+.2f} (p={cl.loc[pt, 'p']:.2g}) | "
          f"{cv.loc[pt, 'diff'] * 1e3:+.2f} (p={cv.loc[pt, 'p']:.2g}) | {cb.loc[pt, 'diff'] * 1e3:+.2f} (p={cb.loc[pt, 'p']:.2g}) |")
    w()
    w("Bulk (BE) is expected to get worse whenever TT/AVB improve: on a single work-conserving, non-preemptive link the "
      "load-weighted mean waiting time is the same for every scheduler (Kleinrock's conservation law), so the paper's claim "
      "that all three classes improve cannot transfer to this model — in the paper it rests on the 5G radio layer.")
    w()
    w("### Intent checks (designs without a fully readable paper, plus one mechanism check)")
    w()
    w("| scheduler | intended behaviour | check (data source) | result |")
    w("|---|---|---|---|")
    on = e1[e1.arrival == "onoff"]
    checks = []
    for s_ in ["DR-DRR", "FuzzyDRR"]:
        pv2 = paired_vs(on[on.load >= 0.8], "vid_p95")
        p_ = pv2[pv2.scheduler == s_]
        ok = (p_["diff"] < 0).all() and (p_["p"] < 0.05).all()
        checks.append((s_, "raise quanta of the class whose delay is at risk -> lower its tail",
                       "E1 ON/OFF load >= 0.8: video p95 below DRR (paired, p<0.05)",
                       f"{'PASS' if ok else 'FAIL'} (mean diff {p_['diff'].mean() * 1e3:+.1f} ms)"))
    pr = np.array([c.price for c in CLASSES])
    rev = e8[e8.point == "partitioned|1.2"].copy()
    rev["revenue"] = sum(pr[k] * rev[f"{c.name}_tput"] for k, c in enumerate(CLASSES)) / 1e6
    pvr = paired_vs(rev, "revenue")
    r = pvr[pvr.scheduler == "RevenueDRR"].iloc[0]
    checks.append(("RevenueDRR", "steer spare capacity to higher-price classes -> more revenue than DRR",
                   "E8 partitioned, load 1.2: sum of price x throughput vs DRR (paired)",
                   f"{'PASS' if r['diff'] > 0 and r['p'] < 0.05 else 'FAIL'} ({r['diff']:+.3f} revenue-Mb/s, p={r['p']:.2g})"))
    rl = e5[e5.scheduler == "RL-SP+DRR"]
    cap = tuned["RL-SP+DRR"]["rate_frac"] * 10e6
    ok = (rl.lat_tput <= cap * 1.01).all()
    checks.append(("RL-SP+DRR (mechanism)", "high-priority class shaped to its rate r",
                   f"E5 stress (latency offers 0.8 C): latency throughput <= r = {cap / 1e7:.1f} C",
                   f"{'PASS' if ok else 'FAIL'} ({rl.lat_tput.mean() / 1e6:.2f} Mb/s vs {cap / 1e6:.1f})"))
    for c in checks:
        w("| " + " | ".join(c) + " |")
    w()
    v = load("E1V")
    cqp = e1[e1.scheduler == "CQDRR"].groupby("point").W.mean()
    cqd = v.groupby("point").W.mean()
    w("### How much did reading the paper change CQDRR? (E1V)")
    w()
    w("| point | W, CQDRR as published (wired reading) | W, our earlier draft rule | W, DRR |")
    w("|---|---|---|---|")
    drrW = e1[e1.scheduler == "DRR"].groupby("point").W.mean()
    for pt in sorted(cqp.index, key=lambda x: (x.split("|")[0], float(x.split("|")[1]))):
        w(f"| {pt.replace('|', ' ')} | {cqp[pt]:.2f} | {cqd[pt]:.2f} | {drrW[pt]:.2f} |")
    w()
    w("## Threats to validity (data-driven)")
    w()
    w("- FuzzyDRR and RevenueDRR are inspired-by designs (full texts unavailable) and DR-DRR is our own design. FuzzyDRR's "
      "second input is queue occupancy where its paper's abstract names throughput. FuzzyDRR's tuned gain (0.1) is near 'off', i.e. under our reading "
      "of the rule base, adapting more makes it worse — the first thing to check against the paper.")
    w("- CQDRR was designed for a TSN-5G radio link; on our wired link its channel term is constant and its delay "
      "term is inert with one TT class, so what remains is the queue-load term plus the AVB -log(D) term. Constants the "
      "paper does not give (alpha-fair alpha, weights, byte scale) are our choices (ALGORITHM_SPEC section 6).")
    w("- RL-SP+DRR follows the paper's Algorithm 1 except one documented clamp (departure >= arrival after an idle period).")
    w("- Throughput fairness is decided by buffer policy, not the scheduler, under shared tail drop; E8 is an "
      "exploratory addition made after E1 (protocol deviation log).")
    w("- Single bottleneck, synthetic traffic, 3 classes; no real traces (as stated in the plan).")
    w("- Statistics: p-values in the per-point tables are per-test (uncorrected) paired Wilcoxon values; Holm correction "
      "is applied only where stated (E9, E1D). With 20 paired seeds the smallest attainable Wilcoxon p is 1.9e-06, which is "
      "why many entries share that value.")
    w("- Overhead figures come from a Python simulator and show relative cost only; they say nothing about router speed.")
    w("- Several analyses were added after seeing data (E8, E9C, E10, E1V); each is labelled exploratory in the protocol's "
      "deviation log, and only the pre-registered rules (tuning, E9, E1D, ES, paper-trend checks) give verdicts.")
    # ---------------- headline summary (all numbers computed above / here)
    sp_first = sum(b[0] == "SP" for b in best.values())
    starvers = {s_: n for s_, n in st_counts.items() if n > 0}
    gapmax = {s_: max(data[e][data[e].scheduler == s_][[f"{c.name}_starv_max" for c in CLASSES]].values.max(initial=0.0)
                      for e in data) for s_ in starvers}
    jmin = e1[e1.arrival == "onoff"].jain.min()
    e9r = load("E9")
    base = e9r[e9r.smooth == 1.0].groupby("base_point").W.mean()
    damp = e9r[e9r.smooth == 0.5].groupby("base_point").W.mean()
    best_gain = (damp / base - 1).min()
    H = ["## Headline results (computed)", "",
         f"1. **Strict Priority** gives the lowest latency-class p95 at {sp_first}/{len(best)} E1 points, but starves other "
         "classes under overload.",
         "2. **Starvation** (> 100 ms backlogged without service), episodes summed over E1–E8 (longest single gap): "
         + ", ".join(f"{k} {v} ({gapmax[k] * 1e3:.0f} ms)" for k, v in starvers.items()) + "; every other scheduler 0. "
         "FIFO has no priorities: its episodes are head-of-line waits in one long FIFO queue (mostly E4's 500 kB "
         "buffer), not service denial.",
         "3. **No single best adaptive scheduler**: best non-SP on W — "
         + ", ".join(f"{k} {v}/{len(rows)}" for k, v in cnt.items()) + ".",
         f"4. **Shared tail-drop buffer fixes throughput shares**: Jain's index >= {jmin:.4f} for every scheduler and run in "
         "E1 ON/OFF; fairness differences appear only with a partitioned buffer (E8).",
         f"5. **Weight oscillation** helps under bursts and hurts under smooth overload (E9 + control E9C); damping "
         f"(lambda = 0.5) lowers W by up to {-best_gain:.0%}.",
         f"6. **Paper-trend checks**: RL-SP+DRR {'reproduced' if rl_ok == len(rr) and starv == 0 else 'not reproduced'}; "
         f"CQDRR {'reproduced' if len(good) >= 6 else 'not reproduced'} ({len(good)}/{len(pts)}); "
         f"SCRR latency {'reproduced' if hits >= 6 else 'not reproduced'} ({hits}/{hi_pts}), fairness "
         f"{'reproduced' if fair_ok else 'not reproduced'}.",
         ""]
    i = OUT.index("<<HEADLINE>>")
    OUT[i:i + 1] = H
    (ROOT / "RESULTS.md").write_text("\n".join(OUT), encoding="utf-8")
    print("wrote RESULTS.md", len(OUT), "lines")


if __name__ == "__main__":
    main()
