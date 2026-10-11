# SFT run `phase2_sft_lr_full_1e-5`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-0.8B` |
| Data | `partial4`: 20,208 examples, 4,145,054 tokens |
| Method | full fine-tuning (fp32 master weights) |
| Optimization | AdamW, learning rate 1e-05, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 1 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 137 |
| Examples | 20,208 |
| Tokens (prompt + completion) | 4,145,054 |
| Completion tokens | 539,172 |
| Padding overhead | 4.6% |
| Training time | 10.5 min |
| Tokens/s | 6,576 |
| Peak GPU memory | 17.4 GiB |
| Trainable parameters | 752,393,024 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 372 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 64 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 1.0634 | 0.0% | 0.0% | 15 |
| 40 | 0.4449 | 9.9% | 7.8% | 14 |
| 80 | 0.3508 | 13.7% | 12.5% | 14 |
| 120 | 0.3165 | 16.9% | 17.2% | 14 |
| 137 | 0.3099 | 16.7% | 15.6% | 14 |

Final mismatches (first five):

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y = 3 - x - z := by linarith`

- target `linarith`, generated `nlinarith [sq_nonneg (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)),
  sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x)),
  sq_nonneg (x * y * (x - y) - y * z * (y - z) - z * x * (z - x)),
  sq_nonneg (x * y * (x + y) - y * z * (y + z) - z * x * (z + x)),
  sq_nonneg (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)),
  sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x)),
  sq_nonneg (x * y * (x - y) - y * z * (y - z) - z * x * (z - x)),
  sq_nonneg (x * y`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

- target `simpa [h₀, h₁] using h₃`, generated `simpa [h₀, h₁, h₂] using h₃`

- target `simp [ha, hb, hc, le_refl]`, generated `ring_nf`

Started 2026-10-11T17:08:46+00:00, git 87569d03d4; checkpoint `/workspace/checkpoints/phase2_sft_lr_full_1e-5/model`.
