"""Mutation check: plant realistic bugs one at a time in a temporary copy and confirm the tests catch them.

Usage:  python tools/mutation_check.py [--out mutation_report.md]
The working tree is never modified: each mutant is applied to a fresh copy in a temporary folder.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SUITES = ["tests/test_core.py", "tests/test_edge_cases.py", "tests/test_reference.py",
          "tests/test_properties.py", "tests/test_theory.py", "tests/test_robustness.py", "tests/test_scenarios.py",
          "tests/test_aqm_imix.py", "tests/test_metamorphic.py", "tests/test_pipeline.py", "tests/test_literature.py"]

# (id, file, exact original text, mutated text, description)
MUTANTS = [
    ("E1", "drrsim/engine.py", "if t_free <= ta and t_free <= next_upd and t_free <= t_wake and t_free != INF:",
     "if t_free < ta and t_free <= next_upd and t_free <= t_wake and t_free != INF:",
     "arrival processed before a completion at the same instant"),
    ("E2", "drrsim/engine.py", "else (total + s > buffer_bytes)", "else (total + s >= buffer_bytes)",
     "off-by-one: a packet that exactly fills the buffer is dropped"),
    ("E3", "drrsim/engine.py", "part = buffer_bytes // k", "part = buffer_bytes // 2",
     "wrong partition size"),
    ("E4", "drrsim/engine.py", "now = t_wake if t_wake <= ta else ta", "now = t_wake",
     "near-tie wake-up recorded after the arrival it precedes"),
    ("E5", "drrsim/engine.py", "rate_Bps = tc.link_rate / 8.0", "rate_Bps = tc.link_rate / 8.5",
     "bit/byte conversion error"),
    ("E6", "drrsim/engine.py", "            total -= s\n", "",
     "buffer occupancy not released when a packet starts service"),
    ("S1", "drrsim/schedulers.py", "        self.in_active[c] = False\n        self.deficit[c] = 0.0\n        self.current = None",
     "        self.in_active[c] = False\n        self.current = None",
     "DRR keeps its deficit after the queue empties"),
    ("S2", "drrsim/schedulers.py", "            if deficit[c] >= head:\n                deficit[c] -= head\n                if len(q) == 1:                   # queue empties",
     "            if deficit[c] > head:\n                deficit[c] -= head\n                if len(q) == 1:                   # queue empties",
     "DRR needs strictly more deficit than the packet size"),
    ("S3", "drrsim/schedulers.py", "            self.active.append(c)", "            self.active.appendleft(c)",
     "new DRR class jumps the round-robin queue"),
    ("S4", "drrsim/schedulers.py", "if q and (best_id is None or q[0] < best_id):", "if q and (best_id is None or q[0] > best_id):",
     "FIFO serves the newest head first"),
    ("S5", "drrsim/schedulers.py", "        for c, q in enumerate(self.v.queues):\n            if q:\n                return c\n        raise RuntimeError(\"select() called",
     "        for c, q in reversed(list(enumerate(self.v.queues))):\n            if q:\n                return c\n        raise RuntimeError(\"select() called",
     "strict priority order reversed"),
    ("S6", "drrsim/schedulers.py", "d = max(now, self.last_dep + ", "d = (self.last_dep + ",
     "RL-SP shaper gives idle class 0 burst credit (and -inf start)"),
    ("S7", "drrsim/schedulers.py", "if self.dep and self.dep[0] <= now + TIE_EPS:", "if self.dep and self.dep[0] < now - TIE_EPS:",
     "RL-SP misses the exact departure instant"),
    ("S8", "drrsim/schedulers.py", "return (rho - 1) / (rho - rho ** (-k))", "return (rho - 1) / (rho + rho ** (-k))",
     "M/M/1/K blocking formula sign error"),
    ("S9", "drrsim/schedulers.py", "self.virtual_clock = max(self.virtual_clock, self.virtual_dequeue)   #",
     "self.virtual_clock = self.virtual_dequeue   #", "SCRR clock may run backwards"),
    ("S10", "drrsim/schedulers.py", "FUZZY_RULES = ((0.75, 1.0, 1.5),", "FUZZY_RULES = ((1.5, 1.0, 0.75),",
     "fuzzy rule table row reversed"),
    ("S11", "drrsim/schedulers.py", "target = min(max(q, BASE_Q[c]), p[\"qmax_mult\"] * BASE_Q[c])",
     "target = max(q, BASE_Q[c])", "DR-DRR loses its upper bound"),
    ("S12", "drrsim/schedulers.py", "limit = K * (int(max(size[x[0]] for x in queues if x) // min(Q)) + 2)", "limit = 64 * K",
     "CQDRR fixed iteration cap (the original bug)"),
    ("M1", "drrsim/metrics.py", "np.percentile(d, 95)", "np.percentile(d, 90)", "p95 computed as p90"),
    ("M2", "drrsim/metrics.py", "(gap > cfg.starvation_T)", "(gap >= cfg.starvation_T)", "starvation threshold not strict"),
    ("M3", "drrsim/metrics.py", "return float(x.sum() ** 2 / (len(x) * (x ** 2).sum()))",
     "return float(x.sum() / (len(x) * (x ** 2).sum()))", "Jain's index formula wrong"),
    ("M4", "drrsim/metrics.py", "sat = [i for i in unsat if demand[i] - alloc[i] <= fair]",
     "sat = [i for i in unsat if demand[i] - alloc[i] < fair]", "max-min share boundary"),
    ("M5", "drrsim/metrics.py", "prev_end = np.concatenate([[-np.inf], end[:-1]])", "prev_end = np.concatenate([[-np.inf], end[1:]])",
     "starvation gap uses the wrong previous packet"),
    ("M6", "drrsim/metrics.py", "s = np.sign(dq[np.abs(dq) > 1e-9])", "s = np.sign(dq)", "zero changes counted as sign flips"),
    ("T1", "drrsim/traffic.py", "s = rng.integers(lo, hi + 1, size=len(t))", "s = rng.integers(lo, hi, size=len(t))",
     "largest packet size never generated"),
    ("T2", "drrsim/traffic.py", "off_mean = on_mean * (1 - duty) / duty", "off_mean = on_mean * duty / (1 - duty)",
     "ON/OFF duty cycle inverted"),
    ("T3", "drrsim/traffic.py", "order = np.lexsort((c, t))", "order = np.lexsort((t, c))", "trace sorted by class instead of time"),
    ("V1", "drrsim/traffic.py", "        if np.any(np.diff(t) < 0):", "        if False:",
     "unsorted traces silently accepted"),
    ("V2", "drrsim/config.py", "        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in nums):",
     "        if False:", "infinite / NaN traffic parameters accepted"),
    ("T4", "drrsim/engine.py", "elif t_wake <= ta + TIE_EPS and t_wake <= next_upd:", "elif t_wake <= ta and t_wake <= next_upd:",
     "wake-up within the tie tolerance processed after an arrival"),
    ("C1", "drrsim/engine.py", "else now + s / (rate_Bps * rate_factor(now))", "else now + s / rate_Bps",
     "capacity schedule ignored"),
    ("C2", "drrsim/config.py", "            if t0 <= t < t1:", "            if t0 <= t <= t1:",
     "capacity segment end treated as inclusive"),
    ("G1", "drrsim/traffic.py", "return mean * (alpha - 1) / alpha * (1.0 + rng.pareto(alpha))",
     "return mean * (1.0 + rng.pareto(alpha))", "Pareto periods with the wrong mean"),
    ("G2", "drrsim/traffic.py", '    if tc.arrival == "onoff" and tc.sync and tc.duty < 1:', "    if False:",
     "synchronised bursts ignored"),
    ("G3", "drrsim/traffic.py", "keep = np.random.default_rng([seed, k, 31337]).random(len(t)) < f / fmax",
     "keep = np.random.default_rng([seed, k, 31337]).random(len(t)) < f", "load-profile thinning wrong"),
    ("G4", "drrsim/traffic.py", "        lo, hi = tc.class_sizes(k)", "        lo, hi = spec.size_min, spec.size_max",
     "packet-size override ignored"),
    ("R1", "drrsim/engine.py", "red_avg = (1 - red_wq) * red_avg + red_wq * total", "red_avg = red_wq * total",
     "RED average forgets its history"),
    ("R2", "drrsim/engine.py", "pa = pb / (1 - red_count * pb) if red_count * pb < 1 else 1.0", "pa = pb",
     "RED inter-drop count correction missing"),
    ("R3", "drrsim/engine.py", "if total + s > buffer_bytes:                     # physical buffer full: tail drop",
     "if False:", "RED admits packets into a full buffer"),
    ("I1", "drrsim/traffic.py", "p=w / w.sum())]", "p=None)]", "IMIX weights ignored"),
    ("U1", "drrsim/runner.py", "header = list(row) + [k for k in tag_cols if k not in row]", "header = list(row)",
     "runner header fixed by the first row (the bug found in round 3)"),
    ("K1", "drrsim/schedulers.py", 'if k != K and not vars(type(self)).get("any_k", False):', "if False:",
     "a 3-class-only scheduler accepts another number of classes"),
    ("K2", "drrsim/engine.py", "    part = buffer_bytes // k\n", "    part = buffer_bytes // K\n",
     "partition size ignores the number of classes"),
    ("L1", "drrsim/schedulers.py", "if c == self.current and len(self.v.queues[c]) == 1 and self.v.t_free <= now:",
     "if False:", "DRR-EOS keeps an old opportunity across an idle link"),
    ("L2", "drrsim/schedulers.py", "            if not q:                             # empty at the end of its service: the opportunity ends\n"
     "                self._leave_front(c)\n            elif", "            if False:\n                pass\n            elif",
     "DRR-EOS never ends an opportunity on an empty queue"),
    ("L3", "drrsim/literature.py", "            tokens = min(float(b), tokens + r_Bps * gap)", "            tokens = tokens + r_Bps * gap",
     "token bucket not capped at its burst size"),
    ("L4", "drrsim/literature.py", "        if self.new_q.pops + self.old_q.pops > pops0:", "        if False:",
     "SCRR probe never ends a visit (bursts summed across visits)"),
]


# Mutants that cannot change behaviour (verified by reasoning; documented, not counted as misses)
EQUIVALENT = {
    "S1": "DRR resets a class's deficit when the class re-joins (on_enqueue), and the deficit is never "
          "read while the class is off the active list, so also zeroing it on leaving changes nothing.",
    "M4": "Water-filling converges to the unique max-min fair allocation whether a class whose residual "
          "demand equals the fair share is frozen this round (<=) or next round (<).",
}


def run(args):
    out, results = Path(args.out), []
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / "base"
        base.mkdir()
        for item in ("drrsim", "tests", "scripts", "config", "pytest.ini"):
            src = ROOT / item
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, base / item)
        for mid, f, old, new, desc in MUTANTS:
            if args.only and mid not in args.only:
                continue
            work = Path(tmp) / mid
            shutil.copytree(base, work)
            path = work / f
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            if text.count(old) != 1:
                results.append((mid, desc, "INVALID (pattern not found exactly once)", 0.0, ""))
                continue
            path.write_text(text.replace(old, new), encoding="utf-8")
            t0 = time.time()
            p = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *SUITES],
                               cwd=work, capture_output=True, text=True, timeout=3600)
            dt = time.time() - t0
            killer = next((ln.split(" - ")[0].replace("FAILED ", "") for ln in p.stdout.splitlines()
                           if ln.startswith("FAILED") or ln.startswith("ERROR")), "")
            status = "killed" if p.returncode != 0 else ("equivalent" if mid in EQUIVALENT else "SURVIVED")
            results.append((mid, desc, status, dt, killer))
            print(f"{mid:4s} {status:8s} {dt:6.1f}s  {desc}  <- {killer}", flush=True)
            shutil.rmtree(work, ignore_errors=True)
    killed = sum(r[2] == "killed" for r in results)
    equiv = sum(r[2] == "equivalent" for r in results)
    real = len(results) - equiv
    lines = ["# Mutation check", "",
             f"{killed}/{real} behaviour-changing planted bugs were caught by the test suite "
             f"({equiv} further mutants are equivalent: they cannot change behaviour, see notes).", "",
             "| id | planted bug | result | first failing test |", "|---|---|---|---|"]
    lines += [f"| {m} | {d} | {s} | `{k}` |" for m, d, s, _, k in results]
    if equiv:
        lines += ["", "**Equivalent mutants**", ""] + [f"- **{m}**: {EQUIVALENT[m]}" for m, _, s, _, _ in results
                                                         if s == "equivalent"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{killed}/{real} behaviour-changing mutants killed, {equiv} equivalent; report: {out}")
    return 0 if killed == real else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "docs" / "MUTATION_REPORT.md"))
    ap.add_argument("--only", nargs="*", help="run only these mutant ids")
    sys.exit(run(ap.parse_args()))
