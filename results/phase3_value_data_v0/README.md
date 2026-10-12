# Value data set `v0`

Built 2026-10-11T22:32:06+00:00 by `experiments/phase3_value_data.py` (git e7ea69f3dc) from 53 finished tracing shards (166,701 traced steps) in `/workspace/data/traced`, 52 s. One example per state on a traced complete proof, labelled with its remaining steps (an upper bound: the proof's own length from there). Train and validation follow the traced split (by canonical statement). States with the same normalized goals keep the fewest remaining steps; validation states that also occur in train are dropped. Token counts are prompt tokens of `Qwen/Qwen3.5-2B` with the value prompt; training drops prompts over 2,048 tokens.

| Split | Traced steps | Proofs | Duplicate steps | States with conflicting counts | Mean spread of conflicts | Dropped (in train) | States |
|---|---|---|---|---|---|---|---|
| train | 163,501 | 46,853 | 28,849 | 11,719 | 2.20 | 0 | 134,652 |
| validation | 3,200 | 958 | 495 | 199 | 2.48 | 89 | 2,616 |

## Remaining-step bins

| Split | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8+ |
|---|---|---|---|---|---|---|---|---|
| train | 40,295 (29.9%) | 27,589 (20.5%) | 19,252 (14.3%) | 13,115 (9.7%) | 9,580 (7.1%) | 7,208 (5.4%) | 5,335 (4.0%) | 12,278 (9.1%) |
| validation | 798 (30.5%) | 538 (20.6%) | 359 (13.7%) | 246 (9.4%) | 189 (7.2%) | 144 (5.5%) | 103 (3.9%) | 239 (9.1%) |

Mean remaining steps of the 8+ states: train 11.8, validation 11.6. Prompts over 2,048 tokens: train 219, validation 50.

## Distributions

| Quantity | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|
| train remaining steps | 3.6 | 2 | 7 | 14 | 102 |
| train prompt tokens | 223.4 | 193 | 306 | 624 | 35502 |
| validation remaining steps | 3.5 | 2 | 7 | 15 | 41 |
| validation prompt tokens | 442.6 | 194 | 325 | 9715 | 26515 |

## States by source

| Source | Train | Validation |
|---|---|---|
| deepseek_prover_v1 | 4,476 | 109 |
| goedel_lean_workbook_proofs | 58,764 | 1,249 |
| goedel_sft_v2 | 6,443 | 172 |
| lean_workbook | 1,215 | 16 |
| leanabell_sft | 6,143 | 88 |
| numinamath_lean_kimina | 8,359 | 117 |
| stp_lean_workbook | 49,252 | 865 |
