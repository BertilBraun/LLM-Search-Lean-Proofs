# Reasoning run `phase5_eval_visible_student_visible`

512 traced train-split states, k=8 samples each from `visible-student` (adapter `None`), thinking off, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git fc7b4c2587.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 44.6% | 63.3% | 62.8% | 37.5% | 7.2% | 125 | 190 |

Generated tokens per success: 427; prompt tokens per state: 191. Reference states reached: 1 step(s): 286, 2 step(s): 5, 3 step(s): 0, 4 step(s): 2.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 21 | 0.5% |
| no_block | 1 | 0.0% |
| empty | 2 | 0.0% |
| error | 968 | 23.6% |
| timeout | 142 | 3.5% |
| partial | 376 | 9.2% |
| closed_early | 13 | 0.3% |
| no_progress | 3 | 0.1% |
| progress | 742 | 18.1% |
| reference | 293 | 7.2% |
| closed | 1535 | 37.5% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1–31 | 277 | 658 | 50.9% | 52.0% | 78.9% | 40.4% | 10.5% | 21 | 48 |
| 32–63 | 354 | 883 | 65.8% | 57.1% | 80.0% | 58.4% | 7.4% | 47 | 77 |
| 64–127 | 417 | 1145 | 48.0% | 55.2% | 63.6% | 41.1% | 6.9% | 93 | 158 |
| 128–191 | 336 | 719 | 28.2% | 36.9% | 46.7% | 22.1% | 6.1% | 156 | 251 |
| 192–255 | 203 | 314 | 24.2% | 28.6% | 44.3% | 21.0% | 3.2% | 218 | 338 |
| 256–383 | 149 | 211 | 28.0% | 30.9% | 41.7% | 19.4% | 8.5% | 308 | 408 |
| 384–511 | 50 | 57 | 22.8% | 26.0% | 43.9% | 17.5% | 5.3% | 441 | 526 |
| 512–767 | 40 | 52 | 13.5% | 15.0% | 40.4% | 7.7% | 5.8% | 629 | 711 |
| 768–1023 | 8 | 8 | 12.5% | 12.5% | 25.0% | 0.0% | 12.5% | 904 | 940 |
| 1024–1535 | 20 | 28 | 10.7% | 15.0% | 32.1% | 7.1% | 3.6% | 1024 | 1091 |
| truncated | 17 | 21 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 458 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 51.3% | 62.9% | 69.0% | 45.9% | 5.4% | 110 | 172 |
| stp_lean_workbook | 256 | 2048 | 37.9% | 63.7% | 56.6% | 29.1% | 8.9% | 139 | 209 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 44.6% | 63.3% | 62.8% | 37.5% | 7.2% | 125 | 190 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 40.3% | 58.6% | 145 | 360 | 941 | 18.8% |
| 512 | 44.1% | 62.3% | 176 | 399 | 214 | 9.8% |
| 1024 | 44.6% | 63.1% | 190 | 426 | 29 | 10.3% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 613 examples from 323 states, reasoning tokens mean 74, median 50.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 779,891 |
| sampling time | 3.5 min |
| samples/s | 19.4 |
| generated tokens/s | 3,688 |
| Lean execution time (overlaps sampling) | 9.4 min |
| Lean s / state | 12.43 |
