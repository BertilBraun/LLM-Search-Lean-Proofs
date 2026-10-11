# SFT run `phase2_sft_lr_full_2e-5`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-0.8B` |
| Data | `partial4`: 20,208 examples, 4,145,054 tokens |
| Method | full fine-tuning (fp32 master weights) |
| Optimization | AdamW, learning rate 2e-05, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
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
| Tokens/s | 6,572 |
| Peak GPU memory | 17.4 GiB |
| Trainable parameters | 752,393,024 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 372 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 64 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 1.0634 | 0.0% | 0.0% | 15 |
| 40 | 0.5377 | 8.1% | 3.1% | 14 |
| 80 | 0.3724 | 11.8% | 7.8% | 14 |
| 120 | 0.3257 | 17.5% | 12.5% | 14 |
| 137 | 0.3151 | 16.7% | 14.1% | 14 |

Final mismatches (first five):

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y = 3 - x - z := by linarith`

- target `linarith`, generated `nlinarith [sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x) - 2 * x * y * z)]`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

- target `simpa [h₀, h₁] using h₃`, generated `simpa [h₀, h₁, h₂] using h₃`

- target `simp [ha, hb, hc, le_refl]`, generated `ring_nf`

Started 2026-10-11T16:43:09+00:00, git 882528c947; checkpoint `/workspace/checkpoints/phase2_sft_lr_full_2e-5/model`.
