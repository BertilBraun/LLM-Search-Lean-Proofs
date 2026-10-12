# Phase 4: applicability check cost

`experiments/phase4_annotation_cost.py --candidates frequent --processes 8 --traced-states 256`: 244 miniF2F-valid
roots and 256 traced validation-split competition states, 32 candidates each, checked with `exact`, `apply`, `rw`
(10,000 heartbeats, 5 s backstop). The candidates are the 32 theorems most often named in traced competition steps,
the same for every state, in runs 1 and 2 (before the premise embeddings existed), and the retriever's top 32 in
run 3.

| Run | Node load (46 cores) | Lean s per state, mean / p50 / p90 | Tactic calls | `exact` / `apply` / `rw` failing, p50 ms | Leaves goals / closes per state |
|---|---|---|---|---|---|
| 1 (LeanDojo corpus only) | ~55–65 | 0.75 / 0.45 / 0.89 | 95.8 | 2 / 6 / 4 | 1.56 / 0.11 |
| 2 (with the added environment theorems, `frequent_10000.md`) | ~50–75 | 1.59 / 1.02 / 1.90 | 95.8 | 3 / 8 / 5 | 2.38 / 0.10 |
| 3 (retriever's top 32, `retrieved_10000.md`) | lower, niced | 0.98 / 0.60 / 1.29 | 95.9 | 3 / 7 / 5 | 1.80 / 0.07 |

Per-call times doubled between the runs with the load of other jobs on the node, so a check costs 0.75–1.6
Lean-seconds per expansion. Row 2 spends ~5.5 Lean-seconds per expansion (`results/phase2_sft_v1_search/`), so the
check adds 15–30%. 15 process restarts per run come from the proof-state threshold (each call leaves a REPL proof
state) and a few wall-clock kills.
