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
