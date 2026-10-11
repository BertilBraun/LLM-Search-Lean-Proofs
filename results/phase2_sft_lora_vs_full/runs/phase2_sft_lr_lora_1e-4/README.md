# SFT run `phase2_sft_lr_lora_1e-4`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-0.8B` |
| Data | `partial4`: 20,208 examples, 4,145,054 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0001, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
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
| Tokens/s | 6,292 |
| Peak GPU memory | 8.3 GiB |
| Trainable parameters | 43,290,624 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 372 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 64 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 1.0638 | 0.0% | 0.0% | 22 |
| 40 | 0.3877 | 12.1% | 12.5% | 21 |
| 80 | 0.3430 | 11.0% | 10.9% | 21 |
| 120 | 0.3252 | 15.1% | 14.1% | 21 |
| 137 | 0.3235 | 15.6% | 12.5% | 21 |

Final mismatches (first five):

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y = 3 - x - z := by linarith`

- target `intro h`, generated `intro hR`

- target `linarith`, generated `nlinarith [sq_nonneg (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)),
  sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x)),
  sq_nonneg (x * y * (x - y) - y * z * (y - z) - z * x * (z - x)),
  sq_nonneg (x * y * (x + y) - y * z * (y + z) - z * x * (z + x)),
  sq_nonneg (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)),
  sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x)),
  sq_nonneg (x * y * (x - y) - y * z * (y - z) - z * x * (z - x)),
  sq_nonneg (x * y`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

- target `simpa [h₀, h₁] using h₃`, generated `simp [h₂, h₃]`

Started 2026-10-11T16:55:21+00:00, git 882528c947; checkpoint `/workspace/checkpoints/phase2_sft_lr_lora_1e-4/adapter`.
