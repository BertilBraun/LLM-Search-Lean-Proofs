# Reasoning run `phase5_pilot_sft_v2_thinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `policy-v2`), thinking on, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git c3d0e529b5.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 12.5% | 41.7% | 16.6% | 10.9% | 1.6% | 656 | 693 |

Generated tokens per success: 5,543; prompt tokens per state: 160. Reference states reached: 1 step(s): 61, 2 step(s): 2, 3 step(s): 0, 4 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 2105 | 51.5% |
| no_block | 452 | 11.1% |
| empty | 687 | 16.8% |
| error | 151 | 3.7% |
| timeout | 14 | 0.3% |
| no_progress | 10 | 0.2% |
| progress | 158 | 3.9% |
| reference | 64 | 1.6% |
| closed | 447 | 10.9% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 15 | 15 | 40.0% | 40.0% | 60.0% | 20.0% | 20.0% | 0 | 61 |
| 1–31 | 112 | 234 | 13.7% | 22.3% | 14.5% | 12.8% | 0.9% | 17 | 24 |
| 32–63 | 96 | 162 | 34.6% | 38.5% | 36.4% | 32.1% | 2.5% | 47 | 60 |
| 64–127 | 133 | 208 | 34.1% | 36.8% | 38.0% | 32.2% | 1.9% | 93 | 111 |
| 128–191 | 125 | 212 | 23.6% | 34.4% | 29.2% | 21.7% | 1.9% | 158 | 187 |
| 192–255 | 121 | 177 | 33.3% | 39.7% | 40.1% | 32.8% | 0.6% | 222 | 255 |
| 256–383 | 185 | 289 | 29.4% | 36.2% | 40.8% | 25.6% | 3.8% | 319 | 357 |
| 384–511 | 176 | 236 | 26.3% | 29.5% | 39.0% | 19.1% | 7.2% | 446 | 488 |
| 512–767 | 214 | 305 | 17.7% | 22.9% | 33.1% | 14.4% | 3.3% | 623 | 665 |
| 768–1023 | 126 | 145 | 24.8% | 27.8% | 37.2% | 19.3% | 5.5% | 877 | 908 |
| truncated | 446 | 2105 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 981 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 19.6% | 63.5% | 27.5% | 18.8% | 0.8% | 552 | 583 |
| goedel_lean_workbook_proofs | 73 | 584 | 12.3% | 38.4% | 14.9% | 11.1% | 1.2% | 693 | 733 |
| goedel_sft_v2 | 72 | 576 | 19.1% | 47.2% | 23.3% | 17.4% | 1.7% | 667 | 703 |
| lean_workbook | 73 | 584 | 10.4% | 49.3% | 14.6% | 9.6% | 0.9% | 656 | 695 |
| leanabell_sft | 73 | 584 | 16.6% | 50.7% | 20.4% | 13.0% | 3.6% | 563 | 617 |
| numinamath_lean_kimina | 73 | 584 | 4.3% | 21.9% | 7.5% | 2.7% | 1.5% | 661 | 705 |
| stp_lean_workbook | 73 | 584 | 5.1% | 20.5% | 8.0% | 3.9% | 1.2% | 802 | 816 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 0.8% | 4.2% | 4.7% | 0.8% | 0.0% | 893 | 916 |
| seen in SFT | 463 | 3704 | 13.7% | 45.6% | 17.8% | 12.0% | 1.7% | 632 | 670 |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 317 examples from 207 states, reasoning tokens mean 302, median 252.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 2,833,179 |
| sampling time | 8.4 min |
| samples/s | 8.1 |
| generated tokens/s | 5,598 |
| Lean execution time (overlaps sampling) | 3.8 min |
| Lean s / state | 1.47 |
