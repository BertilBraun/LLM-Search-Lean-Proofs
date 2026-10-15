# Reasoning SFT run `phase5_sft_visible_student_v2`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-4B` + adapter `/workspace/checkpoints/phase2_sft_4b_gentle_v2/adapter` |
| Data | `reasoning/visible_student_v2`: 13,461 examples, 5,483,999 tokens |
| Optimization | learning rate 0.0001, warmup 0.03, cosine to 0.1, 2 epoch(s), 16,384 padded tokens x 2 micro-batches per GPU, 2 GPU(s) |
| Steps / tokens / time | 170 / 10,922,076 / 47.9 min |
| Tokens/s, peak memory | 3,797, 17.7 GiB |

Validation lists the non-thinking replay examples first: greedy-generation exact match runs on the first of them and tracks the non-thinking mode; the loss covers both kinds.

| Step | Validation loss | Teacher-forced exact match | Non-thinking greedy exact match |
|---|---|---|---|
| 0 | 0.4734 | 12.9% | 22.3% |
| 50 | 0.3801 | 11.2% | 17.6% |
| 100 | 0.3722 | 11.5% | 19.9% |
| 150 | 0.3692 | 12.6% | 21.5% |
| 170 | 0.3700 | 12.8% | 21.5% |

Started 2026-10-15T16:35:06+00:00, git 131b69ffd8; adapter `/workspace/checkpoints/phase5_sft_visible_student_v2/adapter`.
