# Reasoning run `phase5_visible_probe_sft`

512 traced train-split states, k=8 samples each from `base-4b` (adapter `sft-4b`), thinking off, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git 5d825a08ca.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 512 | 4096 | 6.9% | 30.3% | 24.9% | 6.0% | 0.9% | 66 | 83 |

Generated tokens per success: 1,203; prompt tokens per state: 191. Reference states reached: 1 step(s): 38.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 1 | 0.0% |
| no_block | 806 | 19.7% |
| empty | 1509 | 36.8% |
| error | 690 | 16.8% |
| timeout | 71 | 1.7% |
| no_progress | 31 | 0.8% |
| progress | 705 | 17.2% |
| reference | 38 | 0.9% |
| closed | 245 | 6.0% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 4 | 4 | 50.0% | 50.0% | 50.0% | 25.0% | 25.0% | 0 | 36 |
| 1–31 | 469 | 2351 | 10.2% | 28.6% | 38.2% | 8.9% | 1.3% | 11 | 35 |
| 32–63 | 300 | 649 | 4.2% | 6.7% | 13.1% | 3.2% | 0.9% | 46 | 56 |
| 64–127 | 282 | 542 | 2.4% | 4.6% | 4.8% | 2.2% | 0.2% | 91 | 98 |
| 128–191 | 153 | 240 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 154 | 158 |
| 192–255 | 77 | 101 | 0.0% | 0.0% | 2.0% | 0.0% | 0.0% | 221 | 224 |
| 256–383 | 78 | 103 | 0.0% | 0.0% | 1.9% | 0.0% | 0.0% | 309 | 314 |
| 384–511 | 31 | 40 | 0.0% | 0.0% | 5.0% | 0.0% | 0.0% | 448 | 451 |
| 512–767 | 22 | 28 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 619 | 633 |
| 768–1023 | 17 | 17 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 944 | 984 |
| 1024–1535 | 17 | 20 | 5.0% | 5.9% | 15.0% | 5.0% | 0.0% | 1024 | 1098 |
| truncated | 1 | 1 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 3 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 256 | 2048 | 5.7% | 28.5% | 17.9% | 5.5% | 0.2% | 83 | 97 |
| stp_lean_workbook | 256 | 2048 | 8.1% | 32.0% | 31.9% | 6.4% | 1.7% | 48 | 70 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 512 | 4096 | 6.9% | 30.3% | 24.9% | 6.0% | 0.9% | 66 | 83 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 6.9% | 30.3% | 69 | 1,002 | 229 | 0.4% |
| 512 | 6.9% | 30.3% | 77 | 1,120 | 70 | 1.4% |
| 1024 | 6.9% | 30.3% | 83 | 1,200 | 29 | 3.4% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 80 examples from 62 states, reasoning tokens mean 37, median 29.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 340,427 |
| sampling time | 2.8 min |
| samples/s | 24.6 |
| generated tokens/s | 2,043 |
| Lean execution time (overlaps sampling) | 4.7 min |
| Lean s / state | 4.38 |
