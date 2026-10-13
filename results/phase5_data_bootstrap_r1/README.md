# Reasoning SFT data `bootstrap_r1`

Built 2026-10-12T23:48:32+00:00 (git 998d5d2fdd) from runs phase5_bootstrap_r1: 7,998 usable of 8,000 states, 2,456 with selected examples. Per state at most 2 successful samples with at least 16 reasoning tokens, shortest reasoning first, distinct blocks before repeated ones; reasoning over 256 tokens only through a sufficient compression (shortening `2b`), states without a thinking success through rationalized steps. Reasoning examples: the thinking prompt, completion = reasoning, `</think>`, block, end of turn (loss on all of it). Replay: 1 non-thinking examples of SFT data `v2` per reasoning example. 3% of the proofs are held out (66 states); validation lists the replay examples first, so the trainer's greedy-generation check measures the non-thinking mode.

| part | examples | tokens | prompt mean | completion mean | completion p90 | completion max |
|---|---|---|---|---|---|---|
| train reasoning | 4165 | 1359060 | 211 | 116 | 221 | 983 |
| train replay (no thinking) | 4165 | 873363 | 182 | 27 | 69 | 255 |
| validation replay (first) | 500 | 106981 | 186 | 27 | 64 | 245 |
| validation reasoning | 107 | 37120 | 222 | 125 | 261 | 369 |

| source | train reasoning examples |
|---|---|
| goedel_sft_v2 | 3035 |
| stp_lean_workbook | 1130 |

| reasoning origin | train reasoning examples |
|---|---|
| sampled | 3074 |
| compressed | 1091 |
