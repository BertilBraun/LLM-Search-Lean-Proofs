# Reasoning SFT data `teacher_9b`

Built 2026-10-13T18:50:51+00:00 (git d9a5e1debb) from runs phase5_teacher_9b: 3,072 usable of 3,072 states, 1,194 with selected examples. Per state at most 2 successful samples with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones; reasoning over 256 tokens only through a sufficient compression (shortening `9b`), states without a thinking success through rationalized steps. Reasoning examples: the thinking prompt, completion = reasoning, `</think>`, block, end of turn (loss on all of it). Replay: 1 non-thinking examples of SFT data `4b` per reasoning example. 3% of the proofs are held out (36 states); validation lists the replay examples first, so the trainer's greedy-generation check measures the non-thinking mode.

| part | examples | tokens | prompt mean | completion mean | completion p90 | completion max |
|---|---|---|---|---|---|---|
| train reasoning | 2134 | 731221 | 210 | 132 | 239 | 461 |
| train replay (no thinking) | 2134 | 454980 | 186 | 27 | 69 | 237 |
| validation replay (first) | 500 | 106932 | 185 | 29 | 73 | 255 |
| validation reasoning | 67 | 21232 | 204 | 113 | 202 | 261 |

| source | train reasoning examples |
|---|---|
| goedel_sft_v2 | 1395 |
| stp_lean_workbook | 739 |

| reasoning origin | train reasoning examples |
|---|---|
| sampled | 1017 |
| compressed | 1117 |
