# Reasoning run `phase5_size_bootstrap_2b`

512 traced train-split states, k=8 samples each from `probe-2b` (adapter `None`), thinking on, temperature 0.8, at most 4096 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git f6223c626d.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 44.3% | 64.6% | 69.6% | 31.2% | 13.0% | 345 | 420 |

Generated tokens per success: 949; prompt tokens per state: 180. Reference states reached: 1 step(s): 534.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 112 | 2.7% |
| no_block | 17 | 0.4% |
| error | 958 | 23.4% |
| timeout | 159 | 3.9% |
| no_progress | 27 | 0.7% |
| progress | 1009 | 24.6% |
| reference | 534 | 13.0% |
| closed | 1280 | 31.2% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1–31 | 98 | 178 | 88.2% | 84.7% | 94.4% | 83.7% | 4.5% | 23 | 40 |
| 32–63 | 182 | 408 | 82.4% | 74.2% | 88.5% | 76.0% | 6.4% | 46 | 72 |
| 64–127 | 453 | 1203 | 45.7% | 53.6% | 71.7% | 30.2% | 15.5% | 98 | 166 |
| 128–191 | 409 | 992 | 37.6% | 48.2% | 67.7% | 20.7% | 16.9% | 155 | 225 |
| 192–255 | 268 | 430 | 38.6% | 42.5% | 70.9% | 25.1% | 13.5% | 219 | 286 |
| 256–383 | 213 | 315 | 35.2% | 41.8% | 65.7% | 22.2% | 13.0% | 309 | 395 |
| 384–511 | 94 | 108 | 27.8% | 28.7% | 63.0% | 19.4% | 8.3% | 440 | 549 |
| 512–767 | 111 | 133 | 27.1% | 26.1% | 61.7% | 17.3% | 9.8% | 606 | 723 |
| 768–1023 | 51 | 55 | 27.3% | 29.4% | 61.8% | 12.7% | 14.5% | 877 | 988 |
| 1024–1535 | 55 | 62 | 32.3% | 30.9% | 58.1% | 19.4% | 12.9% | 1248 | 1332 |
| 1536–2047 | 38 | 40 | 22.5% | 23.7% | 50.0% | 15.0% | 7.5% | 1765 | 1915 |
| 2048–3071 | 28 | 31 | 16.1% | 17.9% | 58.1% | 12.9% | 3.2% | 2637 | 2702 |
| 3072+ | 26 | 29 | 20.7% | 23.1% | 58.6% | 6.9% | 13.8% | 3523 | 3587 |
| truncated | 84 | 112 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 3754 | 4096 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 47.7% | 60.2% | 71.6% | 39.6% | 8.1% | 266 | 358 |
| stp_lean_workbook | 256 | 2048 | 40.9% | 69.1% | 67.5% | 22.9% | 18.0% | 425 | 482 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 44.3% | 64.6% | 69.6% | 31.2% | 13.0% | 345 | 420 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 35.9% | 60.5% | 179 | 499 | 1317 | 26.2% |
| 512 | 41.7% | 64.3% | 235 | 564 | 504 | 21.4% |
| 1024 | 43.2% | 64.3% | 288 | 666 | 201 | 21.4% |
| 2048 | 44.0% | 64.6% | 347 | 789 | 73 | 17.8% |
| 4096 | 44.3% | 64.6% | 420 | 949 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 623 examples from 331 states, reasoning tokens mean 106, median 85.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 8 (8) |
| samples / generated tokens | 4,096 / 1,721,774 |
| sampling time | 7.5 min |
| samples/s | 9.1 |
| generated tokens/s | 3,837 |
| Lean execution time (overlaps sampling) | 14.7 min |
| Lean s / state | 9.62 |
