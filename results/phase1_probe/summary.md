# Phase 1 model probe

738 traced validation-split states (at most 5 per proof, goals of at most 3000 characters, never trained on) and 244 miniF2F-valid initial states. Per state k=8 samples at temperature 1.0 in the search's prompt format (few-shot: True, thinking: False, at most 256 tokens, stop at the closing fence), all requests queued at once (128 in flight) on one RTX 3090 with one model at a time. Every distinct parsed block ran on its state with `apply_block` (default heartbeats, 10 s wall clock).

Rates are per sample: parse fail = truncated or empty; forbidden = rejected before Lean; valid = at least one top-level tactic applied; fully valid = the whole block applied; progress = the goals changed; close = no goals left; exact match = equal to the traced step up to whitespace. `any` rates are per state (at least one of the k samples). States whose replay or start failed in Lean are excluded as infrastructure failures. Median progress log p: summed log-probability of the samples that made progress.

## All states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b | 982 | 2.2% | 2.0% | 7.1% | 5.9% | 6.2% | 0.8% | – | 42.7% | 37.7% | 5.5% | 7.64 | 27 | -10.76 |
| qwen2.5-math-1.5b-instruct | 982 | 3.8% | 0.9% | 0.9% | 0.5% | 0.7% | 0.1% | – | 7.1% | 5.4% | 0.9% | 7.62 | 32 | -26.41 |
| qwen3-1.7b | 982 | 21.1% | 0.7% | 9.0% | 5.9% | 8.3% | 1.6% | – | 32.8% | 29.7% | 7.0% | 5.01 | 82 | -3.77 |
| qwen3.5-2b | 981 | 9.3% | 6.1% | 18.0% | 9.9% | 16.9% | 4.8% | – | 68.7% | 65.7% | 19.8% | 6.67 | 77 | -15.06 |
| qwen3.5-2b-base | 982 | 14.7% | 7.3% | 16.2% | 9.5% | 15.1% | 2.9% | – | 67.1% | 64.5% | 15.5% | 6.20 | 95 | -16.57 |
| qwen3.5-2b-base-t0.8 | 982 | 20.9% | 5.5% | 20.5% | 13.1% | 19.5% | 3.8% | – | 72.3% | 69.2% | 18.3% | 5.79 | 115 | -12.87 |
| qwen3.5-2b-t0.8 | 982 | 13.2% | 3.8% | 23.4% | 14.4% | 22.6% | 6.9% | – | 73.2% | 70.6% | 23.6% | 6.48 | 92 | -12.16 |

## Traced validation states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b | 738 | 2.6% | 2.0% | 7.2% | 6.1% | 6.5% | 0.9% | 0.1% | 42.7% | 38.6% | 6.6% | 7.61 | 28 | -10.76 |
| qwen2.5-math-1.5b-instruct | 738 | 3.9% | 1.0% | 1.1% | 0.5% | 0.8% | 0.1% | 0.0% | 7.9% | 6.0% | 1.1% | 7.60 | 32 | -16.58 |
| qwen3-1.7b | 738 | 20.0% | 0.8% | 9.4% | 6.2% | 8.8% | 1.8% | 0.0% | 35.2% | 32.1% | 8.1% | 4.98 | 78 | -3.72 |
| qwen3.5-2b | 738 | 9.5% | 6.3% | 18.4% | 9.4% | 17.5% | 4.5% | 0.3% | 70.3% | 68.0% | 19.9% | 6.66 | 78 | -16.95 |
| qwen3.5-2b-base | 738 | 15.4% | 7.6% | 16.5% | 9.5% | 15.4% | 2.9% | 0.3% | 67.5% | 64.9% | 15.6% | 6.12 | 96 | -17.17 |
| qwen3.5-2b-base-t0.8 | 738 | 21.7% | 5.8% | 20.4% | 12.8% | 19.4% | 3.6% | 0.2% | 71.5% | 68.8% | 17.6% | 5.69 | 117 | -13.35 |
| qwen3.5-2b-t0.8 | 738 | 13.4% | 3.8% | 23.4% | 13.6% | 22.6% | 6.3% | 0.4% | 74.0% | 72.1% | 23.6% | 6.48 | 93 | -13.17 |

## miniF2F-valid initial states

| model | states | parse fail | forbidden | valid | fully valid | progress | close | exact match | any valid | any progress | any close | distinct / state | tokens / sample | median progress log p |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b | 244 | 0.9% | 1.9% | 6.7% | 5.5% | 5.4% | 0.3% | – | 42.6% | 34.8% | 2.0% | 7.75 | 24 | -10.27 |
| qwen2.5-math-1.5b-instruct | 244 | 3.3% | 0.8% | 0.6% | 0.3% | 0.5% | 0.1% | – | 4.9% | 3.7% | 0.4% | 7.67 | 33 | -63.77 |
| qwen3-1.7b | 244 | 24.3% | 0.5% | 7.7% | 4.9% | 7.0% | 0.9% | – | 25.4% | 22.5% | 3.7% | 5.09 | 93 | -4.02 |
| qwen3.5-2b | 243 | 8.6% | 5.8% | 16.6% | 11.3% | 15.4% | 5.6% | – | 63.8% | 58.8% | 19.3% | 6.73 | 77 | -9.41 |
| qwen3.5-2b-base | 244 | 12.6% | 6.6% | 15.3% | 9.4% | 14.0% | 3.0% | – | 66.0% | 63.1% | 15.2% | 6.43 | 93 | -14.36 |
| qwen3.5-2b-base-t0.8 | 244 | 18.2% | 4.5% | 20.9% | 14.1% | 19.8% | 4.5% | – | 74.6% | 70.5% | 20.5% | 6.09 | 108 | -11.22 |
| qwen3.5-2b-t0.8 | 244 | 12.6% | 3.7% | 23.6% | 16.5% | 22.6% | 8.6% | – | 70.9% | 66.0% | 23.8% | 6.49 | 88 | -8.60 |

## Throughput and Lean cost

Samples/s with all probe requests queued (few-shot prompt, shared prefix cached, real output lengths).

| model | checkpoint | samples | sampling s | samples/s | generated tokens/s | prompt tokens / state | prompt cache hits | prompts too long | Lean s / state |
|---|---|---|---|---|---|---|---|---|---|
| qwen2.5-math-1.5b | Qwen/Qwen2.5-Math-1.5B | 7856 | 51 | 154.9 | 4203 | 489 | 96.0% | 0 | 1.07 |
| qwen2.5-math-1.5b-instruct | Qwen/Qwen2.5-Math-1.5B-Instruct | 7856 | 58 | 134.4 | 4319 | 489 | 96.4% | 0 | 0.91 |
| qwen3-1.7b | Qwen/Qwen3-1.7B | 7856 | 167 | 47.0 | 3834 | 493 | 97.2% | 0 | 1.24 |
| qwen3.5-2b | Qwen/Qwen3.5-2B | 7856 | 162 | 48.5 | 3758 | 513 | 83.9% | 0 | 4.58 |
| qwen3.5-2b-base | Qwen/Qwen3.5-2B-Base | 7856 | 186 | 42.3 | 4036 | 513 | 85.7% | 0 | 2.37 |
| qwen3.5-2b-base-t0.8 | Qwen/Qwen3.5-2B-Base | 7856 | 220 | 35.8 | 4104 | 513 | 86.7% | 0 | 4.15 |
| qwen3.5-2b-t0.8 | Qwen/Qwen3.5-2B | 7856 | 186 | 42.3 | 3872 | 513 | 85.6% | 0 | 5.32 |

## Valid / progress / any-close by source (usable states)

| source | qwen2.5-math-1.5b | qwen2.5-math-1.5b-instruct | qwen3-1.7b | qwen3.5-2b | qwen3.5-2b-base | qwen3.5-2b-base-t0.8 | qwen3.5-2b-t0.8 |
|---|---|---|---|---|---|---|---|
| minif2f/aime | 4.2% / 1.7% / 0.0% (15) | 0.0% / 0.0% / 0.0% (15) | 0.8% / 0.8% / 0.0% (15) | 6.7% / 4.2% / 0.0% (15) | 13.3% / 9.2% / 0.0% (15) | 14.2% / 10.0% / 0.0% (15) | 6.7% / 2.5% / 0.0% (15) |
| minif2f/algebra | 6.9% / 6.9% / 5.6% (18) | 0.7% / 0.7% / 0.0% (18) | 6.9% / 6.9% / 5.6% (18) | 29.9% / 29.9% / 50.0% (18) | 18.8% / 18.8% / 33.3% (18) | 31.9% / 31.9% / 38.9% (18) | 40.3% / 40.3% / 50.0% (18) |
| minif2f/amc12 | 5.6% / 4.4% / 0.0% (45) | 0.3% / 0.0% / 0.0% (45) | 8.1% / 6.1% / 4.4% (45) | 12.2% / 9.7% / 9.1% (44) | 13.3% / 12.2% / 11.1% (45) | 16.1% / 15.0% / 11.1% (45) | 16.7% / 15.3% / 11.1% (45) |
| minif2f/imo | 3.8% / 3.8% / 0.0% (20) | 1.2% / 0.6% / 0.0% (20) | 2.5% / 2.5% / 0.0% (20) | 11.2% / 11.2% / 0.0% (20) | 9.4% / 9.4% / 0.0% (20) | 8.1% / 8.1% / 0.0% (20) | 11.9% / 11.2% / 0.0% (20) |
| minif2f/induction | 9.4% / 9.4% / 0.0% (8) | 0.0% / 0.0% / 0.0% (8) | 9.4% / 4.7% / 0.0% (8) | 9.4% / 9.4% / 12.5% (8) | 9.4% / 9.4% / 0.0% (8) | 10.9% / 10.9% / 0.0% (8) | 10.9% / 9.4% / 12.5% (8) |
| minif2f/mathd_algebra | 10.4% / 8.0% / 4.3% (70) | 1.2% / 1.1% / 1.4% (70) | 12.3% / 12.0% / 5.7% (70) | 18.8% / 18.0% / 20.0% (70) | 19.8% / 17.5% / 14.3% (70) | 27.7% / 26.2% / 27.1% (70) | 30.2% / 29.6% / 30.0% (70) |
| minif2f/mathd_numbertheory | 4.6% / 4.0% / 1.7% (60) | 0.2% / 0.2% / 0.0% (60) | 6.2% / 6.0% / 3.3% (60) | 19.2% / 17.9% / 31.7% (60) | 14.4% / 13.8% / 26.7% (60) | 20.0% / 19.2% / 31.7% (60) | 26.2% / 25.6% / 36.7% (60) |
| minif2f/numbertheory | 4.7% / 3.1% / 0.0% (8) | 0.0% / 0.0% / 0.0% (8) | 1.6% / 0.0% / 0.0% (8) | 10.9% / 9.4% / 0.0% (8) | 9.4% / 9.4% / 0.0% (8) | 25.0% / 25.0% / 0.0% (8) | 20.3% / 20.3% / 0.0% (8) |
| traced/deepseek_prover_v1 | 9.0% / 8.2% / 5.6% (107) | 0.6% / 0.5% / 1.9% (107) | 11.6% / 11.2% / 11.2% (107) | 23.0% / 21.7% / 29.0% (107) | 21.8% / 20.6% / 27.1% (107) | 27.1% / 25.9% / 29.0% (107) | 29.7% / 28.4% / 37.4% (107) |
| traced/goedel_lean_workbook_proofs | 8.9% / 8.3% / 8.3% (96) | 1.6% / 1.6% / 0.0% (96) | 6.5% / 5.3% / 6.2% (96) | 21.5% / 20.8% / 22.9% (96) | 17.2% / 16.4% / 17.7% (96) | 20.4% / 19.8% / 18.8% (96) | 27.1% / 26.6% / 26.0% (96) |
| traced/goedel_sft_v2 | 6.3% / 5.7% / 10.4% (154) | 0.7% / 0.7% / 0.6% (154) | 13.2% / 12.4% / 13.6% (154) | 18.4% / 18.1% / 20.8% (154) | 17.0% / 16.3% / 14.9% (154) | 20.4% / 19.7% / 16.2% (154) | 23.0% / 22.9% / 24.0% (154) |
| traced/lean_workbook | 7.3% / 7.3% / 8.3% (36) | 0.7% / 0.3% / 0.0% (36) | 5.6% / 5.2% / 16.7% (36) | 23.6% / 22.2% / 52.8% (36) | 21.5% / 20.1% / 33.3% (36) | 26.7% / 25.3% / 36.1% (36) | 35.8% / 35.4% / 52.8% (36) |
| traced/leanabell_sft | 6.9% / 5.6% / 3.9% (76) | 1.0% / 0.7% / 0.0% (76) | 10.5% / 9.9% / 1.3% (76) | 20.4% / 18.8% / 15.8% (76) | 16.6% / 14.6% / 9.2% (76) | 21.9% / 20.2% / 14.5% (76) | 22.4% / 21.1% / 14.5% (76) |
| traced/numinamath_lean_human | 6.4% / 5.4% / 4.3% (92) | 1.1% / 0.7% / 1.1% (92) | 11.4% / 10.7% / 2.2% (92) | 11.1% / 10.1% / 6.5% (92) | 8.6% / 7.5% / 5.4% (92) | 10.6% / 9.9% / 4.3% (92) | 14.1% / 13.0% / 9.8% (92) |
| traced/numinamath_lean_kimina | 6.3% / 5.6% / 1.2% (81) | 1.2% / 0.8% / 1.2% (81) | 4.6% / 4.5% / 7.4% (81) | 12.7% / 11.1% / 12.3% (81) | 13.1% / 11.4% / 9.9% (81) | 16.7% / 15.0% / 12.3% (81) | 17.3% / 16.0% / 16.0% (81) |
| traced/stp_lean_workbook | 6.6% / 6.0% / 8.3% (96) | 1.6% / 0.8% / 3.1% (96) | 6.2% / 5.7% / 6.2% (96) | 18.5% / 18.0% / 15.6% (96) | 17.8% / 17.1% / 14.6% (96) | 22.0% / 21.5% / 18.8% (96) | 23.7% / 22.9% / 20.8% (96) |
