# Reasoning run `phase5_visible_teacher_9b`

6144 traced train-split states, k=8 samples each from `teacher-9b` (adapter `None`), thinking off, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git 5d825a08ca.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 6143 | 49144 | 26.1% | 43.4% | 36.5% | 25.5% | 0.6% | 260 | 378 |

Generated tokens per success: 1,448; prompt tokens per state: 207. Reference states reached: 1 step(s): 281, 2 step(s): 23, 3 step(s): 6, 4 step(s): 0, 5 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 1486 | 3.0% |
| no_block | 9 | 0.0% |
| empty | 13 | 0.0% |
| forbidden | 1428 | 2.9% |
| error | 15454 | 31.4% |
| timeout | 858 | 1.7% |
| partial | 11729 | 23.9% |
| closed_early | 208 | 0.4% |
| no_progress | 118 | 0.2% |
| progress | 5008 | 10.2% |
| reference | 311 | 0.6% |
| closed | 12522 | 25.5% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 6 | 6 | 16.7% | 16.7% | 16.7% | 16.7% | 0.0% | 0 | 200 |
| 1–31 | 82 | 101 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 28 | 38 |
| 32–63 | 957 | 2987 | 96.1% | 91.5% | 96.6% | 96.0% | 0.1% | 51 | 64 |
| 64–127 | 4346 | 12842 | 43.7% | 40.4% | 51.9% | 43.2% | 0.5% | 99 | 169 |
| 128–191 | 4911 | 13789 | 15.3% | 25.6% | 28.3% | 14.6% | 0.7% | 157 | 276 |
| 192–255 | 3637 | 6369 | 12.4% | 16.7% | 25.5% | 11.5% | 0.8% | 219 | 354 |
| 256–383 | 2766 | 4332 | 13.9% | 17.2% | 26.1% | 13.1% | 0.8% | 305 | 452 |
| 384–511 | 1284 | 1604 | 16.2% | 17.9% | 27.1% | 15.3% | 0.9% | 441 | 589 |
| 512–767 | 1321 | 1665 | 13.4% | 15.1% | 26.0% | 12.7% | 0.7% | 624 | 766 |
| 768–1023 | 758 | 893 | 12.0% | 13.3% | 27.4% | 11.2% | 0.8% | 910 | 999 |
| 1024–1535 | 1602 | 3070 | 4.9% | 7.9% | 17.3% | 4.2% | 0.6% | 1024 | 1164 |
| truncated | 1011 | 1486 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 505 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 3071 | 24568 | 35.2% | 50.2% | 43.4% | 35.1% | 0.1% | 235 | 348 |
| stp_lean_workbook | 3072 | 24576 | 17.0% | 36.6% | 29.7% | 15.8% | 1.2% | 284 | 408 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 6143 | 49144 | 26.1% | 43.4% | 36.5% | 25.5% | 0.6% | 260 | 378 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 21.9% | 35.5% | 204 | 933 | 23088 | 9.0% |
| 512 | 24.8% | 41.0% | 288 | 1,163 | 9547 | 6.8% |
| 1024 | 25.8% | 42.7% | 369 | 1,430 | 3326 | 4.9% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 4,738 examples from 2,622 states, reasoning tokens mean 126, median 94.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 24 (24) |
| samples / generated tokens | 49,152 / 18,588,115 |
| sampling time | 133.7 min |
| samples/s | 6.1 |
| generated tokens/s | 2,317 |
| Lean execution time (overlaps sampling) | 117.1 min |
| Lean s / state | 14.48 |
