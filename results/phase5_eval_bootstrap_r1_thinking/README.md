# Reasoning run `phase5_eval_bootstrap_r1_thinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `reasoning-r1`), thinking on, temperature 0.8, at most 512 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 998d5d2fdd.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 42.1% | 62.9% | 64.4% | 29.9% | 12.2% | 187 | 234 |

Generated tokens per success: 557; prompt tokens per state: 180. Reference states reached: 1 step(s): 499.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 611 | 14.9% |
| no_block | 9 | 0.2% |
| error | 697 | 17.0% |
| timeout | 141 | 3.4% |
| closed_early | 1 | 0.0% |
| no_progress | 12 | 0.3% |
| progress | 902 | 22.0% |
| reference | 499 | 12.2% |
| closed | 1224 | 29.9% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1–31 | 99 | 181 | 88.4% | 80.8% | 96.1% | 84.0% | 4.4% | 23 | 41 |
| 32–63 | 193 | 413 | 81.1% | 74.1% | 90.1% | 76.3% | 4.8% | 47 | 71 |
| 64–127 | 448 | 1191 | 49.2% | 57.1% | 75.5% | 32.9% | 16.3% | 97 | 144 |
| 128–191 | 410 | 958 | 39.7% | 49.0% | 70.9% | 21.3% | 18.4% | 154 | 207 |
| 192–255 | 270 | 402 | 33.3% | 38.5% | 65.9% | 20.4% | 12.9% | 221 | 280 |
| 256–383 | 185 | 256 | 37.1% | 41.1% | 70.7% | 23.0% | 14.1% | 305 | 353 |
| 384–511 | 73 | 84 | 39.3% | 41.1% | 79.8% | 23.8% | 15.5% | 427 | 455 |
| truncated | 282 | 611 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 453 | 512 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 46.9% | 58.6% | 68.2% | 39.5% | 7.4% | 168 | 217 |
| stp_lean_workbook | 256 | 2048 | 37.3% | 67.2% | 60.6% | 20.3% | 16.9% | 207 | 252 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 42.1% | 62.9% | 64.4% | 29.9% | 12.2% | 187 | 234 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 36.9% | 59.2% | 178 | 482 | 803 | 26.3% |
| 512 | 42.1% | 62.9% | 234 | 557 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 606 examples from 322 states, reasoning tokens mean 94, median 83.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 959,982 |
| sampling time | 1.8 min |
| samples/s | 37.7 |
| generated tokens/s | 8,847 |
| Lean execution time (overlaps sampling) | 7.9 min |
| Lean s / state | 8.10 |
