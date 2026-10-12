# Reasoning run `phase5_compare_base_fewshot`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `None`), thinking off, temperature 0.8, at most 512 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git 93e1ba42ea.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 11.4% | 35.8% | 18.7% | 11.2% | 0.1% | 0 | 109 |

Generated tokens per success: 962; prompt tokens per state: 503. Reference states reached: 1 step(s): 5, 2 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 223 | 5.5% |
| empty | 6 | 0.1% |
| forbidden | 142 | 3.5% |
| error | 2429 | 59.4% |
| timeout | 50 | 1.2% |
| partial | 469 | 11.5% |
| closed_early | 4 | 0.1% |
| no_progress | 18 | 0.4% |
| progress | 283 | 6.9% |
| reference | 6 | 0.1% |
| closed | 458 | 11.2% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 511 | 3865 | 12.0% | 35.8% | 19.8% | 11.8% | 0.2% | 0 | 86 |
| truncated | 137 | 223 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 512 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 18.2% | 59.5% | 27.9% | 18.1% | 0.2% | 0 | 75 |
| goedel_lean_workbook_proofs | 73 | 584 | 15.6% | 38.4% | 21.6% | 15.6% | 0.0% | 0 | 115 |
| goedel_sft_v2 | 72 | 576 | 5.0% | 22.2% | 10.4% | 5.0% | 0.0% | 0 | 138 |
| lean_workbook | 73 | 584 | 20.9% | 61.6% | 30.7% | 20.4% | 0.5% | 0 | 94 |
| leanabell_sft | 73 | 584 | 9.6% | 32.9% | 19.5% | 9.2% | 0.3% | 0 | 81 |
| numinamath_lean_kimina | 73 | 584 | 5.1% | 17.8% | 11.8% | 5.1% | 0.0% | 0 | 104 |
| stp_lean_workbook | 73 | 584 | 4.8% | 17.8% | 8.9% | 4.8% | 0.0% | 0 | 159 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 1.3% | 6.2% | 4.4% | 1.3% | 0.0% | 0 | 179 |
| seen in SFT | 463 | 3704 | 12.4% | 38.9% | 20.2% | 12.2% | 0.2% | 0 | 102 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 11.3% | 35.6% | 88 | 782 | 278 | 0.7% |
| 512 | 11.4% | 35.8% | 109 | 962 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 447,531 |
| sampling time | 1.0 min |
| samples/s | 66.3 |
| generated tokens/s | 7,242 |
| Lean execution time (overlaps sampling) | 9.7 min |
| Lean s / state | 5.98 |
