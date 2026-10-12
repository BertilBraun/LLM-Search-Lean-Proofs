# Proof search: phase2_sft_v1_search

Run `phase2_sft_v1_search` on miniF2F-valid, git `737a93945357d72ff0e067d7a404c182c551b935`, config `experiments/configs/phase2_sft_v1_search.toml` (copied as `config.toml`). Started 2026-10-12T01:38:12+00:00, 24.0 min wall, 46 CPUs, load average 9.8 at start.

**Solved 148/244 (60.7%).** Solved only with proofs of 2 or more steps: 64. Verification failures (bugs): 0. Proofs that also verify without the per-step heartbeat wrappers: 148/148. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 53 | 0.757 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 17 | 0.378 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 1 | 0.05 |
| algebra | 18 | 16 | 0.889 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 6 | 0.75 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 84 | 104 | 123 | 129 | 140 | 145 | 148 |
| solve rate | 34.4% | 42.6% | 50.4% | 52.9% | 57.4% | 59.4% | 60.7% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 40 | 57 | 85 | 108 | 119 | 125 | 133 | 143 | 144 | 145 | 148 |
| solve rate | 16.4% | 23.4% | 34.8% | 44.3% | 48.8% | 51.2% | 54.5% | 58.6% | 59.0% | 59.4% | 60.7% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 66 | 90 | 110 | 117 | 125 | 132 | 138 | 144 | 145 | 145 | 148 |
| solve rate | 27.0% | 36.9% | 45.1% | 48.0% | 51.2% | 54.1% | 56.6% | 59.0% | 59.4% | 59.4% | 60.7% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 148 |
| expansion_budget | 67 |
| wall_clock_budget | 28 |
| frontier_exhausted | 1 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 24 | 4 | 64 | 64 | 5851 |
| nodes | 76.3 | 16 | 223 | 346 | 18606 |
| edges | 531 | 78.5 | 1540 | 1744 | 129651 |
| lean_seconds | 132 | 13 | 500 | 597 | 32323 |
| wall_seconds | 177 | 25 | 600 | 607 | 43071 |
| duplicates | 137 | 22 | 399 | 706 | 33406 |
| errors | 299 | 43 | 884 | 1128 | 72965 |
| timeouts | 1.72 | 0 | 5 | 38 | 420 |
| repl_failures | 0.0041 | 0 | 0 | 1 | 1 |
| verification_seconds | 1.23 | 0.226 | 2.98 | 17.2 | 301 |

solved (148 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 4.01 | 1 | 13 | 51 | 593 |
| nodes | 14.4 | 5 | 33 | 173 | 2125 |
| edges | 79.5 | 16.5 | 274 | 1205 | 11759 |
| lean_seconds | 18.3 | 1.21 | 42.9 | 567 | 2710 |
| wall_seconds | 25.9 | 3.66 | 68.4 | 592 | 3829 |
| duplicates | 17.8 | 3 | 56 | 274 | 2634 |
| errors | 45.5 | 10 | 154 | 884 | 6737 |
| timeouts | 0.324 | 0 | 0 | 26 | 48 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.04 | 1.09 | 4.45 | 17.2 | 301 |

unsolved (96 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 54.8 | 64 | 64 | 64 | 5258 |
| nodes | 172 | 162 | 286 | 346 | 16481 |
| edges | 1228 | 1384 | 1616 | 1744 | 117892 |
| lean_seconds | 308 | 260 | 560 | 597 | 29613 |
| wall_seconds | 409 | 413 | 603 | 607 | 39242 |
| duplicates | 321 | 346 | 456 | 706 | 30772 |
| errors | 690 | 735 | 1003 | 1128 | 66228 |
| timeouts | 3.88 | 1 | 15 | 38 | 372 |
| repl_failures | 0.0104 | 0 | 0 | 1 | 1 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 54630 | 21866 | 67.7% | 0.4 | 14852 | 9653 | 25628 | 25225 | 0 | 403 | 0 | 62 | 0 |
| aesop | 5634 | 3559 | 11.0% | 0.632 | 362 | 3366 | 1906 | 1901 | 0 | 5 | 0 | 3 | 8 |
| simp_all | 5712 | 2516 | 7.8% | 0.44 | 1069 | 2498 | 2145 | 2141 | 0 | 3 | 1 | 4 | 35 |
| nlinarith | 5570 | 1815 | 5.6% | 0.326 | 4 | 18 | 5548 | 5542 | 0 | 6 | 0 | 3 | 3 |
| linarith | 5801 | 464 | 1.4% | 0.0801 | 27 | 14 | 5760 | 5760 | 0 | 0 | 0 | 23 | 23 |
| field_simp | 5808 | 444 | 1.4% | 0.0765 | 261 | 770 | 4777 | 4777 | 0 | 0 | 0 | 0 | 4 |
| ring_nf | 5775 | 403 | 1.2% | 0.0698 | 741 | 5033 | 1 | 0 | 0 | 1 | 0 | 5 | 12 |
| norm_num | 5804 | 392 | 1.2% | 0.0675 | 86 | 5717 | 1 | 0 | 0 | 1 | 0 | 6 | 9 |
| decide | 5851 | 289 | 0.9% | 0.0493 | 33 | 3 | 5815 | 5815 | 0 | 0 | 0 | 24 | 27 |
| simp | 5809 | 277 | 0.9% | 0.0477 | 360 | 432 | 5017 | 5017 | 0 | 0 | 0 | 0 | 5 |
| rfl | 5804 | 94.2 | 0.3% | 0.0162 | 14 | 9 | 5781 | 5780 | 0 | 1 | 0 | 4 | 4 |
| constructor | 5813 | 84.9 | 0.3% | 0.0146 | 494 | 111 | 5208 | 5208 | 0 | 0 | 0 | 0 | 7 |
| omega | 5827 | 54.6 | 0.2% | 0.00936 | 16 | 12 | 5799 | 5799 | 0 | 0 | 0 | 14 | 14 |
| intros | 5813 | 53.6 | 0.2% | 0.00922 | 43 | 5770 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 84 |
| 2 | 25 |
| 3 | 10 |
| 4 | 11 |
| 5 | 4 |
| 6 | 3 |
| 8 | 3 |
| 10 | 3 |
| 13 | 2 |
| 15 | 2 |
| 16 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | rw [h₀, h₁] ⟶ norm_num |
| amc12a_2009_p5 | ring_nf at h₀ ⟶ simp_all ⟶ norm_num |
| mathd_algebra_547 | simp_all ⟶ norm_num [Real.sqrt_eq_iff_mul_self_eq, pow_succ, mul_assoc] |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_73 | apply mul_left_cancel₀ (sub_ne_zero.mpr h₁) ⟶ linear_combination h₀ - (r - p) * (r - q) |
| mathd_numbertheory_64 | constructor ⟶ decide ⟶ ·<br>  intro x<br>  intro h<br>  simp [Nat.ModEq] at h<br>  omega |
| induction_divisibility_3divnto3m2n | apply Nat.dvd_of_mod_eq_zero ⟶ have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;> simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod] |
| mathd_numbertheory_32 | have h1 : S = Finset.filter (fun n => n ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀]<br>  all_goals norm_num ⟶ aesop |
| mathd_numbertheory_257 | norm_num at h₁ ⟶ omega |
| mathd_algebra_28 | rcases h₁ with ⟨x, hx⟩ ⟶ have h₁ := h₀ x ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| mathd_algebra_116 | rw [h₀] at h₁ ⟶ nlinarith [Real.sqrt_pos.mpr (show (0 : ℝ) < (131 : ℝ) by norm_num), Real.sq_sqrt (show (0 : ℝ) ≤ (131 : ℝ) by norm_num)] |
| mathd_algebra_140 | have h₂ := h₁ 0 ⟶ have h₃ := h₁ 1 ⟶ have h₄ := h₁ (-1) ⟶ linarith |
| mathd_algebra_35 | simp_all ⟶ norm_num |
| mathd_numbertheory_35 | have h₁ := h₀ 1 ⟶ have h₂ := h₀ 2 ⟶ have h₃ := h₀ 3 ⟶ norm_num [Finset.sum_range_succ] at h₁ h₂ h₃ ⊢ |
| mathd_numbertheory_780 | aesop ⟶ interval_cases m <;> omega |
| mathd_algebra_510 | have h₂ : x ^ 2 + y ^ 2 = (x + y) ^ 2 - 2 * (x * y) := by ring ⟶ rw [h₂, h₀, h₁] ⟶ norm_num ⟶ rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num |
| mathd_algebra_245 | simp ⟶ ring_nf<br><;> simp_all [h₀]<br><;> ring_nf<br><;> field_simp [h₀]<br><;> ring_nf<br><;> linarith |
| mathd_algebra_192 | simp_all ⟶ norm_num [ Complex.ext_iff, Complex.I_mul_I ]<br><;> ring<br><;> norm_num<br><;> ring |
| amc12a_2009_p9 | have h₂ := h₀ 0 ⟶ have h₃ := h₁ 0 ⟶ simp at h₂ h₃ ⟶ have h₄ := h₁ 3 ⟶ have h₅ := h₀ 0 ⟶ simp at h₅ ⟶ have h₆ := h₀ 0 ⟶ have h₇ := h₀ 1 ⟶ have h₈ := h₀ 2 ⟶ have h₉ := h₀ (-1) ⟶ have h₁₀ := h₀ (-2) ⟶ norm_num at h₆ h₇ h₈ h₉ h₁₀ ⟶ simp_all |
| mathd_algebra_433 | have h₁ := h₀ 8 ⟶ have h₂ : 2 * 8 - 7 = 9 := by norm_num ⟶ have h₃ : Real.sqrt 9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ simp_all ⟶ ring_nf<br><;> norm_num<br><;> linarith |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp ⟶ rw [div_le_iff (by positivity)] ⟶ nlinarith [Real.mul_self_sqrt (by norm_num : (0 : ℝ) ≤ 2), sq_nonneg (x - 1), sq_nonneg (x + 1), sq_nonneg (x - Real.sqrt 2 / 2), sq_nonneg (x + Real.sqrt 2 / 2)] |
| mathd_algebra_110 | rw [h₀] ⟶ ring_nf ⟶ simp_all ⟶ ring<br><;> simp [Complex.ext_iff]<br><;> norm_num<br><;> ring |
| aime_1984_p15 | field_simp at h₀ h₁ h₂ h₃ ⟶ linarith |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | aesop ⟶ nlinarith [sq_sqrt (mul_nonneg left.le right.le), sq_nonneg (x - y), sq_nonneg (x + y),<br>  sq_nonneg (x - y + 2 * Real.sqrt (x * y)), sq_nonneg (x - y - 2 * Real.sqrt (x * y))] |
| amc12b_2002_p6 | have h₂ := h₁ 0 ⟶ have h₃ := h₁ 1 ⟶ have h₄ := h₁ (-1) ⟶ have h₅ := h₁ 2 ⟶ constructor ⟶ all_goals<br>  ring_nf at h₂ h₃ h₄ h₅<br>  nlinarith [sq_pos_of_ne_zero (show a ≠ 0 by intro h; apply h₀.1 <;> linarith), sq_pos_of_ne_zero (show b ≠ 0 by intro h; apply h₀.2 <;> linarith)] |
| mathd_algebra_43 | simp_all ⟶ linarith |
| imo_1984_p2 | by_contra h₅ ⟶ push_neg at h₅ ⟶ have h₆ : a + b ≤ 18 := by linarith ⟶ have h₇ : a ≤ 18 := by omega ⟶ have h₈ : b ≤ 18 := by linarith ⟶ have h₉ : a ≤ 18 := by linarith ⟶ have h₁₀ : b ≤ 18 := by linarith ⟶ simp_all ⟶ have h₇ : a ≤ 18 := by linarith ⟶ have h_b : b ≤ 18 := by linarith ⟶ simp_all ⟶ have h_a : a ≤ 18 := by linarith ⟶ have h₈ : a ≤ 18 := by linarith ⟶ have h₉ : b ≥ 1 := by omega ⟶ have h₁₀ : a ≥ 1 := by linarith ⟶ interval_cases a <;> interval_cases b <;> omega |
| mathd_algebra_214 | simp_all ⟶ linarith |
| mathd_algebra_151 | have h1 : (Real.sqrt 27 : ℝ) > 4 := by<br>  have h₁ : (4 : ℝ) < Real.sqrt 27 := by<br>    apply Real.lt_sqrt_of_sq_lt<br>    norm_num<br>  linarith ⟶ simp_all ⟶ have h2 : 4 < Real.sqrt 27 := h1 ⟶ have h3 : √26 < √27 := by<br>  apply Real.sqrt_lt_sqrt<br>  <;> norm_num<br>  <;> linarith ⟶ have h4 : Real.sqrt 26 < Real.sqrt 27 := h3 ⟶ simp_all ⟶ have h5 : ⌊Real.sqrt 26⌋ = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;> nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ simp_all ⟶ have h6 : ⌈√27⌉ = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num <;><br>    nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 by norm_num)] ⟶ omega |
| mathd_algebra_234 | field_simp at h₀ ⊢ ⟶ nlinarith [sq_nonneg (d - 5 / 3), sq_nonneg (d + 5 / 3)] |
| amc12a_2013_p8 | field_simp at h₃ ⟶ ring_nf at h₃ ⟶ simp_all ⟶ apply mul_left_cancel₀ (sub_ne_zero.mpr h₂) ⟶ linarith |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| mathd_algebra_536 | field_simp ⟶ ring_nf ⟶ norm_num [Nat.factorial] ⟶ nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show 0 ≤ 9 by norm_num)] |
| amc12b_2003_p9 | simp only [h₀] at h₁ ⊢ ⟶ linarith |
| mathd_algebra_132 | norm_num ⟶ simp only [h₀, h₁] at h₂ ⟶ linarith |
| mathd_numbertheory_22 | have h₂ : 0 ≤ 10 * b + 6 := by linarith ⟶ have h₃ := h₁ ⟶ simp_all ⟶ interval_cases h₁ : b <;> norm_num [h₃] at h₃ <;> omega |
| amc12a_2013_p7 | have h₃ := h₀ 7 ⟶ have h₄ := h₀ 6 ⟶ have h₅ := h₀ 5 ⟶ have h₆ := h₀ 4 ⟶ linarith |
| mathd_algebra_410 | simp_all ⟶ nlinarith [sq_nonneg (x - 3)] |
| amc12_2000_p11 | have h₂ : a ≠ 0 := h₀.1 ⟶ have h₃ : b ≠ 0 := h₀.2 ⟶ field_simp ⟶ ring_nf ⟶ simp_all ⟶ nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)] |
| mathd_algebra_451 | simp_all ⟶ rw [h₃] at * ⟶ simp_all ⟶ rw [← h₂] ⟶ simp ⟶ have h₃ := h₂.symm ⟶ have h₄ := h₀ ⟶ simp_all only [Equiv.symm_apply_eq, h₁, h₂, h₃, h₄] |
| mathd_algebra_13 | have h₁ := h₀ 6 ⟶ have h₂ := h₀ 0 ⟶ have h₃ := h₀ 1 ⟶ have h₄ := h₀ 2 ⟶ have h₅ := h₀ 3 ⟶ have h₆ := h₀ 4 ⟶ have h₇ := h₀ 5 ⟶ have h₈ := h₀ 6 ⟶ have h₉ := h₀ 7 ⟶ have h₁₀ := h₀ 8 ⟶ have h₁₁ := h₀ 9 ⟶ have h₁₂ := h₀ 10 ⟶ norm_num at h₁ h₂ h₃ h₄ h₅ h₆ h₇ h₈ h₉ h₁₀ h₁₁ h₁₂ ⟶ constructor ⟶ all_goals<br>  nlinarith |
| mathd_algebra_493 | simp_all ⟶ norm_num ⟶ have h1 : Real.sqrt 4 = 2 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ ring_nf ⟶ norm_num [h1] ⟶ ring_nf ⟶ have h2 : Real.sqrt 9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ linarith |
| mathd_algebra_11 | have h₃ : a - 2 * b ≠ 0 := by<br>  intro h<br>  apply h₁<br>  linarith ⟶ have h₄ : a - b ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ field_simp [h₃, h₄] at h₂ ⊢ ⟶ linarith |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_algebra_77 | simp_all ⟶ constructor ⟶ all_goals<br>  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)<br>  nlinarith |
| mathd_algebra_159 | have h₂ := h₀ 1 ⟶ linarith |
| mathd_numbertheory_690 | constructor ⟶ decide ⟶ ·<br>  intro a<br>  rintro ⟨ha, h1, h2, h3, h4⟩<br>  norm_num [Nat.ModEq] at *<br>  omega |
| amc12a_2008_p8 | ring_nf at h₂ ⟶ ring_nf ⟶ aesop ⟶ have h₃ : x^2 = 2 * y^2 := by<br>  nlinarith ⟶ simp_all ⟶ have h₄ : x^3 = x * x^2 := by ring ⟶ rw [h₄, h₃] ⟶ ring_nf ⟶ simp ⟶ have h₅ : y^3 = 1 := h₁ ⟶ simp_all ⟶ have h₆ : y = 1 := by<br>  nlinarith ⟶ have h₇ : x^2 = 2 := by<br>  rw [h₆] at h₃<br>  nlinarith ⟶ have h₈ : x = Real.sqrt 2 := by<br>  nlinarith [Real.sqrt_nonneg 2, Real.sq_sqrt (show 0 ≤ 2 by norm_num)] ⟶ simp_all |
| induction_divisibility_9div10tonm1 | apply Nat.dvd_of_mod_eq_zero ⟶ rw [← Nat.mod_add_div (10^n) 9] ⟶ simp [pow_mod, h₀] |
| mathd_algebra_67 | simp_all ⟶ norm_num |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | rw [h₁] at h₀ ⟶ rw [h₁] at * ⟶ simp_all ⟶ rw [← sub_eq_zero] at h₀ ⊢ ⟶ simp ⟶ rw [← sub_eq_zero] at h₀ ⊢ ⟶ simp ⟶ rw [← sub_eq_zero] at h₀ <;> simp_all [Complex.ext_iff, pow_two, Complex.I_mul_I]<br><;> ring<br><;> norm_num<br><;> linarith |
| mathd_algebra_437 | have h₄ : (x : ℝ) < (n : ℝ) := by exact_mod_cast h₂ ⟶ have h₅ : (n : ℝ) < y := h₃ ⟶ have h₆ := h₀ ⟶ have h₇ : y^3 = -101 := h₁ ⟶ have h₈ : x < (n : ℝ) := by exact_mod_cast h₄ ⟶ have h₉ : (n : ℝ) < y := h₅ ⟶ have h₁₀ := h₆ ⟶ have h₁₁ := h₇ ⟶ have h₁₂ : x < (n : ℝ) := by exact_mod_cast h₈ ⟶ have h₁₃ := h₉ ⟶ have h₁₄ := h₆ ⟶ have h₁₅ := h₁₁ ⟶ nlinarith [sq_nonneg (x + y), sq_nonneg (x - y), sq_nonneg (x - 1), sq_nonneg (y - 1)] |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | have h₂ : x + e = 7 := h₀ ⟶ have h₃ := h₁ ⟶ simp_all ⟶ ring_nf at h₂ h₃ ⟶ constructor ⟶ all_goals<br>  apply eq_of_sub_eq_zero<br>  rw [← sub_eq_zero] at *<br>  simp_all [Complex.ext_iff]<br>  constructor <;> linarith |
| mathd_algebra_267 | have h₃ : x - 1 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ have h₄ : x + 2 ≠ 0 := by<br>  intro h<br>  apply h₁<br>  linarith ⟶ field_simp [h₃, h₄] at h₂ ⟶ linarith |
| mathd_numbertheory_326 | ring_nf at h₀ ⟶ have h₁ : -n + n^3 = 720 := h₀ ⟶ simp_all ⟶ apply Eq.symm ⟶ nlinarith [sq_nonneg (n - 9), sq_nonneg (n + 9), sq_nonneg (n - 2), sq_nonneg (n + 2),<br>  sq_nonneg (n - 18), sq_nonneg (n + 18), sq_nonneg (n - 4), sq_nonneg (n + 4),<br>  sq_nonneg (n - 27), sq_nonneg (n + 27), sq_nonneg (n - 36), sq_nonneg (n + 36)] |
| aime_1991_p1 | aesop ⟶ ring_nf at h₁ h₂ ⊢ ⟶ have h₃ := h₁ ⟶ have h₄ := h₂ ⟶ simp_all ⟶ have h₅ : x ≤ 71 := by<br>  nlinarith ⟶ have h₆ : y ≤ 71 := by<br>  nlinarith ⟶ have h₇ : x * y ≤ 71 * 71 := by nlinarith ⟶ simp_all ⟶ interval_cases x <;> try {<br>  omega<br>} <;> try {<br>  interval_cases y <;> omega<br>} |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| mathd_algebra_251 | field_simp at h₁ ⟶ linarith |
| mathd_algebra_181 | have h₂ : n - 3 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ field_simp at h₁ ⟶ linarith |
| mathd_numbertheory_629 | constructor ⟶ decide ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht0, ht1⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num [Nat.lcm] at ht1 <;> omega |
| amc12a_2017_p2 | field_simp ⟶ linarith |
| mathd_algebra_206 | simp only [h₀] at h₂ h₃ ⟶ have h₄ : b * (b + a + 1) = 0 := by linarith ⟶ aesop ⟶ all_goals<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  nlinarith |
| algebra_amgm_sumasqdivbsqgeqsumbdiva | have h₁ : 0 < a * b := by<br>  exact mul_pos h₀.1 h₀.2.1 ⟶ have h₂ : 0 < b * c := by<br>  exact mul_pos h₀.2.1 h₀.2.2 ⟶ have h₃ : 0 < c * a := by<br>  exact mul_pos h₀.2.2 h₀.1 ⟶ have h₄ : 0 < a^2 := by nlinarith ⟶ have h₅ : 0 < b^2 := by nlinarith ⟶ have h₆ : 0 < c^2 := by nlinarith ⟶ have h₇ : 0 < a * b * c := by<br>  exact mul_pos (mul_pos h₀.1 h₀.2.1) h₀.2.2 ⟶ field_simp [h₀.1.ne', h₀.2.1.ne', h₀.2.2.ne'] ⟶ rw [div_le_div_iff (by positivity) (by positivity)] ⟶ nlinarith [sq_nonneg (a^2 * c - b^2 * a), sq_nonneg (b^2 * a - c^2 * b), sq_nonneg (c^2 * b - a^2 * c)] |
