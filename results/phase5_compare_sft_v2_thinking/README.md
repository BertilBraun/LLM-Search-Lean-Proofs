# Reasoning run `phase5_compare_sft_v2_thinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `policy-v2`), thinking on, temperature 0.8, at most 4096 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git 93e1ba42ea.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 20.7% | 55.0% | 38.2% | 16.6% | 4.1% | 1787 | 1935 |

Generated tokens per success: 9,352; prompt tokens per state: 160. Reference states reached: 1 step(s): 159, 2 step(s): 9, 3 step(s): 0, 4 step(s): 0, 5 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 1388 | 34.0% |
| no_block | 546 | 13.4% |
| error | 562 | 13.7% |
| timeout | 26 | 0.6% |
| partial | 3 | 0.1% |
| closed_early | 1 | 0.0% |
| no_progress | 14 | 0.3% |
| progress | 702 | 17.2% |
| reference | 169 | 4.1% |
| closed | 677 | 16.6% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 22 | 23 | 43.5% | 45.5% | 78.3% | 21.7% | 21.7% | 0 | 93 |
| 1–31 | 110 | 233 | 18.5% | 31.8% | 25.8% | 16.7% | 1.7% | 16 | 23 |
| 32–63 | 96 | 168 | 47.6% | 52.1% | 56.0% | 45.2% | 2.4% | 46 | 62 |
| 64–127 | 120 | 209 | 48.3% | 50.0% | 68.4% | 46.4% | 1.9% | 96 | 161 |
| 128–191 | 111 | 176 | 44.9% | 45.0% | 71.6% | 37.5% | 7.4% | 159 | 204 |
| 192–255 | 137 | 183 | 43.7% | 44.5% | 74.9% | 38.8% | 4.9% | 222 | 262 |
| 256–383 | 179 | 280 | 32.9% | 40.2% | 67.9% | 25.7% | 7.1% | 314 | 365 |
| 384–511 | 172 | 234 | 31.2% | 35.5% | 66.7% | 22.2% | 9.0% | 452 | 506 |
| 512–767 | 223 | 322 | 29.5% | 34.5% | 60.9% | 20.5% | 9.0% | 619 | 675 |
| 768–1023 | 155 | 185 | 26.5% | 27.1% | 51.9% | 19.5% | 7.0% | 879 | 927 |
| 1024–1535 | 183 | 254 | 22.8% | 27.3% | 52.4% | 16.9% | 5.9% | 1253 | 1312 |
| 1536–2047 | 107 | 119 | 25.2% | 26.2% | 54.6% | 15.1% | 10.1% | 1769 | 1843 |
| 2048–3071 | 168 | 203 | 18.7% | 22.6% | 45.8% | 11.8% | 6.9% | 2549 | 2630 |
| 3072+ | 91 | 111 | 16.2% | 19.8% | 49.5% | 10.8% | 5.4% | 3495 | 3560 |
| truncated | 387 | 1388 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 3757 | 4096 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 32.4% | 82.4% | 60.5% | 28.7% | 3.7% | 1069 | 1178 |
| goedel_lean_workbook_proofs | 73 | 584 | 20.0% | 53.4% | 36.0% | 16.6% | 3.4% | 1998 | 2129 |
| goedel_sft_v2 | 72 | 576 | 30.9% | 52.8% | 40.6% | 25.0% | 5.9% | 1747 | 1847 |
| lean_workbook | 73 | 584 | 17.6% | 63.0% | 39.4% | 14.6% | 3.1% | 1854 | 1983 |
| leanabell_sft | 73 | 584 | 23.3% | 65.8% | 40.8% | 16.8% | 6.5% | 1353 | 1628 |
| numinamath_lean_kimina | 73 | 584 | 11.6% | 35.6% | 30.0% | 8.2% | 3.4% | 1856 | 2026 |
| stp_lean_workbook | 73 | 584 | 8.9% | 31.5% | 20.0% | 6.0% | 2.9% | 2643 | 2765 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 3.6% | 14.6% | 12.0% | 1.8% | 1.8% | 2846 | 2998 |
| seen in SFT | 463 | 3704 | 22.5% | 59.2% | 40.9% | 18.1% | 4.4% | 1677 | 1825 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 371 | 889 | 24.6% | 35.3% | 70.6% | 16.8% | 7.9% | 798 | 874 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 9.1% | 24.1% | 222 | 2,436 | 1787 | 26.5% |
| 512 | 13.2% | 35.2% | 405 | 3,063 | 1299 | 23.6% |
| 1024 | 17.1% | 45.8% | 698 | 4,089 | 726 | 20.4% |
| 2048 | 19.3% | 51.5% | 1168 | 6,042 | 335 | 16.7% |
| 4096 | 20.7% | 55.0% | 1935 | 9,352 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 450 examples from 274 states, reasoning tokens mean 607, median 324.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 7,913,412 |
| sampling time | 13.5 min |
| samples/s | 5.1 |
| generated tokens/s | 9,794 |
| Lean execution time (overlaps sampling) | 4.9 min |
| Lean s / state | 3.05 |
