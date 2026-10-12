# Row 2: automation sweep + SFT v1 policy

The SFT v1 policy adapter (`results/phase2_sft_v1/`) on Qwen3.5-2B, zero-shot prompt, with the automation sweep,
best-first on the cumulative log-probability; row 1's budget (64 expansions, 600 s, depth 16, n = 16 at temperature
0.8, 256 tokens). Two vLLM servers (one per RTX 3090, each serving the base model with the policy and value adapters,
round-robin), 40 concurrent searches. Automation steps count as log-probability −2.4, the median of the SFT v1 probe's
progress samples (row 1 used the same rule, −12 for the few-shot model). Config
`experiments/configs/phase2_sft_v1_search.toml`; the per-run summary is `summary.md`, the row-0 comparison with
throughput `comparison.md`.

## Findings

- **148/244 (60.7%)** vs 115/244 for row 1 (few-shot Qwen3.5-2B) and 79/244 for row 0: 69 newly solved and none lost
  against row 0, 36 newly solved and 3 lost against row 1.
- Ahead of row 1 at every budget, and far cheaper in tokens: 12.6k generated tokens per theorem (row 1: 34.3k) and
  20.8k per solved theorem (row 1: 72.7k). Lean time per theorem doubled (132 s vs 64 s): more of the SFT policy's
  blocks run.
- Both GPUs ran at ~99% utilization with 40 concurrent searches, so this setup is GPU-bound; the run took 24 min.

## Comparison with rows 0 and 1

244 miniF2F-valid problems shared by every run. λ is A*'s value weight, D the dead-end readout; costs are means per theorem. Value prompt tokens are the value model's prefill-only requests.

| Run | Priority | λ | D | Solved | Expansions | Generated tokens | Generated tokens per solve | Value prompt tokens | Wall s | Lean s |
|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | depth_plus_goals | – | – | 79/244 (32.4%) | 7.3 | 0 | 0 | 0 | 8 | 8 |
| phase1_fewshot_search_qwen3.5-2b | cumulative_log_probability | – | – | 115/244 (47.1%) | 25.5 | 34,255 | 72,680 | 0 | 212 | 64 |
| phase1_fewshot_search_qwen3.5-2b-base | cumulative_log_probability | – | – | 117/244 (48.0%) | 28.3 | 53,687 | 111,962 | 0 | 291 | 75 |
| phase2_sft_v1_search | cumulative_log_probability | – | – | 148/244 (60.7%) | 24.0 | 12,611 | 20,791 | 0 | 177 | 132 |

## By category

| Run | mathd_algebra (70) | mathd_numbertheory (60) | amc12 (45) | aime (15) | imo (20) | algebra (18) | numbertheory (8) | induction (8) |
|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 28 | 38 | 8 | 0 | 0 | 5 | 0 | 0 |
| phase1_fewshot_search_qwen3.5-2b | 41 | 42 | 13 | 1 | 0 | 12 | 3 | 3 |
| phase1_fewshot_search_qwen3.5-2b-base | 46 | 40 | 13 | 0 | 0 | 13 | 2 | 3 |
| phase2_sft_v1_search | 53 | 49 | 17 | 2 | 1 | 16 | 4 | 6 |

## Anytime curves (solved theorems at budget, per theorem)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 59 | 72 | 77 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 77 | 91 | 100 | 107 | 111 | 114 | 115 | 115 | 115 |
| phase1_fewshot_search_qwen3.5-2b-base | 77 | 91 | 102 | 107 | 110 | 116 | 117 | 117 | 117 |
| phase2_sft_v1_search | 84 | 104 | 123 | 129 | 140 | 145 | 148 | 148 | 148 |

| generated_tokens ≤ | 500 | 1000 | 2000 | 5000 | 10000 | 20000 | 50000 | 100000 | 173655 |
|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 75 | 80 | 94 | 102 | 107 | 110 | 115 | 115 | 115 |
| phase1_fewshot_search_qwen3.5-2b-base | 71 | 77 | 85 | 102 | 107 | 109 | 117 | 117 | 117 |
| phase2_sft_v1_search | 101 | 117 | 128 | 133 | 143 | 146 | 148 | 148 | 148 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 609.441 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| phase0_automation_baseline | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| phase1_fewshot_search_qwen3.5-2b | 40 | 55 | 63 | 76 | 95 | 99 | 105 | 110 | 111 | 115 | 115 | 115 |
| phase1_fewshot_search_qwen3.5-2b-base | 40 | 55 | 60 | 74 | 91 | 97 | 106 | 108 | 111 | 115 | 117 | 117 |
| phase2_sft_v1_search | 40 | 57 | 85 | 108 | 119 | 125 | 133 | 143 | 144 | 145 | 148 | 148 |

## Newly solved and lost against the reference runs

**phase1_fewshot_search_qwen3.5-2b-base vs phase0_automation_baseline**: 38 newly solved, 0 lost.

- newly solved: `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_apb4leq8ta4pb4`, `algebra_binomnegdiscrineq_10alt28asqp1`, `algebra_manipexpr_apbeq2cceqiacpbceqm2`, `algebra_sqineq_2at2pclta2c2p41pc`, `algebra_sqineq_2unitcircatblt1`, `algebra_sqineq_36azm9asqle36zsq`, `algebra_sqineq_4bap1lt4bsqpap1sq`, `amc12_2000_p11`, `amc12a_2008_p8`, `amc12a_2009_p5`, `amc12a_2011_p18`, `amc12a_2016_p3`, `induction_divisibility_3div2tooddnp1`, `induction_sum2kp1npqsqm1`, `induction_sum_1oktkp1`, `mathd_algebra_11`, `mathd_algebra_116`, `mathd_algebra_140`, `mathd_algebra_181`, `mathd_algebra_192`, `mathd_algebra_22`, `mathd_algebra_234`, `mathd_algebra_251`, `mathd_algebra_28`, `mathd_algebra_327`, `mathd_algebra_410`, `mathd_algebra_421`, `mathd_algebra_433`, `mathd_algebra_437`, `mathd_algebra_493`, `mathd_algebra_536`, `mathd_algebra_547`, `mathd_algebra_89`, `mathd_numbertheory_22`, `mathd_numbertheory_326`, `numbertheory_2dvd4expn`, `numbertheory_nckeqnm1ckpnm1ckm1`
- lost: none

**phase1_fewshot_search_qwen3.5-2b-base vs phase1_fewshot_search_qwen3.5-2b**: 10 newly solved, 8 lost.

- newly solved: `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `amc12a_2011_p18`, `amc12a_2016_p3`, `induction_divisibility_3div2tooddnp1`, `mathd_algebra_11`, `mathd_algebra_140`, `mathd_algebra_327`, `mathd_algebra_437`, `mathd_algebra_493`, `mathd_numbertheory_22`
- lost: `aime_1984_p15`, `amc12_2001_p9`, `amc12a_2009_p9`, `induction_seq_mul2pnp1`, `mathd_numbertheory_257`, `mathd_numbertheory_412`, `mathd_numbertheory_84`, `numbertheory_sqmod4in01d`

**phase2_sft_v1_search vs phase0_automation_baseline**: 69 newly solved, 0 lost.

- newly solved: `aime_1984_p15`, `aime_1991_p1`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `algebra_apb4leq8ta4pb4`, `algebra_binomnegdiscrineq_10alt28asqp1`, `algebra_manipexpr_apbeq2cceqiacpbceqm2`, `algebra_sqineq_2at2pclta2c2p41pc`, `algebra_sqineq_2unitcircatblt1`, `algebra_sqineq_36azm9asqle36zsq`, `algebra_sqineq_4bap1lt4bsqpap1sq`, `amc12_2000_p11`, `amc12_2000_p5`, `amc12a_2008_p8`, `amc12a_2009_p5`, `amc12a_2009_p9`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12b_2002_p6`, `amc12b_2020_p5`, `imo_1984_p2`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `induction_sum2kp1npqsqm1`, `induction_sum_1oktkp1`, `mathd_algebra_11`, `mathd_algebra_116`, `mathd_algebra_13`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_181`, `mathd_algebra_192`, `mathd_algebra_206`, `mathd_algebra_22`, `mathd_algebra_234`, `mathd_algebra_251`, `mathd_algebra_267`, `mathd_algebra_28`, `mathd_algebra_327`, `mathd_algebra_410`, `mathd_algebra_421`, `mathd_algebra_433`, `mathd_algebra_437`, `mathd_algebra_451`, `mathd_algebra_493`, `mathd_algebra_510`, `mathd_algebra_536`, `mathd_algebra_547`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_numbertheory_22`, `mathd_numbertheory_257`, `mathd_numbertheory_32`, `mathd_numbertheory_326`, `mathd_numbertheory_35`, `mathd_numbertheory_412`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `mathd_numbertheory_84`, `numbertheory_2dvd4expn`, `numbertheory_nckeqnm1ckpnm1ckm1`, `numbertheory_sqmod3in01d`, `numbertheory_sqmod4in01d`
- lost: none

**phase2_sft_v1_search vs phase1_fewshot_search_qwen3.5-2b**: 36 newly solved, 3 lost.

- newly solved: `aime_1991_p1`, `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`, `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`, `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`, `amc12_2000_p5`, `amc12a_2011_p18`, `amc12a_2013_p8`, `amc12b_2002_p6`, `amc12b_2020_p5`, `imo_1984_p2`, `induction_divisibility_3div2tooddnp1`, `induction_divisibility_3divnto3m2n`, `induction_divisibility_9div10tonm1`, `induction_ineq_nsqlefactn`, `mathd_algebra_11`, `mathd_algebra_13`, `mathd_algebra_140`, `mathd_algebra_151`, `mathd_algebra_206`, `mathd_algebra_267`, `mathd_algebra_327`, `mathd_algebra_437`, `mathd_algebra_451`, `mathd_algebra_493`, `mathd_algebra_510`, `mathd_algebra_73`, `mathd_algebra_77`, `mathd_numbertheory_22`, `mathd_numbertheory_32`, `mathd_numbertheory_35`, `mathd_numbertheory_629`, `mathd_numbertheory_64`, `mathd_numbertheory_690`, `mathd_numbertheory_780`, `numbertheory_sqmod3in01d`
- lost: `amc12_2001_p9`, `induction_seq_mul2pnp1`, `mathd_algebra_89`
