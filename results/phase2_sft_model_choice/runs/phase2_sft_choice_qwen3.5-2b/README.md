# SFT run `phase2_sft_choice_qwen3.5-2b`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-2B` |
| Data | `model_choice`: 33,107 examples, 7,500,857 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 1 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 246 |
| Examples | 33,107 |
| Tokens (prompt + completion) | 7,500,857 |
| Completion tokens | 1,030,501 |
| Padding overhead | 5.0% |
| Training time | 35.7 min |
| Tokens/s | 3,500 |
| Peak GPU memory | 14.5 GiB |
| Trainable parameters | 67,276,800 |
| Merge | 23 s |

## Validation

Loss is the mean completion-token loss over 858 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 128 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 0.7685 | 0.0% | 0.8% | 68 |
| 50 | 0.4685 | 13.5% | 10.9% | 56 |
| 100 | 0.4438 | 18.5% | 18.0% | 58 |
| 150 | 0.4203 | 20.0% | 16.4% | 67 |
| 200 | 0.4059 | 20.9% | 21.1% | 56 |
| 246 | 0.3991 | 20.3% | 19.5% | 56 |

Final mismatches (first five):

- target `have eq3 : (x + 5 * y) ^ 2 = 36 * (x * y) := by
  calc
    (x + 5 * y) ^ 2 = (6 * Real.sqrt (x * y)) ^ 2 := by
      rw [show 6 * Real.sqrt (x * y) = x + 5 * y by linarith [eq2]]
    _ = 36 * (Real.sqrt (x * y) ^ 2) := by
      ring_nf
    _ = 36 * (x * y) := by
      rw [Real.sq_sqrt (show (0 : ℝ) ≤ x * y by nlinarith)]`, generated `have h4 : 0 ≤ Real.sqrt (x * y) := Real.sqrt_nonneg (x * y)`

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `rw [h₄] at h₂ h₃`

- target `linarith`, generated `nlinarith [sq_nonneg (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)),
  sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x) - 2 * x * y * z),
  sq_nonneg (x * y * (x - y) - y * z * (y - z)),
  sq_nonneg (y * z * (y - z) - z * x * (z - x)),
  sq_nonneg (z * x * (z - x) - x * y * (x - y))]`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

- target `have h₃ : (1 / 1000 : ℝ) ∈ Set.Ico 0 1 := by
  constructor
  ·
    norm_num
  ·
    norm_num`, generated `have h₃ : √2 ∈ Set.Ioo 1 2 := by
  constructor
  ·
    norm_num [Real.sqrt_lt, Real.lt_sqrt]
    <;>
    norm_num
    <;>
    linarith [Real.sqrt_nonneg 2]
  ·
    norm_num [Real.sqrt_lt, Real.lt_sqrt]
    <;>
    norm_num
    <;>
    linarith [Real.sqrt_nonneg 2]`

Started 2026-10-11T17:54:35+00:00, git ff39505372; checkpoint `/workspace/checkpoints/phase2_sft_choice_qwen3.5-2b/adapter`, merged `/workspace/checkpoints/phase2_sft_choice_qwen3.5-2b/merged`.
