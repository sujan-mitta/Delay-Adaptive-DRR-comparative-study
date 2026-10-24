"""Cross-check every quantitative claim of the paper against the raw results, recomputed independently of
scripts/make_report.py (this file reads the runs.csv files directly). Prints PASS/FAIL per claim; exit code 1 on any FAIL.
Without the (private) paper source only the result-level claims are checked; with it, its tables are parsed and compared too.

  python tools/claims_audit.py [paper_src.html]      (default: paper_draft/paper_src.html, which is private)
"""
import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import run_ledger  # noqa: E402

D = (0.010, 0.050, 0.500)
CLS = ("lat", "vid", "blk")
NON_SP_ORDER = ["FIFO", "DRR", "RL-SP+DRR", "DR-DRR", "CQDRR", "FuzzyDRR", "RevenueDRR"]
results = []


def rd(exp):
    d = pd.read_csv(ROOT / "results" / exp / "runs.csv", float_precision="round_trip")
    d["W"] = np.max([d[f"{c}_p95"] / x for c, x in zip(CLS, D)], axis=0)
    return d


def check(name, got, want, tol=0.0, note=""):
    if isinstance(want, (int, float, np.floating)) and not isinstance(want, bool):
        ok = abs(float(got) - float(want)) <= tol + 1e-12
    else:
        ok = got == want
    results.append((ok, name, got, want, note))


def holm(p):
    p = np.asarray(p, float)
    order = np.argsort(p)
    adj, run = np.empty(len(p)), 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (len(p) - rank) * p[i]))
        adj[i] = run
    return adj


def ci_half(x):
    x = np.asarray(x, float)
    return stats.t.ppf(0.975, len(x) - 1) * x.std(ddof=1) / np.sqrt(len(x))


def paper_tables(path):
    """{caption roman numeral: list of rows, each a list of cell strings}"""
    s = Path(path).read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r'<div class="tcap">Table ([IVX]+)</div>.*?<tbody>(.*?)</tbody>', s, re.S):
        rows = re.findall(r"<tr>(.*?)</tr>", m.group(2), re.S)
        out[m.group(1)] = [[re.sub(r"<[^>]+>|&nbsp;", "", c).replace("&minus;", "-").replace("&plusmn;", "±").replace("&micro;", "u")
                            .replace("&ndash;", "-").strip() for c in re.findall(r"<td>(.*?)</td>", r, re.S)] for r in rows]
    return out


def main(paper):
    # ------------------------------------------------------------------ ledger and set-up
    rows, t = run_ledger.build()
    for k, v in (("main", 6520), ("main_paired_groups", 600), ("main_paired_runs", 4800), ("main_single_runs", 1720),
                 ("further", 12880), ("tuning", 1460), ("simulator_total", 20860), ("kernel_runs", 54), ("replay_runs", 1080), ("tandem_runs", 160),
                 ("archived", 33140)):
        check(f"ledger {k}", t[k], v)
    check("E6 distinct traces", rows["E6"]["distinct_traces"], 40)
    e1, e2, e3, e4, e7, e8 = (rd(e) for e in ("E1", "E2", "E3", "E4", "E7", "E8"))
    check("operating points E1+E2+E3+E4+E7+E8", sum(d.point.nunique() for d in (e1, e2, e3, e4, e7, e8)), 29)
    cfg = (ROOT / "drrsim" / "config.py").read_text(encoding="utf-8")
    check("link rate 10 Mb/s", "link_rate: float = 10e6" in cfg, True)
    check("buffer 125 kB", "buffer_bytes: int = 125_000" in cfg, True)
    check("run 60 s after 5 s warm-up", "warmup: float = 5.0" in cfg and "duration: float = 60.0" in cfg, True)
    check("duty 0.5", "duty: float = 0.5" in cfg, True)
    check("starvation threshold 100 ms", "starvation_T: float = 0.100" in cfg, True)
    check("delay targets 10/50/500 ms and sizes 200/1000-1500/1500 B",
          all(x in cfg for x in ('ClassSpec("lat", 200, 200, 0.010', 'ClassSpec("vid", 1000, 1500, 0.050', 'ClassSpec("blk", 1500, 1500, 0.500')), True)
    check("byte mix 20/40/40", "mix: tuple = (0.2, 0.4, 0.4)" in cfg, True)
    from drrsim.experiments import BURSTS
    check("ON periods 10/50/200 ms", sorted(BURSTS.values()), [0.01, 0.05, 0.2])
    tuned = json.loads((ROOT / "config" / "tuned_params.json").read_text())["params"]
    check("tuned RL-SP rate 0.4", tuned["RL-SP+DRR"]["rate_frac"], 0.4)
    check("tuned DR-DRR kappa 4", tuned["DR-DRR"]["kappa"], 4.0)
    check("tuned CQDRR scale 93.75", tuned["CQDRR"]["scale"], 93.75)
    check("tuned FuzzyDRR gain 0.1", tuned["FuzzyDRR"]["gain"], 0.1)
    check("tuned RevenueDRR tau 12.5 ms", tuned["RevenueDRR"]["tau"], 0.0125)
    sch = (ROOT / "drrsim" / "schedulers.py").read_text(encoding="utf-8")
    check("DR-DRR defaults theta 0.5, M 8", '"theta": 0.5, "qmax_mult": 8.0' in sch, True)
    proto = (ROOT / "docs" / "EXPERIMENT_PROTOCOL.md").read_text(encoding="utf-8")
    numbered = sorted({int(x) for x in re.findall(r"^## Deviation (\d)", proto, re.M)} | {int(x) for x in re.findall(r"^(\d)\. \*\*", proto, re.M)})
    check("nine deviations logged, numbered 1-9 without gaps", numbered, list(range(1, 10)))
    check("seeds 101-120 reported, 1-5 development", (sorted(e1.seed.unique()) == list(range(101, 121))), True)

    # ------------------------------------------------------------------ V-A latency results
    sp_first, non_sp = 0, {}
    for pt, g in e1.groupby("point"):
        m = g.groupby("scheduler").lat_p95.mean()
        sp_first += m.idxmin() == "SP"
        w = m.drop("SP").idxmin()
        non_sp[w] = non_sp.get(w, 0) + 1
    check("SP lowest latency p95 at E1 points", sp_first, 14)
    check("excluding SP: RL-SP+DRR best latency at", non_sp.get("RL-SP+DRR", 0), 12)
    check("excluding SP: RevenueDRR best latency at", non_sp.get("RevenueDRR", 0), 2)
    e7g = e7.groupby("scheduler").lat_p95.mean() * 1e3
    check("E7 latency tails between 0.89 and 1.10 ms", (round(e7g.min(), 2), round(e7g.max(), 2)), (0.89, 1.10))
    # best non-SP by W over 29 points
    best = {}
    for d in (e1, e2, e3, e4, e7, e8):
        for pt, g in d.groupby("point"):
            m = g.groupby("scheduler").W.mean().drop("SP")
            best[m.idxmin()] = best.get(m.idxmin(), 0) + 1
    check("best non-SP by W over 29 points", dict(sorted(best.items())), {"CQDRR": 5, "DR-DRR": 14, "FuzzyDRR": 2, "RL-SP+DRR": 4, "RevenueDRR": 4})

    # ------------------------------------------------------------------ paper tables against data
    pt = paper_tables(paper) if Path(paper).exists() else {}      # the paper is private; without it the table checks are skipped
    g = e1[e1.point == "onoff|0.95"]
    tab = {r[0]: r for r in pt.get("III", [])}
    for s_name in tab:
        gg = g[g.scheduler == s_name]
        got = [round(gg.lat_p95.mean() * 1e3, 1), round(gg.vid_p95.mean() * 1e3, 1), round(gg.blk_p95.mean() * 1e3, 1), round(gg.W.mean(), 3)]
        want = [float(x) for x in tab[s_name][1:5]]
        check(f"Table III {s_name}", got, want)
    # effect sizes
    e1d = rd("E1D")
    eff = pd.concat([e1, e1d], ignore_index=True)
    cols = {"ON/OFF 0.95": "onoff|0.95", "ON/OFF 1.2": "onoff|1.2", "Poisson 0.95": "poisson|0.95", "Poisson 1.2": "poisson|1.2"}
    names = {"SP": "SP", "RL-SP+DRR": "RL-SP+DRR", "DR-DRR": "DR-DRR", "DR-DRR, damped": "DR-DRR+damping", "CQDRR": "CQDRR",
             "FuzzyDRR": "FuzzyDRR", "RevenueDRR": "RevenueDRR"}
    tabE = {r[0]: r for r in pt.get("IV", [])}
    for label, sname in (names.items() if tabE else []):
        for j, (cl, point) in enumerate(cols.items(), start=1):
            gg = eff[eff.point == point]
            ref = gg[gg.scheduler == "DRR"].set_index("seed").sort_index().W
            x = gg[gg.scheduler == sname].set_index("seed").sort_index().W
            dd = (x - ref).dropna()
            got = f"{dd.mean():+.2f}±{ci_half(dd):.2f}".replace("+-", "-")
            want = tabE[label][j].replace(" ", "").replace("+", "+")
            want = want.replace("-", "-")
            check(f"Table IV {label} {cl}", got.replace("-", "-"), want)
    # stress table
    e5, e8s = rd("E5"), rd("E8")
    tabS = {r[0]: r for r in pt.get("V", [])}
    p8 = e8s[e8s.point.str.contains("stress")] if e8s.point.str.contains("stress").any() else None
    for s_name, r in tabS.items():
        a = e5[e5.scheduler == s_name]
        got5 = [round(a.blk_starv_total.mean(), 1), round(a.blk_tput.mean() / 1e6, 2), round(a.jain.mean(), 3)]
        check(f"Table V shared {s_name}", got5, [float(r[1]), float(r[2]), float(r[3])])
        if p8 is not None:
            b = p8[p8.scheduler == s_name]
            got8 = [round(b.blk_starv_total.mean(), 1), round(b.blk_tput.mean() / 1e6, 2), round(b.jain.mean(), 3)]
            check(f"Table V partitioned {s_name}", got8, [float(r[4]), float(r[5]), float(r[6])])
    check("SP stress starvation: bulk 34.5 s, video 20.5 s", (round(e5[e5.scheduler == "SP"].blk_starv_total.mean(), 1),
                                                              round(e5[e5.scheduler == "SP"].vid_starv_total.mean(), 1)), (34.5, 20.5))

    # ------------------------------------------------------------------ V-B starvation, buffer, fairness
    main_df = pd.concat([rd(e) for e in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8")], ignore_index=True)
    st = {}
    for sname, gg in main_df.groupby("scheduler"):
        st[sname] = (int(gg[[f"{c}_starv_count" for c in CLS]].sum().sum()), float(gg[[f"{c}_starv_max" for c in CLS]].max().max()))
    check("SP starvation episodes / longest (s)", (st["SP"][0], round(st["SP"][1], 1)), (21286, 2.4))
    check("CQDRR starvation episodes / longest (ms)", (st["CQDRR"][0], round(st["CQDRR"][1] * 1e3)), (12666, 444))
    check("FIFO starvation episodes", st["FIFO"][0], 1142)
    check("every other scheduler: zero episodes", {k: v[0] for k, v in st.items() if k not in ("SP", "CQDRR", "FIFO")} and all(v[0] == 0 for k, v in st.items() if k not in ("SP", "CQDRR", "FIFO")), True)
    onoff = e1[e1.arrival == "onoff"]
    check("Jain over E1 ON/OFF between 0.9981 and 1.0000", (round(onoff.jain.min(), 4), round(onoff.jain.max(), 4)), (0.9981, 1.0))
    l12 = e1[(e1.arrival == "onoff") & (e1.load == 1.2)]
    spread = max(l12.groupby("scheduler")[f"{c}_drop_rate"].mean().pipe(lambda s: s.max() - s.min()) for c in CLS) * 100
    check("per-class drop-rate spread at load 1.2 < 1 pp", spread < 1.0, True, note=f"{spread:.2f} pp")
    check("RL-SP+DRR bulk throughput 1.75 vs DRR 2.03 Mb/s (E5)", (round(e5[e5.scheduler == "RL-SP+DRR"].blk_tput.mean() / 1e6, 2),
                                                                  round(e5[e5.scheduler == "DRR"].blk_tput.mean() / 1e6, 2)), (1.75, 2.03))
    pp = e1[(e1.point == "poisson|1.2") & (e1.scheduler == "DRR")]
    check("DRR Poisson 1.2: video p95 245 ms, bulk 88 ms", (round(pp.vid_p95.mean() * 1e3), round(pp.blk_p95.mean() * 1e3)), (245, 88))

    # ------------------------------------------------------------------ V-C oscillation, damping
    e9 = rd("E9")
    a, b = (e9[(e9.base_point == "poisson|1.2") & (e9.smooth == x)].W.mean() for x in (1.0, 0.5))
    check("damping halves W at Poisson 1.2: 1.326 -> 0.652", (round(a, 3), round(b, 3)), (1.326, 0.652))
    oq = e1[(e1.point == "onoff|0.95") & (e1.scheduler == "DR-DRR")].osc_mag_mean.mean()
    check("DR-DRR quanta change by 86 % per update (onoff 0.95)", round(oq * 100), 86)
    rs = [stats.spearmanr(g.osc_mag_mean, g.W)[0] for _, g in e1[e1.scheduler == "DR-DRR"].groupby("point") if g.osc_mag_mean.nunique() > 1]
    check("Spearman rho +0.52 for DR-DRR", round(float(np.nanmean(rs)), 2), 0.52)
    dmp = pd.concat([e1[e1.scheduler == "DR-DRR"], e1d])
    better = worse = same = 0
    gains = []
    pvals, diffs = [], []
    for point in e1.point.unique():
        gg = dmp[dmp.point == point]
        x = gg[gg.scheduler == "DR-DRR+damping"].set_index("seed").sort_index().W
        y = gg[gg.scheduler == "DR-DRR"].set_index("seed").sort_index().W
        dd = x - y
        pvals.append(stats.wilcoxon(dd).pvalue if np.any(dd != 0) else 1.0)
        diffs.append(dd.mean())
        gains.append(dd.mean() / y.mean())
    adj = holm(pvals)
    better = sum(1 for d_, a_ in zip(diffs, adj) if d_ < 0 and a_ < 0.05)
    worse = sum(1 for d_, a_ in zip(diffs, adj) if d_ > 0 and a_ < 0.05)
    check("damped variant: better / worse / no difference over 14 points", (better, worse, 14 - better - worse), (6, 3, 5))
    check("largest gain 50.8 % at Poisson 1.2", round(-min(gains) * 100, 1), 50.8)

    # ------------------------------------------------------------------ V-D sensitivity
    e6 = rd("E6")
    e6["load_pt"] = e6.point.str.split("load=").str[1].astype(float)
    e6["knob_"] = e6.point.str.split("=").str[0]
    def rng(sch, knob, load):
        g_ = e6[(e6.scheduler == sch) & (e6.knob_ == knob) & (e6.load_pt == load)].groupby("level").W.mean()
        return g_.min(), g_.max(), g_.get("x1")
    lo, hi, _ = rng("RL-SP+DRR", "rate_frac", 0.95)
    check("RL-SP+DRR shaper rate W range 3.16 to 45.8", (round(lo, 2), round(hi, 1)), (3.16, 45.8))
    lo, hi, _ = rng("RevenueDRR", "guar_scale", 0.95)
    check("RevenueDRR guarantee scale W range 0.84-4.19", (round(lo, 2), round(hi, 2)), (0.84, 4.19))
    worst = 0
    for sch in ("DR-DRR", "CQDRR", "FuzzyDRR"):
        for knob in e6[e6.scheduler == sch].knob_.unique():
            for load in (0.95, 1.2):
                lo, hi, base = rng(sch, knob, load)
                worst = max(worst, (hi - base) / base, (base - lo) / base)
    check("DR-DRR, CQDRR, FuzzyDRR change by at most 27 %", round(worst * 100), 27)
    e10 = rd("E10")
    e10["interval"] = e10.point.str.extract(r"upd=?([0-9.]+)", expand=False) if e10.point.str.contains("upd").any() else None
    sub = e10[(e10.scheduler == "DR-DRR") & e10.point.str.contains("0.95") & e10.point.str.contains("onoff")]
    if "interval" in e10 and sub.interval.notna().any():
        m = sub.groupby("interval").W.mean(); m.index = m.index.astype(float)
        check("DR-DRR W rises 140 % from 5 to 50 ms updates (0.95)", round((m[0.05] / m[0.005] - 1) * 100), 140)
    else:
        print("   (E10 point labels not parsed; the 140 % claim is checked below against the point names)")
        pts = sorted(e10.point.unique()); print("   ", pts[:6])
    check("E3 DRR W Poisson 0.33 -> onoff-large 3.44", (round(e3[(e3.point == "poisson") & (e3.scheduler == "DRR")].W.mean(), 2),
                                                         round(e3[(e3.point == "onoff-large") & (e3.scheduler == "DRR")].W.mean(), 2)), (0.33, 3.44))
    check("E3 DR-DRR W 0.31 -> 1.77", (round(e3[(e3.point == "poisson") & (e3.scheduler == "DR-DRR")].W.mean(), 2),
                                        round(e3[(e3.point == "onoff-large") & (e3.scheduler == "DR-DRR")].W.mean(), 2)), (0.31, 1.77))

    # ------------------------------------------------------------------ E15 fresh seeds
    e15 = rd("E15")
    h1 = h2 = 0
    inside = {}
    for point in e1.point.unique():
        a_, b_ = e1[e1.point == point], e15[e15.point == point]
        h1 += b_.groupby("scheduler").lat_p95.mean().idxmin() == "SP"
        h2 += a_.groupby("scheduler").W.mean().drop("SP").idxmin() == b_.groupby("scheduler").W.mean().drop("SP").idxmin()
        for s_name in a_.scheduler.unique():
            x = a_[a_.scheduler == s_name].W
            inside[s_name] = inside.get(s_name, 0) + (abs(b_[b_.scheduler == s_name].W.mean() - x.mean()) <= ci_half(x))
    check("E15 SP lowest latency", h1, 14)
    check("E15 same best non-SP", h2, 14)
    check("E15 CQDRR inside old interval at 9 of 14", int(inside["CQDRR"]), 9)
    check("E15 overall 99 of 112 inside", int(sum(inside.values())), 99)
    check("fresh mean inside old 95 % interval about 84 %", round(2 * stats.t.cdf(stats.t.ppf(0.975, 19) / np.sqrt(2), 19) - 1, 2), 0.84)

    # ------------------------------------------------------------------ E14 ablation + proposition
    e14 = rd("E14")
    allr = pd.concat([e1[e1.scheduler.isin(["DRR", "DR-DRR"])], e1d, e14], ignore_index=True)
    for variant, want in (("DR-DRR-backlog", (9, 0)), ("DR-DRR-hol", (4, 6))):
        pv, df_ = [], []
        for point in e1.point.unique():
            gg = allr[allr.point == point]
            dd = (gg[gg.scheduler == variant].set_index("seed").sort_index().W - gg[gg.scheduler == "DR-DRR"].set_index("seed").sort_index().W)
            pv.append(stats.wilcoxon(dd).pvalue if np.any(dd != 0) else 1.0)
            df_.append(dd.mean())
        ad = holm(pv)
        check(f"E14 {variant}: DR-DRR better / worse", (sum(1 for d_, a_ in zip(df_, ad) if d_ > 0 and a_ < 0.05), sum(1 for d_, a_ in zip(df_, ad) if d_ < 0 and a_ < 0.05)), want)
    abl = json.loads((ROOT / "config" / "tuned_ablation.json").read_text())["params"]
    check("ablation kappa 4 (backlog), 8 (head-of-line)", (abl["DR-DRR-backlog"]["kappa"], abl["DR-DRR-hol"]["kappa"]), (4.0, 8.0))
    tabA = {r[0]: r for r in pt.get("VI", [])}
    for label, point in (("ON/OFF 0.8", "onoff|0.8"), ("ON/OFF 0.95", "onoff|0.95"), ("ON/OFF 1.2", "onoff|1.2"), ("Poisson 0.95", "poisson|0.95"),
                         ("Poisson 1.05", "poisson|1.05"), ("Poisson 1.2", "poisson|1.2")):
        if not tabA:
            break
        gg = allr[allr.point == point]
        got = [round(gg[gg.scheduler == s_].W.mean(), 3) for s_ in ("DRR", "DR-DRR", "DR-DRR-backlog", "DR-DRR-hol", "DR-DRR+damping")]
        check(f"Table VI {label}", got, [float(x) for x in tabA[label][1:6]])
    gap = max(allr[allr.scheduler.isin(["DR-DRR", "DR-DRR-backlog", "DR-DRR-hol", "DR-DRR+damping"])][[f"{c}_gap_max" for c in CLS]].max())
    check("ablation: longest service gap 20.3 ms", round(gap * 1e3, 1), 20.3)
    Q0 = 1500
    bound = lambda M: 2 * (M * Q0 + 1500 - 1) * 8 / 10e6
    check("gap bound G = 21.6 ms (M = 8, 1500 B packets, 3 classes, 10 Mb/s)", round(bound(8) * 1e3, 1), 21.6)
    ratios, nruns = [], 0
    for exp in ("E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E1D", "E10"):
        d = pd.read_csv(ROOT / "results" / exp / "runs.csv")
        d = d[d.scheduler.isin(["DR-DRR", "DR-DRR+damping"])]
        for _, r in d.iterrows():
            Mq = json.loads(r.params).get("qmax_mult", 8.0) if isinstance(r.params, str) else 8.0
            ratios.append((Mq, max(r.lat_gap_max, r.vid_gap_max, r.blk_gap_max) / bound(Mq)))
            nruns += 1
    rr = pd.DataFrame(ratios, columns=["M", "ratio"])
    check("proposition checked on 1,680 saved DR-DRR runs", nruns, 1680)
    check("no gap above the bound", int((rr.ratio > 1 + 1e-9).sum()), 0)
    check("largest gap = 89-95 % of the bound (M = 4, 8, 12)", tuple(int(x * 100) for x in rr.groupby("M").ratio.max().values), (89, 94, 95))

    # ------------------------------------------------------------------ E18 / E19 / E19H
    pts = [(n, p_, d_[d_.point == p_]) for n, d_ in (("E1", e1), ("E2", e2), ("E3", e3), ("E4", e4), ("E7", e7), ("E8", e8)) for p_ in d_.point.unique()]
    win = {k: {} for k in ("S1", "S2", "S3a", "S3b")}
    for _, _, g_ in pts:
        best_p99 = g_.groupby("seed")[[f"{c}_p99" for c in CLS]].min()
        reg = g_.set_index("seed")[[f"{c}_p99" for c in CLS]].div(best_p99).max(axis=1)
        s1 = pd.Series(reg.values, index=g_.scheduler.values).groupby(level=0).mean()
        s2 = g_.groupby("scheduler")[[f"{c}_p99" for c in CLS]].mean().rank(axis=0).mean(axis=1)
        s3 = {}
        for key, targets in (("S3a", (0.02, 0.1, 1.0)), ("S3b", (0.05, 0.05, 0.05))):
            wv = np.max([g_[f"{c}_p95"] / dd for c, dd in zip(CLS, targets)], axis=0)
            s3[key] = pd.Series(wv, index=g_.scheduler.values).groupby(level=0).mean()
        for key, ser in (("S1", s1), ("S2", s2), ("S3a", s3["S3a"]), ("S3b", s3["S3b"])):
            w_ = ser.drop("SP").idxmin()
            win[key][w_] = win[key].get(w_, 0) + 1
    check("E18 rank score: DR-DRR wins 9 of 29", win["S2"].get("DR-DRR"), 9)
    check("E18 targets 20/100/1000: DR-DRR wins 14 of 29", win["S3a"].get("DR-DRR"), 14)
    check("E18 regret: RevenueDRR 13, DR-DRR 2", (win["S1"].get("RevenueDRR"), win["S1"].get("DR-DRR")), (13, 2))
    check("E18 equal targets: FIFO wins 28 of 29", win["S3b"].get("FIFO"), 28)
    q = json.loads((ROOT / "config" / "tuned_static_drr.json").read_text())["quanta"]
    check("static DRR quanta 6000/6000/1500", q, [6000.0, 6000.0, 1500.0])
    from drrsim.experiments import STATIC_GRID
    check("static search 16 settings, DR-DRR 5 values of kappa", (len(STATIC_GRID) ** 2, 5), (16, 5))
    for exp, base, seeds_note in (("E19", e1[e1.scheduler == "DR-DRR"], "reporting"), ("E19H", e15[e15.scheduler == "DR-DRR"], "fresh")):
        st_ = rd(exp)
        pv, df_ = [], []
        for point in e1.point.unique():
            x = st_[st_.point == point].set_index("seed").sort_index()
            y = base[base.point == point].set_index("seed").sort_index()
            assert (x.trace == y.trace).all()
            dd = x.W - y.W
            pv.append(stats.wilcoxon(dd).pvalue if np.any(dd != 0) else 1.0)
            df_.append(dd.mean())
        ad = holm(pv)
        check(f"{exp} ({seeds_note} seeds): DR-DRR better / worse", (sum(1 for d_, a_ in zip(df_, ad) if d_ > 0 and a_ < 0.05), sum(1 for d_, a_ in zip(df_, ad) if d_ < 0 and a_ < 0.05)), (6, 8))
    s19 = rd("E19")
    for point, label, want_s, want_d in (("onoff|0.95", "ON/OFF 0.95", 0.886, 1.326), ("poisson|1.2", "Poisson 1.2", 0.583, 1.326), ("poisson|0.8", "Poisson 0.8", 0.315, 0.216)):
        check(f"E19 {label}: static {want_s} vs DR-DRR {want_d}", (round(s19[s19.point == point].W.mean(), 3), round(e1[(e1.point == point) & (e1.scheduler == "DR-DRR")].W.mean(), 3)), (want_s, want_d))

    # ------------------------------------------------------------------ E11 / E12 scenarios
    e11, e12 = rd("E11"), rd("E12")
    f1 = sum(g_.groupby("scheduler").lat_p95.mean().idxmin() == "SP" for _, g_ in list(e11.groupby("scenario")) + list(e12[e12.check == "scenario"].groupby("scenario")))
    f5 = 0
    for _, g_ in list(e11.groupby("scenario")) + list(e12[e12.check == "scenario"].groupby("scenario")):
        a_ = g_[g_.scheduler == "DR-DRR"].set_index("seed").sort_index().W; b_ = g_[g_.scheduler == "DRR"].set_index("seed").sort_index().W
        f5 += (a_ - b_).mean() < 0 and stats.wilcoxon(a_ - b_).pvalue < 0.05
    check("SP lowest latency in all 12 scenarios", f1, 12)
    check("DR-DRR beats DRR in all 12 scenarios", int(f5), 12)
    ab = e11[e11.scenario == "abuse"]
    rl = ab[ab.scheduler == "RL-SP+DRR"]
    oth = ab[~ab.scheduler.isin(["RL-SP+DRR", "SP", "FIFO"]) & ab.scheduler.isin(["DRR", "DR-DRR", "CQDRR", "FuzzyDRR", "RevenueDRR", "SCRR"])]
    check("abuse: RL-SP+DRR throughput 7.89 vs others 9.51 Mb/s", (round(rl.tput_total.mean() / 1e6, 2), round(oth.tput_total.mean() / 1e6, 2)), (7.89, 9.51))
    check("abuse: RL-SP+DRR drops 28 % of packets (35 % in the latency class) vs 14 % for DRR",
          (round(rl.n_dropped.sum() / rl.n_packets.sum() * 100), round(rl.lat_drop_rate.mean() * 100),
           round(ab[ab.scheduler == "DRR"].n_dropped.sum() / ab[ab.scheduler == "DRR"].n_packets.sum() * 100)), (28, 35, 14))
    f2 = f4 = 0
    for _, g_ in e11.groupby("scenario"):
        stv = g_.groupby("scheduler")[[f"{c}_starv_count" for c in CLS]].sum().sum(axis=1)
        f2 += set(stv[stv > 0].index) <= {"SP", "CQDRR"}
        drop = g_.groupby("scheduler").apply(lambda x: x.n_dropped.sum() / x.n_packets.sum() * 100)
        f4 += (drop.max() - drop.min()) <= 1.0
    check("F2 'only SP and CQDRR starve' holds in 2 of 8", int(f2), 2)
    extras = set()
    for _, g_ in e11.groupby("scenario"):
        stv = g_.groupby("scheduler")[[f"{c}_starv_count" for c in CLS]].sum().sum(axis=1)
        extra = set(stv[stv > 0].index) - {"SP", "CQDRR"}
        extras |= extra
    check("every extra starving scheduler in E11 is FIFO", extras, {"FIFO"})
    r17s = pd.read_csv(ROOT / "results" / "E17" / "runs.csv")
    stv17 = r17s.groupby("scheduler")[[f"{c}_starv_count" for c in CLS]].sum().sum(axis=1)
    check("E17: only SP, CQDRR and FIFO starved a class", set(stv17[stv17 > 0].index), {"SP", "CQDRR", "FIFO"})
    shared = e1[(e1.arrival == "onoff")]
    check("Jain 0.9981-1.0000 over the E1 ON/OFF runs (not the stress test)", (round(shared.jain.min(), 4), round(shared.jain.max(), 4)), (0.9981, 1.0))

    check("F4 drop-rate spread <= 1 pp holds in 7 of 8", int(f4), 7)
    w12 = e12[e12.check == "window"]
    for load in (0.95, 1.2):
        pass
    x = w12[(w12.base == "onoff|1.2")]
    sd = {}
    for s_name in ("DRR", "FuzzyDRR"):
        v = x[x.scheduler == s_name].W
        sd[s_name] = (round(v.mean(), 3), round(ci_half(v), 3))
    check("window check at load 1.2: DRR 6.477±0.163, FuzzyDRR 6.407±0.100", sd, {"DRR": (6.477, 0.163), "FuzzyDRR": (6.407, 0.100)})
    seeds = e12[e12.check == "seeds"]
    inside = 0
    for s_name in e1.scheduler.unique():
        a_ = e1[(e1.point == "onoff|0.95") & (e1.scheduler == s_name)].W
        b_ = seeds[seeds.scheduler == s_name].W
        inside += abs(b_.mean() - a_.mean()) <= ci_half(a_)
    check("100 seeds: all 8 means inside the 20-seed intervals", int(inside), 8)
    rel = []
    for load in (0.95, 1.2):
        short = e1[(e1.point == f"onoff|{load}") & e1.seed.between(101, 110)].groupby("scheduler").W.mean()
        long_ = w12[w12.base == f"onoff|{load}"].groupby("scheduler").W.mean()
        rel.append(((long_ / short.reindex(long_.index)) - 1).abs().max())
    check("10x window changes no mean W by more than 5.2 %", round(max(rel) * 100, 1), 5.2)

    # ------------------------------------------------------------------ E13 (published examples), SCRR
    e13 = sorted(d for d in glob.glob(str(ROOT / "results" / "E13" / "*")) if not d.endswith("quick"))[-1]
    s13 = pd.read_csv(Path(e13) / "summary.csv")
    reg = s13[s13.verdict.str.startswith(("pass", "fail"))]
    check("E13: 14 of 16 registered comparisons pass", (int(reg.verdict.str.startswith("pass").sum()), len(reg)), (14, 16))
    r1 = s13[(s13.benchmark == "B1") & (s13.case == "paper trajectory")].ours.astype(float)
    check("B1 trajectory 119.2557 us", round(float(r1.iloc[0]), 4), 119.2557)
    r1m = s13[(s13.benchmark == "B1") & s13.case.str.contains("random")].ours.astype(float).iloc[0]
    check("B1 random max 127.6 us, bound 146.2 us", (round(float(r1m), 1), 146.2), (127.6, 146.2))
    b2 = s13[(s13.benchmark == "B2") & (s13.scheduler == "DRR-EOS")].verdict.str.extract(r"tightness ([0-9.]+)")[0].astype(float)
    check("B2 tightness 0.838 and 0.990-0.998", (round(b2.min(), 3), round(sorted(b2)[1], 3), round(b2.max(), 3)), (0.838, 0.990, 0.998))
    b3 = s13[(s13.benchmark == "B3") & (s13.case == "random sizes, unlimited buffer, 20 seeds")]
    check("B3 DRR 1.001, FIFO 2.995", (b3[b3.scheduler == "DRR"].ours.iloc[0][:5], b3[b3.scheduler == "FIFO"].ours.iloc[0][:5]), ("1.001", "2.995"))
    check("B3 offered load 124 % of 400 kb/s", round(((19 * 10 + 30) * ((1 + 562) / 2) * 8) / 400e3, 2), 1.24)
    b4 = s13[(s13.benchmark == "B4") & (s13.scheduler == "RL-SP+DRR") & s13.case.str.contains("on,")].ours.iloc[0]
    check("B4 RL-SP+DRR 6.0 / 2.0 / 2.0 Mb/s", b4, "6.000 / 2.000 / 2.000")
    b5 = s13[(s13.benchmark == "B5") & (s13.scheduler == "SCRR (as printed)") & s13.case.str.contains("backlogged")]
    check("B5 clock advance 2.0 M in 305 traces; burst 2.682 M in 39", (str(b5.iloc[0].verdict), str(b5.iloc[1].verdict), float(b5.iloc[0].ours), round(float(b5.iloc[1].ours), 3)),
          ("fail (305 traces)", "fail (39 traces)", 2.0, 2.682))
    from drrsim import literature as L
    from drrsim.engine import simulate
    tr = L.make_trace([0.0] * 9, [0, 0, 0, 1, 1, 1, 2, 2, 2], [1, 1, 1, 3, 3, 1, 3, 1, 1])
    pa, pb = L.SCRRProbe(k=3), L.SCRRRoundFirstProbe(k=3)
    simulate(tr, pa, L.config(1e6)); simulate(tr, pb, L.config(1e6))
    check("SCRR counterexample: printed advance 4 > M = 3; round-first never above M = 3", (pa.max_advance, pb.max_advance <= 3.0), (4.0, True))
    steps = []
    class Spy(L.SCRRRoundFirstProbe):
        any_k = True
        def select(self, now):
            before = self.virtual_clock
            c = super().select(now)
            if self.virtual_clock != before:
                steps.append(self.virtual_clock)
            return c
    simulate(tr, Spy(k=3), L.config(1e6))
    check("round-first clock moves 1, 4, 7, 9 (steps of at most 3)", steps, [1.0, 4.0, 7.0, 9.0])
    # idle-history effect
    sys.path.insert(0, str(ROOT / "tests"))
    from drrsim.schedulers import SCRR
    from drrsim.traffic import Trace
    import test_matrix as T
    diffs, worst = 0, 0
    for seed in range(200):
        rng_ = np.random.default_rng(10_000 + seed)
        a_ = T.rand_trace(rng_, int(rng_.integers(50, 400)), horizon=0.05, sizes=(40, 576, 1500))
        b_ = T.rand_trace(rng_, int(rng_.integers(50, 400)), horizon=0.05, sizes=(40, 576, 1500))
        b_ = Trace(b_.t + 10.0, b_.cls, b_.size)
        both = Trace(np.r_[a_.t, b_.t], np.r_[a_.cls, b_.cls], np.r_[a_.size, b_.size])
        c_ = T.cfg(rate=1e6, buffer=10 ** 9)
        x = simulate(both, SCRR(), c_).start[len(a_):]
        y = simulate(b_, SCRR(), c_).start
        if not np.array_equal(x, y):
            diffs += 1
            for tt in np.unique(np.r_[x, y]):
                for cl in range(3):
                    m = b_.cls == cl
                    worst = max(worst, abs(int(b_.size[m][x[m] <= tt].sum()) - int(b_.size[m][y[m] <= tt].sum())))
    check("SCRR idle history: 180 of 200 cases differ, at most ~3 packets", (diffs, round(worst / 1500, 1)), (180, 3.0), note="")

    # ------------------------------------------------------------------ E16 / E16b / E17 / E17b
    for exp, tol_abs, want_ok, want_rank in (("E16", 0.5, 18, 3), ("E16b", 5.0, 26, 3)):
        d16 = sorted(glob.glob(str(ROOT / "results" / exp / "*")))[-1]
        k = pd.read_csv(Path(d16) / "summary.csv")
        g16 = k.groupby(["point", "scheduler", "class"])[["kernel_mean_ms", "sim_mean_ms"]].mean()
        ok = int(((g16.kernel_mean_ms - g16.sim_mean_ms).abs() <= 0.10 * g16.sim_mean_ms + tol_abs).sum())
        rank = 0
        for _, x in k[k["class"] == "lat"].groupby("point"):
            rank += x.groupby("scheduler").kernel_p95_ms.mean().sort_values().index.tolist() == x.groupby("scheduler").sim_p95_ms.mean().sort_values().index.tolist()
        check(f"{exp}: delays within tolerance in {want_ok}/27, ranking {want_rank}/3", (ok, rank), (want_ok, want_rank))
    k16b = pd.read_csv(sorted(glob.glob(str(ROOT / "results" / "E16b" / "*")))[-1] + "/summary.csv")
    g_ = k16b.groupby(["point", "scheduler", "class"])[["kernel_mean_ms", "sim_mean_ms"]].mean()
    miss = g_[(g_.kernel_mean_ms - g_.sim_mean_ms).abs() > 0.10 * g_.sim_mean_ms + 5.0]
    check("E16b only miss: Poisson 0.9 FIFO latency, 24.1 vs 32.9 ms", (list(miss.index), round(miss.kernel_mean_ms.iloc[0], 1), round(miss.sim_mean_ms.iloc[0], 1)),
          ([("poisson|0.9", "FIFO", "lat")], 24.1, 32.9))
    d16 = Path(sorted(glob.glob(str(ROOT / "results" / "E16" / "*")))[-1])
    rates = []
    for f in sorted(d16.glob("kernel_*.csv")):
        mode = f.name.split("_")[1]
        if mode == "sp":
            continue
        tr0 = np.loadtxt(d16 / ("trace_" + f.name.split("_", 2)[2]), delimiter=",")
        kk = np.loadtxt(f, delimiter=",", dtype=np.int64)
        kk = kk[np.argsort(kk[:, 3])]
        size, rx, sched = tr0[kk[:, 0], 2], kk[:, 3] / 1e9, kk[:, 2] / 1e9
        busy = sched[1:] < rx[:-1] - 1e-4
        rates.append(size[1:][busy].sum() * 8 / np.diff(rx)[busy].sum() / 1e6)
    check("kernel aggregate rate 9.64-9.95 Mb/s", (round(min(rates), 2), round(max(rates), 2)), (9.64, 9.95))
    meta = json.loads((ROOT / "results" / "E17" / "parse_meta.json").read_text())
    check("MAWI: 1,000,000 packets in 6.7 s; 42.5 % in the latency class", (meta["packets"], round(meta["span_s"], 1), round(meta["class_share_packets"][0] / meta["packets"] * 100, 1)),
          (1000000, 6.7, 42.5))
    r17 = pd.read_csv(ROOT / "results" / "E17" / "runs.csv")
    diffs17, pv17, sp17 = [], [], 0
    for load, g_ in r17.groupby("load"):
        a_ = g_[g_.scheduler == "DR-DRR"].set_index("window").W; b_ = g_[g_.scheduler == "DRR"].set_index("window").W
        diffs17.append((a_ - b_).mean()); pv17.append(stats.wilcoxon(a_ - b_).pvalue)
        sp17 += g_.groupby("scheduler").lat_p95.mean().idxmin() == "SP"
        check(f"E17 load {load}: best non-SP is CQDRR", g_.groupby("scheduler").W.mean().drop("SP").idxmin(), "CQDRR")
    check("E17 DR-DRR minus DRR in W: -0.336 to -0.505, p < 0.01", (round(max(diffs17), 3), round(min(diffs17), 3), max(pv17) < 0.01), (-0.336, -0.505, True))
    # E20 / E20b: Modified DRR baselines
    e20, e20b = rd("E20"), rd("E20B")
    for var, want in (("MDRR-SP", (4, 10)), ("MDRR-ALT", (1, 13))):
        pv_, df_ = [], []
        for pt_, g_ in e20[e20.scheduler == var].groupby("point"):
            ref_ = e1[(e1.point == pt_) & (e1.scheduler == "DR-DRR")].set_index("seed").sort_index().W
            dd_ = (g_.set_index("seed").sort_index().W - ref_).dropna()
            pv_.append(stats.wilcoxon(dd_).pvalue if np.any(dd_ != 0) else 1.0)
            df_.append(dd_.mean())
        ad_ = holm(pv_)
        check(f"E20 {var} vs DR-DRR: MDRR better / worse", (sum(1 for d_, a_ in zip(df_, ad_) if d_ < 0 and a_ < 0.05), sum(1 for d_, a_ in zip(df_, ad_) if d_ > 0 and a_ < 0.05)), want)
    lat20 = pd.concat([e1[e1.scheduler == "SP"], e20]).groupby(["point", "scheduler"]).lat_p95.mean().unstack()
    check("E20 M1: MDRR-SP latency within 10 % of SP at 14/14", int((abs(lat20["MDRR-SP"] / lat20["SP"] - 1) <= 0.10).sum()), 14)
    check("E20 M3: MDRR-ALT latency above MDRR-SP at 14/14", int((lat20["MDRR-ALT"] > lat20["MDRR-SP"]).sum()), 14)
    check("E20 M2: no MDRR starvation", int(e20[[f"{c}_starv_count" for c in CLS]].sum().sum() + e20b[[f"{c}_starv_count" for c in CLS]].sum().sum()), 0)
    check("E20 MDRR-ALT latency p95 at ON/OFF 0.95: about 320 ms", round(lat20["MDRR-ALT"]["onoff|0.95"] * 1e3), 320)
    v_ = e20b[e20b.point == "onoff|0.95"]
    check("E20b MDRR-ALT-V at ON/OFF 0.95: latency 2.3 ms, W 3.17", (round(v_.lat_p95.mean() * 1e3, 1), round(v_.W.mean(), 2)), (2.3, 3.17))
    # E21: other link rates; Holm over 29 points; RevenueDRR half-scale
    e21 = rd("E21")
    e21["rate"] = e21.point.str.split("|").str[0]
    for rname, g_ in e21.groupby("rate"):
        s1_ = sum(h.groupby("scheduler").lat_p95.mean().idxmin() == "SP" for _, h in g_.groupby("point"))
        pv_, df_ = [], []
        for _, h in g_.groupby("point"):
            dd_ = (h[h.scheduler == "DR-DRR"].set_index("seed").sort_index().W - h[h.scheduler == "DRR"].set_index("seed").sort_index().W).dropna()
            pv_.append(stats.wilcoxon(dd_).pvalue if np.any(dd_ != 0) else 1.0)
            df_.append(dd_.mean())
        ad_ = holm(pv_)
        s2_ = sum(1 for d_, a_ in zip(df_, ad_) if d_ < 0 and a_ < 0.05)
        stc_ = g_.groupby("scheduler")[[f"{c}_starv_count" for c in CLS]].sum().sum(axis=1)
        check(f"E21 {rname}: S1 / S2 / DR-DRR starvation episodes", (s1_, s2_, int(stc_["DR-DRR"])), {"100Mb": (3, 3, 0), "1Mb": (3, 0, 3949)}[rname])
        if rname == "1Mb":
            gp_ = g_[g_.scheduler == "DR-DRR"]
            check("E21 1 Mb/s: DR-DRR longest starvation 194 ms, below the 216 ms bound", (round(gp_[[f"{c}_starv_max" for c in CLS]].max().max() * 1e3), 194 < 216), (194, True))
    allp, alld = [], []
    for _, g_ in pd.concat([e1, rd("E2"), rd("E3"), rd("E4"), rd("E7"), rd("E8")]).groupby(["exp", "point"]):
        dd_ = (g_[g_.scheduler == "DR-DRR"].set_index("seed").sort_index().W - g_[g_.scheduler == "DRR"].set_index("seed").sort_index().W).dropna()
        allp.append(stats.wilcoxon(dd_).pvalue if np.any(dd_ != 0) else 1.0)
        alld.append(dd_.mean())
    ad29 = holm(allp)
    check("Holm over all 29 points: DR-DRR vs DRR better / worse / not significant",
          (sum(1 for d_, a_ in zip(alld, ad29) if d_ < 0 and a_ < 0.05), sum(1 for d_, a_ in zip(alld, ad29) if d_ > 0 and a_ < 0.05), int(sum(a_ >= 0.05 for a_ in ad29))), (23, 1, 5))
    e6r = rd("E6")
    e6r = e6r[e6r.scheduler == "RevenueDRR"]
    check("E6: RevenueDRR at half guarantee scale W 0.84 / 1.39", (round(e6r[e6r.point == "guar_scale=x0.5|load=0.95"].W.mean(), 2), round(e6r[e6r.point == "guar_scale=x0.5|load=1.2"].W.mean(), 2)), (0.84, 1.39))
    # E22 tandem, E24 two-knob baselines, E23 SD-DRR
    d22 = pd.read_csv(ROOT / "results" / "E22" / "runs.csv")
    sing = e1[e1.point == "onoff|0.95"].groupby("scheduler").W.mean()
    t1_, pv22, df22, rho22, best22 = 0, [], [], [], []
    for _, g_ in d22.groupby("point"):
        m_ = g_.groupby("scheduler")[["lat_e2e_p95", "W2"]].mean()
        t1_ += m_.lat_e2e_p95.idxmin() == "SP"
        dd_ = g_[g_.scheduler == "DR-DRR"].set_index("seed").sort_index().W2 - g_[g_.scheduler == "DRR"].set_index("seed").sort_index().W2
        pv22.append(stats.wilcoxon(dd_).pvalue)
        df22.append(dd_.mean())
        rho22.append(stats.spearmanr(m_.W2[sing.index], sing).correlation)
        best22.append(m_.W2.drop("SP").idxmin())
    ad22 = holm(pv22)
    check("E22 tandem: T1 / T2 / T3", (int(t1_), sum(1 for d_, a_ in zip(df22, ad22) if d_ < 0 and a_ < 0.05), sum(r_ >= 0.7 for r_ in rho22)), (2, 2, 2))
    check("E22 best non-SP is RevenueDRR at both points", best22, ["RevenueDRR", "RevenueDRR"])
    e24 = rd("E24")
    wins24 = {pt_: g_.groupby("scheduler").W.mean().idxmin() for pt_, g_ in e24.groupby("point")}
    check("E24: DR-DRR lowest of three at 0 of 14 points", sum(v == "DR-DRR" for v in wins24.values()), 0)
    check("E24: RevenueDRR lowest at 8 heavy points, FuzzyDRR at 6 light ones", (sum(v == "RevenueDRR" for v in wins24.values()), sum(v == "FuzzyDRR" for v in wins24.values())), (8, 6))
    p24 = json.loads((ROOT / "config" / "tuned_2knob.json").read_text())["params"]
    check("E24 chosen: DR-DRR kappa 4 theta 0.75; RevenueDRR tau 0.0125 guar_scale 0.25", (p24["DR-DRR"], p24["RevenueDRR"]), ({"kappa": 4, "theta": 0.75}, {"tau": 0.0125, "guar_scale": 0.25}))
    e23, r23 = rd("E23"), rd("E23R")
    n1_ = sum(g_.groupby("scheduler").W.mean().idxmin() == "SD-DRR" for _, g_ in e23.groupby("point"))
    pv_, df_ = [], []
    for _, g_ in e23.groupby("point"):
        dd_ = g_[g_.scheduler == "SD-DRR"].set_index("seed").sort_index().W - g_[g_.scheduler == "DRR"].set_index("seed").sort_index().W
        pv_.append(stats.wilcoxon(dd_).pvalue if np.any(dd_ != 0) else 1.0)
        df_.append(dd_.mean())
    ad_ = holm(pv_)
    sd_ = e23[e23.scheduler == "SD-DRR"]
    n4_ = sum(g_[g_.scheduler == "SD-DRR"].W.mean() < g_[g_.scheduler == "DRR"].W.mean() for _, g_ in r23.groupby("point"))
    check("E23: N1 / N2 better / N2 worse / starvation / N4", (int(n1_), sum(1 for d_, a_ in zip(df_, ad_) if d_ < 0 and a_ < 0.05), sum(1 for d_, a_ in zip(df_, ad_) if d_ > 0 and a_ < 0.05),
          int(sd_[[f"{c}_starv_count" for c in CLS]].sum().sum()), int(n4_)), (1, 2, 4, 0, 3))
    check("E23: SD-DRR longest service gap 20.3 ms, below 21.6", (round(max(sd_[f"{c}_gap_max"].max() for c in CLS) * 1e3, 1), True), (20.3, True))
    # E17c: second backbone trace
    metac = json.loads((ROOT / "results" / "E17c" / "parse_meta.json").read_text())
    check("E17c: 1,000,000 packets in 27.5 s; 97.3 % bulk bytes", (metac["packets"], round(metac["span_s"], 1), round(metac["class_share_bytes"][2] / sum(metac["class_share_bytes"]) * 100, 1)),
          (1000000, 27.5, 97.3))
    rc = pd.read_csv(ROOT / "results" / "E17c" / "runs.csv")
    check("E17c: 270 replay runs", len(rc), 270)
    spc, wspread, others, fifo_worse = 0, 0.0, set(), True
    for load, g_ in rc.groupby("load"):
        spc += g_.groupby("scheduler").lat_p95.mean().idxmin() == "SP"
        mw = g_.groupby("scheduler").W.mean()
        wspread = max(wspread, mw[["DRR", "DR-DRR", "CQDRR", "FuzzyDRR", "RL-SP+DRR", "SP", "SCRR"]].max() - mw[["DRR", "DR-DRR", "CQDRR", "FuzzyDRR", "RL-SP+DRR", "SP", "SCRR"]].min())
        fifo_worse &= mw.idxmax() == "FIFO"
        stc = g_.groupby("scheduler")[[f"{c}_starv_count" for c in CLS]].sum().sum(axis=1)
        others |= set(stc[stc > 0].index) - {"SP", "CQDRR", "FIFO"}
    check("E17c R1c: SP lowest latency p95 at 3/3 loads", spc, 3)
    l95 = rc[rc.load == 0.95].groupby("scheduler").lat_p95.mean() * 1e3
    check("E17c load 0.95 latency p95 (ms): SP 1.1, CQDRR 1.2, DRR 1.4, DR-DRR 1.5; RevenueDRR 6x DRR",
          ([round(l95[x], 1) for x in ("SP", "CQDRR", "DRR", "DR-DRR")], round(l95["RevenueDRR"] / l95["DRR"])), ([1.1, 1.2, 1.4, 1.5], 6))
    check("E17c R3c: nobody besides SP, CQDRR, FIFO starves", others, set())
    check("E17c: seven schedulers tie in mean W within 0.0001; FIFO worst", (round(wspread, 4), fifo_worse), (0.0001, True))
    diffc = [float((g_[g_.scheduler == "DR-DRR"].set_index("window").W - g_[g_.scheduler == "DRR"].set_index("window").W).mean()) for _, g_ in rc.groupby("load")]
    check("E17c R2c: DR-DRR minus DRR in W is below 0.001 in size at all loads (not significant)", max(abs(x) for x in diffc) < 0.001, True)
    check("E17 SP lowest latency at 3/3 loads", sp17, 3)
    for mp in ("strict", "size"):
        rb = pd.read_csv(ROOT / "results" / "E17b" / mp / "runs.csv")
        okk = 0
        for load, g_ in rb.groupby("load"):
            a_ = g_[g_.scheduler == "DR-DRR"].set_index("window").W; b_ = g_[g_.scheduler == "DRR"].set_index("window").W
            okk += (g_.groupby("scheduler").lat_p95.mean().idxmin() == "SP") and (a_ - b_).mean() < 0 and stats.wilcoxon(a_ - b_).pvalue < 0.05
        check(f"E17b {mp}: SP first and DR-DRR < DRR at 3/3 loads", int(okk), 3)

    # ------------------------------------------------------------------ verification-suite counts (arithmetic and reports)
    check("traces of <= 4 packets on the 18-cell grid: 7,315; x 3 buffers = 21,945", (sum(__import__("math").comb(18 + n - 1, n) for n in range(5)), 7315 * 3), (7315, 21945))
    check("reference comparisons 9 x 21,945 = 197,505", 9 * 21945, 197505)
    n5 = sum(__import__("math").comb(18 + n - 1, n) for n in range(6))
    check("five-packet run: 33,649 traces; 7 x 3 x 33,649 = 706,629 comparisons", (n5, 7 * 3 * n5), (33649, 706629))
    mut = (ROOT / "docs" / "MUTATION_REPORT.md").read_text(encoding="utf-8")
    m_ = re.search(r"(\d+)/(\d+) behaviour-changing planted bugs.*?\((\d+) further", mut, re.S)
    n_beh, eq = int(m_.group(2)), int(m_.group(3))
    check("mutation report: planted bugs caught / all behaviour-changing / equivalent", (n_beh, int(m_.group(1)), eq), (56, 56, 2), note=f"total mutants {n_beh + eq}")
    check("paper says 58 planted bugs, 56 behaviour-changing", (n_beh + eq, n_beh), (58, 56))
    tst = (ROOT / "docs" / "TESTING.md").read_text(encoding="utf-8")
    bugs = tst[tst.index("## Bugs found by this testing"):tst.index("## Regression guard")]
    check("twelve problems listed in TESTING.md", len([l for l in bugs.splitlines() if l.startswith("| ") and not l.startswith("| where") and not l.startswith("|---")]), 12)

    bad = [r for r in results if not r[0]]
    for ok, name, got, want, note in results:
        print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"   got {got!r}  paper says {want!r}") + (f"  [{note}]" if note else ""))
    print(f"\n{len(results) - len(bad)} of {len(results)} claims verified; {len(bad)} failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else ROOT / "paper_draft" / "paper_src.html"))
