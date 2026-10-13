# Phase 2: Qwen3.5-4B student SFT

Student for the reasoning-teacher experiment. Recipe: SFT v2's recipe on Qwen3.5-4B. That is LoRA rank 64 / alpha 64
on all language-model linear layers, learning rate 2e-4, 3% warmup, cosine to 10%, one epoch, non-thinking format
(empty think block). The data is `4b` (`results/phase2_sft_data/4b.md`): 95,180 steps and 20.0M tokens subsampled
from the SFT v2 snapshot with v2's source shares. Training ran packed with compiled layers
(`results/gpu_utilization/`), 16k tokens per micro-batch, two micro-batches per GPU and step (64k tokens per step),
DDP on both RTX 3090s. Config `experiments/configs/training/phase2_sft_4b.toml`; training report in `training.md`.

**Adapter: `/workspace/checkpoints/phase2_sft_4b/adapter`** (on the node; serve the raw `Qwen/Qwen3.5-4B` with LoRA
and load it at runtime; not merged).

## Training

- Throughput: 3,969 tokens/s over the run (4,510 in a 14-step DDP benchmark; 32k-token micro-batches run out of
  memory). 307 steps took 84 minutes, peak 17.8 GiB per GPU.
- The first attempt crashed at its first in-training evaluation: greedy generation with 64 prompts next to the 4B
  training state ran out of memory on rank 0. The rerun generates 16 at a time and evaluates only before and after
  training.
- Validation (first 1,000 of the 2,000 held-out steps): loss 0.709 → 0.218, teacher-forced exact match 1.1% → 27.2%,
  greedy exact match on 128 steps 1.6% → 28.9%.

On all 2,000 validation steps of `4b`, scored with the same code:

| Adapter | Data | Loss | Teacher-forced exact match |
|---|---|---|---|
| SFT v2 (Qwen3.5-2B) | 60M tokens | **0.215** | 25.1% |
| Qwen3.5-4B student | 20M tokens | 0.219 | **25.7%** |

## Zero-shot probe vs SFT v2

Both served as adapters on their raw base, probed zero-shot and non-thinking on the standard Phase 1 state set
(738 traced validation states + 244 miniF2F-valid initial states), k=8 at temperature 1.0, max 256 tokens. The
Lean side of both ran back to back in this run; v2's samples are those of `results/phase2_sft_v2/`. Full tables in
`probe/summary.md`.

| Policy | Valid | Progress | Close | Any progress@8 | Any close@8 | Traced any close@8 | miniF2F valid | miniF2F any close@8 | Samples/s |
|---|---|---|---|---|---|---|---|---|---|
| SFT v2, Qwen3.5-2B, 60M tokens | 72.3% | 70.4% | 20.0% | 97.3% | 36.9% | 38.5% | 72.4% | 32.0% | 63 |
| Qwen3.5-4B, 20M tokens | 72.4% | 70.4% | 19.3% | 97.6% | **38.7%** | **40.9%** | 70.3% | 32.0% | 45 |

Paired per-state differences, 4B − v2 (95% bootstrap intervals over 982 states): any close@8 +1.8% [−0.2, +3.8],
any progress@8 +0.3% [−0.9, +1.5].

With a third of the data the 4B student matches SFT v2: equal valid and progress rates, a slightly higher any-close
on the traced states, and the same any-close on miniF2F. Sampling through the adapter is about 30% slower than the
2B (45 vs 63 samples/s, both measured under node load).
