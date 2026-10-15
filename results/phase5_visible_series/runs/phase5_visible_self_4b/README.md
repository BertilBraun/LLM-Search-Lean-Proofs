# Reasoning run `phase5_visible_self_4b`

10240 traced train-split states, k=8 samples each from `base-4b` (adapter `gentle-4b`), thinking off, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 5 states whose replay failed are excluded. Git 2af6978ceb.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 10235 | 81880 | 22.6% | 43.7% | 49.4% | 18.5% | 4.2% | 96 | 129 |

Generated tokens per success: 570; prompt tokens per state: 208. Reference states reached: 1 step(s): 3352, 2 step(s): 37, 3 step(s): 5, 4 step(s): 2, 5 step(s): 4.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 172 | 0.2% |
| no_block | 10193 | 12.4% |
| empty | 13132 | 16.0% |
| forbidden | 7 | 0.0% |
| error | 16254 | 19.9% |
| timeout | 1517 | 1.9% |
| partial | 180 | 0.2% |
| closed_early | 4 | 0.0% |
| no_progress | 252 | 0.3% |
| progress | 21652 | 26.4% |
| reference | 3400 | 4.2% |
| closed | 15117 | 18.5% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 51 | 52 | 30.8% | 31.4% | 57.7% | 15.4% | 15.4% | 0 | 36 |
| 1–31 | 8022 | 29119 | 20.1% | 36.8% | 60.4% | 15.8% | 4.3% | 18 | 47 |
| 32–63 | 7258 | 18365 | 41.0% | 38.3% | 57.3% | 36.6% | 4.3% | 46 | 72 |
| 64–127 | 7251 | 16836 | 21.6% | 30.0% | 41.8% | 17.2% | 4.4% | 90 | 123 |
| 128–191 | 4376 | 7188 | 11.3% | 15.4% | 33.7% | 7.2% | 4.1% | 156 | 196 |
| 192–255 | 2633 | 3611 | 8.0% | 9.8% | 32.6% | 4.1% | 3.9% | 221 | 261 |
| 256–383 | 2439 | 3490 | 6.4% | 7.9% | 28.6% | 3.0% | 3.4% | 309 | 345 |
| 384–511 | 1150 | 1340 | 4.1% | 4.3% | 21.9% | 2.0% | 2.1% | 439 | 469 |
| 512–767 | 726 | 832 | 2.9% | 3.2% | 16.9% | 1.6% | 1.3% | 612 | 634 |
| 768–1023 | 332 | 355 | 6.8% | 7.2% | 18.6% | 5.6% | 1.1% | 917 | 940 |
| 1024–1535 | 475 | 520 | 13.7% | 14.5% | 29.8% | 12.3% | 1.3% | 1024 | 1085 |
| truncated | 158 | 172 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 285 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 5119 | 40952 | 32.7% | 50.0% | 54.0% | 29.0% | 3.7% | 116 | 154 |
| stp_lean_workbook | 5116 | 40928 | 12.6% | 37.4% | 44.7% | 7.9% | 4.6% | 76 | 104 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 10235 | 81880 | 22.6% | 43.7% | 49.4% | 18.5% | 4.2% | 96 | 129 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 21.9% | 42.5% | 103 | 469 | 9588 | 6.0% |
| 512 | 22.4% | 43.4% | 119 | 532 | 2575 | 5.3% |
| 1024 | 22.5% | 43.5% | 128 | 571 | 622 | 14.6% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 7,457 examples from 4,208 states, reasoning tokens mean 52, median 34.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 40 (39) |
| samples / generated tokens | 79,872 / 10,298,601 |
| sampling time | 68.5 min |
| samples/s | 19.4 |
| generated tokens/s | 2,507 |
| Lean execution time (overlaps sampling) | 93.7 min |
| Lean s / state | 6.39 |
