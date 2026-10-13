# Reasoning run `phase5_size_qwen3.5-4b_bounded`

128 traced train-split states, k=8 samples each from `probe-4b` (adapter `None`), thinking on with the system prompt addition “Think briefly (a few sentences) about which tactic to use; do not restate the goal.”, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 0 states whose replay failed are excluded. Git d9f2f47d1a.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 128 | 1024 | 17.1% | 35.2% | 18.2% | 16.9% | 0.2% | 859 | 879 |

Generated tokens per success: 5,142; prompt tokens per state: 184. Reference states reached: 1 step(s): 2.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 737 | 72.0% |
| no_block | 1 | 0.1% |
| forbidden | 5 | 0.5% |
| error | 71 | 6.9% |
| timeout | 4 | 0.4% |
| partial | 20 | 2.0% |
| no_progress | 1 | 0.1% |
| progress | 10 | 1.0% |
| reference | 2 | 0.2% |
| closed | 173 | 16.9% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 32–63 | 1 | 1 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 63 | 80 |
| 64–127 | 8 | 13 | 84.6% | 75.0% | 84.6% | 84.6% | 0.0% | 97 | 155 |
| 128–191 | 11 | 18 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 158 | 170 |
| 192–255 | 20 | 32 | 96.9% | 100.0% | 96.9% | 96.9% | 0.0% | 225 | 238 |
| 256–383 | 26 | 41 | 92.7% | 92.3% | 92.7% | 92.7% | 0.0% | 319 | 336 |
| 384–511 | 57 | 80 | 35.0% | 40.4% | 41.2% | 35.0% | 0.0% | 449 | 536 |
| 512–767 | 57 | 80 | 43.8% | 49.1% | 48.8% | 43.8% | 0.0% | 606 | 702 |
| 768–1023 | 21 | 22 | 59.1% | 61.9% | 68.2% | 50.0% | 9.1% | 865 | 894 |
| truncated | 125 | 737 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 1020 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 64 | 512 | 23.8% | 46.9% | 24.6% | 23.8% | 0.0% | 816 | 836 |
| stp_lean_workbook | 64 | 512 | 10.4% | 23.4% | 11.7% | 10.0% | 0.4% | 903 | 922 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 128 | 1024 | 17.1% | 35.2% | 18.2% | 16.9% | 0.2% | 859 | 879 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 5.1% | 15.6% | 252 | 4,962 | 233 | 52.8% |
| 512 | 12.0% | 28.9% | 483 | 4,023 | 142 | 36.6% |
| 1024 | 17.1% | 35.2% | 879 | 5,142 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 80 examples from 45 states, reasoning tokens mean 319, median 258.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 2 (2) |
| samples / generated tokens | 1,024 / 899,933 |
| sampling time | 6.5 min |
| samples/s | 2.6 |
| generated tokens/s | 2,325 |
| Lean execution time (overlaps sampling) | 0.6 min |
| Lean s / state | 1.59 |
