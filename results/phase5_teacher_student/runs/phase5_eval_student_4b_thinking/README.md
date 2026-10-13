# Reasoning run `phase5_eval_student_4b_thinking`

512 traced train-split states, k=8 samples each from `student-4b` (adapter `None`), thinking on, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git b669b059b1.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 37.8% | 59.0% | 58.4% | 34.2% | 3.7% | 143 | 202 |

Generated tokens per success: 535; prompt tokens per state: 180. Reference states reached: 1 step(s): 139, 2 step(s): 11.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 43 | 1.0% |
| forbidden | 1 | 0.0% |
| error | 1077 | 26.3% |
| timeout | 137 | 3.3% |
| partial | 422 | 10.3% |
| closed_early | 23 | 0.6% |
| no_progress | 17 | 0.4% |
| progress | 827 | 20.2% |
| reference | 150 | 3.7% |
| closed | 1399 | 34.2% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1–31 | 44 | 55 | 81.8% | 79.5% | 92.7% | 76.4% | 5.5% | 26 | 42 |
| 32–63 | 370 | 869 | 40.2% | 48.4% | 64.2% | 35.1% | 5.1% | 50 | 93 |
| 64–127 | 488 | 1773 | 31.2% | 48.0% | 50.8% | 28.0% | 3.3% | 89 | 155 |
| 128–191 | 310 | 559 | 52.2% | 49.7% | 64.9% | 50.1% | 2.1% | 155 | 218 |
| 192–255 | 178 | 252 | 56.3% | 56.2% | 70.2% | 54.4% | 2.0% | 220 | 258 |
| 256–383 | 189 | 274 | 37.6% | 41.8% | 67.9% | 29.9% | 7.7% | 315 | 354 |
| 384–511 | 138 | 208 | 25.5% | 32.6% | 59.6% | 22.1% | 3.4% | 437 | 483 |
| 512–767 | 45 | 57 | 17.5% | 20.0% | 52.6% | 17.5% | 0.0% | 592 | 649 |
| 768–1023 | 6 | 6 | 16.7% | 16.7% | 50.0% | 16.7% | 0.0% | 874 | 926 |
| truncated | 40 | 43 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 579 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 45.2% | 59.8% | 65.0% | 44.3% | 0.9% | 163 | 221 |
| stp_lean_workbook | 256 | 2048 | 30.4% | 58.2% | 51.9% | 24.0% | 6.4% | 123 | 183 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 37.8% | 59.0% | 58.4% | 34.2% | 3.7% | 143 | 202 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 32.7% | 56.1% | 158 | 484 | 871 | 24.1% |
| 512 | 37.3% | 58.2% | 191 | 511 | 183 | 12.0% |
| 1024 | 37.8% | 59.0% | 202 | 535 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 550 examples from 302 states, reasoning tokens mean 87, median 64.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 827,988 |
| sampling time | 3.5 min |
| samples/s | 19.3 |
| generated tokens/s | 3,907 |
| Lean execution time (overlaps sampling) | 9.4 min |
| Lean s / state | 10.66 |
