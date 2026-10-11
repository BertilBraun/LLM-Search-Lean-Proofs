# Phase 2: LoRA vs full fine-tuning (Qwen3.5-0.8B)

**The gap is small.** On identical data, batches and schedule (two epochs of the tracing pilot, 21.7M tokens), LoRA
rank 64 on all language-model linear layers ends 0.011 above full fine-tuning in validation loss (0.411 vs 0.400,
2.8%) with the same teacher-forced exact match (20.9% both). In the Lean probe the two are within noise: valid 63.8%
vs 63.9%, any-close@8 32.6% vs 33.8% (paired difference −1.2%, 95% interval [−2.9, +0.4]), any-progress@8 +0.6%
[−0.7, +1.9]. LoRA stays the default.

## Learning-rate check (`learning_rate_check.md`)

One epoch of `partial4` (4.1M tokens, the first four pilot sources; 372 validation steps) per learning rate, so that
each arm of the A/B runs at its own best rate:

| Arm | Learning rate | Final validation loss | Teacher-forced exact match |
|---|---|---|---|
| LoRA | 1e-4 | 0.3235 | 15.6% |
| LoRA | **2e-4** | **0.3121** | 16.9% |
| LoRA | 5e-4 | 0.3131 | 17.2% |
| Full | 5e-6 | 0.3115 | 16.4% |
| Full | **1e-5** | **0.3099** | 16.7% |
| Full | 2e-5 | 0.3151 | 16.7% |
| Full | 5e-5 | 0.3445 | 16.4% |

The best rates are 2e-4 (LoRA, flat between 2e-4 and 5e-4) and 1e-5 (full), a ratio of 20 rather than 10. At the
best rates the one-epoch gap is 0.002 (0.7%).

## A/B (`ab.md`)

Both arms: Qwen3.5-0.8B, data `pilot` (45,864 steps, 10.9M tokens, completions ≤ 256 tokens) for two epochs, 714 steps
of 32k padded tokens, 3% warmup, cosine to 10%, gradient checkpointing, one RTX 3090 each; validation on 858
held-out steps. Full fine-tuning keeps fp32 master weights with bf16 autocast and freezes the vision tower.

| Arm | Learning rate | Validation loss | Teacher-forced EM | Greedy EM (128) | Valid | Progress | Close | Any close@8 | Tokens/s | Peak GiB |
|---|---|---|---|---|---|---|---|---|---|---|
| LoRA r64 | 2e-4 | 0.4113 | 20.9% | 22.7% | 63.8% | 62.2% | 16.0% | 32.6% | 6,204 | 8.3 |
| Full | 1e-5 | 0.4000 | 20.9% | 18.8% | 63.9% | 62.7% | 16.9% | 33.8% | 6,327 | 17.4 |

LoRA is ahead for the first 250 steps (higher learning rate); full fine-tuning overtakes it at step 300 and pulls
ahead in the second pass over the data (from step 357), where the extra capacity helps to fit repeated examples. Probe details in
`probe/summary.md` (same state set and settings as the model choice: 982 states, k=8, temperature 1.0, zero-shot).

Other findings:

- On Qwen3.5-0.8B full fine-tuning is no slower than LoRA (6.3k vs 6.2k tokens/s): the adapters' extra small
  matmuls cost about what the weight gradients do. Full fine-tuning needs twice the memory, and on 2B it would not
  fit next to fp32 Adam states on a 24 GB card.
- The 0.8B policy after 21.7M tokens probes as well as the 2B after 7.5M (`results/phase2_sft_model_choice/`), and
  vLLM samples it no faster at this output length (92 vs 95 samples/s): with ~30-token outputs the hybrid model's
  serving is bound by per-sequence overhead, not by model size.
