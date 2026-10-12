# Phase 2: SFT v1, the development policy

Qwen3.5-2B (post-trained), LoRA rank 64 / alpha 64 on all language-model linear layers, learning rate 2e-4, 3%
warmup, cosine to 10%, two epochs over data `v1` (the merged tracing snapshot of 2026-10-11 20:39 UTC: 77,209
steps, 16.8M tokens, `results/phase2_sft_data/v1.md`), 32k padded tokens per step, one RTX 3090.
Config `experiments/configs/training/phase2_sft_v1.toml`; training report in `training.md`.

**Adapter: `/workspace/checkpoints/phase2_sft_v1/adapter`** (on the node; serve the raw `Qwen/Qwen3.5-2B` with LoRA
and load it at runtime). It is not merged.

## Training

1,097 steps, 33.5M tokens in 153 minutes (3,647 tokens/s), peak 14.5 GiB. On 1,509 held-out validation steps
(statements split by hash, 61% Goedel workbook like the training data):

| Step | Validation loss | Teacher-forced exact match | Greedy exact match (256) |
|---|---|---|---|
| 0 | 0.618 | 0.0% | 0.0% |
| 200 | 0.261 | 18.9% | 18.4% |
| 600 | 0.228 | 25.8% | 25.4% |
| 1,097 | 0.212 | 29.6% | 29.3% |

Loss was still falling in the second epoch (0.214 → 0.212 over the last 97 steps). Many remaining mismatches are
equivalent `nlinarith` hint lists in a different order or layout.

## Zero-shot probe

Served as an adapter on the raw base (as the search will run it), probed with `experiments/phase1_probe.py` on the
standard Phase 1 state set (738 traced validation states + 244 miniF2F-valid initial states), k=8 at temperature
1.0, max 256 tokens. Full tables in `probe/summary.md`. For comparison, the merged 7.5M-token model-choice run
(`results/phase2_sft_model_choice/`) and the few-shot base model (`results/phase1_probe/`):

| Policy | Valid | Progress | Close | Any progress@8 | Any close@8 | miniF2F any close@8 | Traced exact match | Parse fail | Tokens/sample |
|---|---|---|---|---|---|---|---|---|---|
| Qwen3.5-2B few-shot | 18.0% | 16.9% | 4.8% | 65.7% | 19.8% | 19.3% | – | 9.3% | 77 |
| Model-choice SFT (7.5M tokens, 1 epoch) | 62.9% | 61.1% | 15.5% | 97.4% | 31.7% | 28.3% | 13.8% | 1.1% | 26 |
| **SFT v1** (16.8M tokens, 2 epochs) | **71.4%** | **69.8%** | **20.5%** | 95.8% | **37.6%** | **30.7%** | **17.5%** | 2.3% | 35 |

Paired per-state differences of v1 against the model-choice SFT: any close@8 +5.9% (95% interval [+3.9, +8.0]),
any progress@8 −1.5% [−3.0, −0.2]. v1 is more confident: fewer distinct blocks per state (5.7 vs 6.3) and longer
blocks (35 vs 26 tokens, matching the Goedel-workbook-heavy data), so it closes more often but spreads its k samples
over fewer alternatives. Sampling through the adapter ran at 84 samples/s (the merged model-choice checkpoint: 95).
