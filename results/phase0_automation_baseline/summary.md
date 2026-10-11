# Proof search: phase0_automation_baseline

Run `phase0_automation_baseline` on miniF2F-valid, git `6cb6053176c939a64ec36899a25fb7c4ec8e68ee`, config `experiments/configs/phase0_automation_baseline.toml` (copied as `config.toml`). Started 2026-10-11T14:51:18+00:00, 5.2 min wall, 46 CPUs, load average 6.4 at start.

**Solved 79/244 (32.4%).** Solved only with proofs of 2 or more steps: 20. Verification failures (bugs): 0. Proofs that also verify without the per-step heartbeat wrappers: 79/79. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 28 | 0.4 |
| mathd_numbertheory | 60 | 38 | 0.633 |
| amc12 | 45 | 8 | 0.178 |
| aime | 15 | 0 | 0 |
| imo | 20 | 0 | 0 |
| algebra | 18 | 5 | 0.278 |
| numbertheory | 8 | 0 | 0 |
| induction | 8 | 0 | 0 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 |
|---|---|---|---|---|---|---|---|---|---|
| solved | 59 | 72 | 77 | 79 | 79 | 79 | 79 | 79 | 79 |
| solve rate | 24.2% | 29.5% | 31.6% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 |
|---|---|---|---|---|---|---|---|---|---|---|
| solved | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| solve rate | 16.8% | 23.4% | 31.6% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 |
|---|---|---|---|---|---|---|---|---|---|---|
| solved | 62 | 74 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| solve rate | 25.4% | 30.3% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% | 32.4% |

## Stop reasons

| stop reason | problems |
|---|---|
| frontier_exhausted | 163 |
| proved | 79 |
| expansion_budget | 1 |
| wall_clock_budget | 1 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 7.31 | 2 | 12 | 256 | 1784 |
| nodes | 8.27 | 2 | 12 | 340 | 2019 |
| edges | 92.6 | 26 | 156 | 3328 | 22590 |
| lean_seconds | 8.06 | 1.33 | 12.5 | 300 | 1966 |
| wall_seconds | 8.31 | 1.86 | 12.5 | 300 | 2029 |
| duplicates | 28.2 | 6 | 50 | 1129 | 6892 |
| errors | 57 | 19 | 98 | 1860 | 13919 |
| timeouts | 0.0082 | 0 | 0 | 1 | 2 |
| repl_failures | 0.0082 | 0 | 0 | 2 | 2 |
| verification_seconds | 0.246 | 0 | 1.17 | 3.66 | 60 |

solved (79 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 1.44 | 1 | 2 | 6 | 114 |
| nodes | 2.84 | 2 | 5 | 10 | 224 |
| edges | 11.4 | 9 | 25 | 77 | 904 |
| lean_seconds | 0.564 | 0.199 | 1.78 | 3.5 | 44.6 |
| wall_seconds | 1.33 | 0.899 | 3.21 | 5.89 | 105 |
| duplicates | 2.82 | 2 | 6 | 27 | 223 |
| errors | 6.78 | 5 | 18 | 41 | 536 |
| timeouts | 0 | 0 | 0 | 0 | 0 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 0.76 | 0.595 | 1.52 | 3.66 | 60 |

unsolved (165 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 10.1 | 3 | 18 | 256 | 1670 |
| nodes | 10.9 | 3 | 18 | 340 | 1795 |
| edges | 131 | 39 | 234 | 3328 | 21686 |
| lean_seconds | 11.6 | 2.47 | 23 | 300 | 1922 |
| wall_seconds | 11.7 | 2.48 | 23.1 | 300 | 1924 |
| duplicates | 40.4 | 10 | 72 | 1129 | 6669 |
| errors | 81.1 | 27 | 164 | 1860 | 13383 |
| timeouts | 0.0121 | 0 | 0 | 1 | 2 |
| repl_failures | 0.0121 | 0 | 0 | 2 | 2 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| aesop | 1707 | 463 | 23.7% | 0.271 | 215 | 684 | 808 | 807 | 0 | 0 | 1 | 2 | 2 |
| field_simp | 1723 | 290 | 14.8% | 0.168 | 219 | 520 | 984 | 983 | 0 | 1 | 0 | 0 | 3 |
| simp_all | 1714 | 266 | 13.6% | 0.155 | 191 | 443 | 1080 | 1079 | 0 | 0 | 1 | 2 | 15 |
| nlinarith | 1712 | 247 | 12.6% | 0.144 | 10 | 48 | 1654 | 1654 | 0 | 0 | 0 | 5 | 6 |
| norm_num | 1744 | 213 | 10.9% | 0.122 | 78 | 1666 | 0 | 0 | 0 | 0 | 0 | 6 | 6 |
| ring_nf | 1720 | 175 | 8.9% | 0.102 | 438 | 1282 | 0 | 0 | 0 | 0 | 0 | 6 | 9 |
| simp | 1744 | 134 | 6.8% | 0.0767 | 174 | 264 | 1306 | 1306 | 0 | 0 | 0 | 0 | 1 |
| linarith | 1738 | 81.9 | 4.2% | 0.0471 | 21 | 18 | 1699 | 1699 | 0 | 0 | 0 | 18 | 19 |
| rfl | 1746 | 27.4 | 1.4% | 0.0157 | 5 | 30 | 1711 | 1710 | 0 | 1 | 0 | 5 | 5 |
| decide | 1784 | 25.8 | 1.3% | 0.0145 | 40 | 31 | 1713 | 1713 | 0 | 0 | 0 | 24 | 24 |
| constructor | 1749 | 14.2 | 0.7% | 0.00813 | 353 | 164 | 1232 | 1232 | 0 | 0 | 0 | 0 | 2 |
| intros | 1749 | 12 | 0.6% | 0.00689 | 19 | 1730 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| omega | 1760 | 8.31 | 0.4% | 0.00472 | 12 | 12 | 1736 | 1736 | 0 | 0 | 0 | 11 | 11 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 59 |
| 2 | 16 |
| 3 | 4 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | simp_all ⟶ norm_num |
| mathd_algebra_101 | constructor ⟶ nlinarith ⟶ nlinarith |
| mathd_algebra_35 | simp_all ⟶ norm_num |
| mathd_algebra_126 | constructor ⟶ linarith ⟶ linarith |
| amc12a_2021_p7 | ring_nf ⟶ nlinarith |
| mathd_algebra_245 | field_simp ⟶ linarith |
| mathd_algebra_43 | simp_all ⟶ linarith |
| mathd_algebra_110 | simp_all ⟶ ring_nf ⟶ norm_num |
| mathd_algebra_214 | simp_all ⟶ linarith |
| mathd_algebra_55 | field_simp ⟶ linarith |
| amc12b_2003_p9 | simp_all ⟶ linarith |
| algebra_2complexrootspoly_xsqp49eqxp7itxpn7i | ring_nf ⟶ simp ⟶ ring_nf |
| mathd_algebra_132 | simp_all ⟶ linarith |
| mathd_numbertheory_232 | simp_all ⟶ rfl |
| amc12a_2013_p7 | simp_all ⟶ linarith |
| mathd_algebra_159 | simp_all ⟶ linarith |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_algebra_67 | simp_all ⟶ norm_num |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| amc12a_2017_p2 | field_simp ⟶ linarith |
