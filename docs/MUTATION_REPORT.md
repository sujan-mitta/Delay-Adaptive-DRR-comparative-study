# Mutation check

56/56 behaviour-changing planted bugs were caught by the test suite (2 further mutants are equivalent: they cannot change behaviour, see notes).

| id | planted bug | result | first failing test |
|---|---|---|---|
| E1 | arrival processed before a completion at the same instant | killed | `tests/test_edge_cases.py::test_completion_before_arrival_at_equal_time` |
| E2 | off-by-one: a packet that exactly fills the buffer is dropped | killed | `tests/test_edge_cases.py::test_buffer_exactly_full_is_admitted_one_more_byte_is_dropped` |
| E3 | wrong partition size | killed | `tests/test_core.py::test_partitioned_buffer_isolates_classes` |
| E4 | near-tie wake-up recorded after the arrival it precedes | killed | `tests/test_robustness.py::test_extreme_but_valid_inputs[tie_storm-RL-SP+DRR]` |
| E5 | bit/byte conversion error | killed | `tests/test_core.py::test_toy_fifo_exact` |
| E6 | buffer occupancy not released when a packet starts service | killed | `tests/test_core.py::test_toy_fifo_exact` |
| S1 | DRR keeps its deficit after the queue empties | equivalent | `` |
| S2 | DRR needs strictly more deficit than the packet size | killed | `tests/test_reference.py::test_reference_agreement_on_realistic_traces[0.6-onoff]` |
| S3 | new DRR class jumps the round-robin queue | killed | `tests/test_core.py::test_accounting_and_fifo_within_class[DRR]` |
| S4 | FIFO serves the class of the newest queued packet | killed | `tests/test_core.py::test_toy_fifo_exact` |
| S5 | strict priority order reversed | killed | `tests/test_core.py::test_toy_sp_exact` |
| S6 | RL-SP shaper gives idle class 0 burst credit (and -inf start) | killed | `tests/test_core.py::test_rlsp_toy_exact` |
| S7 | RL-SP misses the exact departure instant | killed | `tests/test_core.py::test_accounting_and_fifo_within_class[RL-SP+DRR]` |
| S8 | M/M/1/K blocking formula sign error | killed | `tests/test_core.py::test_mm1k_blocking_hand_values` |
| S9 | SCRR clock may run backwards | killed | `tests/test_edge_cases.py::test_scrr_virtual_clock_never_goes_backwards` |
| S10 | fuzzy rule table row reversed | killed | `tests/test_core.py::test_fuzzy_multiplier_corners` |
| S11 | DR-DRR loses its upper bound | killed | `tests/test_properties.py::test_invariants_every_scheduler[DR-DRR-backlog]` |
| S12 | CQDRR fixed iteration cap (the original bug) | killed | `tests/test_matrix.py::test_skip_rounding_note_cqdrr_exact_with_binary_fraction_quanta` |
| M1 | p95 computed as p90 | killed | `tests/test_core.py::test_toy_metrics_exact` |
| M2 | starvation threshold not strict | killed | `tests/test_edge_cases.py::test_starvation_threshold_is_strict` |
| M3 | Jain's index formula wrong | killed | `tests/test_core.py::test_maxmin_and_jain` |
| M4 | max-min share boundary | equivalent | `` |
| M5 | starvation gap uses the wrong previous packet | killed | `tests/test_core.py::test_starvation_gaps_hand` |
| M6 | zero changes counted as sign flips | killed | `tests/test_edge_cases.py::test_oscillation_flip_count_ignores_unchanged_steps` |
| T1 | largest packet size never generated | killed | `ERROR tests/test_robustness.py` |
| T2 | ON/OFF duty cycle inverted | killed | `tests/test_theory.py::test_onoff_duty_cycle_is_respected[0.25]` |
| T3 | trace sorted by class instead of time | killed | `tests/test_core.py::test_trace_deterministic_and_sorted[poisson]` |
| V1 | unsorted traces silently accepted | killed | `tests/test_robustness.py::test_hostile_traces_are_refused[FIFO-trace0-sorted]` |
| V2 | infinite / NaN traffic parameters accepted | killed | `tests/test_robustness.py::test_hostile_traffic_configs_are_refused[kw0]` |
| T4 | wake-up within the tie tolerance processed after an arrival | killed | `tests/test_robustness.py::test_extreme_but_valid_inputs[tie_storm-RL-SP+DRR]` |
| C1 | capacity schedule ignored | killed | `tests/test_scenarios.py::test_capacity_fade_exact_and_non_preemptive` |
| C2 | capacity segment end treated as inclusive | killed | `tests/test_scenarios.py::test_capacity_boundary_is_half_open` |
| G1 | Pareto periods with the wrong mean | killed | `tests/test_robustness.py::test_fuzzed_parameters_are_refused_or_simulate_correctly[FuzzyDRR]` |
| G2 | synchronised bursts ignored | killed | `tests/test_scenarios.py::test_sync_all_classes_share_one_onoff_process` |
| G3 | load-profile thinning wrong | killed | `tests/test_scenarios.py::test_profile_scales_rate_inside_segment_only` |
| G4 | packet-size override ignored | killed | `tests/test_scenarios.py::test_size_override_exact_and_byte_load_preserved` |
| R1 | RED average forgets its history | killed | `tests/test_aqm_imix.py::test_red_seed_pairs_runs_and_changes_draws` |
| R2 | RED inter-drop count correction missing | killed | `tests/test_aqm_imix.py::test_red_matches_reference` |
| R3 | RED admits packets into a full buffer | killed | `tests/test_aqm_imix.py::test_red_with_unreachable_thresholds_equals_tail_drop` |
| I1 | IMIX weights ignored | killed | `tests/test_aqm_imix.py::test_imix_sizes_proportions_and_byte_load` |
| U1 | runner header fixed by the first row (the bug found in round 3) | killed | `tests/test_pipeline.py::test_tasks_with_different_tag_columns_share_one_file` |
| K1 | a 3-class-only scheduler accepts another number of classes | killed | `tests/test_literature.py::test_three_class_schedulers_refuse_other_k[RL-SP+DRR]` |
| K2 | partition size ignores the number of classes | killed | `tests/test_literature.py::test_partitioned_buffer_splits_by_the_scheduler_class_count` |
| L1 | DRR-EOS keeps an old opportunity across an idle link | killed | `tests/test_literature.py::test_drr_eos_opportunity_ends_when_the_link_goes_idle` |
| L2 | DRR-EOS never ends an opportunity on an empty queue | killed | `tests/test_properties.py::test_invariants_every_scheduler[DRR-EOS]` |
| L3 | token bucket not capped at its burst size | killed | `tests/test_literature.py::test_token_bucket_sources_conform[0.5]` |
| L4 | SCRR probe never ends a visit (bursts summed across visits) | killed | `tests/test_literature.py::test_scrr_round_first_meets_theorems_on_random_traces` |
| P1 | DRR skip-ahead jumps past the pass in which a class can send | killed | `tests/test_drr_theory.py::test_skip_ahead_makes_identical_decisions[integer-DRR-_NoSkip]` |
| P2 | DRR skip-ahead disabled (tiny quanta hang again) | killed | `tests/test_drr_theory.py::test_tiny_quanta_do_not_hang` |
| P3 | FIFO serves the newest packet (LIFO) | killed | `tests/test_core.py::test_toy_fifo_exact` |
| L5 | Boyer bound computed without the 1-byte residual-deficit correction | killed | `tests/test_drr_theory.py::test_boyer_bound_reproduces_published_values` |
| C3 | CQDRR skip-ahead jumps past the round in which a class can send | killed | `tests/test_matrix.py::test_skip_rounding_note_cqdrr_exact_with_binary_fraction_quanta` |
| C4 | CQDRR skip-ahead disabled (tiny quanta hang again: the round-6 bug) | killed | `tests/test_matrix.py::test_extreme_parameters_finish_fast_and_keep_invariants[CQDRR-tiny]` |
| C5 | CQDRR skip credits only one class | killed | `tests/test_matrix.py::test_skip_rounding_note_cqdrr_exact_with_binary_fraction_quanta` |
| H1 | ON/OFF period limit too loose (1 ns ON periods hang generation again) | killed | `tests/test_matrix.py::test_onoff_periods_too_short_rejected_not_hung[1e-09]` |
| H2 | link rate below 1 b/s accepted (service times can overflow) | killed | `tests/test_matrix.py::test_link_rate_outside_physical_range_rejected[0.5]` |
| H3 | engine accepts an overflowing completion time as 'idle' | killed | `tests/test_matrix.py::test_engine_refuses_overflowing_completion_even_if_validation_is_bypassed` |
| R5 | real-traffic class mapping changed after registration (QUIC no longer video) | killed | `tests/test_realdata.py::test_preregistered_class_mapping` |

**Equivalent mutants**

- **S1**: DRR resets a class's deficit when the class re-joins (on_enqueue), and the deficit is never read while the class is off the active list, so also zeroing it on leaving changes nothing.
- **M4**: Water-filling converges to the unique max-min fair allocation whether a class whose residual demand equals the fair share is frozen this round (<=) or next round (<).

Row R5 (E17 class mapping) was run separately with `--only` after the 55 above; the drrsim code was unchanged in between.
