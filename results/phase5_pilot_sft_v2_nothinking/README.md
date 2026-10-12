# Reasoning run `phase5_pilot_sft_v2_nothinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `policy-v2`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git c3d0e529b5.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 48.2% | 74.8% | 81.3% | 30.7% | 17.6% | 0 | 32 |

Generated tokens per success: 67; prompt tokens per state: 165. Reference states reached: 1 step(s): 700, 2 step(s): 18.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 57 | 1.4% |
| error | 577 | 14.1% |
| timeout | 128 | 3.1% |
| closed_early | 1 | 0.0% |
| no_progress | 45 | 1.1% |
| progress | 1309 | 32.0% |
| reference | 718 | 17.6% |
| closed | 1253 | 30.7% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 511 | 4031 | 48.9% | 74.8% | 82.5% | 31.1% | 17.8% | 0 | 29 |
| truncated | 33 | 57 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 57.4% | 90.5% | 94.6% | 44.3% | 13.2% | 0 | 11 |
| goedel_lean_workbook_proofs | 73 | 584 | 48.3% | 79.5% | 76.2% | 28.9% | 19.3% | 0 | 39 |
| goedel_sft_v2 | 72 | 576 | 45.0% | 61.1% | 72.9% | 31.2% | 13.7% | 0 | 47 |
| lean_workbook | 73 | 584 | 58.9% | 94.5% | 89.7% | 46.4% | 12.5% | 0 | 31 |
| leanabell_sft | 73 | 584 | 50.2% | 76.7% | 86.3% | 28.3% | 21.9% | 0 | 24 |
| numinamath_lean_kimina | 73 | 584 | 36.0% | 56.2% | 72.4% | 18.5% | 17.5% | 0 | 37 |
| stp_lean_workbook | 73 | 584 | 41.6% | 64.4% | 76.9% | 16.8% | 24.8% | 0 | 37 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 22.4% | 31.2% | 63.8% | 7.6% | 14.8% | 0 | 62 |
| seen in SFT | 463 | 3704 | 50.9% | 79.3% | 83.2% | 33.0% | 17.8% | 0 | 29 |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 132,219 |
| sampling time | 0.9 min |
| samples/s | 72.6 |
| generated tokens/s | 2,344 |
| Lean execution time (overlaps sampling) | 11.0 min |
| Lean s / state | 7.72 |
