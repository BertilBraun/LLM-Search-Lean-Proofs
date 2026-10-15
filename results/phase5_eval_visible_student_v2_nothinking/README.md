# Reasoning run `phase5_eval_visible_student_v2_nothinking`

512 traced train-split states, k=8 samples each from `visible-student` (adapter `None`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 131b69ffd8.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 45.7% | 62.7% | 77.3% | 30.1% | 15.6% | 0 | 35 |

Generated tokens per success: 76; prompt tokens per state: 185. Reference states reached: 1 step(s): 637.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 67 | 1.6% |
| error | 697 | 17.0% |
| timeout | 166 | 4.1% |
| no_progress | 13 | 0.3% |
| progress | 1283 | 31.3% |
| reference | 637 | 15.6% |
| closed | 1233 | 30.1% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 512 | 4029 | 46.4% | 62.7% | 78.6% | 30.6% | 15.8% | 0 | 31 |
| truncated | 39 | 67 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 47.2% | 60.2% | 79.6% | 38.9% | 8.3% | 0 | 30 |
| stp_lean_workbook | 256 | 2048 | 44.1% | 65.2% | 75.0% | 21.3% | 22.8% | 0 | 39 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 45.7% | 62.7% | 77.3% | 30.1% | 15.6% | 0 | 35 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 45.7% | 62.7% | 35 | 76 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 142,113 |
| sampling time | 0.9 min |
| samples/s | 77.9 |
| generated tokens/s | 2,702 |
| Lean execution time (overlaps sampling) | 8.1 min |
| Lean s / state | 9.16 |
