# Reasoning run `phase5_eval_student_4b_nothinking`

512 traced train-split states, k=8 samples each from `student-4b` (adapter `None`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git b669b059b1.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 43.9% | 63.5% | 78.9% | 28.9% | 15.1% | 0 | 33 |

Generated tokens per success: 75; prompt tokens per state: 185. Reference states reached: 1 step(s): 613, 2 step(s): 3, 3 step(s): 0, 4 step(s): 0, 5 step(s): 0, 6 step(s): 0, 7 step(s): 0, 8 step(s): 0, 9 step(s): 0, 10 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 56 | 1.4% |
| error | 663 | 16.2% |
| timeout | 146 | 3.6% |
| no_progress | 12 | 0.3% |
| progress | 1420 | 34.7% |
| reference | 617 | 15.1% |
| closed | 1182 | 28.9% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 512 | 4040 | 44.5% | 63.5% | 80.0% | 29.3% | 15.3% | 0 | 30 |
| truncated | 38 | 56 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 42.7% | 57.8% | 79.5% | 36.2% | 6.5% | 0 | 29 |
| stp_lean_workbook | 256 | 2048 | 45.2% | 69.1% | 78.2% | 21.5% | 23.6% | 0 | 37 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 43.9% | 63.5% | 78.9% | 28.9% | 15.1% | 0 | 33 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 43.9% | 63.5% | 33 | 75 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 134,675 |
| sampling time | 0.9 min |
| samples/s | 78.2 |
| generated tokens/s | 2,570 |
| Lean execution time (overlaps sampling) | 7.5 min |
| Lean s / state | 8.25 |
