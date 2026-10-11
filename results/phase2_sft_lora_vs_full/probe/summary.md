# Phase 1 model probe

738 traced validation-split states (at most 5 per proof, goals of at most 3000 characters, never trained on) and 244 miniF2F-valid initial states. Per state k=8 samples at temperature 1.0 in the search's prompt format (few-shot: False, thinking: False, at most 256 tokens, stop at the closing fence), all requests queued at once (128 in flight) on one RTX 3090 with one model at a time. Every distinct parsed block ran on its state with `apply_block` (default heartbeats, 10 s wall clock).

Rates are per sample: parse fail = truncated or empty; forbidden = rejected before Lean; valid = at least one top-level tactic applied; fully valid = the whole block applied; progress = the goals changed; close = no goals left; exact match = equal to the traced step up to whitespace. `any` rates are per state (at least one of the k samples). States whose replay or start failed in Lean are excluded as infrastructure failures. Median progress log p: summed log-probability of the samples that made progress.

## All states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-0.8b-full-sft | 982 | 1.8% | 0.0% | 63.9% | 63.9% | 62.7% | 16.9% | – | 95.7% | 95.3% | 33.8% | 6.17 | 37 | -2.85 |
| qwen3.5-0.8b-lora-sft | 982 | 1.5% | 0.0% | 63.8% | 63.8% | 62.2% | 16.0% | – | 96.9% | 95.9% | 32.6% | 6.15 | 33 | -2.74 |

## Traced validation states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-0.8b-full-sft | 738 | 1.6% | 0.0% | 65.6% | 65.6% | 64.5% | 18.0% | 14.4% | 95.8% | 95.7% | 35.0% | 5.95 | 35 | -2.42 |
| qwen3.5-0.8b-lora-sft | 738 | 1.5% | 0.0% | 64.8% | 64.8% | 63.3% | 17.3% | 14.0% | 96.7% | 96.1% | 34.1% | 5.97 | 33 | -2.45 |

## miniF2F-valid initial states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-0.8b-full-sft | 244 | 2.7% | 0.0% | 58.7% | 58.7% | 57.2% | 13.4% | – | 95.5% | 94.3% | 30.3% | 6.82 | 41 | -4.16 |
| qwen3.5-0.8b-lora-sft | 244 | 1.4% | 0.0% | 60.6% | 60.6% | 58.7% | 12.0% | – | 97.5% | 95.5% | 27.9% | 6.71 | 34 | -3.84 |

## Throughput and Lean cost

Samples/s with all probe requests queued (few-shot prompt, shared prefix cached, real output lengths).

| model | checkpoint | samples | sampling s | samples/s | generated tokens/s | prompt tokens / state | prompt cache hits | prompts too long | Lean s / state |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-0.8b-full-sft | /workspace/checkpoints/phase2_sft_ab_full/model | 7856 | 86 | 91.8 | 3378 | 175 | 80.3% | 0 | 4.63 |
| qwen3.5-0.8b-lora-sft | /workspace/checkpoints/phase2_sft_ab_lora/merged | 7856 | 85 | 92.7 | 3052 | 175 | 80.3% | 0 | 4.31 |

## Valid / progress / any-close by source (usable states)

| source | qwen3.5-0.8b-full-sft | qwen3.5-0.8b-lora-sft |
|---|---|---|
| minif2f/aime | 49.2% / 46.7% / 0.0% (15) | 45.8% / 40.8% / 0.0% (15) |
| minif2f/algebra | 66.7% / 66.0% / 55.6% (18) | 68.8% / 68.1% / 44.4% (18) |
| minif2f/amc12 | 45.6% / 44.2% / 15.6% (45) | 48.9% / 46.9% / 13.3% (45) |
| minif2f/imo | 55.6% / 53.1% / 0.0% (20) | 66.2% / 63.7% / 0.0% (20) |
| minif2f/induction | 57.8% / 56.2% / 37.5% (8) | 65.6% / 64.1% / 50.0% (8) |
| minif2f/mathd_algebra | 62.1% / 60.9% / 28.6% (70) | 63.4% / 61.8% / 21.4% (70) |
| minif2f/mathd_numbertheory | 65.4% / 64.0% / 56.7% (60) | 64.6% / 62.9% / 56.7% (60) |
| minif2f/numbertheory | 59.4% / 57.8% / 0.0% (8) | 62.5% / 60.9% / 12.5% (8) |
| traced/deepseek_prover_v1 | 75.7% / 74.2% / 59.8% (107) | 73.9% / 71.3% / 57.9% (107) |
| traced/goedel_lean_workbook_proofs | 73.2% / 72.0% / 35.4% (96) | 72.1% / 70.8% / 36.5% (96) |
| traced/goedel_sft_v2 | 66.9% / 66.6% / 35.7% (154) | 67.4% / 66.7% / 33.8% (154) |
| traced/lean_workbook | 72.2% / 71.9% / 58.3% (36) | 74.3% / 74.0% / 66.7% (36) |
| traced/leanabell_sft | 69.9% / 67.8% / 32.9% (76) | 69.9% / 66.9% / 31.6% (76) |
| traced/numinamath_lean_human | 45.1% / 43.2% / 17.4% (92) | 40.1% / 37.2% / 18.5% (92) |
| traced/numinamath_lean_kimina | 54.3% / 53.7% / 18.5% (81) | 53.5% / 53.4% / 18.5% (81) |
| traced/stp_lean_workbook | 68.0% / 67.2% / 29.2% (96) | 69.0% / 68.0% / 24.0% (96) |
