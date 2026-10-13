# Reasoning run `phase5_bootstrap_r1_nothinking`

4000 traced train-split states, k=4 samples each from `search-qwen3.5-2b` (adapter `policy-v2`), thinking off, temperature 0.8, at most 256 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 998d5d2fdd.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 4000 | 16000 | 42.3% | 55.1% | 76.3% | 24.2% | 18.1% | 0 | 40 |

Generated tokens per success: 95; prompt tokens per state: 201. Reference states reached: 1 step(s): 2871, 2 step(s): 22, 3 step(s): 1, 4 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 525 | 3.3% |
| forbidden | 1 | 0.0% |
| error | 2623 | 16.4% |
| timeout | 642 | 4.0% |
| no_progress | 91 | 0.6% |
| progress | 5345 | 33.4% |
| reference | 2895 | 18.1% |
| closed | 3878 | 24.2% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 3987 | 15475 | 43.8% | 55.3% | 78.9% | 25.1% | 18.7% | 0 | 33 |
| truncated | 336 | 525 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 256 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 2000 | 8000 | 39.9% | 47.6% | 74.8% | 32.1% | 7.9% | 0 | 44 |
| stp_lean_workbook | 2000 | 8000 | 44.7% | 62.7% | 77.8% | 16.4% | 28.3% | 0 | 37 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 4000 | 16000 | 42.3% | 55.1% | 76.3% | 24.2% | 18.1% | 0 | 40 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 42.3% | 55.1% | 40 | 95 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 16 (16) |
| samples / generated tokens | 16,000 / 645,676 |
| sampling time | 18.0 min |
| samples/s | 14.8 |
| generated tokens/s | 598 |
| Lean execution time (overlaps sampling) | 56.9 min |
| Lean s / state | 5.97 |
