# Phase 2 SFT data sets

Built by `experiments/phase2_sft_data.py` from the traced proof steps in `/workspace/data/traced` (tracing pilot:
the first ~2,000 selected proofs of each of the eight traced sources). One example is one traced train-split step:
the goals before it, rendered with the policy's own `render_prompt` (system message, goals in a lean block, no
lemmas, empty thinking block, prefilled opening fence), and the step as completion (`render_completion`: block,
closing fence, end of turn). Only completion tokens carry loss. Identical (goals, step) pairs are kept once,
validation pairs that also occur in train are dropped, and no step contained a forbidden token. Token counts are
Qwen3.5 tokens (prompt + completion).

| Data set | Used by | Budget | Completion cap | Train examples | Train tokens | Completion tokens | Validation examples |
|---|---|---|---|---|---|---|---|
| `partial4` | full-FT/LoRA learning-rate check | all | 512 | 20,208 | 4,145,054 | 539,172 | 372 |
| `pilot` | LoRA vs full fine-tuning A/B | all | 256 | 45,864 | 10,864,923 | 1,510,468 | 858 |
| `model_choice` | model-choice runs | 7.5M | 256 | 33,107 | 7,500,857 | 1,030,501 | 858 |
| `v1` | SFT v1 (development policy) | all | 256 | 77,209 | 16,756,384 | 2,515,906 | 1,509 |
| `v2` | SFT v2 (final policy) | 60M | 256 | 285,178 | 60,000,472 | 7,646,772 | 2,000 |
| `4b` | Qwen3.5-4B student | 20M | 256 | 95,180 | 20,000,914 | 2,552,397 | 2,000 |

`partial4` was built while the pilot was still running and holds only the first four sources. `v1` is built from
the merged tracing snapshot of 2026-10-11 20:39 UTC (`--snapshot`: 82,027 train steps, pilot plus the first main
shards; 55% Goedel workbook, no Numina human proofs). `v2` is built from the snapshot refreshed on 2026-10-12
03:42 UTC after the narrowed full trace (130 shards, 408,774 train steps, again no Numina human proofs): with equal
shares, DeepSeek-Prover-V1, Leanabell, the Goedel workbook and the small sources are used whole and STP fills the
rest (18.2M of its ~40M tokens). `4b` subsamples the same snapshot to 20M tokens with v2's per-source token shares
as weights (24.3% Goedel workbook, 30.3% STP, 18.5% DeepSeek, 18.5% Leanabell, 4.4% Goedel SFT v2, 3.3% Numina
Kimina, 0.6% Lean Workbook). Details per source
(steps, duplicates, length drops, token shares, length quantiles) in `<name>.md`, machine-readable in `<name>.json`.

Findings:

- Examples are short: 237 tokens on average (prompt 204, completion 33; p99 817). Only 14% of the tokens are
  completion tokens. The ~900k steps of the full trace hold roughly 200M tokens.
- Completions are capped at 256 tokens because the search samples at most 256 tokens per block and drops truncated
  blocks. The cap removes 27% of the `goedel_sft_v2` steps (long `have ... := by` blocks), 5–7% of the NuminaMath
  steps and under 1% elsewhere; with a 512-token cap `goedel_sft_v2` would lose 13%. Raising the search's `max_tokens` would let those
  steps back in.
- Equal token weights with water-filling: in `model_choice`, `deepseek_prover_v1` and `lean_workbook` are used whole
  and every other source gets the same 1.05M tokens.
