# Proof search: phase3_search_shape_n8

Run `phase3_search_shape_n8` on miniF2F-valid, git `639928c64779bdf51b4f5e80d28a726a55384111`, config `experiments/configs/phase3_search_shape_n8.toml` (copied as `config.toml`). Started 2026-10-12T17:53:10+00:00, 61.4 min wall, 46 CPUs, load average 19.8 at start.

**Solved 154/244 (63.1%).** Solved only with proofs of 2 or more steps: 73. Verification failures (bugs): 1. Proofs that also verify without the per-step heartbeat wrappers: 154/154. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 53 | 0.757 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 21 | 0.467 |
| aime | 15 | 3 | 0.2 |
| imo | 20 | 2 | 0.1 |
| algebra | 18 | 15 | 0.833 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 |
|---|---|---|---|---|---|---|---|---|
| solved | 81 | 110 | 130 | 141 | 146 | 152 | 154 | 154 |
| solve rate | 33.2% | 45.1% | 53.3% | 57.8% | 59.8% | 62.3% | 63.1% | 63.1% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 18 | 36 | 60 | 91 | 117 | 130 | 140 | 147 | 148 | 151 | 153 | 154 | 154 | 154 |
| solve rate | 7.4% | 14.8% | 24.6% | 37.3% | 48.0% | 53.3% | 57.4% | 60.2% | 60.7% | 61.9% | 62.7% | 63.1% | 63.1% | 63.1% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 56 | 88 | 116 | 136 | 138 | 140 | 145 | 149 | 149 | 152 | 153 | 154 | 154 | 154 |
| solve rate | 23.0% | 36.1% | 47.5% | 55.7% | 56.6% | 57.4% | 59.4% | 61.1% | 61.1% | 62.3% | 62.7% | 63.1% | 63.1% | 63.1% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 154 |
| expansion_budget | 74 |
| frontier_exhausted | 11 |
| wall_clock_budget | 5 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 43.8 | 3 | 128 | 128 | 10685 |
| nodes | 99.1 | 9 | 330 | 648 | 24188 |
| edges | 564 | 33.5 | 1732 | 1859 | 137632 |
| lean_seconds | 298 | 5.56 | 810 | 3595 | 72733 |
| wall_seconds | 351 | 22.7 | 937 | 3616 | 85749 |
| duplicates | 108 | 6 | 347 | 583 | 26306 |
| errors | 325 | 18 | 1021 | 1287 | 79374 |
| timeouts | 6.27 | 0 | 10 | 213 | 1531 |
| repl_failures | 0.0041 | 0 | 0 | 1 | 1 |
| verification_seconds | 1.61 | 0.664 | 3.86 | 25.4 | 392 |

solved (154 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.82 | 1 | 6 | 63 | 589 |
| nodes | 10.3 | 5 | 21 | 180 | 1581 |
| edges | 43 | 12 | 78 | 869 | 6629 |
| lean_seconds | 20.6 | 1.66 | 22.8 | 1096 | 3171 |
| wall_seconds | 33.3 | 9.62 | 53.6 | 1136 | 5133 |
| duplicates | 6.34 | 1 | 12 | 96 | 976 |
| errors | 25.5 | 6 | 49 | 534 | 3925 |
| timeouts | 0.26 | 0 | 0 | 18 | 40 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.55 | 1.37 | 5.72 | 25.4 | 392 |

unsolved (90 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 112 | 128 | 128 | 128 | 10096 |
| nodes | 251 | 246 | 405 | 648 | 22607 |
| edges | 1456 | 1660 | 1786 | 1859 | 131003 |
| lean_seconds | 773 | 456 | 2154 | 3595 | 69562 |
| wall_seconds | 896 | 605 | 2286 | 3616 | 80616 |
| duplicates | 281 | 289 | 437 | 583 | 25330 |
| errors | 838 | 950 | 1138 | 1287 | 75449 |
| timeouts | 16.6 | 1 | 40 | 213 | 1491 |
| repl_failures | 0.0111 | 0 | 0 | 1 | 1 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 63783 | 55526 | 76.4% | 0.871 | 16396 | 12579 | 28332 | 26810 | 0 | 1522 | 0 | 54 | 0 |
| simp_all | 10253 | 5225 | 7.2% | 0.51 | 2517 | 4009 | 3727 | 3723 | 0 | 4 | 0 | 9 | 29 |
| nlinarith | 10489 | 4817 | 6.6% | 0.459 | 30 | 53 | 10406 | 10404 | 0 | 2 | 0 | 28 | 30 |
| omega | 10685 | 2925 | 4.0% | 0.274 | 59 | 24 | 10602 | 10602 | 0 | 0 | 0 | 30 | 31 |
| field_simp | 10635 | 2181 | 3.0% | 0.205 | 1728 | 987 | 7920 | 7920 | 0 | 0 | 0 | 0 | 9 |
| ring_nf | 10528 | 1453 | 2.0% | 0.138 | 2035 | 8491 | 2 | 0 | 0 | 2 | 0 | 14 | 23 |
| constructor | 10655 | 299 | 0.4% | 0.028 | 1173 | 141 | 9341 | 9341 | 0 | 0 | 0 | 15 | 23 |
| rfl | 10604 | 277 | 0.4% | 0.0261 | 6 | 22 | 10576 | 10574 | 0 | 1 | 1 | 5 | 5 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 81 |
| 2 | 32 |
| 3 | 17 |
| 4 | 10 |
| 5 | 9 |
| 6 | 3 |
| 7 | 1 |
| 8 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | simp_all ⟶ ring_nf |
| mathd_algebra_214 | simp_all only [h₀, h₁, sq, sub_eq_add_neg, mul_neg, mul_one, mul_zero, sub_zero, neg_zero,<br>  add_zero] ⟶ nlinarith |
| mathd_algebra_55 | simp_all ⟶ ring_nf |
| mathd_algebra_73 | have h₂ : x = p + q - r := by<br>  apply mul_left_cancel₀ (sub_ne_zero.2 h₁)<br>  simp [sub_eq_add_neg] at h₀<br>  linear_combination h₀ ⟶ simp_all |
| mathd_algebra_35 | simp_all ⟶ ring_nf |
| mathd_algebra_43 | simp only [h₀, h₁, h₂] at * ⟶ nlinarith |
| mathd_numbertheory_461 | simp_all ⟶ constructor |
| mathd_algebra_192 | simp [h₀, h₁, h₂, Complex.ext_iff, Complex.I_mul_I] ⟶ norm_num |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_numbertheory_109 | simp_all only [Finset.Icc, Finset.sum_range_succ, Nat.sub_eq_zero_of_le] ⟶ constructor |
| mathd_algebra_547 | simp only [h₀, h₁, pow_two, pow_three] ⟶ ring_nf ⟶ rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num |
| amc12b_2003_p9 | simp_all only [h₀, one_mul, mul_one, mul_zero, zero_mul, mul_add, mul_sub, sub_mul, add_sub_assoc,<br>  add_sub_cancel_left, mul_comm, mul_left_comm, mul_assoc] ⟶ nlinarith |
| mathd_algebra_245 | field_simp [h₀, mul_comm] ⟶ ring_nf |
| induction_divisibility_3divnto3m2n | have h : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases h with (h \| h \| h) <;><br>simp [h, Nat.dvd_iff_mod_eq_zero, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_mod]<br><;><br>omega |
| mathd_algebra_28 | simp_all ⟶ obtain ⟨x, hx⟩ := h₁ ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| amc12a_2013_p7 | simp_all ⟶ nlinarith |
| amc12a_2009_p9 | have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1, h₀ 2] |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_numbertheory_64 | constructor ⟶ constructor ⟶ ·<br>  intro x hx<br>  simp [ModEq, Nat.mod_eq_of_lt] at hx<br>  omega |
| amc12_2000_p11 | field_simp [h₀.1, h₀.2] ⟶ nlinarith [h₀.1, h₀.2, h₁, sq_nonneg (a - b)] |
| mathd_algebra_132 | field_simp ⟶ simp only [h₀, h₁, mul_one] at * ⟶ nlinarith |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| amc12a_2013_p8 | field_simp at h₃ ⟶ have h₄ : x * y = 2 := by<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₂)<br>  nlinarith [sq_pos_of_ne_zero h₀, sq_pos_of_ne_zero h₁] ⟶ simp_all |
| mathd_algebra_159 | simp [h₀, h₁] at * ⟶ nlinarith |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp ⟶ rw [div_le_iff (by positivity)] ⟶ nlinarith [sq_sqrt (show (0 : ℝ) ≤ 2 by norm_num), sq_nonneg (x - Real.sqrt 2 / 2)] |
| mathd_algebra_11 | field_simp [h₀, h₁, sub_ne_zero, sub_ne_zero] at h₂ ⊢ ⟶ nlinarith |
| mathd_numbertheory_780 | rcases h₁ with ⟨h₁_left, h₁_right⟩ ⟶ interval_cases m <;> omega |
| amc12_2001_p9 | have h₂ := h₀ 500 (by norm_num) 600 (by norm_num) ⟶ field_simp ⟶ have h₃ := h₀ 600 (by norm_num) 500 (by norm_num) ⟶ norm_num at h₂ h₃ ⟶ nlinarith |
| numbertheory_nckeqnm1ckpnm1ckm1 | cases n <;> cases k <;> simp_all [Nat.choose, Nat.succ_eq_add_one, Nat.add_sub_cancel_left, Nat.add_sub_cancel_right] ⟶ omega |
| mathd_numbertheory_232 | simp_all ⟶ rfl |
| mathd_algebra_67 | simp_all ⟶ ring_nf |
| mathd_algebra_327 | constructor ⟶ . cases' abs_cases (9 + 2 * a) with h₁ h₁ <;> linarith ⟶ case right =><br>  cases' le_total 0 (9 + 2 * a) with h h <;><br>  simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;><br>  linarith |
| mathd_numbertheory_35 | norm_num at h₀ ⟶ have h₁ := h₀ 0 ⟶ omega |
| mathd_numbertheory_22 | have h₂ : b ≤ 9 := by linarith ⟶ interval_cases b <;> norm_num at h₁ ⊢<br><;> omega |
| amc12a_2015_p10 | revert h₀ h₁ h₂ ⟶ intro h1 h2 h3 ⟶ have h4 : y ≤ 25 := by<br>  nlinarith ⟶ interval_cases y <;> norm_num at h1 h2 h3 ⊢ <;><br>  omega |
| mathd_algebra_151 | have h₁ : Int.ceil (Real.sqrt 27) = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num <;><br>    nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 27 by norm_num), Real.sqrt_nonneg 27] ⟶ have h₂ : Int.floor (Real.sqrt 26) = 5 := by<br>  norm_num [Int.floor_eq_iff, Real.le_sqrt, Real.sqrt_lt]<br>  <;><br>  nlinarith [sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ omega |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp only [h₁] at h₀ ⊢ ⟶ simp_all [Complex.ext_iff, Complex.I_mul_I, mul_add, mul_sub, mul_comm, mul_left_comm] ⟶ nlinarith |
| mathd_algebra_116 | have h₂ : x = (13 - Real.sqrt 131) / 4 := by<br>  linarith ⟶ field_simp ⟶ ring_nf at h₁ ⟶ nlinarith [sq_sqrt (show 0 ≤ 131 by norm_num)] |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_algebra_13 | constructor ⟶ case left =><br>  have h₁ := h₀ 4<br>  have h₂ := h₀ (-1)<br>  norm_num at h₁ h₂<br>  <;> field_simp at h₁ h₂<br>  <;> ring_nf at h₁ h₂<br>  <;> norm_num at h₁ h₂<br>  <;> linarith ⟶ next =><br>  have h₁ := h₀ 2<br>  have h₂ := h₀ 4<br>  simp [div_eq_mul_inv, mul_assoc] at h₁ h₂<br>  norm_num at h₁ h₂<br>  field_simp at h₁ h₂<br>  ring_nf at h₁ h₂<br>  linarith |
| mathd_numbertheory_32 | simp only [Finset.sum_eq_multiset_sum] ⟶ have h1 : S = Finset.filter (fun k => k ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀] ⟶ simp_all only [Finset.mem_filter, Finset.mem_range, Nat.dvd_iff_mod_eq_zero, Nat.mod_eq_of_lt,<br>  Nat.lt_succ_self, Nat.zero_lt_succ] ⟶ constructor |
| mathd_algebra_536 | field_simp [Nat.factorial_succ, Nat.factorial_one, mul_comm] ⟶ ring_nf ⟶ nlinarith [Real.sqrt_nonneg 9, sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num)] |
| mathd_algebra_251 | field_simp at h₁ ⟶ nlinarith |
| mathd_numbertheory_257 | norm_num at h₁ ⟶ omega |
| mathd_algebra_181 | field_simp [sub_ne_zero.mpr h₀, sub_ne_zero.mpr h₀] at h₁ ⟶ nlinarith |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| amc12a_2017_p2 | field_simp ⟶ nlinarith |
| mathd_algebra_22 | rw [Real.logb] ⟶ field_simp ⟶ ring_nf |
| mathd_algebra_140 | ring_nf ⟶ have h₂ := h₁ 0 ⟶ simp_all ⟶ nlinarith [h₁ 0, h₁ 1, h₁ (-1)] |
| induction_divisibility_9div10tonm1 | apply Nat.dvd_of_mod_eq_zero ⟶ rw [← Nat.mod_add_div (10 ^ n) 9] ⟶ simp [Nat.pow_mod, Nat.mul_mod, Nat.add_mod, Nat.mod_mod] |
| mathd_numbertheory_326 | ring_nf at h₀ ⟶ rw [← sub_eq_zero] at h₀ ⟶ rw [eq_comm] ⟶ nlinarith [sq_nonneg (n - 1), sq_nonneg (n + 1), sq_nonneg (n^2 - 1)] |
| mathd_algebra_77 | constructor ⟶ all_goals<br>  simp_all only [h₂, h₃, h₄, eq_self_iff_true, and_true]<br>  norm_num<br>  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)<br>  nlinarith |
| mathd_algebra_206 | simp only [h₀, h₁, h₂, h₃, pow_two, eq_self_iff_true, and_true, true_and] at * ⟶ simp_all ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ nlinarith |
| mathd_algebra_59 | norm_num at h₀ ⟶ rw [← sub_eq_zero] ⟶ have : (4 : ℝ) ^ b + 8 = 12 := h₀ ⟶ have h : (4 : ℝ) ^ b = 4 := by<br>  linarith ⟶ have h₁ : b = 1 := by<br>  apply_fun fun x => Real.logb 4 x at h<br>  simpa using h ⟶ simp_all |
| mathd_numbertheory_629 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  ·<br>    norm_num [Nat.lcm]<br>    <;> decide ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht1, ht2⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num at ht2 <;><br>  (try norm_num) <;><br>  (try omega) <;><br>  simp_all [Nat.lcm, Nat.gcd, Nat.div_eq_of_lt] <;><br>  (try omega) <;><br>  (try ring_nf at ht2 <;> omega) |
| aime_1984_p15 | field_simp at h₀ h₁ h₂ h₃ ⟶ nlinarith |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | have h₂ : x = -4 := by<br>  have h₂₁ : x = -4 := by<br>    have h₂₂ : 2 * x + e = 3 := h₁<br>    have h₂₃ : x + e = 7 := h₀<br>    have h₂₄ : (2 * x + e) - (x + e) = (3 : ℂ) - (7 : ℂ) := by rw [h₂₃, h₂₂]<br>    have h₂₅ : x = -4 := by<br>      ring_nf at h₂₄ ⊢<br>      <;> simp_all [Complex.ext_iff]<br>      <;> linarith<br>    exact h₂₅<br>  exact h₂₁ ⟶ have h₃ : e = 11 := by<br>  rw [h₂] at h₁<br>  linear_combination h₁ ⟶ simp_all |
| imo_1964_p1_2 | ring_nf ⟶ rw [Nat.dvd_iff_mod_eq_zero] ⟶ have : 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 := by<br>  have : 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 := by<br>    have : ∀ n : ℕ, 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 := by<br>      intro n<br>      induction n with<br>      \| zero =><br>        simp<br>      \| succ n ih =><br>        rcases ih with (h \| h \| h) <;> simp_all [Nat.pow_succ, Nat.mul_mod]<br>        <;> omega<br>    exact this n<br>  exact this ⟶ omega |
| mathd_numbertheory_690 | constructor ⟶ ·<br>  constructor<br>  · norm_num<br>  constructor<br>  · norm_num [Nat.ModEq]<br>  constructor<br>  · norm_num [Nat.ModEq]<br>  constructor<br>  · norm_num [Nat.ModEq]<br>  · norm_num [Nat.ModEq] ⟶ ·<br>  intro a h<br>  rcases h with ⟨h1, h2, h3, h4, h5⟩<br>  by_contra h6<br>  interval_cases a <;> simp_all (config := {decide := true}) |
| amc12b_2002_p6 | constructor ⟶ simp_all ⟶ case left =><br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  have h₅ := h₁ 2<br>  have h₆ := h₁ (-2)<br>  have h₇ := h₁ 1<br>  have h₈ := h₁ 2<br>  have h₉ := h₁ (-1)<br>  have h₁₀ := h₁ 3<br>  have h₁₁ := h₁ (-3)<br>  simp [h₀] at *<br>  nlinarith ⟶ apply mul_right_cancel₀ h₀.1 ⟶ nlinarith [h₁ 0, h₁ 1, h₁ (-1)] |
| mathd_algebra_421 | rw [h₀] at h₁ ⟶ nlinarith [sq_nonneg (a - c), h₁, h₂, h₃, h₄] |
| amc12a_2016_p3 | simp_all ⟶ ring_nf ⟶ have h₁ : Int.floor (-15 / 16 : ℝ) = -1 := by<br>  norm_num [Int.floor_eq_iff, Int.ofNat_le]<br>  <;><br>  (try decide) <;><br>  (try norm_num) <;><br>  (try linarith) <;><br>  (try<br>    {<br>      norm_num [Int.floor_eq_iff, Int.ofNat_le] <;><br>      linarith<br>    }) ⟶ simp_all ⟶ ring_nf |
| amc12b_2003_p17 | have h₃ : 0 < x * y := mul_pos h₀.1 h₀.2 ⟶ field_simp ⟶ have h₄ : x * y ≠ 0 := by linarith ⟶ field_simp [Real.log_mul, Real.log_inv, h₀.1.ne', h₀.2.ne', Real.log_pow, mul_comm] at h₁ h₂ ⊢ ⟶ nlinarith |
| mathd_algebra_267 | apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ have h₃ : x + 2 ≠ 0 := by<br>  intro h<br>  apply h₁<br>  linarith ⟶ have h₄ : x - 1 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ field_simp [h₃, h₄] at h₂ ⟶ nlinarith |
| mathd_algebra_185 | simp_all ⟶ apply Eq.symm ⟶ simp_all [abs_lt] ⟶ have h₂ : s = Finset.Ioo (-13 : ℤ) 5 := by<br>  ext x<br>  simp [h₁]<br>  constructor<br>  ·<br>    intro hx<br>    omega<br>  ·<br>    intro hx<br>    omega ⟶ simp_all |
| induction_seq_mul2pnp1 | ring_nf ⟶ induction' n with n hᵢ ⟶ omega ⟶ cases n <;> simp_all [Nat.mul_succ] ⟶ omega |
| mathd_algebra_493 | simp_all ⟶ have h₁ : Real.sqrt 4 = 2 := by<br>  rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num ⟶ simp_all ⟶ ring_nf ⟶ have h₂ : √9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  <;> ring_nf <;> norm_num ⟶ nlinarith |
| mathd_algebra_451 | field_simp ⟶ have h₄ := h₀ ⟶ have h₅ := h₁.symm ⟶ have h₆ := h₃.symm ⟶ have h₇ := h₁.symm ⟶ have h₈ := h₂.symm ⟶ simp_all |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | have h₃ : Real.sqrt (x * y) ≥ 0 := by<br>  apply Real.sqrt_nonneg ⟶ have h₄ : x * y ≥ 0 := by nlinarith ⟶ field_simp ⟶ nlinarith [sq_sqrt (by nlinarith : 0 ≤ x * y), sq_nonneg (Real.sqrt (x * y) - (x - y) / 2)] |
| imo_1961_p1 | ring_nf ⟶ refine' ⟨_, _, _⟩ ⟶ nlinarith ⟶ nlinarith ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₃)]<br><;> linarith |
| aime_1983_p9 | have h₁ : sin x ≤ 1 := by<br>  exact sin_le_one x ⟶ have h₂ : Real.sin x > 0 := Real.sin_pos_of_pos_of_lt_pi h₀.1 (by linarith [Real.pi_pos]) ⟶ rw [le_div_iff (by nlinarith [Real.sin_sq_add_cos_sq x])] ⟶ have h₃ : x ^ 2 * Real.sin x ^ 2 ≥ 0 := by<br>  apply mul_nonneg<br>  nlinarith [Real.sin_sq_le_one x]<br>  nlinarith ⟶ nlinarith [sq_nonneg (x * sin x - 2 / 3)] |
| amc12a_2008_p8 | have h₃ : 0 < Real.sqrt 2 := Real.sqrt_pos.2 (by norm_num) ⟶ have h₄ : Real.sqrt 2^2 = 2 := Real.sq_sqrt (by linarith) ⟶ ring_nf ⟶ have h₅ : y = 1 := by<br>  nlinarith ⟶ have h₆ : x^3 = Real.sqrt 2 * 2 := by<br>  rw [h₅] at h₂<br>  nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num),<br>    mul_self_nonneg (x - Real.sqrt 2)] ⟶ simp_all |
| aime_1991_p1 | cases' h₀ with hx hy ⟶ have hxy : x * y > 0 := mul_pos hx hy ⟶ have hyx : x * y > 0 := by nlinarith ⟶ have hxy' : x * y ≤ 146 := by<br>  nlinarith ⟶ have hxy'' : x + y ≤ 146 := by<br>  nlinarith ⟶ simp_all ⟶ have hxy''' : x * y ≥ 39 := by<br>  nlinarith [sq_nonneg (x + y), sq_nonneg (x - y)] ⟶ nlinarith |
