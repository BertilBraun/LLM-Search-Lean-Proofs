# SFT run `phase2_sft_choice_qwen2.5-math-1.5b-instruct`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen2.5-Math-1.5B-Instruct` |
| Data | `model_choice`: 33,107 examples, 7,202,583 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 1 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 237 |
| Examples | 33,107 |
| Tokens (prompt + completion) | 7,202,583 |
| Completion tokens | 1,009,240 |
| Padding overhead | 5.3% |
| Training time | 28.2 min |
| Tokens/s | 4,250 |
| Peak GPU memory | 12.1 GiB |
| Trainable parameters | 73,859,072 |
| Merge | 35 s |

## Validation

Loss is the mean completion-token loss over 858 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 128 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 2.5276 | 0.0% | 0.0% | 52 |
| 50 | 0.8246 | 10.8% | 8.6% | 50 |
| 100 | 0.7098 | 13.9% | 14.1% | 49 |
| 150 | 0.6260 | 14.7% | 14.8% | 49 |
| 200 | 0.6023 | 15.7% | 14.1% | 50 |
| 237 | 0.5877 | 15.4% | 14.8% | 49 |

Final mismatches (first five):

- target `constructor`, generated `have h₁ : 0 ≤ a * b := by positivity`

- target `have eq3 : (x + 5 * y) ^ 2 = 36 * (x * y) := by
  calc
    (x + 5 * y) ^ 2 = (6 * Real.sqrt (x * y)) ^ 2 := by
      rw [show 6 * Real.sqrt (x * y) = x + 5 * y by linarith [eq2]]
    _ = 36 * (Real.sqrt (x * y) ^ 2) := by
      ring_nf
    _ = 36 * (x * y) := by
      rw [Real.sq_sqrt (show (0 : ℝ) ≤ x * y by nlinarith)]`, generated `have h4 : 0 ≤ Real.sqrt (x * y) := Real.sqrt_nonneg (x * y)`

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y = 3 - x - z := by linarith`

- target `linarith`, generated `have : 0 ≤ (x * y * (x - y) + y * z * (y - z) + z * x * (z - x)) ^ 2 := by
  positivity`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := by positivity`

Started 2026-10-11T20:11:48+00:00, git 21245c0196; checkpoint `/workspace/checkpoints/phase2_sft_choice_qwen2.5-math-1.5b-instruct/adapter`, merged `/workspace/checkpoints/phase2_sft_choice_qwen2.5-math-1.5b-instruct/merged`.
