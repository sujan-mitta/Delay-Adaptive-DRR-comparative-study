"""drrsim: discrete-event simulator for comparing delay-adaptive DRR schedulers."""
from .config import CLASSES, K, SimConfig, TrafficConfig
from .engine import simulate
from .metrics import compute
from .schedulers import ADAPTIVE, SCHEDULERS, make
from .traffic import Trace, generate_trace


__all__ = ["CLASSES", "K", "SimConfig", "TrafficConfig", "simulate", "compute", "ADAPTIVE", "SCHEDULERS",
           "make", "Trace", "generate_trace", "run_one"]


def run_one(cfg: SimConfig, scheduler: str, seed: int, params: dict | None = None, trace: Trace | None = None):
    """Generate (or reuse) the trace, simulate, and return (metrics dict, log, trace)."""
    trace = trace if trace is not None else generate_trace(cfg.traffic, seed)
    sch = make(scheduler, **(params or {}))
    log = simulate(trace, sch, cfg)
    return compute(trace, log, cfg), log, trace
