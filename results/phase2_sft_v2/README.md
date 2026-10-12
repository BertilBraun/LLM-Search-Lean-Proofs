# Phase 2: SFT v2, the final policy SFT

Qwen3.5-2B (post-trained), LoRA rank 64 / alpha 64 on all language-model linear layers, learning rate 2e-4, 3%
warmup, cosine to 10%, one epoch over data `v2` (`results/phase2_sft_data/v2.md`): the tracing snapshot refreshed
after the narrowed full trace, 285,178 steps and 60.0M tokens with equal source shares, so DeepSeek-Prover-V1,
Leanabell, the Goedel workbook and the small sources are used whole and STP fills the rest. DDP on both RTX 3090s,
32k padded tokens per GPU and step (64k per step). Config `experiments/configs/training/phase2_sft_v2.toml`; training
report in `training.md`.

**Adapter: `/workspace/checkpoints/phase2_sft_v2/adapter`** (on the node; serve the raw `Qwen/Qwen3.5-2B` with LoRA
and load it at runtime). It is not merged.

## Training

981 steps, 60.0M tokens in 143 minutes (6,982 tokens/s on two GPUs, 1.9× one GPU), peak 14.8 GiB per GPU. On its
2,000 held-out validation steps (statements split by hash; 47% STP): loss 0.692 → 0.268 (step 200) → 0.243 (400) →
0.229 (600) → 0.220 (800) → 0.215 (981); teacher-forced exact match 25.8%, greedy exact match 21.5% (256 steps).

The two validation sets differ in mix, so both adapters were scored on both (teacher-forced, same code):

| Adapter | v2 validation loss | v2 teacher-forced EM | v1 validation loss | v1 teacher-forced EM |
|---|---|---|---|---|
| SFT v1 (16.8M tokens, 2 epochs) | 0.253 | 23.7% | 0.212 | 29.6% |
| SFT v2 (60M tokens, 1 epoch) | **0.215** | **25.8%** | **0.203** | 28.2% |

v2 is better on both validation sets by loss and on the broader one by exact match. v1 keeps a small exact-match
edge on its own Goedel-workbook-heavy set, which it saw twice.

## Zero-shot probe

Served as an adapter on the raw base, probed with `experiments/phase1_probe.py` on the standard Phase 1 state set
(738 traced validation states + 244 miniF2F-valid initial states), k=8 at temperature 1.0, max 256 tokens. The Lean
side of both probes was re-run back to back, because the first v2 run overlapped the deferred tracing job and
timed out more often (3.6% of blocks vs 2.1%). Full tables in `probe/summary.md`.

| Policy | Valid | Progress | Close | Any progress@8 | Any close@8 | miniF2F valid | miniF2F any close@8 | Traced exact match | Parse fail | Distinct / state |
|---|---|---|---|---|---|---|---|---|---|---|
| SFT v1 | 71.0% | 69.4% | 20.1% | 95.7% | 36.8% | 70.4% | 30.7% | 17.5% | 2.3% | 5.7 |
| **SFT v2** | **71.9%** | **69.9%** | 19.7% | **96.9%** | 36.3% | **72.2%** | **32.0%** | 16.6% | **1.5%** | **6.0** |

Paired per-state differences, v2 − v1 (95% bootstrap intervals): any close@8 −0.5% [−2.1, +1.0], any progress@8
+1.2% [0.0, +2.4]; on the miniF2F states alone any close +1.2% [−2.0, +4.5]. In the probe the two adapters are equal
within noise. v2 is slightly broader (more distinct candidates, fewer parse failures, shorter blocks) and generalizes
better by validation loss, so it is the policy for the search rows.

Lean seconds per state (8–10) are inflated by the concurrent tracing job (load average 50–80 on 46 cores) and are
not comparable with earlier probes. The sampling rate is not comparable either (63 vs 84 samples/s), because it
depends on the node's CPU load during sampling.
