# Automation sweep: tactic ablations (pilots)

Pilot runs on miniF2F-valid with the row-0 search settings (256 expansions, 300 s, depth 16, 10 s per tactic).
The leave-one-out runs re-search only the 79 theorems solved by `pilot_automation_all_tactics` (all 15 tactics, git
b1ff152): removing a tactic only shrinks the reachable states, so it cannot add solves among the
theorems whose frontier was exhausted.

## Full miniF2F-valid

| run | git | tactics | solved | Lean s total | Lean s per expansion |
|---|---|---|---|---|---|
| pilot_automation_all_tactics | b1ff152 | decide, omega, positivity, intros, constructor, rfl, tauto, simp, field_simp, norm_num, linarith, ring_nf, simp_all, nlinarith, aesop | 79/244 | 2306 | 1.296 |
| pilot_automation_13_tactics | 0f43fd8 | decide, omega, intros, constructor, rfl, simp, field_simp, norm_num, linarith, ring_nf, simp_all, nlinarith, aesop | 79/244 | 1977 | 1.106 |
| pilot_automation_7_tactics | dc1e528 | omega, constructor, rfl, field_simp, ring_nf, simp_all, nlinarith | 79/244 | 565 | 0.461 |

## Leave-one-out on the solved theorems

| run | solved | Lean s total | Lean s per expansion | lost theorems |
|---|---|---|---|---|
| minimal_sweep | 77/79 | 32.7 | 0.300 | mathd_algebra_101, mathd_algebra_126 |
| minimal_sweep_constructor | 79/79 | 32.9 | 0.291 | — |
| without_aesop | 79/79 | 41.6 | 0.368 | — |
| without_constructor | 79/79 | 47.6 | 0.425 | — |
| without_decide | 79/79 | 48.5 | 0.426 | — |
| without_field_simp | 77/79 | 50.4 | 0.410 | amc12a_2017_p2, mathd_algebra_245 |
| without_intros | 79/79 | 47.9 | 0.420 | — |
| without_linarith | 79/79 | 51.7 | 0.454 | — |
| without_nlinarith | 74/79 | 45.1 | 0.383 | amc12_2001_p2, amc12a_2021_p7, mathd_algebra_101, mathd_algebra_37, mathd_numbertheory_48 |
| without_norm_num | 79/79 | 47.4 | 0.405 | — |
| without_omega | 70/79 | 70.0 | 0.547 | mathd_algebra_123, mathd_numbertheory_110, mathd_numbertheory_284, mathd_numbertheory_301, mathd_numbertheory_33, mathd_numbertheory_335, mathd_numbertheory_370, mathd_numbertheory_458, mathd_numbertheory_92 |
| without_positivity | 79/79 | 48.6 | 0.426 | — |
| without_rfl | 79/79 | 48.6 | 0.426 | — |
| without_ring_nf | 71/79 | 44.6 | 0.406 | algebra_2complexrootspoly_xsqp49eqxp7itxpn7i, algebra_2rootsintpoly_am10tap11eqasqpam110, algebra_2rootspoly_apatapbeq2asqp2ab, algebra_3rootspoly_amdtamctambeqnasqmbpctapcbtdpasqmbpctapcbta, algebra_manipexpr_2erprsqpesqeqnrpnesq, amc12a_2021_p7, mathd_algebra_110, mathd_algebra_182 |
| without_simp | 79/79 | 44.1 | 0.394 | — |
| without_simp_all | 78/79 | 39.8 | 0.362 | amc12a_2003_p1 |
| without_tauto | 79/79 | 47.5 | 0.417 | — |
| without_tauto_positivity | 79/79 | 47.6 | 0.418 | — |
| without_tauto_positivity_rfl | 76/79 | 60.1 | 0.501 | amc12a_2003_p1, mathd_numbertheory_232, mathd_numbertheory_668 |
