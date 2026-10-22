"""End-to-end miniature runs of every pipeline script, isolated in temporary folders, plus guard paths."""
import json
import sys
from datetime import datetime

import numpy as np
import pandas as pd
import pytest

from test_pipeline import load_script
from drrsim import SimConfig, TrafficConfig, analysis, experiments, runner
from drrsim.engine import View
from drrsim.runner import task
from drrsim.schedulers import make
from drrsim import traffic


def tiny_cfg(load=0.95, arrival="onoff", **kw):
    return SimConfig(TrafficConfig(load=load, arrival=arrival, duration=1.0, warmup=0.2, **kw))


# ---------------- guard paths in the library ----------------
@pytest.mark.parametrize("name", ["SP", "DRR", "CQDRR"])
def test_select_on_empty_buffer_raises(name):
    s = make(name)
    s.bind(View([], [], 1e7, 125_000, 0.01))
    with pytest.raises(RuntimeError):
        s.select(0.0)


def test_base_interface_defaults():
    f = make("FIFO")
    f.bind(View([], [], 1e7, 125_000, 0.01))
    assert all(np.isnan(f.quanta())) and f.update(0.0) is None and f.on_enqueue(0, 0.0) is None


def test_poisson_generator_tops_up_when_first_batch_is_short():
    class ShortRng:                                   # exponential draws far below the mean -> first batch too short
        def exponential(self, scale, n):
            return np.full(n, scale * 0.01)
    t = traffic._poisson_times(ShortRng(), rate=100.0, horizon=50.0)
    assert t[-1] < 50.0 and len(t) > 100 * 50 and np.all(np.diff(t) > 0)


def test_execute_failure_path_in_process():
    ok, row = runner._execute(task("T", "p", "DRR", 1, tiny_cfg(), params={"bogus": 1}))
    assert not ok and "bogus" in row["error"] and row["key"] == "T|p|DRR|1"


def test_manifest_name_collision_gets_a_counter(tmp_path, monkeypatch):
    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 1, 1, 12, 0, 0, 123456)
    monkeypatch.setattr(runner, "datetime", Frozen)
    t = [task("T", "p", "FIFO", 1, tiny_cfg())]
    for _ in range(3):
        runner.run_tasks(tmp_path, t, workers=1)
    names = sorted(p.name for p in tmp_path.glob("manifest_*.json"))
    assert names == ["manifest_20260101-120000-123456.json", "manifest_20260101-120000-123456_1.json",
                     "manifest_20260101-120000-123456_2.json"]


def test_load_tuned_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(experiments, "TUNED_PATH", tmp_path / "missing.json")
    with pytest.raises(SystemExit):
        experiments.load_tuned()


# ---------------- scripts end to end ----------------
def test_tune_script_end_to_end_with_force_guard(tmp_path, monkeypatch):
    tune = load_script("tune")
    grid = {"DR-DRR": ("kappa", [2.0, 4.0], [1.0], [8.0])}

    def tiny_tuning_tasks(extra=None):
        out = []
        for v in grid["DR-DRR"][1] + list((extra or {}).get("DR-DRR", [])):
            for load in (0.95, 1.2):
                for s in (1, 2):
                    out.append(task("TUNE", f"kappa={v}|load={load}", "DR-DRR", s, tiny_cfg(load),
                                    {"kappa": v}, {"knob": "kappa", "value": v}))
        for load in (0.95, 1.2):
            for s in (1, 2):
                out.append(task("TUNE", f"ref|load={load}", "DRR", s, tiny_cfg(load), {}, {"knob": "", "value": ""}))
        return out
    monkeypatch.setattr(tune, "ROOT", tmp_path)
    monkeypatch.setattr(tune, "TUNED_PATH", tmp_path / "tuned.json")
    monkeypatch.setattr(tune, "TUNE_GRID", grid)
    monkeypatch.setattr(tune, "tuning_tasks", tiny_tuning_tasks)
    monkeypatch.setattr(sys, "argv", ["tune.py"])
    tune.main()
    chosen = json.loads((tmp_path / "tuned.json").read_text())["params"]
    assert set(chosen) == {"DR-DRR"} and chosen["DR-DRR"]["kappa"] in (1.0, 2.0, 4.0, 8.0)
    summary = pd.read_csv(tmp_path / "results" / "TUNE" / "tuning_summary.csv")
    assert summary.chosen.sum() == 1
    tune.main()                                                         # same result: accepted silently
    p = tmp_path / "tuned.json"
    d = json.loads(p.read_text())
    d["params"]["DR-DRR"]["kappa"] = 999.0
    p.write_text(json.dumps(d))
    with pytest.raises(SystemExit):                                     # differing values need --force
        tune.main()
    monkeypatch.setattr(sys, "argv", ["tune.py", "--force"])
    tune.main()
    assert json.loads(p.read_text())["params"] == chosen


def test_run_experiments_script(tmp_path, monkeypatch):
    rx = load_script("run_experiments")
    monkeypatch.setattr(rx, "ROOT", tmp_path)
    monkeypatch.setattr(rx, "load_tuned", lambda: {})
    monkeypatch.setattr(rx, "experiment_tasks", lambda e, t: [task(e, "p", "FIFO", 1, tiny_cfg())])
    monkeypatch.setattr(sys, "argv", ["run_experiments.py", "E1", "E2", "--workers", "1"])
    rx.main()
    for e in ("E1", "E2"):
        assert len(pd.read_csv(tmp_path / "results" / e / "runs.csv")) == 1


def test_e9_control_script(tmp_path, monkeypatch):
    e9 = load_script("e9_control")
    fake = pd.DataFrame([{"base_point": "onoff|0.95", "smooth": lam, "seed": s,
                          "lat_q_mean": 1500.0 * lam, "vid_q_mean": 1500.0, "blk_q_mean": 1500.0}
                         for lam in (1.0, 0.5) for s in (101, 102)])
    monkeypatch.setattr(e9, "load", lambda exp: fake)
    monkeypatch.setattr(e9, "ROOT", tmp_path)
    monkeypatch.setattr(e9, "CFG", {"onoff|0.95": tiny_cfg()})
    monkeypatch.setattr(e9, "SQ_SMOOTH", [1.0, 0.5])
    monkeypatch.setattr(e9, "SEEDS", [101, 102])
    e9.main()
    q = json.loads((tmp_path / "results" / "E9C" / "control_quanta.json").read_text())
    assert q == {"onoff|0.95|0.5": [750.0, 1500.0, 1500.0], "onoff|0.95|1.0": [1500.0, 1500.0, 1500.0]}
    runs = pd.read_csv(tmp_path / "results" / "E9C" / "runs.csv")
    assert len(runs) == 4 and (runs.scheduler == "DRR").all()
    fake.loc[:, "vid_q_mean"] = 999.0                                   # different means: must refuse to mix
    with pytest.raises(SystemExit):
        e9.main()


def test_timeseries_script(tmp_path, monkeypatch):
    ts = load_script("timeseries")
    monkeypatch.setattr(ts, "ROOT", tmp_path)
    monkeypatch.setattr(ts, "load_tuned", lambda: {})
    monkeypatch.setattr(ts, "onoff", lambda load: tiny_cfg(load))
    monkeypatch.setattr(ts, "T0", 0.3)
    monkeypatch.setattr(ts, "T1", 0.8)
    ts.main()
    df = pd.read_csv(tmp_path / "results" / "TIMESERIES" / "quanta.csv")
    assert set(df.scheduler) == set(ts.ADAPTIVE) and df.t.between(0.3, 0.8).all() and (df.backlog >= 0).all()
    before = (tmp_path / "results" / "TIMESERIES" / "quanta.csv").read_bytes()
    ts.main()                                                           # refuses to overwrite
    assert (tmp_path / "results" / "TIMESERIES" / "quanta.csv").read_bytes() == before


@pytest.mark.parametrize("ratios,code", [((0.9, 0.95, 1.0), 0), ((1.2, 1.0, 1.0), 3)])
def test_confirm_damping_script_exit_codes(tmp_path, monkeypatch, ratios, code):
    cd = load_script("confirm_damping")
    pts = ["onoff|0.9", "onoff|1.2", "poisson|0.95"]
    rows = []
    for bp, r in zip(pts, ratios):
        rows += [{"base_point": bp, "smooth": 1.0, "W": 1.0}, {"base_point": bp, "smooth": 0.5, "W": r}]
    monkeypatch.setattr(cd, "load", lambda exp: pd.DataFrame(rows))
    monkeypatch.setattr(cd, "ROOT", tmp_path)
    (tmp_path / "results" / "DEVD").mkdir(parents=True)
    with pytest.raises(SystemExit) as e:
        cd.main()
    assert e.value.code == code
    assert json.loads((tmp_path / "results" / "DEVD" / "decision.json").read_text())["confirmed"] == (code == 0)


def test_backlog_reconstruction_matches_engine_state():
    ts = load_script("timeseries")
    cfg = tiny_cfg(1.1)
    tr = traffic.generate_trace(cfg.traffic, 3)
    from drrsim import simulate
    log = simulate(tr, make("DRR"), cfg)
    times = np.linspace(0.05, 1.1, 50)
    for k in range(3):
        b = ts.backlog_at(times, tr, log, k)
        m = (tr.cls == k) & ~log.dropped
        brute = [tr.size[m][(tr.t[m] <= t) & (log.start[m] > t)].sum() for t in times]
        assert np.array_equal(b, brute)


def test_analysis_load_adds_W(tmp_path, monkeypatch):
    d = tmp_path / "results" / "Y"
    d.mkdir(parents=True)
    pd.DataFrame({"key": ["a", "b"], "lat_p95": [0.02, 0.005], "vid_p95": [0.05, 0.01],
                  "blk_p95": [0.1, 1.0]}).to_csv(d / "runs.csv", index=False)
    monkeypatch.setattr(analysis, "ROOT", tmp_path)
    df = analysis.load("Y")
    assert df.W.tolist() == pytest.approx([2.0, 2.0])
