# SFT runs

Data: `model_choice`. Arrows go from the evaluation before training to the final one. Validation loss is the mean completion-token loss on held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations with the normalized target. Per-run details under `runs/`.

| Run | Model | Method | Learning rate | Tokens | Steps | Minutes | Tokens/s | Peak GiB | Validation loss | Teacher-forced exact match | Generation exact match |
|---|---|---|---|---|---|---|---|---|---|---|---|
| phase2_sft_choice_qwen3.5-2b | `Qwen/Qwen3.5-2B` | LoRA r64 | 0.0002 | 7,500,857 | 246 | 36 | 3,500 | 14.5 | 0.7685 → 0.3991 | 0.0% → 20.3% | 0.8% → 19.5% |
| phase2_sft_choice_qwen3.5-2b-base | `Qwen/Qwen3.5-2B-Base` | LoRA r64 | 0.0002 | 7,500,857 | 246 | 34 | 3,657 | 14.5 | 0.7542 → 0.3890 | 0.0% → 19.8% | 0.0% → 18.0% |
| phase2_sft_choice_qwen3-1.7b | `Qwen/Qwen3-1.7B` | LoRA r64 | 0.0002 | 7,335,011 | 243 | 33 | 3,693 | 13.1 | 2.3278 → 0.4925 | 0.7% → 16.4% | 2.3% → 15.6% |
| phase2_sft_choice_qwen2.5-math-1.5b-instruct | `Qwen/Qwen2.5-Math-1.5B-Instruct` | LoRA r64 | 0.0002 | 7,202,583 | 237 | 28 | 4,250 | 12.1 | 2.5276 → 0.5877 | 0.0% → 15.4% | 0.0% → 14.8% |

## Validation loss during training

| Step | phase2_sft_choice_qwen3.5-2b | phase2_sft_choice_qwen3.5-2b-base | phase2_sft_choice_qwen3-1.7b | phase2_sft_choice_qwen2.5-math-1.5b-instruct |
|---|---|---|---|---|
| 0 | 0.7685 | 0.7542 | 2.3278 | 2.5276 |
| 50 | 0.4685 | 0.4553 | 0.6219 | 0.8246 |
| 100 | 0.4438 | 0.4323 | 0.5695 | 0.7098 |
| 150 | 0.4203 | 0.4059 | 0.5255 | 0.6260 |
| 200 | 0.4059 | 0.3949 | 0.5007 | 0.6023 |
| 237 |  |  |  | 0.5877 |
| 243 |  |  | 0.4925 |  |
| 246 | 0.3991 | 0.3890 |  |  |
