"""Configuration objects with validation. All times in seconds, sizes in bytes, rates in bit/s."""
from __future__ import annotations

import hashlib
import json
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

    def __post_init__(self):
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

    @property
    def horizon(self) -> float:
        return self.warmup + self.duration

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
    buffer_policy: str = "shared"          # "shared" tail drop | "partitioned" (B/K per class)
    update_interval: float = 0.010
    starvation_T: float = 0.100
    drain: bool = True

    def __post_init__(self):
        if self.buffer_bytes < max(c.size_max for c in CLASSES):
            raise ValueError("buffer must hold at least one maximum-size packet")
        if self.buffer_policy not in ("shared", "partitioned"):
            raise ValueError(f"unknown buffer policy {self.buffer_policy!r}")
        if self.buffer_policy == "partitioned" and self.buffer_bytes // K < max(c.size_max for c in CLASSES):
            raise ValueError("each partition must hold at least one maximum-size packet")
        if self.update_interval <= 0 or self.starvation_T <= 0:
            raise ValueError("update_interval and starvation_T must be > 0")

    def with_traffic(self, **kw) -> "SimConfig":
        return replace(self, traffic=replace(self.traffic, **kw))
