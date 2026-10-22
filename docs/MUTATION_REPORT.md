# Mutation check

25/25 behaviour-changing planted bugs were caught by the test suite (2 further mutants are equivalent: they cannot change behaviour, see notes).

| id | planted bug | result | first failing test |
|---|---|---|---|
| E1 | arrival processed before a completion at the same instant | killed | `tests/test_edge_cases.py::test_completion_before_arrival_at_equal_time` |
| E2 | off-by-one: a packet that exactly fills the buffer is dropped | killed | `tests/test_edge_cases.py::test_buffer_exactly_full_is_admitted_one_more_byte_is_dropped` |
| E3 | wrong partition size | killed | `tests/test_core.py::test_partitioned_buffer_isolates_classes` |
| E4 | arrival processed before a wake-up at the same instant | killed | `tests/test_edge_cases.py::test_wake_is_processed_before_an_arrival_at_the_same_instant` |
| E5 | bit/byte conversion error | killed | `tests/test_core.py::test_toy_fifo_exact` |
| E6 | buffer occupancy not released when a packet starts service | killed | `tests/test_core.py::test_toy_fifo_exact` |
| S1 | DRR keeps its deficit after the queue empties | equivalent | `` |
| S2 | DRR needs strictly more deficit than the packet size | killed | `tests/test_reference.py::test_reference_agreement_on_realistic_traces[0.6-onoff]` |
| S3 | new DRR class jumps the round-robin queue | killed | `tests/test_core.py::test_accounting_and_fifo_within_class[DRR]` |
| S4 | FIFO serves the newest head first | killed | `tests/test_core.py::test_toy_fifo_exact` |
| S5 | strict priority order reversed | killed | `tests/test_core.py::test_toy_sp_exact` |
| S6 | RL-SP shaper gives idle class 0 burst credit (and -inf start) | killed | `tests/test_core.py::test_rlsp_toy_exact` |
| S7 | RL-SP misses the exact departure instant | killed | `tests/test_core.py::test_accounting_and_fifo_within_class[RL-SP+DRR]` |
| S8 | M/M/1/K blocking formula sign error | killed | `tests/test_core.py::test_mm1k_blocking_hand_values` |
| S9 | SCRR clock may run backwards | killed | `tests/test_edge_cases.py::test_scrr_virtual_clock_never_goes_backwards` |
| S10 | fuzzy rule table row reversed | killed | `tests/test_core.py::test_fuzzy_multiplier_corners` |
| S11 | DR-DRR loses its upper bound | killed | `tests/test_properties.py::test_adaptive_quanta_finite_positive_bounded[DR-DRR]` |
| S12 | CQDRR fixed iteration cap (the original bug) | killed | `tests/test_edge_cases.py::test_cqdrr_tiny_quantum_regression` |
| M1 | p95 computed as p90 | killed | `tests/test_core.py::test_toy_metrics_exact` |
| M2 | starvation threshold not strict | killed | `tests/test_edge_cases.py::test_starvation_threshold_is_strict` |
| M3 | Jain's index formula wrong | killed | `tests/test_core.py::test_maxmin_and_jain` |
| M4 | max-min share boundary | equivalent | `` |
| M5 | starvation gap uses the wrong previous packet | killed | `tests/test_core.py::test_starvation_gaps_hand` |
| M6 | zero changes counted as sign flips | killed | `tests/test_edge_cases.py::test_oscillation_flip_count_ignores_unchanged_steps` |
| T1 | largest packet size never generated | killed | `tests/test_core.py::test_trace_deterministic_and_sorted[poisson]` |
| T2 | ON/OFF duty cycle inverted | killed | `tests/test_theory.py::test_onoff_duty_cycle_is_respected[0.25]` |
| T3 | trace sorted by class instead of time | killed | `tests/test_core.py::test_trace_deterministic_and_sorted[poisson]` |

**Equivalent mutants**

- **S1**: DRR resets a class's deficit when the class re-joins (on_enqueue), and the deficit is never read while the class is off the active list, so also zeroing it on leaving changes nothing.
- **M4**: Water-filling converges to the unique max-min fair allocation whether a class whose residual demand equals the fair share is frozen this round (<=) or next round (<).
