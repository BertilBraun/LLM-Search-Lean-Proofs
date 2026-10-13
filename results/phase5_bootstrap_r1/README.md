# Reasoning run `phase5_bootstrap_r1`

8000 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `policy-v2`), thinking on, temperature 0.8, at most 1024 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 2 states whose replay failed are excluded. Git 998d5d2fdd.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 7998 | 63984 | 16.2% | 34.6% | 24.5% | 14.3% | 1.9% | 691 | 721 |

Generated tokens per success: 4,437; prompt tokens per state: 196. Reference states reached: 1 step(s): 1198, 2 step(s): 28, 3 step(s): 2, 4 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 36300 | 56.7% |
| no_block | 6730 | 10.5% |
| empty | 1 | 0.0% |
| forbidden | 2 | 0.0% |
| error | 4906 | 7.7% |
| timeout | 326 | 0.5% |
| partial | 24 | 0.0% |
| closed_early | 3 | 0.0% |
| no_progress | 103 | 0.2% |
| progress | 5193 | 8.1% |
| reference | 1229 | 1.9% |
| closed | 9167 | 14.3% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 311 | 322 | 32.6% | 33.4% | 73.6% | 7.5% | 25.2% | 0 | 62 |
| 1–31 | 2009 | 4328 | 21.9% | 32.7% | 25.0% | 20.5% | 1.4% | 19 | 26 |
| 32–63 | 1540 | 2955 | 57.0% | 56.7% | 63.5% | 55.9% | 1.1% | 46 | 59 |
| 64–127 | 1759 | 3306 | 59.1% | 60.8% | 70.0% | 57.0% | 2.1% | 94 | 115 |
| 128–191 | 1651 | 2621 | 56.9% | 60.1% | 73.4% | 52.9% | 4.0% | 158 | 190 |
| 192–255 | 1479 | 2088 | 50.1% | 53.1% | 69.9% | 45.8% | 4.4% | 223 | 263 |
| 256–383 | 2054 | 3107 | 38.8% | 43.0% | 62.7% | 32.9% | 5.9% | 317 | 373 |
| 384–511 | 2187 | 2925 | 26.4% | 30.5% | 54.9% | 19.1% | 7.3% | 446 | 512 |
| 512–767 | 2991 | 4157 | 20.6% | 24.4% | 54.1% | 13.8% | 6.8% | 626 | 688 |
| 768–1023 | 1579 | 1875 | 18.0% | 20.0% | 53.2% | 12.1% | 5.9% | 872 | 909 |
| truncated | 6850 | 36300 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 1000 | 1024 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| goedel_sft_v2 | 4000 | 32000 | 26.0% | 44.1% | 34.9% | 24.1% | 1.9% | 641 | 675 |
| stp_lean_workbook | 3998 | 31984 | 6.5% | 25.0% | 14.2% | 4.6% | 2.0% | 742 | 767 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 7998 | 63984 | 16.2% | 34.6% | 24.5% | 14.3% | 1.9% | 691 | 721 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 3933 | 7975 | 31.8% | 39.2% | 68.9% | 24.4% | 7.4% | 353 | 418 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 10.8% | 23.1% | 219 | 2,023 | 13102 | 26.4% |
| 512 | 14.1% | 28.4% | 405 | 2,875 | 7362 | 18.8% |
| 1024 | 16.2% | 34.6% | 721 | 4,437 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 4,563 examples from 2,662 states, reasoning tokens mean 225, median 127.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 32 (32) |
| samples / generated tokens | 64,000 / 46,130,314 |
| sampling time | 74.7 min |
| samples/s | 14.3 |
| generated tokens/s | 10,287 |
| Lean execution time (overlaps sampling) | 61.7 min |
| Lean s / state | 3.06 |
