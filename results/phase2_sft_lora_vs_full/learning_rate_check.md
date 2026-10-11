# SFT runs

Data: `partial4`. Arrows go from the evaluation before training to the final one. Validation loss is the mean completion-token loss on held-out steps; teacher-forced exact match counts steps whose every target token is the argmax; generation exact match compares greedy generations with the normalized target. Per-run details under `runs/`.

| Run | Model | Method | Learning rate | Tokens | Steps | Minutes | Tokens/s | Peak GiB | Validation loss | Teacher-forced exact match | Generation exact match |
|---|---|---|---|---|---|---|---|---|---|---|---|
| phase2_sft_lr_lora_1e-4 | `Qwen/Qwen3.5-0.8B` | LoRA r64 | 0.0001 | 4,145,054 | 137 | 11 | 6,292 | 8.3 | 1.0638 → 0.3235 | 0.0% → 15.6% | 0.0% → 12.5% |
| phase2_sft_lr_lora_2e-4 | `Qwen/Qwen3.5-0.8B` | LoRA r64 | 0.0002 | 4,145,054 | 137 | 14 | 5,097 | 8.3 | 1.0638 → 0.3121 | 0.0% → 16.9% | 0.0% → 17.2% |
| phase2_sft_lr_lora_5e-4 | `Qwen/Qwen3.5-0.8B` | LoRA r64 | 0.0005 | 4,145,054 | 137 | 11 | 6,290 | 8.3 | 1.0638 → 0.3131 | 0.0% → 17.2% | 0.0% → 15.6% |
| phase2_sft_lr_full_5e-6 | `Qwen/Qwen3.5-0.8B` | full | 5e-06 | 4,145,054 | 137 | 11 | 6,541 | 17.4 | 1.0634 → 0.3115 | 0.0% → 16.4% | 0.0% → 18.8% |
| phase2_sft_lr_full_1e-5 | `Qwen/Qwen3.5-0.8B` | full | 1e-05 | 4,145,054 | 137 | 11 | 6,576 | 17.4 | 1.0634 → 0.3099 | 0.0% → 16.7% | 0.0% → 15.6% |
| phase2_sft_lr_full_2e-5 | `Qwen/Qwen3.5-0.8B` | full | 2e-05 | 4,145,054 | 137 | 11 | 6,572 | 17.4 | 1.0634 → 0.3151 | 0.0% → 16.7% | 0.0% → 14.1% |
| phase2_sft_lr_full_5e-5 | `Qwen/Qwen3.5-0.8B` | full | 5e-05 | 4,145,054 | 137 | 11 | 6,543 | 17.4 | 1.0634 → 0.3445 | 0.0% → 16.4% | 0.0% → 15.6% |

## Validation loss during training

| Step | phase2_sft_lr_lora_1e-4 | phase2_sft_lr_lora_2e-4 | phase2_sft_lr_lora_5e-4 | phase2_sft_lr_full_5e-6 | phase2_sft_lr_full_1e-5 | phase2_sft_lr_full_2e-5 | phase2_sft_lr_full_5e-5 |
|---|---|---|---|---|---|---|---|
| 0 | 1.0638 | 1.0638 | 1.0638 | 1.0634 | 1.0634 | 1.0634 | 1.0634 |
| 40 | 0.3877 | 0.3940 | 0.4984 | 0.3996 | 0.4449 | 0.5377 | 0.5970 |
| 80 | 0.3430 | 0.3412 | 0.3707 | 0.3450 | 0.3508 | 0.3724 | 0.4222 |
| 120 | 0.3252 | 0.3149 | 0.3210 | 0.3172 | 0.3165 | 0.3257 | 0.3605 |
| 137 | 0.3235 | 0.3121 | 0.3131 | 0.3115 | 0.3099 | 0.3151 | 0.3445 |
