# Value labels of search trees (statistics only)

miniF2F-valid trees exercise the tree labeler; they are never value training data. Every node with goals gets one label: **exact** remaining steps when it reaches the verified proof (fewest edges over child and duplicate edges), else **at least** 1 + the fewest edges to a frontier node (open, i.e. not fully expanded, or with an attempt lost to an infrastructure failure) when it reaches one, else **dead** (everything below it was expanded without a proof). Weights: exact 1, at least 1, dead 0.5. Proved states (no goals) get no label.

| Run | Solved trees | Labelled nodes | Exact | At least | Dead | Exact off the found path | Failed but censored | Trees with a dead node | Unsolved trees with a dead root | Distinct states |
|---|---|---|---|---|---|---|---|---|---|---|
| phase1_fewshot_search_qwen3.5-2b | 115/244 | 13,706 | 266 (1.9%) | 12,293 (89.7%) | 1,147 (8.4%) | 28 | 6 | 121 | 36 | 13,706 |
| phase1_fewshot_search_qwen3.5-2b-base | 117/244 | 14,771 | 254 (1.7%) | 13,611 (92.1%) | 906 (6.1%) | 7 | 13 | 115 | 12 | 14,771 |
| phase0_automation_baseline | 79/244 | 1,940 | 107 (5.5%) | 672 (34.6%) | 1,161 (59.8%) | 4 | 1 | 163 | 160 | 1,940 |

## Remaining steps (exact) and lower bounds (at least)

| Run | Label | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8+ |
|---|---|---|---|---|---|---|---|---|---|
| phase1_fewshot_search_qwen3.5-2b | exact | 115 | 42 | 27 | 15 | 11 | 10 | 7 | 39 |
| phase1_fewshot_search_qwen3.5-2b | at least | 7522 | 3297 | 1063 | 293 | 77 | 29 | 9 | 3 |
| phase1_fewshot_search_qwen3.5-2b-base | exact | 117 | 41 | 23 | 12 | 10 | 8 | 6 | 37 |
| phase1_fewshot_search_qwen3.5-2b-base | at least | 7953 | 3800 | 1209 | 379 | 144 | 55 | 32 | 39 |
| phase0_automation_baseline | exact | 79 | 22 | 6 | 0 | 0 | 0 | 0 | 0 |
| phase0_automation_baseline | at least | 157 | 109 | 93 | 72 | 51 | 40 | 28 | 122 |

## Depth of labelled nodes

| Run | Label | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase1_fewshot_search_qwen3.5-2b | exact | 115 | 40 | 22 | 15 | 14 | 12 | 8 | 7 | 7 | 7 | 8 | 5 | 3 | 1 | 1 | 1 | 0 |
| phase1_fewshot_search_qwen3.5-2b | at least | 93 | 461 | 576 | 537 | 495 | 599 | 582 | 614 | 632 | 666 | 673 | 631 | 702 | 784 | 936 | 1303 | 2009 |
| phase1_fewshot_search_qwen3.5-2b | dead | 36 | 66 | 72 | 92 | 81 | 96 | 89 | 75 | 76 | 72 | 58 | 76 | 75 | 61 | 69 | 53 | 0 |
| phase1_fewshot_search_qwen3.5-2b-base | exact | 117 | 42 | 24 | 13 | 8 | 7 | 6 | 6 | 5 | 8 | 4 | 4 | 4 | 2 | 2 | 2 | 0 |
| phase1_fewshot_search_qwen3.5-2b-base | at least | 115 | 539 | 569 | 562 | 574 | 569 | 681 | 738 | 737 | 743 | 813 | 818 | 871 | 1013 | 1106 | 1400 | 1763 |
| phase1_fewshot_search_qwen3.5-2b-base | dead | 12 | 39 | 34 | 31 | 47 | 61 | 76 | 68 | 69 | 54 | 61 | 61 | 69 | 68 | 89 | 67 | 0 |
| phase0_automation_baseline | exact | 79 | 24 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| phase0_automation_baseline | at least | 5 | 35 | 36 | 37 | 43 | 57 | 72 | 91 | 122 | 81 | 45 | 8 | 8 | 8 | 8 | 8 | 8 |
| phase0_automation_baseline | dead | 160 | 256 | 242 | 173 | 112 | 86 | 59 | 37 | 9 | 6 | 4 | 4 | 4 | 4 | 4 | 1 | 0 |

## Node statuses

| Run | Nodes | Without goals | expanded | failed | open | proved |
|---|---|---|---|---|---|---|
| phase1_fewshot_search_qwen3.5-2b | 13821 | 115 | 4809 | 1153 | 7506 | 353 |
| phase1_fewshot_search_qwen3.5-2b-base | 14888 | 117 | 5665 | 919 | 7940 | 364 |
| phase0_automation_baseline | 2019 | 79 | 519 | 1162 | 156 | 182 |
