# Reasoning run `phase5_eval_visible_student_v2_visible`

512 traced train-split states, k=8 samples each from `visible-student` (adapter `None`), thinking off, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 131b69ffd8.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 42.1% | 61.7% | 61.3% | 36.2% | 5.9% | 140 | 211 |

Generated tokens per success: 500; prompt tokens per state: 191. Reference states reached: 1 step(s): 234, 2 step(s): 6.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 32 | 0.8% |
| empty | 4 | 0.1% |
| error | 969 | 23.7% |
| timeout | 133 | 3.2% |
| partial | 439 | 10.7% |
| closed_early | 7 | 0.2% |
| no_progress | 3 | 0.1% |
| progress | 786 | 19.2% |
| reference | 240 | 5.9% |
| closed | 1483 | 36.2% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1–31 | 190 | 344 | 52.3% | 55.3% | 80.5% | 39.8% | 12.5% | 21 | 47 |
| 32–63 | 324 | 806 | 68.1% | 55.2% | 85.9% | 62.8% | 5.3% | 48 | 73 |
| 64–127 | 439 | 1263 | 45.6% | 51.3% | 63.8% | 39.2% | 6.4% | 94 | 153 |
| 128–191 | 369 | 867 | 26.6% | 39.3% | 44.9% | 22.7% | 3.9% | 156 | 253 |
| 192–255 | 228 | 381 | 22.3% | 26.8% | 41.2% | 17.1% | 5.2% | 218 | 332 |
| 256–383 | 169 | 241 | 27.0% | 31.4% | 48.5% | 22.0% | 5.0% | 304 | 396 |
| 384–511 | 57 | 65 | 24.6% | 26.3% | 47.7% | 20.0% | 4.6% | 444 | 540 |
| 512–767 | 40 | 44 | 29.5% | 27.5% | 50.0% | 22.7% | 6.8% | 603 | 714 |
| 768–1023 | 23 | 23 | 21.7% | 21.7% | 52.2% | 17.4% | 4.3% | 875 | 914 |
| 1024–1535 | 23 | 30 | 10.0% | 13.0% | 30.0% | 10.0% | 0.0% | 1024 | 1078 |
| truncated | 23 | 32 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 377 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 49.4% | 63.7% | 68.8% | 45.1% | 4.3% | 123 | 191 |
| stp_lean_workbook | 256 | 2048 | 34.7% | 59.8% | 53.9% | 27.3% | 7.4% | 158 | 230 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 42.1% | 61.7% | 61.3% | 36.2% | 5.9% | 140 | 211 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 37.2% | 57.4% | 157 | 421 | 1086 | 18.3% |
| 512 | 41.3% | 60.5% | 193 | 466 | 231 | 13.0% |
| 1024 | 42.0% | 61.7% | 210 | 501 | 33 | 12.1% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 596 examples from 315 states, reasoning tokens mean 83, median 59.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 862,255 |
| sampling time | 3.7 min |
| samples/s | 18.3 |
| generated tokens/s | 3,860 |
| Lean execution time (overlaps sampling) | 9.6 min |
| Lean s / state | 12.28 |
