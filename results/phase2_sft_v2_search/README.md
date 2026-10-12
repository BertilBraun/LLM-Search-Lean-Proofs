# Row 2 with SFT v2: automation sweep + SFT v2 policy

The protocol of the v1 pair (`results/phase2_sft_v1_search/`) with the SFT v2 policy adapter (`policy-v2`): automation
sweep plus the policy, best-first on the cumulative log-probability, 64 expansions, 600 s, depth 16, n = 16 at
temperature 0.8, 256 tokens, two vLLM servers (one per RTX 3090, each serving `policy-v2` and `value-v0`), 40
concurrent searches. Automation steps count as −2.8, the median log-probability of the SFT v2 probe's progress samples
(`/workspace/runs/phase2_sft_v2_probe`, all 982 states; v1: −2.39, used as −2.4). Config
`experiments/configs/phase2_sft_v2_search.toml`.

## Findings

- **148/244 (60.7%), the same as SFT v1**: 5 newly solved and 5 lost against the v1 row 2; 69 newly solved and none lost
  against row 0, 36 newly solved and 3 lost against row 1.
- Cheaper in tokens: 8.7k generated tokens per theorem (v1: 12.6k) although generation is now charged per batch,
  including failed samples and candidates left unrun after a proof (the v1 runs did not count those).
- Not comparable with v1 in wall time: an expert-iteration pool pre-filter ran its own Lean processes during the v2
  pair (mean 1-minute load 43 on the 46-core quota, about 34 during the v1 pair), so Lean time per theorem rose to
  155 s (v1: 132 s) and the run took 25.5 min (v1: 24.0 min).

## Comparison with rows 0, 1 and the v1 pair

244 miniF2F-valid problems shared by every run. λ is A*'s value weight, D the dead-end readout; costs are means per theorem. Value prompt tokens are the value model's prefill-only requests.

| Run | Priority | λ | D | Solved | Expansions | Generated tokens | Generated tokens per solve | Value prompt tokens | Wall s | Lean s |
|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | depth_plus_goals | – | – | 79/244 (32.4%) | 7.3 | 0 | 0 | 0 | 8 | 8 |
| phase1_fewshot_search_qwen3.5-2b | cumulative_log_probability | – | – | 115/244 (47.1%) | 25.5 | 34,255 | 72,680 | 0 | 212 | 64 |
| phase2_sft_v1_search | cumulative_log_probability | – | – | 148/244 (60.7%) | 24.0 | 12,611 | 20,791 | 0 | 177 | 132 |
| phase3_astar_v0 | a_star | 0.5 | 16 | 155/244 (63.5%) | 22.1 | 12,208 | 19,217 | 18,861 | 175 | 115 |
| phase2_sft_v2_search | cumulative_log_probability | – | – | 148/244 (60.7%) | 22.5 | 8,684 | 14,317 | 0 | 197 | 155 |

## By category

| Run | mathd_algebra (70) | mathd_numbertheory (60) | amc12 (45) | aime (15) | imo (20) | algebra (18) | numbertheory (8) | induction (8) |
|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 28 | 38 | 8 | 0 | 0 | 5 | 0 | 0 |
| phase1_fewshot_search_qwen3.5-2b | 41 | 42 | 13 | 1 | 0 | 12 | 3 | 3 |
| phase2_sft_v1_search | 53 | 49 | 17 | 2 | 1 | 16 | 4 | 6 |
| phase3_astar_v0 | 58 | 49 | 19 | 2 | 2 | 15 | 4 | 6 |
| phase2_sft_v2_search | 53 | 49 | 18 | 1 | 1 | 15 | 4 | 7 |

## Anytime curves (solved theorems at budget, per theorem)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 59 | 72 | 77 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 77 | 91 | 100 | 107 | 111 | 114 | 115 | 115 | 115 |
| phase2_sft_v1_search | 84 | 104 | 123 | 129 | 140 | 145 | 148 | 148 | 148 |
| phase3_astar_v0 | 84 | 119 | 131 | 139 | 146 | 152 | 155 | 155 | 155 |
| phase2_sft_v2_search | 83 | 102 | 128 | 136 | 141 | 144 | 148 | 148 | 148 |

| generated_tokens ≤ | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 163426 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 75 | 80 | 94 | 102 | 107 | 110 | 115 | 115 | 115 |
| phase2_sft_v1_search | 101 | 117 | 128 | 133 | 143 | 146 | 148 | 148 | 148 |
| phase3_astar_v0 | 105 | 122 | 132 | 143 | 149 | 153 | 154 | 155 | 155 |
| phase2_sft_v2_search | 85 | 110 | 130 | 140 | 144 | 147 | 148 | 148 | 148 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 615.485 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 40 | 55 | 63 | 76 | 95 | 99 | 105 | 110 | 111 | 115 | 115 | 115 |
| phase2_sft_v1_search | 40 | 57 | 85 | 108 | 119 | 125 | 133 | 143 | 144 | 145 | 148 | 148 |
| phase3_astar_v0 | 33 | 55 | 80 | 105 | 123 | 127 | 139 | 147 | 148 | 151 | 155 | 155 |
| phase2_sft_v2_search | 33 | 47 | 69 | 91 | 118 | 124 | 135 | 140 | 140 | 146 | 148 | 148 |

## Newly solved and lost against the reference runs

**phase2_sft_v2_search vs phase0_automation_baseline**: 69 newly solved, 0 lost.

- newly solved: `aime_1984_p15`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `algebra_apb4leq8ta4pb4`, `algebra_binomnegdiscrineq_10alt28asqp1`, `algebra_manipexpr_apbeq2cceqiacpbceqm2`, `algebra_sqineq_2at2pclta2c2p41pc`, `algebra_sqineq_2unitcircatblt1`, `algebra_sqineq_36azm9asqle36zsq`, `algebra_sqineq_4bap1lt4bsqpap1sq`, `amc12_2000_p11`, `amc12_2000_p5`, `amc12a_2009_p5`, `amc12a_2009_p9`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12a_2015_p10`, `amc12b_2002_p6`, `amc12b_2003_p17`, `amc12b_2020_p5`, `imo_1961_p1`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `induction_seq_mul2pnp1`, `induction_sum2kp1npqsqm1`, `induction_sum_1oktkp1`, `mathd_algebra_11`, `mathd_algebra_116`, `mathd_algebra_13`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_181`, `mathd_algebra_192`, `mathd_algebra_206`, `mathd_algebra_22`, `mathd_algebra_234`, `mathd_algebra_251`, `mathd_algebra_267`, `mathd_algebra_28`, `mathd_algebra_327`, `mathd_algebra_410`, `mathd_algebra_421`, `mathd_algebra_433`, `mathd_algebra_437`, `mathd_algebra_493`, `mathd_algebra_510`, `mathd_algebra_536`, `mathd_algebra_547`, `mathd_algebra_59`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_numbertheory_22`, `mathd_numbertheory_257`, `mathd_numbertheory_32`, `mathd_numbertheory_326`, `mathd_numbertheory_35`, `mathd_numbertheory_412`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `mathd_numbertheory_84`, `numbertheory_2dvd4expn`, `numbertheory_nckeqnm1ckpnm1ckm1`, `numbertheory_sqmod3in01d`, `numbertheory_sqmod4in01d`
- lost: none

**phase2_sft_v2_search vs phase1_fewshot_search_qwen3.5-2b**: 36 newly solved, 3 lost.

- newly solved: `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `amc12_2000_p5`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12a_2015_p10`, `amc12b_2002_p6`, `amc12b_2003_p17`, `amc12b_2020_p5`, `imo_1961_p1`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `mathd_algebra_11`, `mathd_algebra_13`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_206`, `mathd_algebra_267`, `mathd_algebra_327`, `mathd_algebra_437`, `mathd_algebra_493`, `mathd_algebra_510`, `mathd_algebra_59`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_numbertheory_22`, `mathd_numbertheory_32`, `mathd_numbertheory_35`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `numbertheory_sqmod3in01d`
- lost: `amc12_2001_p9`, `amc12a_2008_p8`, `mathd_algebra_89`

**phase2_sft_v2_search vs phase2_sft_v1_search**: 5 newly solved, 5 lost.

- newly solved: `amc12a_2015_p10`, `amc12b_2003_p17`, `imo_1961_p1`, `induction_seq_mul2pnp1`, `mathd_algebra_59`
- lost: `aime_1991_p1`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `amc12a_2008_p8`, `imo_1984_p2`, `mathd_algebra_451`

**phase2_sft_v2_search vs phase3_astar_v0**: 3 newly solved, 10 lost.

- newly solved: `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `induction_seq_mul2pnp1`, `mathd_algebra_59`
- lost: `aime_1991_p1`, `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`, `amc12b_2004_p3`, `imo_1974_p5`, `mathd_algebra_131`, `mathd_algebra_323`, `mathd_algebra_393`, `mathd_algebra_405`, `mathd_algebra_480`, `mathd_algebra_89`

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
