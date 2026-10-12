# Proof search: phase3_search_shape_n16_prior02

Run `phase3_search_shape_n16_prior02` on miniF2F-valid, git `874e8fe559e2fa0332e8fd3b8370c4baf0a3eec9`, config `experiments/configs/phase3_search_shape_n16_prior02.toml` (copied as `config.toml`). Started 2026-10-12T19:56:08+00:00, 61.2 min wall, 46 CPUs, load average 19.2 at start.

**Solved 154/244 (63.1%).** Solved only with proofs of 2 or more steps: 64. Verification failures (bugs): 0. Proofs that also verify without the per-step heartbeat wrappers: 154/154. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 54 | 0.771 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 20 | 0.444 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 2 | 0.1 |
| algebra | 18 | 16 | 0.889 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 90 | 113 | 136 | 144 | 146 | 151 | 154 |
| solve rate | 36.9% | 46.3% | 55.7% | 59.0% | 59.8% | 61.9% | 63.1% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 17 | 36 | 61 | 74 | 108 | 120 | 137 | 145 | 147 | 151 | 152 | 154 | 154 | 154 |
| solve rate | 7.0% | 14.8% | 25.0% | 30.3% | 44.3% | 49.2% | 56.1% | 59.4% | 60.2% | 61.9% | 62.3% | 63.1% | 63.1% | 63.1% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 57 | 83 | 115 | 127 | 134 | 138 | 145 | 147 | 150 | 151 | 153 | 154 | 154 | 154 |
| solve rate | 23.4% | 34.0% | 47.1% | 52.0% | 54.9% | 56.6% | 59.4% | 60.2% | 61.5% | 61.9% | 62.7% | 63.1% | 63.1% | 63.1% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 154 |
| expansion_budget | 83 |
| wall_clock_budget | 4 |
| frontier_exhausted | 3 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 24.9 | 3 | 64 | 64 | 6073 |
| nodes | 75.1 | 12 | 228 | 373 | 18319 |
| edges | 425 | 41.5 | 1218 | 1353 | 103725 |
| lean_seconds | 262 | 7.75 | 628 | 3584 | 63980 |
| wall_seconds | 311 | 35.7 | 687 | 3617 | 75808 |
| duplicates | 89.1 | 7 | 278 | 514 | 21749 |
| errors | 236 | 20 | 679 | 1020 | 57496 |
| timeouts | 5.52 | 0 | 6 | 226 | 1348 |
| repl_failures | 0.0082 | 0 | 0 | 2 | 2 |
| verification_seconds | 1.78 | 0.548 | 4.88 | 32.5 | 435 |

solved (154 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.29 | 1 | 5 | 53 | 506 |
| nodes | 11.3 | 5 | 21 | 266 | 1739 |
| edges | 47 | 11.5 | 89 | 1113 | 7242 |
| lean_seconds | 19.9 | 1.72 | 30 | 605 | 3071 |
| wall_seconds | 37.6 | 13.4 | 68.4 | 677 | 5792 |
| duplicates | 7.54 | 1 | 14 | 199 | 1161 |
| errors | 27.2 | 6 | 44 | 624 | 4187 |
| timeouts | 0.195 | 0 | 0 | 16 | 30 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.82 | 1.46 | 7.05 | 32.5 | 435 |

unsolved (90 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 61.9 | 64 | 64 | 64 | 5567 |
| nodes | 184 | 182 | 275 | 373 | 16580 |
| edges | 1072 | 1088 | 1313 | 1353 | 96483 |
| lean_seconds | 677 | 367 | 1824 | 3584 | 60909 |
| wall_seconds | 778 | 501 | 1884 | 3617 | 70017 |
| duplicates | 229 | 226 | 352 | 514 | 20588 |
| errors | 592 | 598 | 770 | 1020 | 53309 |
| timeouts | 14.6 | 1 | 36 | 226 | 1318 |
| repl_failures | 0.0222 | 0 | 0 | 2 | 2 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 61871 | 55022 | 86.0% | 0.889 | 13821 | 13813 | 29179 | 27844 | 0 | 1338 | 0 | 67 | 0 |
| simp_all | 5858 | 2986 | 4.7% | 0.51 | 1380 | 2257 | 2221 | 2218 | 0 | 3 | 0 | 6 | 22 |
| nlinarith | 5881 | 2217 | 3.5% | 0.377 | 28 | 28 | 5825 | 5822 | 0 | 3 | 0 | 26 | 28 |
| omega | 6073 | 1394 | 2.2% | 0.23 | 39 | 6 | 6028 | 6027 | 0 | 0 | 1 | 26 | 26 |
| field_simp | 5971 | 1093 | 1.7% | 0.183 | 967 | 679 | 4325 | 4324 | 0 | 1 | 0 | 0 | 7 |
| ring_nf | 6017 | 887 | 1.4% | 0.147 | 1175 | 4840 | 2 | 0 | 0 | 2 | 0 | 11 | 18 |
| constructor | 6047 | 177 | 0.3% | 0.0292 | 660 | 98 | 5289 | 5288 | 0 | 0 | 1 | 14 | 20 |
| rfl | 6007 | 174 | 0.3% | 0.0289 | 5 | 28 | 5974 | 5973 | 0 | 1 | 0 | 4 | 4 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 90 |
| 2 | 24 |
| 3 | 22 |
| 4 | 7 |
| 5 | 4 |
| 6 | 5 |
| 7 | 2 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | rw [h₀, h₁] ⟶ ring_nf |
| mathd_algebra_35 | simp_all ⟶ ring_nf |
| mathd_algebra_43 | simp only [h₀, h₁, h₂] at * ⟶ nlinarith |
| mathd_algebra_214 | simp [h₀, h₁] at * ⟶ nlinarith |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_numbertheory_461 | simp_all ⟶ constructor |
| amc12b_2003_p9 | simp only [h₀] at h₁ ⊢ ⟶ nlinarith |
| mathd_algebra_28 | obtain ⟨x, hx⟩ := h₁ ⟶ simp [h₀, hx] at * ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| mathd_algebra_73 | apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ ring_nf at h₀ ⊢ ⟶ linear_combination h₀ |
| induction_divisibility_3divnto3m2n | apply Nat.dvd_of_mod_eq_zero ⟶ have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;> simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod] |
| mathd_algebra_132 | field_simp ⟶ simp only [h₀, h₁, h₂] at * ⟶ nlinarith |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_245 | field_simp [h₀, mul_comm] ⟶ ring_nf |
| mathd_algebra_116 | field_simp [h₀] at h₁ ⊢ ⟶ nlinarith [sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)] |
| amc12a_2009_p9 | simp_all ⟶ have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1, h₀ (-1)] |
| amc12_2001_p9 | have h₂ := h₀ 500 (by norm_num) 600 (by norm_num) ⟶ field_simp ⟶ have h₃ := h₀ 600 (by norm_num) 500 (by norm_num) ⟶ norm_num at h₂ h₃ ⟶ nlinarith |
| mathd_algebra_159 | simp [h₀, h₁] at * ⟶ nlinarith |
| amc12a_2013_p7 | simp_all ⟶ nlinarith |
| mathd_algebra_140 | have h₂ := h₁ 0 ⟶ simp_all ⟶ nlinarith [h₀.1, h₀.2.1, h₀.2.2, h₁ 0, h₁ 1, h₁ (-1), h₁ (1 / 2), h₁ (0.5)] |
| mathd_numbertheory_64 | constructor ⟶ constructor ⟶ ·<br>  intro x hx<br>  simp [Nat.ModEq] at hx<br>  omega |
| mathd_algebra_192 | simp_all ⟶ ring_nf<br><;> simp [Complex.ext_iff, pow_two, pow_three]<br><;> norm_num<br><;> ring_nf<br><;> norm_num<br><;> ring_nf<br><;> norm_num |
| mathd_numbertheory_780 | rcases h₁ with ⟨h₁_left, h₁_right⟩ ⟶ interval_cases m <;> omega |
| mathd_numbertheory_326 | apply Eq.symm ⟶ ring_nf at h₀ ⟶ nlinarith [h₀, sq_nonneg (n - 4), sq_nonneg (n + 4)] |
| mathd_algebra_11 | field_simp [sub_ne_zero.2 h₀, sub_ne_zero.2 h₁] at h₂ ⊢ ⟶ nlinarith |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all ⟶ simp [Complex.ext_iff, Complex.I_mul_I] at h₀ h₁ ⊢ ⟶ constructor <;> linarith |
| mathd_algebra_267 | field_simp [h₀, h₁, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₂ ⟶ nlinarith |
| mathd_numbertheory_257 | norm_num at h₁ ⟶ omega |
| mathd_algebra_59 | norm_num at h₀ ⟶ have h₁ : (4 : ℝ) ^ b = 4 := by linarith ⟶ have h₂ : b = 1 := by<br>  apply_fun fun x => Real.logb 4 x at h₁<br>  simp at h₁<br>  linarith ⟶ simp_all |
| mathd_algebra_151 | have h1 : ⌈Real.sqrt 27⌉ = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num [Real.sqrt_le_iff, Real.lt_sqrt] <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sqrt_nonneg 26] ⟶ have h2 : ⌊Real.sqrt 26⌋ = 5 := by<br>  rw [Int.floor_eq_iff]<br>  norm_num<br>  constructor <;> norm_num <;><br>    nlinarith [Real.sq_sqrt (show 0 ≤ 26 by norm_num), Real.sqrt_nonneg 26] ⟶ omega |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp ⟶ rw [div_le_iff (by positivity)] ⟶ ring_nf ⟶ nlinarith [Real.sqrt_nonneg 2, sq_sqrt (show 0 ≤ 2 by norm_num), mul_self_nonneg (x - Real.sqrt 2 / 2)] |
| mathd_algebra_22 | rw [Real.logb] ⟶ field_simp ⟶ ring_nf |
| amc12a_2013_p8 | field_simp at h₃ ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₂) ⟶ nlinarith |
| mathd_numbertheory_22 | have h₂ : b ≤ 9 := by linarith ⟶ interval_cases b <;> norm_num at h₀ h₁ ⊢ |
| amc12b_2003_p17 | field_simp ⟶ field_simp [Real.log_mul, h₀.1.ne', h₀.2.ne'] at h₁ h₂ ⊢ ⟶ nlinarith |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_numbertheory_35 | have h₁ : 24 ∣ Nat.sqrt 196 := h₀ 24 ⟶ have h₂ := h₀ 24 ⟶ norm_num at h₂ |
| mathd_algebra_536 | norm_num [Nat.factorial] ⟶ rw [mul_comm] ⟶ norm_num [show (8 + Real.sqrt (9 : ℝ)) * 6 / 2 = 33 by<br>  have h₁ : Real.sqrt (9 : ℝ) = 3 := by<br>    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  rw [h₁]<br>  norm_num] |
| mathd_algebra_251 | have h₂ : x = 2 := by<br>  field_simp [h₀] at h₁<br>  linarith ⟶ simp_all |
| amc12_2000_p11 | field_simp [h₀.1, h₀.2] ⟶ ring_nf ⟶ nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), sq_nonneg (a * b), sq_nonneg (a * b - b), sq_nonneg (a * b + b)] |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| amc12a_2017_p2 | field_simp ⟶ nlinarith |
| mathd_algebra_181 | have h₂ : n - 3 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ have h₃ : n = 11 := by<br>  field_simp at h₁<br>  linarith ⟶ simp_all |
| mathd_algebra_206 | simp only [h₀, h₁, h₂, h₃] at * ⟶ nlinarith [sq_pos_of_ne_zero (show 2 * a - b ≠ 0 by intro h; apply h₁ <;> linarith)] |
| induction_ineq_nsqlefactn | induction' h₀ with n hn ⟶ simp [Nat.factorial] ⟶ cases n with<br>\| zero => contradiction<br>\| succ n =><br>  cases n with<br>  \| zero => contradiction<br>  \| succ n =><br>    simp_all [Nat.factorial_succ, Nat.mul_succ]<br>    nlinarith |
| amc12b_2020_p5 | simp_all [mul_comm] ⟶ ring_nf at h₀ h₁ ⟶ field_simp at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ simp_all ⟶ omega |
| mathd_numbertheory_690 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  ·<br>    norm_num [Nat.ModEq] ⟶ ·<br>  intro a h<br>  rcases h with ⟨h1, h2, h3, h4, h5⟩<br>  by_contra h6<br>  push_neg at h6<br>  interval_cases a <;> norm_num [Nat.ModEq, Nat.ModEq] at h2 h3 h4 h5 <;> omega |
| mathd_numbertheory_629 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  ·<br>    norm_num [Nat.lcm] ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht1, ht2⟩<br>  by_contra h<br>  push_neg at h<br>  have h1 : t ≤ 18 := by linarith<br>  interval_cases t <;> norm_num at ht1 ht2 ⊢<br>  all_goals omega |
| mathd_algebra_433 | have h₁ : f 8 = 3 * Real.sqrt (2 * 8 - 7) - 8 := by<br>  rw [h₀] ⟶ rw [h₁] ⟶ ring_nf at h₁ ⊢ ⟶ simp_all ⟶ ring_nf at h₁ ⊢ ⟶ nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num)] |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | refine' ⟨_, _⟩ ⟶ all_goals<br>  simp_all [Complex.ext_iff, add_comm] ⟶ all_goals<br>  ring_nf at *<br>  constructor<br>  nlinarith<br>  nlinarith |
| amc12b_2002_p6 | constructor ⟶ {<br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  have h₅ := h₁ 2<br>  have h₆ := h₁ (-2)<br>  norm_num at h₂ h₃ h₄ h₅ h₆<br>  nlinarith [sq_pos_of_ne_zero h₀.1, sq_pos_of_ne_zero h₀.2]<br>} ⟶ apply mul_left_cancel₀ (sub_ne_zero.mpr h₀.2) ⟶ nlinarith [h₀.1, h₀.2, h₁ 0, h₁ 2, h₁ (a + b)] |
| aime_1984_p15 | field_simp at h₀ h₁ h₂ h₃ ⟶ nlinarith |
| mathd_numbertheory_32 | rw [Finset.sum_eq_multiset_sum] ⟶ have h₁ : S = Finset.filter (λ n => n ∣ 36) (Finset.range (37)) := by<br>  ext n<br>  simp [h₀]<br>  <;> aesop ⟶ rw [h₁] ⟶ constructor |
| induction_seq_mul2pnp1 | ring_nf ⟶ induction' n with n ih ⟶ all_goals simp_all [pow_succ, Nat.mul_succ] ⟶ cases n <;> simp_all [Nat.mul_succ, Nat.pow_succ, Nat.mul_zero, Nat.add_zero]<br><;> omega |
| amc12a_2015_p10 | ring_nf at h₂ ⟶ have h₃ : y ≠ 0 := by linarith ⟶ have h₄ : y < x := h₁ ⟶ have h₅ : x ≤ 80 := by<br>  nlinarith ⟶ have h₆ : y < 80 := by linarith ⟶ interval_cases y <;> omega |
| mathd_algebra_77 | refine' ⟨_, _⟩ ⟶ all_goals simp_all [h₂, h₃, h₄] ⟶ all_goals<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  nlinarith |
| mathd_algebra_13 | constructor ⟶ next =><br>  have h₁ := h₀ 4<br>  have h₂ := h₀ 8<br>  norm_num [pow_two] at h₁ h₂<br>  field_simp at h₁ h₂<br>  all_goals ring_nf at h₁ h₂<br>  all_goals linarith ⟶ simp_all ⟶ next =><br>  have h₁ := h₀ 0<br>  have h₂ := h₀ 6<br>  have h₃ := h₀ 12<br>  have h₄ := h₀ 14<br>  have h₅ := h₀ 17<br>  have h₆ := h₀ 20<br>  have h₇ := h₀ 22<br>  have h₈ := h₀ 25<br>  have h₉ := h₀ 28<br>  have h₁₀ := h₀ 31<br>  norm_num at *<br>  <;> linarith |
| imo_1984_p2 | rcases h₀ with ⟨h₀_left, h₀_right⟩ ⟶ have h₅ : 0 < a + b := by linarith ⟶ contrapose! h₁ ⟶ have h₆ : a + b < 19 := by linarith ⟶ have h₇ : a < 19 := by linarith ⟶ have h₈ : b < 19 := by linarith ⟶ interval_cases a <;> interval_cases b <;> omega |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | rw [add_assoc] ⟶ rw [add_assoc] ⟶ use x^2 + y^2 + z^2 - x * y - x * z - y * z ⟶ nlinarith |
| mathd_algebra_493 | simp only [h₀, Real.sqrt_sq, sq, mul_comm] ⟶ have h₁ : Real.sqrt 4 = 2 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ have h₂ : ∀ x, f x = x^2 - 4 * Real.sqrt x + 1 := h₀ ⟶ simp_all ⟶ ring_nf ⟶ have h₃ : Real.sqrt 9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ nlinarith |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | have h₃ : Real.sqrt (x * y) ≥ 0 := Real.sqrt_nonneg (x * y) ⟶ simp_all ⟶ nlinarith [sq_sqrt (mul_nonneg (le_of_lt h₀.1) (le_of_lt h₀.2)),<br>  sq_nonneg (Real.sqrt (x * y) - (x - y) / 2)] |
| mathd_algebra_451 | simp_all ⟶ have h₄ := h₀ ⟶ have h₅ := h₁.symm ⟶ have h₆ := h₁.symm ⟶ have h₇ := h₂.symm ⟶ simp_all |
| imo_1961_p1 | ring_nf ⟶ refine' ⟨_, _, _⟩ ⟶ nlinarith ⟶ nlinarith ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₁), sq_pos_of_ne_zero (sub_ne_zero.mpr h₂), sq_pos_of_ne_zero (sub_ne_zero.mpr h₃)] |
| amc12a_2008_p8 | ring_nf ⟶ have h₃ : y = 1 := by nlinarith ⟶ rw [h₃] at h₂ ⟶ have h₄ : x^2 = 2 := by<br>  nlinarith ⟶ have h₅ : x = Real.sqrt 2 := by<br>  nlinarith [Real.sqrt_nonneg 2, Real.sq_sqrt (show 0 ≤ 2 by norm_num)] ⟶ nlinarith |
| aime_1983_p9 | ring_nf ⟶ have h₁ : 0 < Real.sin x := Real.sin_pos_of_pos_of_lt_pi h₀.1 (by linarith [Real.pi_pos]) ⟶ field_simp ⟶ rw [le_div_iff (by nlinarith [Real.sin_pos_of_pos_of_lt_pi h₀.1 (by linarith : x < Real.pi)])] ⟶ nlinarith [sq_nonneg (x * Real.sin x - 2 / 3), sq_nonneg (x - Real.sin x), sq_nonneg (x + Real.sin x),<br>  sq_nonneg (x - 2 / 3), sq_nonneg (x + 2 / 3)]<br><;> linarith<br><;> linarith<br><;> linarith<br><;> linarith<br><;> linarith |
