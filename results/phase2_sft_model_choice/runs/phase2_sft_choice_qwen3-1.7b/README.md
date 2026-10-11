# SFT run `phase2_sft_choice_qwen3-1.7b`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3-1.7B` |
| Data | `model_choice`: 33,107 examples, 7,335,011 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 1 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 243 |
| Examples | 33,107 |
| Tokens (prompt + completion) | 7,335,011 |
| Completion tokens | 1,009,240 |
| Padding overhead | 5.1% |
| Training time | 33.1 min |
| Tokens/s | 3,693 |
| Peak GPU memory | 13.1 GiB |
| Trainable parameters | 69,730,304 |
| Merge | 33 s |

## Validation

Loss is the mean completion-token loss over 858 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 128 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 2.3278 | 0.7% | 2.3% | 61 |
| 50 | 0.6219 | 7.3% | 10.2% | 61 |
| 100 | 0.5695 | 12.6% | 10.2% | 61 |
| 150 | 0.5255 | 15.0% | 13.3% | 61 |
| 200 | 0.5007 | 16.4% | 16.4% | 61 |
| 243 | 0.4925 | 16.4% | 15.6% | 61 |

Final mismatches (first five):

- target `have eq3 : (x + 5 * y) ^ 2 = 36 * (x * y) := by
  calc
    (x + 5 * y) ^ 2 = (6 * Real.sqrt (x * y)) ^ 2 := by
      rw [show 6 * Real.sqrt (x * y) = x + 5 * y by linarith [eq2]]
    _ = 36 * (Real.sqrt (x * y) ^ 2) := by
      ring_nf
    _ = 36 * (x * y) := by
      rw [Real.sq_sqrt (show (0 : ℝ) ≤ x * y by nlinarith)]`, generated `have h4 : 0 ≤ Real.sqrt (x * y) := Real.sqrt_nonneg (x * y)`

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y = 3 - x - z := by
  linarith`

- target `linarith`, generated `nlinarith [sq_nonneg (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)),
  sq_nonneg (x * y * (x + y) + y * z * (y + z) + z * x * (z + x) - 2 * x * y * z)]`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

- target `have h₃ : (1 / 1000 : ℝ) ∈ Set.Ico 0 1 := by
  constructor
  ·
    norm_num
  ·
    norm_num`, generated `have h₃ := h 1 (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n => 0) (fun n`

Started 2026-10-11T19:28:26+00:00, git 1cf565fa71; checkpoint `/workspace/checkpoints/phase2_sft_choice_qwen3-1.7b/adapter`, merged `/workspace/checkpoints/phase2_sft_choice_qwen3-1.7b/merged`.
