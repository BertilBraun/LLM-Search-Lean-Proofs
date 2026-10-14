# Reasoning run `phase5_eval_sft_4b_nothinking`

512 traced train-split states, k=8 samples each from `sft-4b-base` (adapter `sft-4b`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git f9e2911576.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 45.1% | 64.1% | 78.5% | 28.4% | 16.7% | 0 | 38 |

Generated tokens per success: 83; prompt tokens per state: 185. Reference states reached: 1 step(s): 683, 2 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 85 | 2.1% |
| forbidden | 1 | 0.0% |
| error | 652 | 15.9% |
| timeout | 143 | 3.5% |
| no_progress | 12 | 0.3% |
| progress | 1356 | 33.1% |
| reference | 684 | 16.7% |
| closed | 1163 | 28.4% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 512 | 4011 | 46.0% | 64.1% | 80.2% | 29.0% | 17.1% | 0 | 33 |
| truncated | 47 | 85 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 45.3% | 59.0% | 78.6% | 37.1% | 8.2% | 0 | 37 |
| stp_lean_workbook | 256 | 2048 | 44.9% | 69.1% | 78.4% | 19.7% | 25.2% | 0 | 38 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 45.1% | 64.1% | 78.5% | 28.4% | 16.7% | 0 | 38 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 45.1% | 64.1% | 38 | 83 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 153,702 |
| sampling time | 1.9 min |
| samples/s | 36.3 |
| generated tokens/s | 1,364 |
| Lean execution time (overlaps sampling) | 7.9 min |
| Lean s / state | 8.47 |
