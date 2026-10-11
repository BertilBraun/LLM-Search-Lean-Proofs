# SFT run `phase2_sft_lr_full_5e-6`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-0.8B` |
| Data | `partial4`: 20,208 examples, 4,145,054 tokens |
| Method | full fine-tuning (fp32 master weights) |
| Optimization | AdamW, learning rate 5e-06, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
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
| Training time | 10.6 min |
| Tokens/s | 6,541 |
| Peak GPU memory | 17.4 GiB |
| Trainable parameters | 752,393,024 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 372 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 64 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 1.0634 | 0.0% | 0.0% | 16 |
| 40 | 0.3996 | 14.2% | 14.1% | 14 |
| 80 | 0.3450 | 11.3% | 14.1% | 14 |
| 120 | 0.3172 | 15.3% | 15.6% | 14 |
| 137 | 0.3115 | 16.4% | 18.8% | 15 |

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

- target `simp [ha, hb, hc, le_refl]`, generated `ring_nf`

- target `rintro (rfl | rfl) <;> linear_combination 0`, generated `rintro (rfl | rfl) <;>
simp_all only [mul_add, mul_sub, mul_one, mul_neg, mul_zero, sub_mul, sub_sub_cancel,
  sub_neg_eq_add, sub_zero, add_zero, add_sub_cancel, add_assoc, add_left_comm,
  add_comm, add_left_comm, add_assoc, add_left_comm, add_comm, add_assoc, add_left_comm,
  add_comm, add_assoc, add_left_comm, add_comm, add_assoc, add_left_comm, add_comm,
  add_assoc, add_left_comm, add_comm, add_assoc, add_left_comm, add_comm, add_assoc,
  add_left_comm, add_comm, add_assoc, add_left_comm, add_comm, add_assoc, add_left_comm,
  add_comm, add_assoc, add_left_comm, add_comm, add_assoc, add_left_comm, add_comm,
  add_assoc, add_left_comm, add_comm, add_assoc, add_left_comm, add_comm, add_assoc,
  add_left_comm, add_comm, add_assoc, add_left_comm, add_comm, add_assoc, add_left_comm,
  add_comm, add_assoc, add_left_comm, add_comm, add`

Started 2026-10-11T20:13:56+00:00, git 04d5ff1012; checkpoint `/workspace/checkpoints/phase2_sft_lr_full_5e-6/model`.
