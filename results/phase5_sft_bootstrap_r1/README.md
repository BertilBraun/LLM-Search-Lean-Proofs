# Reasoning SFT run `phase5_sft_bootstrap_r1`

| Setting | Value |
|---|---|
| Model | `Qwen/Qwen3.5-2B` + adapter `/workspace/checkpoints/phase2_sft_v2/adapter` |
| Data | `reasoning/bootstrap_r1`: 8,330 examples, 2,232,423 tokens |
| Optimization | learning rate 0.0001, warmup 0.03, cosine to 0.1, 2 epoch(s), 32,768 padded tokens x 1 micro-batches per GPU, 2 GPU(s) |
| Steps / tokens / time | 68 / 4,436,379 / 8.5 min |
| Tokens/s, peak memory | 8,705, 17.4 GiB |

Validation lists the non-thinking replay examples first: greedy-generation exact match runs on the first of them and tracks the non-thinking mode; the loss covers both kinds.

| Step | Validation loss | Teacher-forced exact match | Non-thinking greedy exact match |
|---|---|---|---|
| 0 | 0.3666 | 21.4% | 26.6% |
| 50 | 0.3323 | 20.9% | 26.2% |
| 68 | 0.3321 | 21.1% | 26.2% |

Started 2026-10-12T23:48:49+00:00, git 998d5d2fdd; adapter `/workspace/checkpoints/phase5_sft_bootstrap_r1/adapter`.
