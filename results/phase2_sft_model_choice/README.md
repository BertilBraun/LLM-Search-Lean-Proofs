# Phase 2: base-model choice after an identical short LoRA SFT

**Recommendation: Qwen3.5-2B (the post-trained checkpoint).** After the same SFT, Qwen3.5-2B and Qwen3.5-2B-Base
are indistinguishable on every probe metric, and both are clearly ahead of Qwen3-1.7B and Qwen2.5-Math-1.5B-Instruct.
Between the two 2B checkpoints the post-trained one wins on what the probe cannot see: it keeps a trained thinking
mode, which stages 2–3 of the training ladder (single-step reasoning, expert iteration with reasoning) bootstrap from.
The base checkpoint would need a teacher for that.

## Setup

- Data: `model_choice` (`results/phase2_sft_data/model_choice.md`): 33,107 traced train-split steps from the tracing
  pilot, 7.5M Qwen3.5 tokens, equal token shares per source, completions capped at the search's 256 tokens.
- Training, identical for every model: LoRA rank 64, alpha 64, on all language-model linear layers (attention,
  Gated DeltaNet projections, MLP), AdamW at 2e-4 (best of 1e-4/2e-4/5e-4 in the 0.8B check, see
  `results/phase2_sft_lora_vs_full/`), 3% warmup, cosine to 10%, one epoch, 32k padded tokens per step,
  length-grouped batches, completion-only loss, bf16 with gradient checkpointing, one RTX 3090.
  Config `experiments/configs/training/phase2_sft_model_choice.toml`; per-run details under `runs/`.
- Validation inside training: 858 held-out traced steps (statements split by hash). Teacher-forced exact match =
  every target token is the argmax; generation exact match = greedy block equals the target on 128 of them.
- Probe: the merged checkpoint served by vLLM and probed zero-shot with `experiments/phase1_probe.py` on the
  Phase 1 state set (738 traced validation states + 244 miniF2F-valid initial states), k=8 samples at temperature
  1.0, max 256 tokens, every distinct block run in Lean. Full tables in `probe/summary.md`.

## Results

| Model | Train min | Tokens/s | Val loss | Teacher-forced EM | Greedy EM | Valid | Progress | Close | Any progress@8 | Any close@8 | Probe samples/s | Lean s/state |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.5-2B | 36 | 3,500 | 0.399 | 20.3% | 19.5% | 62.9% | 61.1% | 15.5% | 97.4% | 31.7% | 95 | 3.2 |
| Qwen3.5-2B-Base | 34 | 3,657 | 0.389 | 19.8% | 18.0% | 64.0% | 62.1% | 15.9% | 96.6% | 32.2% | 96 | 3.2 |
| Qwen3-1.7B | 33 | 3,693 | 0.493* | 16.4% | 15.6% | 52.6% | 50.6% | 13.7% | 94.1% | 29.9% | 196 | 2.9 |
| Qwen2.5-Math-1.5B-Instruct | 28 | 4,250 | 0.588* | 15.4% | 14.8% | 40.9% | 39.5% | 11.2% | 88.1% | 27.2% | 200 | 2.5 |

Probe rates are per sample over all 982 states; `any@8` per state. *Per-token losses of other tokenizers are not
comparable with Qwen3.5's; exact match is.

Before SFT (few-shot, `results/phase1_probe/`), valid/progress/any-close were 18.0%/16.9%/19.8% for Qwen3.5-2B,
16.2%/15.1%/15.5% for Qwen3.5-2B-Base, 9.0%/8.3%/7.0% for Qwen3-1.7B and 0.9%/0.7%/0.9% for
Qwen2.5-Math-1.5B-Instruct. A 35-minute SFT lifts Qwen3.5-2B to 3.5× the valid rate, cuts parse failures from 9% to
1%, forbidden blocks from 6% to 0.1% and tokens per sample from 77 to 26.

Paired per-state differences against Qwen3.5-2B (95% bootstrap intervals over the 982 states):

| Model | Any close@8 | Any progress@8 |
|---|---|---|
| Qwen3.5-2B-Base | +0.5% [−0.9, +2.0] | −0.7% [−1.9, +0.5] |
| Qwen3-1.7B | −1.7% [−3.9, +0.5] | −3.3% [−4.9, −1.6] |
| Qwen2.5-Math-1.5B-Instruct | −4.5% [−6.7, −2.2] | −9.3% [−11.5, −7.2] |
| Qwen3-1.7B at k=16 | +1.6% [−0.5, +3.8] | +1.0% [−0.2, +2.2] |
| Qwen3.5-2B at k=16 | +6.4% [+4.3, +8.5] | +1.6% [+0.6, +2.6] |

## Compute-matched check

After SFT the outputs are short (~25 tokens), and at that shape the dense models sample about twice as fast as the
hybrid Qwen3.5 (196 vs 95 samples/s with all probe requests queued; with long few-shot outputs both ran at ~47).
So the k=16 rows above compare equal GPU time: Qwen3-1.7B at k=16 took 76 s of sampling, Qwen3.5-2B at k=8 83 s.
At equal sampling time Qwen3-1.7B is level (+1.6% any-close, not significant), but it gets there with twice the
distinct candidates per state (12.4 vs 6.3) and 1.5× the Lean time (4.7 vs 3.2 Lean s/state). Lean is the scarcer
resource at these rates: Qwen3.5-2B at k=8 already needs ~38 Lean CPU-seconds per GPU-second (11.9 states/s ×
3.2 s), close to the 46-core quota, so the faster sampler would be Lean-bound and gain nothing. Per sample,
Qwen3.5-2B is clearly better (valid 62.9% vs 52.6%), and that is what counts when Lean, not the GPU, limits the
search. The search runs of row 1 should still be re-checked with the SFT policy once it exists.

## Other observations

- Exact match of greedy generations agrees with teacher-forced exact match within sampling noise, so the cheap
  teacher-forced number (computed on all 858 validation steps in the same forward pass as the loss) is a usable
  training-time proxy.
- Validation loss still falls at the end of every run (Qwen3.5-2B: 0.406 → 0.399 over the last 46 steps), so the
  full SFT should use substantially more data.
- Qwen3.5-2B-Base reaches a slightly lower validation loss (0.389 vs 0.399) but the probe does not separate them.
- Training throughput at this sequence shape (237 tokens per example): Qwen3.5-2B 3.5k tokens/s on one 3090,
  7.1k tokens/s on both GPUs with DDP (2.0× scaling, `experiments/phase2_sft.py` under `torchrun`).

## Full SFT

Proposed here and run as SFT v2 (`results/phase2_sft_v2/`) with a 60M-token budget instead of 80M:

- Model Qwen3.5-2B, LoRA rank 64 on all language-model linear layers, learning rate 2e-4, cosine, one epoch,
  32k tokens per GPU per step on both GPUs (64k per step): `experiments/configs/training/phase2_sft_v2.toml`.
- Data `v2`: equal source shares (`experiments/configs/training/phase2_sft_data_v2.toml`) over the merged snapshot
  after the narrowed full trace.
- Time: at 7.1k tokens/s on two GPUs, 60M tokens take 2.3 h of training plus evaluations; 80M would take 3.1 h.
- Training needs `flash-linear-attention` (pure Triton, now in the `ml` extra); without it the Gated DeltaNet
  layers fall back to a PyTorch path that is half as fast (3.6k vs 6.7k tokens/s on Qwen3.5-0.8B in a
  micro-benchmark).
