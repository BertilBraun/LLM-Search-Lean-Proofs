# SFT runs

Data: `pilot`. Arrows go from the evaluation before training to the final one. Validation loss is the mean completion-token loss on held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations with the normalized target. Per-run details under `runs/`.

| Run | Model | Method | Learning rate | Tokens | Steps | Minutes | Tokens/s | Peak GiB | Validation loss | Teacher-forced exact match | Generation exact match |
|---|---|---|---|---|---|---|---|---|---|---|---|
| phase2_sft_ab_lora | `Qwen/Qwen3.5-0.8B` | LoRA r64 | 0.0002 | 21,729,846 | 714 | 58 | 6,204 | 8.3 | 1.0924 → 0.4113 | 0.0% → 20.9% | 0.0% → 22.7% |
| phase2_sft_ab_full | `Qwen/Qwen3.5-0.8B` | full | 1e-05 | 21,729,846 | 714 | 57 | 6,327 | 17.4 | 1.0924 → 0.4000 | 0.0% → 20.9% | 0.0% → 18.8% |

## Validation loss during training

| Step | phase2_sft_ab_lora | phase2_sft_ab_full |
|---|---|---|
| 0 | 1.0924 | 1.0924 |
| 50 | 0.5470 | 0.5673 |
| 100 | 0.5064 | 0.5147 |
| 150 | 0.4786 | 0.4898 |
| 200 | 0.4572 | 0.4671 |
| 250 | 0.4445 | 0.4466 |
| 300 | 0.4445 | 0.4412 |
| 350 | 0.4408 | 0.4258 |
| 400 | 0.4363 | 0.4322 |
| 450 | 0.4356 | 0.4292 |
| 500 | 0.4237 | 0.4166 |
| 550 | 0.4220 | 0.4131 |
| 600 | 0.4215 | 0.4112 |
| 650 | 0.4152 | 0.4063 |
| 700 | 0.4143 | 0.4022 |
| 714 | 0.4113 | 0.4000 |
