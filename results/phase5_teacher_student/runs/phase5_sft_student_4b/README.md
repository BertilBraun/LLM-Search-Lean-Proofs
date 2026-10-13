# Reasoning SFT run `phase5_sft_student_4b`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-4B` + adapter `/workspace/checkpoints/phase2_sft_4b/adapter` |
| Data | `reasoning/teacher_9b`: 4,268 examples, 1,186,201 tokens |
| Optimization | learning rate 0.0001, warmup 0.03, cosine to 0.1, 2 epoch(s), 16,384 padded tokens x 2 micro-batches per GPU, 2 GPU(s) |
| Steps / tokens / time | 36 / 2,334,291 / 10.0 min |
| Tokens/s, peak memory | 3,891, 17.7 GiB |

Validation lists the non-thinking replay examples first: greedy-generation exact match runs on the first of them and tracks the non-thinking mode; the loss covers both kinds.

| Step | Validation loss | Teacher-forced exact match | Non-thinking greedy exact match |
|---|---|---|---|
| 0 | 0.4585 | 24.5% | 27.3% |
| 36 | 0.3286 | 21.9% | 26.2% |

Started 2026-10-13T19:19:05+00:00, git b669b059b1; adapter `/workspace/checkpoints/phase5_sft_student_4b/adapter`.
