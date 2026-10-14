# Reasoning SFT run `phase5_sft_student_4b_light`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-4B` + adapter `/workspace/checkpoints/phase2_sft_4b/adapter` |
| Data | `reasoning/teacher_9b_light`: 3,966 examples, 1,238,726 tokens |
| Optimization | learning rate 0.0001, warmup 0.03, cosine to 0.1, 2 epoch(s), 16,384 padded tokens x 2 micro-batches per GPU, 2 GPU(s) |
| Steps / tokens / time | 38 / 2,460,828 / 10.7 min |
| Tokens/s, peak memory | 3,849, 17.7 GiB |

Validation lists the non-thinking replay examples first: greedy-generation exact match runs on the first of them and tracks the non-thinking mode; the loss covers both kinds.

| Step | Validation loss | Teacher-forced exact match | Non-thinking greedy exact match |
|---|---|---|---|
| 0 | 0.3918 | 20.4% | 24.6% |
| 38 | 0.3100 | 17.2% | 18.8% |

Started 2026-10-14T00:26:20+00:00, git 62c1d7a90a; adapter `/workspace/checkpoints/phase5_sft_student_4b_light/adapter`.
