# SFT run `phase2_sft_v2`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-2B` |
| Data | `v2`: 285,178 examples, 60,000,472 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 2 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 981 |
| Examples | 285,178 |
| Tokens (prompt + completion) | 60,000,472 |
| Completion tokens | 7,646,772 |
| Padding overhead | 5.0% |
| Training time | 143.2 min |
| Tokens/s | 6,982 |
| Peak GPU memory | 14.8 GiB |
| Trainable parameters | 67,276,800 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 2,000 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 256 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 0.6923 | 0.0% | 0.0% | 111 |
| 200 | 0.2676 | 21.5% | 20.3% | 107 |
| 400 | 0.2425 | 22.9% | 21.1% | 140 |
| 600 | 0.2288 | 24.4% | 20.3% | 153 |
| 800 | 0.2200 | 24.2% | 19.9% | 143 |
| 981 | 0.2153 | 25.8% | 21.5% | 121 |

Final mismatches (first five):

- target `subst hx`, generated `have h₀ : x ≠ 0 := by
  intro h
  rw [h] at hx
  norm_num at hx`

- target `simp only [hk]`, generated `intro total_cells covered_cells`

- target `rw [eq_comm]`, generated `linarith`

- target `field_simp`, generated `field_simp [h₁, h₂, h₃, h₄, h₅, h₆, h₇, h₈, h₉, h₁₀, h₁₁, h₁₂]`

- target `nlinarith [sq_nonneg (a * b * c), mul_self_nonneg (a - b * c), mul_self_nonneg (b - c * a), mul_self_nonneg (c - a * b)]
<;> simp [pow_add, mul_assoc]
<;> nlinarith`, generated `nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a),
  mul_pos ha hb, mul_pos hb hc, mul_pos hc ha,
  sq_nonneg (a - 1), sq_nonneg (b - 1), sq_nonneg (c - 1)]`

Started 2026-10-12T03:48:27+00:00, git 3ce77df855; checkpoint `/workspace/checkpoints/phase2_sft_v2/adapter`.
