# Reasoning run `phase5_pilot_base_thinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `None`), thinking on, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git c3d0e529b5.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 3.7% | 13.9% | 4.9% | 3.7% | 0.0% | 886 | 929 |

Generated tokens per success: 25,047; prompt tokens per state: 160. Reference states reached: 1 step(s): 2.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 2988 | 72.9% |
| empty | 4 | 0.1% |
| forbidden | 93 | 2.3% |
| error | 767 | 18.7% |
| timeout | 1 | 0.0% |
| partial | 40 | 1.0% |
| closed_early | 1 | 0.0% |
| no_progress | 3 | 0.1% |
| progress | 47 | 1.1% |
| reference | 2 | 0.0% |
| closed | 150 | 3.7% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 1 | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 224 |
| 64–127 | 3 | 3 | 66.7% | 66.7% | 66.7% | 66.7% | 0.0% | 117 | 133 |
| 128–191 | 15 | 20 | 45.0% | 46.7% | 50.0% | 45.0% | 0.0% | 163 | 210 |
| 192–255 | 17 | 28 | 35.7% | 35.3% | 42.9% | 35.7% | 0.0% | 230 | 270 |
| 256–383 | 62 | 84 | 35.7% | 32.3% | 40.5% | 35.7% | 0.0% | 330 | 384 |
| 384–511 | 197 | 299 | 15.7% | 17.3% | 20.1% | 15.4% | 0.3% | 454 | 562 |
| 512–767 | 319 | 533 | 6.9% | 9.1% | 11.1% | 6.9% | 0.0% | 621 | 759 |
| 768–1023 | 121 | 140 | 12.1% | 14.0% | 17.9% | 11.4% | 0.7% | 849 | 930 |
| truncated | 505 | 2988 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 1006 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 6.6% | 27.0% | 8.6% | 6.4% | 0.2% | 849 | 885 |
| goedel_lean_workbook_proofs | 73 | 584 | 3.4% | 12.3% | 4.6% | 3.4% | 0.0% | 882 | 929 |
| goedel_sft_v2 | 73 | 584 | 2.6% | 15.1% | 3.3% | 2.6% | 0.0% | 903 | 952 |
| lean_workbook | 73 | 584 | 4.5% | 13.7% | 5.3% | 4.3% | 0.2% | 891 | 935 |
| leanabell_sft | 73 | 584 | 4.8% | 17.8% | 7.0% | 4.8% | 0.0% | 857 | 892 |
| numinamath_lean_kimina | 73 | 584 | 2.2% | 6.8% | 3.4% | 2.2% | 0.0% | 917 | 954 |
| stp_lean_workbook | 73 | 584 | 1.9% | 4.1% | 2.2% | 1.9% | 0.0% | 905 | 960 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 0.3% | 2.1% | 0.5% | 0.3% | 0.0% | 928 | 979 |
| seen in SFT | 464 | 3712 | 4.1% | 15.1% | 5.4% | 4.0% | 0.1% | 882 | 924 |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 105 examples from 71 states, reasoning tokens mean 478, median 448.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 3,807,080 |
| sampling time | 9.8 min |
| samples/s | 7.0 |
| generated tokens/s | 6,472 |
| Lean execution time (overlaps sampling) | 2.3 min |
| Lean s / state | 0.79 |
