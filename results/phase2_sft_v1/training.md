# SFT run `phase2_sft_v1`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-2B` |
| Data | `v1`: 77,209 examples, 16,756,384 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 2 epoch(s) |
| Batching | 32,768 padded tokens per micro-batch, 1 micro-batches per step per GPU, 1 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 1,097 |
| Examples | 154,418 |
| Tokens (prompt + completion) | 33,512,768 |
| Completion tokens | 5,031,812 |
| Padding overhead | 4.8% |
| Training time | 153.2 min |
| Tokens/s | 3,647 |
| Peak GPU memory | 14.5 GiB |
| Trainable parameters | 67,276,800 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 1,509 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 256 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 0.6176 | 0.0% | 0.0% | 122 |
| 200 | 0.2611 | 18.9% | 18.4% | 103 |
| 400 | 0.2421 | 25.9% | 23.4% | 95 |
| 600 | 0.2282 | 25.8% | 25.4% | 101 |
| 800 | 0.2204 | 29.8% | 31.6% | 96 |
| 1000 | 0.2140 | 28.9% | 29.3% | 98 |
| 1097 | 0.2117 | 29.6% | 29.3% | 93 |

Final mismatches (first five):

- target `nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a), mul_nonneg ha.le hb.le, mul_nonneg hb.le hc.le, mul_nonneg ha.le hc.le,
  mul_nonneg (sq_nonneg (a - b)) hc.le, mul_nonneg (sq_nonneg (b - c)) ha.le, mul_nonneg (sq_nonneg (c - a)) hb.le,
  mul_nonneg (sq_nonneg (a - b)) ha.le, mul_nonneg (sq_nonneg (b - c)) hb.le, mul_nonneg (sq_nonneg (c - a)) hc.le,
  mul_nonneg (sq_nonneg (a + b - 2 * c)) hc.le, mul_nonneg (sq_nonneg (b + c - 2 * a)) ha.le, mul_nonneg (sq_nonneg (c + a - 2 * b)) hb.le]
<;> linarith`, generated `nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a), mul_nonneg ha.le hb.le, mul_nonneg hb.le hc.le, mul_nonneg hc.le ha.le,
  mul_nonneg (sq_nonneg (a - b)) hc.le, mul_nonneg (sq_nonneg (b - c)) ha.le, mul_nonneg (sq_nonneg (c - a)) hb.le,
  mul_nonneg (sq_nonneg (a - b)) hb.le, mul_nonneg (sq_nonneg (b - c)) hc.le, mul_nonneg (sq_nonneg (c - a)) ha.le]`

- target `nlinarith [sq_sqrt (show (0 : ℝ) ≤ 3 by norm_num), sq_sqrt (show (0 : ℝ) ≤ a^2 + a by nlinarith),
  sq_sqrt (show (0 : ℝ) ≤ b^2 + b by nlinarith), sq_sqrt (show (0 : ℝ) ≤ c^2 + c by nlinarith)]`, generated `nlinarith [sq_sqrt (show 0 ≤ 3 by norm_num),
  sq_sqrt (show 0 ≤ a ^ 2 + a by nlinarith),
  sq_sqrt (show 0 ≤ b ^ 2 + b by nlinarith),
  sq_sqrt (show 0 ≤ c ^ 2 + c by nlinarith)]`

- target `have h₃ : 0 < a ^ 2 * b * c := by nlinarith`, generated `field_simp`

- target `field_simp [ha.ne', hb.ne', hc.ne', add_assoc]`, generated `field_simp [ha.ne', hb.ne', hc.ne']`

- target `constructor`, generated `ring_nf`

Started 2026-10-11T22:37:47+00:00, git 5b8ef73f97; checkpoint `/workspace/checkpoints/phase2_sft_v1/adapter`.
