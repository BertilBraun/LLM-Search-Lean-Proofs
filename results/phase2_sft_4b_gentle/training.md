# SFT run `phase2_sft_4b_gentle`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-4B` |
| Data | `4b`: 107,336 examples, 24,501,536 tokens |
| Method | LoRA rank 64, alpha 64, dropout 0 |
| Optimization | AdamW, learning rate 0.0002, warmup 0.03, cosine to 0.1, weight decay 0, clip 1, 1 epoch(s) |
| Batching | 16,384 padded tokens per micro-batch, 2 micro-batches per step per GPU, 2 GPU(s), length-grouped, gradient checkpointing on |
| Kernels | flash-linear-attention |

## Throughput

| Quantity | Value |
|---|---|
| Steps | 377 |
| Examples | 107,181 |
| Tokens (prompt + completion) | 24,465,290 |
| Completion tokens | 5,780,341 |
| Padding overhead | 0.0% |
| Training time | 102.9 min |
| Tokens/s | 3,964 |
| Peak GPU memory | 17.8 GiB |
| Trainable parameters | 129,859,584 |
| Merge | not merged |

## Validation

Loss is the mean completion-token loss over 1,000 held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations on the first 128 of them with the normalized target.

| Step | Validation loss | Teacher-forced exact match | Generation exact match | Seconds |
|---|---|---|---|---|
| 0 | 0.7094 | 1.1% | 1.6% | 249 |
| 377 | 0.2208 | 26.3% | 28.9% | 188 |

Final mismatches (first five):

- target `nlinarith [sq_nonneg (a + b + c + d), sq_nonneg (a - b + c - d), sq_nonneg (a - b - c + d), sq_nonneg (a + b - c - d), sq_nonneg (a^2 - b^2 + c^2 - d^2), sq_nonneg (a^2 - b^2 - c^2 + d^2), sq_nonneg (a * b - b * c + c * d - d * a), sq_nonneg (a * b - b * c - c * d + d * a), sq_nonneg (a * b + b * c + c * d + d * a)]`, generated `nlinarith [sq_nonneg (a - b + c - d), sq_nonneg (a + b - c - d), sq_nonneg (a - b - c + d),
  sq_nonneg (a + b + c - d), sq_nonneg (a - b + c + d), sq_nonneg (a + b - c + d),
  sq_nonneg (a - b - c - d), sq_nonneg (a + b + c + d)]`

- target `nlinarith [sq_nonneg (x ^ 2 - y ^ 2), sq_nonneg (y ^ 2 - z ^ 2),
  sq_nonneg (z ^ 2 - x ^ 2), sq_nonneg (x * y), sq_nonneg (y * z), sq_nonneg (z * x),
  sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x),
  sq_nonneg (x ^ 2 + y ^ 2 - z ^ 2), sq_nonneg (y ^ 2 + z ^ 2 - x ^ 2),
  sq_nonneg (z ^ 2 + x ^ 2 - y ^ 2)]`, generated `nlinarith [sq_nonneg (x^2 - y^2), sq_nonneg (y^2 - z^2), sq_nonneg (z^2 - x^2),
  sq_nonneg (x^2 + y^2), sq_nonneg (y^2 + z^2), sq_nonneg (z^2 + x^2),
  sq_nonneg (x^2 + 2 * y^2 - z^2), sq_nonneg (y^2 + 2 * z^2 - x^2),
  sq_nonneg (z^2 + 2 * x^2 - y^2)]`

- target `have : x = 3 := by omega`, generated `omega`

- target `simp [pow_two, mul_assoc]`, generated `nlinarith [sq_nonneg (a - 1), sq_nonneg (b - 1), sq_nonneg (c - 1), sq_nonneg (d - 1),
  sq_nonneg (a - b), sq_nonneg (a - c), sq_nonneg (a - d), sq_nonneg (b - c), sq_nonneg (b - d),
  sq_nonneg (c - d), sq_nonneg (a + b + c + d - 4)]`

- target `nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a),
  mul_self_nonneg (a * b + b * c + c * a - 3),
  mul_self_nonneg (a * b - b * c),
  mul_self_nonneg (b * c - c * a),
  mul_self_nonneg (c * a - a * b)]`, generated `nlinarith [sq_nonneg (a - b), sq_nonneg (b - c), sq_nonneg (c - a),
  sq_nonneg (a * b - b * c), sq_nonneg (b * c - c * a), sq_nonneg (c * a - a * b)]`

Started 2026-10-14T21:23:45+00:00, git dece5b565c; checkpoint `/workspace/checkpoints/phase2_sft_4b_gentle/adapter`.
