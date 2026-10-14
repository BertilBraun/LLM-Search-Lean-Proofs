# Search comparison

244 miniF2F-valid problems shared by every run. n is the policy's samples per expansion, λ A*'s value weight, w_p its policy-prior weight, D the dead-end readout; costs are means per theorem. Value prompt tokens are the value model's prefill-only requests; policy generations are expansions × n.

| Run | Priority | n | λ | Depth weight | w_p | D | Solved | Expansions | Generated tokens | Generated tokens per solve | Value prompt tokens | Wall s | Lean s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_search_bootstrap_thinking | a_star | 8 | 1 | 0.25 | 0 | 16 | 152/244 (62.3%) | 12.8 | 31,184 | 50,059 | 6,536 | 252 | 49 |
| phase5_search_bootstrap_nothinking_n16 | a_star | 16 | 1 | 0.25 | 0 | 16 | 159/244 (65.2%) | 41.6 | 12,363 | 18,973 | 35,371 | 334 | 214 |
| phase5_search_student_4b_thinking | a_star | 8 | 1 | 0.25 | 0 | 16 | 147/244 (60.2%) | 8.4 | 15,321 | 25,430 | 5,986 | 328 | 34 |
| phase5_search_student_4b_nothinking_n16 | a_star | 16 | 1 | 0.25 | 0 | 16 | 156/244 (63.9%) | 22.0 | 7,792 | 12,188 | 18,700 | 363 | 147 |
| phase5_search_student_4b_light_thinking | a_star | 8 | 1 | 0.25 | 0 | 16 | 150/244 (61.5%) | 9.6 | 32,686 | 53,169 | 8,115 | 680 | 40 |
| phase5_search_student_4b_light_nothinking_n16 | a_star | 16 | 1 | 0.25 | 0 | 16 | 162/244 (66.4%) | 66.9 | 28,010 | 42,188 | 68,257 | 1503 | 1028 |

## By category

| Run | mathd_algebra (70) | mathd_numbertheory (60) | amc12 (45) | aime (15) | imo (20) | algebra (18) | numbertheory (8) | induction (8) |
|---|---|---|---|---|---|---|---|---|
| phase5_search_bootstrap_thinking | 56 | 47 | 19 | 2 | 2 | 15 | 4 | 7 |
| phase5_search_bootstrap_nothinking_n16 | 57 | 48 | 21 | 3 | 2 | 17 | 4 | 7 |
| phase5_search_student_4b_thinking | 52 | 48 | 19 | 2 | 2 | 15 | 3 | 6 |
| phase5_search_student_4b_nothinking_n16 | 56 | 49 | 21 | 2 | 2 | 15 | 4 | 7 |
| phase5_search_student_4b_light_thinking | 53 | 48 | 21 | 2 | 3 | 13 | 4 | 6 |
| phase5_search_student_4b_light_nothinking_n16 | 60 | 49 | 22 | 2 | 2 | 16 | 4 | 7 |

## Anytime curves (solved theorems at budget, per theorem)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 | 512 | 647 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_search_bootstrap_thinking | 80 | 112 | 133 | 139 | 148 | 152 | 152 | 152 | 152 | 152 | 152 |
| phase5_search_bootstrap_nothinking_n16 | 86 | 119 | 138 | 145 | 149 | 151 | 155 | 157 | 159 | 159 | 159 |
| phase5_search_student_4b_thinking | 101 | 123 | 132 | 140 | 145 | 147 | 147 | 147 | 147 | 147 | 147 |
| phase5_search_student_4b_nothinking_n16 | 82 | 114 | 132 | 142 | 148 | 152 | 155 | 156 | 156 | 156 | 156 |
| phase5_search_student_4b_light_thinking | 105 | 124 | 129 | 139 | 145 | 149 | 150 | 150 | 150 | 150 | 150 |
| phase5_search_student_4b_light_nothinking_n16 | 81 | 116 | 132 | 139 | 150 | 154 | 156 | 159 | 161 | 162 | 162 |

| policy_generations ≤ | 16 | 32 | 64 | 128 | 256 | 512 | 1024 |
|---|---|---|---|---|---|---|---|
| phase5_search_bootstrap_thinking | 112 | 133 | 139 | 148 | 152 | 152 | 152 |
| phase5_search_bootstrap_nothinking_n16 | 86 | 119 | 138 | 145 | 149 | 151 | 155 |
| phase5_search_student_4b_thinking | 123 | 132 | 140 | 145 | 147 | 147 | 147 |
| phase5_search_student_4b_nothinking_n16 | 82 | 114 | 132 | 142 | 148 | 152 | 155 |
| phase5_search_student_4b_light_thinking | 124 | 129 | 139 | 145 | 149 | 150 | 150 |
| phase5_search_student_4b_light_nothinking_n16 | 81 | 116 | 132 | 139 | 150 | 154 | 156 |

| generated_tokens ≤ | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 100258 |
|---|---|---|---|---|---|---|---|---|---|
| phase5_search_bootstrap_thinking | 0 | 7 | 58 | 109 | 133 | 140 | 151 | 152 | 152 |
| phase5_search_bootstrap_nothinking_n16 | 59 | 124 | 137 | 147 | 155 | 158 | 159 | 159 | 159 |
| phase5_search_student_4b_thinking | 0 | 33 | 96 | 128 | 136 | 141 | 147 | 147 | 147 |
| phase5_search_student_4b_nothinking_n16 | 83 | 120 | 136 | 146 | 155 | 156 | 156 | 156 | 156 |
| phase5_search_student_4b_light_thinking | 0 | 4 | 50 | 106 | 127 | 134 | 145 | 150 | 150 |
| phase5_search_student_4b_light_nothinking_n16 | 76 | 117 | 132 | 146 | 153 | 156 | 158 | 162 | 162 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 | 7688.19 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_search_bootstrap_thinking | 20 | 26 | 53 | 56 | 64 | 85 | 115 | 134 | 138 | 146 | 152 | 152 | 152 | 152 | 152 |
| phase5_search_bootstrap_nothinking_n16 | 21 | 38 | 58 | 75 | 107 | 119 | 138 | 146 | 148 | 151 | 156 | 159 | 159 | 159 | 159 |
| phase5_search_student_4b_thinking | 20 | 26 | 51 | 56 | 61 | 65 | 107 | 124 | 131 | 138 | 141 | 147 | 147 | 147 | 147 |
| phase5_search_student_4b_nothinking_n16 | 22 | 37 | 55 | 62 | 85 | 105 | 128 | 137 | 144 | 150 | 155 | 156 | 156 | 156 | 156 |
| phase5_search_student_4b_light_thinking | 20 | 26 | 53 | 56 | 58 | 59 | 73 | 114 | 120 | 128 | 136 | 145 | 150 | 150 | 150 |
| phase5_search_student_4b_light_nothinking_n16 | 26 | 39 | 55 | 60 | 83 | 98 | 122 | 137 | 141 | 148 | 156 | 156 | 158 | 160 | 162 |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 | 7252.31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_search_bootstrap_thinking | 65 | 78 | 116 | 133 | 141 | 146 | 150 | 151 | 151 | 152 | 152 | 152 | 152 | 152 | 152 |
| phase5_search_bootstrap_nothinking_n16 | 62 | 94 | 116 | 129 | 137 | 143 | 145 | 148 | 151 | 155 | 158 | 159 | 159 | 159 | 159 |
| phase5_search_student_4b_thinking | 66 | 75 | 118 | 130 | 138 | 141 | 146 | 147 | 147 | 147 | 147 | 147 | 147 | 147 | 147 |
| phase5_search_student_4b_nothinking_n16 | 63 | 83 | 119 | 132 | 139 | 140 | 147 | 151 | 155 | 156 | 156 | 156 | 156 | 156 | 156 |
| phase5_search_student_4b_light_thinking | 67 | 80 | 119 | 128 | 140 | 142 | 148 | 149 | 150 | 150 | 150 | 150 | 150 | 150 | 150 |
| phase5_search_student_4b_light_nothinking_n16 | 62 | 88 | 117 | 134 | 141 | 142 | 151 | 155 | 156 | 157 | 157 | 158 | 159 | 161 | 162 |

## Newly solved and lost against the reference runs

**phase5_search_bootstrap_thinking vs phase5_search_bootstrap_nothinking_n16**: 2 newly solved, 9 lost.

- newly solved: `mathd_algebra_323`, `mathd_algebra_393`
- lost: `aime_1991_p1`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `amc12a_2016_p3`, `amc12b_2003_p6`, `mathd_algebra_405`, `mathd_algebra_422`, `mathd_algebra_493`, `mathd_numbertheory_35`

**phase5_search_bootstrap_thinking vs phase5_search_student_4b_nothinking_n16**: 4 newly solved, 8 lost.

- newly solved: `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `mathd_algebra_151`, `mathd_algebra_267`, `mathd_algebra_323`
- lost: `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `amc12a_2016_p3`, `amc12b_2003_p17`, `mathd_algebra_131`, `mathd_algebra_433`, `mathd_algebra_493`, `mathd_numbertheory_32`, `mathd_numbertheory_35`

**phase5_search_student_4b_thinking vs phase5_search_bootstrap_nothinking_n16**: 3 newly solved, 15 lost.

- newly solved: `mathd_algebra_131`, `mathd_algebra_393`, `mathd_numbertheory_32`
- lost: `aime_1991_p1`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `amc12a_2016_p3`, `amc12b_2003_p6`, `induction_seq_mul2pnp1`, `mathd_algebra_13`, `mathd_algebra_151`, `mathd_algebra_405`, `mathd_algebra_422`, `mathd_algebra_536`, `mathd_algebra_77`, `mathd_algebra_89`, `mathd_numbertheory_780`, `numbertheory_nckeqnm1ckpnm1ckm1`

**phase5_search_student_4b_thinking vs phase5_search_student_4b_nothinking_n16**: 3 newly solved, 12 lost.

- newly solved: `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `mathd_algebra_267`
- lost: `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `amc12a_2016_p3`, `amc12b_2003_p17`, `induction_seq_mul2pnp1`, `mathd_algebra_13`, `mathd_algebra_433`, `mathd_algebra_536`, `mathd_algebra_77`, `mathd_algebra_89`, `mathd_numbertheory_780`, `numbertheory_nckeqnm1ckpnm1ckm1`

**phase5_search_student_4b_light_thinking vs phase5_search_bootstrap_nothinking_n16**: 5 newly solved, 14 lost.

- newly solved: `amc12b_2003_p17`, `imo_1984_p2`, `mathd_algebra_131`, `mathd_algebra_323`, `mathd_algebra_393`
- lost: `aime_1991_p1`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12b_2003_p6`, `induction_seq_mul2pnp1`, `mathd_algebra_151`, `mathd_algebra_405`, `mathd_algebra_422`, `mathd_algebra_480`, `mathd_algebra_59`, `mathd_algebra_73`, `mathd_algebra_89`

**phase5_search_student_4b_light_thinking vs phase5_search_student_4b_nothinking_n16**: 3 newly solved, 9 lost.

- newly solved: `imo_1984_p2`, `mathd_algebra_267`, `mathd_algebra_323`
- lost: `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `induction_seq_mul2pnp1`, `mathd_algebra_433`, `mathd_algebra_480`, `mathd_algebra_59`, `mathd_algebra_73`, `mathd_algebra_89`, `mathd_numbertheory_32`

**phase5_search_student_4b_light_nothinking_n16 vs phase5_search_bootstrap_nothinking_n16**: 7 newly solved, 4 lost.

- newly solved: `amc12b_2003_p17`, `imo_1984_p2`, `mathd_algebra_131`, `mathd_algebra_393`, `mathd_algebra_433`, `mathd_algebra_69`, `mathd_numbertheory_32`
- lost: `aime_1991_p1`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `imo_1961_p1`, `mathd_algebra_422`

**phase5_search_student_4b_light_nothinking_n16 vs phase5_search_student_4b_nothinking_n16**: 7 newly solved, 1 lost.

- newly solved: `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12b_2003_p6`, `imo_1984_p2`, `mathd_algebra_151`, `mathd_algebra_267`, `mathd_algebra_405`, `mathd_algebra_69`
- lost: `imo_1961_p1`

## Value calibration on the search trees

Each node's h (as scored when it was enqueued) against its label from the tree labeler: exact remaining steps for nodes that reach the proof (fewest edges), dead for fully expanded nodes without a proof, at least n otherwise (open nodes: at least 1). Dead AUC: h separating dead from exact nodes.

### phase5_search_bootstrap_thinking

5,677 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.609; dead AUC 0.519; mean root h 2.73 (solved) vs 4.47 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 152 | 1.70 | 1.20 | 1.53 | 2.45 |
| exact 2 | 72 | 2.69 | 1.48 | 2.41 | 4.01 |
| exact 3 | 40 | 3.50 | 1.99 | 2.87 | 5.98 |
| exact 4 | 23 | 2.90 | 1.57 | 2.96 | 4.08 |
| exact 5 | 11 | 2.85 | 1.77 | 1.93 | 4.95 |
| exact 6 | 9 | 3.21 | 1.96 | 2.27 | 8.09 |
| exact 7 | 5 | 4.76 | 1.99 | 4.37 | 9.63 |
| exact 8+ | 4 | 5.59 | 2.25 | 7.50 | 8.54 |
| dead | 770 | 2.38 | 1.40 | 2.04 | 3.72 |
| at least 2+ | 2033 | 2.54 | 1.56 | 2.29 | 3.66 |
| at least 1 (open) | 2558 | 3.10 | 1.75 | 2.74 | 4.87 |

### phase5_search_bootstrap_nothinking_n16

30,013 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.296; dead AUC 0.496; mean root h 2.82 (solved) vs 4.43 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 159 | 1.71 | 1.20 | 1.46 | 2.51 |
| exact 2 | 73 | 2.83 | 1.54 | 2.39 | 4.92 |
| exact 3 | 43 | 3.11 | 1.42 | 2.43 | 6.18 |
| exact 4 | 23 | 2.75 | 1.84 | 2.27 | 5.14 |
| exact 5 | 52 | 1.63 | 1.25 | 1.36 | 2.37 |
| exact 6 | 14 | 2.69 | 1.70 | 2.40 | 4.52 |
| exact 7 | 9 | 3.34 | 1.74 | 2.97 | 7.94 |
| exact 8+ | 9 | 4.65 | 1.99 | 3.97 | 10.97 |
| dead | 1239 | 2.05 | 1.31 | 1.81 | 3.16 |
| at least 2+ | 8459 | 2.06 | 1.46 | 1.95 | 2.68 |
| at least 1 (open) | 19933 | 2.50 | 1.66 | 2.29 | 3.46 |

### phase5_search_student_4b_thinking

4,213 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.332; dead AUC 0.499; mean root h 2.77 (solved) vs 4.31 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 147 | 2.06 | 1.22 | 1.77 | 2.95 |
| exact 2 | 52 | 2.68 | 1.52 | 2.24 | 4.02 |
| exact 3 | 23 | 2.96 | 1.43 | 2.38 | 5.12 |
| exact 4 | 15 | 2.68 | 1.48 | 2.49 | 4.52 |
| exact 5 | 8 | 4.14 | 1.41 | 3.71 | 9.63 |
| exact 6 | 5 | 3.35 | 1.61 | 2.51 | 7.50 |
| exact 7 | 3 | 3.73 | 1.55 | 3.54 | 6.10 |
| exact 8+ | 1 | 2.87 | 2.87 | 2.87 | 2.87 |
| dead | 419 | 2.26 | 1.37 | 1.95 | 3.61 |
| at least 2+ | 1322 | 2.29 | 1.38 | 2.00 | 3.34 |
| at least 1 (open) | 2218 | 2.76 | 1.46 | 2.40 | 4.48 |

### phase5_search_student_4b_nothinking_n16

17,685 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.476; dead AUC 0.423; mean root h 2.79 (solved) vs 4.43 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 156 | 1.70 | 1.20 | 1.47 | 2.45 |
| exact 2 | 77 | 2.52 | 1.37 | 2.15 | 3.75 |
| exact 3 | 48 | 2.82 | 1.41 | 2.46 | 5.06 |
| exact 4 | 30 | 2.93 | 1.57 | 2.51 | 5.60 |
| exact 5 | 16 | 3.33 | 1.32 | 3.17 | 5.22 |
| exact 6 | 8 | 3.74 | 1.23 | 3.69 | 7.50 |
| exact 7 | 5 | 2.26 | 1.23 | 2.27 | 3.88 |
| exact 8+ | 5 | 3.38 | 1.30 | 1.81 | 9.63 |
| dead | 388 | 1.85 | 1.26 | 1.62 | 2.70 |
| at least 2+ | 4570 | 1.96 | 1.34 | 1.82 | 2.65 |
| at least 1 (open) | 12382 | 2.44 | 1.48 | 2.13 | 3.66 |

### phase5_search_student_4b_light_thinking

5,003 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.388; dead AUC 0.506; mean root h 2.79 (solved) vs 4.34 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 150 | 2.08 | 1.22 | 1.70 | 3.23 |
| exact 2 | 45 | 2.72 | 1.44 | 2.19 | 5.60 |
| exact 3 | 27 | 2.65 | 1.35 | 2.14 | 3.72 |
| exact 4 | 21 | 3.31 | 1.72 | 3.12 | 5.03 |
| exact 5 | 11 | 2.72 | 1.97 | 2.89 | 3.34 |
| exact 6 | 6 | 3.81 | 1.64 | 3.18 | 9.63 |
| exact 7 | 4 | 5.00 | 2.67 | 5.11 | 8.72 |
| exact 8+ | 2 | 4.87 | 3.81 | 5.94 | 5.94 |
| dead | 447 | 2.33 | 1.38 | 2.04 | 3.40 |
| at least 2+ | 1637 | 2.19 | 1.36 | 1.99 | 3.13 |
| at least 1 (open) | 2653 | 2.68 | 1.45 | 2.37 | 4.27 |

### phase5_search_student_4b_light_nothinking_n16

60,707 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.467; dead AUC 0.507; mean root h 2.81 (solved) vs 4.52 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 162 | 1.67 | 1.22 | 1.46 | 2.44 |
| exact 2 | 81 | 2.49 | 1.56 | 2.15 | 3.48 |
| exact 3 | 48 | 2.71 | 1.30 | 2.31 | 4.72 |
| exact 4 | 42 | 2.66 | 1.42 | 2.30 | 4.02 |
| exact 5 | 36 | 2.59 | 1.48 | 1.93 | 4.95 |
| exact 6 | 18 | 3.26 | 1.56 | 3.12 | 5.98 |
| exact 7 | 6 | 4.04 | 1.67 | 3.68 | 8.72 |
| exact 8+ | 12 | 2.91 | 1.63 | 1.82 | 3.82 |
| dead | 818 | 2.24 | 1.25 | 2.01 | 3.64 |
| at least 2+ | 15069 | 1.80 | 1.33 | 1.67 | 2.38 |
| at least 1 (open) | 44415 | 2.15 | 1.41 | 1.91 | 3.13 |
