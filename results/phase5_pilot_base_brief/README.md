# Reasoning run `phase5_pilot_base_brief`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `None`), thinking on with the system prompt addition “Think briefly (a few sentences) about which tactic to use; do not restate the goal.”, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git c3d0e529b5.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 4.1% | 16.6% | 5.7% | 4.1% | 0.0% | 922 | 941 |

Generated tokens per success: 22,886; prompt tokens per state: 180. Reference states reached: 1 step(s): 2.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 3227 | 78.9% |
| no_block | 1 | 0.0% |
| forbidden | 34 | 0.8% |
| error | 554 | 13.6% |
| timeout | 1 | 0.0% |
| partial | 38 | 0.9% |
| no_progress | 7 | 0.2% |
| progress | 58 | 1.4% |
| reference | 2 | 0.0% |
| closed | 166 | 4.1% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 1 | 1 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 0 | 30 |
| 1–31 | 2 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 2 | 62 |
| 64–127 | 1 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 94 | 126 |
| 128–191 | 16 | 19 | 52.6% | 50.0% | 57.9% | 52.6% | 0.0% | 163 | 235 |
| 192–255 | 27 | 28 | 35.7% | 33.3% | 42.9% | 35.7% | 0.0% | 224 | 260 |
| 256–383 | 68 | 81 | 33.3% | 27.9% | 38.3% | 33.3% | 0.0% | 328 | 379 |
| 384–511 | 195 | 256 | 14.1% | 15.9% | 20.3% | 14.1% | 0.0% | 452 | 541 |
| 512–767 | 233 | 340 | 14.4% | 18.5% | 23.2% | 13.8% | 0.6% | 621 | 707 |
| 768–1023 | 111 | 132 | 26.5% | 28.8% | 35.6% | 26.5% | 0.0% | 857 | 900 |
| truncated | 511 | 3227 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 1020 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 7.1% | 27.0% | 9.5% | 7.1% | 0.0% | 904 | 918 |
| goedel_lean_workbook_proofs | 73 | 584 | 3.4% | 19.2% | 4.3% | 3.4% | 0.0% | 909 | 929 |
| goedel_sft_v2 | 72 | 576 | 3.1% | 12.5% | 4.5% | 3.1% | 0.0% | 935 | 953 |
| lean_workbook | 73 | 584 | 4.8% | 19.2% | 6.3% | 4.6% | 0.2% | 922 | 939 |
| leanabell_sft | 73 | 584 | 5.1% | 20.5% | 7.2% | 5.1% | 0.0% | 909 | 932 |
| numinamath_lean_kimina | 73 | 584 | 3.1% | 13.7% | 5.5% | 2.9% | 0.2% | 949 | 963 |
| stp_lean_workbook | 73 | 584 | 2.1% | 4.1% | 2.6% | 2.1% | 0.0% | 923 | 951 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 0.0% | 0.0% | 1.3% | 0.0% | 0.0% | 928 | 956 |
| seen in SFT | 463 | 3704 | 4.5% | 18.4% | 6.2% | 4.5% | 0.1% | 921 | 939 |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 125 examples from 84 states, reasoning tokens mean 506, median 486.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 3,851,782 |
| sampling time | 9.9 min |
| samples/s | 6.9 |
| generated tokens/s | 6,476 |
| Lean execution time (overlaps sampling) | 3.7 min |
| Lean s / state | 1.08 |
