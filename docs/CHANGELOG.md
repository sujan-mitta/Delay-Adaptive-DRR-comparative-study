# Changelog

Each entry says what changed and whether any reported result changed. Superseded runs are never deleted; they are
archived under `results/_superseded*` and `results/_aborted*` (33,140 runs in total). Protocol deviations are logged in
`docs/EXPERIMENT_PROTOCOL.md`; bugs found by testing are listed in `docs/TESTING.md`.

## Before the first published results (commit a85b372)
- RL-SP+DRR corrected to the paper's Algorithm 1 (deviation 4); earlier runs archived in `_superseded_rlsp_draft`.
- CQDRR replaced by the paper's rule once the full text could be read (deviation 5); the draft rule kept as the labelled
  variant CQDRR-draft; earlier runs archived in `_superseded_cqdrr_draft`.
- SQ-DRR renamed DR-DRR and presented as our own design after its cited source could not be found (deviation 6).

## 4353e03 — exhaustive testing
- Fixed: CQDRR loop cap (no reported run affected), SCRR global clock could move backwards (SCRR arm ES re-run, verdicts
  unchanged; old runs in `_superseded_scrr_clock`), manifest overwrite (no result affected).

## 0f388d7 — hardening and E11
- Strict input validation; unified 1e-12 s tie rule (all saved runs re-simulate exactly). New experiment E11.

## dddfee0 — round 3 and E12
- Runner CSV-header bug found by E12 (E12 re-run; partial output in `_aborted_e12_header`). New options IMIX and RED (off by
  default). Regression guard `tools/regress_check.py`.

## 8dabe1d — E13
- Published examples re-created. Engine supports any number of classes for FIFO, SP, DRR, DRR-EOS and SCRR (bit-exact).

## 8dfbdfb, f20ae6e, 4d35f71 — rounds 5-7
- Fixed: DRR and CQDRR loops whose length grew as quanta shrank, an ON/OFF generator hang, a service-time overflow read as
  "idle". None reachable with the parameters of any reported run; all saved runs re-simulate exactly. O(1) FIFO.

## Audit round (this entry)
- Run accounting reconciled: 6,520 runs in the main matrix (E1-E8, 2,320 point-seed groups), 8,640 in further reported arms,
  640 tuning runs, 15,800 in total. The regression guard now covers all of them (it previously skipped the 240 E9C runs
  and 60 tuning-extension runs, which also re-simulate exactly).
- New pre-registered experiments E14 (DR-DRR ablation: backlog-only and head-of-line-only variants) and E15 (held-out
  seeds 201-220). E15's third criterion (H3) failed as registered; reported with the computed explanation.
- Proposition: bounded service gap of DR-DRR, checked on all 1,680 saved DR-DRR runs and by a property test.
- DR-DRR's delay estimate moved into one method so the ablation variants override only that line (all saved DR-DRR runs
  re-simulate exactly).

## Evidence round (this entry)
- New pre-registered checks: E16b (kernel at 1 Mb/s), E17b (two alternative real-traffic class mappings), E18 (re-scoring
  without our delay targets), E19 (tuned static DRR). E16b and E17b hold. E18 and E19 go against our own conclusions: DR-DRR's
  lead is partly an artefact of the score W, and a tuned static DRR beats DR-DRR at 8 of 14 load points; the paper says so.
- Simulator runs are now 16,240 (E19 and its tuning added 440), still all re-simulated exactly by the regression guard.
- The paper text was rewritten for plainer, less templated prose (style rules in paper_draft/STYLE.md, which is private);
  both paper versions now carry an AI-use statement.

## Audit follow-up (this entry)
- Found by an outside read of the paper: it said all 2,320 (point, seed) groups were shared across eight schedulers. They are
  not: 600 groups are (4,800 runs); the other 1,720 are single-scheduler sensitivity runs of E6 on 40 shared traces. The
  paper's wording was wrong, the data were not. `tools/run_ledger.py` now generates `docs/RUN_LEDGER.md` and every count in the
  paper comes from it; `tests/test_ledger.py` keeps it honest.
- E19H (pre-registered): the tuned static DRR on fresh seeds 201-220, paired with E15's DR-DRR: again mixed (DR-DRR better at
  6, worse at 8 of 14, at the same points). Simulator runs are now 16,520.
- Paper: abstract narrowed (the lead is under our score and against reconstructed baselines), static-baseline tuning budget
  stated (16 settings against DR-DRR's 5), confirmatory versus exploratory claims listed, "real traffic" replaced by "one
  replayed backbone trace".

## Claim-by-claim audit (this entry)
`tools/claims_audit.py` recomputes every quantitative claim of the paper from the raw `runs.csv` files, independently of the
report generator (175 checks with the paper source, 117 without it). It found, and we fixed:
- "best non-SP scheduler" was counted two ways (by mean rank in the report headline, by mean W elsewhere): CQDRR 5 / RL-SP+DRR 4
  by mean W, not 4 / 5. The report now uses mean W everywhere and says so.
- The paper's "RL-SP+DRR drop rate climbs to 35 %" was the latency class's rate; overall it drops 28 % of packets (DRR: 14 %).
- The SCRR counterexample text said the reordered algorithm "advances the clock by 1" at that step; the trace shows the clock
  moving 1, 4, 7, 9 (steps of at most M = 3). The violation of the printed algorithm (an advance of 4) is unchanged.
- Three cells of the effect-size table were rounded by hand and differed from the data in the second decimal; the table is now
  generated from the data.
- Mutation count: 58 planted bugs, 56 behaviour-changing (the paper said 57 and 55 before the R5 mutant was added).
- The protocol's deviation log skipped number 3 (E8, added after E1); entry added.
- Wording that said more than the data: "every bursty run" (Jain: the load-sweep ON/OFF runs), "no DRR-family scheduler starved a
  class" (CQDRR is one), the Holm families, the gap bound (at most 21.6 ms, not exactly), "about as well as the best static
  setting" (it loses at heavy load), "ranks the kernel's schedulers correctly" (it ranks them as the kernel does).

