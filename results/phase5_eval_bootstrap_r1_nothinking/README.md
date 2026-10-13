# Reasoning run `phase5_eval_bootstrap_r1_nothinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `reasoning-r1`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 998d5d2fdd.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 46.0% | 64.6% | 79.4% | 28.9% | 17.1% | 0 | 41 |

Generated tokens per success: 90; prompt tokens per state: 185. Reference states reached: 1 step(s): 700, 2 step(s): 0, 3 step(s): 0, 4 step(s): 0, 5 step(s): 0, 6 step(s): 0, 7 step(s): 0, 8 step(s): 0, 9 step(s): 0, 10 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 118 | 2.9% |
| error | 615 | 15.0% |
| timeout | 110 | 2.7% |
| no_progress | 13 | 0.3% |
| progress | 1356 | 33.1% |
| reference | 701 | 17.1% |
| closed | 1183 | 28.9% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 512 | 3978 | 47.4% | 64.6% | 81.8% | 29.7% | 17.6% | 0 | 35 |
| truncated | 60 | 118 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 46.2% | 57.0% | 76.8% | 37.5% | 8.7% | 0 | 44 |
| stp_lean_workbook | 256 | 2048 | 45.8% | 72.3% | 82.1% | 20.3% | 25.5% | 0 | 38 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 46.0% | 64.6% | 79.4% | 28.9% | 17.1% | 0 | 41 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 46.0% | 64.6% | 41 | 90 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 168,940 |
| sampling time | 0.6 min |
| samples/s | 112.2 |
| generated tokens/s | 4,628 |
| Lean execution time (overlaps sampling) | 8.0 min |
| Lean s / state | 7.34 |
