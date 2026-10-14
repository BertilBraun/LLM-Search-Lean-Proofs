# Reasoning run `phase5_eval_student_4b_light_thinking`

512 traced train-split states, k=8 samples each from `student-4b` (adapter `None`), thinking on, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 62c1d7a90a.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 36.0% | 59.8% | 56.9% | 32.4% | 3.6% | 280 | 333 |

Generated tokens per success: 925; prompt tokens per state: 180. Reference states reached: 1 step(s): 136, 2 step(s): 10, 3 step(s): 0, 4 step(s): 0, 5 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 86 | 2.1% |
| error | 1131 | 27.6% |
| timeout | 98 | 2.4% |
| partial | 430 | 10.5% |
| closed_early | 22 | 0.5% |
| no_progress | 14 | 0.3% |
| progress | 840 | 20.5% |
| reference | 147 | 3.6% |
| closed | 1328 | 32.4% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1–31 | 4 | 4 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 28 | 40 |
| 32–63 | 36 | 44 | 88.6% | 86.1% | 97.7% | 86.4% | 2.3% | 52 | 76 |
| 64–127 | 223 | 446 | 67.9% | 57.8% | 79.1% | 65.9% | 2.0% | 103 | 126 |
| 128–191 | 416 | 934 | 42.7% | 46.4% | 61.6% | 39.1% | 3.6% | 162 | 203 |
| 192–255 | 400 | 780 | 34.5% | 41.5% | 51.9% | 31.3% | 3.2% | 221 | 280 |
| 256–383 | 414 | 991 | 29.3% | 39.1% | 52.1% | 24.6% | 4.6% | 311 | 373 |
| 384–511 | 316 | 574 | 22.1% | 28.5% | 54.4% | 17.2% | 4.9% | 433 | 479 |
| 512–767 | 140 | 200 | 20.0% | 24.3% | 53.5% | 18.0% | 2.0% | 599 | 654 |
| 768–1023 | 31 | 37 | 10.8% | 12.9% | 37.8% | 10.8% | 0.0% | 852 | 891 |
| truncated | 60 | 86 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 795 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 44.5% | 63.3% | 64.3% | 43.4% | 1.1% | 278 | 329 |
| stp_lean_workbook | 256 | 2048 | 27.5% | 56.2% | 49.5% | 21.5% | 6.1% | 282 | 337 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 36.0% | 59.8% | 56.9% | 32.4% | 3.6% | 280 | 333 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 22.7% | 45.9% | 223 | 981 | 2276 | 23.9% |
| 512 | 34.4% | 57.2% | 306 | 891 | 456 | 14.9% |
| 1024 | 36.0% | 59.8% | 333 | 925 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 551 examples from 306 states, reasoning tokens mean 191, median 161.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 1,363,786 |
| sampling time | 5.0 min |
| samples/s | 13.7 |
| generated tokens/s | 4,573 |
| Lean execution time (overlaps sampling) | 7.7 min |
| Lean s / state | 9.53 |
