# Reasoning SFT data `teacher_9b_light`

Built 2026-10-14T00:23:06+00:00 (git 62c1d7a90a) from runs phase5_teacher_9b: 3,072 usable of 3,072 states, 1,143 with selected examples. Per state at most 2 successful samples with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones; reasoning over 350 tokens only through a sufficient compression (shortening `9b_light`), states without a thinking success through rationalized steps. Reasoning examples: the thinking prompt, completion = reasoning, `</think>`, block, end of turn (loss on all of it). Replay: 1 non-thinking examples of SFT data `4b` per reasoning example. 3% of the proofs are held out (23 states); validation lists the replay examples first, so the trainer's greedy-generation check measures the non-thinking mode.

| part | examples | tokens | prompt mean | completion mean | completion p90 | completion max |
|---|---|---|---|---|---|---|
| train reasoning | 1983 | 827709 | 207 | 211 | 328 | 623 |
| train replay (no thinking) | 1983 | 411017 | 180 | 27 | 71 | 240 |
| validation replay (first) | 500 | 104013 | 180 | 28 | 77 | 255 |
| validation reasoning | 40 | 17261 | 214 | 218 | 345 | 444 |

| source | train reasoning examples |
|---|---|
| goedel_sft_v2 | 1306 |
| stp_lean_workbook | 677 |

| reasoning origin | train reasoning examples |
|---|---|
| sampled | 1327 |
| compressed | 656 |
