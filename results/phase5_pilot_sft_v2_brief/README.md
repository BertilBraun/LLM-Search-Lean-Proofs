# Reasoning run `phase5_pilot_sft_v2_brief`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `policy-v2`), thinking on with the system prompt addition “Think briefly (a few sentences) about which tactic to use; do not restate the goal.”, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git c3d0e529b5.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 10.0% | 41.3% | 13.8% | 8.9% | 1.1% | 633 | 677 |

Generated tokens per success: 6,749; prompt tokens per state: 180. Reference states reached: 1 step(s): 44, 2 step(s): 2, 3 step(s): 0, 4 step(s): 0, 5 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 2036 | 49.8% |
| no_block | 611 | 14.9% |
| empty | 703 | 17.2% |
| error | 166 | 4.1% |
| timeout | 8 | 0.2% |
| no_progress | 9 | 0.2% |
| progress | 145 | 3.5% |
| reference | 47 | 1.1% |
| closed | 363 | 8.9% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 33 | 37 | 40.5% | 39.4% | 67.6% | 29.7% | 10.8% | 0 | 61 |
| 1–31 | 114 | 262 | 10.7% | 20.2% | 12.2% | 10.7% | 0.0% | 16 | 25 |
| 32–63 | 115 | 205 | 32.2% | 37.4% | 35.6% | 31.7% | 0.5% | 45 | 60 |
| 64–127 | 130 | 238 | 25.2% | 35.4% | 29.4% | 23.9% | 1.3% | 95 | 123 |
| 128–191 | 118 | 186 | 18.8% | 25.4% | 23.7% | 17.2% | 1.6% | 161 | 195 |
| 192–255 | 122 | 164 | 20.1% | 22.1% | 29.9% | 19.5% | 0.6% | 222 | 264 |
| 256–383 | 170 | 284 | 21.1% | 30.0% | 29.6% | 19.0% | 2.1% | 315 | 355 |
| 384–511 | 180 | 232 | 17.2% | 21.7% | 27.6% | 14.2% | 3.0% | 447 | 500 |
| 512–767 | 205 | 299 | 16.4% | 21.0% | 25.8% | 11.4% | 5.0% | 634 | 684 |
| 768–1023 | 125 | 145 | 16.6% | 17.6% | 31.7% | 11.7% | 4.8% | 873 | 904 |
| truncated | 458 | 2036 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 971 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 16.0% | 64.9% | 22.5% | 15.2% | 0.8% | 522 | 550 |
| goedel_lean_workbook_proofs | 73 | 584 | 9.8% | 42.5% | 13.0% | 8.9% | 0.9% | 656 | 707 |
| goedel_sft_v2 | 72 | 576 | 14.8% | 43.1% | 17.5% | 13.2% | 1.6% | 653 | 696 |
| lean_workbook | 73 | 584 | 11.8% | 52.1% | 16.4% | 11.1% | 0.7% | 611 | 655 |
| leanabell_sft | 73 | 584 | 9.8% | 38.4% | 12.5% | 8.6% | 1.2% | 557 | 611 |
| numinamath_lean_kimina | 73 | 584 | 4.5% | 27.4% | 7.4% | 2.7% | 1.7% | 670 | 729 |
| stp_lean_workbook | 73 | 584 | 3.6% | 20.5% | 7.2% | 2.4% | 1.2% | 765 | 792 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 1.3% | 8.3% | 3.1% | 0.8% | 0.5% | 864 | 892 |
| seen in SFT | 463 | 3704 | 10.9% | 44.7% | 14.9% | 9.7% | 1.2% | 609 | 655 |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 312 examples from 205 states, reasoning tokens mean 283, median 212.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 2,768,991 |
| sampling time | 8.3 min |
| samples/s | 8.2 |
| generated tokens/s | 5,566 |
| Lean execution time (overlaps sampling) | 3.6 min |
| Lean s / state | 1.45 |
