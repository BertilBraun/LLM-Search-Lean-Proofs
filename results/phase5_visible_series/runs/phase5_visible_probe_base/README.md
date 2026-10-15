# Reasoning run `phase5_visible_probe_base`

512 traced train-split states, k=8 samples each from `base-4b` (adapter `None`), thinking off, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 5d825a08ca.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 25.7% | 47.3% | 33.4% | 25.2% | 0.4% | 156 | 281 |

Generated tokens per success: 1,096; prompt tokens per state: 191. Reference states reached: 1 step(s): 17, 2 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 56 | 1.4% |
| forbidden | 87 | 2.1% |
| error | 1687 | 41.2% |
| timeout | 72 | 1.8% |
| partial | 800 | 19.5% |
| closed_early | 25 | 0.6% |
| no_progress | 7 | 0.2% |
| progress | 311 | 7.6% |
| reference | 18 | 0.4% |
| closed | 1033 | 25.2% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1–31 | 8 | 10 | 90.0% | 100.0% | 90.0% | 90.0% | 0.0% | 28 | 46 |
| 32–63 | 138 | 392 | 79.8% | 71.0% | 82.9% | 79.8% | 0.0% | 52 | 75 |
| 64–127 | 477 | 1872 | 28.0% | 39.6% | 35.6% | 27.6% | 0.4% | 97 | 193 |
| 128–191 | 391 | 1104 | 12.5% | 21.5% | 21.3% | 12.1% | 0.4% | 153 | 308 |
| 192–255 | 213 | 316 | 12.0% | 15.0% | 20.6% | 11.1% | 0.9% | 217 | 400 |
| 256–383 | 133 | 170 | 9.4% | 12.0% | 23.5% | 8.8% | 0.6% | 301 | 485 |
| 384–511 | 47 | 53 | 5.7% | 6.4% | 15.1% | 5.7% | 0.0% | 433 | 611 |
| 512–767 | 39 | 47 | 14.9% | 17.9% | 21.3% | 10.6% | 4.3% | 625 | 775 |
| 768–1023 | 18 | 21 | 9.5% | 11.1% | 33.3% | 4.8% | 4.8% | 891 | 976 |
| 1024–1535 | 35 | 55 | 1.8% | 2.9% | 7.3% | 1.8% | 0.0% | 1024 | 1196 |
| truncated | 47 | 56 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 386 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 33.3% | 53.1% | 40.0% | 33.1% | 0.2% | 132 | 235 |
| stp_lean_workbook | 256 | 2048 | 18.1% | 41.4% | 26.8% | 17.4% | 0.7% | 180 | 327 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 25.7% | 47.3% | 33.4% | 25.2% | 0.4% | 156 | 281 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 23.2% | 40.4% | 188 | 811 | 1496 | 6.8% |
| 512 | 25.3% | 46.3% | 243 | 964 | 444 | 3.6% |
| 1024 | 25.6% | 47.3% | 279 | 1,087 | 60 | 1.7% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 436 examples from 242 states, reasoning tokens mean 98, median 78.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 1,151,838 |
| sampling time | 5.2 min |
| samples/s | 13.2 |
| generated tokens/s | 3,713 |
| Lean execution time (overlaps sampling) | 10.1 min |
| Lean s / state | 11.80 |
