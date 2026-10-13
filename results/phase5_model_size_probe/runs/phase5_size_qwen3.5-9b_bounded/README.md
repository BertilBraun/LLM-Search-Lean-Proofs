# Reasoning run `phase5_size_qwen3.5-9b_bounded`

128 traced train-split states, k=8 samples each from `probe-9b` (adapter `None`), thinking on with the system prompt addition “Think briefly (a few sentences) about which tactic to use; do not restate the goal.”, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git d9f2f47d1a.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 128 | 1024 | 28.7% | 44.5% | 42.8% | 27.7% | 1.0% | 550 | 596 |

Generated tokens per success: 2,077; prompt tokens per state: 184. Reference states reached: 1 step(s): 10.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 237 | 23.1% |
| empty | 17 | 1.7% |
| forbidden | 9 | 0.9% |
| error | 235 | 22.9% |
| timeout | 4 | 0.4% |
| partial | 84 | 8.2% |
| no_progress | 1 | 0.1% |
| progress | 143 | 14.0% |
| reference | 10 | 1.0% |
| closed | 284 | 27.7% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 32–63 | 2 | 3 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 53 | 64 |
| 64–127 | 16 | 41 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 99 | 111 |
| 128–191 | 30 | 65 | 98.5% | 96.7% | 100.0% | 96.9% | 1.5% | 161 | 174 |
| 192–255 | 28 | 52 | 92.3% | 89.3% | 94.2% | 92.3% | 0.0% | 223 | 237 |
| 256–383 | 64 | 126 | 49.2% | 50.0% | 72.2% | 45.2% | 4.0% | 318 | 347 |
| 384–511 | 107 | 324 | 17.6% | 30.8% | 41.0% | 16.4% | 1.2% | 448 | 520 |
| 512–767 | 77 | 138 | 12.3% | 16.9% | 31.2% | 12.3% | 0.0% | 599 | 679 |
| 768–1023 | 31 | 38 | 5.3% | 6.5% | 34.2% | 5.3% | 0.0% | 848 | 891 |
| truncated | 94 | 237 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 1000 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 64 | 512 | 37.3% | 50.0% | 51.6% | 37.3% | 0.0% | 487 | 521 |
| stp_lean_workbook | 64 | 512 | 20.1% | 39.1% | 34.0% | 18.2% | 2.0% | 614 | 671 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 128 | 1024 | 28.7% | 44.5% | 42.8% | 27.7% | 1.0% | 550 | 596 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 14.4% | 27.3% | 243 | 1,695 | 637 | 23.1% |
| 512 | 26.2% | 38.3% | 429 | 1,641 | 298 | 8.7% |
| 1024 | 28.7% | 44.5% | 596 | 2,077 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 107 examples from 57 states, reasoning tokens mean 266, median 201.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 2 (2) |
| samples / generated tokens | 1,024 / 610,708 |
| sampling time | 9.7 min |
| samples/s | 1.8 |
| generated tokens/s | 1,044 |
| Lean execution time (overlaps sampling) | 1.4 min |
| Lean s / state | 3.84 |
