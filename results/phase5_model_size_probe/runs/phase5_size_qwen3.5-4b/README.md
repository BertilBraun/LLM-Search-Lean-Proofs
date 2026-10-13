# Reasoning run `phase5_size_qwen3.5-4b`

128 traced train-split states, k=8 samples each from `probe-4b` (adapter `None`), thinking on, temperature 0.8, at most 4096 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git f6223c626d.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 128 | 1024 | 24.2% | 35.2% | 25.8% | 24.1% | 0.1% | 3072 | 3105 |

Generated tokens per success: 12,819; prompt tokens per state: 164. Reference states reached: 1 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 671 | 65.5% |
| error | 68 | 6.6% |
| partial | 20 | 2.0% |
| closed_early | 1 | 0.1% |
| no_progress | 2 | 0.2% |
| progress | 14 | 1.4% |
| reference | 1 | 0.1% |
| closed | 247 | 24.1% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 64–127 | 4 | 10 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 103 | 114 |
| 128–191 | 11 | 20 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 156 | 168 |
| 192–255 | 17 | 24 | 91.7% | 94.1% | 91.7% | 91.7% | 0.0% | 218 | 234 |
| 256–383 | 28 | 39 | 92.3% | 92.9% | 92.3% | 92.3% | 0.0% | 316 | 349 |
| 384–511 | 40 | 55 | 38.2% | 40.0% | 43.6% | 38.2% | 0.0% | 440 | 545 |
| 512–767 | 49 | 63 | 49.2% | 42.9% | 55.6% | 49.2% | 0.0% | 605 | 732 |
| 768–1023 | 21 | 22 | 54.5% | 52.4% | 59.1% | 54.5% | 0.0% | 860 | 1120 |
| 1024–1535 | 16 | 20 | 80.0% | 75.0% | 85.0% | 80.0% | 0.0% | 1350 | 1395 |
| 1536–2047 | 24 | 29 | 72.4% | 70.8% | 79.3% | 72.4% | 0.0% | 1803 | 1886 |
| 2048–3071 | 24 | 30 | 83.3% | 79.2% | 86.7% | 80.0% | 3.3% | 2460 | 2505 |
| 3072+ | 28 | 41 | 82.9% | 75.0% | 92.7% | 82.9% | 0.0% | 3606 | 3623 |
| truncated | 116 | 671 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 4087 | 4096 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 64 | 512 | 34.0% | 45.3% | 35.7% | 34.0% | 0.0% | 2749 | 2781 |
| stp_lean_workbook | 64 | 512 | 14.5% | 25.0% | 15.8% | 14.3% | 0.2% | 3395 | 3429 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 128 | 1024 | 24.2% | 35.2% | 25.8% | 24.1% | 0.1% | 3072 | 3105 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 4.8% | 14.8% | 252 | 5,273 | 303 | 65.7% |
| 512 | 10.5% | 27.3% | 486 | 4,612 | 231 | 60.6% |
| 1024 | 14.7% | 29.7% | 907 | 6,151 | 131 | 74.0% |
| 2048 | 18.5% | 32.8% | 1684 | 9,121 | 77 | 76.6% |
| 4096 | 24.2% | 35.2% | 3105 | 12,819 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 83 examples from 45 states, reasoning tokens mean 589, median 311.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 2 (2) |
| samples / generated tokens | 1,024 / 3,179,167 |
| sampling time | 33.2 min |
| samples/s | 0.5 |
| generated tokens/s | 1,597 |
| Lean execution time (overlaps sampling) | 0.9 min |
| Lean s / state | 1.66 |
