# Reasoning run `phase5_eval_bootstrap_sft_v2_thinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `policy-v2`), thinking on, temperature 0.8, at most 512 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 998d5d2fdd.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 16.3% | 32.6% | 22.3% | 15.3% | 1.1% | 386 | 400 |

Generated tokens per success: 2,450; prompt tokens per state: 180. Reference states reached: 1 step(s): 44.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 2694 | 65.8% |
| no_block | 320 | 7.8% |
| error | 168 | 4.1% |
| timeout | 2 | 0.0% |
| no_progress | 6 | 0.1% |
| progress | 237 | 5.8% |
| reference | 44 | 1.1% |
| closed | 625 | 15.3% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 16 | 16 | 31.2% | 31.2% | 75.0% | 12.5% | 18.8% | 0 | 71 |
| 1–31 | 112 | 228 | 33.8% | 41.1% | 37.3% | 32.9% | 0.9% | 19 | 32 |
| 32–63 | 102 | 219 | 59.4% | 64.7% | 64.8% | 58.4% | 0.9% | 47 | 59 |
| 64–127 | 129 | 247 | 59.1% | 64.3% | 73.3% | 57.5% | 1.6% | 92 | 113 |
| 128–191 | 109 | 178 | 59.0% | 67.0% | 77.0% | 55.1% | 3.9% | 157 | 183 |
| 192–255 | 120 | 172 | 48.3% | 55.0% | 69.2% | 41.3% | 7.0% | 221 | 256 |
| 256–383 | 141 | 209 | 34.4% | 41.8% | 67.5% | 31.1% | 3.3% | 315 | 349 |
| 384–511 | 112 | 133 | 38.3% | 39.3% | 71.4% | 33.1% | 5.3% | 437 | 458 |
| truncated | 449 | 2694 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 502 | 512 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 27.4% | 46.9% | 34.4% | 26.2% | 1.2% | 353 | 372 |
| stp_lean_workbook | 256 | 2048 | 5.3% | 18.4% | 10.2% | 4.3% | 0.9% | 418 | 429 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 16.3% | 32.6% | 22.3% | 15.3% | 1.1% | 386 | 400 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 198 | 403 | 37.5% | 47.0% | 79.4% | 31.3% | 6.2% | 218 | 258 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 12.7% | 26.0% | 219 | 1,728 | 425 | 35.1% |
| 512 | 16.3% | 32.6% | 400 | 2,450 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 286 examples from 161 states, reasoning tokens mean 128, median 83.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 1,639,104 |
| sampling time | 2.6 min |
| samples/s | 26.1 |
| generated tokens/s | 10,459 |
| Lean execution time (overlaps sampling) | 1.7 min |
| Lean s / state | 1.44 |
