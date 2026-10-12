# Proof search: phase3_astar_v0

Run `phase3_astar_v0` on miniF2F-valid, git `10c7ff97a0318a8923b118c70b6e454581685721`, config `experiments/configs/phase3_astar_v0.toml` (copied as `config.toml`). Started 2026-10-12T03:08:36+00:00, 24.2 min wall, 46 CPUs, load average 25.3 at start.

**Solved 155/244 (63.5%).** Solved only with proofs of 2 or more steps: 71. Verification failures (bugs): 2. Proofs that also verify without the per-step heartbeat wrappers: 155/155. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 58 | 0.829 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 19 | 0.422 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 2 | 0.1 |
| algebra | 18 | 15 | 0.833 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 6 | 0.75 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 84 | 119 | 131 | 139 | 146 | 152 | 155 |
| solve rate | 34.4% | 48.8% | 53.7% | 57.0% | 59.8% | 62.3% | 63.5% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 33 | 55 | 80 | 105 | 123 | 127 | 139 | 147 | 148 | 151 | 155 |
| solve rate | 13.5% | 22.5% | 32.8% | 43.0% | 50.4% | 52.0% | 57.0% | 60.2% | 60.7% | 61.9% | 63.5% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 67 | 93 | 115 | 125 | 132 | 137 | 147 | 149 | 152 | 153 | 155 |
| solve rate | 27.5% | 38.1% | 47.1% | 51.2% | 54.1% | 56.1% | 60.2% | 61.1% | 62.3% | 62.7% | 63.5% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 155 |
| expansion_budget | 62 |
| wall_clock_budget | 24 |
| frontier_exhausted | 3 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 22.1 | 3 | 64 | 64 | 5402 |
| nodes | 85.1 | 12 | 264 | 410 | 20755 |
| edges | 511 | 57 | 1546 | 1675 | 124791 |
| lean_seconds | 115 | 8.1 | 411 | 596 | 28004 |
| wall_seconds | 175 | 17.8 | 598 | 613 | 42699 |
| duplicates | 124 | 13 | 388 | 620 | 30291 |
| errors | 282 | 32 | 845 | 1080 | 68861 |
| timeouts | 1.68 | 0 | 5 | 37 | 411 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 1.66 | 0.382 | 3.43 | 46.8 | 404 |

solved (155 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.8 | 1 | 9 | 58 | 589 |
| nodes | 14 | 6 | 34 | 132 | 2177 |
| edges | 75.6 | 19 | 166 | 1303 | 11725 |
| lean_seconds | 16.6 | 1.46 | 32.7 | 526 | 2567 |
| wall_seconds | 28.1 | 4.67 | 61 | 576 | 4348 |
| duplicates | 17 | 3 | 35 | 357 | 2638 |
| errors | 43.2 | 10 | 93 | 795 | 6692 |
| timeouts | 0.29 | 0 | 0 | 21 | 45 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.61 | 1.21 | 4.98 | 46.8 | 404 |

unsolved (89 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 54.1 | 64 | 64 | 64 | 4813 |
| nodes | 209 | 218 | 325 | 410 | 18578 |
| edges | 1270 | 1441 | 1615 | 1675 | 113066 |
| lean_seconds | 286 | 263 | 520 | 596 | 25438 |
| wall_seconds | 431 | 432 | 603 | 613 | 38351 |
| duplicates | 311 | 343 | 439 | 620 | 27653 |
| errors | 699 | 748 | 987 | 1080 | 62169 |
| timeouts | 4.11 | 1 | 13 | 37 | 366 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 55576 | 19805 | 70.8% | 0.356 | 15228 | 9242 | 26388 | 25991 | 2 | 396 | 0 | 58 | 0 |
| aesop | 5103 | 2593 | 9.3% | 0.508 | 716 | 2913 | 1474 | 1468 | 0 | 6 | 0 | 5 | 12 |
| simp_all | 5313 | 1703 | 6.1% | 0.321 | 1400 | 2047 | 1866 | 1866 | 0 | 0 | 0 | 3 | 17 |
| nlinarith | 5292 | 957 | 3.4% | 0.181 | 6 | 23 | 5263 | 5262 | 0 | 1 | 0 | 4 | 4 |
| field_simp | 5319 | 551 | 2.0% | 0.104 | 487 | 874 | 3958 | 3957 | 0 | 1 | 0 | 0 | 3 |
| decide | 5402 | 486 | 1.7% | 0.09 | 46 | 4 | 5352 | 5352 | 0 | 0 | 0 | 24 | 28 |
| ring_nf | 5306 | 458 | 1.6% | 0.0864 | 1144 | 4160 | 2 | 0 | 0 | 2 | 0 | 5 | 9 |
| norm_num | 5315 | 446 | 1.6% | 0.084 | 154 | 5159 | 2 | 0 | 0 | 2 | 0 | 6 | 7 |
| linarith | 5351 | 377 | 1.3% | 0.0705 | 32 | 22 | 5297 | 5297 | 0 | 0 | 0 | 31 | 31 |
| simp | 5358 | 342 | 1.2% | 0.0639 | 593 | 451 | 4314 | 4314 | 0 | 0 | 0 | 1 | 3 |
| rfl | 5354 | 95.2 | 0.3% | 0.0178 | 6 | 13 | 5335 | 5334 | 0 | 1 | 0 | 4 | 4 |
| constructor | 5362 | 79.5 | 0.3% | 0.0148 | 595 | 71 | 4696 | 4696 | 0 | 0 | 0 | 0 | 5 |
| omega | 5378 | 50 | 0.2% | 0.0093 | 38 | 16 | 5324 | 5324 | 0 | 0 | 0 | 16 | 16 |
| intros | 5362 | 47.5 | 0.2% | 0.00887 | 66 | 5296 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 84 |
| 2 | 38 |
| 3 | 22 |
| 4 | 5 |
| 5 | 3 |
| 6 | 3 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | aesop ⟶ norm_num |
| mathd_algebra_547 | subst h₀; subst h₁; norm_num ⟶ rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num |
| induction_divisibility_3divnto3m2n | have h : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases h with (h \| h \| h) <;><br>simp [h, Nat.dvd_iff_mod_eq_zero, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_eq_of_lt] |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_numbertheory_64 | constructor ⟶ decide ⟶ ·<br>  intro x hx<br>  simp [Nat.ModEq] at hx<br>  omega |
| mathd_algebra_116 | simp_all only [sq, mul_one, mul_add, mul_sub, mul_comm, mul_left_comm, mul_right_comm] ⟶ nlinarith [Real.sq_sqrt (show 0 ≤ 131 by norm_num)] |
| mathd_algebra_28 | aesop ⟶ nlinarith [sq_nonneg (w + 5 / 4)] |
| mathd_algebra_433 | have h₁ : f 8 = 1 := by<br>  rw [h₀]<br>  have h₂ : sqrt (2 * (8 : ℝ) - 7) = 3 := by<br>    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  rw [h₂]<br>  norm_num ⟶ linarith |
| mathd_numbertheory_32 | have h₁ : S = Finset.filter (fun n ↦ n ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀] ⟶ aesop |
| mathd_numbertheory_780 | rcases h₁ with ⟨h₁, h₄⟩ ⟶ interval_cases m <;> omega |
| mathd_algebra_245 | field_simp [h₀, mul_comm] ⟶ linarith |
| mathd_algebra_35 | simp_all ⟶ norm_num |
| mathd_algebra_73 | apply mul_left_cancel₀ (sub_ne_zero.mpr h₁) ⟶ ring_nf ⟶ linear_combination h₀ |
| mathd_numbertheory_35 | have h₁ : (∑ k in S, k) = 24 := by<br>  have h₂ := h₀ 196<br>  have h₃ := h₀ 21<br>  have h₄ := h₀ 14<br>  have h₅ := h₀ 7<br>  have h₆ := h₀ 3<br>  have h₇ := h₀ 2<br>  have h₈ := h₀ 1<br>  norm_num at *<br>  <;><br>  (try omega) <;><br>  (try<br>    {<br>      simp_all [Finset.sum_eq_multiset_sum]<br>      <;> norm_num<br>      <;> omega<br>    }) <;><br>  (try<br>    {<br>      norm_num at *<br>      <;> omega<br>    })<br>  <;><br>  (try<br>    {<br>      omega<br>    })<br>  <;><br>  (try<br>    {<br>      aesop<br>    }) ⟶ omega |
| mathd_algebra_192 | simp_all ⟶ norm_num [Complex.ext_iff, pow_two] |
| mathd_algebra_480 | have h_pi_pos : (0 : ℝ) ≤ Real.pi ∧ Real.pi < 4 := by<br>  have h_pos : 0 < Real.pi := Real.pi_pos<br>  have h_bound : Real.pi < 4 := by<br>    have := Real.pi_gt_31415<br>    have := Real.pi_lt_31416<br>    norm_num at *<br>    <;> linarith<br>  constructor<br>  · linarith<br>  · linarith ⟶ simp_all |
| mathd_numbertheory_257 | rcases h₀ with ⟨h₀_left, h₀_right⟩ ⟶ interval_cases x <;> norm_num [Finset.sum_range_succ] at h₁<br><;> omega |
| mathd_algebra_110 | simp_all ⟶ ring_nf<br><;> simp [Complex.ext_iff]<br><;> norm_num |
| mathd_algebra_140 | have h2 := h₁ 1 ⟶ aesop ⟶ nlinarith [h₁ 0, h₁ 1, h₁ 2, h₁ 3, h₁ 4, h₁ 5, h₁ 6, h₁ 7, h₁ 8, h₁ 9] |
| amc12a_2009_p9 | simp_all ⟶ have h₂ := h₀ (-3) ⟶ have h₃ := h₀ 0 ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1, h₀ 2] |
| mathd_algebra_405 | have h₁ : S = Finset.filter (fun x => 0 < x ∧ x^2 + 4*x + 4 < 20) (Finset.range 21) := by<br>  ext x<br>  simp [h₀, Finset.mem_filter]<br>  <;> omega ⟶ aesop |
| mathd_algebra_13 | aesop ⟶ ·<br>  have h₁ := h₀ 4 (by norm_num) (by norm_num)<br>  have h₂ := h₀ 6 (by norm_num) (by norm_num)<br>  norm_num at h₁ h₂<br>  linarith ⟶ {<br>  have h₁ := h₀ 4<br>  have h₂ := h₀ 0<br>  have h₃ := h₀ 3<br>  have h₄ := h₀ 5<br>  norm_num at h₁ h₂ h₃ h₄<br>  all_goals linarith<br>} |
| amc12a_2015_p10 | have h₃ : x ≤ 80 := by<br>  nlinarith ⟶ have h₄ : y ≤ 80 := by nlinarith ⟶ interval_cases y <;> try {<br>  omega<br>} <;> try {<br>  interval_cases x <;> omega<br>} |
| amc12b_2002_p6 | constructor ⟶ ·<br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  simp at h₂ h₃<br>  nlinarith [sq_pos_of_ne_zero h₀.1, sq_pos_of_ne_zero h₀.2, sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.1), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.2)] ⟶ ·<br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  have h₅ := h₁ 2<br>  have h₆ := h₁ (-2)<br>  have h₇ := h₁ (a / 2)<br>  have h₈ := h₁ (-a / 2)<br>  field_simp [h₀.1, h₀.2] at h₂ h₃ h₄ h₅ h₆ h₇ h₈<br>  linarith [h₂, h₃, h₄, h₅, h₆, h₇, h₈] |
| aime_1984_p15 | ring_nf at * ⟶ linarith |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | aesop ⟶ norm_num ⟶ have h₁ : (2 : ℝ) ≤ 2 - Real.sqrt 2 + x⁻¹ * (1 / 2) + x := by<br>  have h₂ : 0 < Real.sqrt 2 := by norm_num<br>  have h₃ : 0 < x := by linarith<br>  have h₄ : 0 < x ^ 2 := by positivity<br>  have h₅ : 0 < x ^ 3 := by positivity<br>  have h₆ : 0 < x ^ 4 := by positivity<br>  field_simp<br>  rw [le_div_iff (by positivity)]<br>  nlinarith [Real.sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - 1),<br>    sq_nonneg (x - Real.sqrt 2 / 2), sq_nonneg (x - 1 + Real.sqrt 2 / 2)] ⟶ linarith |
| mathd_algebra_43 | simp_all only [h₀, mul_comm] ⟶ linarith |
| amc12b_2004_p3 | have h1 : 2 ^ x * 3 ^ y = 1296 := h₀ ⟶ have h2 : x ≤ 10 := by<br>  by_contra h<br>  push_neg at h<br>  have h3 : x ≥ 11 := by omega<br>  have h4 : 2 ^ x ≥ 2 ^ 11 := by<br>    apply Nat.pow_le_pow_of_le_right (show 0 < 2 by norm_num)<br>    <;> omega<br>  have h5 : 3 ^ y ≥ 1 := by<br>    apply Nat.one_le_pow<br>    norm_num<br>  have h6 : 2 ^ x * 3 ^ y ≥ 2 ^ 11 * 1 := by<br>    nlinarith<br>  have h7 : 2 ^ 11 * 1 = 2048 := by norm_num<br>  have h8 : 2 ^ x * 3 ^ y ≥ 2048 := by nlinarith<br>  have h9 : 2 ^ x * 3 ^ y = 1296 := h1<br>  linarith ⟶ have h3 : y ≤ 15 := by<br>  by_contra h<br>  have h4 : y ≥ 16 := by omega<br>  have h5 : 3 ^ y ≥ 3 ^ 16 := by exact pow_le_pow_right (by norm_num) h4<br>  have h6 : 2 ^ x * 3 ^ y ≥ 2 ^ 0 * 3 ^ 16 := by<br>    have h7 : 2 ^ x ≥ 2 ^ 0 := by<br>      apply pow_le_pow_right<br>      norm_num<br>      all_goals omega<br>    nlinarith<br>  norm_num at h1<br>  all_goals nlinarith ⟶ interval_cases x <;> interval_cases y <;> simp_all |
| mathd_algebra_55 | simp_all only [sub_eq_add_neg, add_assoc, add_left_comm, add_right_comm] ⟶ norm_num |
| mathd_algebra_214 | simp_all only [sq, mul_add, mul_one, mul_sub, mul_comm, mul_left_comm, mul_assoc] ⟶ linarith |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | rw [dvd_iff_exists_eq_mul_left] ⟶ use x^2 + y^2 + z^2 - x * y - y * z - z * x ⟶ linarith |
| amc12a_2013_p8 | have h₄ : x * y = 2 := by<br>  field_simp [h₀, h₁, h₂, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₃<br>  have h₅ : x * y - 2 = 0 := by<br>    apply mul_left_cancel₀ (sub_ne_zero.mpr h₂)<br>    nlinarith<br>  linarith ⟶ linarith |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_234 | field_simp at h₀ ⊢ ⟶ nlinarith [h₀, sq_nonneg (3 * d), sq_nonneg (5 * d), sq_nonneg (3 * d - 5 * d)] |
| mathd_algebra_393 | simp_all ⟶ have h1 : σ 2 = 33 := by<br>  rw [h₀]<br>  norm_num ⟶ simp_all ⟶ have h2 : σ 2 = 33 := by<br>  rw [h₀]<br>  norm_num ⟶ rw [show 33 = σ 2 by linarith [h2]] ⟶ simp |
| mathd_algebra_536 | have h_main : (Nat.factorial 3 : ℝ) * ((2 : ℝ) ^ 3 + Real.sqrt (9 : ℝ)) / 2 = 33 := by<br>  have h₁ : (Nat.factorial 3 : ℝ) = (6 : ℝ) := by<br>    norm_num [Nat.factorial]<br>    <;><br>    simp_all [Nat.factorial]<br>    <;><br>    norm_num<br>    <;><br>    linarith<br>  have h₂ : (Real.sqrt (9 : ℝ) : ℝ) = (3 : ℝ) := by<br>    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  rw [h₁, h₂]<br>  <;> ring_nf<br>  <;> norm_num<br>  <;><br>  linarith ⟶ linarith |
| amc12b_2003_p17 | field_simp ⟶ simp [Real.log_mul, h₀.1.ne', h₀.2.ne', Real.log_pow, h₀.1.ne', h₀.2.ne'] at h₁ h₂ ⊢ ⟶ linarith |
| mathd_numbertheory_22 | have h₂ : b ≤ 9 := by linarith ⟶ interval_cases b <;> norm_num at h₁ <;> omega |
| amc12b_2003_p9 | simp only [h₀, sub_eq_add_neg, add_assoc] at h₁ ⊢ ⟶ linarith |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| amc12_2000_p11 | have h₂ : a / b + b / a - a * b = 2 := by<br>  have h₃ : a / b + b / a - a * b = 2 := by<br>    have h₄ : a ≠ 0 := h₀.1<br>    have h₅ : b ≠ 0 := h₀.2<br>    field_simp [h₄, h₅]<br>    nlinarith [h₁, mul_self_nonneg (a - b)]<br>  exact h₃ ⟶ linarith |
| mathd_algebra_132 | field_simp ⟶ simp_all ⟶ linarith |
| amc12a_2013_p7 | simp_all ⟶ linarith |
| mathd_algebra_493 | have h₁ : f 4 = 9 := by<br>  rw [h₀ 4]<br>  have h₁ : Real.sqrt 4 = 2 := by<br>    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  rw [h₁]<br>  norm_num ⟶ have h₂ : f (f 4) = 70 := by<br>  rw [h₁]<br>  have h₃ : f 9 = 9 ^ 2 - 4 * Real.sqrt 9 + 1 := by<br>    apply h₀<br>  rw [h₃]<br>  have h₄ : Real.sqrt 9 = 3 := by<br>    norm_num [Real.sqrt_eq_iff_sq_eq]<br>  rw [h₄]<br>  norm_num ⟶ linarith |
| mathd_algebra_151 | have h1 : 27 < 1001 := by norm_num ⟶ have h2 : √27 > 5 := by<br>  have h2 : (5 : ℝ) < √27 := by<br>    apply Real.lt_sqrt_of_sq_lt<br>    norm_num<br>  linarith ⟶ have h3 : Real.sqrt 26 < 6 := by<br>  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show (0 : ℝ) ≤ 26 by norm_num)] ⟶ have h4 : ⌈(Real.sqrt 27 : ℝ)⌉ = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 by norm_num)] ⟶ have h5 : ⌊Real.sqrt 26⌋ = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ (26 : ℝ) by norm_num)] ⟶ omega |
| algebra_sqineq_4bap1lt4bsqpap1sq | ring_nf ⟶ nlinarith [sq_nonneg (b - (a + 1) / 2)] |
| mathd_algebra_131 | simp_all ⟶ have h₄ : a - 1 ≠ 0 := by<br>  by_contra h<br>  have eq1 : a = 1 := by linarith<br>  rw [eq1] at h₁<br>  nlinarith ⟶ have h₅ : b - 1 ≠ 0 := by<br>  by_contra h<br>  have h₆ : b = 1 := by linarith<br>  rw [h₆] at h₂<br>  nlinarith ⟶ field_simp ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₃), sq_pos_of_ne_zero (sub_ne_zero.mpr h₄), sq_pos_of_ne_zero (sub_ne_zero.mpr h₅)] |
| mathd_numbertheory_232 | norm_num [h₀, h₁, h₂] at h₂ ⊢ ⟶ rfl |
| mathd_algebra_410 | aesop ⟶ nlinarith [sq_nonneg (x - 3)] |
| mathd_algebra_77 | simp_all ⟶ constructor ⟶ all_goals<br>  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)<br>  nlinarith |
| mathd_numbertheory_690 | constructor ⟶ decide ⟶ ·<br>  intro a<br>  rintro ⟨ha_pos, ha_mod2, ha_mod5, ha_mod7, ha_mod9⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases a <;> norm_num [Nat.ModEq] at ha_mod2 ha_mod5 ha_mod7 ha_mod9 <;> omega |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_algebra_159 | norm_num [h₀] at h₁ ⟶ linarith |
| mathd_algebra_11 | have h₄ : a - 2 * b ≠ 0 := by<br>  intro h₅<br>  apply h₁<br>  linarith ⟶ have h₅ : a - b ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ have h₆ : (a + 11 * b) / (a - b) = 2 := by<br>  field_simp [h₄, h₅] at h₂ ⊢<br>  nlinarith ⟶ linarith |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all ⟶ simp_all [Complex.ext_iff, Complex.I_mul_I] ⟶ linarith |
| mathd_algebra_67 | simp_all ⟶ norm_num |
| mathd_algebra_437 | have h₄ : n = -4 := by<br>  have h₅ : (x : ℝ) < (n : ℝ) := by exact_mod_cast h₂<br>  have h₆ : (n : ℝ) < (y : ℝ) := by exact_mod_cast h₃<br>  have h₇ : (x : ℝ) ^ 3 = -45 := by norm_num [h₀]<br>  have h₈ : (y : ℝ) ^ 3 = -101 := by norm_num [h₁]<br>  have h₉ : (n : ℝ) = -4 := by<br>    nlinarith [pow_two_nonneg ((x - 3) * (x + 3)), pow_two_nonneg (y - 4), pow_two_nonneg (y + 4),<br>      pow_two_nonneg ((x + 4 : ℝ) * (x - 4 : ℝ)), pow_two_nonneg (y - 5 : ℝ), pow_two_nonneg (y + 5 : ℝ)]<br>  exact_mod_cast h₉ ⟶ omega |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | refine' ⟨_, _⟩ ⟶ ring_nf at h₀ h₁ ⊢ ⟶ all_goals<br>  apply Eq.symm<br>  apply Eq.symm<br>  ring_nf at h₀ h₁ ⊢<br>  simp_all [Complex.ext_iff]<br>  constructor <;> nlinarith |
| aime_1991_p1 | have h3 : x ≤ 71 := by<br>  nlinarith ⟶ interval_cases x <;> try {<br>  omega<br>} ⟶ all_goals nlinarith |
| mathd_numbertheory_326 | ring_nf at h₀ ⟶ have h : n^3 + (-n) = 720 := by linarith ⟶ have h₁ : n + 1 = 10 := by<br>  nlinarith [sq_nonneg (n - 10), sq_nonneg (n + 1), sq_nonneg (n ^ 2 - 100), sq_nonneg (n ^ 2 + 100)] ⟶ omega |
| imo_1974_p5 | aesop ⟶ case left =><br>  apply lt_of_sub_pos<br>  field_simp<br>  ring_nf<br>  nlinarith [mul_pos left left_1, mul_pos left left_2, mul_pos right left_1, mul_pos right left_2] ⟶ ·<br>  have h₀ : 0 < a + b + d := by linarith<br>  have h₁ : 0 < a + b + c := by linarith<br>  have h₂ : 0 < b + c + d := by linarith<br>  have h₃ : 0 < a + c + d := by linarith<br>  have h₄ : 0 < a * b := by positivity<br>  have h₅ : 0 < a * c := by positivity<br>  have h₆ : 0 < a * d := by positivity<br>  have h₇ : 0 < b * c := by positivity<br>  have h₈ : 0 < b * d := by positivity<br>  have h₉ : 0 < c * d := by positivity<br>  field_simp<br>  rw [← sub_pos]<br>  field_simp<br>  ring_nf<br>  nlinarith |
| mathd_algebra_323 | simp ⟶ have h₁ := h 3 ⟶ norm_num at h₁ ⟶ have h₂ : (σ.symm 19) = (3 : ℝ) := by<br>  rw [show 19 = σ 3 by linarith [h₁]]<br>  simp [← h]<br>  <;> norm_num<br>  <;><br>  (try<br>    {<br>      norm_num<br>    })<br>  <;><br>  (try<br>    {<br>      aesop<br>    }) ⟶ linarith |
| induction_ineq_nsqlefactn | induction' h₀ with n hn ⟶ decide ⟶ { simp_all [Nat.factorial_succ, Nat.succ_mul, Nat.mul_succ]<br>  nlinarith } |
| mathd_algebra_267 | apply Eq.symm ⟶ field_simp [h₀, h₁, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₂ ⟶ linarith |
| mathd_algebra_251 | have h₂ : x = 2 := by<br>  have h₃ : x ≠ 0 := h₀<br>  have h₄ : 3 + 1 / x = 7 / x := h₁<br>  have h₅ : x = 2 := by<br>    field_simp at h₄ ⊢<br>    nlinarith<br>  exact h₅ ⟶ linarith |
| mathd_algebra_206 | rw [h₀] at h₂ h₃ ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ nlinarith |
| mathd_algebra_181 | have h₂ : n - 3 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ have h₃ : n = 11 := by<br>  field_simp [h₂] at h₁<br>  linarith ⟶ linarith |
| amc12a_2017_p2 | field_simp [h₀, h₁] at * ⟶ linarith |
| mathd_numbertheory_629 | constructor ⟶ decide ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht_pos, ht_lcm⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num [Nat.lcm] at ht_lcm <;> omega |
| mathd_algebra_89 | simp ⟶ have h₁ : b ^ 2 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  nlinarith ⟶ field_simp [h₀, h₁, pow_ne_zero, pow_two, mul_ne_zero] ⟶ ring_nf ⟶ have h₂ : b^6 * 3136 = (b^2 * 4)^3 * 49 := by<br>  ring_nf<br>  <;> nlinarith<br>  <;> ring_nf<br>  <;> nlinarith ⟶ aesop |
| imo_1961_p1 | ring_nf ⟶ have h₇ : a^2 < 3 * b^2 := by<br>  nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₃),<br>    Real.sqrt_nonneg (x * y - z ^ 2)] ⟶ refine' ⟨_, _, _⟩<br><;> nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)]<br><;> nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)]<br><;> nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)] |
