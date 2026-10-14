# Search comparison

244 miniF2F-valid problems shared by every run. n is the policy's samples per expansion, λ A*'s value weight, w_p its policy-prior weight, D the dead-end readout; costs are means per theorem. Value prompt tokens are the value model's prefill-only requests; policy generations are expansions × n.

| Run | Priority | n | λ | Depth weight | w_p | D | Solved | Expansions | Generated tokens | Generated tokens per solve | Value prompt tokens | Wall s | Lean s |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_expansions_student_4b_light_thinking | a_star | 16 | 1 | 0.25 | 0 | 16 | 160/244 (65.6%) | 16.3 | 113,546 | 173,158 | 20,545 | 2480 | 125 |
| phase5_expansions_student_4b_light_nothinking | a_star | 16 | 1 | 0.25 | 0 | 16 | 154/244 (63.1%) | 24.8 | 12,201 | 19,332 | 25,897 | 509 | 234 |
| phase5_search_student_4b_light_nothinking_n16 | a_star | 16 | 1 | 0.25 | 0 | 16 | 162/244 (66.4%) | 66.9 | 28,010 | 42,188 | 68,257 | 1503 | 1028 |

## By category

| Run | mathd_algebra (70) | mathd_numbertheory (60) | amc12 (45) | aime (15) | imo (20) | algebra (18) | numbertheory (8) | induction (8) |
|---|---|---|---|---|---|---|---|---|
| phase5_expansions_student_4b_light_thinking | 60 | 49 | 22 | 2 | 2 | 15 | 3 | 7 |
| phase5_expansions_student_4b_light_nothinking | 55 | 49 | 20 | 3 | 2 | 14 | 4 | 7 |
| phase5_search_student_4b_light_nothinking_n16 | 60 | 49 | 22 | 2 | 2 | 16 | 4 | 7 |

## Anytime curves (solved theorems at budget, per theorem)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 | 512 | 647 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_expansions_student_4b_light_thinking | 120 | 130 | 143 | 145 | 150 | 157 | 160 | 160 | 160 | 160 | 160 |
| phase5_expansions_student_4b_light_nothinking | 86 | 114 | 129 | 139 | 147 | 152 | 154 | 154 | 154 | 154 | 154 |
| phase5_search_student_4b_light_nothinking_n16 | 81 | 116 | 132 | 139 | 150 | 154 | 156 | 159 | 161 | 162 | 162 |

| policy_generations ≤ | 16 | 32 | 64 | 128 | 256 | 512 | 1024 |
|---|---|---|---|---|---|---|---|
| phase5_expansions_student_4b_light_thinking | 120 | 130 | 143 | 145 | 150 | 157 | 160 |
| phase5_expansions_student_4b_light_nothinking | 86 | 114 | 129 | 139 | 147 | 152 | 154 |
| phase5_search_student_4b_light_nothinking_n16 | 81 | 116 | 132 | 139 | 150 | 154 | 156 |

| generated_tokens ≤ | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 200000 | 444993 |
|---|---|---|---|---|---|---|---|---|---|---|
| phase5_expansions_student_4b_light_thinking | 0 | 0 | 5 | 79 | 120 | 133 | 145 | 150 | 157 | 160 |
| phase5_expansions_student_4b_light_nothinking | 73 | 113 | 132 | 143 | 150 | 153 | 154 | 154 | 154 | 154 |
| phase5_search_student_4b_light_nothinking_n16 | 76 | 117 | 132 | 146 | 153 | 156 | 158 | 162 | 162 | 162 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 | 7688.19 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_expansions_student_4b_light_thinking | 20 | 26 | 53 | 56 | 56 | 58 | 66 | 74 | 114 | 127 | 139 | 145 | 146 | 153 | 160 |
| phase5_expansions_student_4b_light_nothinking | 22 | 37 | 55 | 61 | 81 | 105 | 120 | 131 | 136 | 145 | 151 | 154 | 154 | 154 | 154 |
| phase5_search_student_4b_light_nothinking_n16 | 26 | 39 | 55 | 60 | 83 | 98 | 122 | 137 | 141 | 148 | 156 | 156 | 158 | 160 | 162 |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 | 7252.31 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase5_expansions_student_4b_light_thinking | 70 | 82 | 120 | 134 | 144 | 148 | 153 | 156 | 156 | 158 | 160 | 160 | 160 | 160 | 160 |
| phase5_expansions_student_4b_light_nothinking | 63 | 92 | 115 | 128 | 136 | 139 | 144 | 148 | 150 | 152 | 153 | 154 | 154 | 154 | 154 |
| phase5_search_student_4b_light_nothinking_n16 | 62 | 88 | 117 | 134 | 141 | 142 | 151 | 155 | 156 | 157 | 157 | 158 | 159 | 161 | 162 |

## Newly solved and lost against the reference runs

**phase5_expansions_student_4b_light_thinking vs phase5_expansions_student_4b_light_nothinking**: 12 newly solved, 6 lost.

- newly solved: `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `amc12a_2016_p3`, `amc12b_2002_p6`, `imo_1964_p1_2`, `mathd_algebra_149`, `mathd_algebra_185`, `mathd_algebra_267`, `mathd_algebra_323`, `mathd_algebra_509`, `mathd_algebra_69`, `mathd_algebra_89`
- lost: `aime_1991_p1`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `imo_1984_p2`, `mathd_algebra_433`, `mathd_algebra_536`, `numbertheory_nckeqnm1ckpnm1ckm1`

**phase5_expansions_student_4b_light_thinking vs phase5_search_student_4b_light_nothinking_n16**: 5 newly solved, 7 lost.

- newly solved: `imo_1961_p1`, `mathd_algebra_149`, `mathd_algebra_185`, `mathd_algebra_323`, `mathd_algebra_509`
- lost: `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `imo_1984_p2`, `mathd_algebra_151`, `mathd_algebra_405`, `mathd_algebra_433`, `mathd_algebra_536`, `numbertheory_nckeqnm1ckpnm1ckm1`

## Value calibration on the search trees

Each node's h (as scored when it was enqueued) against its label from the tree labeler: exact remaining steps for nodes that reach the proof (fewest edges), dead for fully expanded nodes without a proof, at least n otherwise (open nodes: at least 1). Dead AUC: h separating dead from exact nodes.

### phase5_expansions_student_4b_light_thinking

11,486 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.219; dead AUC 0.386; mean root h 2.90 (solved) vs 4.31 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 160 | 2.29 | 1.23 | 1.90 | 3.74 |
| exact 2 | 41 | 2.75 | 1.46 | 2.05 | 5.60 |
| exact 3 | 29 | 2.52 | 1.36 | 2.12 | 5.11 |
| exact 4 | 16 | 2.56 | 1.52 | 2.19 | 4.52 |
| exact 5 | 13 | 2.35 | 1.55 | 2.13 | 3.08 |
| exact 6 | 17 | 2.32 | 1.51 | 2.22 | 3.16 |
| exact 7 | 7 | 3.49 | 1.88 | 2.87 | 6.77 |
| exact 8+ | 6 | 4.64 | 2.53 | 3.19 | 8.72 |
| dead | 369 | 1.91 | 1.32 | 1.71 | 2.60 |
| at least 2+ | 3241 | 1.94 | 1.35 | 1.77 | 2.67 |
| at least 1 (open) | 7587 | 2.36 | 1.40 | 2.10 | 3.48 |

### phase5_expansions_student_4b_light_nothinking

22,581 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.543; dead AUC 0.370; mean root h 2.78 (solved) vs 4.41 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 154 | 1.69 | 1.21 | 1.46 | 2.45 |
| exact 2 | 70 | 2.47 | 1.42 | 2.11 | 3.77 |
| exact 3 | 46 | 2.44 | 1.30 | 2.07 | 3.66 |
| exact 4 | 33 | 2.94 | 1.62 | 2.43 | 5.00 |
| exact 5 | 19 | 3.18 | 1.60 | 3.03 | 6.32 |
| exact 6 | 11 | 5.00 | 2.15 | 3.86 | 8.54 |
| exact 7 | 4 | 4.53 | 2.27 | 5.12 | 7.84 |
| exact 8+ | 1 | 10.97 | 10.97 | 10.97 | 10.97 |
| dead | 368 | 1.71 | 1.25 | 1.55 | 2.33 |
| at least 2+ | 5338 | 1.89 | 1.34 | 1.73 | 2.56 |
| at least 1 (open) | 16537 | 2.36 | 1.44 | 2.06 | 3.51 |

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
