# SFT run `phase2_sft_ab_full`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-0.8B` |
| Data | `pilot`: 45,864 examples, 10,864,923 tokens |
| Method | full fine-tuning (fp32 master weights) |
| Optimization | AdamW, learning rate 1e-05, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 2 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 1 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 714 |
| Examples | 91,728 |
| Tokens (prompt + completion) | 21,729,846 |
| Completion tokens | 3,020,936 |
| Padding overhead | 4.8% |
| Training time | 57.2 min |
| Tokens/s | 6,327 |
| Peak GPU memory | 17.4 GiB |
| Trainable parameters | 752,393,024 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 858 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 128 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 1.0924 | 0.0% | 0.0% | 33 |
| 50 | 0.5673 | 14.0% | 14.1% | 33 |
| 100 | 0.5147 | 14.2% | 12.5% | 33 |
| 150 | 0.4898 | 16.3% | 15.6% | 25 |
| 200 | 0.4671 | 17.5% | 18.8% | 33 |
| 250 | 0.4466 | 16.4% | 17.2% | 32 |
| 300 | 0.4412 | 17.1% | 14.1% | 33 |
| 350 | 0.4258 | 18.6% | 15.6% | 33 |
| 400 | 0.4322 | 19.9% | 17.2% | 31 |
| 450 | 0.4292 | 20.5% | 18.0% | 32 |
| 500 | 0.4166 | 20.2% | 19.5% | 32 |
| 550 | 0.4131 | 19.5% | 19.5% | 33 |
| 600 | 0.4112 | 20.6% | 20.3% | 31 |
| 650 | 0.4063 | 20.7% | 21.9% | 33 |
| 700 | 0.4022 | 21.3% | 21.1% | 29 |
| 714 | 0.4000 | 20.9% | 18.8% | 28 |

Final mismatches (first five):

- target `intro original rotated line final`, generated `let original := fun x : ℝ => 3 * x ^ 2 - 6 * x + 5`

- target `have eq3 : (x + 5 * y) ^ 2 = 36 * (x * y) := by
  calc
    (x + 5 * y) ^ 2 = (6 * Real.sqrt (x * y)) ^ 2 := by
      rw [show 6 * Real.sqrt (x * y) = x + 5 * y by linarith [eq2]]
    _ = 36 * (Real.sqrt (x * y) ^ 2) := by
      ring_nf
    _ = 36 * (x * y) := by
      rw [Real.sq_sqrt (show (0 : ℝ) ≤ x * y by nlinarith)]`, generated `have h4 : 0 ≤ x + y := by nlinarith`

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `simp_all only [add_assoc, add_left_comm, add_right_comm, add_comm, add_left_comm, add_right_comm]`

- target `linarith`, generated `have := sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x) - 2 * x * y * z)`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

Started 2026-10-11T20:38:18+00:00, git 21245c0196; checkpoint `/workspace/checkpoints/phase2_sft_ab_full/model`.
