# Delay-Adaptive DRR Comparative Study — simulator and results

One discrete-event simulator, eight schedulers behind one interface, identical paired workloads.
Rules: [docs/ALGORITHM_SPEC.md](docs/ALGORITHM_SPEC.md) ·
protocol + deviation log: [docs/EXPERIMENT_PROTOCOL.md](docs/EXPERIMENT_PROTOCOL.md) ·
**results: [RESULTS.md](RESULTS.md)** (auto-generated) · figures: `figures/`.

> Rules 1–4 follow their published definitions (RL-SP+DRR checked against arXiv:2002.07027). CQDRR follows its open-access paper. FuzzyDRR and RevenueDRR are inspired-by designs (papers paywalled; only abstract / 2-page preview checked). DR-DRR is our own design (the plan's source could not be found). See [docs/REFERENCES_CHECK.md](docs/REFERENCES_CHECK.md).

## Reproduce everything (Windows PowerShell, Python ≥ 3.11)

```powershell
python -m pip install -r requirements-lock.txt   # or requirements.txt for any recent versions
python -m pytest                       # full suite (needs requirements-dev.txt); see docs/TESTING.md
python scripts/tune.py                 # dev seeds 1–5; verifies config/tuned_params.json is reproduced
python scripts/run_experiments.py      # E1–E10, seeds 101–120 (~7 min on 16 cores); resumable
python scripts/e9_control.py           # E9C: static DRR at DR-DRR mean quanta (needs E9)
python scripts/run_experiments.py DEVD # dev-seed check for DR-DRR+damping
python scripts/confirm_damping.py      # pre-registered rule; stop if it exits non-zero
python scripts/run_experiments.py E1D  # DR-DRR+damping on reported seeds
python scripts/run_experiments.py E1V  # superseded CQDRR draft, for comparison
python scripts/run_experiments.py ES   # SCRR (NSDI 2025), optional ninth scheduler
python scripts/run_experiments.py E11  # real-life stress scenarios (jumbo, tiny, heavy-tail, sync, flash, fade, abuse, ramp)
python scripts/run_experiments.py E12  # IMIX, RED AQM, bulk flood, shallow buffer + jumbo; window and seed-count checks
python scripts/run_benchmarks.py       # E13: published examples (DRR trajectory, DRR bounds, original DRR, RL-SP-DRR, SCRR theorems)
python scripts/e14_ablation.py         # E14: DR-DRR ablation; E15: held-out seeds 201-220
python scripts/e16_kernel.py           # E16: real Linux kernel FIFO/prio/drr in WSL2 or Linux (root; see testbed/)
python scripts/e17_realtrace.py parse <mawi.pcap.gz> ; python scripts/e17_realtrace.py run   # E17: real MAWI traffic
python scripts/timeseries.py           # quanta traces for Figure 5
python scripts/make_figures.py         # figures/ from results/*.csv only
python scripts/make_report.py          # RESULTS.md from results/*.csv only
```
or `./scripts/reproduce.ps1`. Runs are appended to `results/<exp>/runs.csv`; completed keys are
skipped, nothing is overwritten. To start a clean run, move `results/` aside (never delete it).

## Reproducibility
- **Bit-exact:** install `requirements-lock.txt` (the versions used for the reported results, Python 3.13.0).
  A from-scratch run of `scripts/reproduce.ps1` in a clean copy reproduced all 9 700 runs bit-for-bit.
- **Other versions:** also tested on Python 3.11.17 with numpy 2.4.6, pandas 3.1.0, matplotlib 3.11.2,
  scipy 1.17.1 — all tests pass, and re-simulated runs give identical traffic traces, packet timings,
  drops, percentiles and starvation; only some averaged statistics differ in the last floating-point
  digit (relative difference ≤ 2e-15) because newer libraries sum in a different order.
- Every run row stores its traffic-trace digest; `results/<exp>/manifest_*.json` records the code hash
  (SHA-256 of `drrsim/*.py`, line endings normalised; runs made before later behaviour-neutral edits
  carry older hashes, and the clean-copy check above confirms identical output),
  library versions and configurations.

## Layout
| path | what |
|---|---|
| `drrsim/config.py` | validated traffic/sim configs, class definitions (sizes, delay targets, prices) |
| `drrsim/traffic.py` | Poisson and ON/OFF-modulated Poisson traces, deterministic per seed |
| `drrsim/engine.py` | event loop: arrivals, shared or partitioned byte buffer, non-preemptive link |
| `drrsim/schedulers.py` | the 8 compared schedulers (FIFO, SP, DRR, RL-SP+DRR, DR-DRR, CQDRR, FuzzyDRR, RevenueDRR) plus separate arms SCRR, DR-DRR+damping, CQDRR-draft |
| `drrsim/metrics.py` | delay/tail, throughput, drops, Jain, starvation, oscillation, overhead |
| `drrsim/runner.py` | parallel append-only runner, manifests, failure log |
| `drrsim/experiments.py` | all experiments (index in docs/EXPERIMENT_PROTOCOL.md), tuning grid, sensitivity knobs |
| `drrsim/analysis.py` | 95 % CIs, paired Wilcoxon tests, rank stability, pairing check |
| `scripts/` | tuning, experiment runs, controls, figures, report, `reproduce.ps1` |
| `tests/` | tests: toy cases, edge cases, property-based, reference implementations, queueing theory, pipeline (docs/TESTING.md) |
| `tools/mutation_check.py` | plants realistic bugs in temp copies to check the tests catch them |
| `tools/regress_check.py` | re-simulates every saved run; all metrics must match exactly |
| `drrsim/literature.py`, `scripts/run_benchmarks.py` | E13: setups from published papers rebuilt and compared with their numbers |
| `docs/` | algorithm spec, protocol + deviation log, reference check, testing and mutation report, changelog |
| `results/` | every run as CSV + manifests; `_superseded*/` keeps earlier runs (never deleted) |

## Metric definitions (one definition for every scheduler)
- **Queueing delay** = service start − arrival, packets arriving in the 60 s window; mean, p95, p99.
- **Throughput** = payload bits whose transmission ends in the window / 60 s.
- **Drop rate** = dropped / offered (arrivals in window).
- **Jain** over `x_i = throughput_i / max-min fair share_i` (equal weights, from offered rates).
- **Starvation**: a gap where a class is backlogged and receives no service for > 100 ms;
  count, total, max.
- **Oscillation** (adaptive): mean |ΔQ_i|/Q⁰ per 10-ms update; sign flips of ΔQ_i per second.
- **W** = max_i p95_i / D_i, D = (10, 50, 500) ms. W ≤ 1 means every class met its p95 target.

## Figures (all regenerated from `results/*.csv` by `scripts/make_figures.py`)
| file | content | plan figure |
|---|---|---|
| fig1_system_model | queues, scheduler, bottleneck link | 1 |
| fig2_p95_vs_load | per-class p95 vs load, Poisson and ON/OFF | 2 |
| fig3_starvation_stress | starvation and bulk throughput, stress test, shared vs partitioned buffer | 3 |
| fig4_delay_fairness_tradeoff | latency p95 vs Jain's index | 4 |
| fig5_weight_oscillation | quanta over time for the four adaptive schedulers | 5 |
| fig6_parameter_sensitivity | W for each knob at ×0.5 / ×1 / ×1.5 | 6 |
| fig7_burstiness | per-class p95 vs burst size | extra |
| fig8_buffer_and_mix | W vs buffer size and traffic mix | extra |
| fig9_drdrr_damping | damping ablation with static-DRR control | extra |
| fig10_drdrr_damping_variant | DR-DRR+damping across all E1 points | extra |
| fig11_scrr | SCRR vs DRR (1500 B and 9000 B quanta) | extra (optional 9th scheduler) |
| fig12_reallife_heatmap | mean W per real-life scenario and scheduler (E11) | extra |
| fig13_e12_heatmap | mean W per scenario and scheduler (E12) | extra |
| fig14_literature | original DRR Fig. 7 re-created; worst delay / published DRR bound (E13) | extra |

## Citation and AI-use note
If you use this simulator, cite the accompanying paper (details to be added on acceptance).
Parts of this code base were written with AI assistance (Claude); results come only from the
saved runs, and the paper text is written by the author.


## License
MIT, see [LICENSE](LICENSE).
