# SFT run `phase2_sft_ab_lora`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-0.8B` |
| Data | `pilot`: 45,864 examples, 10,864,923 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 2 epoch(s) |
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
| Training time | 58.4 min |
| Tokens/s | 6,204 |
| Peak GPU memory | 8.3 GiB |
| Trainable parameters | 43,290,624 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 858 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 128 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 1.0924 | 0.0% | 0.0% | 46 |
| 50 | 0.5470 | 13.2% | 12.5% | 45 |
| 100 | 0.5064 | 14.3% | 12.5% | 45 |
| 150 | 0.4786 | 16.1% | 18.0% | 46 |
| 200 | 0.4572 | 18.2% | 16.4% | 46 |
| 250 | 0.4445 | 17.8% | 18.8% | 45 |
| 300 | 0.4445 | 17.9% | 18.0% | 46 |
| 350 | 0.4408 | 19.2% | 18.0% | 46 |
| 400 | 0.4363 | 19.5% | 17.2% | 46 |
| 450 | 0.4356 | 19.5% | 18.8% | 43 |
| 500 | 0.4237 | 19.2% | 18.0% | 46 |
| 550 | 0.4220 | 18.8% | 17.2% | 46 |
| 600 | 0.4215 | 20.9% | 22.7% | 51 |
| 650 | 0.4152 | 20.4% | 22.7% | 48 |
| 700 | 0.4143 | 22.3% | 23.4% | 51 |
| 714 | 0.4113 | 20.9% | 22.7% | 45 |

Final mismatches (first five):

- target `have eq3 : (x + 5 * y) ^ 2 = 36 * (x * y) := by
  calc
    (x + 5 * y) ^ 2 = (6 * Real.sqrt (x * y)) ^ 2 := by
      rw [show 6 * Real.sqrt (x * y) = x + 5 * y by linarith [eq2]]
    _ = 36 * (Real.sqrt (x * y) ^ 2) := by
      ring_nf
    _ = 36 * (x * y) := by
      rw [Real.sq_sqrt (show (0 : ℝ) ≤ x * y by nlinarith)]`, generated `have h4 : 0 ≤ x * y := by nlinarith`

- target `simp_all only [rpow_two, mul_neg, mul_one, sub_eq_add_neg]`, generated `have h₅ : y + z = 3 - x := by linarith`

- target `linarith`, generated `have := sq_nonneg (x * y * (x - y) - y * z * (y - z) - z * x * (z - x))`

- target `have h₁ : 0 < b * c := by nlinarith`, generated `have h₁ : 0 < b * c := mul_pos hb hc`

- target `have h₃ : (1 / 1000 : ℝ) ∈ Set.Ico 0 1 := by
  constructor
  ·
    norm_num
  ·
    norm_num`, generated `have h₃ : (1 : ℝ) < √2 := by
  exact_mod_cast h₂.1`

Started 2026-10-11T20:53:26+00:00, git 21245c0196; checkpoint `/workspace/checkpoints/phase2_sft_ab_lora/adapter`.
