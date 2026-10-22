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


def _onoff_times(rng, rate: float, horizon: float, on_mean: float, duty: float) -> np.ndarray:
    """ON/OFF-modulated Poisson with long-run mean `rate`; peak rate = rate / duty."""
    if rate <= 0:
        return np.empty(0)
    if duty >= 1:
        return _poisson_times(rng, rate, horizon)
    off_mean = on_mean * (1 - duty) / duty
    # alternating periods, starting in the stationary state
    on = rng.random() < duty
    starts, ends = [], []
    t = 0.0
    while t < horizon:
        d = rng.exponential(on_mean if on else off_mean)
        if on:
            starts.append(t)
            ends.append(min(t + d, horizon))
        t += d
        on = not on
    if not starts:
        return np.empty(0)
    starts, ends = np.array(starts), np.array(ends)
    lens = ends - starts
    cum = np.concatenate([[0.0], np.cumsum(lens)])
    # Poisson points on the concatenated ON time axis, mapped back to real time
    u = _poisson_times(rng, rate / duty, cum[-1])
    k = np.searchsorted(cum, u, side="right") - 1
    return starts[k] + (u - cum[k])


def generate_trace(tc: TrafficConfig, seed: int) -> Trace:
    loads = tc.per_class_load()
    ts, cs, ss = [], [], []
    for k, spec in enumerate(CLASSES):
        rng = np.random.default_rng([seed, k, 7919])
        pkt_rate = loads[k] * tc.link_rate / 8 / spec.mean_size
        if tc.arrival == "poisson":
            t = _poisson_times(rng, pkt_rate, tc.horizon)
        else:
            t = _onoff_times(rng, pkt_rate, tc.horizon, tc.on_mean, tc.duty)
        s = rng.integers(spec.size_min, spec.size_max + 1, size=len(t))
        ts.append(t)
        cs.append(np.full(len(t), k, dtype=np.int8))
        ss.append(s.astype(np.int32))
    t = np.concatenate(ts)
    c = np.concatenate(cs)
    s = np.concatenate(ss)
    order = np.lexsort((c, t))  # by time, then class
    return Trace(t[order], c[order], s[order])
