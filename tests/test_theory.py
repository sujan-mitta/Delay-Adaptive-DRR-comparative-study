"""The simulator against queueing theory, exact sample-path laws, and statistical tests of the traffic."""
import numpy as np
import pytest
from scipy import stats

from conftest import WORK_CONSERVING, trace_from
from drrsim import SimConfig, TrafficConfig, generate_trace, make, simulate
from drrsim.config import CLASSES

C = 10e6
INF_BUF = 10**12


def run(load_per_class, scheduler="FIFO", seeds=(1, 2, 3), duration=60.0):
    waits = {k: [] for k in range(3)}
    for s in seeds:
        tc = TrafficConfig(class_loads=load_per_class, arrival="poisson", warmup=0.0, duration=duration, link_rate=C)
        tr = generate_trace(tc, s)
        log = simulate(tr, make(scheduler), SimConfig(tc, buffer_bytes=INF_BUF))
        for k in range(3):
            w = (log.start - tr.t)[tr.cls == k]
            if len(w):
                waits[k].append(w.mean())
    return {k: float(np.mean(v)) for k, v in waits.items() if v}


def service_moments(k):
    lo, hi = CLASSES[k].size_min, CLASSES[k].size_max
    sizes = np.arange(lo, hi + 1, dtype=float)               # sizes are uniform integers in [lo, hi]
    return (sizes * 8 / C).mean(), ((sizes * 8 / C) ** 2).mean()


def arrival_rate(k, load):
    return load * C / 8 / CLASSES[k].mean_size


@pytest.mark.parametrize("rho", [0.5, 0.8])
def test_md1_mean_wait(rho):
    D, _ = service_moments(0)                                   # 200 B, deterministic
    theory = rho * D / (2 * (1 - rho))
    sim = run((rho, 0.0, 0.0), duration=40.0)[0]
    assert sim == pytest.approx(theory, rel=0.03)


def test_mg1_pollaczek_khinchine():
    rho = 0.7
    ES, ES2 = service_moments(1)                                # video: uniform 1000..1500 B
    lam = arrival_rate(1, rho)
    theory = lam * ES2 / (2 * (1 - rho))
    sim = run((0.0, rho, 0.0))[1]
    assert sim == pytest.approx(theory, rel=0.03)


def test_strict_priority_matches_cobham():
    loads = (0.2, 0.3, 0.3)                                     # total 0.8, non-preemptive priority 0 > 1 > 2
    lam = [arrival_rate(k, loads[k]) for k in range(3)]
    W0 = sum(lam[k] * service_moments(k)[1] / 2 for k in range(3))
    sigma = np.cumsum(loads)
    theory = [W0 / ((1 - (sigma[k - 1] if k else 0.0)) * (1 - sigma[k])) for k in range(3)]
    sim = run(loads, scheduler="SP", seeds=(1, 2, 3, 4))
    for k in range(3):
        assert sim[k] == pytest.approx(theory[k], rel=0.04)


@pytest.mark.parametrize("arrival", ["poisson", "onoff"])
def test_kleinrock_conservation_exact_sample_path(arrival):
    # for work-conserving non-preemptive schedulers with no drops, the unfinished-work process is identical,
    # hence sum(size * wait) is identical for every scheduler on the same trace
    tc = TrafficConfig(load=0.95, arrival=arrival, warmup=0.0, duration=20.0)
    tr = generate_trace(tc, 5)
    cfg = SimConfig(tc, buffer_bytes=INF_BUF)
    vals = {}
    for name in WORK_CONSERVING:
        log = simulate(tr, make(name), cfg)
        vals[name] = float(np.sum(tr.size * (log.start - tr.t)))
    ref = vals["FIFO"]
    for name, v in vals.items():
        assert v == pytest.approx(ref, rel=1e-9), name
    # and the per-class split differs between schedulers (the law constrains only the weighted sum)
    assert len({round(v, -3) for v in vals.values()}) == 1


def test_littles_law_sample_path():
    tc = TrafficConfig(load=0.9, arrival="onoff", warmup=0.0, duration=20.0)
    tr = generate_trace(tc, 6)
    log = simulate(tr, make("DRR"), SimConfig(tc, buffer_bytes=INF_BUF))
    times = np.concatenate([tr.t, log.start])
    steps = np.concatenate([np.ones(len(tr)), -np.ones(len(tr))])
    o = np.lexsort((-steps, times))                  # at equal times count departures-to-link before arrivals
    q = np.cumsum(steps[o])
    area = np.sum(q[:-1] * np.diff(times[o]))        # integral of the number waiting
    assert area == pytest.approx(np.sum(log.start - tr.t), rel=1e-9)


@pytest.mark.parametrize("name", ["FIFO", "SP", "DRR", "RL-SP+DRR", "SCRR"])
def test_time_scale_invariance_bit_exact(name):
    # doubling the link rate and halving all arrival times halves every timestamp exactly
    # (factor 2 is exact in binary floating point); schedulers here have no absolute-time parameters
    tc = TrafficConfig(load=1.1, arrival="onoff", warmup=0.0, duration=5.0)
    tr = generate_trace(tc, 8)
    fast = trace_from(zip(tr.t / 2, tr.cls, tr.size))
    a = simulate(tr, make(name), SimConfig(tc, buffer_bytes=40_000))
    b = simulate(fast, make(name), SimConfig(TrafficConfig(load=1.1, arrival="onoff", warmup=0.0, duration=2.5,
                                                           link_rate=2 * tc.link_rate), buffer_bytes=40_000))
    assert np.array_equal(a.dropped, b.dropped)
    assert np.array_equal(np.nan_to_num(a.start / 2, nan=-1), np.nan_to_num(b.start, nan=-1))


# ---------------- traffic generator statistics ----------------
def test_poisson_interarrivals_are_exponential():
    tc = TrafficConfig(class_loads=(0.3, 0.0, 0.0), arrival="poisson", warmup=0.0, duration=30.0)
    t = generate_trace(tc, 11).t
    lam = arrival_rate(0, 0.3)
    p = stats.kstest(np.diff(t), "expon", args=(0, 1 / lam)).pvalue
    assert p > 0.001


def test_poisson_counts_have_unit_dispersion():
    tc = TrafficConfig(class_loads=(0.0, 0.5, 0.0), arrival="poisson", warmup=0.0, duration=200.0)
    t = generate_trace(tc, 12).t
    counts = np.histogram(t, bins=np.arange(0, 200.0001, 0.1))[0]
    assert counts.var() / counts.mean() == pytest.approx(1.0, abs=0.08)


def test_video_sizes_uniform_chi_square():
    tr = generate_trace(TrafficConfig(class_loads=(0.0, 0.9, 0.0), warmup=0.0, duration=100.0), 13)
    s = tr.size
    observed = np.bincount(s - 1000, minlength=501)
    p = stats.chisquare(observed).pvalue
    assert p > 0.001 and observed.min() > 0


@pytest.mark.parametrize("duty", [0.25, 0.5, 0.75])
def test_onoff_duty_cycle_is_respected(duty):
    # with long periods (mean ON 1 s) and 10 ms bins, bin-edge effects are small and the ON-period rate
    # (rate / duty, ~7 packets per bin) makes empty ON bins negligible: the share of empty bins ~ 1 - duty
    tc = TrafficConfig(class_loads=(0.0, 0.0, 0.6), arrival="onoff", duty=duty, on_mean=1.0,
                       warmup=0.0, duration=600.0)
    t = generate_trace(tc, 14).t
    counts = np.histogram(t, bins=np.arange(0, 600.0001, 0.01))[0]
    assert (counts == 0).mean() == pytest.approx(1 - duty, abs=0.05)
    on_bins = counts[counts > 0]
    peak = arrival_rate(2, 0.6) / duty * 0.01                     # expected packets per ON bin
    assert on_bins.mean() == pytest.approx(peak, rel=0.1)
