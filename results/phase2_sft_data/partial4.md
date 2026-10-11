# SFT data `partial4`

Built 2026-10-11T16:26:36+00:00 from 8 shard files in `/workspace/data/traced` (git 5e75ccd0b7, 19 s). Budget everything of `Qwen/Qwen3.5-2B` tokens (prompt + completion), caps 2048 prompt and 512 completion tokens, seed `sft-pilot`. Each example is one traced train-split step: the goals before it rendered with the policy prompt (no lemmas, thinking off, prefilled fence) and the step as the completion. Steps with forbidden tokens are dropped, identical (goals, step) pairs are kept once, and each source is filled in a fixed pseudo-random order up to its weighted share of the budget; the shares of exhausted sources go to the others.

| Source | Weight | Traced train steps | Forbidden | Duplicates | Examined | Over length | Selected | Tokens | Share |
|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 1 | 5,398 | 0 | 48 | 5,350 | 8 | 5,342 | 1,104,367 | 26.6% |
| stp_lean_workbook | 1 | 8,217 | 0 | 77 | 8,140 | 6 | 8,134 | 1,864,746 | 45.0% |
| deepseek_prover_v1 | 1 | 4,555 | 0 | 3 | 4,552 | 1 | 4,551 | 810,341 | 19.5% |
| lean_workbook | 1 | 2,264 | 0 | 82 | 2,182 | 1 | 2,181 | 365,600 | 8.8% |
| goedel_sft_v2 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| numinamath_lean_kimina | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| numinamath_lean_human | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% |
| leanabell_sft | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0.0% |

## Token lengths

| Split | Part | Examples | Tokens | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|---|
| train | prompt | 20,208 | 3,605,882 | 178 | 162 | 259 | 447 | 1994 |
| train | completion | 20,208 | 539,172 | 27 | 16 | 64 | 190 | 512 |
| train | total | 20,208 | 4,145,054 | 205 | 185 | 306 | 518 | 2506 |
| validation | prompt | 372 | 67,415 | 181 | 162 | 263 | 468 | 688 |
| validation | completion | 372 | 9,879 | 27 | 16 | 64 | 154 | 230 |
| validation | total | 372 | 77,294 | 208 | 189 | 303 | 494 | 719 |

| Source | Prompt mean | p50 | p90 | p99 | Max | Completion mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 172 | 156 | 245 | 470 | 1262 | 35 | 18 | 87 | 210 | 483 |
| stp_lean_workbook | 196 | 181 | 284 | 455 | 1994 | 34 | 18 | 84 | 223 | 512 |
| deepseek_prover_v1 | 167 | 150 | 234 | 431 | 1509 | 11 | 9 | 21 | 45 | 139 |
| lean_workbook | 154 | 140 | 209 | 410 | 870 | 14 | 12 | 27 | 43 | 176 |
| goedel_sft_v2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| numinamath_lean_kimina | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| numinamath_lean_human | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| leanabell_sft | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

Validation: 372 examples from 375 traced validation-split steps (statements held out by hash) after dropping 3 duplicates or pairs also present in train; by source: deepseek_prover_v1: 110, goedel_lean_workbook_proofs: 112, lean_workbook: 33, stp_lean_workbook: 117.
