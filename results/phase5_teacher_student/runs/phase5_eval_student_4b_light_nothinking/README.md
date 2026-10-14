# Reasoning run `phase5_eval_student_4b_light_nothinking`

512 traced train-split states, k=8 samples each from `student-4b` (adapter `None`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 62c1d7a90a.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 43.4% | 61.7% | 78.1% | 27.7% | 15.7% | 0 | 34 |

Generated tokens per success: 78; prompt tokens per state: 185. Reference states reached: 1 step(s): 641, 2 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 71 | 1.7% |
| error | 674 | 16.5% |
| timeout | 151 | 3.7% |
| no_progress | 14 | 0.3% |
| progress | 1408 | 34.4% |
| reference | 642 | 15.7% |
| closed | 1136 | 27.7% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 512 | 4025 | 44.2% | 61.7% | 79.5% | 28.2% | 16.0% | 0 | 30 |
| truncated | 52 | 71 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 40.7% | 55.1% | 78.2% | 34.6% | 6.1% | 0 | 30 |
| stp_lean_workbook | 256 | 2048 | 46.1% | 68.4% | 78.1% | 20.8% | 25.2% | 0 | 38 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 43.4% | 61.7% | 78.1% | 27.7% | 15.7% | 0 | 34 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 43.4% | 61.7% | 34 | 78 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 139,298 |
| sampling time | 0.9 min |
| samples/s | 78.4 |
| generated tokens/s | 2,666 |
| Lean execution time (overlaps sampling) | 8.5 min |
| Lean s / state | 8.43 |
