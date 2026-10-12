# Reasoning run `phase5_compare_base_thinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `None`), thinking on, temperature 0.8, at most 4096 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git 93e1ba42ea.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 4.5% | 18.0% | 6.3% | 4.4% | 0.0% | 2601 | 2700 |

Generated tokens per success: 60,636; prompt tokens per state: 160. Reference states reached: 1 step(s): 0, 2 step(s): 2.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 2139 | 52.3% |
| forbidden | 153 | 3.7% |
| error | 1473 | 36.0% |
| timeout | 1 | 0.0% |
| partial | 60 | 1.5% |
| closed_early | 5 | 0.1% |
| no_progress | 9 | 0.2% |
| progress | 66 | 1.6% |
| reference | 2 | 0.0% |
| closed | 180 | 4.4% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 2 | 2 | 0.0% | 0.0% | 50.0% | 0.0% | 0.0% | 0 | 21 |
| 64–127 | 4 | 5 | 40.0% | 50.0% | 40.0% | 40.0% | 0.0% | 107 | 146 |
| 128–191 | 12 | 15 | 26.7% | 33.3% | 40.0% | 26.7% | 0.0% | 165 | 210 |
| 192–255 | 19 | 22 | 31.8% | 31.6% | 36.4% | 31.8% | 0.0% | 232 | 278 |
| 256–383 | 68 | 93 | 29.0% | 33.8% | 37.6% | 29.0% | 0.0% | 329 | 396 |
| 384–511 | 213 | 312 | 12.2% | 13.1% | 15.4% | 12.2% | 0.0% | 458 | 608 |
| 512–767 | 346 | 641 | 5.5% | 9.0% | 7.8% | 5.5% | 0.0% | 624 | 793 |
| 768–1023 | 215 | 274 | 6.9% | 7.4% | 9.9% | 6.6% | 0.4% | 880 | 1068 |
| 1024–1535 | 201 | 251 | 9.6% | 11.4% | 13.1% | 9.2% | 0.4% | 1251 | 1426 |
| 1536–2047 | 103 | 115 | 7.8% | 8.7% | 12.2% | 7.8% | 0.0% | 1775 | 1949 |
| 2048–3071 | 112 | 146 | 8.2% | 9.8% | 16.4% | 8.2% | 0.0% | 2532 | 2679 |
| 3072+ | 67 | 73 | 6.8% | 7.5% | 12.3% | 6.8% | 0.0% | 3487 | 3614 |
| truncated | 487 | 2139 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 4053 | 4096 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 6.1% | 28.4% | 11.1% | 6.1% | 0.0% | 2186 | 2262 |
| goedel_lean_workbook_proofs | 73 | 584 | 5.0% | 19.2% | 6.3% | 5.0% | 0.0% | 2679 | 2777 |
| goedel_sft_v2 | 72 | 576 | 4.7% | 13.9% | 5.6% | 4.7% | 0.0% | 2750 | 2877 |
| lean_workbook | 73 | 584 | 5.5% | 24.7% | 6.8% | 5.1% | 0.3% | 2547 | 2641 |
| leanabell_sft | 73 | 584 | 5.8% | 24.7% | 8.4% | 5.8% | 0.0% | 2452 | 2524 |
| numinamath_lean_kimina | 73 | 584 | 1.5% | 9.6% | 2.7% | 1.5% | 0.0% | 2764 | 2871 |
| stp_lean_workbook | 73 | 584 | 2.6% | 5.5% | 2.9% | 2.6% | 0.0% | 2836 | 2952 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 0.8% | 2.1% | 0.8% | 0.8% | 0.0% | 2814 | 2965 |
| seen in SFT | 463 | 3704 | 4.8% | 19.7% | 6.9% | 4.8% | 0.1% | 2579 | 2672 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 0.3% | 2.0% | 255 | 87,040 | 1920 | 8.9% |
| 512 | 1.9% | 9.0% | 505 | 26,465 | 1717 | 6.1% |
| 1024 | 3.2% | 13.5% | 925 | 28,648 | 798 | 6.3% |
| 2048 | 4.0% | 16.8% | 1575 | 39,015 | 266 | 6.4% |
| 4096 | 4.5% | 18.0% | 2700 | 60,636 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 137 examples from 92 states, reasoning tokens mean 866, median 559.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 11,062,074 |
| sampling time | 16.7 min |
| samples/s | 4.1 |
| generated tokens/s | 11,063 |
| Lean execution time (overlaps sampling) | 3.8 min |
| Lean s / state | 1.29 |
