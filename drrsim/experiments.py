"""Experiment matrix E1–E7 and the tuning grid, as task lists (see docs/EXPERIMENT_PROTOCOL.md)."""
from __future__ import annotations

import json

from .config import SimConfig, TrafficConfig
from .runner import ROOT, task
from .schedulers import ADAPTIVE, SCHEDULERS

DEV_SEEDS = list(range(1, 6))
SEEDS = list(range(101, 121))
LOADS = [0.4, 0.6, 0.8, 0.9, 0.95, 1.05, 1.2]
BURSTS = {"small": 0.01, "medium": 0.05, "large": 0.2}
MIXES = {"A": (0.2, 0.4, 0.4), "B": (0.4, 0.3, 0.3), "C": (0.1, 0.2, 0.7)}
BUFFERS = {"small": 30_000, "medium": 125_000, "large": 500_000}

# knob, grid, extension below the grid, extension above the grid (used once if optimum is on an edge)
TUNE_GRID = {
    "RL-SP+DRR": ("rate_frac", [0.1, 0.2, 0.3, 0.4, 0.5], [0.05, 0.025], [0.6, 0.7]),
    "DR-DRR": ("kappa", [1, 2, 4, 8, 16], [0.5, 0.25], [32, 64]),
    "CQDRR": ("scale", [375.0, 750.0, 1500.0, 3000.0, 6000.0], [187.5, 93.75], [12000.0, 24000.0]),
    "FuzzyDRR": ("gain", [0.5, 1.0, 1.5, 2.0, 3.0], [0.25, 0.1], [4.0, 5.0]),
    "RevenueDRR": ("tau", [0.025, 0.05, 0.1, 0.2, 0.4], [0.0125, 0.00625], [0.8, 1.6]),
}
SENS_KNOBS = {
    "RL-SP+DRR": ["rate_frac"],
    "DR-DRR": ["kappa", "theta", "qmax_mult"],
    "CQDRR": ["scale", "w", "rbar_gain", "rate_ewma"],
    "FuzzyDRR": ["gain", "delay_span", "qmin"],
    "RevenueDRR": ["tau", "ewma", "guar_scale"],
}
SQ_SMOOTH = [1.0, 0.5, 0.25, 0.1]
UPDATE_INTERVALS = [0.005, 0.01, 0.02, 0.05]
DAMPED = "DR-DRR+damping"
TUNED_PATH = ROOT / "config" / "tuned_params.json"


def onoff(load=0.95, burst="medium", **kw) -> SimConfig:
    return SimConfig(TrafficConfig(load=load, arrival="onoff", on_mean=BURSTS[burst], **kw))


def poisson(load, **kw) -> SimConfig:
    return SimConfig(TrafficConfig(load=load, arrival="poisson", **kw))


def tuning_tasks(extra=None):
    """extra: {scheduler: [values]} to run in addition to the base grid."""
    out = []
    for name, (knob, values, _, _) in TUNE_GRID.items():
        for v in list(values) + list((extra or {}).get(name, [])):
            for load in (0.95, 1.2):
                for s in DEV_SEEDS:
                    out.append(task("TUNE", f"{knob}={v}|load={load}", name, s, onoff(load),
                                    {knob: v}, {"knob": knob, "value": v}))
    for load in (0.95, 1.2):  # DRR reference on dev seeds
        for s in DEV_SEEDS:
            out.append(task("TUNE", f"ref|load={load}", "DRR", s, onoff(load), {}, {"knob": "", "value": ""}))
    return out


def load_tuned() -> dict:
    if not TUNED_PATH.exists():
        raise SystemExit("config/tuned_params.json missing: run scripts/tune.py first")
    return json.loads(TUNED_PATH.read_text())["params"]


def _all(exp, point, cfg, tuned, seeds=SEEDS, tags=None):
    return [task(exp, point, n, s, cfg, tuned.get(n, {}), tags) for n in SCHEDULERS for s in seeds]


def experiment_tasks(exp: str, tuned: dict):
    t = []
    if exp == "E1":
        for load in LOADS:
            t += _all("E1", f"poisson|{load}", poisson(load), tuned)
            t += _all("E1", f"onoff|{load}", onoff(load), tuned)
    elif exp == "E2":
        for m, mix in MIXES.items():
            t += _all("E2", f"mix={m}", onoff(0.95, mix=mix), tuned, tags={"mix_id": m})
    elif exp == "E3":
        t += _all("E3", "poisson", poisson(0.9), tuned, tags={"burst": "poisson"})
        for b in BURSTS:
            t += _all("E3", f"onoff-{b}", onoff(0.9, b), tuned, tags={"burst": b})
    elif exp == "E4":
        for b, size in BUFFERS.items():
            c = onoff(0.95)
            t += _all("E4", f"buffer={b}", SimConfig(c.traffic, buffer_bytes=size), tuned, tags={"buffer_id": b})
    elif exp == "E5":
        cfg = SimConfig(TrafficConfig(arrival="onoff", on_mean=0.05, load=1.3, class_loads=(0.8, 0.2, 0.3)))
        t += _all("E5", "stress", cfg, tuned)
    elif exp == "E6":
        for name, knobs in SENS_KNOBS.items():
            from .schedulers import REGISTRY
            base = {**REGISTRY[name].defaults, **tuned.get(name, {})}
            for load in (0.95, 1.2):
                for knob in knobs:
                    b = base[knob]
                    levels = {"x0.5": 0.5 * b, "x1": b, "x1.5": 1.5 * b}
                    for lab, v in levels.items():
                        p = {**tuned.get(name, {}), knob: v}
                        for s in SEEDS:
                            t.append(task("E6", f"{knob}={lab}|load={load}", name, s, onoff(load), p,
                                          {"knob": knob, "level": lab, "value": v}))
        for load in (0.95, 1.2):
            for s in SEEDS:
                t.append(task("E6", f"ref|load={load}", "DRR", s, onoff(load), {}, {"knob": "", "level": "ref", "value": ""}))
    elif exp == "E8":  # exploratory: partitioned buffer (added after E1, see protocol deviation log)
        for load in (0.95, 1.2):
            c = onoff(load)
            t += _all("E8", f"partitioned|{load}", SimConfig(c.traffic, buffer_policy="partitioned"), tuned,
                      tags={"policy": "partitioned"})
        st = TrafficConfig(arrival="onoff", on_mean=0.05, load=1.3, class_loads=(0.8, 0.2, 0.3))
        t += _all("E8", "partitioned|stress", SimConfig(st, buffer_policy="partitioned"), tuned,
                  tags={"policy": "partitioned"})
        pc = poisson(1.2)   # explains the shared-buffer capture effect seen in E1 Poisson overload
        t += _all("E8", "partitioned|poisson1.2", SimConfig(pc.traffic, buffer_policy="partitioned"), tuned,
                  tags={"policy": "partitioned"})
    elif exp == "E9":  # pre-registered DR-DRR damping ablation (protocol, section E9)
        p0 = tuned.get("DR-DRR", {})
        for label, cfg in [("onoff|0.95", onoff(0.95)), ("onoff|1.2", onoff(1.2)), ("poisson|1.2", poisson(1.2))]:
            for lam in SQ_SMOOTH:
                for s in SEEDS:
                    t.append(task("E9", f"{label}|smooth={lam}", "DR-DRR", s, cfg, {**p0, "smooth": lam},
                                  {"base_point": label, "smooth": lam}))
    elif exp == "DEVD":  # dev-seed confirmation of DR-DRR damping (protocol section E1D)
        p0 = tuned.get("DR-DRR", {})
        for load in LOADS:
            for label, cfg in [(f"poisson|{load}", poisson(load)), (f"onoff|{load}", onoff(load))]:
                for lam in (1.0, 0.5):
                    for s in DEV_SEEDS:
                        t.append(task("DEVD", f"{label}|smooth={lam}", "DR-DRR", s, cfg, {**p0, "smooth": lam},
                                      {"base_point": label, "smooth": lam}))
    elif exp == "E1D":  # DR-DRR+damping at every E1 point, reported seeds (only after DEVD confirms)
        for load in LOADS:
            for label, cfg in [(f"poisson|{load}", poisson(load)), (f"onoff|{load}", onoff(load))]:
                t += [task("E1D", label, DAMPED, s, cfg, {**tuned.get("DR-DRR", {}), "smooth": 0.5}) for s in SEEDS]
    elif exp == "E10":  # robustness: adaptive update interval, and warm-up length
        for name in ADAPTIVE:
            for load in (0.95, 1.2):
                for dt in UPDATE_INTERVALS:
                    c = onoff(load)
                    t += [task("E10", f"dt={dt}|onoff|{load}", name, s, SimConfig(c.traffic, update_interval=dt),
                               tuned.get(name, {}), {"check": "update_interval", "dt": dt, "base_point": f"onoff|{load}"})
                          for s in SEEDS]
        for label, mk in [("onoff|1.2", onoff), ("poisson|1.2", poisson)]:
            c = mk(1.2, warmup=20.0)
            t += _all("E10", f"warmup=20|{label}", c, tuned, tags={"check": "warmup", "base_point": label})
    elif exp == "E1V":  # our superseded CQDRR reading, for comparison with the paper rule (deviation 5)
        for load in LOADS:
            for label, cfg in [(f"poisson|{load}", poisson(load)), (f"onoff|{load}", onoff(load))]:
                t += [task("E1V", label, "CQDRR-draft", s, cfg, {"beta": 2.0}) for s in SEEDS]
    elif exp == "ES":  # SCRR, optional ninth scheduler (protocol section ES); paired with source experiments
        st = TrafficConfig(arrival="onoff", on_mean=0.05, load=1.3, class_loads=(0.8, 0.2, 0.3))
        pts = []
        for load in LOADS:
            pts += [("E1", f"poisson|{load}", poisson(load)), ("E1", f"onoff|{load}", onoff(load))]
        pts += [("E3", "poisson", poisson(0.9))] + [("E3", f"onoff-{b}", onoff(0.9, b)) for b in BURSTS]
        pts += [("E5", "stress", SimConfig(st))]
        pts += [("E8", f"partitioned|{l}", SimConfig(onoff(l).traffic, buffer_policy="partitioned")) for l in (0.95, 1.2)]
        pts += [("E8", "partitioned|stress", SimConfig(st, buffer_policy="partitioned"))]
        for src, label, cfg in pts:
            t += [task("ES", f"{src}|{label}", "SCRR", s, cfg, {}, {"src_exp": src, "base_point": label}) for s in SEEDS]
            if src == "E1":
                t += [task("ES", f"{src}|{label}|q9000", "DRR", s, cfg, {"quanta": (9000, 9000, 9000)},
                           {"src_exp": src, "base_point": label}) for s in SEEDS]
    elif exp == "E11":  # real-life stress scenarios (pre-registered, protocol section E11); 8 schedulers + SCRR
        for label, cfg in SCENARIOS.items():
            for name in SCHEDULERS + ["SCRR"]:
                t += [task("E11", label, name, s, cfg, tuned.get(name, {}), {"scenario": label}) for s in SEEDS]
    elif exp == "E12":  # more real-life conditions + checks of the method (protocol section E12)
        for label, cfg in SCENARIOS_E12.items():
            for name in SCHEDULERS + ["SCRR"]:
                t += [task("E12", label, name, s, cfg, tuned.get(name, {}), {"check": "scenario", "scenario": label})
                      for s in SEEDS]
        for load in (0.95, 1.2):                       # M1: 10x longer measurement window
            cfg = onoff(load, duration=600.0)
            t += [task("E12", f"window|{load}", name, s, cfg, tuned.get(name, {}), {"check": "window", "base": f"onoff|{load}"})
                  for name in SCHEDULERS for s in range(101, 111)]
        t += [task("E12", "seeds|0.95", name, s, onoff(0.95), tuned.get(name, {}), {"check": "seeds", "base": "onoff|0.95"})
              for name in SCHEDULERS for s in range(101, 201)]   # M2: 100 seeds
    elif exp == "E7":
        t += _all("E7", "poisson|0.3", poisson(0.3), tuned)
    else:
        raise ValueError(exp)
    return t


_STEPS = ((5.0, 15.0, 0.5), (15.0, 25.0, 0.75), (25.0, 35.0, 1.0), (35.0, 45.0, 1.25), (45.0, 55.0, 1.5),
          (55.0, 65.0, 1.625))   # load 0.8 x factor = 0.4, 0.6, 0.8, 1.0, 1.2, 1.3 in six 10-s steps
SCENARIOS = {
    "jumbo": onoff(0.95, size_override=(None, None, (9000, 9000))),
    "tiny": onoff(0.95, size_override=((64, 64), None, None)),
    "heavy-tail": onoff(0.95, on_dist="pareto", pareto_alpha=1.5),
    "sync": onoff(0.95, sync=True),
    "flash-crowd": onoff(0.8, profile=((25.0, 35.0, 3.0, 1),)),
    "link-fade": SimConfig(onoff(0.8).traffic, capacity=((25.0, 35.0, 0.4),)),
    "abuse": SimConfig(TrafficConfig(arrival="onoff", on_mean=0.05, load=1.1, class_loads=(0.6, 0.2, 0.3),
                                     size_override=((1500, 1500), None, None))),
    "ramp": onoff(0.8, profile=tuple((a, b, f, -1) for a, b, f in _STEPS)),
}

IMIX = ((40, 7), (576, 4), (1500, 1))      # classic Internet mix by packet count
SCENARIOS_E12 = {
    "imix": onoff(0.95, size_dist=(None, IMIX, IMIX)),
    "red": SimConfig(onoff(0.95).traffic, buffer_policy="red"),
    "bulk-flood": SimConfig(TrafficConfig(arrival="onoff", on_mean=0.05, load=3.6, class_loads=(0.2, 0.4, 3.0))),
    "shallow-jumbo": SimConfig(onoff(0.95, size_override=(None, None, (9000, 9000))).traffic, buffer_bytes=30_000),
}

EXPERIMENTS = ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8", "E9", "E10"]
