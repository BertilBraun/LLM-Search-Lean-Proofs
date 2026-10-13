# Reasoning run `phase5_teacher_9b`

3072 traced train-split states, k=8 samples each from `teacher-9b` (adapter `None`), thinking on with the system prompt addition “Think briefly (a few sentences) about which tactic to use; do not restate the goal.”, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git d9a5e1debb.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 3072 | 24576 | 23.5% | 40.6% | 38.2% | 22.1% | 1.4% | 570 | 621 |

Generated tokens per success: 2,642; prompt tokens per state: 217. Reference states reached: 1 step(s): 319, 2 step(s): 14, 3 step(s): 1, 4 step(s): 0, 5 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 6108 | 24.9% |
| no_block | 3 | 0.0% |
| empty | 481 | 2.0% |
| forbidden | 282 | 1.1% |
| error | 5307 | 21.6% |
| timeout | 229 | 0.9% |
| partial | 2734 | 11.1% |
| closed_early | 53 | 0.2% |
| no_progress | 75 | 0.3% |
| progress | 3531 | 14.4% |
| reference | 335 | 1.4% |
| closed | 5438 | 22.1% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 32–63 | 44 | 52 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 54 | 66 |
| 64–127 | 261 | 493 | 96.3% | 94.6% | 98.2% | 96.3% | 0.0% | 99 | 112 |
| 128–191 | 471 | 901 | 89.3% | 85.6% | 94.3% | 89.0% | 0.3% | 162 | 176 |
| 192–255 | 715 | 1213 | 73.5% | 66.6% | 84.8% | 72.2% | 1.2% | 225 | 245 |
| 256–383 | 1587 | 3122 | 44.1% | 42.6% | 66.5% | 41.8% | 2.2% | 323 | 355 |
| 384–511 | 2717 | 8512 | 18.4% | 30.5% | 40.4% | 16.3% | 2.1% | 444 | 516 |
| 512–767 | 1912 | 3528 | 14.4% | 20.5% | 33.4% | 12.7% | 1.7% | 596 | 680 |
| 768–1023 | 561 | 647 | 15.6% | 17.8% | 41.0% | 14.7% | 0.9% | 854 | 907 |
| truncated | 2399 | 6108 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 998 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 1682 | 13456 | 30.8% | 47.2% | 45.3% | 30.6% | 0.3% | 551 | 596 |
| stp_lean_workbook | 1390 | 11120 | 14.6% | 32.5% | 29.6% | 11.9% | 2.7% | 593 | 651 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 3072 | 24576 | 23.5% | 40.6% | 38.2% | 22.1% | 1.4% | 570 | 621 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 8.2% | 18.6% | 249 | 3,021 | 16159 | 23.2% |
| 512 | 20.0% | 34.8% | 446 | 2,227 | 7384 | 11.5% |
| 1024 | 23.5% | 40.6% | 621 | 2,642 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 2,269 examples from 1,246 states, reasoning tokens mean 301, median 287.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 12 (12) |
| samples / generated tokens | 24,576 / 15,254,025 |
| sampling time | 88.7 min |
| samples/s | 4.6 |
| generated tokens/s | 2,867 |
| Lean execution time (overlaps sampling) | 31.3 min |
| Lean s / state | 6.94 |
