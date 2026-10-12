# Search comparison

83 miniF2F-valid problems shared by every run. λ is A*'s value weight, D the dead-end readout; costs are means per theorem. Value prompt tokens are the value model's prefill-only requests.

| Run | Priority | λ | D | Solved | Expansions | Generated tokens | Generated tokens per solve | Value prompt tokens | Wall s | Lean s |
|---|---|---|---|---|---|---|---|---|---|---|
| phase2_sft_v1_search | cumulative_log_probability | – | – | 37/83 (44.6%) | 33.8 | 19,103 | 42,853 | 0 | 260 | 194 |
| phase3_astar_v0_sweep_l0.5 | a_star | 0.5 | 16 | 40/83 (48.2%) | 31.5 | 18,995 | 39,415 | 27,140 | 254 | 162 |
| phase3_astar_v0_sweep_l1 | a_star | 1 | 16 | 39/83 (47.0%) | 30.8 | 18,539 | 39,455 | 26,227 | 251 | 161 |
| phase3_astar_v0_sweep_l2 | a_star | 2 | 16 | 41/83 (49.4%) | 30.8 | 18,604 | 37,662 | 26,152 | 269 | 182 |
| phase3_astar_v0_sweep_l4 | a_star | 4 | 16 | 40/83 (48.2%) | 30.2 | 17,816 | 36,969 | 26,394 | 259 | 172 |

## By category

| Run | mathd_algebra (21) | mathd_numbertheory (11) | amc12 (19) | aime (8) | imo (10) | algebra (6) | numbertheory (4) | induction (4) |
|---|---|---|---|---|---|---|---|---|
| phase2_sft_v1_search | 13 | 7 | 4 | 2 | 1 | 6 | 1 | 3 |
| phase3_astar_v0_sweep_l0.5 | 16 | 7 | 5 | 2 | 1 | 5 | 1 | 3 |
| phase3_astar_v0_sweep_l1 | 13 | 7 | 5 | 2 | 3 | 5 | 1 | 3 |
| phase3_astar_v0_sweep_l2 | 16 | 7 | 5 | 2 | 1 | 6 | 1 | 3 |
| phase3_astar_v0_sweep_l4 | 14 | 7 | 6 | 2 | 2 | 5 | 1 | 3 |

## Anytime curves (solved theorems at budget, per theorem)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| phase2_sft_v1_search | 11 | 18 | 27 | 29 | 33 | 35 | 37 |
| phase3_astar_v0_sweep_l0.5 | 12 | 24 | 32 | 36 | 37 | 38 | 40 |
| phase3_astar_v0_sweep_l1 | 12 | 25 | 31 | 33 | 37 | 38 | 39 |
| phase3_astar_v0_sweep_l2 | 10 | 22 | 27 | 32 | 34 | 38 | 41 |
| phase3_astar_v0_sweep_l4 | 12 | 21 | 30 | 34 | 36 | 38 | 40 |

| generated_tokens ≤ | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 100748 |
|---|---|---|---|---|---|---|---|---|---|
| phase2_sft_v1_search | 18 | 24 | 29 | 32 | 35 | 36 | 37 | 37 | 37 |
| phase3_astar_v0_sweep_l0.5 | 17 | 30 | 33 | 35 | 37 | 39 | 40 | 40 | 40 |
| phase3_astar_v0_sweep_l1 | 19 | 27 | 33 | 35 | 36 | 38 | 39 | 39 | 39 |
| phase3_astar_v0_sweep_l2 | 18 | 26 | 31 | 32 | 36 | 40 | 41 | 41 | 41 |
| phase3_astar_v0_sweep_l4 | 18 | 28 | 30 | 34 | 36 | 36 | 40 | 40 | 40 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 614.929 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase2_sft_v1_search | 0 | 1 | 9 | 20 | 24 | 28 | 32 | 35 | 35 | 36 | 37 | 37 |
| phase3_astar_v0_sweep_l0.5 | 0 | 0 | 7 | 18 | 29 | 30 | 33 | 37 | 37 | 38 | 40 | 40 |
| phase3_astar_v0_sweep_l1 | 0 | 1 | 9 | 18 | 26 | 31 | 34 | 35 | 36 | 39 | 39 | 39 |
| phase3_astar_v0_sweep_l2 | 0 | 0 | 5 | 17 | 25 | 27 | 32 | 35 | 36 | 38 | 41 | 41 |
| phase3_astar_v0_sweep_l4 | 0 | 1 | 7 | 18 | 26 | 29 | 32 | 35 | 35 | 36 | 40 | 40 |

## Newly solved and lost against the reference runs

**phase3_astar_v0_sweep_l0.5 vs phase2_sft_v1_search**: 5 newly solved, 2 lost.

- newly solved: `amc12b_2003_p17`, `imo_1974_p5`, `mathd_algebra_131`, `mathd_algebra_405`, `mathd_algebra_89`
- lost: `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `imo_1984_p2`

**phase3_astar_v0_sweep_l1 vs phase2_sft_v1_search**: 4 newly solved, 2 lost.

- newly solved: `amc12b_2004_p3`, `imo_1964_p1_2`, `imo_1974_p5`, `mathd_algebra_405`
- lost: `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `mathd_algebra_451`

**phase3_astar_v0_sweep_l2 vs phase2_sft_v1_search**: 4 newly solved, 0 lost.

- newly solved: `amc12b_2003_p17`, `mathd_algebra_405`, `mathd_algebra_59`, `mathd_algebra_89`
- lost: none

**phase3_astar_v0_sweep_l4 vs phase2_sft_v1_search**: 5 newly solved, 2 lost.

- newly solved: `amc12b_2003_p17`, `amc12b_2004_p3`, `imo_1974_p5`, `mathd_algebra_131`, `mathd_algebra_89`
- lost: `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `mathd_algebra_451`

## Value calibration on the search trees

Each node's h (as scored when it was enqueued) against its label from the tree labeler: exact remaining steps for nodes that reach the proof (fewest edges), dead for fully expanded nodes without a proof, at least n otherwise (open nodes: at least 1). Dead AUC: h separating dead from exact nodes.

### phase3_astar_v0_sweep_l0.5

10,305 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.635; dead AUC 0.516; mean root h 3.07 (solved) vs 4.31 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 40 | 1.81 | 1.20 | 1.69 | 2.77 |
| exact 2 | 30 | 2.96 | 1.79 | 2.64 | 4.70 |
| exact 3 | 16 | 3.27 | 1.88 | 2.72 | 5.04 |
| exact 4 | 14 | 3.42 | 2.31 | 3.32 | 4.73 |
| exact 5 | 12 | 4.68 | 2.26 | 4.76 | 6.91 |
| exact 6 | 1 | 2.10 | 2.10 | 2.10 | 2.10 |
| dead | 86 | 2.73 | 1.57 | 2.84 | 3.98 |
| at least 2+ | 2407 | 3.02 | 1.77 | 2.73 | 4.73 |
| at least 1 (open) | 7699 | 3.29 | 1.81 | 2.93 | 5.26 |

### phase3_astar_v0_sweep_l1

9,799 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.637; dead AUC 0.410; mean root h 3.03 (solved) vs 4.30 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 39 | 1.80 | 1.20 | 1.67 | 2.48 |
| exact 2 | 27 | 2.76 | 1.82 | 2.72 | 3.68 |
| exact 3 | 13 | 3.63 | 1.73 | 3.19 | 5.71 |
| exact 4 | 6 | 3.63 | 1.91 | 3.79 | 5.15 |
| dead | 124 | 2.13 | 1.38 | 1.86 | 3.51 |
| at least 2+ | 2338 | 2.59 | 1.64 | 2.35 | 3.73 |
| at least 1 (open) | 7252 | 3.06 | 1.76 | 2.72 | 4.74 |

### phase3_astar_v0_sweep_l2

9,367 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.594; dead AUC 0.418; mean root h 2.87 (solved) vs 4.53 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 41 | 1.59 | 1.16 | 1.46 | 2.41 |
| exact 2 | 31 | 2.39 | 1.63 | 2.26 | 3.34 |
| exact 3 | 26 | 2.56 | 1.87 | 2.37 | 3.18 |
| exact 4 | 19 | 2.79 | 1.70 | 2.60 | 4.53 |
| exact 5 | 11 | 2.60 | 2.00 | 2.16 | 3.00 |
| exact 6 | 3 | 2.80 | 2.61 | 2.61 | 3.18 |
| exact 7 | 1 | 3.74 | 3.74 | 3.74 | 3.74 |
| dead | 145 | 2.05 | 1.32 | 1.77 | 3.12 |
| at least 2+ | 2260 | 2.23 | 1.50 | 2.09 | 3.07 |
| at least 1 (open) | 6830 | 2.74 | 1.66 | 2.43 | 4.18 |

### phase3_astar_v0_sweep_l4

8,327 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.459; dead AUC 0.430; mean root h 3.16 (solved) vs 4.22 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 40 | 1.64 | 1.20 | 1.43 | 2.53 |
| exact 2 | 28 | 2.48 | 1.45 | 2.49 | 3.64 |
| exact 3 | 19 | 2.57 | 1.33 | 2.21 | 4.72 |
| exact 4 | 11 | 2.82 | 1.89 | 2.29 | 4.57 |
| exact 5 | 9 | 2.98 | 1.67 | 2.16 | 6.80 |
| exact 6 | 9 | 2.96 | 1.46 | 1.86 | 7.76 |
| exact 7 | 4 | 2.79 | 1.89 | 2.35 | 5.00 |
| exact 8+ | 3 | 3.14 | 2.47 | 3.19 | 3.75 |
| dead | 157 | 2.00 | 1.33 | 1.92 | 2.89 |
| at least 2+ | 2215 | 2.03 | 1.47 | 1.88 | 2.70 |
| at least 1 (open) | 5832 | 2.54 | 1.63 | 2.18 | 3.88 |
