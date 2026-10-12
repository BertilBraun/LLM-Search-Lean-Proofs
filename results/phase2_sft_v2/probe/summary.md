# Phase 1 model probe

738 traced validation-split states (at most 5 per proof, goals of at most 3000 characters, never trained on) and 244 miniF2F-valid initial states. Per state k=8 samples at temperature 1.0 in the search's prompt format (few-shot: False, thinking: False, at most 256 tokens, stop at the closing fence), all requests queued at once (128 in flight) on one RTX 3090 with one model at a time. Every distinct parsed block ran on its state with `apply_block` (default heartbeats, 10 s wall clock).

Rates are per sample: parse fail = truncated or empty; forbidden = rejected before Lean; valid = at least one top-level tactic applied; fully valid = the whole block applied; progress = the goals changed; close = no goals left; exact match = equal to the traced step up to whitespace. `any` rates are per state (at least one of the k samples). States whose replay or start failed in Lean are excluded as infrastructure failures. Median progress log p: summed log-probability of the samples that made progress.

## All states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v1 | 982 | 2.3% | 0.0% | 71.0% | 71.0% | 69.4% | 20.1% | – | 95.9% | 95.7% | 36.8% | 5.69 | 35 | -2.37 |
| qwen3.5-2b-sft-v2 | 981 | 1.5% | 0.0% | 71.9% | 71.9% | 69.9% | 19.7% | – | 97.6% | 96.9% | 36.3% | 5.98 | 32 | -2.78 |

## Traced validation states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v1 | 738 | 2.4% | 0.0% | 71.2% | 71.2% | 70.1% | 21.5% | 17.5% | 95.3% | 95.0% | 38.8% | 5.49 | 37 | -2.06 |
| qwen3.5-2b-sft-v2 | 737 | 1.6% | 0.1% | 71.7% | 71.7% | 70.4% | 21.3% | 16.6% | 96.9% | 96.2% | 37.7% | 5.78 | 33 | -2.45 |

## miniF2F-valid initial states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v1 | 244 | 2.0% | 0.0% | 70.4% | 70.4% | 67.2% | 16.1% | – | 98.0% | 98.0% | 30.7% | 6.27 | 31 | -3.34 |
| qwen3.5-2b-sft-v2 | 244 | 1.2% | 0.0% | 72.2% | 72.2% | 68.3% | 14.9% | – | 99.6% | 99.2% | 32.0% | 6.57 | 27 | -3.96 |

## Throughput and Lean cost

Samples/s with all probe requests queued (few-shot prompt, shared prefix cached, real output lengths).

| model | checkpoint | samples | sampling s | samples/s | generated tokens/s | prompt tokens / state | prompt cache hits | prompts too long | Lean s / state |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v1 | Qwen/Qwen3.5-2B + /workspace/checkpoints/phase2_sft_v1/adapter | 7856 | 93 | 84.4 | 2967 | 175 | 80.9% | 0 | 8.36 |
| qwen3.5-2b-sft-v2 | Qwen/Qwen3.5-2B + /workspace/checkpoints/phase2_sft_v2/adapter | 7856 | 124 | 63.1 | 2017 | 175 | 81.6% | 0 | 9.76 |

## Valid / progress / any-close by source (usable states)

| source | qwen3.5-2b-sft-v1 | qwen3.5-2b-sft-v2 |
|---|---|---|
| minif2f/aime | 63.3% / 55.0% / 0.0% (15) | 65.0% / 54.2% / 0.0% (15) |
| minif2f/algebra | 73.6% / 71.5% / 55.6% (18) | 75.7% / 75.0% / 55.6% (18) |
| minif2f/amc12 | 63.1% / 58.1% / 13.3% (45) | 65.3% / 60.6% / 13.3% (45) |
| minif2f/imo | 65.0% / 58.8% / 0.0% (20) | 68.8% / 61.3% / 0.0% (20) |
| minif2f/induction | 71.9% / 71.9% / 37.5% (8) | 67.2% / 65.6% / 37.5% (8) |
| minif2f/mathd_algebra | 70.4% / 69.1% / 30.0% (70) | 74.6% / 72.3% / 31.4% (70) |
| minif2f/mathd_numbertheory | 78.5% / 76.0% / 58.3% (60) | 79.2% / 75.0% / 58.3% (60) |
| minif2f/numbertheory | 68.8% / 64.1% / 0.0% (8) | 57.8% / 57.8% / 25.0% (8) |
| traced/deepseek_prover_v1 | 83.4% / 81.5% / 73.8% (107) | 83.5% / 81.7% / 65.4% (107) |
| traced/goedel_lean_workbook_proofs | 80.2% / 79.0% / 36.5% (96) | 78.6% / 77.2% / 35.4% (96) |
| traced/goedel_sft_v2 | 70.9% / 70.2% / 35.1% (154) | 69.2% / 68.3% / 33.8% (154) |
| traced/lean_workbook | 75.3% / 75.3% / 61.1% (36) | 76.4% / 76.0% / 66.7% (36) |
| traced/leanabell_sft | 78.6% / 76.5% / 40.8% (76) | 79.4% / 77.5% / 40.8% (76) |
| traced/numinamath_lean_human | 49.0% / 47.1% / 17.4% (92) | 53.0% / 50.8% / 17.4% (92) |
| traced/numinamath_lean_kimina | 61.1% / 60.5% / 24.7% (81) | 60.3% / 59.4% / 21.2% (80) |
| traced/stp_lean_workbook | 71.5% / 71.2% / 30.2% (96) | 75.4% / 74.9% / 35.4% (96) |
