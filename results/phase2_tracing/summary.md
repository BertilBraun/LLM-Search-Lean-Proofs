# Phase 2 proof tracing

Parts pilot, main: 29/229 shards traced (224,421 proofs planned; `stp_conjectures` excluded). Every step ran with 200,000 heartbeats and a wall-clock backstop. Only complete proofs (every step succeeds, no goals at the end) yield training steps; steps after the goals are closed are dropped. Proofs failing at a step (step_error, closed_early, goals_remaining) are re-checked as whole theorems with `verify_proof`: those that compile fail only in step-by-step replay, the others do not compile in the pinned environment (their failure reason is Lean's first error for the whole proof).

## Replay by source

| source | planned | attempted | complete rate | complete | step_error | closed_early | goals_remaining | timeout | start_failure | repl_failure | block fallback (completed) | failures compiling as whole proofs | complete with a step > 20 s | steps |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 27249 | 17000 | 92.9% | 15797 | 60 | 0 | 0 | 1143 | 0 | 0 | 0 (0) | 45/60 | 1161 | 46963 |
| stp_lean_workbook | 47138 | 2000 | 95.0% | 1900 | 11 | 0 | 1 | 53 | 35 | 0 | 2 (2) | 4/12 | 232 | 8334 |
| deepseek_prover_v1 | 27187 | 2000 | 99.2% | 1983 | 6 | 0 | 1 | 10 | 0 | 0 | 0 (0) | 7/7 | 0 | 4665 |
| lean_workbook | 1516 | 1516 | 60.9% | 923 | 9 | 2 | 8 | 0 | 574 | 0 | 0 (0) | 2/19 | 0 | 2300 |
| goedel_sft_v2 | 64834 | 2000 | 88.4% | 1768 | 150 | 0 | 1 | 75 | 4 | 2 | 0 (0) | 77/151 | 114 | 6621 |
| numinamath_lean_kimina | 30171 | 2000 | 79.8% | 1596 | 313 | 2 | 8 | 77 | 4 | 0 | 4 (2) | 32/323 | 84 | 8501 |
| numinamath_lean_human | 8762 | 0 | 0.0% | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 (0) | 0/0 | 0 | 0 |
| leanabell_sft | 17564 | 2000 | 97.0% | 1941 | 15 | 0 | 0 | 43 | 0 | 1 | 0 (0) | 13/15 | 32 | 6299 |
| total | 224421 | 28516 | 90.8% | 25908 | 564 | 4 | 19 | 1401 | 617 | 3 | 6 (4) | 180/587 | 1623 | 83683 |

## Main failure reasons

- **goedel_lean_workbook_proofs**: timeout: wall clock: 1012; timeout: heartbeats: 131; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 37; step_error: Forbidden tokens: apply?: 5; step_error: lean_search: the tactic closed a goal with sorry: 5; step_error, whole proof compiles: Case tag '_' not found.: 5; step_error: Forbidden tokens: exact?: 4; step_error, whole proof compiles: The rfl tactic failed. Possible reasons:: 2

- **stp_lean_workbook**: timeout: wall clock: 41; start_failure: ambiguous, possible interpretations : 34; timeout: heartbeats: 12; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 4; step_error: Forbidden tokens: apply?: 3; step_error: Forbidden tokens: exact?: 2; start_failure: function expected at: 1; goals_remaining: unsolved goals: 1

- **deepseek_prover_v1**: timeout: heartbeats: 9; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 6; goals_remaining, whole proof compiles: 1; timeout: wall clock: 1

- **lean_workbook**: start_failure: unexpected token; expected '_': 295; start_failure: unexpected token '_'; expected '_': 132; start_failure: unexpected token; expected '_' or identifier: 93; start_failure: ambiguous, possible interpretations : 20; start_failure: unexpected token '_'; expected '_' or identifier: 18; start_failure: type of theorem '_' is not a proposition: 16; goals_remaining: unsolved goals: 7; step_error: tactic '_' failed, nested error:: 5

- **goedel_sft_v2**: step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 77; timeout: wall clock: 60; step_error: linarith failed to find a contradiction: 24; timeout: heartbeats: 15; step_error: unsolved goals: 14; step_error: lean_search: the tactic closed a goal with sorry: 8; step_error: omega could not prove the goal:: 5; step_error: type mismatch: 3

- **numinamath_lean_kimina**: step_error: Forbidden tokens: native_decide: 150; timeout: wall clock: 66; step_error: linarith failed to find a contradiction: 40; step_error: tactic '_' failed, failed to unify: 20; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 18; step_error: unsolved goals: 14; step_error, whole proof compiles: unknown constant '_': 13; timeout: heartbeats: 11

- **numinamath_lean_human**: none

- **leanabell_sft**: timeout: wall clock: 25; timeout: heartbeats: 18; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 7; step_error, whole proof compiles: unknown constant '_': 6; step_error: Forbidden tokens: exact?: 1; repl_failure: crashed: 1; step_error: lean_search: the tactic closed a goal with sorry: 1

- **total**: timeout: wall clock: 1205; start_failure: unexpected token; expected '_': 295; timeout: heartbeats: 196; step_error, whole proof compiles: lean_search: the tactic closed a goal with sorry: 150; step_error: Forbidden tokens: native_decide: 150; start_failure: unexpected token '_'; expected '_': 133; start_failure: unexpected token; expected '_' or identifier: 93; step_error: linarith failed to find a contradiction: 64

## Splits

2% of statements are held out for validation, by a stable hash of the canonical statement (12% of the statements appear in several sources under different identifiers).

| split | complete proofs | statements | steps |
|---|---|---|---|
| train | 25400 | 21364 | 82027 |
| validation | 508 | 427 | 1656 |

## Remaining steps per training step

|  | count | mean | p50 | p90 | p99 | max | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8-15 | 16-31 | 32+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | 83683 | 3.4 | 2 | 7 | 14 | 99 | 25908 | 18754 | 12240 | 7798 | 5425 | 3801 | 2882 | 6197 | 437 | 241 |
| train | 82027 | 3.4 | 2 | 7 | 14 | 99 | 25400 | 18392 | 12005 | 7645 | 5320 | 3716 | 2821 | 6077 | 421 | 230 |
| validation | 1656 | 3.59 | 2 | 7 | 26 | 42 | 508 | 362 | 235 | 153 | 105 | 85 | 61 | 120 | 16 | 11 |

## Open goals before each step

|  | count | mean | p50 | p90 | p99 | max | 0 | 1 | 2 | 3 | 4-5 | 6-10 | 11+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| goals before | 83683 | 1.07 | 1 | 1 | 2 | 49 | 0 | 78429 | 4630 | 572 | 36 | 15 | 1 |

## Step length (characters)

|  | count | mean | p50 | p90 | p99 | max | 0-10 | 11-20 | 21-50 | 51-100 | 101-200 | 201-500 | 501-1000 | 1001+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| step characters | 83683 | 106 | 35 | 222 | 1346 | 11559 | 16539 | 13858 | 23131 | 11863 | 8829 | 6509 | 1620 | 1334 |

## Verification

501 complete proofs (a stable 2% sample) re-verified end to end with `verify_state`: 501 verified (agreement 100.00%); 499 also verify without the per-step heartbeat wrappers.

## Throughput

| invocation | processes | shards | proofs | wall s | proofs/s | steps/s | tactic calls/s | Lean busy |
|---|---|---|---|---|---|---|---|---|
| 2026-10-11T15:30:34+00:00 | 16 | 14 | 13516 | 7083 | 1.91 | 5.96 | 8.31 | 68% |
| 2026-10-11T17:41:18+00:00 | 40 | 2 | 2000 | 579 | 3.46 | 9.49 | 13.8 | 83% |
| 2026-10-11T18:02:23+00:00 | 36 | 13 | 13000 | 9297 | 1.4 | 3.87 | 5.57 | 37% |

## Data

Shards in `/workspace/data/traced/shards/<source>/<part>_<index>.{steps,proofs}.jsonl`; merged files `/workspace/data/traced/steps_{train,validation}.jsonl` and `proofs.jsonl` (an incremental snapshot of the finished shards; `merged_snapshot.json` lists them). Schemas in `lean_search.corpora.records`: `TracedStep` (one per step of a complete proof; `previous_steps` rebuilds the state before it, see `tracing.state_before`) and `TracedProof` (one per proof: status, path, failing step, timing, verification).
