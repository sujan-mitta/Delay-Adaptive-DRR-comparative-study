# EXPERIMENT_PROTOCOL

> **Reading note.** Pre-registered sections are kept exactly as written at the time. Sections dated
> before deviation 6 call the delay-risk scheduler "SQ-DRR"; it is now named **DR-DRR** (same rule).

## Index of experiments
| ID | What | Status | Results |
|----|------|--------|---------|
| TUNE | primary-knob grid, dev seeds 1–5 | pre-registered (rule v2, deviation 2) | `results/TUNE/` |
| E1–E7 | main matrix (load, mix, burstiness, buffer, stress, sensitivity, low-load control) | planned | `results/E1`…`E7` |
| E8 | partitioned buffer (fairness only visible here) | exploratory, added after E1 | `results/E8` |
| E9 / E9C | DR-DRR damping ablation / static-DRR control | E9 pre-registered; E9C post-hoc | `results/E9`, `E9C` |
| DEVD / E1D | dev-seed check, then DR-DRR+damping at all E1 points | pre-registered | `results/DEVD`, `E1D` |
| E10 | robustness: update interval, warm-up | exploratory | `results/E10` |
| E1V | superseded CQDRR draft rule, for comparison | exploratory | `results/E1V` |
| ES | SCRR (optional ninth scheduler) + DRR-9000 comparator | pre-registered | `results/ES` |
| E11 | real-life stress scenarios (8) | pre-registered | `results/E11` |
| E12 | IMIX, RED, bulk flood, shallow+jumbo; window-length and seed-count checks | pre-registered | `results/E12` |

## Fixed defaults
- Link 10 Mb/s; buffer 125 000 B (100 ms at line rate); warm-up 5 s; measurement 60 s;
  arrivals stop at 65 s and the system is drained (pending = 0 at the end).
- Default mix (byte shares latency/video/bulk) = 0.2 / 0.4 / 0.4.
- ON/OFF: every class is an ON/OFF-modulated Poisson source, exponential ON (mean `T_on`)
  and OFF (mean `T_on·(1−d)/d`), duty `d = 0.5`, peak rate = mean rate / d.
  Burst sizes: small `T_on = 10 ms`, medium 50 ms, large 200 ms.
  *Calibration (done before any reported run, FIFO only, dev seed 1):* `d = 0.3` gave
  7 % packet loss at load 0.95 / medium (20 % for bulk), an extreme regime; `d = 0.5` gives
  0.1 % / 2 % / 5 % loss for small / medium / large at load 0.95. FIFO is scheduler-neutral
  here, so this choice cannot favour any compared variant.
- Starvation threshold `T = 100 ms`.

## Seeds and pairing
- Development seeds 1–5 (tuning only). Reported seeds 101–120 (20 per point).
- A trace depends only on (traffic config, seed); every scheduler at a point gets the
  identical trace. Each run row stores the trace's SHA-256 prefix to prove pairing.

## Tuning (dev seeds only, `scripts/tune.py`)
For RL-SP and each adaptive scheduler, a 5-value grid on its primary knob, at
ON/OFF-medium. Objective: minimise mean latency-class p95 delay at load 0.95, subject to
Jain's index ≥ 0.98 at load 1.2 (0.95 was rejected before tuning: a back-of-envelope
check showed even Strict Priority reaches ≈0.955 at 1.2, so it would not constrain). If no grid value is feasible, pick the max-Jain value.
Chosen values are frozen in `config/tuned_params.json` before any reported run.

## Matrix
| ID | Varies | Values | Fixed |
|----|--------|--------|-------|
| E1 | load | 0.4 0.6 0.8 0.9 0.95 1.05 1.2 | Poisson and ON/OFF-medium |
| E2 | mix | A 0.2/0.4/0.4, B 0.4/0.3/0.3, C 0.1/0.2/0.7 | load 0.95, ON/OFF-medium |
| E3 | burstiness | Poisson, ON/OFF small/medium/large | load 0.9 |
| E4 | buffer | 30 kB, 125 kB, 500 kB | load 0.95, ON/OFF-medium |
| E5 | stress | latency class alone = 0.8·C, video 0.2, bulk 0.3 (total 1.3) | ON/OFF-medium |
| E6 | each knob ×0.5, ×1, ×1.5 | one at a time | ON/OFF-medium, loads 0.95 and 1.2 |
| E7 | low-load control | load 0.3 | Poisson |

## Metric definitions
See `drrsim/metrics.py` docstring; summarised in README. Statistics: mean over 20 seeds,
95 % t-interval; paired differences vs DRR with Wilcoxon signed-rank p-values.

## Integrity
- Runs are appended to `results/<exp>/runs.csv`; completed keys are skipped on resume,
  never overwritten. Failures go to `results/<exp>/failures.csv`, never silently dropped.
- `results/<exp>/manifest.json` records code hash, library versions, configs, params.
- Figures and `RESULTS.md` are generated only from the saved CSVs.

## Deviation log (all on development seeds 1–5, before any reported-seed run)
1. **Burst duty 0.3 → 0.5.** See calibration note above (FIFO only).
2. **Tuning rule v1 → v2.** v1 (min latency p95 @0.95 s.t. Jain@1.2 ≥ 0.98) was
   non-binding: every grid value scored Jain ≥ 0.9997, because the latency class demands
   less than its max-min share, so prioritising it costs others delay, not throughput.
   v1 therefore drove every knob to its most aggressive grid edge. v2 minimises the
   deadline-normalised worst-class tail `W = max_i p95_i / D_i` at load 0.95 (the goal
   all delay-adaptive variants share), keeps the Jain constraint, treats values within
   1 % of the best as tied (pick closest to the spec default), and extends the grid once
   if the pick is on an edge. Full table: `results/TUNE/tuning_summary.csv`.
   *Finding carried forward:* throughput-based Jain is blind to the cost of
   prioritisation in this setting; we therefore also report per-class delay costs.
3. **E8 (partitioned buffer) added after E1.** A shared tail-drop buffer makes throughput shares scheduler-independent for
   work-conserving schedulers, so fairness differences could only show with per-class buffers; E8 was therefore added after the
   first E1 results and is exploratory. (It was recorded in the experiment index but not numbered here until the 2026-10-23
   audit, which found the numbering skipped 3.)

## E9 — SQ-DRR damping ablation (pre-registered 2026-10-22, before running)
Question (RQ3): does SQ-DRR's weight oscillation *cause* worse tail delay?
- Intervention: exponential smoothing of SQ-DRR's quanta, `Q_i ← (1−λ)Q_i + λ·Q*_i`,
  λ ∈ {1 (= tuned SQ-DRR, unchanged), 0.5, 0.25, 0.1}. All else frozen (κ = 4).
- Points: ON/OFF-medium load 0.95 and 1.2; Poisson load 1.2. Seeds 101–120, paired.
- Manipulation check: oscillation |ΔQ|/Q⁰ must fall with λ; otherwise the test is void.
- Decision rule: "oscillation hurts tails" is supported if, at ≥ 2 of 3 points, some λ < 1
  lowers mean W by ≥ 5 % vs λ = 1 with paired Wilcoxon p < 0.05 (Holm-corrected over the
  3 λ values per point). "Not supported" if no λ < 1 lowers W significantly at any point.
  Otherwise "mixed". Also reported, not used for the decision: latency- and video-class p95.
- Sanity: λ = 1 runs must be identical to the E1 SQ-DRR runs at the same points.
- *Post-hoc control E9C (exploratory, added after seeing E9):* smoothing also changed SQ-DRR's
  mean quanta (Poisson 1.2: ≈3800 B → ≈1530 B), confounding "less oscillation" with "smaller
  quanta". Control: static DRR fixed at SQ-DRR's mean quanta for each (point, λ), same seeds
  (`scripts/e9_control.py`, quanta in `results/E9C/control_quanta.json`).

## E1D — "SQ-DRR+damping" variant (pre-registered 2026-10-22, before running)
λ = 0.5 was suggested by E9, which used reported seeds; it must be confirmed on development
seeds before any reported-seed run.
- **Dev check (`DEVD`)**: SQ-DRR λ = 1 vs λ = 0.5 (κ = 4 fixed) at all 14 E1 points, seeds 1–5.
- **Confirm λ = 0.5 iff** (a) at no E1 point is its dev-mean W worse than λ = 1 by more than 5 %, and
  (b) its dev-mean W is lower than λ = 1 at ≥ half of the points with load ≥ 0.9 (≥ 4 of 8).
  If not confirmed, the variant is **not** run on reported seeds and the outcome is reported.
- **If confirmed**: run "SQ-DRR+damping" (λ = 0.5, otherwise identical to SQ-DRR) at all 14 E1
  points, seeds 101–120, in `results/E1D/` (kept separate from E1 so the 8-scheduler tables are
  unchanged), paired with E1 by trace digest. Report vs SQ-DRR and DRR: W, per-class p95,
  oscillation, paired Wilcoxon (Holm over the 14 points). No other parameter is re-tuned.

## Deviation 4 — RL-SP+DRR corrected to its paper (2026-10-22)
The full text of arXiv:2002.07027 (Algorithm 1) contradicted the draft rule: the high-priority
class is shaped by per-packet departure times (not a token bucket), and non-conforming
high-priority packets are held rather than served by DRR (DRR covers low-priority classes only).
The implementation was corrected (docs/ALGORITHM_SPEC.md §4), its E6 knob list became
`rate_frac` only (no bucket), tuning was re-run for it on dev seeds 1–5 (`tune.py --force`;
other schedulers' choices must reproduce unchanged), and **all** experiments were re-run.
Results before this change are archived under `results/_superseded_rlsp_draft/`.

## Additional checks (added 2026-10-22; exploratory, not part of the original matrix)
- **E8 + Poisson 1.2, partitioned buffer**: tests the explanation for the E1 anomaly where DRR's
  bulk p95 *falls* from load 1.05 to 1.2 under a shared buffer (smaller video packets capture
  the shared buffer: free space of 1000–1499 B admits video, not bulk).
- **E10 robustness**: (a) adaptive update interval Δ ∈ {5, 10, 20, 50} ms for the four adaptive
  schedulers, ON/OFF-medium loads 0.95 and 1.2; (b) warm-up 20 s instead of 5 s (same 60 s
  window) for all 8 schedulers at ON/OFF 1.2 and Poisson 1.2. Rankings are "robust" if the
  order of mean W among the 8 is unchanged and no scheduler's W moves by more than its 95 % CI
  plus 10 %.

## Deviation 5 — CQDRR replaced by the paper's rule (2026-10-22)
The open-access full text (Electronics Letters e70418) showed the draft CQDRR rule was not the
paper's: the published quantum is EXP-PF-style (delay term + α-fair rate term + queue-length ×
M/M/1/K blocking term), differs per traffic type, and its delay term is inert with one TT class.
"CQDRR" in the main 8 is now the paper rule (ALGORITHM_SPEC §6); the draft is kept as the
labelled variant "CQDRR-draft" (E1 points only, `results/E1V/`, β = 2 as tuned before).
CQDRR's knob grid became `scale` (tuning re-run on dev seeds, `--force`), E6 knobs became
scale, w, rbar_gain, rate_ewma. All experiments re-run; previous results archived in
`results/_superseded_cqdrr_draft/`.

## Phase-5 paper-trend reproduction (pre-registered 2026-10-22, before the re-run)
Only papers whose full text we could read can be checked.
- **CQDRR** (paper Fig. 3: lower average end-to-end delay than DRR, larger gains at high load).
  *Reproduced* if, at the 8 E1 points with load ≥ 0.9 (Poisson and ON/OFF), CQDRR's **mean**
  queueing delay is below DRR's for both the latency (TT) and video (AVB) classes, paired
  Wilcoxon p < 0.05, at ≥ 6 of 8 points. Bulk (BE) is reported but not required: on one
  work-conserving link the conservation law forbids lowering every class's mean delay at once.
- **RL-SP+DRR** (paper: prioritises high-priority traffic like strict priority while keeping
  low-priority traffic served). *Reproduced* if, at every E1 point with load ≥ 0.6, its
  latency-class mean delay is below FIFO's (paired, p < 0.05), and it has zero video/bulk
  starvation episodes in E1–E8.
- SQ-DRR, FuzzyDRR, RevenueDRR: **not checkable** (papers not obtainable); intent checks only.

## Deviation 6 — "SQ-DRR" renamed "DR-DRR", our own design (2026-10-22)
No paper matching the plan's citation (Kim & Park, J. High Speed Networks, 2004) could be found by
us or by the author. The rule is unchanged; only its name and attribution change (DR-DRR = delay-risk
DRR, our own design; its damped variant is "DR-DRR+damping"). Everything was re-run under the new
name; the metrics must be bit-identical to the archived runs (checked). FuzzyDRR and RevenueDRR full
texts could not be obtained either; they stay as clearly labelled inspired-by designs.

## ES — SCRR (optional ninth scheduler), pre-registered 2026-10-22 before running
SCRR = Self-Clocked Round-Robin with enhancements, Sharafzadeh et al., NSDI 2025, Appendix A
Algorithms 3–4 (ALGORITHM_SPEC §9). Parameter-free, so no tuning. Each class is one sub-queue.
Run as a separate arm (`results/ES/`), paired by trace with the source experiments: all 14 E1
points, E3 (4 points), E5 stress, E8 (partitioned 0.95, 1.2, stress). The paper's comparator
"DRR with a large quantum" is added as DRR with quanta 9000 B at the E1 points ("|q9000" labels).
Paper-trend checks:
- **(a) latency** — paper: ~71 % better application latency than DRR with a large quantum.
  *Reproduced* if SCRR's latency-class mean delay is below DRR-9000's (paired Wilcoxon p < 0.05)
  at ≥ 6 of the 8 E1 points with load ≥ 0.9.
- **(b) fairness** — paper: flow fairness on par with DRR. *Reproduced* if |Jain(SCRR) − Jain(DRR)|
  ≤ 0.01 at all three E8 partitioned points (shared-buffer Jain is uninformative, see E8).
- Reported, not used for a verdict: W, per-class p95, rank among the 8 + SCRR.

## Deviation 7 — fixes found by the extended test suite (2026-10-22)
- **SCRR**: Algorithm 4's idle-reset could move the global virtual clock backwards, contradicting the
  paper's stated invariant; every clock update is now `max(old, new)` (ALGORITHM_SPEC §9). The SCRR arm
  `ES` was re-run; earlier ES runs are archived in `results/_superseded_scrr_clock/`.
- **CQDRR**: the select loop's fixed iteration cap was replaced by an exact, lazily computed bound.
  Behaviour is unchanged for every reported run (none came near the old cap).
- **Runner**: manifest file names now carry microseconds and a collision counter (never overwritten).
All other results were re-produced from a clean copy and compared bit-for-bit (see docs/TESTING.md).

## E11 — real-life stress scenarios (pre-registered 2026-10-22, before any code for them exists)
Purpose: test whether the main findings survive conditions the model did not cover. All 8 compared
schedulers + SCRR, tuned parameters frozen (no re-tuning), seeds 101–120, ON/OFF-medium unless noted,
shared 125 kB buffer, 60 s window after 5 s warm-up.

| id | scenario | change vs. the base model | base load |
|----|----------|---------------------------|-----------|
| S1 | jumbo | bulk packets 9000 B (data-centre jumbo frames); quanta unchanged | 0.95 |
| S2 | tiny | latency packets 64 B (VoIP/ACK floods), same byte load | 0.95 |
| S3 | heavy-tail | ON and OFF periods Pareto (shape 1.5, same means): self-similar traffic | 0.95 |
| S4 | sync | one shared ON/OFF process for all classes (correlated bursts) | 0.95 |
| S5 | flash-crowd | video arrival rate ×3 during t ∈ [25, 35) s | 0.8 |
| S6 | link-fade | link capacity ×0.4 during t ∈ [25, 35) s (schedulers still assume nominal C) | 0.8 |
| S7 | abuse | latency class carries 1500-B packets at 0.6·C (mislabelled bulk); video 0.2, bulk 0.3 | 1.1 |
| S8 | ramp | load ×{0.4, 0.6, 0.8, 1.0, 1.2, 1.3}/0.8 in six 10-s steps over the window | 0.8 |

Findings re-tested, with the criterion for "holds" fixed now:
- **F1** SP gives the lowest mean latency-class p95 of all 9 schedulers.
- **F2** Only SP and CQDRR ever starve a class (> 100 ms backlogged without service): every other
  scheduler has 0 episodes.
- **F3** No single best non-SP scheduler: at least two different schedulers are best (mean W, SP excluded)
  across the 8 scenarios.
- **F4** Under the shared buffer, per-class drop rates differ across schedulers by ≤ 1 percentage point.
- **F5** DR-DRR has lower mean W than DRR (paired Wilcoxon p < 0.05).
Reported per scenario and in total (number of scenarios in which each finding holds). Also reported, without
a verdict: each scheduler's rank by W per scenario and its worst rank (robustness).

## Deviation 8 — input hardening, unified tie rule, E11 results (2026-10-22)
- Strict validation of traces, configurations and every scheduler parameter (hostile inputs used to hang,
  give silently wrong timings, or crash with unclear errors; see docs/TESTING.md).
- One tie rule for the whole engine: events within 1e-12 s are simultaneous, ordered completion, wake-up,
  update, arrival. Previously RL-SP's eligibility used this tolerance but wake-up vs. arrival ordering did not;
  the inconsistency only appeared in an adversarial tie storm.
- New scenario options (size overrides, Pareto ON/OFF, synchronised ON/OFF, load profiles, link-capacity
  schedule) are off by default.
- **Effect on reported results: none.** All 9 400 saved runs were re-simulated after these changes and match
  exactly; all 720 saved traffic traces regenerate with identical digests.
- E11 ran as pre-registered. The wording of F2 ("only SP and CQDRR ever starve") omitted FIFO, whose long
  FIFO waits also count as starvation episodes in the main study; F2 is reported as registered (fails), with
  the computed explanation beside it, not re-worded.

## E12 — more real-life conditions and checks of the method (pre-registered 2026-10-22, before any code for it)
Same setup as E11 (8 schedulers + SCRR, frozen parameters, seeds 101–120, ON/OFF-medium, 125 kB shared buffer).

| id | scenario | change vs. the base model | load |
|----|----------|---------------------------|------|
| R1 | imix | video and bulk use the classic Internet mix by packet count 7:4:1 of 40 / 576 / 1500 B | 0.95 |
| R2 | red | RED active queue management on the shared buffer (byte mode, min 25 kB, max 75 kB, max_p 0.1, w 0.002) | 0.95 |
| R3 | bulk-flood | bulk class alone offers 3·C (a flood on the lowest class); latency 0.2, video 0.4 | 3.6 |
| R4 | shallow-jumbo | 30 kB buffer and 9000-B bulk frames | 0.95 |

Findings re-tested (same criteria as E11): F1, F3, F5 as before; F2' = no DRR-family scheduler (DRR, RL-SP+DRR,
DR-DRR, FuzzyDRR, RevenueDRR, SCRR) ever starves a class; F4 is reported only (RED changes admission).

Checks of the method (no scenario change):
- **M1 window length**: ON/OFF loads 0.95 and 1.2 with a 600 s window (10×), seeds 101–110. Passes if the order of
  the 8 schedulers by mean W is identical to E1's and every scheduler's W is within 10 % of E1's.
- **M2 seed count**: ON/OFF 0.95 with seeds 101–200 (100 seeds). Passes if at least 7 of the 8 schedulers' 100-seed
  mean W lies inside E1's 20-seed 95 % confidence interval, and the order of the 8 by mean W is unchanged.
  *(Amended within minutes of registration, before any E12 code or data existed: "every scheduler" would fail by
  chance about one time in three even if all intervals were correct, since each 95 % interval misses 5 % of the time.)*

## Deviation 9 — round 3 (2026-10-23)
- The first E12 run stopped after 720 rows because of a runner bug (CSV header fixed by the first finished row;
  E12 mixes tag columns). The runner was fixed and tested; the partial output is archived in
  `results/_aborted_e12_header/`, and E12 was re-run in full. No earlier experiment was affected.
- M2's pass rule was amended before any E12 code or data existed (see E12 section).
- M1 fails as registered at load 1.2: DRR and FuzzyDRR (6th and 7th) swap places with overlapping confidence
  intervals; all other positions are unchanged and no mean W moves by more than 5.2 %. Reported as a fail with the
  computed explanation; not re-worded.
- New options (IMIX size distributions, RED) are off by default; all saved runs re-simulate exactly.


## E13 — benchmarks against published examples (pre-registered 2026-10-23, before any code for them)
Each benchmark re-creates a setup published in a paper, runs it in our simulator, and compares with the paper.

| id | source (full text read) | published setup | what we compare | pass criterion |
|----|-------------------------|-----------------|-----------------|----------------|
| B1 | Tabatabaee & Le Boudec, IEEE/ACM ToN 2022 (arXiv 2106.01034), Sec. 3 | DRR, 3 flows, l = 100 B, c = 100 Mb/s, quanta 100l / 5l / 10l, the paper's exact trajectory | delay of the "packet of interest"; published 119.256 µs; Boyer et al. bound 146.228 µs; Soni et al. bound 112.172 µs | our delay = 119.256 µs (± 0.01); below the Boyer bound; above Soni's (reproducing its invalidity) |
| B2 | same paper, Sec. 6.1 / Table 1 (Bouillard's single-server example) | DRR, 4 classes, c = 5 Gb/s, quantum 16 000 bit each, packets {3.04, 12, 12, 12} kb, token buckets b = {42.56, 2160, 3240, 7200} kb, r = {8.521, 180, 162, 180} Mb/s | worst delay found by simulation (greedy and randomised token-bucket-constrained arrivals) vs. published bounds {44.51 µs, 1.32 ms, 1.81 ms, 2.72 ms} (best bounds, Thm 5) | no class ever exceeds its published bound; tightness (observed / bound) reported |
| B3 | Shreedhar & Varghese, IEEE/ACM ToN 1996, Sec. 5.2–5.3 | 20 flows, Poisson 10 pkt/s, sizes uniform up to 4500 bit; flow 10 ill-behaved at 30 pkt/s; random, constant (100 bit) and bimodal (100 / 4500 bit) sizes | per-flow bandwidth, DRR vs FCFS | DRR: the ill-behaved flow gets within 10 % of the mean of the others; FCFS: it gets ≥ 2× the mean of the others; DRR fairness holds for all three size models. Link rate is not given in the text: we use 400 kb/s (offered 495 kb/s, congested) and say so |
| B4 | Tokmakov et al., IEEE CloudNet 2019 (arXiv 2002.07027), PROACTIVE | 10 Mb/s link, UDP saturating, high priority shaped to 60 %, medium and low share the rest by DRR; high priority switched on after 90 s for 90 s | per-class throughput with and without high priority; published: high priority 5.3 Mb/s | high = 6.0 Mb/s ± 1 % (the configured share; the published 5.3 includes testbed overhead), medium ≈ low ≈ 2.0 Mb/s ± 5 % while high is on, ≈ 5.0 each while off |
| B5 | Sharafzadeh et al., NSDI 2025, Theorems 1–2 | SCRR, backlogged flows | (i) global-clock advance per round ≤ M (max packet length); (ii) bytes dequeued from one sub-queue in one visit ≤ (r_max + 1)·M = 2M (unweighted) | never violated, over randomised traces including jumbo/tiny mixes |
| — | Mukherjee et al., WiOpt 2025, Table II | not reproducible: units inconsistent (a 10 Kb burst at 40 Kb/s cannot have 0.2 ms delay) and the simulated arrival process is not stated | — | reported as not reproducible |
B2 and B3 need more than three traffic classes: FIFO, SP, DRR and SCRR are generalised to any number of
classes (default 3, bit-exact with all saved runs); the adaptive schedulers stay three-class.

### E13 — amendments and notes (written before the final run; development runs disclosed)
- Run sizes, fixed before the final run: B1 2000 random inputs; B2 3000 inputs (500 × {greedy, random offsets,
  random silences} × 2 RNG streams); B3 and B4 seeds 101–120; B5 1000 traces per case.
- B3 buffer (not stated in the registration): unlimited buffer for the registered check, so that the drop policy
  cannot matter (the paper used McKenney's buffer stealing, which we do not model). A 140 kB shared and a
  140 kB partitioned buffer are reported as descriptive sensitivity. Packet sizes in bytes: 4500 bit → 562 B,
  100 bit → 13 B; DRR quantum 562 B. SCRR is added to B3 as a descriptive extra.
- B4: per-class (partitioned) buffers, as bmv2 priority queues have; FIFO is the paper's "NO", and unshaped SP is
  shown for contrast (the paper's STRICT is rate-limited, so it is not the same thing).
- Two DRR rules are reported in B1 and B2: DRR-EOS (end-of-service rule of the network-calculus model the bounds
  are derived for) and our DRR (dequeue-time rule, as Linux `sch_drr`). B1's registered criterion applies to both.
- Development runs: while building the benchmarks, single-seed (101) and small trial runs of B1–B5 were made to
  check the code. They showed the B5 violation. The diagnostic SCRR variant that closes a round before the next
  dequeue (`SCRRRoundFirst`) was written **after** seeing it; its rows are descriptive, not registered.
- New options in the engine: any number of classes for FIFO, SP, DRR, DRR-EOS and SCRR (default 3; all saved runs
  re-simulate exactly); the adaptive schedulers and RL-SP+DRR refuse any other number.
- After the first full run (`results/E13/20261023-012612`, kept): with constant 13 B packets the offered load is
  ~23 kb/s on the 400 kb/s link, so nothing is congested and every flow (including the ill-behaved one) gets what it
  sends; that case cannot test fairness. A **post-hoc** variant scales the link to the same overload as with random
  sizes (offered / link = 1.24) for the constant and bimodal cases. Its rows are labelled "post hoc" and are
  descriptive. Nothing else changed between the two runs.

## E14 — DR-DRR ablation (pre-registered 2026-10-23, before any code for the variants)
Question: does each part of DR-DRR's risk estimate d_i = max(H_i, 8 B_i / (C phi_i)) add value?
- Variants (same bounds Q0 = 1500 B, M = 8, theta = 0.5): **DR-DRR-backlog** (d_i = 8 B_i / (C phi_i) only) and
  **DR-DRR-hol** (d_i = H_i only). Their kappa is tuned exactly like DR-DRR's (same grid, same rule, dev seeds 1-5,
  extended once at an edge) so that no variant is handicapped by DR-DRR's tuning.
- Runs: all 14 E1 points, seeds 101-120, paired with the saved DRR, DR-DRR and DR-DRR+damping runs (same traces).
- Statistic: per point, paired difference W(variant) - W(DR-DRR) over 20 seeds; paired Wilcoxon, Holm-corrected over
  the 14 points of each variant; effect size = mean paired difference with a 95 % t-interval.
- Verdict per variant V: "the full rule adds value over V" if DR-DRR is significantly better at >= 7 points and
  significantly worse at <= 2; "V suffices" if DR-DRR is significantly better at <= 2 points; otherwise "mixed".
- Also reported (descriptive): starvation episodes, the largest service gap, and quantum oscillation of each variant.

## E15 — held-out seeds (pre-registered 2026-10-23)
Question: do the headline results hold on seeds never seen during development or reporting?
- Runs: all 8 schedulers at the 14 E1 points with fresh seeds 201-220 (tuned parameters unchanged).
- H1: SP has the lowest latency-class p95 at 14/14 points.
- H2: at >= 11 of 14 points the best non-SP scheduler on mean W is the same as with seeds 101-120.
- H3: for each scheduler, the held-out mean W lies inside the 101-120 95 % interval at >= 11 of 14 points.

## Proposition — bounded service gap of DR-DRR (derived 2026-10-23, then checked on saved runs)
With base quantum Q0 >= the largest packet, quanta clipped to [Q0, M Q0], K classes and link rate C, the head packet of
a backlogged class waits at most sum over the other classes of (M Q0 + Lmax_j - 1) * 8 / C before service (21.6 ms for
the study's settings). Checked against all 1,680 saved DR-DRR and DR-DRR+damping runs at 10 Mb/s: 0 violations,
largest gap 89-95 % of the bound (M = 4, 8, 12).

## E16 — real Linux kernel schedulers (pre-registered 2026-10-23, before any testbed code)
Question: does the simulator predict what the real Linux kernel's schedulers do on the same packets?
- Testbed: WSL2, Linux 6.18; two network namespaces joined by a veth pair. Egress of the sender: `tbf` at 10 Mb/s
  (smallest feasible burst) with a child qdisc: `pfifo`-style byte FIFO (FIFO), `prio` with 3 bands (SP), or `drr` with
  3 classes and quantum 1500 B (DRR); per-class byte limits equal to the simulator's partitioned buffer (125 kB / 3) for
  SP and DRR, and 125 kB for FIFO. Classes are selected by UDP destination port. Frame size = the simulator's packet size.
- Traffic: the simulator's own traces (ON/OFF 0.8, ON/OFF 0.95, Poisson 0.9; 10 s each; seeds 101-103), sent with their
  exact inter-arrival times from a user-space sender; each packet carries its scheduled send time; the receiver records
  the arrival time on the same clock.
- Comparison with the simulator on the same trace (partitioned buffer for SP and DRR, shared for FIFO):
  K1: per scheduler and class, the kernel's mean delay is within 10 % + 0.5 ms of the simulator's;
  K2: the order of the three schedulers by latency-class p95 is the same in kernel and simulator at every point.
  Also reported: per-class p95 and drop rates, and how often kernel and simulator send the same class next.
- Known differences, stated in advance: kernel timers and the user-space sender add jitter of tens of microseconds;
  tbf releases packets in bursts of up to its bucket; Linux counts frame bytes, the simulator counts packet bytes.

## E17 — real backbone traffic (pre-registered 2026-10-23, before downloading)
Question: do the main findings hold for real packet arrivals and sizes?
- Data: the first ~200 MB of the public MAWI trace samplepoint-F 2024-01-01 14:00 (anonymized headers, WIDE project).
  Packets are mapped to classes by protocol and port before any scheduling result is seen: latency = DNS (53), NTP (123),
  SIP (5060-5061), RTP/RTCP-like UDP 16384-32767, and ICMP; video = UDP 443 (QUIC); bulk = everything else.
- Replay: the trace is split into 10 consecutive windows (one per "seed"); inter-arrival times are scaled so that the
  offered load on the 10 Mb/s link is 0.8, 0.95 or 1.2; real packet sizes are kept (capped at 1500 B). All 8 schedulers
  and SCRR, shared 125 kB buffer, delay targets as in the main study.
- R1: SP has the lowest latency-class p95 at all three loads. R2: DR-DRR beats DRR on mean W at all three loads (paired
  over windows). R3: no DRR-family scheduler starves a class. The best non-SP scheduler is reported descriptively.

### E16 / E17 — notes written after running (deviations and caveats)
- E16: the first attempt stopped in testbed setup (a filter was attached to the classless FIFO) before any packet was
  sent; its folder, which held only one generated trace, was removed and the run repeated in full. Results: K1 fails as
  registered (18/27 cells), K2 holds (3/3). Measured cause of K1: per-packet transmission times are exact, but timer
  stalls in the WSL2 virtual machine lower the aggregate service rate of tbf to 9.64-9.95 Mb/s; tbf's 1600 B bucket also
  lets a small packet leave right after a large one, so SP's latency class waits less than in the non-preemptive model.
  A post-hoc re-simulation at a per-run measured rate was tried and discarded: the rate estimate is not valid for SP.
- E17: the download stopped at 151.7 MB (connection reset by the server) instead of ~200 MB; the 1,000,000 packets
  needed were in the prefix (sha256 in results/E17/parse_meta.json). The pre-registered port mapping puts 42.5 % of
  packets (12.7 % of bytes) into the latency class, because UDP ports 16384-32767 are also used by non-real-time flows;
  the mapping was not changed after seeing the data. The derived arrays are not redistributed (regenerate them with
  `scripts/e17_realtrace.py parse`). Results: R1, R2, R3 hold at 3/3 loads; the best non-SP scheduler is CQDRR at all
  three loads (on synthetic traffic it is usually DR-DRR).

## E18 — is the ranking an artefact of the score W? (pre-registered 2026-10-23, before computing any new metric)
W uses the same per-class delay targets that DR-DRR uses internally, which could favour delay-target-aware schedulers.
We re-score the saved runs (E1-E8, E11, E12, E17; no new simulation) with three scores that do not use our targets:
- S1 regret: for each run, max over classes of p99_i(scheduler) / min over schedulers of p99_i at that point and seed
  (how far the worst class is from the best any scheduler achieved for it);
- S2 Borda: mean over classes of the scheduler's rank by p99_i at that point (1 = best), averaged over seeds;
- S3 alternative targets: W recomputed with D = (20, 100, 1000) ms and with equal targets D = (50, 50, 50) ms.
Verdict: "DR-DRR's lead is not an artefact of W" if, among non-SP schedulers, DR-DRR is the most frequent winner under
at least 3 of the 4 scores (S1, S2, S3a, S3b) across the same 29 operating points used for W; "artefact" if it is the
most frequent winner under at most 1; otherwise "partly".

## E19 — does a tuned static DRR match DR-DRR? (pre-registered 2026-10-23)
If fixed, well-chosen quanta did as well, adaptation would not be needed. Static DRR quanta (Q_lat, Q_vid) are tuned on
dev seeds 1-5 by W with the main tuning rule (ON/OFF loads 0.95 and 1.2), grid {1500, 3000, 6000, 12000}^2 with
Q_blk = 1500; the chosen pair is run at the 14 E1 points with seeds 101-120 (paired with E1).
Verdict: "adaptation adds value" if DR-DRR has lower W than tuned static DRR at >= 8 of 14 points (paired Wilcoxon,
Holm over 14) and higher at <= 2; "static suffices" if DR-DRR is better at <= 2; otherwise "mixed".

## E16b — kernel check at 1 Mb/s (pre-registered 2026-10-23)
E16's absolute delays were limited by virtual-machine timer stalls of the order of 0.1 ms against 0.16-1.2 ms packet
times. At 1 Mb/s packet times are 10x longer, so the same stalls matter 10x less. Same testbed with tbf at 1 Mb/s; the
E16 traces (first 3 s) with every time multiplied by 10. Prediction from the simulator's exact scale invariance (FIFO,
SP, DRR): kernel waiting times = 10 x the simulator's at 10 Mb/s. K1b: kernel mean within 10 % + 5 ms (the 0.5 ms
tolerance scaled by 10) of the prediction in >= 24 of 27 cells; K2b: same scheduler order by latency-class p95 at 3/3.

## E17b — sensitivity to the real-traffic class mapping (pre-registered 2026-10-23)
Two alternative mappings, applied to the same MAWI windows: strict (latency = DNS, NTP, ICMP only; video = UDP 443;
bulk = rest) and size-based (latency = any packet <= 300 B; video = UDP 443 > 300 B; bulk = rest). R1-R3 of E17 are
re-evaluated under each; verdict "mapping-robust" if R1 and R2 hold at 3/3 loads under both.

### E16b / E17b / E18 / E19 — results and what they changed (written after running)
- **E16b holds**: K1b 26/27 cells (criterion >= 24; the one miss is Poisson 0.9 FIFO latency, kernel 24.1 ms vs predicted
  32.9 ms), K2b 3/3. At 1 Mb/s the kernel agrees with the simulator's exact-scaling prediction, which supports the E16
  diagnosis (virtual-machine timer noise at 10 Mb/s, not a model error).
- **E17b holds**: R1 and R2 at 3/3 loads under both alternative class mappings; CQDRR stays the best non-SP scheduler.
  The derived MAWI arrays were re-parsed to keep protocol and ports (the registered classes are unchanged; E17's numbers are
  identical apart from the two wall-clock columns).
- **E18 verdict "partly an artefact of W"** (DR-DRR most frequent winner under 2 of 4 scores). Under regret (S1) RevenueDRR
  wins 13 of 29 points; under equal targets (S3b) FIFO wins 28 of 29, which is expected because equal targets reward
  equalising delays across classes. The paper's claim about DR-DRR was weakened accordingly.
- **E19 verdict "mixed"**: a static DRR with quanta (6000, 6000, 1500), tuned on dev seeds like DR-DRR, has lower W than
  DR-DRR at 8 of 14 points (all of the overloaded ones, by up to 0.74) and higher at 6 (all the lightly loaded ones). The
  paper no longer presents adaptation as necessary.

## E19H — static DRR on fresh seeds (pre-registered 2026-10-23, before running)
E19 evaluated the tuned static quanta on the reporting seeds 101-120 (the same seeds as DR-DRR). To remove any doubt that the
comparison depends on those seeds, the same quanta (no retuning; config/tuned_static_drr.json) are run at the 14 E1 points on
the fresh seeds 201-220 and compared, paired by trace, with DR-DRR's E15 runs on the same seeds. Same verdict rule as E19:
"adaptation adds value" if DR-DRR has lower W at >= 8 of 14 points (Holm-corrected paired Wilcoxon) and higher at <= 2;
"static suffices" if DR-DRR is better at <= 2; otherwise "mixed". Prediction written before running: the E19 pattern (static
better at the heavy and bursty points, DR-DRR better at light load) repeats, i.e. the verdict is again "mixed".
Tuning budgets, for the record: DR-DRR's kappa was chosen among 5 grid values (no edge extension was needed); the static
quanta among 16 settings (4 x 4 grid), with the same objective, constraint, tie rule and development seeds. The static search was
therefore larger, not smaller.

## E17c — a second, independent backbone trace (pre-registered 2026-10-23, before downloading)
E17 used one 6.7-second prefix of one MAWI trace. To check that its conclusions are not specific to it, the same procedure is
repeated on the first ~150 MB of a trace from another year: https://mawi.wide.ad.jp/mawi/samplepoint-F/2022/202201011400.pcap.gz
(samplepoint F, 2022-01-01 14:00). Nothing is changed: the registered port-to-class mapping of E17, 10 windows of 100,000
packets, loads 0.8 / 0.95 / 1.2, the same schedulers, tuned parameters and delay targets.
- R1c: SP has the lowest latency-class p95 at 3/3 loads. R2c: DR-DRR beats DRR on mean W (paired over windows, p < 0.05) at 3/3
  loads. R3c: no scheduler other than SP, CQDRR and FIFO starves a class at any load.
- Replication question (descriptive): is the best non-SP scheduler by mean W the same as in E17 (CQDRR)?
- If the prefix holds fewer than 1,000,000 IPv4/IPv6 packets, the window size is reduced to what it holds and this is reported.

### E17c outcome (2026-10-23)
- Deviation 4: 42 MB of the trace (not 150 MB) already held the required 1,000,000 IPv4/IPv6 packets (27.5 s; the 2022 file keeps
  headers only), so the download was stopped there. The prefix is exactly 41,943,040 bytes; sha256 in `results/E17c/parse_meta.json`.
- This trace is 97.3 % bulk by bytes (latency 2.5 %, video 0.2 %). R1c holds (3/3). R3c holds (3/3). R2c fails (0/3), but not
  because DR-DRR loses: W is set by the bulk class (p95 about 100 ms against a 500 ms target), and DRR, DR-DRR, CQDRR, FuzzyDRR,
  RL-SP+DRR, SP and SCRR tie to within 0.0001 in mean W. The replication question about the best non-SP scheduler therefore has no answer
  on W for this trace. Reported as is; it is a weaker check than E17 because it barely exercises the latency and video classes.


## E20 — Modified DRR baselines (pre-registered 2026-10-23, before any code for them)
Why: a related-work check found that router vendors ship Modified DRR (MDRR), analysed by Lenzini, Mingozzi and Stea, and that
our comparison had no such baseline. We implement it from the vendor description as we understand it; we have not read the
analysis papers in full, so these are **reconstructions**.
- **MDRR-SP** (strict-priority low-latency mode): class 0 (latency) is a low-latency queue served first whenever it is
  backlogged; classes 1 and 2 share the link by DRR with quanta 1500 B. The queue is not rate-limited (so it can starve the others,
  as SP can).
- **MDRR-ALT** (alternate-priority mode): packets alternate between the low-latency queue and the DRR classes: after one
  low-latency packet, one packet from the DRR classes goes next if any is backlogged, and vice versa. If only one side is
  backlogged it is served.
- Neither has a tunable parameter (quanta 1500 B for classes 1-2, as DRR), so there is no tuning step.
- Not implemented: Proportional Nested DRR (Shiravi, Kim, Min). We know it only from its abstract, which is too little to
  reconstruct it faithfully. Listed as a gap.
- Runs: the 14 E1 points, seeds 101-120, paired with the saved SP, DRR and DR-DRR runs (same traces).
- Statistic: per point, paired difference in W, MDRR variant minus DR-DRR; paired Wilcoxon, Holm-corrected over the 14 points
  for each variant.
- Verdict per variant V (same rule shape as E14): "V beats DR-DRR" if V is significantly better at >= 7 points and DR-DRR at
  <= 2; "DR-DRR beats V" if DR-DRR is significantly better at >= 7 and V at <= 2; otherwise "mixed".
- M1: MDRR-SP's latency-class p95 is within 10 % of SP's at >= 12 of 14 points (both serve that class first).
- M2: MDRR-SP starves no class more than SP does (starvation episodes, summed over runs, not above SP's).
- M3: MDRR-ALT's latency-class p95 is above MDRR-SP's at >= 12 of 14 points (it gives up some priority).
- Also reported (descriptive): per-class p95, starvation episodes, largest service gap.

### E20 outcome and E20b (post-hoc, added 2026-10-23 after seeing E20)
- E20 verdicts (rules above): MDRR-SP vs DR-DRR: DR-DRR better at 10 points, MDRR-SP at 4 -> "DR-DRR beats MDRR-SP" is not met
  (needs >= 7 and <= 2), so **mixed**. MDRR-ALT vs DR-DRR: DR-DRR better at 13, MDRR-ALT at 1 -> **DR-DRR beats MDRR-ALT**.
  M1 holds (14/14), M2 holds (no starvation at all), M3 holds (14/14).
- MDRR-ALT's latency tails are hundreds of milliseconds under load. The cause is our packet-level reading: alternating single
  packets gives 200-byte latency packets about 12 % of the bytes while the class offers 20 %, so it overloads. A vendor
  implementation alternates turns, not packets, so this reading is probably unfair to MDRR. We therefore added **MDRR-ALT-V**
  (low-latency queue takes one DRR turn, quantum 1500 B, between turns of the other classes) and ran it on the same 14 points
  and seeds as **E20b**. It is post-hoc: it was written after seeing E20, it has no pre-registered criteria, and it is not checked
  against the independent reference simulator (unit tests and the common invariants only). Its numbers are descriptive.

## E21 — other link rates (pre-registered 2026-10-24, before any run)
Why: every main result is at 10 Mb/s; a reviewer can fairly ask whether the conclusions are specific to that rate. FIFO, SP and
DRR are exactly scale invariant (see the paper), but the adaptive schemes are not: their 10 ms update interval and their tuned
constants do not scale.
- Rates: 1 Mb/s (60 s after a 5 s warm-up, buffer 12.5 kB) and 100 Mb/s (10 s after a 1 s warm-up, buffer 1.25 MB). The buffer is
  scaled with the rate so that it drains in the same 100 ms; packet sizes, delay targets, update interval (10 ms) and all
  tuned parameters stay as at 10 Mb/s (no retuning). The shorter 100 Mb/s run is a deviation forced by run time (about 100,000 packets
  per class-second at that rate).
- Points: ON/OFF 0.95, ON/OFF 1.2, Poisson 1.2. Seeds 101-110. The eight compared schedulers.
- S1: SP has the lowest latency-class p95 at 3/3 points at each rate.
- S2: DR-DRR beats DRR on W (paired Wilcoxon, Holm over the 3 points of a rate, p < 0.05, DR-DRR lower) at >= 2/3 points at each rate.
- S3: no scheduler other than SP, CQDRR and FIFO starves a class at either rate.
- Descriptive: the best non-SP scheduler on mean W at each point.

### E21 outcome (2026-10-24)
- S1 holds at both rates (SP lowest latency p95 at 3/3 points). S2 holds at 100 Mb/s (3/3, Holm p = 0.006) and **fails at 1 Mb/s
  (0/3: DR-DRR is worse than DRR at all three points)**. S3 holds at 100 Mb/s and **fails at 1 Mb/s**: DR-DRR starved classes in 3,949
  episodes, the longest 194 ms. This is consistent with Proposition 1, whose bound at 1 Mb/s is 216 ms (above the 100 ms
  starvation threshold). A 1500 B packet takes 12 ms at 1 Mb/s, longer than the 10 ms update interval. No retuning was done.
- Also computed after the fact from saved runs (exploratory): Holm over all 29 points for DR-DRR vs DRR gives better at 23, worse
  at 1 (Poisson 0.8, 0.00007 in W), not significant at 5; RevenueDRR at half its tuned guarantee scale scores below DR-DRR on the E6
  traces (0.84 vs 1.33 at load 0.95, 1.39 vs 1.99 at 1.2).

## E22 — two links in tandem (pre-registered 2026-10-24, before any run)
Why: a reviewer can fairly say a single bottleneck is not a network. The simulator is single-link, but a two-hop path can be
composed from it: the packets that leave link 1 are the through-traffic arrivals at link 2, where they meet fresh cross traffic.
- Path: link 1 (10 Mb/s, 125 kB shared buffer) then link 2 (10 Mb/s, 125 kB). The same scheduler, with the same tuned parameters,
  runs on both links. Through traffic: ON/OFF (medium bursts), load L on link 1, three classes as in the main study. Cross traffic on
  link 2: Poisson, load 0.3, same class mix, an independent trace (seed + 1000). Zero propagation delay. A packet dropped on link 1
  does not reach link 2.
- Points: L = 0.8 and L = 0.95. Seeds 101-110. The eight compared schedulers (so link 2 carries 1.1 and 1.25 of its capacity).
- Score: W2 = max over classes of p95 of the end-to-end queueing delay (wait on link 1 plus wait on link 2, through packets only,
  arrivals in the same 60 s window after a 5 s warm-up) divided by 2 D_i (each hop gets the class's target).
- T1: SP has the lowest latency-class end-to-end p95 at 2/2 points.
- T2: DR-DRR beats DRR on W2 at 2/2 points (paired Wilcoxon, Holm over the 2 points, p < 0.05, DR-DRR lower).
- T3: the order of the eight schedulers by mean W2 at each point has Spearman correlation >= 0.7 with their order by mean W on a
  single link at ON/OFF 0.95 (E1).
- Descriptive: the best non-SP scheduler on mean W2; per-hop p95.

### E22 outcome (2026-10-24)
T1 holds (SP lowest end-to-end latency tail at 2/2 points), T2 holds (DR-DRR beats DRR on W2 at 2/2, Holm p = 0.004, differences -1.57
and -2.18), T3 holds (Spearman 0.98 at both points). Descriptive: RevenueDRR is the best non-SP scheduler on W2 at both points
(0.85 and 1.20), ahead of DR-DRR (1.02 and 1.33). Limits: two identical links, zero propagation delay, one cross-traffic pattern,
no more than two hops.

## E24 — baselines tuned on two knobs (pre-registered 2026-10-24, before any run)
Why: the reconstructed baselines (FuzzyDRR, RevenueDRR) were tuned on one knob each; E6 later showed that a second knob
(RevenueDRR's guarantee scale) moves them past DR-DRR. To keep the ranking from resting on a thin tuning budget, each of the three
adaptive schemes with several relevant knobs gets a two-knob grid, tuned like before.
- Grids (dev seeds 1-5, ON/OFF-medium at loads 0.95 and 1.2): DR-DRR kappa {1,2,4,8,16} x theta {0.25,0.5,0.75,1.0};
  FuzzyDRR gain {0.1,0.5,1,2,3} x delay_span {1,2,4}; RevenueDRR tau {0.0125,0.05,0.1,0.4} x guar_scale {0.25,0.5,1.0,1.5}.
  Other knobs stay at the values in use.
- Rule (as for the one-knob tuning): objective mean W at load 0.95, constraint mean Jain >= 0.98 at load 1.2, values within 1 % of the
  best count as tied and the one closest (sum of |log ratio| over the knobs) to the specified default is picked. No grid extension.
- Evaluation: the three tuned schemes at the 14 E1 points, seeds 101-120, paired with the saved E1 runs.
- Q1: DR-DRR has the lowest mean W of the three at >= 8 of 14 points.
- Q2: DR-DRR has the lowest mean W of the three at every ON/OFF point with load >= 0.9 (4 points).
- Descriptive: the chosen values, and DR-DRR's W under one-knob and two-knob tuning.

### E24 outcome (2026-10-24)
Chosen: DR-DRR kappa 4, theta 0.75; FuzzyDRR gain 0.1, delay_span 2; RevenueDRR tau 0.0125 (the grid's lower edge), guar_scale 0.25 (the lower edge).
Q1 **fails** (DR-DRR lowest of the three at 0 of 14 points) and Q2 **fails** (0 of 4). With two-knob tuning RevenueDRR has the lowest
W at 8 points (ON/OFF 0.8-1.2, Poisson 0.95-1.2) and FuzzyDRR at the 6 light-load ones (by small margins). DR-DRR's one-knob
lead over these reconstructions does not survive a larger tuning budget for them. Two chosen values sit on the grid edge, so
RevenueDRR may be better still.

## E23 — static base with a delay-risk boost, SD-DRR (pre-registered 2026-10-24, before any code for it)
Why: E19 found that static quanta (6000, 6000, 1500 B) beat DR-DRR at heavy and bursty loads, E24 that a two-knob RevenueDRR does
too, while DR-DRR is better at light loads and adapts. SD-DRR combines the two: DR-DRR's rule applied on top of a static base
(the E19 quanta, tuned on development seeds) instead of 1500 B.
- Rule: Q_i = clip(B_i (1 + kappa max(0, r_i - theta)), B_i, M B_i) with B = (6000, 6000, 1500) B, r_i as in Eq. (2), M = 2
  (so the cap is 12000, 12000, 3000 B). Update interval 10 ms as for DR-DRR.
- Tuning (dev seeds 1-5, same objective, constraint and tie rule as before): kappa {1,2,4,8,16} x theta {0.5,0.75,1.0}. M and B are not tuned.
- Evaluation on fresh seeds 201-220 at the 14 E1 points. Competitors, each with the parameters already fixed for it: DR-DRR
  (kappa 4, theta 0.75, E24), RevenueDRR and FuzzyDRR (E24 values), static DRR (6000, 6000, 1500) and plain DRR.
- N1: SD-DRR has the lowest mean W among SD-DRR, DR-DRR, RevenueDRR, FuzzyDRR and static DRR at >= 8 of 14 points.
- N2: SD-DRR is significantly better than static DRR (paired Wilcoxon, Holm over 14) at >= 7 points and significantly worse at <= 2.
- N3: SD-DRR starves no class at any of the 14 points, and its largest service gap stays below 8 sum_j (M B_j + L_j - 1) / C for the
  class concerned (at most 21.6 ms).
- N4: at the E21 points (1 and 100 Mb/s, seeds 101-110, no retuning) SD-DRR has a lower mean W than DRR at >= 5 of 6.

### E23 outcome (2026-10-24)
Chosen (dev seeds): kappa 4, theta 0.75. N1 **fails** (SD-DRR lowest of the five at 1 of 14 points), N2 **fails** (better than static DRR
at 2 points, worse at 4), N3 holds (no starvation; longest service gap 20.3 ms, inside the 21.6 ms bound), N4 **fails** (lower W than
DRR at 3 of 6 points; at 1 Mb/s it is worse at all three). The tuned static quanta are not improved by a delay-risk boost at 10 Mb/s,
and the design does not fix the 1 Mb/s reversal. One design was registered and run; no variant was tried afterwards.
The first E23 run attempt used an invalid scheduler label for the static DRR (280 failed tasks, kept in
`results/E23/failures_first_attempt_label_bug.csv`); the fixed run re-used the 1,120 results already saved.

## E25 — alternative readings of the reconstructed baselines (pre-registered 2026-10-24, before any code for them)
Why: the full FuzzyDRR and RevenueDRR papers are paywalled (Unpaywall lists both as closed; no author copies found), so our versions
are readings of abstracts and previews. Instead of one reading, we try a family of plausible ones, pick the best of each family on
development seeds, and ask whether the conclusion about DR-DRR depends on which reading we chose.
- RevenueDRR readings: the order in which spare capacity goes to classes (all 6 orders of latency, video, bulk; ours is latency,
  video, bulk) x guarantee scale {0.25, 0.5, 1.0} x tau {0.0125, 0.1} = 36 settings.
- FuzzyDRR readings: second fuzzy input = queue occupancy (ours) or throughput shortfall (1 - served bytes / (arrived bytes + backlog
  at the start of the interval) in the last update interval, EWMA 0.5, the other reading the abstract suggests) x gain {0.1, 0.5, 1,
  2, 3} x delay_span {1, 2, 4} = 30 settings.
- Selection: development seeds 1-5, ON/OFF-medium at loads 0.95 and 1.2, objective W at 0.95 s.t. mean Jain at 1.2 >= 0.98, ties
  within 1 % broken toward the reading closest to ours. Evaluation: the two selected readings and DR-DRR (E24 values) at the 14 E1
  points, seeds 101-120.
- A: the selected RevenueDRR reading has lower mean W than DR-DRR at >= 7 of the 8 points where E24's RevenueDRR won.
- B: the selected FuzzyDRR reading differs from plain DRR by more than 5 % in mean W at >= 7 of 14 points (does the fuzzy mechanism do anything?).
- C: at >= 11 of 14 points the lowest-W scheme of the three is the same as in E24.
- Descriptive: which readings were selected.

### E25 outcome (2026-10-24)
Selected: RevenueDRR order (latency, video, bulk), guarantee scale 0.25, tau 0.0125 (the same as E24); FuzzyDRR second input
**throughput shortfall**, gain 1.0, delay_span 2.0 (W at 0.95 on the development seeds 1.945 against 2.7 for our occupancy reading).
A holds (8 of 8), B holds (13 of 14), C holds (14 of 14). So the conclusion of E24 does not depend on which of 66 readings we use:
a demand-aware reading of RevenueDRR has the lowest W at the 8 heavy points and FuzzyDRR at the 6 light ones, DR-DRR at none. The
throughput reading made FuzzyDRR clearly better than our first reading (and different from plain DRR), so for FuzzyDRR the reading mattered;
it still does not reach DR-DRR at heavy load. Access to the source papers (closed per Unpaywall) was not obtained.
