"""All figures, generated only from saved CSVs under results/. Output: figures/*.png and *.pdf."""
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, NullFormatter  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from drrsim.analysis import ORDER, load, summary  # noqa: E402
from drrsim.experiments import BURSTS  # noqa: E402
from drrsim.runner import ROOT  # noqa: E402

FIG = ROOT / "figures"
FIG.mkdir(exist_ok=True)
# validated categorical palette (fixed order, one slot per scheduler) + marker as secondary encoding
COLOR = dict(zip(ORDER, ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]))
MARK = dict(zip(ORDER, ["o", "s", "D", "^", "v", "P", "X", "*"]))
INK, MUTED, GRID = "#1f1f1e", "#6b6a63", "#e6e5e0"
plt.rcParams.update({
    "font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.spines.top": False,
    "axes.spines.right": False, "legend.frameon": False, "lines.linewidth": 1.6, "lines.markersize": 5,
    "savefig.dpi": 200, "figure.facecolor": "white",
})
CLS_LABEL = {"lat": "latency", "vid": "video", "blk": "bulk"}


def plain_log(ax, axis="y"):
    """Log scale with plain-number tick labels at 1-2-5 steps (no 10^x clutter)."""
    a = ax.yaxis if axis == "y" else ax.xaxis
    (ax.set_yscale if axis == "y" else ax.set_xscale)("log")
    a.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))
    a.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))
    a.set_minor_formatter(NullFormatter())


def save(fig, name):
    fig.savefig(FIG / f"{name}.png", bbox_inches="tight")
    fig.savefig(FIG / f"{name}.pdf", bbox_inches="tight")
    plt.close(fig)
    print("wrote", name)


def legend_below(fig, ncol=4):
    h = [plt.Line2D([], [], color=COLOR[s], marker=MARK[s], label=s) for s in ORDER]
    fig.legend(handles=h, loc="lower center", ncol=ncol, bbox_to_anchor=(0.5, -0.02))


def fig1_model():
    fig, ax = plt.subplots(figsize=(7.0, 2.6))
    ax.set_axis_off()
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 4.3)
    names = [("latency", "200 B, D = 10 ms"), ("video", "1000–1500 B, D = 50 ms"), ("bulk", "1500 B, D = 500 ms")]
    for i, (n, sub) in enumerate(names):
        y = 3.0 - i * 1.1
        ax.text(0.0, y + 0.42, n, fontsize=8, color=INK, weight="bold")
        ax.text(0.0, y + 0.1, sub, fontsize=6.5, color=MUTED)
        ax.add_patch(FancyArrowPatch((2.15, y + 0.3), (2.95, y + 0.3), arrowstyle="-|>", mutation_scale=10, color=MUTED))
        ax.add_patch(FancyBboxPatch((3.05, y), 2.6, 0.6, boxstyle="round,pad=0.02", fc="white", ec=MUTED))
        for j in range(5):
            ax.add_patch(plt.Rectangle((5.2 - j * 0.45, y + 0.1), 0.35, 0.4, fc="#cde2fb", ec="none"))
        ax.add_patch(FancyArrowPatch((5.7, y + 0.3), (6.75, 1.95), arrowstyle="-|>", mutation_scale=10, color=MUTED))
    ax.add_patch(FancyBboxPatch((2.95, 0.55), 2.8, 3.25, boxstyle="round,pad=0.05", fc="none", ec=INK, ls="--", lw=0.8))
    ax.text(4.35, 0.2, "per-class FIFO queues, byte buffer B, tail drop", ha="center", fontsize=6.5, color=INK)
    ax.add_patch(FancyBboxPatch((6.8, 1.35), 2.6, 1.2, boxstyle="round,pad=0.05", fc="#2a78d6", ec="none"))
    ax.text(8.1, 2.1, "scheduler", ha="center", color="white", fontsize=8.5, weight="bold")
    ax.text(8.1, 1.72, "quanta Q(t), update 10 ms", ha="center", color="white", fontsize=6)
    ax.add_patch(FancyArrowPatch((9.5, 1.95), (11.95, 1.95), arrowstyle="-|>", mutation_scale=12, color=INK, lw=1.5))
    ax.text(10.7, 2.15, "link C = 10 Mb/s", ha="center", fontsize=7, color=INK)
    ax.add_patch(FancyArrowPatch((8.1, 3.55), (8.1, 2.65), arrowstyle="-|>", mutation_scale=8, color=MUTED, ls=":"))
    ax.text(8.6, 3.7, "observes backlog, head-of-line wait, arrivals", ha="center", fontsize=6.5, color=MUTED)
    save(fig, "fig1_system_model")


def fig2_delay_vs_load():
    df = load("E1")
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 4.8), sharex=True)
    for r, arr in enumerate(["onoff", "poisson"]):
        d = df[df.arrival == arr]
        for c, cls in enumerate(["lat", "vid", "blk"]):
            ax = axes[r, c]
            s = summary(d, f"{cls}_p95", by=("load", "scheduler"))
            for sch in ORDER:
                g = s[s.scheduler == sch].sort_values("load")
                ax.errorbar(g.load, g["mean"] * 1e3, yerr=g["ci"] * 1e3, color=COLOR[sch], marker=MARK[sch],
                            capsize=2, elinewidth=0.8, label=sch)
            plain_log(ax)
            ax.axvline(1.0, color=MUTED, lw=0.6, ls=":")
            if r == 0:
                ax.set_title(f"{CLS_LABEL[cls]} class p95", fontsize=9, color=INK)
            if c == 0:
                ax.set_ylabel(f"{'ON/OFF-medium' if arr == 'onoff' else 'Poisson'}\np95 queueing delay (ms)")
            if r == 1:
                ax.set_xlabel("offered load")
    legend_below(fig)
    fig.subplots_adjust(bottom=0.17, hspace=0.15, wspace=0.3)
    save(fig, "fig2_p95_vs_load")


def fig3_starvation():
    e5, e8 = load("E5"), load("E8")
    st = e8[e8.point == "partitioned|stress"]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.6))
    x = np.arange(len(ORDER))
    for ax, (metric, lab, scale) in zip(axes, [("blk_starv_total", "bulk starvation total (s / 60 s)", 1),
                                               ("vid_starv_total", "video starvation total (s / 60 s)", 1),
                                               ("blk_tput", "bulk throughput (Mb/s)", 1e-6)]):
        for off, d, name, hatch in [(-0.2, e5, "shared buffer", None), (0.2, st, "partitioned buffer", "////")]:
            s = summary(d, metric, by=("scheduler",)).set_index("scheduler").loc[ORDER]
            ax.bar(x + off, s["mean"] * scale, 0.38, yerr=s["ci"] * scale, color=[COLOR[k] for k in ORDER],
                   hatch=hatch, edgecolor="white", linewidth=0.5, capsize=1.5, error_kw={"elinewidth": 0.7},
                   label=name)
        ax.set_xticks(x, ORDER, rotation=60, ha="right", fontsize=7)
        ax.set_title(lab, fontsize=8, color=INK)
    h = [plt.Rectangle((0, 0), 1, 1, fc="#9a9990"), plt.Rectangle((0, 0), 1, 1, fc="#9a9990", hatch="////", ec="white")]
    fig.legend(h, ["shared buffer (E5)", "partitioned buffer (E8)"], loc="upper center", ncol=2, bbox_to_anchor=(0.5, 1.06))
    fig.suptitle("Stress test: latency class alone offers 0.8·C (total 1.3·C), ON/OFF-medium", y=1.12, fontsize=9)
    save(fig, "fig3_starvation_stress")


def fig4_tradeoff():
    e1, e8 = load("E1"), load("E8")
    panels = [(e1[e1.point == "onoff|1.2"], "shared buffer, load 1.2"),
              (e8[e8.point == "partitioned|1.2"], "partitioned buffer, load 1.2"),
              (e8[e8.point == "partitioned|stress"], "partitioned buffer, stress")]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.7))
    for ax, (d, title) in zip(axes, panels):
        for sch in ORDER:
            g = d[d.scheduler == sch]
            ax.errorbar(g.jain.mean(), g.lat_p95.mean() * 1e3,
                        xerr=summary(g, "jain", by=("scheduler",))["ci"].iloc[0],
                        yerr=summary(g, "lat_p95", by=("scheduler",))["ci"].iloc[0] * 1e3,
                        color=COLOR[sch], marker=MARK[sch], ms=7, capsize=2, ls="none", mec="white", mew=0.8)
        plain_log(ax)
        ax.set_title(title, fontsize=8, color=INK)
        ax.set_xlim(0.8, 1.01)
    axes[0].set_ylabel("latency-class p95 (ms)")
    fig.supxlabel("Jain's index of max-min-normalised throughput (same scale in all panels)", fontsize=8, y=0.17)
    legend_below(fig)
    fig.subplots_adjust(bottom=0.36, wspace=0.35)
    save(fig, "fig4_delay_fairness_tradeoff")


def fig5_oscillation():
    ts = pd.read_csv(ROOT / "results" / "TIMESERIES" / "quanta.csv")
    names = list(dict.fromkeys(ts.scheduler))
    fig, axes = plt.subplots(len(names), 1, figsize=(7.2, 1.45 * len(names) + 0.6), sharex=True)
    ccol = {"lat": "#2a78d6", "vid": "#eb6834", "blk": "#1baf7a"}
    for ax, n in zip(axes, names):
        for cls in ["lat", "vid", "blk"]:
            g = ts[(ts.scheduler == n) & (ts.cls == cls)]
            ax.plot(g.t, g.quantum / 1500, color=ccol[cls], lw=1.0, label=f"{CLS_LABEL[cls]} quantum")
        ax.set_ylabel("Q / Q⁰")
        ax.text(0.005, 0.85, n, transform=ax.transAxes, fontsize=8, weight="bold", color=COLOR[n])
    axes[-1].set_xlabel("simulated time (s), seed 101, ON/OFF-medium, load 0.95")
    axes[0].legend(loc="upper right", ncol=3, fontsize=7, bbox_to_anchor=(1.0, 1.45))
    save(fig, "fig5_weight_oscillation")


def fig6_sensitivity():
    df = load("E6")
    df["L"] = df.point.str.split("load=").str[1].astype(float)
    ref = df[df.scheduler == "DRR"]
    rows = [(s, k) for s in ORDER for k in sorted(df[df.scheduler == s].knob.dropna().unique()) if s != "DRR"]
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 0.28 * len(rows) + 1.2), sharey=True)
    for ax, load_pt in zip(axes, [0.95, 1.2]):
        d = df[df.L == load_pt]
        for i, (s, k) in enumerate(rows):
            g = d[(d.scheduler == s) & (d.knob == k)].groupby("level").W.mean()
            lo, hi = g.min(), g.max()
            ax.plot([lo, hi], [i, i], color=COLOR[s], lw=4, alpha=0.35, solid_capstyle="round")
            for lev, mk in [("x0.5", "<"), ("x1.5", ">")]:
                if lev in g:
                    ax.plot(g[lev], i, marker=mk, color=COLOR[s], ms=5)
            ax.plot(g["x1"], i, marker="o", color=COLOR[s], mec="white", ms=6)
        ax.axvline(ref[ref.L == load_pt].W.mean(), color=MUTED, ls="--", lw=0.8)
        ax.text(ref[ref.L == load_pt].W.mean(), len(rows) - 0.4, " DRR", fontsize=7, color=MUTED)
        plain_log(ax, "x")
        ax.set_title(f"load {load_pt}, ON/OFF-medium", fontsize=8, color=INK)
        ax.set_xlabel("W = max_i p95_i / D_i  (lower is better)")
    axes[0].set_yticks(range(len(rows)), [f"{s}: {k}" for s, k in rows], fontsize=7)
    axes[0].invert_yaxis()
    fig.text(0.5, -0.04, "●  tuned value      ◀  ×0.5      ▶  ×1.5      band = range over the three", ha="center", fontsize=7, color=MUTED)
    save(fig, "fig6_parameter_sensitivity")


def fig7_burstiness():
    df = load("E3")
    order = ["poisson"] + [f"onoff-{b}" for b in BURSTS]
    labels = ["Poisson", "small\n10 ms", "medium\n50 ms", "large\n200 ms"]
    fig, axes = plt.subplots(1, 3, figsize=(7.2, 2.6), sharex=True)
    for ax, cls in zip(axes, ["lat", "vid", "blk"]):
        s = summary(df, f"{cls}_p95")
        for sch in ORDER:
            g = s[s.scheduler == sch].set_index("point").loc[order]
            ax.errorbar(range(4), g["mean"] * 1e3, yerr=g["ci"] * 1e3, color=COLOR[sch], marker=MARK[sch], capsize=2)
        plain_log(ax)
        ax.set_xticks(range(4), labels, fontsize=6.5)
        ax.set_title(f"{CLS_LABEL[cls]} class p95 (ms), load 0.9", fontsize=8, color=INK)
    fig.supxlabel("arrival process (ON/OFF: mean burst length)", fontsize=8, y=0.2)
    legend_below(fig)
    fig.subplots_adjust(bottom=0.4, wspace=0.3)
    save(fig, "fig7_burstiness")


def fig8_buffer_and_mix():
    e4, e2 = load("E4"), load("E2")
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 2.7))
    for ax, (d, order, labels, title) in zip(axes, [
        (e4, ["buffer=small", "buffer=medium", "buffer=large"], ["30 kB", "125 kB", "500 kB"], "E4 buffer size (load 0.95)"),
        (e2, ["mix=A", "mix=B", "mix=C"], ["A 0.2/0.4/0.4", "B 0.4/0.3/0.3", "C 0.1/0.2/0.7"], "E2 traffic mix lat/vid/blk (load 0.95)"),
    ]):
        s = summary(d, "W")
        for sch in ORDER:
            g = s[s.scheduler == sch].set_index("point").loc[order]
            ax.errorbar(range(3), g["mean"], yerr=g["ci"], color=COLOR[sch], marker=MARK[sch], capsize=2)
        ax.axhline(1.0, color=MUTED, ls=":", lw=0.8)
        plain_log(ax)
        ax.set_xticks(range(3), labels, fontsize=7)
        ax.set_title(title, fontsize=8, color=INK)
    axes[0].set_ylabel("W = max_i p95_i / D_i\n(dotted: W = 1, targets met)")
    legend_below(fig)
    fig.subplots_adjust(bottom=0.33, wspace=0.25)
    save(fig, "fig8_buffer_and_mix")


def fig9_damping():
    e9, c = load("E9"), load("E9C")
    pts = [("onoff|0.95", "ON/OFF-medium, load 0.95"), ("onoff|1.2", "ON/OFF-medium, load 1.2"),
           ("poisson|1.2", "Poisson, load 1.2")]
    fig, axes = plt.subplots(2, 3, figsize=(7.2, 4.2), sharex=True)
    lams = [1.0, 0.5, 0.25, 0.1]
    for j, (bp, title) in enumerate(pts):
        ax = axes[0, j]
        for d, lab, col, mk in [(e9, "DR-DRR with damping λ", COLOR["DR-DRR"], MARK["DR-DRR"]),
                                (c, "static DRR at DR-DRR's mean quanta", COLOR["DRR"], MARK["DRR"])]:
            s = summary(d[d.base_point == bp], "W", by=("smooth",)).set_index("smooth").loc[lams]
            ax.errorbar(range(4), s["mean"], yerr=s["ci"], color=col, marker=mk, capsize=2, label=lab)
        ax.set_title(title, fontsize=8, color=INK)
        ax2 = axes[1, j]
        s = summary(e9[e9.base_point == bp], "osc_mag_mean", by=("smooth",)).set_index("smooth").loc[lams]
        ax2.errorbar(range(4), s["mean"], yerr=s["ci"], color=COLOR["DR-DRR"], marker=MARK["DR-DRR"], capsize=2)
        plain_log(ax2)
        ax2.set_xticks(range(4), [f"{l:g}" for l in lams])
    axes[0, 0].set_ylabel("W = max_i p95_i / D_i")
    axes[1, 0].set_ylabel("oscillation |ΔQ|/Q⁰")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.supxlabel("DR-DRR smoothing λ (1 = no damping)", fontsize=8, y=0.1)
    fig.legend(h, l, loc="lower center", ncol=2, bbox_to_anchor=(0.5, -0.03))
    fig.subplots_adjust(bottom=0.2, hspace=0.25, wspace=0.3)
    save(fig, "fig9_drdrr_damping")


def fig10_damped_variant():
    e1, dd = load("E1"), load("E1D")
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.4), sharex=True)
    series = [("DRR", e1, dict(color=COLOR["DRR"], marker=MARK["DRR"])),
              ("CQDRR", e1, dict(color=COLOR["CQDRR"], marker=MARK["CQDRR"])),
              ("DR-DRR", e1, dict(color=COLOR["DR-DRR"], marker=MARK["DR-DRR"])),
              ("DR-DRR+damping", dd, dict(color=COLOR["DR-DRR"], marker=MARK["DR-DRR"], ls="--", mfc="white"))]
    for j, arr in enumerate(["onoff", "poisson"]):
        ax = axes[0, j]
        for name, d, st in series:
            g = summary(d[(d.arrival == arr) & (d.scheduler == name)], "W", by=("load",)).sort_values("load")
            ax.errorbar(g.load, g["mean"], yerr=g["ci"], capsize=2, label=name, **st)
        plain_log(ax)
        ax.axhline(1.0, color=MUTED, ls=":", lw=0.8)
        ax.set_title("ON/OFF-medium" if arr == "onoff" else "Poisson", fontsize=8, color=INK)
        ax = axes[1, j]
        a = dd[dd.arrival == arr].set_index(["load", "seed"]).W
        b = e1[(e1.arrival == arr) & (e1.scheduler == "DR-DRR")].set_index(["load", "seed"]).W.loc[a.index]
        rel = (a / b - 1) * 100
        g = summary(rel.reset_index(name="r"), "r", by=("load",)).sort_values("load")
        ax.errorbar(g.load, g["mean"], yerr=g["ci"], capsize=2, color=COLOR["DR-DRR"], marker=MARK["DR-DRR"],
                    ls="--", mfc="white")
        ax.axhline(0, color=MUTED, lw=0.8)
        ax.set_xlabel("offered load")
    axes[0, 0].set_ylabel("W = max_i p95_i / D_i")
    axes[1, 0].set_ylabel("W change vs DR-DRR (%)")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.03))
    fig.subplots_adjust(bottom=0.17, hspace=0.2, wspace=0.25)
    save(fig, "fig10_drdrr_damping_variant")


def fig11_scrr():
    e1, es = load("E1"), load("ES")
    es1 = es[es.src_exp == "E1"]
    series = [
        ("DRR, quantum 1500 B", e1[e1.scheduler == "DRR"], "point", dict(color=COLOR["DRR"], marker=MARK["DRR"])),
        ("DRR, quantum 9000 B (paper's comparator)", es1[es1.scheduler == "DRR"], "base_point",
         dict(color=COLOR["DRR"], marker=MARK["DRR"], ls="--", mfc="white")),
        ("SCRR (NSDI 2025)", es1[es1.scheduler == "SCRR"], "base_point", dict(color=INK, marker="h")),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(7.2, 4.6), sharex=True)
    for i, arr in enumerate(["onoff", "poisson"]):
        for j, (metric, scale, lab) in enumerate([("lat_delay_mean", 1e3, "latency-class mean delay (ms)"),
                                                  ("W", 1.0, "W = max_i p95_i / D_i")]):
            ax = axes[i, j]
            for name, d, col, st in series:
                d = d[d[col].str.startswith(arr)].copy()
                d["L"] = d[col].str.split("|").str[1].astype(float)
                g = summary(d, metric, by=("L",)).sort_values("L")
                ax.errorbar(g.L, g["mean"] * scale, yerr=g["ci"] * scale, capsize=2, label=name, **st)
            plain_log(ax)
            if i == 0:
                ax.set_title(lab, fontsize=8, color=INK)
            if j == 0:
                ax.set_ylabel("ON/OFF-medium" if arr == "onoff" else "Poisson")
            if i == 1:
                ax.set_xlabel("offered load")
    h, l = axes[0, 0].get_legend_handles_labels()
    fig.legend(h, l, loc="lower center", ncol=3, bbox_to_anchor=(0.5, -0.03), fontsize=7)
    fig.subplots_adjust(bottom=0.17, hspace=0.2, wspace=0.25)
    save(fig, "fig11_scrr")


if __name__ == "__main__":
    fig1_model()
    fig2_delay_vs_load()
    fig3_starvation()
    fig4_tradeoff()
    fig5_oscillation()
    fig6_sensitivity()
    fig7_burstiness()
    fig8_buffer_and_mix()
    fig9_damping()
    fig10_damped_variant()
    fig11_scrr()
