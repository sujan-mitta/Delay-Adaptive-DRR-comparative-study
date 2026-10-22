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
