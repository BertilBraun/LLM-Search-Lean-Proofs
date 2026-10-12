# Offline recall of the ReProver retriever

`kaiyuy/leandojo-lean4-retriever-byt5-small`, premise embeddings in float16. R@k: mean fraction of a state's gold premises in the top k (ReProver's metric); Hit@k: states with at least one gold premise in the top k. States with at least one gold premise: novel_premises/val: 3,907, novel_premises/test: 4,141, competition/validation: 3,216.

| Mode | Split | States | Gold/state | R@1 | R@4 | R@8 | R@10 | R@16 | R@32 | R@64 | Hit@8 | Hit@32 | MRR |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| all | novel_premises/val | 3,907 | 2.25 | 0.199 | 0.426 | 0.544 | 0.582 | 0.649 | 0.743 | 0.821 | 0.721 | 0.861 | 0.476 |
| accessible | novel_premises/val | 3,907 | 2.25 | 0.232 | 0.469 | 0.592 | 0.628 | 0.700 | 0.798 | 0.874 | 0.758 | 0.897 | 0.524 |
| deployed | novel_premises/val | 3,871 | 2.24 | 0.199 | 0.420 | 0.540 | 0.575 | 0.645 | 0.740 | 0.817 | 0.717 | 0.858 | 0.472 |
| all | novel_premises/test | 4,141 | 2.35 | 0.199 | 0.430 | 0.549 | 0.583 | 0.657 | 0.752 | 0.828 | 0.736 | 0.879 | 0.485 |
| accessible | novel_premises/test | 4,141 | 2.35 | 0.225 | 0.473 | 0.599 | 0.637 | 0.713 | 0.811 | 0.877 | 0.778 | 0.910 | 0.530 |
| deployed | novel_premises/test | 4,104 | 2.34 | 0.200 | 0.429 | 0.546 | 0.580 | 0.655 | 0.747 | 0.823 | 0.734 | 0.874 | 0.483 |
| competition | traced/validation | 3,216 | 1.85 | 0.048 | 0.101 | 0.156 | 0.178 | 0.236 | 0.328 | 0.432 | 0.216 | 0.432 | 0.124 |
