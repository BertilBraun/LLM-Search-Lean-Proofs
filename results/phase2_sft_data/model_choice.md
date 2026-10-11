# SFT data `model_choice`

Built 2026-10-11T17:32:58+00:00 from 16 shard files in `/workspace/data/traced` (git 0499cf49a7, 35 s). Budget 7,500,000 tokens of `Qwen/Qwen3.5-2B` tokens (prompt + completion), caps 2048 prompt and 256 completion tokens, seed `sft-pilot`. Each example is one traced train-split step: the goals before it rendered with the policy prompt (no lemmas, thinking off, prefilled fence) and the step as the completion. Steps with forbidden tokens are dropped, identical (goals, step) pairs are kept once, and each source is filled in a fixed pseudo-random order up to its weighted share of the budget; the shares of exhausted sources go to the others.

| Source | Weight | Traced train steps | Forbidden | Duplicates | Examined | Over length | Selected | Tokens | Share |
|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 1 | 5,398 | 0 | 48 | 5,168 | 31 | 5,137 | 1,054,119 | 14.1% |
| stp_lean_workbook | 1 | 8,217 | 0 | 77 | 4,653 | 24 | 4,629 | 1,054,023 | 14.1% |
| deepseek_prover_v1 | 1 | 4,555 | 0 | 3 | 4,552 | 1 | 4,551 | 810,341 | 10.8% |
| lean_workbook | 1 | 2,264 | 0 | 82 | 2,182 | 1 | 2,181 | 365,600 | 4.9% |
| goedel_sft_v2 | 1 | 6,449 | 0 | 0 | 5,026 | 1,318 | 3,708 | 1,054,250 | 14.1% |
| numinamath_lean_kimina | 1 | 8,384 | 0 | 5 | 4,418 | 299 | 4,119 | 1,054,232 | 14.1% |
| numinamath_lean_human | 1 | 7,411 | 0 | 6 | 3,569 | 220 | 3,349 | 1,054,170 | 14.1% |
| leanabell_sft | 1 | 6,209 | 0 | 0 | 5,459 | 26 | 5,433 | 1,054,122 | 14.1% |

## Token lengths

| Split | Part | Examples | Tokens | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|---|
| train | prompt | 33,107 | 6,470,356 | 195 | 164 | 296 | 697 | 2035 |
| train | completion | 33,107 | 1,030,501 | 31 | 15 | 83 | 217 | 256 |
| train | total | 33,107 | 7,500,857 | 227 | 191 | 358 | 754 | 2077 |
| validation | prompt | 858 | 167,781 | 196 | 171 | 296 | 480 | 796 |
| validation | completion | 858 | 30,723 | 36 | 17 | 102 | 231 | 255 |
| validation | total | 858 | 198,504 | 231 | 207 | 379 | 579 | 802 |

| Source | Prompt mean | p50 | p90 | p99 | Max | Completion mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 172 | 156 | 244 | 474 | 1262 | 33 | 18 | 85 | 195 | 255 |
| stp_lean_workbook | 196 | 181 | 286 | 457 | 1232 | 32 | 18 | 80 | 186 | 256 |
| deepseek_prover_v1 | 167 | 150 | 234 | 431 | 1509 | 11 | 9 | 21 | 45 | 139 |
| lean_workbook | 154 | 140 | 209 | 410 | 870 | 14 | 12 | 27 | 43 | 176 |
| goedel_sft_v2 | 225 | 189 | 363 | 703 | 1261 | 60 | 19 | 181 | 246 | 256 |
| numinamath_lean_kimina | 212 | 183 | 337 | 610 | 1290 | 44 | 25 | 117 | 237 | 256 |
| numinamath_lean_human | 280 | 209 | 492 | 1364 | 2033 | 35 | 16 | 91 | 212 | 256 |
| leanabell_sft | 173 | 142 | 244 | 811 | 2035 | 21 | 12 | 44 | 144 | 250 |

Validation: 858 examples from 920 traced validation-split steps (statements held out by hash) after dropping 3 duplicates or pairs also present in train; by source: deepseek_prover_v1: 110, goedel_lean_workbook_proofs: 112, goedel_sft_v2: 133, lean_workbook: 33, leanabell_sft: 90, numinamath_lean_human: 157, numinamath_lean_kimina: 106, stp_lean_workbook: 117.
