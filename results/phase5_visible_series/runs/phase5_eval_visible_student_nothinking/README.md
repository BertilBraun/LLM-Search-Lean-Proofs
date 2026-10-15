# Reasoning run `phase5_eval_visible_student_nothinking`

512 traced train-split states, k=8 samples each from `visible-student` (adapter `None`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git fc7b4c2587.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 47.4% | 64.8% | 79.6% | 30.5% | 16.8% | 0 | 34 |

Generated tokens per success: 71; prompt tokens per state: 185. Reference states reached: 1 step(s): 688, 2 step(s): 0, 3 step(s): 0, 4 step(s): 0, 5 step(s): 0, 6 step(s): 0, 7 step(s): 0, 8 step(s): 0, 9 step(s): 0, 10 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 61 | 1.5% |
| error | 629 | 15.4% |
| timeout | 145 | 3.5% |
| no_progress | 12 | 0.3% |
| progress | 1309 | 32.0% |
| reference | 689 | 16.8% |
| closed | 1251 | 30.5% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 512 | 4035 | 48.1% | 64.8% | 80.8% | 31.0% | 17.1% | 0 | 30 |
| truncated | 34 | 61 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 48.3% | 59.4% | 80.9% | 39.7% | 8.5% | 0 | 30 |
| stp_lean_workbook | 256 | 2048 | 46.4% | 70.3% | 78.3% | 21.3% | 25.1% | 0 | 37 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 47.4% | 64.8% | 79.6% | 30.5% | 16.8% | 0 | 34 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 47.4% | 64.8% | 34 | 71 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 138,155 |
| sampling time | 0.9 min |
| samples/s | 79.1 |
| generated tokens/s | 2,668 |
| Lean execution time (overlaps sampling) | 8.3 min |
| Lean s / state | 8.62 |
