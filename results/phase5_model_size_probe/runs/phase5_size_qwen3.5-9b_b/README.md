# Reasoning run `phase5_size_qwen3.5-9b_b`

64 traced train-split states, k=8 samples each from `probe-9b-b` (adapter `None`), thinking on, temperature 0.8, at most 4096 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git d9f2f47d1a.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 64 | 512 | 21.9% | 37.5% | 32.8% | 21.3% | 0.6% | 1584 | 1649 |

Generated tokens per success: 7,539; prompt tokens per state: 168. Reference states reached: 1 step(s): 3.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 143 | 27.9% |
| empty | 6 | 1.2% |
| forbidden | 7 | 1.4% |
| error | 133 | 26.0% |
| timeout | 3 | 0.6% |
| partial | 52 | 10.2% |
| progress | 56 | 10.9% |
| reference | 3 | 0.6% |
| closed | 109 | 21.3% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 64–127 | 5 | 5 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 109 | 121 |
| 128–191 | 8 | 18 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 162 | 174 |
| 192–255 | 14 | 19 | 94.7% | 92.9% | 94.7% | 94.7% | 0.0% | 221 | 237 |
| 256–383 | 15 | 24 | 83.3% | 73.3% | 87.5% | 83.3% | 0.0% | 317 | 334 |
| 384–511 | 53 | 134 | 18.7% | 28.3% | 37.3% | 17.2% | 1.5% | 453 | 550 |
| 512–767 | 50 | 108 | 8.3% | 16.0% | 25.9% | 7.4% | 0.9% | 599 | 717 |
| 768–1023 | 21 | 27 | 14.8% | 19.0% | 33.3% | 14.8% | 0.0% | 875 | 973 |
| 1024–1535 | 14 | 16 | 12.5% | 14.3% | 31.2% | 12.5% | 0.0% | 1267 | 1462 |
| 1536–2047 | 6 | 8 | 37.5% | 33.3% | 62.5% | 37.5% | 0.0% | 1783 | 1834 |
| 2048–3071 | 6 | 9 | 88.9% | 83.3% | 100.0% | 88.9% | 0.0% | 2619 | 2633 |
| 3072+ | 1 | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 3155 | 3195 |
| truncated | 47 | 143 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 4096 | 4096 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 32 | 256 | 32.4% | 46.9% | 45.7% | 32.4% | 0.0% | 1323 | 1373 |
| stp_lean_workbook | 32 | 256 | 11.3% | 28.1% | 19.9% | 10.2% | 1.2% | 1845 | 1925 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 64 | 512 | 21.9% | 37.5% | 32.8% | 21.3% | 0.6% | 1584 | 1649 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 7.2% | 18.8% | 251 | 3,473 | 332 | 22.6% |
| 512 | 16.4% | 28.1% | 472 | 2,876 | 232 | 12.1% |
| 1024 | 19.3% | 37.5% | 730 | 3,775 | 45 | 28.9% |
| 2048 | 20.3% | 37.5% | 1064 | 5,240 | 12 | 66.7% |
| 4096 | 21.9% | 37.5% | 1649 | 7,539 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 41 examples from 24 states, reasoning tokens mean 373, median 247.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 1 (1) |
| samples / generated tokens | 512 / 844,342 |
| sampling time | 18.0 min |
| samples/s | 0.5 |
| generated tokens/s | 782 |
| Lean execution time (overlaps sampling) | 0.7 min |
| Lean s / state | 4.19 |
