# Reasoning SFT data `visible_student`

Built 2026-10-15T00:58:50+00:00 (git dece5b565c) from runs phase5_visible_teacher_9b, phase5_visible_self_4b: 16,378 usable of 16,384 states, 6,771 with selected examples. Per state at most 2 successful samples with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones; reasoning over 350 tokens only through a sufficient compression (shortening `9b_light`), states without a thinking success through rationalized steps. Reasoning examples: the thinking prompt, completion = reasoning, `</think>`, block, end of turn (loss on all of it). Replay: 0.2143 non-thinking examples of SFT data `4b` per reasoning example. 3% of the proofs are held out (204 states); validation lists the replay examples first, so the trainer's greedy-generation check measures the non-thinking mode.

| part | examples | tokens | prompt mean | completion mean | completion p90 | completion max |
|---|---|---|---|---|---|---|
| train reasoning | 11727 | 3707195 | 214 | 102 | 221 | 932 |
| train replay (no thinking) | 2513 | 524855 | 183 | 25 | 59 | 251 |
| validation replay (first) | 500 | 105795 | 183 | 28 | 72 | 255 |
| validation reasoning | 365 | 113663 | 207 | 104 | 237 | 573 |

| source | train reasoning examples |
|---|---|
| goedel_sft_v2 | 7349 |
| stp_lean_workbook | 4378 |

| reasoning origin | train reasoning examples |
|---|---|
| sampled | 11584 |
| compressed | 143 |
