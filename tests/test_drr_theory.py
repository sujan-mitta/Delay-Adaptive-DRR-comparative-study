"""DRR theory and limits for any number of classes: the network-calculus delay bound of Boyer et al. as an oracle,
the DRR fairness lemma, the skip-ahead over empty passes, extreme class counts, and exact metamorphic laws."""
import time

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from drrsim import literature as L
from drrsim.engine import simulate
from drrsim.schedulers import DRR, DRREndOfService, make

ANY_K = ["FIFO", "SP", "DRR", "DRR-EOS", "SCRR"]


def random_trace(rng, k, n, horizon=0.05, sizes=(40, 64, 200, 576, 1500, 9000)):
    return L.make_trace(rng.uniform(0, horizon, n), rng.integers(0, k, n), rng.choice(sizes, n))


def params(name, q):
    return {"quanta": tuple(q)} if name in ("DRR", "DRR-EOS") else {}


# ---------------------------------------------------------------- Boyer et al. bound as an oracle
def test_boyer_bound_reproduces_published_values():
    b1, c1 = L.B1, L.B1["c"] / 8
    assert L.boyer_bound(0, b1["quanta"], [100] * 3, 100, 0.86 * c1, c1) * 1e6 == pytest.approx(146.228, abs=5e-4)
    b2, c2 = L.B2, L.B2["c"] / 8
    got = [L.boyer_bound(i, [b2["quantum"]] * 4, b2["l"], b2["b"][i], b2["r_bps"][i] / 8, c2) for i in range(4)]
    assert got == pytest.approx(b2["boyer_s"], rel=0.013)            # Table 1 prints 2-3 significant digits


def test_boyer_bound_rejects_unstable_flow():
    with pytest.raises(ValueError):
        L.boyer_bound(0, [100.0, 100.0], [100, 100], 100, 0.6, 1.0)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.integers(0, 2 ** 32 - 1), st.sampled_from([1.0, 0.25]))
def test_every_packet_meets_the_boyer_bound(seed, qmin_frac):
    """Random DRR systems (2-5 flows, quanta from qmin_frac to 3 x max packet), token-bucket inputs that are greedy,
    offset or with random silences: no packet of any flow may exceed its Boyer et al. delay bound, under both the
    end-of-service rule the bound is derived for and the dequeue-time rule."""
    rng = np.random.default_rng(seed)
    k = int(rng.integers(2, 6))
    lmax = [int(rng.choice([64, 200, 576, 1500])) for _ in range(k)]
    Q = [float(max(1, int(rng.uniform(qmin_frac, 3.0) * l))) for l in lmax]
    c = 1.25e6
    R = [c * q / sum(Q) for q in Q]
    share = rng.dirichlet(np.ones(k)) * rng.uniform(0.3, 0.98)
    r = [min(share[i] * c, 0.999 * R[i]) for i in range(k)]
    b = [l * int(rng.integers(1, 30)) for l in lmax]
    times, cls, sizes = [], [], []
    for i in range(k):
        mode = int(rng.integers(0, 3))
        ts = L.token_bucket_times(rng, r[i], b[i], lmax[i], start=rng.uniform(0, 0.02) if mode else 1e-9 * i,
                                  horizon=0.2, idle_p=[0.0, 0.0, 0.2][mode], idle_mean=rng.uniform(0.1, 2) * b[i] / r[i])
        assert L.conforms(ts, [lmax[i]] * len(ts), r[i], b[i])
        times += ts
        cls += [i] * len(ts)
        sizes += [lmax[i]] * len(ts)
    tr = L.make_trace(times, cls, sizes)
    for sch in ("DRR-EOS", "DRR"):
        log = simulate(tr, make(sch, k=k, quanta=tuple(Q)), L.config(c * 8))
        d = log.end - tr.t
        for i in range(k):
            if np.any(tr.cls == i):
                assert d[tr.cls == i].max() <= L.boyer_bound(i, Q, lmax, b[i], r[i], c) * (1 + 1e-12), (sch, i)


# ---------------------------------------------------------------- DRR fairness lemma
@pytest.mark.parametrize("name", ["DRR", "DRR-EOS"])
@pytest.mark.parametrize("seed", range(6))
def test_drr_fairness_lemma_for_backlogged_classes(name, seed):
    """All classes backlogged from t = 0: at every service instant, for any two classes still backlogged,
    |sent_i / Q_i - sent_j / Q_j| <= 2 + Max / min(Q) (visit counts differ by at most one; within a visit a
    class is at most one quantum ahead; the carried deficit is below Max)."""
    rng = np.random.default_rng(seed)
    k = int(rng.integers(2, 9))
    n = 400 * k
    tr = L.make_trace(np.zeros(n), rng.integers(0, k, n), rng.choice([64, 576, 1500], n))
    Q = rng.uniform(100, 4000, k)
    log = simulate(tr, make(name, k=k, quanta=tuple(Q)), L.config(1e7))
    o = np.argsort(log.start)
    sent = np.zeros(k)
    left = np.bincount(tr.cls, minlength=k).astype(int)
    M = int(tr.size.max())
    for j in o:
        c = tr.cls[j]
        sent[c] += tr.size[j]
        left[c] -= 1
        live = left > 0
        if live.sum() >= 2:
            x = sent[live] / Q[live]
            assert x.max() - x.min() <= 2 + M / Q.min() + 1e-9


def test_drr_deficit_never_reaches_max_between_visits():
    rng = np.random.default_rng(3)
    tr = random_trace(rng, 5, 3000)
    s = make("DRR", k=5, quanta=tuple(rng.uniform(50, 3000, 5)))
    seen = []
    sel = s.select

    def spy(now):
        c = sel(now)
        seen.extend(s.deficit[x] for x in s.active if x != s.current)
        return c
    s.select = spy
    simulate(tr, s, L.config(1e7))
    assert seen and max(seen) < int(tr.size.max()) and min(seen) >= 0


# ---------------------------------------------------------------- skip-ahead over empty passes
class _NoSkip(DRR):
    name = "DRR-noskip"
    any_k = True

    def _skip_empty_passes(self):
        pass


class _NoSkipEOS(DRREndOfService):
    name = "DRR-EOS-noskip"
    any_k = True

    def _skip_empty_passes(self):
        pass


@pytest.mark.parametrize("fast, slow", [(DRR, _NoSkip), (DRREndOfService, _NoSkipEOS)])
@pytest.mark.parametrize("kind", ["integer", "fractional", "tiny"])
def test_skip_ahead_makes_identical_decisions(fast, slow, kind):
    rng = np.random.default_rng({"integer": 1, "fractional": 2, "tiny": 3}[kind])
    for _ in range(15):
        k = int(rng.integers(1, 7))
        n = int(rng.integers(20, 300 if kind != "tiny" else 60))     # the pass-by-pass reference is slow for tiny quanta
        tr = random_trace(rng, k, n, sizes=(40, 64, 200, 576, 1500, 9000) if kind != "tiny" else (40, 64, 200, 576))
        q = {"integer": lambda: float(rng.integers(1, 40)), "fractional": lambda: float(rng.uniform(0.5, 40)),
             "tiny": lambda: float(rng.uniform(0.01, 0.5))}[kind]
        Q = tuple(q() for _ in range(k))
        a = simulate(tr, fast(k=k, quanta=Q), L.config(1e7))
        b = simulate(tr, slow(k=k, quanta=Q), L.config(1e7))
        assert np.array_equal(a.start, b.start)


def test_tiny_quanta_do_not_hang():
    # 0.01 B quanta against packets up to 9000 B: 900 000 empty passes per packet without the skip
    rng = np.random.default_rng(4)
    tr = random_trace(rng, 3, 1000, horizon=0.5)
    t0 = time.perf_counter()
    log = simulate(tr, make("DRR", quanta=(0.01, 0.01, 0.01)), L.config(1e7))
    assert log.pending == 0 and time.perf_counter() - t0 < 1.0       # ~0.02 s; several seconds without the skip


# ---------------------------------------------------------------- extreme class counts
def test_one_class_every_any_k_scheduler_is_fifo():
    rng = np.random.default_rng(5)
    tr = random_trace(rng, 1, 2000)
    ref = simulate(tr, make("FIFO", k=1), L.config(1e7)).start
    for name in ANY_K[1:]:
        log = simulate(tr, make(name, k=1, **params(name, [700.0])), L.config(1e7))
        assert np.array_equal(log.start, ref), name


@pytest.mark.parametrize("name", ANY_K)
def test_maximum_class_count(name):
    rng = np.random.default_rng(6)
    k = 4096
    tr = L.make_trace(np.sort(rng.uniform(0, 0.01, 6000)), rng.integers(0, k, 6000), rng.choice([64, 1500], 6000))
    log = simulate(tr, make(name, k=k, **params(name, [1500.0] * k)), L.config(1e7))
    assert log.pending == 0 and not np.isnan(log.end).any()


# ---------------------------------------------------------------- exact metamorphic laws
@pytest.mark.parametrize("seed", range(4))
def test_work_conservation_busy_periods_identical(seed):
    """Non-preemptive work-conserving schedulers see the same busy periods: the busy/idle pattern depends only
    on arrival times and sizes, never on the order of service."""
    rng = np.random.default_rng(seed)
    k = int(rng.integers(2, 12))
    tr = random_trace(rng, k, 1500, horizon=0.4)

    def busy(log):
        o = np.argsort(log.start)
        s, e = log.start[o], log.end[o]
        gaps = s[1:] > e[:-1] + 1e-12
        return np.r_[s[0], s[1:][gaps]], np.r_[e[:-1][gaps], e[-1]]
    ref = busy(simulate(tr, make("FIFO", k=k), L.config(1e7)))
    for name in ANY_K[1:]:
        got = busy(simulate(tr, make(name, k=k, **params(name, rng.uniform(64, 3000, k))), L.config(1e7)))
        assert len(got[0]) == len(ref[0]) and np.allclose(got[0], ref[0], rtol=0, atol=1e-9) \
            and np.allclose(got[1], ref[1], rtol=0, atol=1e-9), name


@pytest.mark.parametrize("name", ANY_K)
def test_class_relabelling_any_k(name):
    """Renaming classes (and permuting quanta with them) changes nothing for round-robin rules that do not use
    the class index (continuous arrival times: no same-instant ties ordered by index). SP is the exception."""
    rng = np.random.default_rng(7)
    k = 7
    tr = random_trace(rng, k, 2000)
    perm = rng.permutation(k)
    q = rng.uniform(64, 3000, k)
    a = simulate(tr, make(name, k=k, **params(name, q)), L.config(1e7))
    tr2 = L.make_trace(tr.t, perm[tr.cls], tr.size)
    q2 = np.empty(k)
    q2[perm] = q
    b = simulate(tr2, make(name, k=k, **params(name, q2)), L.config(1e7))
    if name == "SP":
        assert not np.array_equal(a.start, b.start)
    else:
        assert np.array_equal(a.start, b.start)


@pytest.mark.parametrize("name", ANY_K + ["RL-SP+DRR"])
def test_double_link_rate_halves_time_exactly(name):
    """Scaling time by 1/2 and the link rate by 2 is exact in binary floating point, so every decision time must
    be exactly half (non-adaptive schedulers: adaptive ones use absolute delay targets)."""
    rng = np.random.default_rng(8)
    k = 3
    tr = random_trace(rng, k, 3000)
    p = params(name, rng.uniform(64, 3000, k))
    if name == "RL-SP+DRR":
        p = {"rate_frac": 0.3}
    a = simulate(tr, make(name, k=k, **p), L.config(1e7))
    tr2 = L.make_trace(tr.t / 2, tr.cls, tr.size)
    b = simulate(tr2, make(name, k=k, **p), L.config(2e7))
    assert np.array_equal(b.start, a.start / 2) and np.array_equal(b.end, a.end / 2)
