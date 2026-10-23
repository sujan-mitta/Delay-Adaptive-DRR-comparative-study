# Testing and verification

998 automated tests in fifteen layers, a regression guard over every saved run, and mutation testing of the suite itself.

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest                                   # all tests (a few minutes; theory, property and fuzz tests dominate)
python -m pytest --cov=drrsim --cov=scripts        # with coverage
python tools/mutation_check.py                     # plants 57 bugs in temp copies (in parallel); writes docs/MUTATION_REPORT.md
python tools/regress_check.py                      # re-simulates every saved run; all metrics must match exactly
```

## Layers

| file | tests | what it establishes |
|---|---|---|
| `test_core.py` | 51 | hand-calculated toy cases (FIFO, SP, drops, metrics), accounting and FIFO-within-class for every scheduler, DRR share = quanta ratio, RL-SP shaping, CQDRR/SCRR/fuzzy/blocking helpers |
| `test_edge_cases.py` | 126 | every config validator; empty and single-packet traces for all 11 schedulers; exact buffer and partition boundaries; completion/arrival and wake/arrival ties at the same instant; no-drain mode; idle update clock; single-class traffic = FIFO for every work-conserving scheduler; tiny quanta; extreme parameters; metric edge cases (window, empty classes, strict thresholds, oscillation, max-min, Jain) |
| `test_properties.py` | 23 | Hypothesis property tests, 150 random scenarios each (random arrival times incl. exact ties, classes, sizes, buffer sizes and policies, link rates). For **all 11 schedulers**: conservation, start ≥ arrival, exact service times, one packet on the link, FIFO within class, determinism, and an **independent drop oracle** — buffer occupancy recomputed from the logs alone must explain every drop and every admission. Work conservation for all work-conserving schedulers; RL-SP departure times; quanta bounds; partition isolation |
| `test_reference.py` | 8 | **Differential testing**: FIFO, SP, DRR (random quanta) and RL-SP must agree packet-for-packet (every start time, every drop) with independent reference implementations in `tests/reference.py` (heap-based event loop, textbook "visit" DRR) on random and realistic traces |
| `test_theory.py` | 18 | **Queueing theory**: M/D/1 and M/G/1 (Pollaczek–Khinchine) mean waits within 3 %; strict priority vs **Cobham's formula** within 4 % per class; **Kleinrock's conservation law** (exact sample-path form, all work-conserving schedulers agree to 1e-9); **Little's law** (exact); bit-exact **time-scale invariance**; traffic statistics (KS test of exponential inter-arrivals, unit dispersion, chi-square of packet sizes, ON/OFF duty cycle and peak rate) |
| `test_pipeline.py` | 36 | runner (append-only, resume, failure log, duplicate keys, deterministic rows), task counts and key uniqueness for every experiment, tuning-rule ties/feasibility/fallback, damping decision rule, CI/paired-test/rank statistics, end-to-end regeneration of `RESULTS.md` and all 11 figures, integrity of the saved results |
| `test_robustness.py` | 206 | **Hostile and out-of-bound inputs**: unsorted / NaN / infinite / negative times, out-of-range classes, zero, negative and fractional sizes, mismatched arrays, NaN/infinite/absurd configs, absurd scale (refused before allocating); **fuzzing of every scheduler parameter** with NaN, ±inf, 1e±300, zero, negatives, strings, None, booleans and wrong-length lists — each input is refused with a clear `ValueError` or simulates correctly; **extreme but valid** real-world inputs for all 11 schedulers: 50× overload, near-zero load, 1 kb/s and 100 Gb/s links, a one-packet buffer, 9000-B jumbo and 1-B packets, 10 000 simultaneous arrivals, and a tie storm where every arrival lands on a completion instant |
| `test_scenarios.py` | 53 | E11 scenario features: validation, packet-size overrides, Pareto ON/OFF (mean and heavy tail), synchronised ON/OFF, load profiles (rate inside/outside, silencing, other classes untouched), link-capacity schedules (exact, half-open, non-preemptive; agreement with the reference simulator and full invariants for every scheduler on random schedules), and every scenario run for every scheduler |
| `test_aqm_imix.py` | 35 | IMIX size distributions (sizes, 7:4:1 proportions by chi-square, byte load, validation) and RED active queue management (hand-computed trace with known random draws, reduces to tail drop with unreachable thresholds, seeded pairing, early-drop effect, **exact agreement with an independent RED in the reference simulator**, invariants for all 11 schedulers) |
| `test_metamorphic.py` | 29 | Laws between runs: **causality** (removing future arrivals changes no earlier decision, all 11 schedulers), **class-relabelling symmetry** (FIFO, DRR, SCRR), **time-shift invariance** (bit-exact), **worker-count invariance** of the runner |
| `test_matrix.py` | 269 | Round-6 matrix over **all 12 scheduler variants**: smallest/largest allowed quanta and 1-byte + 9000-byte packets (each run must finish in < 5 s and keep every invariant); **a reused scheduler object behaves like a fresh one**; **no state leaks between runs**; independent oracles for any class count (**textbook DRR Algorithm 1**, strict priority, one-line FIFO); long-run DRR shares follow the quanta and SCRR shares are equal; **history is forgotten after a long idle period** (FIFO, SP, DRR, DRR-EOS, RL-SP+DRR) and SCRR's carry-over is bounded; four **combinations of scenario options** (RED + link fade, IMIX + partitioned + synchronised bursts, Pareto + flash crowd + RED, jumbo + partitioned + link boost) with every scheduler; boundaries of the public helpers; round 7 adds the hazard audit: **every parameter of every scheduler at 13 extremes (1e-300 to 1e300)** must be rejected or run correctly, link-rate and ON/OFF limits, and the engine's own overflow guard |
| `test_exhaustive.py` | 22 | **Exhaustive small-scope check, not sampling**: every trace of up to 4 packets on a grid built for exact ties (7,315 traces x 3 buffers = 21,945 cases); every scheduler keeps every invariant on every case (263,340 runs), and FIFO, SP, DRR (3 quanta settings) and RL-SP+DRR (2 rates) match the independent reference packet for packet on every case (153,615 comparisons). `EXHAUSTIVE_N=5` extends it to 33,649 traces (run once in round 7: 1,211,364 invariant runs and 706,629 reference comparisons, all correct, 11 min) |
| `test_drr_theory.py` | 64 | DRR theory for any number of classes: **every packet within the Boyer et al. delay bound** (the formula reproduces the published 146.228 µs and Table 1 values; Hypothesis-generated systems and token-bucket inputs, both DRR rules); the **DRR fairness lemma** for backlogged classes; deficits stay below the largest packet; **skip-ahead over empty passes makes identical decisions** (integer, fractional and tiny quanta) and tiny quanta no longer hang; one class = FIFO for every rule; 4096 classes; **busy periods identical** for all work-conserving rules; class relabelling; **doubling the link rate halves every time exactly** |
| `test_literature.py` | 42 | E13 published examples: any number of classes (FIFO, SP, DRR, DRR-EOS, SCRR serve everything in per-class order; 3-class schedulers refuse other counts; partitions split by the class count), **DRR-EOS vs DRR differ exactly when a packet arrives during the class's last packet**, token-bucket sources conform (greedy shape exact), **B1 trajectory delay = 119.256 µs and the paper's service order**, B2 within the published bounds, B3/B4 shares, the SCRR probe does not change decisions, a minimal case where SCRR as printed exceeds Theorem 1 |
| `test_scripts.py` | 16 | miniature end-to-end runs of `tune.py` (incl. the `--force` overwrite guard), `run_experiments.py`, `e9_control.py`, `timeseries.py`, `confirm_damping.py` (exit codes) in temporary folders; guard paths; backlog reconstruction vs brute force |

Coverage: **100 % of every `drrsim` module**; 94–99 % of the scripts (only `__main__` launch lines uncovered).
Also passes on Python 3.11 with the newest library versions.

## Mutation testing
`tools/mutation_check.py` plants 36 realistic bugs one at a time (wrong tie order, off-by-one buffer
admission, wrong partition size, bit/byte error, missing occupancy release, DRR deficit and ordering
errors, reversed priorities, RL-SP shaping errors, formula sign errors, the SCRR clock and CQDRR loop
bugs, wrong percentile/threshold/Jain/max-min/sign-flip logic, generator size/duty/sort errors, validation, tie-rule, capacity-schedule and scenario-generator errors) in
temporary copies and records whether the suite fails. Result: see `docs/MUTATION_REPORT.md`.

## Bugs found by this testing (all fixed)
| where | bug | effect on reported results |
|---|---|---|
| CQDRR `select` | fixed 192-visit cap raised an error for quanta below ~21 B | none (reported runs use a 64 B floor; 0 runs had failed) |
| SCRR (paper's Algorithm 4) | global virtual clock could move backwards when the scheduler emptied, contradicting the paper's own invariant | small; SCRR arm (ES) re-run, verdicts re-checked |
| runner manifests | two runs started in the same second overwrote each other's manifest | none (each real call ran longer than a second) |
| test suite | the first mutation run showed two gaps (wake-vs-arrival tie; flip counting across flat steps) | tests added; both mutants now killed |
| input handling | negative sizes and zero / negative DRR quanta hung forever; unsorted, NaN or negative arrival times gave silently wrong timings; other bad inputs crashed with IndexError / ZeroDivisionError; infinite loads were accepted | none (strict validation added; all 9 400 saved runs re-simulate identically) |
| RL-SP + engine | the 1e-12 s tie tolerance applied to RL-SP eligibility but not to wake-up vs. arrival ordering; in an adversarial tie storm a held packet could leave up to 1e-12 s early after an arrival had already been refused | none (unified tie rule; all 810 RL-SP runs re-simulate identically) |
| fuzzing | an RL-SP shaping rate of 1e-52 pushed departure times to 1e50 s, beyond float precision | none (rate_frac bounded to [1e-6, 1e3]) |
| audit | ON/OFF traffic with a 1 ns mean ON period looped ~10^8 times per trace (a hang); no limit on the number of periods | none (saved runs use 10-200 ms periods); refused with a clear message above 5e7 periods |
| audit | a link rate below ~1e-308 b/s made a service time overflow to infinity, which the engine uses to mean 'idle': three packets were 'on the link' at once | none (all runs use 10 Mb/s or more); link rate limited to [1, 1e15] b/s and the engine refuses any infinite completion time by itself |
| matrix | CQDRR at its smallest allowed quanta took ~94 ms per packet (a 65-s run would take hours): it has its own fixed-order round loop, which the round-5 DRR fix did not cover | none (no saved run used such quanta); same skip-ahead added; all saved runs re-simulate exactly |
| scaling | DRR added one quantum per pass even when no class could send for many passes: with the allowed minimum quantum (0.01 B) a 65-s run took ~15 min (an effective hang; adaptive schedulers can also reach small quanta through `qmin`) | none (no saved run used such quanta); fixed by skipping whole empty passes, identical decisions, all saved runs re-simulate exactly |
| runner | the CSV header was fixed by whichever result finished first, so an experiment mixing tag columns crashed mid-run (found by E12) | none for earlier runs (each used one tag set); E12 re-run, partial output archived |

## Regression guard
`tools/regress_check.py` re-simulates saved runs and requires every metric to match exactly (CSV values are read
with exact float round-tripping; pandas' default parser is not exact). `tests/test_pipeline.py` runs it on a fixed
random sample of 120 runs on every test run; the full check covers all saved runs.

## Performance
Profiling shows the time is the per-packet event loop (metrics 0.013 s and trace generation 0.008 s per
65-s run are negligible). An isolated A/B benchmark (separate processes, alternating, best of 9) puts the
current code about 6 % faster than the first published version, within ±5 % run-to-run noise; the CQDRR
loop-bound fix was made lazy so it costs nothing. Larger gains would need compiling the loop (e.g. Numba),
judged not worth the added dependency and the risk to bit-exact reproducibility for an ~8-minute pipeline.
A later round replaced two per-event branches in the engine loop with sentinels (an INF arrival after the last
packet; an INF completion time while idle). Bit-exact (all saved runs identical) but only ~2 % faster in an
isolated A/B test (within noise), confirming that the pure-Python loop is at its practical limit.
Round 5: DRR skips whole passes in which no class can send (O(classes) instead of O(passes × classes)); with
0.01 B quanta a 65-s run went from ~15 min to 0.5 s, and all saved runs are bit-exact. Decisions are identical whenever the float arithmetic is exact (whole-byte or binary-fraction quanta); with quanta such as 0.02 B one multiplication replaces many roundings, so a send can move by one round only where the exact deficit equals a packet size, and there the skip is the more accurate (round 6 found 2 such cases in 60 CQDRR runs). FIFO
now remembers the class of each queued packet in arrival order instead of scanning every queue head (O(1)
instead of O(classes) per decision; ~30 % faster at 3 classes in an interleaved A/B test (best of 5, four
alternations), and 4096-class runs no longer crawl); DRR and DR-DRR speed is unchanged within noise. The
mutation check runs mutants in parallel (`--jobs`, default a quarter of the CPUs): all 51 mutants in 16 min on a 16-CPU machine, against about an hour for the previous sequential run of 41.

## Findings about the published algorithms (not bugs in this code)
- **SCRR does not forget at idle (round 6).** Each flow's virtual clock survives an empty system of any length;
  Algorithm 4 resets nothing when the packet count reaches zero, and the algorithm exactly as printed behaves the
  same as ours. After 10 s of silence the schedule still depends on earlier traffic in 180 of 200 random cases; a
  class's served bytes differ from a fresh start by up to 3.03 maximum-size packets (74 ms at 1 Mb/s). FIFO, SP,
  DRR, DRR-EOS and RL-SP+DRR forget completely.
- **SCRR's printed Algorithm 4 exceeds its Theorems 1-2 (E13, B5)**, because the round is closed one dequeue late.

## Hunting whole classes of bugs, not single cases (round 7)
Rounds 5 and 6 each found the same kind of bug in a different place (a loop whose length grows with a parameter:
DRR, then CQDRR). Round 7 therefore audited the code by hazard class instead of by test case:
- **Every loop** (9 in the library) was checked for a bound that does not depend on parameter values. DRR,
  DRR-EOS and CQDRR are bounded by the skip-ahead; the engine by the number of events and the 5e7 update limit;
  max-min water-filling by the number of classes; trace generation by MAX_PACKETS and, new, MAX_PERIODS.
- **Every risky expression** (exp, log, powers, divisions; 7 places) was checked against the validated parameter
  ranges, then confirmed by boundary-value analysis: every parameter of every scheduler at 13 extremes (1e-300 to
  1e300) is either rejected by validation or runs correctly (no crash, hang, NaN or infinity).
- **Every special value** used as a sentinel was checked for collisions with real data (the overflow-to-INF case
  above was found this way).
- **Every small input** is checked exhaustively (test_exhaustive.py), so correctness on tiny cases is shown for all
  of them rather than for a random sample.

Audit round: two DR-DRR ablation variants joined the scheduler registry, so every test parametrised over all
variants now also covers them (998 tests); a property test checks DR-DRR's service-gap bound (Proposition 1) on random
traffic, and the regression guard covers all 15,800 runs.
