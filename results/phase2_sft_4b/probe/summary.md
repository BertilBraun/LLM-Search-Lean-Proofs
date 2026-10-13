# Phase 1 model probe

738 traced validation-split states (at most 5 per proof, goals of at most 3000 characters, never trained on) and 244 miniF2F-valid initial states. Per state k=8 samples at temperature 1.0 in the search's prompt format (few-shot: False, thinking: False, at most 256 tokens, stop at the closing fence), all requests queued at once (128 in flight) on one RTX 3090 with one model at a time. Every distinct parsed block ran on its state with `apply_block` (default heartbeats, 10 s wall clock).

Rates are per sample: parse fail = truncated or empty; forbidden = rejected before Lean; valid = at least one top-level tactic applied; fully valid = the whole block applied; progress = the goals changed; close = no goals left; exact match = equal to the traced step up to whitespace. `any` rates are per state (at least one of the k samples). States whose replay or start failed in Lean are excluded as infrastructure failures. Median progress log p: summed log-probability of the samples that made progress.

## All states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v2 | 982 | 1.5% | 0.0% | 72.3% | 72.3% | 70.4% | 20.0% | – | 97.8% | 97.3% | 36.9% | 5.98 | 32 | -2.82 |
| qwen3.5-4b-sft | 982 | 1.5% | 0.0% | 72.4% | 72.4% | 70.4% | 19.3% | – | 98.3% | 97.6% | 38.7% | 6.13 | 31 | -3.08 |

## Traced validation states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v2 | 738 | 1.6% | 0.1% | 72.3% | 72.3% | 71.0% | 21.7% | 16.6% | 97.2% | 96.6% | 38.5% | 5.78 | 33 | -2.49 |
| qwen3.5-4b-sft | 738 | 1.7% | 0.0% | 73.1% | 73.1% | 71.5% | 21.1% | 14.8% | 98.1% | 97.6% | 40.9% | 5.89 | 32 | -2.68 |

## miniF2F-valid initial states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v2 | 244 | 1.2% | 0.0% | 72.4% | 72.4% | 68.4% | 15.0% | – | 99.6% | 99.2% | 32.0% | 6.57 | 27 | -3.96 |
| qwen3.5-4b-sft | 244 | 1.0% | 0.0% | 70.3% | 70.3% | 67.0% | 13.9% | – | 98.8% | 97.5% | 32.0% | 6.87 | 28 | -4.30 |

## Throughput and Lean cost

Samples/s with all probe requests queued (few-shot prompt, shared prefix cached, real output lengths).

| model | checkpoint | samples | sampling s | samples/s | generated tokens/s | prompt tokens / state | prompt cache hits | prompts too long | Lean s / state |
|---|---|---|---|---|---|---|---|---|---|
| qwen3.5-2b-sft-v2 | Qwen/Qwen3.5-2B + /workspace/checkpoints/phase2_sft_v2/adapter | 7856 | 124 | 63.1 | 2017 | 175 | 81.6% | 0 | 5.07 |
| qwen3.5-4b-sft | Qwen/Qwen3.5-4B + /workspace/checkpoints/phase2_sft_4b/adapter | 7856 | 175 | 44.9 | 1410 | 175 | 81.4% | 0 | 4.60 |

## Valid / progress / any-close by source (usable states)

| source | qwen3.5-2b-sft-v2 | qwen3.5-4b-sft |
|---|---|---|
| minif2f/aime | 66.7% / 55.8% / 0.0% (15) | 55.0% / 48.3% / 0.0% (15) |
| minif2f/algebra | 76.4% / 75.7% / 55.6% (18) | 77.1% / 75.7% / 55.6% (18) |
| minif2f/amc12 | 65.3% / 60.6% / 13.3% (45) | 64.4% / 61.1% / 13.3% (45) |
| minif2f/imo | 68.8% / 61.3% / 0.0% (20) | 73.8% / 71.2% / 0.0% (20) |
| minif2f/induction | 67.2% / 65.6% / 37.5% (8) | 62.5% / 59.4% / 37.5% (8) |
| minif2f/mathd_algebra | 74.6% / 72.3% / 31.4% (70) | 73.2% / 70.7% / 30.0% (70) |
| minif2f/mathd_numbertheory | 79.2% / 75.0% / 58.3% (60) | 73.1% / 68.5% / 61.7% (60) |
| minif2f/numbertheory | 57.8% / 57.8% / 25.0% (8) | 68.8% / 67.2% / 12.5% (8) |
| traced/deepseek_prover_v1 | 83.5% / 81.7% / 65.4% (107) | 84.3% / 81.7% / 69.2% (107) |
| traced/goedel_lean_workbook_proofs | 79.4% / 78.0% / 36.5% (96) | 81.6% / 79.6% / 40.6% (96) |
| traced/goedel_sft_v2 | 69.5% / 68.5% / 34.4% (154) | 73.7% / 73.1% / 40.3% (154) |
| traced/lean_workbook | 78.8% / 78.5% / 66.7% (36) | 79.9% / 78.8% / 66.7% (36) |
| traced/leanabell_sft | 79.8% / 77.8% / 42.1% (76) | 78.1% / 77.0% / 42.1% (76) |
| traced/numinamath_lean_human | 53.3% / 51.1% / 18.5% (92) | 50.8% / 48.4% / 16.3% (92) |
| traced/numinamath_lean_kimina | 60.5% / 59.6% / 21.0% (81) | 62.5% / 61.1% / 22.2% (81) |
| traced/stp_lean_workbook | 77.2% / 76.7% / 37.5% (96) | 74.7% / 73.4% / 39.6% (96) |
