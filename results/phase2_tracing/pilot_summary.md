# Phase 2 proof tracing

Parts pilot: 16/16 shards traced (15,516 proofs planned; `stp_conjectures` excluded). Every step ran with 200,000 heartbeats and a wall-clock backstop. Only complete proofs (every step succeeds, no goals at the end) yield training steps; steps after the goals are closed are dropped. Proofs failing at a step (step_error, closed_early, goals_remaining) are re-checked as whole theorems with `verify_proof`: those that compile fail only in step-by-step replay, the others do not compile in the pinned environment (their failure reason is Lean's first error for the whole proof).

## Replay by source

| source | planned | attempted | complete rate | complete | step_error | closed_early | goals_remaining | timeout | start_failure | repl_failure | block fallback (completed) | failures compiling as whole proofs | complete with a step > 20 s | steps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 2000 | 2000 | 93.4% | 1868 | 7 | 0 | 0 | 125 | 0 | 0 | 0 (0) | 5/7 | 151 | 5510 |
| stp_lean_workbook | 2000 | 2000 | 95.0% | 1900 | 11 | 0 | 1 | 53 | 35 | 0 | 2 (2) | 4/12 | 232 | 8334 |
| deepseek_prover_v1 | 2000 | 2000 | 99.2% | 1983 | 6 | 0 | 1 | 10 | 0 | 0 | 0 (0) | 7/7 | 0 | 4665 |
| lean_workbook | 1516 | 1516 | 60.9% | 923 | 9 | 2 | 8 | 0 | 574 | 0 | 0 (0) | 2/19 | 0 | 2300 |
| goedel_sft_v2 | 2000 | 2000 | 88.4% | 1768 | 150 | 0 | 1 | 75 | 4 | 2 | 0 (0) | 77/151 | 114 | 6621 |
| numinamath_lean_kimina | 2000 | 2000 | 79.8% | 1596 | 313 | 2 | 8 | 77 | 4 | 0 | 4 (2) | 32/323 | 84 | 8501 |
| numinamath_lean_human | 2000 | 2000 | 52.2% | 1045 | 824 | 3 | 18 | 8 | 100 | 2 | 45 (8) | 106/845 | 10 | 7577 |
| leanabell_sft | 2000 | 2000 | 97.0% | 1941 | 15 | 0 | 0 | 43 | 0 | 1 | 0 (0) | 13/15 | 32 | 6299 |
| total | 15516 | 15516 | 83.9% | 13024 | 1335 | 7 | 37 | 391 | 717 | 5 | 51 (12) | 246/1379 | 623 | 49807 |

## Main failure reasons

- **goedel_lean_workbook_proofs**: timeout: wall clock: 107; timeout: heartbeats: 18; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 5; step_error: Forbidden tokens: apply?: 2

- **stp_lean_workbook**: timeout: wall clock: 41; start_failure: ambiguous, possible interpretations : 34; timeout: heartbeats: 12; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 4; step_error: Forbidden tokens: apply?: 3; step_error: Forbidden tokens: exact?: 2; start_failure: function expected at: 1; goals_remaining: unsolved goals: 1

- **deepseek_prover_v1**: timeout: heartbeats: 9; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 6; goals_remaining, whole proof compiles: 1; timeout: wall clock: 1

- **lean_workbook**: start_failure: unexpected token; expected '_': 295; start_failure: unexpected token '_'; expected '_': 132; start_failure: unexpected token; expected '_' or identifier: 93; start_failure: ambiguous, possible interpretations : 20; start_failure: unexpected token '_'; expected '_' or identifier: 18; start_failure: type of theorem '_' is not a proposition: 16; goals_remaining: unsolved goals: 7; step_error: tactic '_' failed, nested error:: 5

- **goedel_sft_v2**: step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 77; timeout: wall clock: 60; step_error: linarith failed to find a contradiction: 24; timeout: heartbeats: 15; step_error: unsolved goals: 14; step_error: lean_search: the tactic closed a goal with sorry: 8; step_error: omega could not prove the goal:: 5; step_error: type mismatch: 3

- **numinamath_lean_kimina**: step_error: Forbidden tokens: native_decide: 150; timeout: wall clock: 66; step_error: linarith failed to find a contradiction: 40; step_error: tactic '_' failed, failed to unify: 20; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 18; step_error: unsolved goals: 14; step_error, whole proof compiles: unknown constant '_': 13; timeout: heartbeats: 11

- **numinamath_lean_human**: step_error: unknown constant '_': 160; step_error: unknown identifier '_': 157; step_error: Forbidden tokens: native_decide: 105; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 91; step_error: tactic '_' failed, did not find instance of the pattern in the target expression: 40; step_error: linarith failed to find a contradiction: 33; step_error: unsolved goals: 30; step_error: application type mismatch: 24

- **leanabell_sft**: timeout: wall clock: 25; timeout: heartbeats: 18; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 7; step_error, whole proof compiles: unknown constant '_': 6; step_error: Forbidden tokens: exact?: 1; repl_failure: crashed: 1; step_error: lean_search: the tactic closed a goal with sorry: 1

- **total**: timeout: wall clock: 304; start_failure: unexpected token; expected '_': 295; step_error: Forbidden tokens: native_decide: 255; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 209; step_error: unknown constant '_': 170; step_error: unknown identifier '_': 167; start_failure: unexpected token '_'; expected '_': 133; step_error: linarith failed to find a contradiction: 97

## Splits

2% of statements are held out for validation, by a stable hash of the canonical statement (12% of the statements appear in several sources under different identifiers).

| split | complete proofs | statements | steps |
|---|---|---|---|
| train | 12775 | 12095 | 48887 |
| validation | 249 | 236 | 920 |

## Remaining steps per training step

|  | count | mean | p50 | p90 | p99 | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8-15 | 16-31 | 32+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 49807 | 4.36 | 3 | 9 | 29 | 146 | 13024 | 10853 | 7455 | 4636 | 3262 | 2349 | 1805 | 5016 | 967 | 440 |
| train | 48887 | 4.37 | 3 | 9 | 29 | 146 | 12775 | 10650 | 7314 | 4549 | 3204 | 2301 | 1772 | 4932 | 950 | 440 |
| validation | 920 | 3.71 | 3 | 8 | 18 | 26 | 249 | 203 | 141 | 87 | 58 | 48 | 33 | 84 | 17 | 0 |

## Open goals before each step

|  | count | mean | p50 | p90 | p99 | max | 0 | 1 | 2 | 3 | 4-5 | 6-10 | 11+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| goals before | 49807 | 1.12 | 1 | 1 | 3 | 476 | 0 | 46298 | 2755 | 417 | 220 | 88 | 29 |

## Step length (characters)

|  | count | mean | p50 | p90 | p99 | max | 0-10 | 11-20 | 21-50 | 51-100 | 101-200 | 201-500 | 501-1000 | 1001+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| step characters | 49807 | 140 | 34 | 298 | 1929 | 11559 | 9276 | 9278 | 13026 | 6850 | 4328 | 3987 | 1585 | 1477 |

## Verification

238 complete proofs (a stable 2% sample) re-verified end to end with `verify_state`: 238 verified (agreement 100.00%); 236 also verify without the per-step heartbeat wrappers.

## Throughput

| invocation | processes | shards | proofs | wall s | proofs/s | steps/s | tactic calls/s | Lean busy |
|---|---|---|---|---|---|---|---|---|
| 2026-10-11T15:30:34+00:00 | 16 | 16 | 15516 | 7083 | 2.19 | 7.03 | 10.2 | 75% |

## Data

Shards in `/workspace/data/traced/shards/<source>/<part>_<index>.{steps,proofs}.jsonl`; merged files `/workspace/data/traced/steps_{train,validation}.jsonl` and `proofs.jsonl`. Schemas in `lean_search.corpora.records`: `TracedStep` (one per step of a complete proof; `previous_steps` rebuilds the state before it, see `tracing.state_before`) and `TracedProof` (one per proof: status, path, failing step, timing, verification).
