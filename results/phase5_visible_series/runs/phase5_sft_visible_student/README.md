# Reasoning SFT run `phase5_sft_visible_student`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-4B` + adapter `/workspace/checkpoints/phase2_sft_4b_gentle/adapter` |
| Data | `reasoning/visible_student`: 16,753 examples, 5,140,373 tokens |
| Optimization | learning rate 0.0001, warmup 0.03, cosine to 0.1, 2 epoch(s), 16,384 padded tokens x 2 micro-batches per GPU, 2 GPU(s) |
| Steps / tokens / time | 158 / 10,239,508 / 43.8 min |
| Tokens/s, peak memory | 3,893, 17.7 GiB |

Validation lists the non-thinking replay examples first: greedy-generation exact match runs on the first of them and tracks the non-thinking mode; the loss covers both kinds.

| Step | Validation loss | Teacher-forced exact match | Non-thinking greedy exact match |
|---|---|---|---|
| 0 | 0.4979 | 14.5% | 23.8% |
| 50 | 0.3783 | 14.5% | 21.5% |
| 100 | 0.3739 | 13.9% | 22.3% |
| 150 | 0.3710 | 13.9% | 21.9% |
| 158 | 0.3704 | 14.2% | 23.0% |

Started 2026-10-15T01:02:12+00:00, git dece5b565c; adapter `/workspace/checkpoints/phase5_sft_visible_student/adapter`.
