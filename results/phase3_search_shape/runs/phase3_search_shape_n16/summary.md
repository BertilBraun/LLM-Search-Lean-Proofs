# Proof search: phase3_search_shape_n16

Run `phase3_search_shape_n16` on miniF2F-valid, git `8704fef23dfee7f77327210cc6971a469b3159b7`, config `experiments/configs/phase3_search_shape_n16.toml` (copied as `config.toml`). Started 2026-10-12T16:52:15+00:00, 60.8 min wall, 46 CPUs, load average 15.7 at start.

**Solved 156/244 (63.9%).** Solved only with proofs of 2 or more steps: 68. Verification failures (bugs): 1. Proofs that also verify without the per-step heartbeat wrappers: 156/156. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 56 | 0.8 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 20 | 0.444 |
| aime | 15 | 3 | 0.2 |
| imo | 20 | 2 | 0.1 |
| algebra | 18 | 15 | 0.833 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 88 | 117 | 141 | 143 | 151 | 153 | 156 |
| solve rate | 36.1% | 48.0% | 57.8% | 58.6% | 61.9% | 62.7% | 63.9% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 15 | 26 | 56 | 81 | 110 | 126 | 138 | 145 | 150 | 152 | 153 | 155 | 155 | 156 |
| solve rate | 6.1% | 10.7% | 23.0% | 33.2% | 45.1% | 51.6% | 56.6% | 59.4% | 61.5% | 62.3% | 62.7% | 63.5% | 63.5% | 63.9% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 56 | 81 | 117 | 127 | 136 | 139 | 144 | 149 | 151 | 152 | 153 | 155 | 155 | 156 |
| solve rate | 23.0% | 33.2% | 48.0% | 52.0% | 55.7% | 57.0% | 59.0% | 61.1% | 61.9% | 62.3% | 62.7% | 63.5% | 63.5% | 63.9% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 156 |
| expansion_budget | 82 |
| frontier_exhausted | 4 |
| wall_clock_budget | 2 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 24.2 | 3 | 64 | 64 | 5912 |
| nodes | 73.9 | 11 | 233 | 385 | 18040 |
| edges | 413 | 39.5 | 1209 | 1360 | 100776 |
| lean_seconds | 285 | 7.05 | 727 | 3588 | 69582 |
| wall_seconds | 327 | 28.8 | 794 | 3609 | 79666 |
| duplicates | 83 | 7 | 262 | 549 | 20259 |
| errors | 230 | 19 | 699 | 986 | 56006 |
| timeouts | 6.14 | 0 | 13 | 173 | 1497 |
| repl_failures | 0.0082 | 0 | 0 | 2 | 2 |
| verification_seconds | 2.04 | 0.952 | 4.55 | 24.8 | 497 |

solved (156 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.25 | 1 | 4 | 56 | 507 |
| nodes | 10.4 | 5 | 22 | 122 | 1616 |
| edges | 45.1 | 12.5 | 80 | 939 | 7039 |
| lean_seconds | 35.1 | 1.95 | 33.9 | 2150 | 5472 |
| wall_seconds | 51.5 | 13.9 | 88.8 | 2177 | 8035 |
| duplicates | 7.65 | 1 | 14 | 191 | 1193 |
| errors | 25.4 | 6 | 45 | 586 | 3970 |
| timeouts | 0.955 | 0 | 0 | 104 | 149 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 3.19 | 1.43 | 7.16 | 24.8 | 497 |

unsolved (88 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 61.4 | 64 | 64 | 64 | 5405 |
| nodes | 187 | 186 | 289 | 385 | 16424 |
| edges | 1065 | 1106 | 1302 | 1360 | 93737 |
| lean_seconds | 729 | 410 | 2376 | 3588 | 64110 |
| wall_seconds | 814 | 503 | 2391 | 3609 | 71631 |
| duplicates | 217 | 212 | 332 | 549 | 19066 |
| errors | 591 | 586 | 783 | 986 | 52036 |
| timeouts | 15.3 | 2 | 43 | 173 | 1348 |
| repl_failures | 0.0227 | 0 | 0 | 2 | 2 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 60017 | 59656 | 85.8% | 0.994 | 12960 | 13060 | 28780 | 27292 | 0 | 1489 | 0 | 65 | 0 |
| simp_all | 5699 | 3300 | 4.7% | 0.579 | 1573 | 2055 | 2071 | 2068 | 0 | 3 | 0 | 8 | 23 |
| nlinarith | 5785 | 2291 | 3.3% | 0.396 | 28 | 25 | 5732 | 5731 | 0 | 1 | 0 | 26 | 27 |
| omega | 5912 | 1733 | 2.5% | 0.293 | 45 | 19 | 5848 | 5848 | 0 | 0 | 0 | 30 | 30 |
| field_simp | 5806 | 1171 | 1.7% | 0.202 | 1025 | 582 | 4199 | 4197 | 0 | 1 | 1 | 0 | 4 |
| ring_nf | 5856 | 1003 | 1.4% | 0.171 | 1405 | 4449 | 2 | 0 | 0 | 2 | 0 | 10 | 13 |
| constructor | 5882 | 208 | 0.3% | 0.0353 | 755 | 48 | 5079 | 5078 | 0 | 0 | 1 | 13 | 20 |
| rfl | 5819 | 192 | 0.3% | 0.0331 | 5 | 21 | 5793 | 5792 | 0 | 1 | 0 | 5 | 5 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 88 |
| 2 | 32 |
| 3 | 18 |
| 4 | 8 |
| 5 | 8 |
| 6 | 1 |
| 7 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_43 | simp [h₀, h₁, h₂] at *; ⟶ nlinarith |
| mathd_algebra_48 | simp_all ⟶ ring_nf |
| mathd_algebra_214 | simp only [h₀, h₁] at * ⟶ nlinarith |
| mathd_algebra_547 | simp [h₀, h₁, Real.sqrt_eq_iff_sq_eq, sq, mul_comm, mul_assoc, mul_left_comm] ⟶ rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num |
| amc12b_2003_p9 | simp_all only [h₀, sub_eq_add_neg] ⟶ nlinarith |
| mathd_algebra_192 | simp [h₀, h₁, h₂, Complex.ext_iff, pow_two, mul_add, mul_sub, sub_eq_add_neg, add_assoc, add_left_comm] ⟶ norm_num |
| amc12a_2015_p10 | have : y < 26 := by nlinarith ⟶ interval_cases y <;> omega |
| amc12a_2009_p9 | have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1] |
| mathd_algebra_245 | field_simp [h₀, pow_succ, mul_assoc, mul_comm, mul_left_comm] ⟶ ring_nf |
| numbertheory_sqmod4in01d | have h : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases h with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_234 | field_simp at h₀ ⊢ ⟶ nlinarith [h₀, sq_nonneg d] |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| induction_divisibility_3divnto3m2n | have h : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases h with (h \| h \| h) <;><br>simp [h, Nat.dvd_iff_mod_eq_zero, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_mod] |
| mathd_algebra_132 | field_simp ⟶ simp only [h₀, h₁, h₂] at * ⟶ nlinarith |
| mathd_algebra_116 | field_simp [h₀, Real.sqrt_eq_iff_mul_self_eq] at h₁ ⊢ ⟶ nlinarith [sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)] |
| mathd_numbertheory_22 | have h₂ : b = 3 ∨ b = 1 := by<br>  interval_cases b <;> norm_num at h₁ ⊢ <;> omega ⟶ omega |
| mathd_algebra_110 | simp_all ⟶ ring<br><;> simp [Complex.ext_iff, pow_two]<br><;> ring |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | rintro x (hx : 0 < x) ⟶ field_simp ⟶ rw [div_le_iff (by positivity)] ⟶ nlinarith [sq_sqrt (show (0 : ℝ) ≤ 2 by norm_num),<br>  sq_nonneg (x - Real.sqrt 2 / 2),<br>  sq_nonneg (x - 1 / 2)] |
| mathd_algebra_73 | apply mul_right_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ linear_combination h₀ |
| mathd_numbertheory_257 | rw [Finset.sum_range_succ] at h₁ ⟶ have h₂ : x = 45 := by<br>  norm_num [Finset.sum_range_succ, Nat.add_comm] at h₁<br>  omega ⟶ omega |
| amc12a_2013_p7 | simp_all ⟶ nlinarith |
| amc12a_2013_p8 | field_simp at h₃ ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₂) ⟶ nlinarith |
| mathd_algebra_28 | simp_all ⟶ obtain ⟨x, hx⟩ := h₁ ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| mathd_algebra_159 | simp only [h₀, h₁] at * ⟶ nlinarith |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| mathd_algebra_140 | have h₂ := h₁ (-1) ⟶ have h₃ := h₁ 1 ⟶ ring_nf at h₂ h₃ ⟶ nlinarith [h₀.1, h₀.2.1, h₀.2.2, h₁ 0, h₁ 1, h₁ 2] |
| mathd_numbertheory_35 | have h₁ := h₀ 196 ⟶ norm_num at h₀ h₁ |
| mathd_numbertheory_109 | simp_all only [Finset.sum_range, Nat.mul_comm, Nat.mul_one, Nat.mul_zero] ⟶ constructor |
| mathd_algebra_536 | norm_num [Nat.factorial, Real.sqrt_eq_iff_mul_self_eq]<br><;> ring_nf<br><;> norm_num<br><;> ring_nf<br><;> norm_num<br><;> ring_nf<br><;> norm_num<br><;> ring_nf<br><;> norm_num ⟶ have h₁ : 24 + Real.sqrt 9 * 3 = 33 := by<br>  have h₂ : Real.sqrt 9 = 3 := by<br>    rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num<br>  rw [h₂]<br>  norm_num<br>  <;><br>  ring_nf <;><br>  norm_num<br>  <;><br>  linarith ⟶ simp_all |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all ⟶ simp_all [Complex.ext_iff] ⟶ nlinarith |
| mathd_algebra_11 | field_simp [h₀, h₁, sub_eq_zero, sub_ne_zero, not_false_iff] at h₂ ⊢ ⟶ nlinarith |
| mathd_numbertheory_64 | constructor ⟶ constructor ⟶ ·<br>  intro x hx<br>  norm_num [Nat.ModEq] at hx<br>  omega |
| mathd_algebra_22 | field_simp [Real.logb, Real.log_pow] ⟶ ring_nf |
| mathd_numbertheory_232 | simp_all ⟶ rfl |
| mathd_numbertheory_32 | rw [Finset.sum_eq_multiset_sum] ⟶ have h₁ : S = Finset.filter (fun n : ℕ => n ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀, Finset.mem_filter, Finset.mem_range, Finset.mem_filter] ⟶ aesop |
| mathd_algebra_267 | have h₃ : x = 0 := by<br>  have h₃ : x - 1 ≠ 0 := by<br>    intro h<br>    apply h₀<br>    linarith<br>  have h₄ : x + 2 ≠ 0 := by<br>    intro h<br>    apply h₁<br>    linarith<br>  field_simp [h₃, h₄] at h₂<br>  nlinarith ⟶ simp_all |
| mathd_algebra_251 | have h₂ : x = 2 := by<br>  field_simp [h₀] at h₁<br>  linarith ⟶ simp_all |
| amc12_2000_p11 | field_simp [h₀.1, h₀.2, h₁] ⟶ nlinarith [sq_nonneg (a - b), h₀.1, h₀.2, h₁] |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| aime_1984_p15 | ring_nf at * ⟶ nlinarith |
| mathd_numbertheory_780 | rcases h₁ with ⟨h₁_1, h₁_2⟩ ⟶ interval_cases m <;> omega |
| mathd_algebra_181 | have h₂ : n - 3 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ field_simp at h₁ ⟶ nlinarith |
| amc12a_2017_p2 | field_simp [h₀, h₁, mul_comm] ⟶ nlinarith |
| mathd_numbertheory_326 | ring_nf at h₀ ⊢ ⟶ have h₁ : n = 9 := by<br>  nlinarith [pow_two n, pow_two (n - 9), pow_two (n + 9)] ⟶ omega |
| mathd_algebra_151 | have h1 : Int.ceil (Real.sqrt 27) = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor<br>  · norm_num<br>    nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show (0 : ℝ) ≤ 27 by norm_num)]<br>  · norm_num<br>    nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show (0 : ℝ) ≤ 27 by norm_num)] ⟶ have h2 : Int.floor (Real.sqrt 26) = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sq_sqrt (by norm_num : (0 : ℝ) ≤ 26), Real.sqrt_nonneg 26] ⟶ omega |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | refine ⟨?_,?_⟩ ⟶ all_goals<br>  simp_all [Complex.ext_iff]<br>  ring_nf<br>  <;><br>  (try constructor) <;><br>  (try linarith)<br>  <;><br>  (try omega) |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_numbertheory_629 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  ·<br>    norm_num ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht_lt, ht_lcm⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num [Nat.lcm] at ht_lcm <;> omega |
| mathd_algebra_206 | simp only [h₀, mul_add, mul_one, add_assoc, add_left_comm, add_comm] at * ⟶ simp_all ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ nlinarith |
| mathd_algebra_77 | constructor ⟶ all_goals simp_all only [h₂, h₃, h₄] ⟶ all_goals<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁)] |
| mathd_algebra_433 | have h₁ := h₀ 8 ⟶ simp_all only [h₀, h₁, mul_sub, sub_mul, mul_one, mul_add, mul_comm, mul_left_comm, mul_assoc] ⟶ norm_num ⟶ have h₁ : Real.sqrt 9 = 3 := by norm_num [Real.sqrt_eq_iff_sq_eq] ⟶ nlinarith |
| mathd_algebra_59 | rw [pow_three] at h₀ ⟶ rw [← mul_right_inj' (by norm_num : (4 : ℝ) ≠ 0)] ⟶ ring_nf at h₀ ⊢ ⟶ have h₁ : b = 1 := by<br>  have h₁ : (4 : ℝ) ^ b = 4 := by linarith<br>  have h₂ : b = 1 := by<br>    apply_fun (fun x => logb 4 x) at h₁<br>    field_simp at h₁<br>    ring_nf at h₁ ⊢<br>    linarith<br>  exact h₂ ⟶ simp_all |
| mathd_algebra_13 | constructor ⟶ {<br>  have h₁ := h₀ (-1)<br>  have h₂ := h₀ 1<br>  have h₃ := h₀ 2<br>  have h₄ := h₀ 3<br>  have h₅ := h₀ 4<br>  have h₆ := h₀ 5<br>  have h₇ := h₀ 6<br>  norm_num at h₁ h₂ h₃ h₄ h₅ h₆ h₇<br>  ring_nf at h₁ h₂ h₃ h₄ h₅ h₆ h₇<br>  linarith<br>} ⟶ simp_all ⟶ case right =><br>  have h₁ := h₀ 1<br>  have h₂ := h₀ 2<br>  have h₃ := h₀ 3<br>  have h₄ := h₀ 4<br>  have h₅ := h₀ 5<br>  have h₆ := h₀ 6<br>  have h₇ := h₀ 7<br>  have h₈ := h₀ 8<br>  have h₉ := h₀ 9<br>  have h₁₀ := h₀ 10<br>  norm_num at *<br>  <;> linarith |
| mathd_algebra_451 | simp_all ⟶ have h₄ := h₀ ⟶ have h₅ := h₁.symm ⟶ have h₆ := h₂.symm ⟶ simp_all |
| amc12b_2003_p17 | field_simp ⟶ have h₃ : x * y > 0 := mul_pos h₀.1 h₀.2 ⟶ have h₄ : x * y ≠ 0 := by linarith ⟶ simp_all [Real.log_mul, Real.log_rpow, mul_assoc] ⟶ nlinarith |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | have h₃ : Real.sqrt (x * y) ≥ 0 := Real.sqrt_nonneg _ ⟶ have h₄ : Real.sqrt (x * y) * (x - y) ≥ 0 := mul_nonneg h₃ (sub_nonneg.mpr h₁) ⟶ nlinarith [sq_sqrt (show 0 ≤ x * y from by nlinarith), sq_nonneg (x - y),<br>  sq_nonneg (x + y - 2 * Real.sqrt (x * y)), sq_nonneg (x + y),<br>  sq_nonneg (x - y - 2 * Real.sqrt (x * y))] |
| mathd_algebra_480 | have h₃ : (0 : ℝ) ≤ (Real.pi : ℝ) := by<br>  have h₃₁ : 0 ≤ Real.pi := by<br>    have h₃₂ : 0 ≤ Real.pi := by<br>      apply Real.pi_nonneg<br>    exact h₃₂<br>  exact h₃₁ ⟶ have h₄ : Real.pi < 4 := by<br>  have := Real.pi_lt_31416<br>  norm_num at this ⊢<br>  <;> linarith ⟶ simp_all |
| mathd_numbertheory_690 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  ·<br>    norm_num [Nat.ModEq] ⟶ ·<br>  rintro a ⟨ha_pos, ha1, ha2, ha3, ha4⟩<br>  by_contra h<br>  push_neg at h<br>  have h1 : a < 314 := by linarith [ha_pos]<br>  interval_cases a <;> norm_num [Nat.ModEq, Nat.mod_eq_of_lt] at ha1 ha2 ha3 ha4 <;> omega |
| amc12b_2002_p6 | constructor ⟶ case left =><br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  simp [h₀.1, h₀.2] at h₂ h₃ h₄<br>  nlinarith ⟶ have h₂ := h₁ (-a) ⟶ have h₃ := h₁ b ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₀.1), sq_pos_of_ne_zero (sub_ne_zero.mpr h₀.2)] |
| aime_1983_p9 | rw [le_div_iff (by nlinarith [Real.sin_pos_of_pos_of_lt_pi h₀.1 h₀.2])] ⟶ have h₁ : sin x ≤ 1 := by<br>  apply sin_le_one ⟶ have h₂ : 0 ≤ sin x ^ 2 := by nlinarith ⟶ nlinarith [sq_nonneg (x * sin x - 2 / 3), h₀.1, h₀.2, sin_le_one x, sin_sq_add_cos_sq x] |
| induction_seq_mul2pnp1 | induction' n with n hn ⟶ all_goals simp_all [Nat.succ_eq_add_one, Nat.add_assoc] ⟶ cases n ⟶ all_goals simp_all [Nat.pow_succ, Nat.mul_add, Nat.add_mul, Nat.mul_one, Nat.mul_zero, Nat.add_zero] ⟶ omega |
| mathd_algebra_89 | simp [h₀, mul_assoc, mul_comm, mul_left_comm, pow_add, pow_mul, mul_pow, mul_comm,<br>  mul_assoc, mul_left_comm] ⟶ field_simp ⟶ ring<br><;> simp_all<br><;> norm_cast<br><;> linarith |
| imo_1964_p1_2 | rw [Nat.dvd_iff_mod_eq_zero] ⟶ rw [← Nat.mod_add_div (2 ^ n) 7] ⟶ have : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by<br>  have : ∀ n : ℕ, 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by<br>    intro n<br>    induction n with<br>    \| zero =><br>      norm_num<br>    \| succ n ih =><br>      simp [Nat.pow_succ, Nat.mul_mod, ih]<br>      <;> omega<br>  exact this n ⟶ omega |
| amc12a_2016_p3 | simp_all ⟶ ring_nf ⟶ norm_num ⟶ have h₁ : ⌊-(15 / 16:ℝ)⌋ = -1 := by<br>  rw [Int.floor_eq_iff]<br>  norm_num<br>  <;><br>  norm_num<br>  <;><br>  apply And.intro<br>  <;> norm_num<br>  <;><br>  linarith ⟶ norm_num [h₁] |
| mathd_algebra_493 | simp only [h₀, sq, mul_assoc, mul_comm, mul_left_comm] ⟶ norm_num ⟶ have h₁ := Real.sqrt_nonneg 4 ⟶ have h₂ : Real.sqrt 4 = 2 := by rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ have h₃ : 0 ≤ Real.sqrt (16 - 4 * Real.sqrt 4 + 1) := by<br>  apply Real.sqrt_nonneg ⟶ simp_all ⟶ nlinarith [sq_sqrt (show 0 ≤ 16 - 4 * 2 + 1 by norm_num)] |
| imo_1961_p1 | ring_nf ⟶ simp_all ⟶ have h₇ : a > 0 := by linarith ⟶ refine' ⟨h₇, _, _⟩ ⟶ nlinarith ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂),<br>  sq_pos_of_ne_zero (sub_ne_zero_of_ne h₃), sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)] |
| amc12a_2008_p8 | ring_nf ⟶ simp_all [pow_two, Real.sqrt_eq_iff_sq_eq] ⟶ have hy : y = 1 := by nlinarith [h₀.1, h₀.2, h₁] ⟶ have hx : x = Real.sqrt 2 := by<br>  rw [hy] at h₂<br>  nlinarith [Real.sqrt_pos.mpr (show (0 : ℝ) < 2 by norm_num), Real.sq_sqrt (show (0 : ℝ) ≤ 2 by norm_num)] ⟶ nlinarith |
| aime_1991_p1 | cases' h₀ with h₀x h₀y ⟶ have h₀xy : x * y ≤ 71 := by<br>  nlinarith ⟶ have h₁xy : x * y ≥ 1 := by nlinarith ⟶ nlinarith [mul_le_mul_right x h₀y, mul_le_mul_left y h₀x] |
