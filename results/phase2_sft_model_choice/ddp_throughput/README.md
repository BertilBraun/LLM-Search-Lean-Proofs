# SFT run `phase2_sft_ddp_smoke`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-2B` |
| Data | `model_choice`: 33,107 examples, 7,500,857 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 2 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 30 |
| Examples | 7,672 |
| Tokens (prompt + completion) | 1,827,703 |
| Completion tokens | 271,373 |
| Padding overhead | 4.9% |
| Training time | 4.3 min |
| Tokens/s | 7,102 |
| Peak GPU memory | 14.8 GiB |
| Trainable parameters | 67,276,800 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 256 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 32 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 0.7889 | 0.0% | 0.0% | 37 |
| 30 | 0.4937 | 13.7% | 18.8% | 23 |

Final mismatches (first five):

- target `intro original rotated line final`, generated `let original := fun x => 3 * x ^ 2 - 6 * x + 5`

- target `have eq3 : (x + 5 * y) ^ 2 = 36 * (x * y) := by
  calc
    (x + 5 * y) ^ 2 = (6 * Real.sqrt (x * y)) ^ 2 := by
      rw [show 6 * Real.sqrt (x * y) = x + 5 * y by linarith [eq2]]
    _ = 36 * (Real.sqrt (x * y) ^ 2) := by
      ring_nf
    _ = 36 * (x * y) := by
      rw [Real.sq_sqrt (show (0 : ℝ) ≤ x * y by nlinarith)]`, generated `have h4 : 0 ≤ Real.sqrt (x * y) := Real.sqrt_nonneg (x * y)`

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y = 3 - x - z := by linarith`

- target `linarith`, generated `nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x),
  sq_nonneg (x * y - y * z), sq_nonneg (y * z - z * x), sq_nonneg (z * x - x * y),
  sq_nonneg (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)),
  sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x) - 2 * x * y * z)]`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

Started 2026-10-11T22:05:21+00:00, git 21245c0196; checkpoint `/workspace/checkpoints/phase2_sft_ddp_smoke/adapter`.
