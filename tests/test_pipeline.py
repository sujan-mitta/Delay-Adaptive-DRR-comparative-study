"""Runner, experiment definitions, decision rules, analysis statistics, and end-to-end outputs."""
import importlib.util
import json
import sys

import numpy as np
import pandas as pd
import pytest

from drrsim import SimConfig, TrafficConfig
from drrsim import analysis, runner
from drrsim.experiments import (DEV_SEEDS, EXPERIMENTS, LOADS, SEEDS, TUNE_GRID, experiment_tasks, load_tuned,
                                tuning_tasks)
from drrsim.runner import ROOT, code_hash, key, run_tasks, task

HAVE_RESULTS = (ROOT / "results" / "E1" / "runs.csv").exists()


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def tiny(load=0.5):
    return SimConfig(TrafficConfig(load=load, duration=0.5, warmup=0.1))


# ---------------- runner ----------------
def test_run_tasks_writes_resumes_and_never_overwrites(tmp_path):
    tasks = [task("T", "p", s, seed, tiny()) for s in ("FIFO", "DRR") for seed in (1, 2)]
    run_tasks(tmp_path, tasks, workers=2)
    df = pd.read_csv(tmp_path / "runs.csv")
    assert len(df) == 4 and set(df.key) == {key(t) for t in tasks}
    before = (tmp_path / "runs.csv").read_bytes()
    run_tasks(tmp_path, tasks, workers=2)                       # resume: nothing re-run, file untouched
    assert (tmp_path / "runs.csv").read_bytes() == before
    more = tasks + [task("T", "p", "SP", 1, tiny())]
    run_tasks(tmp_path, more, workers=1)                        # only the new task is appended
    df2 = pd.read_csv(tmp_path / "runs.csv")
    assert len(df2) == 5 and df2.key.is_unique
    assert len(list(tmp_path.glob("manifest_*.json"))) == 3     # one manifest per call, none overwritten


def test_failures_are_logged_not_dropped(tmp_path):
    good = task("T", "p", "FIFO", 1, tiny())
    bad = task("T", "p", "DRR", 1, tiny(), params={"no_such_param": 1})
    run_tasks(tmp_path, [good, bad], workers=1)
    assert len(pd.read_csv(tmp_path / "runs.csv")) == 1
    f = pd.read_csv(tmp_path / "failures.csv")
    assert f.key.tolist() == [key(bad)] and "no_such_param" in f.error.iloc[0]


def test_duplicate_task_keys_rejected(tmp_path):
    t = task("T", "p", "FIFO", 1, tiny())
    with pytest.raises(ValueError):
        run_tasks(tmp_path, [t, t], workers=1)


def test_run_rows_are_deterministic_and_record_pairing(tmp_path):
    t = task("T", "p", "DRR", 3, tiny())
    ok1, r1 = runner._execute(t)
    ok2, r2 = runner._execute(t)
    assert ok1 and ok2
    r1.pop("wall_time"), r2.pop("wall_time"), r1.pop("decisions_per_s"), r2.pop("decisions_per_s")
    assert r1.keys() == r2.keys() and len(r1["trace"]) == 16
    for k in r1:                                   # NaN-aware equality (NaN != NaN in Python)
        a, b = r1[k], r2[k]
        assert a == b or (isinstance(a, float) and np.isnan(a) and np.isnan(b)), k


def test_code_hash_format_and_stability():
    h = code_hash()
    assert len(h) == 16 and int(h, 16) >= 0 and h == code_hash()


# ---------------- experiment definitions ----------------
EXPECTED = {"E1": 2240, "E2": 480, "E3": 640, "E4": 480, "E5": 160, "E6": 1720, "E7": 160, "E8": 640,
            "E9": 240, "E10": 960, "DEVD": 140, "E1D": 280, "E1V": 280, "ES": 720, "E11": 1440}


@pytest.mark.parametrize("exp", sorted(EXPECTED))
def test_experiment_task_counts_and_unique_keys(exp):
    t = experiment_tasks(exp, load_tuned())
    assert len(t) == EXPECTED[exp]
    assert len({key(x) for x in t}) == len(t)
    seeds = {x["seed"] for x in t}
    assert seeds == (set(DEV_SEEDS) if exp == "DEVD" else set(SEEDS))


def test_unknown_experiment_rejected():
    with pytest.raises(ValueError):
        experiment_tasks("E99", load_tuned())


def test_tuning_grid_and_extension_tasks():
    base = tuning_tasks()
    assert len(base) == sum(len(v[1]) for v in TUNE_GRID.values()) * 2 * len(DEV_SEEDS) + 2 * len(DEV_SEEDS)
    assert {x["seed"] for x in base} == set(DEV_SEEDS)
    ext = tuning_tasks({"CQDRR": [1.0]})
    assert len(ext) == len(base) + 2 * len(DEV_SEEDS)


def test_reported_and_dev_seeds_disjoint():
    assert not set(SEEDS) & set(DEV_SEEDS) and len(SEEDS) == 20 and LOADS == sorted(LOADS)


def test_main_experiments_use_tuned_parameters():
    tuned = load_tuned()
    for t in experiment_tasks("E1", tuned):
        assert t["params"] == tuned.get(t["scheduler"], {})
    assert set(EXPERIMENTS) >= {"E1", "E5", "E8"}


# ---------------- decision rules ----------------
def test_tune_pick_feasibility_ties_and_fallback():
    tune = load_script("tune")
    t = pd.DataFrame({"value": [1.0, 2.0, 4.0, 8.0], "W@0.95": [2.0, 1.005, 1.0, 1.5],
                      "jain@1.2": [0.99] * 4, "feasible": [True] * 4})
    assert tune.pick(t, default=2.0) == 2.0           # 1.005 is within 1 % of the best -> closest to default
    assert tune.pick(t, default=8.0) == 4.0
    t.loc[2, "feasible"] = False
    assert tune.pick(t, default=8.0) == 2.0           # infeasible best is skipped
    t["feasible"] = False
    t["jain@1.2"] = [0.5, 0.9, 0.7, 0.6]
    assert tune.pick(t, default=1.0) == 2.0           # nothing feasible -> max Jain


def test_confirm_damping_rule():
    cd = load_script("confirm_damping")

    def frame(ratios):
        rows = []
        for (bp, r) in ratios.items():
            rows += [{"base_point": bp, "smooth": 1.0, "W": 1.0}, {"base_point": bp, "smooth": 0.5, "W": r}]
        return pd.DataFrame(rows)
    ok, _ = cd.decide(frame({"onoff|0.9": 0.9, "onoff|1.2": 0.95, "onoff|0.6": 1.04}))
    assert ok["confirmed"]
    bad, _ = cd.decide(frame({"onoff|0.9": 0.9, "onoff|1.2": 0.95, "onoff|0.6": 1.06}))
    assert not bad["confirmed"] and bad["worst_point"] == "onoff|0.6"          # +6 % breaks the 5 % limit
    few, _ = cd.decide(frame({"onoff|0.9": 1.01, "onoff|1.2": 1.02, "onoff|0.95": 0.99}))
    assert not few["confirmed"]                                                  # only 1 of 3 high-load points better


# ---------------- analysis statistics ----------------
def test_ci95_edges():
    assert analysis.ci95([])[2] == 0 and np.isnan(analysis.ci95([])[0])
    m, h, n = analysis.ci95([3.0])
    assert (m, n) == (3.0, 1) and np.isnan(h)
    m, h, n = analysis.ci95([1.0, np.nan, 3.0])
    assert (m, n) == (2.0, 2)
    assert analysis.ci95([2.0, 2.0, 2.0])[1] == 0.0


def test_paired_vs_identical_and_shifted():
    df = pd.DataFrame({"point": "p", "seed": list(range(10)) * 3,
                       "scheduler": ["DRR"] * 10 + ["SP"] * 10 + ["FIFO"] * 10,
                       "x": list(range(10)) + list(range(10)) + [v + 1.0 for v in range(10)]})
    r = analysis.paired_vs(df, "x").set_index("scheduler")
    assert r.loc["SP", "diff"] == 0 and r.loc["SP", "p"] == 1.0 and r.loc["SP", "wins"] == 0
    assert r.loc["FIFO", "diff"] == pytest.approx(1.0) and r.loc["FIFO", "p"] < 0.01


def test_rank_stability_ties_share_first_place():
    rows = [{"point": "p", "seed": s, "scheduler": n, "W": (1.0 if n in ("SP", "DRR") else 2.0)}
            for s in range(4) for n in analysis.ORDER]
    r = analysis.rank_stability(pd.DataFrame(rows), "W").set_index("scheduler")
    assert r.loc["SP", "first_share"] == 1.0 and r.loc["DRR", "first_share"] == 1.0
    assert r.loc["FIFO", "mean_rank"] == 3.0


def test_check_pairing_and_duplicate_keys(tmp_path, monkeypatch):
    ok = pd.DataFrame({"point": ["p", "p"], "seed": [1, 1], "trace": ["a", "a"]})
    assert analysis.check_pairing(ok) == 1
    with pytest.raises(AssertionError):
        analysis.check_pairing(pd.DataFrame({"point": ["p", "p"], "seed": [1, 1], "trace": ["a", "b"]}))
    d = tmp_path / "results" / "X"
    d.mkdir(parents=True)
    cols = {c: [0.1, 0.1] for c in ("lat_p95", "vid_p95", "blk_p95")}
    pd.DataFrame({"key": ["k", "k"], **cols}).to_csv(d / "runs.csv", index=False)
    monkeypatch.setattr(analysis, "ROOT", tmp_path)
    with pytest.raises(ValueError):
        analysis.load("X")


# ---------------- end-to-end outputs on the saved results ----------------
@pytest.mark.skipif(not HAVE_RESULTS, reason="needs saved results")
def test_report_regenerates_with_every_section(tmp_path):
    rep = load_script("make_report")
    out = tmp_path / "R.md"
    rep.main(out=out)
    text = out.read_text(encoding="utf-8")
    for heading in ["## Headline results", "## RQ1", "## RQ2", "## RQ3", "### E9", "### E1D", "### ES",
                    "## RQ4", "## RQ5", "## Measurement adequacy", "## Validation", "## Threats to validity"]:
        assert heading in text, heading
    assert "<<HEADLINE>>" not in text and "nan" not in text.split("## Headline")[1].split("##")[0]


@pytest.mark.skipif(not HAVE_RESULTS, reason="needs saved results")
def test_figures_regenerate(tmp_path, monkeypatch):
    fig = load_script("make_figures")
    monkeypatch.setattr(fig, "FIG", tmp_path)
    for name in dir(fig):
        if name.startswith("fig") and callable(getattr(fig, name)):
            getattr(fig, name)()
    pngs = sorted(p.stem for p in tmp_path.glob("*.png"))
    assert len(pngs) in (11, 12) and all((tmp_path / f"{p}.pdf").exists() for p in pngs)


@pytest.mark.skipif(not HAVE_RESULTS, reason="needs saved results")
def test_saved_results_integrity():
    for exp in EXPECTED:
        p = ROOT / "results" / exp / "runs.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p)
        assert len(df) == EXPECTED[exp] and df.key.is_unique, exp
        assert (df.n_delivered + df.n_dropped == df.n_packets).all() and (df.pending == 0).all(), exp
        f = ROOT / "results" / exp / "failures.csv"
        assert not f.exists() or f.stat().st_size == 0, exp
    dec = json.loads((ROOT / "results" / "DEVD" / "decision.json").read_text())
    assert dec["confirmed"] is True
