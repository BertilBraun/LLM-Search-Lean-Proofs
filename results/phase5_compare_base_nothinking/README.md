# Reasoning run `phase5_compare_base_nothinking`

512 traced train-split states, k=8 samples each from `search-qwen3.5-2b` (adapter `None`), thinking off, temperature 0.8, at most 512 generated tokens (reasoning and block; truncation is a failure). Every distinct block ran on its rebuilt state with `apply_block` (10 s wall clock). Success: the whole block applied and the goals are closed or equal the reference proof's next state or a later one. 1 states whose replay failed are excluded. Git 93e1ba42ea.

## Overview

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| all | 511 | 4088 | 7.2% | 30.1% | 12.6% | 7.0% | 0.2% | 0 | 109 |

Generated tokens per success: 1,519; prompt tokens per state: 165. Reference states reached: 1 step(s): 7, 2 step(s): 1.

## Outcomes

| outcome | samples | share |
|---|---|---|
| truncated | 117 | 2.9% |
| empty | 4 | 0.1% |
| forbidden | 416 | 10.2% |
| error | 2457 | 60.1% |
| timeout | 40 | 1.0% |
| partial | 515 | 12.6% |
| closed_early | 23 | 0.6% |
| no_progress | 8 | 0.2% |
| progress | 214 | 5.2% |
| reference | 8 | 0.2% |
| closed | 286 | 7.0% |

## Success against reasoning length

Samples grouped by their reasoning tokens (text before `</think>`); truncated samples separately.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 511 | 3971 | 7.4% | 30.1% | 13.0% | 7.2% | 0.2% | 0 | 97 |
| truncated | 81 | 117 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 512 |

## By source

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| deepseek_prover_v1 | 74 | 592 | 9.0% | 40.5% | 19.3% | 7.9% | 1.0% | 0 | 66 |
| goedel_lean_workbook_proofs | 73 | 584 | 9.8% | 34.2% | 15.6% | 9.8% | 0.0% | 0 | 113 |
| goedel_sft_v2 | 72 | 576 | 4.5% | 20.8% | 9.2% | 4.5% | 0.0% | 0 | 120 |
| lean_workbook | 73 | 584 | 14.7% | 63.0% | 19.9% | 14.7% | 0.0% | 0 | 113 |
| leanabell_sft | 73 | 584 | 5.5% | 24.7% | 11.3% | 5.3% | 0.2% | 0 | 94 |
| numinamath_lean_kimina | 73 | 584 | 2.9% | 15.1% | 6.7% | 2.9% | 0.0% | 0 | 107 |
| stp_lean_workbook | 73 | 584 | 3.9% | 12.3% | 6.3% | 3.8% | 0.2% | 0 | 153 |

## By SFT exposure of the prompt state

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| unseen in SFT | 48 | 384 | 1.0% | 6.2% | 4.4% | 0.8% | 0.3% | 0 | 159 |
| seen in SFT | 463 | 3704 | 7.8% | 32.6% | 13.5% | 7.6% | 0.2% | 0 | 104 |

## Recovered answer format

Samples that closed `</think>` and then wrote the tactic and a closing fence without the opening one (the non-thinking answer format). The search's parser rejects them; this pipeline executes them and renders their training targets with the opening fence.

| group | states | samples | success | any success / state | fully valid | closed | reference | reasoning tokens | generated tokens |
|---|---|---|---|---|---|---|---|---|---|
| recovered format | 0 | 0 | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0 | 0 |

## Simulated generation caps

The same samples cut at a smaller cap: a sample counts as a success only if it finished within the cap, and costs at most the cap. Finished beyond the cap: samples that completed but needed more tokens.

| cap | success | any success / state | tokens / sample | tokens / success | finished beyond cap | their success |
|---|---|---|---|---|---|---|
| 256 | 7.1% | 29.9% | 95 | 1,329 | 301 | 0.7% |
| 512 | 7.2% | 30.1% | 109 | 1,519 | 0 | 0.0% |

## Rejection selection

At most 2 successes per state with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones: 0 examples from 0 states, reasoning tokens mean 0, median 0.

## Throughput

| quantity | value |
|---|---|
| chunks (sampled in this run's log) | 4 (4) |
| samples / generated tokens | 4,096 / 447,801 |
| sampling time | 0.9 min |
| samples/s | 74.0 |
| generated tokens/s | 8,088 |
| Lean execution time (overlaps sampling) | 7.2 min |
| Lean s / state | 5.41 |
