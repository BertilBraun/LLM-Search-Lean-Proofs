# Reasoning run `phase5_visible_probe_student`

512 traced train-split states, k=8 samples each from `base-4b` (adapter `student-r2`), thinking off, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 5d825a08ca.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 37.5% | 64.5% | 64.1% | 30.9% | 6.5% | 106 | 153 |

Generated tokens per success: 408; prompt tokens per state: 191. Reference states reached: 1 step(s): 258, 2 step(s): 10.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 13 | 0.3% |
| no_block | 1 | 0.0% |
| empty | 2 | 0.0% |
| forbidden | 4 | 0.1% |
| error | 1099 | 26.8% |
| timeout | 85 | 2.1% |
| partial | 256 | 6.2% |
| closed_early | 9 | 0.2% |
| no_progress | 26 | 0.6% |
| progress | 1067 | 26.0% |
| reference | 268 | 6.5% |
| closed | 1266 | 30.9% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 368 | 650 | 47.1% | 51.9% | 80.9% | 28.2% | 18.9% | 0 | 32 |
| 1–31 | 41 | 59 | 94.9% | 92.7% | 98.3% | 94.9% | 0.0% | 25 | 37 |
| 32–63 | 164 | 446 | 88.3% | 75.0% | 93.5% | 85.9% | 2.5% | 49 | 63 |
| 64–127 | 461 | 1494 | 35.5% | 52.5% | 65.1% | 29.9% | 5.6% | 98 | 136 |
| 128–191 | 391 | 1029 | 18.7% | 32.0% | 47.8% | 14.6% | 4.1% | 155 | 215 |
| 192–255 | 181 | 282 | 12.4% | 14.4% | 40.1% | 10.6% | 1.8% | 216 | 292 |
| 256–383 | 81 | 95 | 17.9% | 18.5% | 41.1% | 14.7% | 3.2% | 295 | 384 |
| 384–511 | 12 | 13 | 15.4% | 16.7% | 23.1% | 15.4% | 0.0% | 433 | 559 |
| 512–767 | 10 | 11 | 18.2% | 20.0% | 54.5% | 9.1% | 9.1% | 580 | 624 |
| 768–1023 | 2 | 2 | 0.0% | 0.0% | 50.0% | 0.0% | 0.0% | 921 | 1010 |
| 1024–1535 | 2 | 2 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 1024 | 1072 |
| truncated | 12 | 13 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 187 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 42.1% | 61.7% | 67.5% | 40.1% | 2.1% | 101 | 148 |
| stp_lean_workbook | 256 | 2048 | 32.8% | 67.2% | 60.7% | 21.7% | 11.0% | 112 | 158 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 37.5% | 64.5% | 64.1% | 30.9% | 6.5% | 106 | 153 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 35.9% | 61.9% | 135 | 375 | 500 | 12.6% |
| 512 | 37.4% | 64.3% | 148 | 396 | 76 | 3.9% |
| 1024 | 37.5% | 64.5% | 153 | 408 | 2 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 540 examples from 300 states, reasoning tokens mean 86, median 81.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 626,186 |
| sampling time | 3.2 min |
| samples/s | 21.4 |
| generated tokens/s | 3,274 |
| Lean execution time (overlaps sampling) | 6.7 min |
| Lean s / state | 7.91 |
