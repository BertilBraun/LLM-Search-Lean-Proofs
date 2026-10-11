# Proof search: phase1_fewshot_search_qwen3.5-2b-base

Run `phase1_fewshot_search_qwen3.5-2b-base` on miniF2F-valid, git `ff395053726f7ee18aa3ea02ce0deeadcd4bf724`, config `experiments/configs/phase1_fewshot_search_qwen3.5-2b-base.toml` (copied as `config.toml`). Started 2026-10-11T19:10:45+00:00, 53.6 min wall, 46 CPUs, load average 79.8 at start.

**Solved 117/244 (48.0%).** Solved only with proofs of 2 or more steps: 40. Verification failures (bugs): 0. Proofs that also verify without the per-step heartbeat wrappers: 117/117. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 46 | 0.657 |
| mathd_numbertheory | 60 | 40 | 0.667 |
| amc12 | 45 | 13 | 0.289 |
| aime | 15 | 0 | 0 |
| imo | 20 | 0 | 0 |
| algebra | 18 | 13 | 0.722 |
| numbertheory | 8 | 2 | 0.25 |
| induction | 8 | 3 | 0.375 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 77 | 91 | 102 | 107 | 110 | 116 | 117 |
| solve rate | 31.6% | 37.3% | 41.8% | 43.9% | 45.1% | 47.5% | 48.0% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 40 | 55 | 60 | 74 | 91 | 97 | 106 | 108 | 111 | 115 | 117 |
| solve rate | 16.4% | 22.5% | 24.6% | 30.3% | 37.3% | 39.8% | 43.4% | 44.3% | 45.5% | 47.1% | 48.0% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 63 | 76 | 89 | 98 | 108 | 108 | 115 | 116 | 116 | 117 | 117 |
| solve rate | 25.8% | 31.1% | 36.5% | 40.2% | 44.3% | 44.3% | 47.1% | 47.5% | 47.5% | 48.0% | 48.0% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 117 |
| wall_clock_budget | 81 |
| expansion_budget | 34 |
| frontier_exhausted | 12 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 28.3 | 16.5 | 64 | 64 | 6910 |
| nodes | 61 | 37.5 | 150 | 231 | 14888 |
| edges | 649 | 356 | 1487 | 1653 | 158275 |
| lean_seconds | 74.8 | 31.1 | 210 | 464 | 18245 |
| wall_seconds | 291 | 150 | 605 | 609 | 70946 |
| duplicates | 124 | 64 | 303 | 485 | 30325 |
| errors | 478 | 265 | 1105 | 1271 | 116594 |
| timeouts | 0.615 | 0 | 2 | 16 | 150 |
| repl_failures | 0.16 | 0 | 0 | 38 | 39 |
| verification_seconds | 0.873 | 0 | 2.17 | 24.6 | 213 |

solved (117 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.13 | 1 | 6 | 34 | 366 |
| nodes | 10.1 | 3 | 25 | 104 | 1186 |
| edges | 64.6 | 13 | 162 | 852 | 7559 |
| lean_seconds | 7.78 | 0.788 | 16.9 | 243 | 911 |
| wall_seconds | 27.2 | 4.42 | 56.7 | 485 | 3179 |
| duplicates | 10.8 | 2 | 29 | 131 | 1260 |
| errors | 46.5 | 8 | 117 | 671 | 5444 |
| timeouts | 0.0342 | 0 | 0 | 1 | 4 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 1.82 | 1.05 | 3.78 | 24.6 | 213 |

unsolved (127 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 51.5 | 59 | 64 | 64 | 6544 |
| nodes | 108 | 109 | 162 | 231 | 13702 |
| edges | 1187 | 1342 | 1536 | 1653 | 150716 |
| lean_seconds | 136 | 116 | 252 | 464 | 17334 |
| wall_seconds | 534 | 601 | 607 | 609 | 67767 |
| duplicates | 229 | 232 | 351 | 485 | 29065 |
| errors | 875 | 978 | 1172 | 1271 | 111150 |
| timeouts | 1.15 | 0 | 3 | 16 | 146 |
| repl_failures | 0.307 | 0 | 0 | 38 | 39 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 70175 | 8569 | 47.0% | 0.122 | 8264 | 2168 | 58701 | 63103 | 0 | 112 | 5 | 38 | 0 |
| aesop | 5785 | 4187 | 23.0% | 0.724 | 1085 | 2916 | 1784 | 1739 | 0 | 34 | 11 | 2 | 3 |
| simp_all | 6839 | 1613 | 8.8% | 0.236 | 1834 | 2643 | 2362 | 2351 | 0 | 0 | 11 | 6 | 21 |
| nlinarith | 6833 | 1338 | 7.3% | 0.196 | 8 | 595 | 6230 | 6230 | 0 | 0 | 0 | 3 | 3 |
| field_simp | 6866 | 441 | 2.4% | 0.0642 | 369 | 955 | 5542 | 5540 | 0 | 0 | 2 | 0 | 4 |
| ring_nf | 6794 | 438 | 2.4% | 0.0645 | 996 | 5796 | 2 | 0 | 0 | 2 | 0 | 5 | 14 |
| linarith | 6861 | 438 | 2.4% | 0.0638 | 42 | 533 | 6286 | 6286 | 0 | 0 | 0 | 17 | 17 |
| norm_num | 6847 | 391 | 2.1% | 0.0571 | 168 | 6678 | 1 | 0 | 0 | 1 | 0 | 4 | 6 |
| simp | 6867 | 267 | 1.5% | 0.0389 | 665 | 467 | 5735 | 5733 | 0 | 0 | 2 | 0 | 2 |
| decide | 6910 | 266 | 1.5% | 0.0385 | 67 | 105 | 6738 | 6736 | 0 | 0 | 2 | 24 | 24 |
| intros | 6872 | 89.3 | 0.5% | 0.013 | 256 | 6616 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| rfl | 6869 | 77.3 | 0.4% | 0.0113 | 5 | 206 | 6658 | 6655 | 0 | 1 | 2 | 5 | 5 |
| constructor | 6872 | 65.2 | 0.4% | 0.00949 | 676 | 294 | 5902 | 5900 | 0 | 0 | 2 | 0 | 0 |
| omega | 6885 | 57.7 | 0.3% | 0.00838 | 209 | 353 | 6323 | 6321 | 0 | 0 | 2 | 13 | 14 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 77 |
| 2 | 17 |
| 3 | 11 |
| 4 | 4 |
| 5 | 1 |
| 6 | 1 |
| 8 | 1 |
| 10 | 1 |
| 13 | 2 |
| 16 | 2 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | have h : q - e = 12 := by<br>  rw [h₀, h₁]<br>  ring ⟶ simp_all |
| induction_sum2kp1npqsqm1 | ring_nf ⟶ have h : ∑ x in Finset.range n, (3 + x * 2) = (n + 1) ^ 2 - 1 := by<br>  induction n with<br>  \| zero => simp<br>  \| succ n ih =><br>    simp_all [Finset.sum_range_succ, Nat.cast_add, Nat.cast_mul, Nat.cast_one]<br>    <;> ring_nf at *<br>    <;> omega ⟶ omega |
| mathd_algebra_116 | have h₂ : (13 - Real.sqrt 131) / 4 = (13 - Real.sqrt 131) / 4 := by rfl ⟶ have h₃ : (13 - Real.sqrt 131) / 4 = (13 - Real.sqrt 131) / 4 := rfl<br>nlinarith [Real.sqrt_nonneg 131, Real.sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num), h₁] |
| amc12a_2008_p8 | have h₃ : y = 1 := by<br>  nlinarith ⟶ have h₃ : y = 1 := by<br>  nlinarith [sq_nonneg (y - 1)] ⟶ have h₃ : y = 1 := by<br>  nlinarith [sq_sqrt (show 0 ≤ 1 by norm_num)] ⟶ have h₃ : y = 1 := by<br>  nlinarith [sq_nonneg (y - 1), h₁] ⟶ ring_nf ⟶ have h₄ : 0 < Real.sqrt 2 := by<br>  exact Real.sqrt_pos.mpr (by norm_num) ⟶ have h₄ : 0 < √2 := by<br>  exact Real.sqrt_pos.mpr (by norm_num) ⟶ have h₄ : 0 < √2 := by positivity ⟶ have h₅ : √2 > 0 := by<br>  exact Real.sqrt_pos.mpr (by norm_num) ⟶ have h₁ : x ^ 3 = √2 * 2 := by<br>  nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num),<br>    sq_nonneg (x - √2),<br>    sq_nonneg (y - 1)]<br>exact h₁ |
| mathd_algebra_547 | have h₂ : (5 : ℝ) ^ 3 - 2 ^ 2 = 121 := by norm_num ⟶ have h : √(x ^ 3 - 2 ^ y) = 11 := by<br>  rw [h₀, h₁]<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>exact h |
| mathd_algebra_35 | simp_all ⟶ norm_num |
| mathd_algebra_245 | have h₁ : x ≠ 0 := h₀ ⟶ field_simp [h₀, h₁]<br>ring_nf<br><;> field_simp [h₀, h₁]<br><;> ring_nf<br><;> norm_num |
| mathd_algebra_28 | obtain ⟨x, hx⟩ := h₁<br>have h₂ : f x = 2 * x ^ 2 + 5 * x + c := h₀ x<br>rw [h₂] at hx ⟶ ring_nf at h₀ h₂ ⊢ ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ have h₁ : 2 - √2 ≥ 2 - x - 1 / (2 * x) := by<br>  have h₂ : 0 < x := hx<br>  field_simp [h₂.ne']<br>  rw [div_le_iff (by positivity)]<br>  nlinarith [sq_sqrt (by positivity : 0 ≤ (2 : ℝ)), sq_nonneg (x - Real.sqrt 2 / 2)]<br>exact h₁ |
| mathd_algebra_192 | simp_all [Complex.ext_iff, Complex.I_mul_I] ⟶ norm_num |
| mathd_algebra_110 | have h₂ : (2 - 2 * Complex.I) * (5 + 5 * Complex.I) = 20 := by<br>  ring_nf<br>  norm_num ⟶ simp_all |
| amc12a_2011_p18 | have h₁ : \|x + y\| + \|x - y\| = 2 := h₀ ⟶ ring_nf ⟶ cases' le_total 0 (x + y) with h h <;><br>cases' le_total 0 (x - y) with hh h <;><br>simp_all [abs_of_nonneg, abs_of_nonpos, sub_eq_add_neg]<br>all_goals<br>  nlinarith |
| mathd_algebra_433 | have h₁ : ∀ (x : ℝ), f x = 3 * √(2 * x - 7) - 8 := by<br>  intro x<br>  rw [h₀] ⟶ have h₂ : ∀ (x : ℝ), f x = 3 * Real.sqrt (2 * x - 7) - 8 := by<br>  simpa using h₀ ⟶ have h₃ : f 8 = 3 * Real.sqrt (2 * 8 - 7) - 8 := by<br>  simpa using h₁ 8 ⟶ have h₄ : (2 * 8 - 7 : ℝ) ≥ 0 := by norm_num ⟶ have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₄ : 2 * 8 - 7 ≥ 0 := by nlinarith ⟶ have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₄₁ : 2 * 8 - 7 ≥ 0 := by<br>  norm_num ⟶ have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₄ : 2 * 8 - 7 ≥ 0 := by<br>  norm_num ⟶ have h₄₁ : 2 * 8 - 7 ≥ 0 := by nlinarith ⟶ have h₄₁ : 2 * 8 - 7 ≥ 0 := by<br>  norm_num ⟶ have h₄₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₅ : Real.sqrt (2 * 8 - 7) = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>rw [h₅] at h₃<br>norm_num at h₄<br>norm_num at h₄ h₅<br>linarith |
| mathd_algebra_327 | simp_all ⟶ have h₁ : 5⁻¹ * \|9 + 2 * a\| < 1 := h₀ ⟶ simp_all ⟶ have h₁ : 5⁻¹ * \|9 + 2 * a\| < 1 := by simpa using h₁ ⟶ norm_num at h₁ ⟶ have h₁ : \|9 + 2 * a\| < 5 := by<br>  nlinarith ⟶ simp_all ⟶ have h₁ : \|9 + 2 * a\| < 5 := h₁<br>have h₂ : -7 < a := by<br>  linarith [abs_lt.mp h₁]<br>have h₃ : a < -2 := by<br>  linarith [abs_lt.mp h₁]<br>exact ⟨h₂, h₃⟩ |
| mathd_algebra_43 | simp_all ⟶ linarith |
| mathd_algebra_214 | simp_all ⟶ linarith |
| mathd_algebra_22 | simp [logb] ⟶ field_simp ⟶ linarith |
| amc12b_2003_p9 | simp_all ⟶ linarith |
| mathd_algebra_536 | field_simp [Nat.factorial] ⟶ ring_nf ⟶ have : √9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>rw [this]<br>norm_num |
| algebra_binomnegdiscrineq_10alt28asqp1 | have h₁ : a ≤ 28 * a ^ 2 + 1 / 10 := by<br>  nlinarith [sq_nonneg (a - 1), sq_nonneg (a - 1 / 14)] ⟶ have h₁ : a ≤ 28 * a ^ 2 + 1 / 10 := h₁ ⟶ norm_num at h₁ ⟶ have h₁ : a ≤ 28 * a ^ 2 + 1 / 10 := h₁ ⟶ have h₁ : 10 * a ≤ 28 * a ^ 2 + 1 := by<br>  nlinarith [sq_nonneg (a - 1), sq_nonneg (a - 1 / 7)] ⟶ linarith |
| mathd_algebra_132 | norm_num ⟶ field_simp [h₀, h₁] at h₂ ⟶ linarith |
| amc12a_2013_p7 | simp_all ⟶ linarith |
| algebra_sqineq_36azm9asqle36zsq | simp ⟶ ring_nf ⟶ have h₁ : a * z * 36 ≤ a ^ 2 * 9 + z ^ 2 * 36 := by<br>  nlinarith [sq_nonneg (a - 3 * z), sq_nonneg (a - 2 * z)] ⟶ linarith |
| algebra_2complexrootspoly_xsqp49eqxp7itxpn7i | field_simp [Complex.ext_iff]<br>ring_nf<br>norm_num ⟶ have h₁ : x.re * x.re - x.im * x.im = x.re ^ 2 - x.im ^ 2 := by ring ⟶ have h₂ := h₁.symm ⟶ have h₃ : (x ^ 2).re = x.re ^ 2 - x.im ^ 2 := by<br>  simp [Complex.ext_iff, pow_two]<br>  <;> ring_nf<br>  <;> linarith<br>have h₄ : (x ^ 2).im = x.re * x.im * 2 := by<br>  simp [Complex.ext_iff, pow_two]<br>  <;> ring_nf<br>  <;> linarith<br>exact ⟨h₃, h₄⟩ |
| numbertheory_nckeqnm1ckpnm1ckm1 | aesop ⟶ cases k ⟶ cases n<br>all_goals<br>  simp_all [Nat.choose_succ_succ, Nat.succ_eq_add_one] ⟶ cases n<br>all_goals simp_all [Nat.succ_eq_add_one, Nat.choose_succ_succ, Nat.add_comm, Nat.add_left_comm, Nat.add_assoc] |
| mathd_numbertheory_22 | have h₂ : (10 * b + 6).sqrt * (10 * b + 6).sqrt = 10 * b + 6 := by<br>  rw [h₁] ⟶ interval_cases b <;> norm_num at h₀ h₁ h₂ ⊢ |
| mathd_algebra_493 | simp_all ⟶ have h₁ : f 4 = 4 ^ 2 - 4 * √4 + 1 := by<br>  simp_all [h₀] ⟶ ring_nf ⟶ have h₂ : f 4 = 4 ^ 2 - 4 * √4 + 1 := by<br>  norm_num [h₀] ⟶ have h₃ : √4 = 2 := by<br>  norm_num [Real.sqrt_eq_iff_sq_eq] ⟶ simp ⟶ have h₁ : (2 : ℝ) ≠ 0 := by norm_num ⟶ have h₁ : (2 : ℝ) ≠ 0 := by norm_num ⟶ ring_nf ⟶ have h₁ : √4 = 2 := by rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ have h₄ : √4 = 2 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ have h₅ : ∀ (x : ℝ), Real.sqrt x ≥ 0 := by<br>  intro x<br>  exact Real.sqrt_nonneg x ⟶ norm_num at *<br>nlinarith [Real.sqrt_nonneg 4, Real.sqrt_nonneg (17 - Real.sqrt 4 * 4),<br>  Real.sq_sqrt (show 0 ≤ 4 by norm_num),<br>  Real.sq_sqrt (show 0 ≤ (17 - Real.sqrt 4 * 4) by<br>    nlinarith [Real.sqrt_nonneg 4])] |
| mathd_numbertheory_232 | have h₃ : x = 3⁻¹ := h₀<br>have h₄ : y = 5⁻¹ := h₁<br>have h₅ : z = (x + y)⁻¹ := h₂<br>simp at h₅ ⟶ simp_all ⟶ rfl |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_algebra_159 | have h := h₁ ⟶ have h₁ : ∀ x, f x = 3 * x ^ 4 - 7 * x ^ 3 + 2 * x ^ 2 - b * x + 1 := fun x ↦ h₀ x<br>specialize h₁ (1)<br>linarith |
| mathd_algebra_11 | have h₃ : a - 2 * b ≠ 0 := by<br>  intro h₄<br>  apply h₁<br>  linarith<br>field_simp [h₃] at h₂ ⊢ ⟶ ring_nf ⟶ have h : a ≠ b := h₀ ⟶ field_simp at * ⟶ have h₃ : a - 2 * b ≠ 0 := by<br>  intro h₃<br>  contradiction ⟶ have h₁ : a^6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h₁ : a^6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h₁ : a ^ 6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h₁ : a ^ 6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h₄ : a ^ 6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h₄ : a ^ 6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h₄ : a^6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h : a ^ 6 + 1 ≠ 0 := by<br>  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ have h₄ : a - b ≠ 0 := by<br>  intro h₄<br>  apply h₀<br>  linarith ⟶ have h₅ : a + b * 11 = 2 * (a - b) := by<br>  nlinarith [h₀, h₁, h₂] ⟶ simp_all |
| mathd_algebra_437 | have h₄ : (x + y) ^ 3 = -45 - 101 := by<br>  nlinarith [sq_nonneg (x + y), sq_nonneg (x - y)] ⟶ have h₅ : (x + y) ^ 3 = -146 := by<br>  nlinarith ⟶ have h₆ : x + y = -4 := by<br>  nlinarith [sq_nonneg (x + y), h₀, h₁, h₂]<br>nlinarith |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | have h₂ : a * Complex.I + b * Complex.I = -2 ⟶ simp_all [Complex.ext_iff]<br><;> ring_nf at *<br><;> norm_num<br><;> linarith ⟶ simp_all |
| mathd_algebra_67 | have h : g (f (-1)) = 2 := by<br>  rw [h₀, h₁]<br>  norm_num ⟶ linarith |
| mathd_numbertheory_326 | have h₁ : n ≠ 0 := by<br>  intro hn<br>  rw [hn] at h₀<br>  norm_num at h₀ ⟶ ring_nf ⟶ have n_pos : 0 < n := by<br>  nlinarith [sq_nonneg (n - 1), sq_nonneg (n + 1)]<br>nlinarith [sq_nonneg (n - 1), sq_nonneg (n + 1)] |
| mathd_algebra_89 | field_simp [h₀]<br>ring ⟶ have h₁ : b ≠ 0 := h₀ ⟶ simp_all ⟶ have h₂ : b ≠ 0 := h₁<br>have h₃ : b ^ 6 * 3136 = (b ^ 2 * 4) ^ 3 * 49 := by<br>  have h₄ : b ^ 6 * 3136 = (b ^ 6) * 3136 := by ring<br>  rw [h₄]<br>  have h₅ : (b ^ 2 * 4) ^ 3 * 49 = (b ^ 2) ^ 3 * 4 ^ 3 * 49 := by ring<br>  rw [h₅]<br>  have h₆ : (b ^ 2) ^ 3 * 4 ^ 3 * 49 = (b ^ 2 * 4) ^ 3 * 49 := by<br>    ring<br>  rw [h₆]<br>  ring<br>exact h₃ |
| numbertheory_2dvd4expn | cases n ⟶ omega ⟶ omega |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| mathd_algebra_181 | have h₂ : (n + 5) / (n - 3) = 2 := h₁<br>field_simp [h₀] at h₂ ⟶ ring_nf at h₁ h₂ ⊢ ⟶ have h₃ : n ≠ 3 := h₀<br>field_simp [h₃] at h₁ h₂ ⊢ ⟶ norm_num at h₀ h₁ h₂ ⟶ have h₄ : (n + 5) / (-3 + n) = 2 := h₁<br>have h₅ : n ≠ 3 := h₃<br>have h₆ : -3 + n ≠ 0 := by<br>  intro h<br>  apply h₅<br>  linarith<br>have h₇ : (n + 5) / (-3 + n) = 2 := h₁<br>have h₈ : n = 11 := by<br>  field_simp [h₆] at h₇<br>  linarith<br>exact h₈ |
| amc12a_2016_p3 | field_simp ⟶ norm_num at h₀ ⟶ norm_num ⟶ simp_all ⟶ have h₁ : ∀ (x y : ℝ), ¬y = 0 → f x y = x - y * ↑⌊x / y⌋ := h₀ ⟶ field_simp ⟶ simp_all [Int.floor_eq_iff]<br><;> norm_num ⟶ have h : ∀ (x y : ℝ), ¬y = 0 → f x y = x - y * ↑⌊x / y⌋ := h₁ ⟶ simp_all ⟶ have h : ∀ (x y : ℝ), ¬y = 0 → f x y = x - y * ↑⌊x / y⌋ := h ⟶ field_simp ⟶ have h₁ : (15 + 2 * ⌊-15 / 16⌋ * 8) * 40 = -40 := by<br>  norm_num [h] ⟶ norm_num<br><;> ring_nf<br><;> norm_cast<br><;> linarith |
