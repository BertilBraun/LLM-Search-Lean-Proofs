# Row 4 with SFT v2: A* with value v0

Row 2 with SFT v2 (`results/phase2_sft_v2_search/`), same policy, budget and servers, run right after it, with A*:
f = depth + 0.5·h, h from value v0 (λ from the v1 pair's sweep, not re-swept; D has no effect on v0). Config
`experiments/configs/phase3_astar_v0_sft_v2.toml`.

## Findings

- **157/244 (64.3%) vs 148/244 (60.7%) for row 2 with SFT v2**: 12 newly solved, 3 lost (two-sided sign test
  p ≈ 0.035). The v1 pair gave 155 vs 148 (12 newly solved, 5 lost, p ≈ 0.14); across both pairs A* gains 24 theorems
  and loses 8 (the pairs share the problems and the value model, so this is not an independent test).
- A* is ahead at almost every expansion and token budget (123 vs 102 at 2 expansions, 144 vs 141 at 16, 153 vs 144
  at 32) and at most wall-clock budgets, with 21% less Lean time per theorem (123 s vs 155 s) and a slightly shorter
  run (24.3 vs 25.5 min).
- Value cost: 19,823 prefill-only requests, 230 prompt tokens each (18.7k per theorem, next to 8.3k generated tokens
  per theorem); policy sampling ran at the same rate as in row 2 (58 samples/s).
- Against the v1 A* run (155/244): 8 newly solved, 6 lost; with SFT v2 the policy alone does not improve on v1, A* on
  top of either policy adds 7–9 theorems.
- Calibration (`served_trees_phase2_sft_v2_search.md` scores row 2's trees, which A* did not steer; this run's own
  trees below): h orders the exact remaining steps (Spearman 0.65 on row 2's trees, 0.70 on this run's) and the
  roots of solved theorems get a lower h (2.8 vs 4.5), but dead ends still look close to a proof (h ≈ 2.3–2.5),
  as with SFT v1: v0 has never seen a dead end.
- The pair ran while an expert-iteration pool pre-filter used part of the CPU (mean 1-minute load 43,
  `load_session.log` on the node); both rows of the pair ran under it.

## Comparison with rows 0, 1, the v1 pair and row 2 with SFT v2

244 miniF2F-valid problems shared by every run. λ is A*'s value weight, D the dead-end readout; costs are means per theorem. Value prompt tokens are the value model's prefill-only requests.

| Run | Priority | λ | D | Solved | Expansions | Generated tokens | Generated tokens per solve | Value prompt tokens | Wall s | Lean s |
|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | depth_plus_goals | – | – | 79/244 (32.4%) | 7.3 | 0 | 0 | 0 | 8 | 8 |
| phase1_fewshot_search_qwen3.5-2b | cumulative_log_probability | – | – | 115/244 (47.1%) | 25.5 | 34,255 | 72,680 | 0 | 212 | 64 |
| phase2_sft_v1_search | cumulative_log_probability | – | – | 148/244 (60.7%) | 24.0 | 12,611 | 20,791 | 0 | 177 | 132 |
| phase3_astar_v0 | a_star | 0.5 | 16 | 155/244 (63.5%) | 22.1 | 12,208 | 19,217 | 18,861 | 175 | 115 |
| phase2_sft_v2_search | cumulative_log_probability | – | – | 148/244 (60.7%) | 22.5 | 8,684 | 14,317 | 0 | 197 | 155 |
| phase3_astar_v0_sft_v2 | a_star | 0.5 | 16 | 157/244 (64.3%) | 21.6 | 8,338 | 12,958 | 18,661 | 175 | 123 |

## By category

| Run | mathd_algebra (70) | mathd_numbertheory (60) | amc12 (45) | aime (15) | imo (20) | algebra (18) | numbertheory (8) | induction (8) |
|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 28 | 38 | 8 | 0 | 0 | 5 | 0 | 0 |
| phase1_fewshot_search_qwen3.5-2b | 41 | 42 | 13 | 1 | 0 | 12 | 3 | 3 |
| phase2_sft_v1_search | 53 | 49 | 17 | 2 | 1 | 16 | 4 | 6 |
| phase3_astar_v0 | 58 | 49 | 19 | 2 | 2 | 15 | 4 | 6 |
| phase2_sft_v2_search | 53 | 49 | 18 | 1 | 1 | 15 | 4 | 7 |
| phase3_astar_v0_sft_v2 | 55 | 49 | 20 | 2 | 4 | 16 | 4 | 7 |

## Anytime curves (solved theorems at budget, per theorem)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 59 | 72 | 77 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 77 | 91 | 100 | 107 | 111 | 114 | 115 | 115 | 115 |
| phase2_sft_v1_search | 84 | 104 | 123 | 129 | 140 | 145 | 148 | 148 | 148 |
| phase3_astar_v0 | 84 | 119 | 131 | 139 | 146 | 152 | 155 | 155 | 155 |
| phase2_sft_v2_search | 83 | 102 | 128 | 136 | 141 | 144 | 148 | 148 | 148 |
| phase3_astar_v0_sft_v2 | 89 | 123 | 133 | 138 | 144 | 153 | 157 | 157 | 157 |

| generated_tokens ≤ | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 163426 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 75 | 80 | 94 | 102 | 107 | 110 | 115 | 115 | 115 |
| phase2_sft_v1_search | 101 | 117 | 128 | 133 | 143 | 146 | 148 | 148 | 148 |
| phase3_astar_v0 | 105 | 122 | 132 | 143 | 149 | 153 | 154 | 155 | 155 |
| phase2_sft_v2_search | 85 | 110 | 130 | 140 | 144 | 147 | 148 | 148 | 148 |
| phase3_astar_v0_sft_v2 | 100 | 121 | 132 | 140 | 150 | 156 | 157 | 157 | 157 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 615.485 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 40 | 55 | 63 | 76 | 95 | 99 | 105 | 110 | 111 | 115 | 115 | 115 |
| phase2_sft_v1_search | 40 | 57 | 85 | 108 | 119 | 125 | 133 | 143 | 144 | 145 | 148 | 148 |
| phase3_astar_v0 | 33 | 55 | 80 | 105 | 123 | 127 | 139 | 147 | 148 | 151 | 155 | 155 |
| phase2_sft_v2_search | 33 | 47 | 69 | 91 | 118 | 124 | 135 | 140 | 140 | 146 | 148 | 148 |
| phase3_astar_v0_sft_v2 | 34 | 52 | 79 | 106 | 124 | 126 | 137 | 145 | 148 | 153 | 157 | 157 |

## Newly solved and lost against the reference runs

**phase3_astar_v0_sft_v2 vs phase0_automation_baseline**: 78 newly solved, 0 lost.

- newly solved: `aime_1983_p9`, `aime_1984_p15`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `algebra_apb4leq8ta4pb4`, `algebra_binomnegdiscrineq_10alt28asqp1`, `algebra_manipexpr_apbeq2cceqiacpbceqm2`, `algebra_sqineq_2at2pclta2c2p41pc`, `algebra_sqineq_2unitcircatblt1`, `algebra_sqineq_36azm9asqle36zsq`, `algebra_sqineq_4bap1lt4bsqpap1sq`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12_2000_p11`, `amc12_2000_p5`, `amc12_2001_p9`, `amc12a_2008_p8`, `amc12a_2009_p5`, `amc12a_2009_p9`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12a_2015_p10`, `amc12b_2002_p6`, `amc12b_2003_p17`, `amc12b_2020_p5`, `imo_1961_p1`, `imo_1964_p1_2`, `imo_1974_p5`, `imo_1984_p2`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `induction_seq_mul2pnp1`, `induction_sum2kp1npqsqm1`, `induction_sum_1oktkp1`, `mathd_algebra_11`, `mathd_algebra_116`, `mathd_algebra_13`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_181`, `mathd_algebra_192`, `mathd_algebra_206`, `mathd_algebra_22`, `mathd_algebra_234`, `mathd_algebra_251`, `mathd_algebra_267`, `mathd_algebra_28`, `mathd_algebra_327`, `mathd_algebra_405`, `mathd_algebra_410`, `mathd_algebra_421`, `mathd_algebra_433`, `mathd_algebra_437`, `mathd_algebra_451`, `mathd_algebra_480`, `mathd_algebra_510`, `mathd_algebra_536`, `mathd_algebra_547`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_algebra_89`, `mathd_numbertheory_22`, `mathd_numbertheory_257`, `mathd_numbertheory_32`, `mathd_numbertheory_326`, `mathd_numbertheory_35`, `mathd_numbertheory_412`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `mathd_numbertheory_84`, `numbertheory_2dvd4expn`, `numbertheory_nckeqnm1ckpnm1ckm1`, `numbertheory_sqmod3in01d`, `numbertheory_sqmod4in01d`
- lost: none

**phase3_astar_v0_sft_v2 vs phase1_fewshot_search_qwen3.5-2b**: 42 newly solved, 0 lost.

- newly solved: `aime_1983_p9`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12_2000_p5`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12a_2015_p10`, `amc12b_2002_p6`, `amc12b_2003_p17`, `amc12b_2020_p5`, `imo_1961_p1`, `imo_1964_p1_2`, `imo_1974_p5`, `imo_1984_p2`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `mathd_algebra_11`, `mathd_algebra_13`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_206`, `mathd_algebra_267`, `mathd_algebra_327`, `mathd_algebra_405`, `mathd_algebra_437`, `mathd_algebra_451`, `mathd_algebra_480`, `mathd_algebra_510`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_numbertheory_22`, `mathd_numbertheory_32`, `mathd_numbertheory_35`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `numbertheory_sqmod3in01d`
- lost: none

**phase3_astar_v0_sft_v2 vs phase2_sft_v1_search**: 12 newly solved, 3 lost.

- newly solved: `aime_1983_p9`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12_2001_p9`, `amc12a_2015_p10`, `amc12b_2003_p17`, `imo_1961_p1`, `imo_1964_p1_2`, `imo_1974_p5`, `induction_seq_mul2pnp1`, `mathd_algebra_405`, `mathd_algebra_480`, `mathd_algebra_89`
- lost: `aime_1991_p1`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `mathd_algebra_493`

**phase3_astar_v0_sft_v2 vs phase3_astar_v0**: 8 newly solved, 6 lost.

- newly solved: `aime_1983_p9`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `amc12_2001_p9`, `amc12a_2008_p8`, `imo_1964_p1_2`, `imo_1984_p2`, `induction_seq_mul2pnp1`, `mathd_algebra_451`
- lost: `aime_1991_p1`, `amc12b_2004_p3`, `mathd_algebra_131`, `mathd_algebra_323`, `mathd_algebra_393`, `mathd_algebra_493`

**phase3_astar_v0_sft_v2 vs phase2_sft_v2_search**: 12 newly solved, 3 lost.

- newly solved: `aime_1983_p9`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12_2001_p9`, `amc12a_2008_p8`, `imo_1964_p1_2`, `imo_1974_p5`, `imo_1984_p2`, `mathd_algebra_405`, `mathd_algebra_451`, `mathd_algebra_480`, `mathd_algebra_89`
- lost: `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `mathd_algebra_493`, `mathd_algebra_59`

## Value calibration on the search trees

Each node's h (as scored when it was enqueued) against its label from the tree labeler: exact remaining steps for nodes that reach the proof (fewest edges), dead for fully expanded nodes without a proof, at least n otherwise (open nodes: at least 1). Dead AUC: h separating dead from exact nodes.

### phase3_astar_v0

20,391 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.730; dead AUC 0.448; mean root h 2.82 (solved) vs 4.38 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 155 | 1.69 | 1.20 | 1.51 | 2.45 |
| exact 2 | 71 | 3.04 | 1.99 | 2.86 | 4.11 |
| exact 3 | 46 | 3.72 | 1.47 | 3.16 | 7.50 |
| exact 4 | 32 | 3.73 | 2.48 | 3.57 | 5.04 |
| exact 5 | 12 | 4.46 | 2.61 | 4.44 | 6.75 |
| exact 6 | 7 | 4.58 | 2.61 | 5.15 | 7.11 |
| dead | 196 | 2.26 | 1.31 | 1.96 | 3.79 |
| at least 2+ | 4860 | 2.94 | 1.66 | 2.65 | 4.61 |
| at least 1 (open) | 15012 | 3.26 | 1.76 | 2.89 | 5.28 |

### phase3_astar_v0_sft_v2

19,824 labelled nodes with an estimate. Spearman of h with the exact remaining steps 0.702; dead AUC 0.461; mean root h 2.79 (solved) vs 4.46 (unsolved).

| Label | Nodes | Mean h | p10 | Median | p90 |
|---|---|---|---|---|---|
| exact 1 | 157 | 1.81 | 1.21 | 1.63 | 2.53 |
| exact 2 | 68 | 3.35 | 2.01 | 2.98 | 5.09 |
| exact 3 | 34 | 3.69 | 2.40 | 3.21 | 5.95 |
| exact 4 | 31 | 3.75 | 2.27 | 3.27 | 6.18 |
| exact 5 | 15 | 3.64 | 2.06 | 3.34 | 6.46 |
| exact 6 | 1 | 3.79 | 3.79 | 3.79 | 3.79 |
| dead | 254 | 2.28 | 1.40 | 2.09 | 3.36 |
| at least 2+ | 4677 | 2.86 | 1.64 | 2.62 | 4.39 |
| at least 1 (open) | 14587 | 3.20 | 1.81 | 2.90 | 4.93 |
