"""Packet traces: Poisson and ON/OFF-modulated Poisson generators, deterministic per seed."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from .config import CLASSES, TrafficConfig


@dataclass
class Trace:
    t: np.ndarray      # arrival times, sorted ascending (ties broken by class index)
    cls: np.ndarray    # int8 class index
    size: np.ndarray   # int32 bytes

    def __len__(self):
        return len(self.t)

    def validate(self, n_classes: int = 3) -> "Trace":
        """Reject traces the engine cannot simulate correctly (it relies on every property checked here)."""
        t, c, s = (np.asarray(x) for x in (self.t, self.cls, self.size))
        if not (t.ndim == c.ndim == s.ndim == 1 and len(t) == len(c) == len(s)):
            raise ValueError("trace arrays t, cls, size must be 1-D and of equal length")
        if len(t) == 0:
            return self
        if not np.issubdtype(t.dtype, np.number) or not np.all(np.isfinite(t)):
            raise ValueError("arrival times must be finite numbers")
        if t[0] < 0:
            raise ValueError("arrival times must be >= 0")
        if np.any(np.diff(t) < 0):
            raise ValueError("arrival times must be sorted ascending")
        if not np.issubdtype(c.dtype, np.integer) or c.min() < 0 or c.max() >= n_classes:
            raise ValueError(f"class indices must be integers in [0, {n_classes - 1}]")
        if not np.issubdtype(s.dtype, np.integer) or s.min() < 1:
            raise ValueError("packet sizes must be integers >= 1 byte")
        return self

    def digest(self) -> str:
        h = hashlib.sha256()
        for a in (self.t, self.cls, self.size):
            h.update(np.ascontiguousarray(a).tobytes())
        return h.hexdigest()[:16]

    def save(self, path):
        np.savez_compressed(path, t=self.t, cls=self.cls, size=self.size)

    @classmethod
    def load(cls, path):
        d = np.load(path)
        return cls(d["t"], d["cls"], d["size"])


def _poisson_times(rng, rate: float, horizon: float) -> np.ndarray:
    if rate <= 0:
        return np.empty(0)
    n_guess = int(rate * horizon + 6 * np.sqrt(rate * horizon) + 16)
    t = np.cumsum(rng.exponential(1.0 / rate, n_guess))
    while t[-1] < horizon:
        more = t[-1] + np.cumsum(rng.exponential(1.0 / rate, n_guess))
        t = np.concatenate([t, more])
    return t[t < horizon]


def _onoff_periods(rng, horizon: float, on_mean: float, duty: float, dist: str = "exp", alpha: float = 1.5):
    """Alternating ON/OFF periods up to `horizon`, starting in the stationary state. Returns (starts, ends) of ON."""
    off_mean = on_mean * (1 - duty) / duty

    def draw(mean):
        if dist == "exp":
            return rng.exponential(mean)
        return mean * (alpha - 1) / alpha * (1.0 + rng.pareto(alpha))   # Pareto with the given mean

    on = rng.random() < duty
    starts, ends = [], []
    t = 0.0
    while t < horizon:
        d = draw(on_mean if on else off_mean)
        if on:
            starts.append(t)
            ends.append(min(t + d, horizon))
        t += d
        on = not on
    return np.array(starts), np.array(ends)


def _onoff_times(rng, rate: float, horizon: float, on_mean: float, duty: float, dist: str = "exp",
                 alpha: float = 1.5, periods=None) -> np.ndarray:
    """ON/OFF-modulated Poisson with long-run mean `rate`; peak rate = rate / duty.
    `periods` (starts, ends) can be supplied to share one ON/OFF process between classes."""
    if rate <= 0:
        return np.empty(0)
    if duty >= 1:
        return _poisson_times(rng, rate, horizon)
    starts, ends = periods if periods is not None else _onoff_periods(rng, horizon, on_mean, duty, dist, alpha)
    if len(starts) == 0:
        return np.empty(0)
    lens = ends - starts
    cum = np.concatenate([[0.0], np.cumsum(lens)])
    # Poisson points on the concatenated ON time axis, mapped back to real time
    u = _poisson_times(rng, rate / duty, cum[-1])
    k = np.searchsorted(cum, u, side="right") - 1
    return starts[k] + (u - cum[k])


MAX_PACKETS = 5e7


def generate_trace(tc: TrafficConfig, seed: int) -> Trace:
    loads = tc.per_class_load()
    expected = sum(l * tc.link_rate / 8 / tc.class_mean_size(k) * max([1.0] + [s[2] for s in tc.profile])
                   for k, l in enumerate(loads)) * tc.horizon
    if expected > MAX_PACKETS:
        raise ValueError(f"configuration would generate ~{expected:.3g} packets (limit {MAX_PACKETS:.0e}); "
                         "reduce load, link rate or duration")
    shared = None
    if tc.arrival == "onoff" and tc.sync and tc.duty < 1:     # one ON/OFF process for every class
        shared = _onoff_periods(np.random.default_rng([seed, 99, 7919]), tc.horizon, tc.on_mean, tc.duty,
                                tc.on_dist, tc.pareto_alpha)
    ts, cs, ss = [], [], []
    for k, spec in enumerate(CLASSES):
        rng = np.random.default_rng([seed, k, 7919])
        lo, hi = tc.class_sizes(k)
        segs = [seg for seg in tc.profile if seg[3] in (-1, k)]
        fmax = max([1.0] + [seg[2] for seg in segs])                   # thinning envelope
        pkt_rate = loads[k] * tc.link_rate / 8 / tc.class_mean_size(k) * fmax
        if tc.arrival == "poisson":
            t = _poisson_times(rng, pkt_rate, tc.horizon)
        else:
            t = _onoff_times(rng, pkt_rate, tc.horizon, tc.on_mean, tc.duty, tc.on_dist, tc.pareto_alpha, shared)
        if segs:                                                       # non-stationary rate by thinning
            f = np.ones(len(t))
            for t0, t1, factor, _ in segs:
                f[(t >= t0) & (t < t1)] = factor
            keep = np.random.default_rng([seed, k, 31337]).random(len(t)) < f / fmax
            t = t[keep]
        dist = tc.size_dist[k] if tc.size_dist is not None else None
        if dist is None:
            s = rng.integers(lo, hi + 1, size=len(t))
        else:                                                          # discrete size distribution (e.g. IMIX)
            vals = np.array([x[0] for x in dist])
            w = np.array([x[1] for x in dist], dtype=float)
            s = vals[rng.choice(len(vals), size=len(t), p=w / w.sum())]
        ts.append(t)
        cs.append(np.full(len(t), k, dtype=np.int8))
        ss.append(s.astype(np.int32))
    t = np.concatenate(ts)
    c = np.concatenate(cs)
    s = np.concatenate(ss)
    order = np.lexsort((c, t))  # by time, then class
    return Trace(t[order], c[order], s[order])
