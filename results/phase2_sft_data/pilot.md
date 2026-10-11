# SFT data `pilot`

Built 2026-10-11T17:31:20+00:00 from 16 shard files in `/workspace/data/traced` (git 77e0c0f67a, 44 s). Budget everything of `Qwen/Qwen3.5-2B` tokens (prompt + completion), caps 2048 prompt and 256 completion tokens, seed `sft-pilot`. Each example is one traced train-split step: the goals before it rendered with the policy prompt (no lemmas, thinking off, prefilled fence) and the step as the completion. Steps with forbidden tokens are dropped, identical (goals, step) pairs are kept once, and each source is filled in a fixed pseudo-random order up to its weighted share of the budget; the shares of exhausted sources go to the others.

| Source | Weight | Traced train steps | Forbidden | Duplicates | Examined | Over length | Selected | Tokens | Share |
|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 1 | 5,398 | 0 | 48 | 5,350 | 31 | 5,319 | 1,093,210 | 10.1% |
| stp_lean_workbook | 1 | 8,217 | 0 | 77 | 8,140 | 49 | 8,091 | 1,840,042 | 16.9% |
| deepseek_prover_v1 | 1 | 4,555 | 0 | 3 | 4,552 | 1 | 4,551 | 810,341 | 7.5% |
| lean_workbook | 1 | 2,264 | 0 | 82 | 2,182 | 1 | 2,181 | 365,600 | 3.4% |
| goedel_sft_v2 | 1 | 6,449 | 0 | 0 | 6,449 | 1,722 | 4,727 | 1,349,402 | 12.4% |
| numinamath_lean_kimina | 1 | 8,384 | 0 | 5 | 8,379 | 569 | 7,810 | 1,996,874 | 18.4% |
| numinamath_lean_human | 1 | 7,411 | 0 | 6 | 7,405 | 399 | 7,006 | 2,211,716 | 20.4% |
| leanabell_sft | 1 | 6,209 | 0 | 0 | 6,209 | 30 | 6,179 | 1,197,738 | 11.0% |

## Token lengths

| Split | Part | Examples | Tokens | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|---|
| train | prompt | 45,864 | 9,354,455 | 204 | 170 | 312 | 782 | 2035 |
| train | completion | 45,864 | 1,510,468 | 33 | 16 | 88 | 220 | 256 |
| train | total | 45,864 | 10,864,923 | 237 | 199 | 375 | 817 | 2077 |
| validation | prompt | 858 | 167,781 | 196 | 171 | 296 | 480 | 796 |
| validation | completion | 858 | 30,723 | 36 | 17 | 102 | 231 | 255 |
| validation | total | 858 | 198,504 | 231 | 207 | 379 | 579 | 802 |

| Source | Prompt mean | p50 | p90 | p99 | Max | Completion mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|---|---|---|
| goedel_lean_workbook_proofs | 172 | 156 | 246 | 470 | 1262 | 33 | 18 | 86 | 194 | 255 |
| stp_lean_workbook | 195 | 181 | 284 | 455 | 1414 | 32 | 18 | 81 | 190 | 256 |
| deepseek_prover_v1 | 167 | 150 | 234 | 431 | 1509 | 11 | 9 | 21 | 45 | 139 |
| lean_workbook | 154 | 140 | 209 | 410 | 870 | 14 | 12 | 27 | 43 | 176 |
| goedel_sft_v2 | 225 | 191 | 365 | 700 | 1261 | 60 | 19 | 181 | 247 | 256 |
| numinamath_lean_kimina | 212 | 183 | 334 | 602 | 1592 | 44 | 25 | 119 | 234 | 256 |
| numinamath_lean_human | 282 | 209 | 492 | 1476 | 2033 | 34 | 16 | 88 | 212 | 256 |
| leanabell_sft | 173 | 142 | 243 | 829 | 2035 | 20 | 12 | 44 | 144 | 250 |

Validation: 858 examples from 920 traced validation-split steps (statements held out by hash) after dropping 3 duplicates or pairs also present in train; by source: deepseek_prover_v1: 110, goedel_lean_workbook_proofs: 112, goedel_sft_v2: 133, lean_workbook: 33, leanabell_sft: 90, numinamath_lean_human: 157, numinamath_lean_kimina: 106, stp_lean_workbook: 117.
