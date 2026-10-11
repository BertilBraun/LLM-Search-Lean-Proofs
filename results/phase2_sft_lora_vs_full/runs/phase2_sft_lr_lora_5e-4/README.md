# SFT run `phase2_sft_lr_lora_5e-4`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-0.8B` |
| Data | `partial4`: 20,208 examples, 4,145,054 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0005, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
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
| Training time | 11.0 min |
| Tokens/s | 6,290 |
| Peak GPU memory | 8.3 GiB |
| Trainable parameters | 43,290,624 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 372 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 64 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 1.0638 | 0.0% | 0.0% | 22 |
| 40 | 0.4984 | 10.2% | 7.8% | 21 |
| 80 | 0.3707 | 11.0% | 9.4% | 21 |
| 120 | 0.3210 | 16.9% | 12.5% | 21 |
| 137 | 0.3131 | 17.2% | 15.6% | 15 |

Final mismatches (first five):

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y = 3 - x - z := by linarith`

- target `linarith`, generated `nlinarith [sq_nonneg (x * y * (x - y) - y * z * (y - z) - z * x * (z - x))]`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

- target `simpa [h₀, h₁] using h₃`, generated `simp at h₃`

- target `simp [ha, hb, hc, le_refl]`, generated `ring_nf`

Started 2026-10-11T17:21:14+00:00, git 0499cf49a7; checkpoint `/workspace/checkpoints/phase2_sft_lr_lora_5e-4/adapter`.
