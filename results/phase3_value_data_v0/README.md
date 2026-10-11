# Value data set `v0`

Built 2026-10-11T20:31:55+00:00 by `experiments/phase3_value_data.py` (git fa1c45f6d3) from 27 finished tracing shards (78,165 traced steps) in `/workspace/data/traced`, 28 s. One example per state on a traced complete proof, labelled with its remaining steps (an upper bound: the proof's own length from there). Train and validation follow the traced split (by canonical statement). States with the same normalized goals keep the fewest remaining steps; validation states that also occur in train are dropped. Token counts are prompt tokens of `Qwen/Qwen3.5-2B` with the value prompt; training drops prompts over 2,048 tokens.

| Split | Traced steps | Proofs | Duplicate steps | States with conflicting counts | Mean spread of conflicts | Dropped (in train) | States |
|---|---|---|---|---|---|---|---|
| train | 76,628 | 23,560 | 6,377 | 2,659 | 1.89 | 0 | 70,251 |
| validation | 1,537 | 472 | 117 | 48 | 1.60 | 34 | 1,386 |

## Remaining-step bins

| Split | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8+ |
|---|---|---|---|---|---|---|---|---|
| train | 21,914 (31.2%) | 15,550 (22.1%) | 10,293 (14.7%) | 6,514 (9.3%) | 4,535 (6.5%) | 3,208 (4.6%) | 2,402 (3.4%) | 5,835 (8.3%) |
| validation | 429 (31.0%) | 306 (22.1%) | 193 (13.9%) | 125 (9.0%) | 88 (6.3%) | 71 (5.1%) | 51 (3.7%) | 123 (8.9%) |

Mean remaining steps of the 8+ states: train 12.3, validation 13.7. Prompts over 2,048 tokens: train 90, validation 40.

## Distributions

| Quantity | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|
| train remaining steps | 3.4 | 2 | 7 | 15 | 99 |
| train prompt tokens | 214.6 | 183 | 300 | 634 | 35502 |
| validation remaining steps | 3.6 | 2 | 7 | 29 | 42 |
| validation prompt tokens | 606.7 | 186 | 335 | 18110 | 26515 |

## States by source

| Source | Train | Validation |
|---|---|---|
| deepseek_prover_v1 | 4,476 | 109 |
| goedel_lean_workbook_proofs | 36,020 | 788 |
| goedel_sft_v2 | 6,443 | 172 |
| lean_workbook | 1,430 | 20 |
| leanabell_sft | 6,146 | 89 |
| numinamath_lean_kimina | 8,360 | 117 |
| stp_lean_workbook | 7,376 | 91 |
