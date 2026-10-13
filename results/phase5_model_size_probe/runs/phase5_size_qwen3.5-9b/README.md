# Reasoning run `phase5_size_qwen3.5-9b`

64 traced train-split states, k=8 samples each from `probe-9b` (adapter `None`), thinking on, temperature 0.8, at most 4096 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git d9f2f47d1a.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 64 | 512 | 33.8% | 53.1% | 42.8% | 33.6% | 0.2% | 1424 | 1484 |

Generated tokens per success: 4,392; prompt tokens per state: 161. Reference states reached: 1 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 124 | 24.2% |
| empty | 7 | 1.4% |
| forbidden | 6 | 1.2% |
| error | 108 | 21.1% |
| partial | 47 | 9.2% |
| closed_early | 1 | 0.2% |
| progress | 46 | 9.0% |
| reference | 1 | 0.2% |
| closed | 172 | 33.6% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 64–127 | 2 | 6 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 97 | 108 |
| 128–191 | 9 | 29 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 161 | 172 |
| 192–255 | 10 | 22 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 228 | 240 |
| 256–383 | 20 | 49 | 87.8% | 85.0% | 87.8% | 87.8% | 0.0% | 317 | 351 |
| 384–511 | 52 | 126 | 28.6% | 36.5% | 43.7% | 28.6% | 0.0% | 446 | 541 |
| 512–767 | 49 | 108 | 17.6% | 30.6% | 36.1% | 16.7% | 0.9% | 610 | 732 |
| 768–1023 | 18 | 20 | 20.0% | 16.7% | 35.0% | 20.0% | 0.0% | 865 | 953 |
| 1024–1535 | 9 | 10 | 10.0% | 11.1% | 30.0% | 10.0% | 0.0% | 1176 | 1252 |
| 1536–2047 | 4 | 4 | 25.0% | 25.0% | 50.0% | 25.0% | 0.0% | 1720 | 1773 |
| 2048–3071 | 8 | 10 | 80.0% | 75.0% | 90.0% | 80.0% | 0.0% | 2396 | 2415 |
| 3072+ | 3 | 4 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 3431 | 3462 |
| truncated | 48 | 124 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 4095 | 4096 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 32 | 256 | 41.4% | 56.2% | 50.0% | 41.4% | 0.0% | 1185 | 1230 |
| stp_lean_workbook | 32 | 256 | 26.2% | 50.0% | 35.5% | 25.8% | 0.4% | 1663 | 1738 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 64 | 512 | 33.8% | 53.1% | 42.8% | 33.6% | 0.2% | 1424 | 1484 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 9.8% | 18.8% | 249 | 2,548 | 338 | 36.4% |
| 512 | 26.2% | 39.1% | 453 | 1,731 | 211 | 18.5% |
| 1024 | 30.9% | 51.6% | 679 | 2,201 | 44 | 34.1% |
| 2048 | 31.4% | 53.1% | 970 | 3,084 | 14 | 85.7% |
| 4096 | 33.8% | 53.1% | 1484 | 4,392 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 62 examples from 34 states, reasoning tokens mean 380, median 302.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 1 (1) |
| samples / generated tokens | 512 / 759,860 |
| sampling time | 16.1 min |
| samples/s | 0.5 |
| generated tokens/s | 787 |
| Lean execution time (overlaps sampling) | 0.6 min |
| Lean s / state | 3.44 |
