# Row 4 (development): A* with value v0

Row 2's policy and budget (SFT v1 policy adapter, automation sweep, n = 16 at temperature 0.8, 256 tokens, 64
expansions, 600 s, depth 16, 40 concurrent searches) with A*: f = depth + λ·h, h from the value-v0 adapter
(`results/phase3_value_v0/`). Rows 2 and 4 ran back to back on the same two vLLM servers (one per RTX 3090, each
serving Qwen3.5-2B with both adapters, round-robin). Config `experiments/configs/phase3_astar_v0.toml`.

## Findings

- **155/244 (63.5%) vs 148/244 (60.7%) for row 2**: 12 newly solved, 5 lost (two-sided sign test p ≈ 0.14, one
  seed). A* is ahead at every expansion budget from 2 on (119 vs 104 at 2, 139 vs 129 at 8, 146 vs 140 at 16) and at
  every generated-token budget, and spends 13% less Lean time per theorem; at the very smallest wall-clock budgets
  it is slightly behind (the value requests add latency).
- Cost: 20,390 prefill-only value requests (226 prompt tokens each, 18.9k per theorem, next to 12.2k generated
  tokens). The run took 24.2 min against 24.0 min for row 2.
- λ sweep on 83 row-0-unsolved problems (every other one; `sweep.md`): λ = 0.5 / 1 / 2 / 4 solve 40 / 39 / 41 / 40
  against 37 for row 2. λ = 0.5 has the best anytime curves over expansions, tokens and wall time, so the full run
  uses it. D was not swept: v0 has no dead labels and puts p_dead ≈ 1e-7 on every state, so D does not change h.
  The subset belongs to the same split, so the choice of λ carries a small selection bias.
- Calibration (`served_trees_*.md`; trees are only scored, never trained on): h orders the exact remaining steps
  (Spearman 0.73 on this run's trees, 0.55 on row 2's trees, 0.80 on held-out traced proof states) and separates
  solved from unsolved theorems at the root (mean 2.8 vs 4.4). It does not recognize dead ends: fully expanded nodes
  without a proof get h ≈ 2 (row 2 trees: 2.1), like states one or two steps from a proof, because v0 only saw
  states on successful proofs. This is what value v1 (dead and censored labels from statement-pool trees) must fix.
- One value request failed with a transport error during the sweep (the λ = 4 run was restarted); the estimator now
  retries such requests (one retry needed in the rerun, none in the full run).

## Comparison with rows 0, 1 and 2

244 miniF2F-valid problems shared by every run. λ is A*'s value weight, D the dead-end readout; costs are means per theorem. Value prompt tokens are the value model's prefill-only requests.

| Run | Priority | λ | D | Solved | Expansions | Generated tokens | Generated tokens per solve | Value prompt tokens | Wall s | Lean s |
|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | depth_plus_goals | – | – | 79/244 (32.4%) | 7.3 | 0 | 0 | 0 | 8 | 8 |
| phase1_fewshot_search_qwen3.5-2b | cumulative_log_probability | – | – | 115/244 (47.1%) | 25.5 | 34,255 | 72,680 | 0 | 212 | 64 |
| phase2_sft_v1_search | cumulative_log_probability | – | – | 148/244 (60.7%) | 24.0 | 12,611 | 20,791 | 0 | 177 | 132 |
| phase3_astar_v0 | a_star | 0.5 | 16 | 155/244 (63.5%) | 22.1 | 12,208 | 19,217 | 18,861 | 175 | 115 |

## By category

| Run | mathd_algebra (70) | mathd_numbertheory (60) | amc12 (45) | aime (15) | imo (20) | algebra (18) | numbertheory (8) | induction (8) |
|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 28 | 38 | 8 | 0 | 0 | 5 | 0 | 0 |
| phase1_fewshot_search_qwen3.5-2b | 41 | 42 | 13 | 1 | 0 | 12 | 3 | 3 |
| phase2_sft_v1_search | 53 | 49 | 17 | 2 | 1 | 16 | 4 | 6 |
| phase3_astar_v0 | 58 | 49 | 19 | 2 | 2 | 15 | 4 | 6 |

## Anytime curves (solved theorems at budget, per theorem)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 59 | 72 | 77 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 77 | 91 | 100 | 107 | 111 | 114 | 115 | 115 | 115 |
| phase2_sft_v1_search | 84 | 104 | 123 | 129 | 140 | 145 | 148 | 148 | 148 |
| phase3_astar_v0 | 84 | 119 | 131 | 139 | 146 | 152 | 155 | 155 | 155 |

| generated_tokens ≤ | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 163426 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 75 | 80 | 94 | 102 | 107 | 110 | 115 | 115 | 115 |
| phase2_sft_v1_search | 101 | 117 | 128 | 133 | 143 | 146 | 148 | 148 | 148 |
| phase3_astar_v0 | 105 | 122 | 132 | 143 | 149 | 153 | 154 | 155 | 155 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 613.161 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 40 | 55 | 63 | 76 | 95 | 99 | 105 | 110 | 111 | 115 | 115 | 115 |
| phase2_sft_v1_search | 40 | 57 | 85 | 108 | 119 | 125 | 133 | 143 | 144 | 145 | 148 | 148 |
| phase3_astar_v0 | 33 | 55 | 80 | 105 | 123 | 127 | 139 | 147 | 148 | 151 | 155 | 155 |

## Newly solved and lost against the reference runs

**phase3_astar_v0 vs phase0_automation_baseline**: 76 newly solved, 0 lost.

- newly solved: `aime_1984_p15`, `aime_1991_p1`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_apb4leq8ta4pb4`, `algebra_binomnegdiscrineq_10alt28asqp1`, `algebra_manipexpr_apbeq2cceqiacpbceqm2`, `algebra_sqineq_2at2pclta2c2p41pc`, `algebra_sqineq_2unitcircatblt1`, `algebra_sqineq_36azm9asqle36zsq`, `algebra_sqineq_4bap1lt4bsqpap1sq`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12_2000_p11`, `amc12_2000_p5`, `amc12a_2009_p5`, `amc12a_2009_p9`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12a_2015_p10`, `amc12b_2002_p6`, `amc12b_2003_p17`, `amc12b_2004_p3`, `amc12b_2020_p5`, `imo_1961_p1`, `imo_1974_p5`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `induction_sum2kp1npqsqm1`, `induction_sum_1oktkp1`, `mathd_algebra_11`, `mathd_algebra_116`, `mathd_algebra_13`, `mathd_algebra_131`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_181`, `mathd_algebra_192`, `mathd_algebra_206`, `mathd_algebra_22`, `mathd_algebra_234`, `mathd_algebra_251`, `mathd_algebra_267`, `mathd_algebra_28`, `mathd_algebra_323`, `mathd_algebra_327`, `mathd_algebra_393`, `mathd_algebra_405`, `mathd_algebra_410`, `mathd_algebra_421`, `mathd_algebra_433`, `mathd_algebra_437`, `mathd_algebra_480`, `mathd_algebra_493`, `mathd_algebra_510`, `mathd_algebra_536`, `mathd_algebra_547`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_algebra_89`, `mathd_numbertheory_22`, `mathd_numbertheory_257`, `mathd_numbertheory_32`, `mathd_numbertheory_326`, `mathd_numbertheory_35`, `mathd_numbertheory_412`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `mathd_numbertheory_84`, `numbertheory_2dvd4expn`, `numbertheory_nckeqnm1ckpnm1ckm1`, `numbertheory_sqmod3in01d`, `numbertheory_sqmod4in01d`
- lost: none

**phase3_astar_v0 vs phase1_fewshot_search_qwen3.5-2b**: 43 newly solved, 3 lost.

- newly solved: `aime_1991_p1`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12_2000_p5`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12a_2015_p10`, `amc12b_2002_p6`, `amc12b_2003_p17`, `amc12b_2004_p3`, `amc12b_2020_p5`, `imo_1961_p1`, `imo_1974_p5`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `mathd_algebra_11`, `mathd_algebra_13`, `mathd_algebra_131`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_206`, `mathd_algebra_267`, `mathd_algebra_323`, `mathd_algebra_327`, `mathd_algebra_393`, `mathd_algebra_405`, `mathd_algebra_437`, `mathd_algebra_480`, `mathd_algebra_493`, `mathd_algebra_510`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_numbertheory_22`, `mathd_numbertheory_32`, `mathd_numbertheory_35`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `numbertheory_sqmod3in01d`
- lost: `amc12_2001_p9`, `amc12a_2008_p8`, `induction_seq_mul2pnp1`

**phase3_astar_v0 vs phase2_sft_v1_search**: 12 newly solved, 5 lost.

- newly solved: `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12a_2015_p10`, `amc12b_2003_p17`, `amc12b_2004_p3`, `imo_1961_p1`, `imo_1974_p5`, `mathd_algebra_131`, `mathd_algebra_323`, `mathd_algebra_393`, `mathd_algebra_405`, `mathd_algebra_480`, `mathd_algebra_89`
- lost: `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `amc12a_2008_p8`, `imo_1984_p2`, `mathd_algebra_451`

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
