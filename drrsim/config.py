"""Configuration objects with validation. All times in seconds, sizes in bytes, rates in bit/s."""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, replace


@dataclass(frozen=True)
class ClassSpec:
    name: str
    size_min: int
    size_max: int
    delay_target: float
    price: float

    @property
    def mean_size(self) -> float:
        return (self.size_min + self.size_max) / 2


CLASSES: tuple[ClassSpec, ...] = (
    ClassSpec("lat", 200, 200, 0.010, 3.0),
    ClassSpec("vid", 1000, 1500, 0.050, 2.0),
    ClassSpec("blk", 1500, 1500, 0.500, 1.0),
)
K = len(CLASSES)


@dataclass(frozen=True)
class TrafficConfig:
    load: float = 0.9                      # total offered load / link rate
    mix: tuple = (0.2, 0.4, 0.4)           # byte shares per class
    arrival: str = "poisson"               # "poisson" | "onoff"
    on_mean: float = 0.05                  # mean ON period (ON/OFF only)
    duty: float = 0.5                      # fraction of time ON (ON/OFF only)
    class_loads: tuple | None = None       # absolute per-class loads; overrides load*mix
    warmup: float = 5.0
    duration: float = 60.0
    link_rate: float = 10e6
    # --- real-life scenario options (E11); the defaults reproduce the original model exactly ---
    size_override: tuple | None = None     # per class: None or (min_bytes, max_bytes)
    on_dist: str = "exp"                   # ON/OFF period distribution: "exp" | "pareto"
    pareto_alpha: float = 1.5              # Pareto shape for on_dist="pareto" (> 1: finite mean)
    sync: bool = False                     # one shared ON/OFF process for all classes
    profile: tuple = ()                    # ((t0, t1, factor, cls), ...): arrival-rate multiplier, cls -1 = all
    size_dist: tuple | None = None         # per class: None or ((bytes, weight), ...) discrete size distribution

    def __post_init__(self):
        nums = [self.load, self.on_mean, self.duty, self.warmup, self.duration, self.link_rate, *self.mix,
                *(self.class_loads or ())]
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in nums):
            raise ValueError("traffic parameters must be finite numbers (no NaN or infinity)")
        if self.arrival not in ("poisson", "onoff"):
            raise ValueError(f"unknown arrival process {self.arrival!r}")
        if len(self.mix) != K or any(m < 0 for m in self.mix) or abs(sum(self.mix) - 1) > 1e-9:
            raise ValueError(f"mix must be {K} non-negative shares summing to 1, got {self.mix}")
        if self.class_loads is not None and (len(self.class_loads) != K or any(x < 0 for x in self.class_loads)):
            raise ValueError("class_loads must be K non-negative values")
        if not (self.load > 0 and self.link_rate > 0 and self.duration > 0 and self.warmup >= 0):
            raise ValueError("load, link_rate, duration must be > 0 and warmup >= 0")
        if not (0 < self.duty <= 1 and self.on_mean > 0):
            raise ValueError("duty must be in (0,1] and on_mean > 0")
        if self.on_dist not in ("exp", "pareto"):
            raise ValueError(f"unknown on_dist {self.on_dist!r}")
        if not (isinstance(self.pareto_alpha, (int, float)) and math.isfinite(self.pareto_alpha)
                and 1 < self.pareto_alpha <= 50):
            raise ValueError("pareto_alpha must be in (1, 50] (finite mean)")
        if not isinstance(self.sync, bool):
            raise ValueError("sync must be True or False")
        if self.size_override is not None:
            if len(self.size_override) != K:
                raise ValueError(f"size_override needs {K} entries (None or (min, max))")
            for e in self.size_override:
                if e is not None and not (len(e) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in e)
                                          and 1 <= e[0] <= e[1] <= 65535):
                    raise ValueError(f"size_override entry must be (min, max) integers with 1 <= min <= max <= 65535, got {e}")
        if self.size_dist is not None:
            if len(self.size_dist) != K:
                raise ValueError(f"size_dist needs {K} entries (None or ((bytes, weight), ...))")
            for k, e in enumerate(self.size_dist):
                if e is None:
                    continue
                if self.size_override is not None and self.size_override[k] is not None:
                    raise ValueError(f"class {k}: use size_override or size_dist, not both")
                if not (len(e) >= 1 and all(len(x) == 2 and isinstance(x[0], int) and not isinstance(x[0], bool)
                                            and 1 <= x[0] <= 65535 and isinstance(x[1], (int, float))
                                            and math.isfinite(x[1]) and x[1] > 0 for x in e)):
                    raise ValueError(f"size_dist entry must be ((bytes 1..65535, weight > 0), ...), got {e}")
        for seg in self.profile:
            if not (len(seg) == 4 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in seg)
                    and seg[0] < seg[1] and 0 <= seg[2] <= 100 and seg[3] in (-1, 0, 1, 2)):
                raise ValueError(f"profile segment must be (t0 < t1, 0 <= factor <= 100, class in -1..2), got {seg}")

    @property
    def horizon(self) -> float:
        return self.warmup + self.duration

    def class_mean_size(self, k: int) -> float:
        if self.size_dist is not None and self.size_dist[k] is not None:
            w = sum(x[1] for x in self.size_dist[k])
            return sum(x[0] * x[1] for x in self.size_dist[k]) / w
        lo, hi = self.class_sizes(k)
        return (lo + hi) / 2

    def class_sizes(self, k: int) -> tuple:
        o = self.size_override[k] if self.size_override else None
        return o if o is not None else (CLASSES[k].size_min, CLASSES[k].size_max)

    def per_class_load(self) -> tuple:
        if self.class_loads is not None:
            return tuple(self.class_loads)
        return tuple(self.load * m for m in self.mix)

    def key(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:12]


@dataclass(frozen=True)
class SimConfig:
    traffic: TrafficConfig = field(default_factory=TrafficConfig)
    buffer_bytes: int = 125_000
    buffer_policy: str = "shared"          # "shared" tail drop | "partitioned" (B/K per class) | "red"
    red: tuple = (25_000.0, 75_000.0, 0.1, 0.002)   # RED (min_th bytes, max_th bytes, max_p, w_q)
    red_seed: int = 0                      # RNG seed for RED's random drops (same for every scheduler: paired)
    update_interval: float = 0.010
    starvation_T: float = 0.100
    drain: bool = True
    capacity: tuple = ()                   # ((t0, t1, factor), ...): link-rate multiplier at service start

    def __post_init__(self):
        if not isinstance(self.buffer_bytes, int) or isinstance(self.buffer_bytes, bool):
            raise ValueError("buffer_bytes must be an integer number of bytes")
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (self.update_interval, self.starvation_T)):
            raise ValueError("update_interval and starvation_T must be finite numbers")
        if self.buffer_bytes < max(c.size_max for c in CLASSES):
            raise ValueError("buffer must hold at least one maximum-size packet")
        if self.buffer_policy == "red":
            mn, mx, mp, wq = self.red
            if not (all(isinstance(x, (int, float)) and math.isfinite(x) for x in self.red)
                    and 0 <= mn < mx <= self.buffer_bytes and 0 < mp <= 1 and 0 < wq <= 1):
                raise ValueError(f"red must be (0 <= min_th < max_th <= buffer, 0 < max_p <= 1, 0 < w_q <= 1), got {self.red}")
            if not isinstance(self.red_seed, int):
                raise ValueError("red_seed must be an integer")
        if self.buffer_policy not in ("shared", "partitioned", "red"):
            raise ValueError(f"unknown buffer policy {self.buffer_policy!r}")
        if self.buffer_policy == "partitioned" and self.buffer_bytes // K < max(c.size_max for c in CLASSES):
            raise ValueError("each partition must hold at least one maximum-size packet")
        if self.update_interval <= 0 or self.starvation_T <= 0:
            raise ValueError("update_interval and starvation_T must be > 0")
        for seg in self.capacity:
            if not (len(seg) == 3 and all(isinstance(x, (int, float)) and math.isfinite(x) for x in seg)
                    and seg[0] < seg[1] and 1e-3 <= seg[2] <= 1e3):
                raise ValueError(f"capacity segment must be (t0 < t1, 1e-3 <= factor <= 1e3), got {seg}")

    def rate_factor(self, t: float) -> float:
        """Link-rate multiplier for a packet starting service at time t (last matching segment wins)."""
        f = 1.0
        for t0, t1, factor in self.capacity:
            if t0 <= t < t1:
                f = factor
        return f

    def with_traffic(self, **kw) -> "SimConfig":
        return replace(self, traffic=replace(self.traffic, **kw))
