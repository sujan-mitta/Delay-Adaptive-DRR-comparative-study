"""Statistics over saved run CSVs: means with 95 % t-intervals, paired tests, pairing checks."""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from .config import CLASSES
from .runner import ROOT
from .schedulers import SCHEDULERS

ORDER = SCHEDULERS


def load(exp: str) -> pd.DataFrame:
    df = pd.read_csv(ROOT / "results" / exp / "runs.csv")
    if len(df) != df["key"].nunique():
        raise ValueError(f"{exp}: duplicate run keys")
    df["W"] = np.max([df[f"{c.name}_p95"] / c.delay_target for c in CLASSES], axis=0)
    return df


def check_pairing(df: pd.DataFrame) -> int:
    """Every (point, seed) must have one trace digest across schedulers. Returns #groups checked."""
    g = df.groupby(["point", "seed"])["trace"].nunique()
    bad = g[g != 1]
    if len(bad):
        raise AssertionError(f"unpaired traces: {bad.index.tolist()[:5]}")
    return len(g)


def ci95(x) -> tuple[float, float, int]:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n == 0:
        return np.nan, np.nan, 0
    if n == 1:
        return float(x[0]), np.nan, 1
    h = stats.t.ppf(0.975, n - 1) * x.std(ddof=1) / np.sqrt(n)
    return float(x.mean()), float(h), n


def summary(df, metric, by=("point", "scheduler")) -> pd.DataFrame:
    rows = []
    for k, g in df.groupby(list(by), sort=False):
        m, h, n = ci95(g[metric])
        rows.append(dict(zip(by, k if isinstance(k, tuple) else (k,)), mean=m, ci=h, n=n))
    return pd.DataFrame(rows)


def paired_vs(df, metric, ref="DRR", point_col="point") -> pd.DataFrame:
    """Per point and scheduler: mean paired difference (sched - ref) with CI and Wilcoxon p."""
    rows = []
    for p, g in df.groupby(point_col, sort=False):
        r = g[g.scheduler == ref].set_index("seed")[metric]
        for s in ORDER:
            if s == ref:
                continue
            x = g[g.scheduler == s].set_index("seed")[metric]
            d = (x - r).dropna()
            if not len(d):
                continue
            m, h, n = ci95(d)
            try:
                pval = stats.wilcoxon(d).pvalue if np.any(d != 0) else 1.0
            except ValueError:
                pval = np.nan
            rows.append({point_col: p, "scheduler": s, "diff": m, "ci": h, "n": n, "p": pval,
                         "wins": int((d < 0).sum())})
    return pd.DataFrame(rows)


def rank_stability(df, metric, order=None) -> pd.DataFrame:
    """Per point: mean rank of each scheduler across seeds (1 = lowest metric) and share of seeds it ranks 1st."""
    order = order or ORDER
    rows = []
    for p, g in df.groupby("point", sort=False):
        piv = g.pivot(index="seed", columns="scheduler", values=metric)[order]
        ranks = piv.rank(axis=1, method="min")
        for s in order:
            rows.append({"point": p, "scheduler": s, "mean_rank": ranks[s].mean(),
                         "first_share": float((ranks[s] == 1).mean())})
    return pd.DataFrame(rows)
