# Proof search: phase3_search_shape_n4

Run `phase3_search_shape_n4` on miniF2F-valid, git `639928c64779bdf51b4f5e80d28a726a55384111`, config `experiments/configs/phase3_search_shape_n4.toml` (copied as `config.toml`). Started 2026-10-12T18:54:40+00:00, 61.3 min wall, 46 CPUs, load average 29.4 at start.

**Solved 153/244 (62.7%).** Solved only with proofs of 2 or more steps: 74. Verification failures (bugs): 2. Proofs that also verify without the per-step heartbeat wrappers: 153/153. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 54 | 0.771 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 20 | 0.444 |
| aime | 15 | 3 | 0.2 |
| imo | 20 | 2 | 0.1 |
| algebra | 18 | 15 | 0.833 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 6 | 0.75 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 | 128 | 256 |
|---|---|---|---|---|---|---|---|---|---|
| solved | 79 | 108 | 126 | 132 | 137 | 141 | 148 | 150 | 153 |
| solve rate | 32.4% | 44.3% | 51.6% | 54.1% | 56.1% | 57.8% | 60.7% | 61.5% | 62.7% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 16 | 38 | 62 | 93 | 117 | 126 | 135 | 140 | 143 | 147 | 147 | 153 | 153 | 153 |
| solve rate | 6.6% | 15.6% | 25.4% | 38.1% | 48.0% | 51.6% | 55.3% | 57.4% | 58.6% | 60.2% | 60.2% | 62.7% | 62.7% | 62.7% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 57 | 84 | 116 | 123 | 131 | 134 | 139 | 143 | 145 | 148 | 150 | 153 | 153 | 153 |
| solve rate | 23.4% | 34.4% | 47.5% | 50.4% | 53.7% | 54.9% | 57.0% | 58.6% | 59.4% | 60.7% | 61.5% | 62.7% | 62.7% | 62.7% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 153 |
| expansion_budget | 51 |
| frontier_exhausted | 34 |
| wall_clock_budget | 6 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 70.3 | 3 | 256 | 256 | 17162 |
| nodes | 121 | 7 | 445 | 821 | 29507 |
| edges | 717 | 29 | 2657 | 2794 | 174888 |
| lean_seconds | 296 | 4.72 | 848 | 3595 | 72229 |
| wall_seconds | 358 | 18.6 | 1018 | 3614 | 87312 |
| duplicates | 134 | 4 | 504 | 841 | 32733 |
| errors | 434 | 17 | 1610 | 1875 | 105791 |
| timeouts | 4.76 | 0 | 6 | 188 | 1161 |
| repl_failures | 0.0082 | 0 | 0 | 2 | 2 |
| verification_seconds | 1.95 | 0.763 | 4.77 | 24.2 | 475 |

solved (153 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 10.2 | 1 | 17 | 243 | 1567 |
| nodes | 19.9 | 4 | 32 | 530 | 3048 |
| edges | 102 | 10 | 173 | 2532 | 15542 |
| lean_seconds | 32.6 | 1.75 | 48.4 | 917 | 4983 |
| wall_seconds | 52.2 | 7.94 | 87.9 | 1001 | 7981 |
| duplicates | 16.3 | 1 | 26 | 438 | 2496 |
| errors | 63.2 | 6 | 96 | 1669 | 9672 |
| timeouts | 0.373 | 0 | 0 | 32 | 57 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 3.07 | 1.63 | 7.42 | 24.2 | 469 |

unsolved (91 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 171 | 256 | 256 | 256 | 15595 |
| nodes | 291 | 349 | 534 | 821 | 26459 |
| edges | 1751 | 2508 | 2730 | 2794 | 159346 |
| lean_seconds | 739 | 450 | 1722 | 3595 | 67247 |
| wall_seconds | 872 | 687 | 1814 | 3614 | 79332 |
| duplicates | 332 | 384 | 602 | 841 | 30237 |
| errors | 1056 | 1362 | 1793 | 1875 | 96119 |
| timeouts | 12.1 | 1 | 31 | 188 | 1104 |
| repl_failures | 0.022 | 0 | 0 | 2 | 2 |
| verification_seconds | 0.0682 | 0 | 0 | 3.14 | 6.2 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 56507 | 43564 | 60.3% | 0.771 | 18472 | 9972 | 22125 | 20976 | 0 | 1149 | 0 | 55 | 0 |
| simp_all | 16307 | 10030 | 13.9% | 0.615 | 3580 | 6508 | 6219 | 6213 | 0 | 6 | 0 | 6 | 44 |
| nlinarith | 16543 | 6721 | 9.3% | 0.406 | 39 | 69 | 16435 | 16432 | 0 | 3 | 0 | 32 | 34 |
| omega | 17162 | 5722 | 7.9% | 0.333 | 74 | 24 | 17064 | 17063 | 0 | 0 | 1 | 30 | 31 |
| field_simp | 17015 | 3228 | 4.5% | 0.19 | 2519 | 1598 | 12898 | 12897 | 0 | 1 | 0 | 1 | 15 |
| ring_nf | 17111 | 2127 | 2.9% | 0.124 | 2863 | 14247 | 1 | 0 | 0 | 1 | 0 | 12 | 23 |
| constructor | 17132 | 405 | 0.6% | 0.0237 | 1702 | 269 | 15161 | 15160 | 0 | 0 | 1 | 14 | 36 |
| rfl | 17111 | 400 | 0.6% | 0.0234 | 14 | 46 | 17051 | 17050 | 0 | 1 | 0 | 5 | 5 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 79 |
| 2 | 30 |
| 3 | 15 |
| 4 | 7 |
| 5 | 3 |
| 6 | 3 |
| 7 | 8 |
| 8 | 1 |
| 9 | 2 |
| 10 | 1 |
| 11 | 1 |
| 12 | 2 |
| 15 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | simp_all ⟶ ring_nf |
| mathd_algebra_43 | simp_all only [mul_comm] ⟶ nlinarith |
| mathd_algebra_55 | field_simp [h₀, h₁] ⟶ ring_nf |
| mathd_algebra_126 | refine' ⟨_, _⟩ ⟶ all_goals linarith |
| amc12a_2009_p5 | ring_nf at h₀ ⟶ simp_all ⟶ ring_nf |
| mathd_algebra_547 | subst h₀ h₁ ⟶ rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num<br><;> ring_nf<br><;> norm_num<br><;> linarith |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod]<br><;><br>omega |
| amc12b_2003_p9 | simp [h₀, h₁] at * ⟶ nlinarith |
| mathd_algebra_214 | simp_all ⟶ nlinarith |
| amc12a_2013_p8 | have h₄ : x * y = 2 := by<br>  field_simp at h₃<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₂)<br>  linarith ⟶ simp_all |
| mathd_algebra_101 | constructor ⟶ nlinarith ⟶ nlinarith |
| mathd_numbertheory_22 | have h₂ : b = 3 ∨ b = 1 := by<br>  have h₂ : b ≤ 9 := by linarith<br>  interval_cases b <;> norm_num at h₁ ⊢ <;> try norm_num <;> try ring_nf at h₁ ⊢ <;> try omega ⟶ omega |
| amc12a_2009_p9 | have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1] |
| mathd_algebra_110 | simp_all ⟶ simp [Complex.ext_iff, mul_add, mul_comm, mul_left_comm] ⟶ ring_nf |
| mathd_algebra_73 | apply mul_right_cancel₀ (sub_ne_zero.mpr h₁) ⟶ ring_nf ⟶ linear_combination h₀ |
| mathd_algebra_132 | field_simp ⟶ simp_all ⟶ nlinarith |
| mathd_numbertheory_232 | simp_all ⟶ rfl |
| numbertheory_sqmod3in01d | have h : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases h with (h \| h \| h) <;> simp [h, pow_two, Int.mul_emod]<br><;> omega |
| mathd_algebra_28 | simp_all ⟶ rcases h₁ with ⟨x, hx⟩ ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| mathd_algebra_22 | simp [Real.logb, Real.log_rpow, mul_comm] ⟶ field_simp<br><;> ring_nf<br><;> field_simp<br><;> ring_nf |
| amc12a_2013_p7 | have h₃ : s 4 = 10 := by<br>  linarith [h₀ 7, h₀ 6, h₀ 5, h₀ 4, h₀ 3, h₀ 2, h₀ 1, h₀ 0, h₂] ⟶ simp_all |
| mathd_algebra_116 | field_simp [h₀] at h₁ ⊢ ⟶ nlinarith [h₀, h₁, sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)] |
| mathd_algebra_410 | simp_all ⟶ nlinarith [sq_nonneg (x - 3)] |
| mathd_numbertheory_780 | rcases h₁ with ⟨h₁_left, h₁_right⟩ ⟶ interval_cases m <;> omega |
| mathd_algebra_327 | constructor ⟶ all_goals<br>  cases' le_total 0 (9 + 2 * a) with h h <;><br>  simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;><br>  linarith |
| mathd_algebra_192 | simp_all ⟶ ring_nf<br><;> simp [Complex.ext_iff, pow_two, pow_three, mul_add, mul_sub, mul_comm, mul_left_comm, mul_assoc,<br>  Complex.ofReal_mul, Complex.ofReal_re, Complex.ofReal_im, Complex.I_re, Complex.I_im]<br><;> ring_nf<br><;> norm_num |
| amc12b_2020_p5 | ring_nf at h₀ h₁ ⟶ field_simp at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| mathd_algebra_234 | field_simp ⟶ norm_num ⟶ nlinarith [sq_nonneg (d - 3), sq_nonneg (d + 3)] |
| mathd_algebra_159 | simp_all only [h₀, one_pow, mul_one, mul_zero, zero_add, mul_neg, neg_mul, neg_neg, mul_assoc] ⟶ nlinarith |
| algebra_sqineq_2at2pclta2c2p41pc | have h : 0 ≤ (a - 2 - c)^2 := sq_nonneg _ ⟶ nlinarith |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp ⟶ rw [div_le_iff (by positivity)] ⟶ nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num),<br>  sq_nonneg (x - 1),<br>  sq_nonneg (x - Real.sqrt 2 / 2)] |
| induction_divisibility_3divnto3m2n | apply Nat.dvd_of_mod_eq_zero ⟶ have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_mod]<br><;><br>omega |
| mathd_numbertheory_64 | constructor ⟶ constructor ⟶ ·<br>  intro x hx<br>  by_contra h<br>  push_neg at h<br>  interval_cases x <;> simp_all (config := {decide := true}) |
| mathd_algebra_67 | simp_all ⟶ ring_nf |
| mathd_algebra_11 | ring_nf ⟶ field_simp [sub_ne_zero.mpr h₀, sub_ne_zero.mpr h₁, sub_ne_zero.mpr h₀.symm, sub_ne_zero.mpr h₁.symm] at h₂ ⊢ ⟶ nlinarith |
| mathd_algebra_140 | have h₂ := h₁ 1 ⟶ have h₃ := h₁ 2 ⟶ have h₄ := h₁ (-1) ⟶ nlinarith |
| mathd_numbertheory_35 | norm_num [Finset.sum_eq_multiset_sum] at h₀ ⟶ have h₁ := h₀ 24 ⟶ omega |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_numbertheory_668 | norm_num [h₀, h₁, ← sub_eq_add_neg] ⟶ rfl |
| mathd_numbertheory_461 | simp_all ⟶ constructor |
| mathd_algebra_251 | have h₂ : x = 2 := by<br>  field_simp [h₀] at h₁<br>  linarith ⟶ simp_all |
| mathd_algebra_181 | field_simp [sub_ne_zero.mpr h₀, sub_ne_zero.mpr h₀] at h₁ ⟶ nlinarith |
| amc12a_2017_p2 | field_simp ⟶ nlinarith |
| mathd_numbertheory_32 | simp only [Finset.sum_eq_multiset_sum] ⟶ have h₁ : S = Finset.filter (fun k : ℕ => k ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀] ⟶ simp [h₁, Nat.dvd_iff_mod_eq_zero, Nat.mod_eq_of_lt] ⟶ constructor |
| mathd_algebra_267 | field_simp [h₀, h₁, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₂ ⊢ ⟶ nlinarith |
| induction_ineq_nsqlefactn | induction' h₀ with n h₀ ⟶ all_goals simp_all [Nat.factorial_succ, Nat.pow_succ] ⟶ nlinarith |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ simp_all only [Complex.ext_iff, Complex.I_mul_I, Complex.ofReal_add, Complex.ofReal_one,<br>  Complex.ofReal_neg, Complex.ofReal_mul, Complex.ofReal_zero, Complex.ofReal_add,<br>  Complex.ofReal_one, Complex.ofReal_neg, Complex.ofReal_mul, Complex.ofReal_zero] ⟶ simp_all ⟶ nlinarith |
| aime_1984_p15 | norm_num [div_eq_mul_inv] at h₀ h₁ h₂ h₃ ⟶ nlinarith |
| mathd_algebra_77 | simp_all only [h₂, pow_two] ⟶ constructor ⟶ simp_all ⟶ all_goals<br>  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)<br>  nlinarith |
| mathd_algebra_451 | simp_all ⟶ have h₄ := h₁.symm ⟶ simp_all ⟶ rw [← h₂] ⟶ field_simp |
| mathd_algebra_206 | simp_all ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ nlinarith |
| mathd_numbertheory_629 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  ·<br>    norm_num [Nat.lcm] ⟶ ring_nf ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht1, ht2⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num at ht1 ht2 <;> simp_all [Nat.lcm, Nat.gcd_eq_right]<br>  <;> norm_num at *<br>  <;> aesop |
| mathd_algebra_13 | constructor ⟶ simp_all ⟶ all_goals<br>  have h₁ := h₀ 0<br>  have h₂ := h₀ 2<br>  have h₃ := h₀ 4<br>  have h₄ := h₀ 5<br>  have h₅ := h₀ 6<br>  have h₆ := h₀ 7<br>  have h₇ := h₀ 8<br>  have h₈ := h₀ 9<br>  norm_num at h₁ h₂ h₃ h₄ h₅ h₆ h₇ h₈<br>  <;><br>  (try ring_nf at h₁ h₂ h₃ h₄ h₅ h₆ h₇ h₈) <;><br>  (try linarith) <;><br>  (try nlinarith)<br>  <;><br>  (try nlinarith [h₁, h₂, h₃, h₄, h₅, h₆, h₇, h₈])<br>  <;><br>  nlinarith |
| mathd_algebra_536 | norm_num ⟶ norm_num [Nat.factorial] ⟶ have h : Real.sqrt 9 = 3 := by norm_num [Real.sqrt_eq_iff_sq_eq] ⟶ nlinarith |
| amc12a_2008_p8 | ring_nf ⟶ have h₃ : y = 1 := by<br>  nlinarith [h₁] ⟶ field_simp [h₁, h₃] at h₂ ⊢ ⟶ have h₄ : x = Real.sqrt 2 := by<br>  nlinarith [Real.sqrt_nonneg 2, Real.sq_sqrt (show (0 : ℝ) ≤ 2 by norm_num)] ⟶ nlinarith |
| mathd_numbertheory_326 | ring_nf at h₀ ⟶ have : -n + n ^ 3 = 720 := by<br>  exact h₀ ⟶ have : n ^ 3 - n = 720 := by linarith ⟶ ring_nf ⟶ have h : n = 9 := by<br>  nlinarith [sq_nonneg (n - 9), sq_nonneg (n + 9)] ⟶ omega |
| induction_seq_mul2pnp1 | ring_nf ⟶ induction' n with n hn ⟶ omega ⟶ cases n ⟶ simp_all ⟶ simp_all [Nat.pow_succ, Nat.mul_add, Nat.add_mul] ⟶ omega |
| amc12b_2002_p6 | simp_all ⟶ have h₂ := h₁ 0 ⟶ constructor ⟶ simp_all ⟶ simp_all ⟶ linarith [h₁ 1, h₁ (-1)] |
| amc12_2000_p11 | simp_all ⟶ have h₂ : a ≠ 0 := by<br>  intro h<br>  have h₃ : (a:ℝ) = 0 := by simpa using h<br>  tauto ⟶ field_simp ⟶ simp_all ⟶ field_simp [h₀, h₂, mul_comm] ⟶ ring<br><;> field_simp [h₀, h₁, h₂]<br><;> ring ⟶ nlinarith [h₀, h₁, h₂, sq_nonneg (a - b)] |
| amc12_2001_p9 | have h₂ := h₀ 500 (by norm_num) 600 (by norm_num) ⟶ field_simp ⟶ norm_num at h₂ ⟶ norm_num at h₀ h₁ h₂ ⊢ ⟶ have h₃ := h₀ 500 (by norm_num) 600 ⟶ have h₄ := h₀ 600 (by norm_num) 500 (by norm_num) ⟶ norm_num at h₃ h₄ ⟶ nlinarith |
| mathd_numbertheory_690 | constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ constructor ⟶ all_goals norm_num [Nat.ModEq, Nat.ModEq] ⟶ ·<br>  intro a h<br>  rcases h with ⟨ha0, ha3, ha5, ha7, ha9⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases a <;> norm_num at ha0 ha3 ha5 ha7 ha9 <;><br>  (try simp_all) <;><br>  (try omega) <;><br>  (try nlinarith) |
| mathd_algebra_151 | have h1 : √27 ≥ 5 := by<br>  norm_num [Real.sqrt_le_iff]<br>  <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show (0 : ℝ) ≤ 27 by norm_num)] ⟶ have h2 : Real.sqrt 26 ≤ Real.sqrt 27 := by<br>  apply Real.sqrt_le_sqrt<br>  norm_num ⟶ have h3 : Real.sqrt 27 ≤ Real.sqrt 27 + 1 := by linarith [Real.sqrt_nonneg 27] ⟶ have h4 : Int.ceil (Real.sqrt 27) = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num<br>  <;> nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 by norm_num)] ⟶ simp_all ⟶ have h5 : ⌊Real.sqrt 26⌋ = 5 := by<br>  have h₅ : ⌊Real.sqrt 26⌋ = 5 := by<br>    rw [Int.floor_eq_iff]<br>    constructor<br>    ·<br>      norm_num<br>      nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)]<br>    ·<br>      norm_num<br>      nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)]<br>  exact h₅ ⟶ omega |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | rw [add_assoc] ⟶ apply Int.dvd_of_emod_eq_zero ⟶ field_simp ⟶ use x^2 + y^2 + z^2 - x * y - y * z - z * x ⟶ nlinarith |
| amc12a_2016_p3 | have h₁ := h₀ (3 / 8) (-(2 / 5)) (by norm_num) ⟶ have h₂ := h₀ (3/8) (-(2/5)) (by norm_num) ⟶ have h₃ := h₀ (3 / 8) (-(2 / 5)) (by norm_num) ⟶ have h₄ : Int.floor (3 / 8 / (-2 / 5 : ℝ)) = -1 := by<br>  norm_num [Int.floor_eq_iff]<br>  <;><br>  (try norm_num) <;><br>  (try simp_all [Int.floor_eq_iff]) <;><br>  (try constructor) <;><br>  (try linarith)<br>  <;><br>  (try<br>    {<br>      use -1<br>      norm_num<br>      <;><br>      (try norm_num) <;><br>      (try linarith)<br>    })<br>  <;><br>  (try<br>    {<br>      use -2<br>      norm_num<br>      <;><br>      (try norm_num) <;><br>      (try linarith)<br>    }) ⟶ simp_all ⟶ field_simp ⟶ norm_num at h₀ h₄ ⊢<br><;> simp_all<br><;> linarith |
| mathd_algebra_421 | have h₅ : b = a^2 + 4*a + 6 := h₀ ⟶ have h₆ := h₁ ⟶ have h₇ := h₂ ⟶ have h₈ := h₃ ⟶ field_simp at h₅ h₆ h₇ h₈ ⟶ simp_all ⟶ nlinarith [sq_nonneg (a - c)] |
| imo_1964_p1_2 | intro h ⟶ have h₁ := h ⟶ simp_all ⟶ have h₂ : (7 : ℕ) ∣ (2^n + 1) := h₁ ⟶ have h₃ : (2^n + 1) % 7 = 0 := by<br>  omega ⟶ have h₄ : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by<br>  have : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by<br>    have : ∀ n : ℕ, 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by<br>      intro n<br>      induction n with<br>      \| zero =><br>        simp<br>      \| succ n ih =><br>        simp [pow_succ, ih]<br>        <;> omega<br>    exact this n<br>  exact this ⟶ omega |
| amc12b_2003_p17 | field_simp ⟶ rw [← Real.exp_log (by nlinarith : 0 < x * y)] ⟶ have h₃ : x * y > 0 := by<br>  have h₃₁ : 0 < x := h₀.1<br>  have h₃₂ : 0 < y := h₀.2<br>  have h₃₃ : 0 < x * y := mul_pos h₃₁ h₃₂<br>  exact h₃₃ ⟶ field_simp ⟶ have h₄ : x * y > 0 := by nlinarith ⟶ have h₅ : (x ^ 2 * y) > 0 := mul_pos (pow_pos h₀.1 2) h₀.2 ⟶ have h₆ : x * y > 0 := by nlinarith ⟶ have h₇ := h₀.2 ⟶ have h₈ : x > 0 := h₀.1 ⟶ have h₉ : x * y > 0 := by linarith ⟶ field_simp [Real.log_mul, Real.log_rpow, h₀.1, h₀.2] at h₁ h₂ ⊢ ⟶ nlinarith |
| imo_1961_p1 | ring_nf ⟶ have h₇ : 0 < a := by linarith ⟶ have h₈ : 0 < b^2 := by nlinarith ⟶ simp_all ⟶ constructor ⟶ nlinarith ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₃)] |
| mathd_algebra_509 | field_simp [Real.sqrt_eq_iff_sq_eq, sq, mul_comm] ⟶ have h1 : Real.sqrt 80 = 4 * Real.sqrt 5 := by<br>  rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num<br>  <;> ring_nf <;> norm_num<br>  <;> linarith [Real.sqrt_nonneg 5] ⟶ ring_nf ⟶ simp_all ⟶ have h2 : Real.sqrt 845 = Real.sqrt 5 * 13 := by<br>  have h3 : Real.sqrt 845 = Real.sqrt (5 * 13^2) := by norm_num<br>  rw [h3]<br>  have h4 : Real.sqrt (5 * 13^2) = Real.sqrt 5 * 13 := by<br>    rw [Real.sqrt_eq_iff_mul_self_eq (by positivity) (by positivity)]<br>    nlinarith [sq_sqrt (show (0 : ℝ) ≤ (5 : ℝ) by norm_num),<br>      sq_sqrt (show (0 : ℝ) ≤ (13 : ℝ) by norm_num),<br>      sq_nonneg (Real.sqrt 5 - 13)]<br>  rw [h4] ⟶ have h3 : Real.sqrt 45 = Real.sqrt 9 * Real.sqrt 5 := by<br>  have h3 : Real.sqrt 45 = Real.sqrt (9 * 5) := by norm_num<br>  rw [h3]<br>  have h4 : Real.sqrt (9 * 5) = Real.sqrt 9 * Real.sqrt 5 := by<br>    rw [Real.sqrt_mul] <;> norm_num<br>  rw [h4]<br>  <;> ring_nf <;> norm_num ⟶ ring_nf ⟶ have h4 : Real.sqrt 9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ have h5 : √4 = 2 := by<br>  rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num ⟶ field_simp ⟶ simp_all ⟶ ring<br><;> norm_num<br><;> linarith [Real.sqrt_pos.mpr (show (0 : ℝ) < 5 by norm_num)] |
| mathd_algebra_59 | rw [eq_comm] at h₀ ⟶ norm_num at h₀ ⟶ rw [show (4 : ℝ) = 2 ^ 2 by norm_num] at h₀ ⟶ field_simp [pow_two] at h₀ ⟶ rw [← mul_right_inj' two_ne_zero] ⟶ norm_num at h₀ ⟶ have h₁ : (4 : ℝ) ^ b = 4 := by linarith ⟶ simp_all ⟶ apply_fun fun x => Real.logb 4 x at h₁ ⟶ simp_all |
| mathd_algebra_323 | field_simp ⟶ have h₁ := h 3 ⟶ have h₂ := h (-2) ⟶ have h₃ := h 12 ⟶ have h₄ := h 19 ⟶ have h₅ := h 0 ⟶ norm_num at h₁ h₂ h₃ h₄ h₅ ⟶ have h₆ : σ.symm 19 = 3 := by<br>  have h₆₁ : σ 3 = 19 := h₁<br>  have h₆₂ : σ.symm 19 = 3 := by<br>    have h₆₃ : σ 3 = 19 := h₁<br>    have h₆₄ : σ.symm 19 = 3 := by<br>      have h₆₅ : σ 3 = 19 := h₁<br>      have h₆₆ : σ.symm 19 = 3 := by<br>        rw [← h₆₅]<br>        norm_num<br>      exact h₆₆<br>    exact h₆₄<br>  exact h₆₂ ⟶ simp_all |
| aime_1983_p9 | ring_nf ⟶ have h₁ : Real.sin x ≥ 0 := Real.sin_nonneg_of_nonneg_of_le_pi (by linarith) (by linarith [Real.pi_pos]) ⟶ simp_all ⟶ field_simp ⟶ rw [le_div_iff (by nlinarith [Real.sin_pos_of_pos_of_lt_pi h₀.1 h₀.2])] ⟶ have h₂ := cos_sq_add_sin_sq x ⟶ nlinarith [sq_nonneg (6 * x * Real.sin x - 4), h₁, h₂] |
| aime_1991_p1 | rw [← mul_right_inj' (two_ne_zero' ℕ)] ⟶ simp_all ⟶ have h₃ : x ≤ 71 := by<br>  nlinarith ⟶ have h₄ : y ≤ 71 := by<br>  nlinarith ⟶ have h₅ : x * y ≤ 71 := by<br>  nlinarith ⟶ have h₆ : x ≤ 71 := by nlinarith ⟶ simp_all ⟶ have h₇ : y ≥ 2 := by<br>  nlinarith ⟶ have h₈ : x ≥ 3 := by<br>  by_contra h<br>  push_neg at h<br>  nlinarith ⟶ interval_cases x <;> try {<br>  omega<br>} <;> try {<br>  omega<br>} ⟶ nlinarith |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | have h₃ : 0 < x * y := mul_pos h₀.1 h₀.2 ⟶ have h₄ := sq_nonneg (x - y) ⟶ field_simp ⟶ have h₅ : (Real.sqrt (x * y) * (x - y)) ^ 2 = (x + y) ^ 2 := by<br>  rw [h₂]<br>  <;> ring_nf<br>  <;> nlinarith [h₀.1, h₀.2, h₁] ⟶ rw [eq_comm] at h₅ ⟶ rw [← sub_nonneg] ⟶ ring_nf ⟶ ring_nf at h₅ ⟶ nlinarith [sq_sqrt (by nlinarith : 0 ≤ x * y), sq_nonneg (x + y - 2 * Real.sqrt (x * y)),<br>  sq_nonneg (x - y - 2 * Real.sqrt (x * y))] |
