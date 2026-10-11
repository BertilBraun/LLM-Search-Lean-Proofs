# Phase 1 model probe

738 traced validation-split states (at most 5 per proof, goals of at most 3000 characters, never trained on) and 244 miniF2F-valid initial states. Per state k=8 samples at temperature 1.0 in the search's prompt format (few-shot: False, thinking: False, at most 256 tokens, stop at the closing fence), all requests queued at once (128 in flight) on one RTX 3090 with one model at a time. Every distinct parsed block ran on its state with `apply_block` (default heartbeats, 10 s wall clock).

Rates are per sample: parse fail = truncated or empty; forbidden = rejected before Lean; valid = at least one top-level tactic applied; fully valid = the whole block applied; progress = the goals changed; close = no goals left; exact match = equal to the traced step up to whitespace. `any` rates are per state (at least one of the k samples). States whose replay or start failed in Lean are excluded as infrastructure failures. Median progress log p: summed log-probability of the samples that made progress.

## All states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b-instruct-sft | 981 | 0.8% | 0.1% | 40.9% | 40.9% | 39.5% | 11.2% | – | 90.2% | 88.1% | 27.2% | 7.02 | 28 | -3.39 |
| qwen3-1.7b-sft | 982 | 0.5% | 0.0% | 52.6% | 52.6% | 50.6% | 13.7% | – | 95.8% | 94.1% | 29.9% | 6.67 | 23 | -3.26 |
| qwen3-1.7b-sft-k16 | 981 | 0.6% | 0.0% | 51.9% | 51.9% | 49.5% | 13.2% | – | 98.8% | 98.4% | 33.3% | 12.41 | 24 | -3.15 |
| qwen3.5-2b-base-sft | 982 | 1.2% | 0.1% | 64.0% | 64.0% | 62.1% | 15.9% | – | 97.3% | 96.6% | 32.2% | 6.23 | 27 | -2.84 |
| qwen3.5-2b-sft | 982 | 1.1% | 0.1% | 62.9% | 62.9% | 61.1% | 15.5% | – | 97.6% | 97.4% | 31.7% | 6.30 | 26 | -2.99 |
| qwen3.5-2b-sft-k16 | 981 | 1.0% | 0.0% | 62.7% | 62.7% | 60.8% | 15.7% | – | 99.1% | 99.0% | 38.1% | 11.77 | 27 | -3.04 |

## Traced validation states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b-instruct-sft | 738 | 0.8% | 0.1% | 42.3% | 42.3% | 41.1% | 12.4% | 8.4% | 90.9% | 88.9% | 28.9% | 6.91 | 29 | -3.18 |
| qwen3-1.7b-sft | 738 | 0.6% | 0.1% | 54.5% | 54.5% | 52.8% | 14.7% | 10.5% | 95.9% | 94.7% | 31.4% | 6.56 | 23 | -3.14 |
| qwen3-1.7b-sft-k16 | 738 | 0.6% | 0.0% | 53.8% | 53.8% | 51.8% | 13.9% | 10.2% | 99.1% | 98.5% | 35.1% | 12.21 | 24 | -3.09 |
| qwen3.5-2b-base-sft | 738 | 1.1% | 0.1% | 64.8% | 64.8% | 63.1% | 16.5% | 14.1% | 97.0% | 96.5% | 33.2% | 6.09 | 27 | -2.60 |
| qwen3.5-2b-sft | 738 | 1.1% | 0.1% | 63.8% | 63.8% | 62.3% | 16.3% | 13.8% | 97.4% | 97.4% | 32.8% | 6.15 | 27 | -2.79 |
| qwen3.5-2b-sft-k16 | 738 | 1.1% | 0.0% | 63.8% | 63.8% | 62.4% | 16.3% | 13.1% | 98.9% | 98.9% | 40.0% | 11.46 | 27 | -2.80 |

## miniF2F-valid initial states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b-instruct-sft | 243 | 0.7% | 0.0% | 36.4% | 36.4% | 34.7% | 7.5% | – | 88.1% | 85.6% | 22.2% | 7.36 | 27 | -4.08 |
| qwen3-1.7b-sft | 244 | 0.5% | 0.0% | 46.9% | 46.9% | 43.9% | 10.9% | – | 95.5% | 92.2% | 25.4% | 6.98 | 24 | -3.54 |
| qwen3-1.7b-sft-k16 | 243 | 0.6% | 0.1% | 46.1% | 46.1% | 42.7% | 11.1% | – | 97.9% | 97.9% | 28.0% | 13.01 | 24 | -3.34 |
| qwen3.5-2b-base-sft | 244 | 1.5% | 0.1% | 61.4% | 61.4% | 58.9% | 14.1% | – | 98.0% | 97.1% | 29.1% | 6.65 | 27 | -3.65 |
| qwen3.5-2b-sft | 244 | 0.9% | 0.1% | 60.1% | 60.1% | 57.4% | 13.2% | – | 98.0% | 97.1% | 28.3% | 6.78 | 25 | -3.62 |
| qwen3.5-2b-sft-k16 | 243 | 0.8% | 0.1% | 59.3% | 59.3% | 56.2% | 13.9% | – | 99.6% | 99.2% | 32.5% | 12.70 | 26 | -3.63 |

## Throughput and Lean cost

Samples/s with all probe requests queued (few-shot prompt, shared prefix cached, real output lengths).

| model | checkpoint | samples | sampling s | samples/s | generated tokens/s | prompt tokens / state | prompt cache hits | prompts too long | Lean s / state |
|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b-instruct-sft | /workspace/checkpoints/phase2_sft_choice_qwen2.5-math-1.5b-instruct/merged | 7856 | 39 | 200.3 | 5651 | 167 | 89.2% | 0 | 2.45 |
| qwen3-1.7b-sft | /workspace/checkpoints/phase2_sft_choice_qwen3-1.7b/merged | 7856 | 40 | 195.5 | 4546 | 171 | 89.6% | 0 | 2.94 |
| qwen3-1.7b-sft-k16 | /workspace/checkpoints/phase2_sft_choice_qwen3-1.7b/merged | 15712 | 76 | 207.0 | 4927 | 171 | 92.0% | 0 | 4.73 |
| qwen3.5-2b-base-sft | /workspace/checkpoints/phase2_sft_choice_qwen3.5-2b-base/merged | 7856 | 82 | 95.5 | 2600 | 175 | 78.9% | 0 | 3.18 |
| qwen3.5-2b-sft | /workspace/checkpoints/phase2_sft_choice_qwen3.5-2b/merged | 7856 | 83 | 95.2 | 2514 | 175 | 79.6% | 0 | 3.15 |
| qwen3.5-2b-sft-k16 | /workspace/checkpoints/phase2_sft_choice_qwen3.5-2b/merged | 15712 | 119 | 132.6 | 3565 | 175 | 85.9% | 0 | 6.26 |

## Valid / progress / any-close by source (usable states)

| source | qwen2.5-math-1.5b-instruct-sft | qwen3-1.7b-sft | qwen3-1.7b-sft-k16 | qwen3.5-2b-base-sft | qwen3.5-2b-sft | qwen3.5-2b-sft-k16 |
|---|---|---|---|---|---|---|
| minif2f/aime | 29.2% / 25.8% / 0.0% (15) | 35.0% / 29.2% / 0.0% (15) | 33.8% / 28.3% / 6.7% (15) | 60.8% / 57.5% / 0.0% (15) | 55.0% / 51.7% / 0.0% (15) | 48.3% / 41.7% / 0.0% (15) |
| minif2f/algebra | 49.3% / 45.1% / 38.9% (18) | 50.0% / 49.3% / 50.0% (18) | 51.0% / 51.0% / 44.4% (18) | 71.5% / 70.1% / 55.6% (18) | 68.8% / 67.4% / 61.1% (18) | 69.1% / 68.1% / 50.0% (18) |
| minif2f/amc12 | 37.2% / 35.2% / 9.1% (44) | 43.9% / 41.7% / 8.9% (45) | 42.6% / 38.6% / 9.1% (44) | 56.4% / 53.1% / 13.3% (45) | 58.6% / 54.7% / 13.3% (45) | 54.3% / 48.9% / 13.6% (44) |
| minif2f/imo | 36.2% / 36.2% / 0.0% (20) | 44.4% / 43.1% / 0.0% (20) | 44.7% / 43.8% / 0.0% (20) | 55.6% / 53.1% / 0.0% (20) | 52.5% / 50.0% / 0.0% (20) | 56.2% / 54.1% / 0.0% (20) |
| minif2f/induction | 18.8% / 18.8% / 0.0% (8) | 29.7% / 28.1% / 0.0% (8) | 21.9% / 21.9% / 0.0% (8) | 65.6% / 62.5% / 25.0% (8) | 59.4% / 57.8% / 0.0% (8) | 55.5% / 55.5% / 50.0% (8) |
| minif2f/mathd_algebra | 44.6% / 42.9% / 21.4% (70) | 52.3% / 48.0% / 24.3% (70) | 51.6% / 47.8% / 30.0% (70) | 63.9% / 61.3% / 25.7% (70) | 62.9% / 60.0% / 24.3% (70) | 62.1% / 59.9% / 31.4% (70) |
| minif2f/mathd_numbertheory | 28.3% / 26.9% / 46.7% (60) | 50.0% / 46.9% / 53.3% (60) | 49.9% / 45.4% / 56.7% (60) | 62.1% / 60.4% / 58.3% (60) | 59.4% / 57.3% / 58.3% (60) | 61.7% / 58.4% / 61.7% (60) |
| minif2f/numbertheory | 23.4% / 23.4% / 0.0% (8) | 31.2% / 29.7% / 0.0% (8) | 28.1% / 26.6% / 0.0% (8) | 50.0% / 48.4% / 0.0% (8) | 59.4% / 57.8% / 0.0% (8) | 56.2% / 53.1% / 12.5% (8) |
| traced/deepseek_prover_v1 | 50.9% / 49.3% / 46.7% (107) | 64.0% / 61.8% / 54.2% (107) | 61.9% / 59.8% / 66.4% (107) | 75.5% / 73.7% / 59.8% (107) | 75.4% / 73.9% / 57.9% (107) | 74.1% / 72.3% / 73.8% (107) |
| traced/goedel_lean_workbook_proofs | 46.7% / 45.7% / 24.0% (96) | 55.7% / 53.9% / 29.2% (96) | 55.7% / 54.0% / 29.2% (96) | 72.0% / 70.4% / 31.2% (96) | 67.8% / 66.7% / 27.1% (96) | 68.3% / 67.2% / 33.3% (96) |
| traced/goedel_sft_v2 | 46.9% / 46.0% / 36.4% (154) | 59.7% / 58.5% / 35.1% (154) | 60.9% / 59.6% / 40.3% (154) | 66.4% / 65.5% / 37.0% (154) | 66.2% / 65.3% / 39.0% (154) | 66.6% / 65.5% / 39.6% (154) |
| traced/lean_workbook | 49.0% / 48.3% / 47.2% (36) | 57.3% / 56.9% / 52.8% (36) | 53.5% / 52.4% / 61.1% (36) | 71.2% / 69.4% / 55.6% (36) | 71.5% / 70.5% / 47.2% (36) | 73.8% / 72.7% / 58.3% (36) |
| traced/leanabell_sft | 42.4% / 41.0% / 19.7% (76) | 53.5% / 51.6% / 23.7% (76) | 55.3% / 52.1% / 27.6% (76) | 69.1% / 66.8% / 26.3% (76) | 66.8% / 64.0% / 26.3% (76) | 64.2% / 62.7% / 36.8% (76) |
| traced/numinamath_lean_human | 24.2% / 22.6% / 13.0% (92) | 39.8% / 37.4% / 13.0% (92) | 39.5% / 36.1% / 14.1% (92) | 42.8% / 40.2% / 13.0% (92) | 42.8% / 40.8% / 14.1% (92) | 45.2% / 42.4% / 16.3% (92) |
| traced/numinamath_lean_kimina | 33.2% / 31.8% / 25.9% (81) | 46.1% / 45.4% / 28.4% (81) | 42.7% / 41.4% / 25.9% (81) | 52.9% / 51.7% / 18.5% (81) | 54.2% / 52.5% / 23.5% (81) | 54.2% / 52.7% / 28.4% (81) |
| traced/stp_lean_workbook | 43.5% / 42.3% / 19.8% (96) | 55.1% / 53.1% / 20.8% (96) | 53.6% / 51.4% / 21.9% (96) | 68.6% / 66.7% / 28.1% (96) | 66.4% / 65.1% / 26.0% (96) | 65.5% / 64.5% / 37.5% (96) |
