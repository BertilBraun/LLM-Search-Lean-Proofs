# Proof search: phase3_astar_v0_sft_v2

Run `phase3_astar_v0_sft_v2` on miniF2F-valid, git `0ca398c6bf58fb2dd45c6871c92a96f746801d27`, config `experiments/configs/phase3_astar_v0_sft_v2.toml` (copied as `config.toml`). Started 2026-10-12T07:28:52+00:00, 24.3 min wall, 46 CPUs, load average 36.1 at start.

**Solved 157/244 (64.3%).** Solved only with proofs of 2 or more steps: 68. Verification failures (bugs): 0. Proofs that also verify without the per-step heartbeat wrappers: 157/157. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 55 | 0.786 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 20 | 0.444 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 4 | 0.2 |
| algebra | 18 | 16 | 0.889 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 89 | 123 | 133 | 138 | 144 | 153 | 157 |
| solve rate | 36.5% | 50.4% | 54.5% | 56.6% | 59.0% | 62.7% | 64.3% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 34 | 52 | 79 | 106 | 124 | 126 | 137 | 145 | 148 | 153 | 157 |
| solve rate | 13.9% | 21.3% | 32.4% | 43.4% | 50.8% | 51.6% | 56.1% | 59.4% | 60.7% | 62.7% | 64.3% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 64 | 92 | 114 | 125 | 131 | 135 | 142 | 149 | 152 | 156 | 157 |
| solve rate | 26.2% | 37.7% | 46.7% | 51.2% | 53.7% | 55.3% | 58.2% | 61.1% | 62.3% | 63.9% | 64.3% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 157 |
| expansion_budget | 58 |
| wall_clock_budget | 25 |
| frontier_exhausted | 4 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 21.6 | 2 | 64 | 64 | 5261 |
| nodes | 83.1 | 11.5 | 257 | 440 | 20274 |
| edges | 498 | 50 | 1550 | 1742 | 121426 |
| lean_seconds | 123 | 8.68 | 427 | 588 | 30130 |
| wall_seconds | 175 | 18.5 | 600 | 610 | 42784 |
| duplicates | 121 | 12 | 384 | 532 | 29643 |
| errors | 266 | 26.5 | 842 | 1085 | 64870 |
| timeouts | 1.9 | 0 | 5 | 35 | 463 |
| repl_failures | 0.0041 | 0 | 0 | 1 | 1 |
| verification_seconds | 1.69 | 0.473 | 3.45 | 32.2 | 413 |

solved (157 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 4.52 | 1 | 10 | 55 | 710 |
| nodes | 16.5 | 6 | 35 | 172 | 2593 |
| edges | 91.1 | 19 | 239 | 1245 | 14306 |
| lean_seconds | 20.5 | 1.52 | 51.9 | 467 | 3224 |
| wall_seconds | 32.3 | 4.66 | 80.9 | 517 | 5074 |
| duplicates | 21.7 | 4 | 67 | 340 | 3412 |
| errors | 50 | 10 | 116 | 772 | 7854 |
| timeouts | 0.287 | 0 | 0 | 17 | 45 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.63 | 1.38 | 5.11 | 32.2 | 413 |

unsolved (87 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 52.3 | 64 | 64 | 64 | 4551 |
| nodes | 203 | 213 | 324 | 440 | 17681 |
| edges | 1231 | 1431 | 1649 | 1742 | 107120 |
| lean_seconds | 309 | 286 | 539 | 588 | 26906 |
| wall_seconds | 433 | 455 | 604 | 610 | 37710 |
| duplicates | 302 | 344 | 422 | 532 | 26231 |
| errors | 655 | 720 | 933 | 1085 | 57016 |
| timeouts | 4.8 | 1 | 18 | 35 | 418 |
| repl_failures | 0.0115 | 0 | 0 | 1 | 1 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 54027 | 21710 | 72.1% | 0.402 | 14678 | 9288 | 23641 | 23190 | 0 | 451 | 1 | 59 | 0 |
| aesop | 4935 | 2518 | 8.4% | 0.51 | 652 | 2599 | 1684 | 1679 | 0 | 5 | 0 | 3 | 11 |
| simp_all | 5146 | 1715 | 5.7% | 0.333 | 1232 | 1875 | 2039 | 2038 | 0 | 1 | 0 | 5 | 12 |
| nlinarith | 5155 | 983 | 3.3% | 0.191 | 8 | 35 | 5112 | 5111 | 0 | 1 | 0 | 5 | 5 |
| field_simp | 5215 | 597 | 2.0% | 0.115 | 499 | 1041 | 3675 | 3675 | 0 | 0 | 0 | 0 | 2 |
| decide | 5261 | 534 | 1.8% | 0.102 | 47 | 5 | 5209 | 5209 | 0 | 0 | 0 | 24 | 27 |
| ring_nf | 5162 | 509 | 1.7% | 0.0986 | 1143 | 4016 | 3 | 0 | 0 | 3 | 0 | 6 | 9 |
| norm_num | 5213 | 492 | 1.6% | 0.0945 | 211 | 5001 | 1 | 0 | 0 | 1 | 0 | 5 | 5 |
| linarith | 5209 | 399 | 1.3% | 0.0767 | 30 | 33 | 5146 | 5146 | 0 | 0 | 0 | 28 | 28 |
| simp | 5215 | 388 | 1.3% | 0.0744 | 813 | 426 | 3976 | 3976 | 0 | 0 | 0 | 0 | 0 |
| rfl | 5213 | 92.8 | 0.3% | 0.0178 | 5 | 42 | 5166 | 5165 | 0 | 1 | 0 | 4 | 4 |
| constructor | 5219 | 74.2 | 0.2% | 0.0142 | 623 | 79 | 4517 | 4517 | 0 | 0 | 0 | 0 | 5 |
| intros | 5219 | 52.2 | 0.2% | 0.00999 | 49 | 5170 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| omega | 5237 | 50.5 | 0.2% | 0.00964 | 40 | 33 | 5164 | 5164 | 0 | 0 | 0 | 18 | 19 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 89 |
| 2 | 41 |
| 3 | 12 |
| 4 | 12 |
| 5 | 2 |
| 6 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | aesop ⟶ norm_num |
| mathd_algebra_73 | have h₂ : x = p + q - r := by<br>  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)<br>  linear_combination h₀ - (p + q - r) * (p + q - r) ⟶ simp_all |
| mathd_numbertheory_32 | have h₁ : S = Finset.filter (λ n => n ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀]<br>  <;> tauto ⟶ aesop |
| mathd_algebra_547 | simp_all only [h₀, h₁, one_pow, sub_eq_add_neg, add_comm, add_left_comm, add_assoc] ⟶ norm_num [Real.sqrt_eq_iff_sq_eq] |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_116 | ring_nf at h₁ ⟶ nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)] |
| induction_divisibility_3divnto3m2n | have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, Nat.dvd_iff_mod_eq_zero, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_mod]<br><;><br>omega |
| mathd_numbertheory_64 | constructor ⟶ decide ⟶ ·<br>  intro x hx<br>  norm_num [Nat.ModEq] at hx<br>  omega |
| mathd_algebra_28 | aesop ⟶ nlinarith [sq_nonneg (w + 5 / 4)] |
| amc12a_2009_p9 | simp_all ⟶ have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1, h₀ 2] |
| mathd_algebra_245 | field_simp [h₀, mul_comm, mul_left_comm, mul_assoc, pow_two, pow_three] ⟶ linarith |
| mathd_numbertheory_257 | rcases h₀ with ⟨h₀_left, h₀_right⟩ ⟶ interval_cases x <;> simp_all (config := {decide := true}) |
| mathd_numbertheory_35 | have h₁ := h₀ 24 ⟶ norm_num at h₁ |
| mathd_algebra_192 | simp_all ⟶ ring_nf<br><;> simp [Complex.ext_iff, pow_two, pow_three]<br><;> norm_num<br><;> ring_nf<br><;> norm_num<br><;> ring_nf<br><;> norm_num |
| mathd_algebra_110 | simp [Complex.ext_iff, h₀, h₁, mul_add, mul_sub, mul_comm] ⟶ norm_num |
| mathd_algebra_140 | have h₂ : a * b - 3 * c = -9 := by<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-3 / 4)<br>  have h₅ := h₁ (1 / 3)<br>  have h₆ := h₁ (-1 / 2)<br>  have h₇ := h₁ (-1 / 3)<br>  have h₈ := h₁ 2<br>  have h₉ := h₁ (-2)<br>  have h₁₀ := h₁ (-3)<br>  have h₁₁ := h₁ 0<br>  have h₁₂ := h₁ 3<br>  have h₁₃ := h₁ 4<br>  have h₁₄ := h₁ 5<br>  have h₁₅ := h₁ 6<br>  have h₁₆ := h₁ 7<br>  have h₁₇ := h₁ 8<br>  have h₁₈ := h₁ 9<br>  have h₁₉ := h₁ 10<br>  norm_num at *<br>  nlinarith ⟶ linarith |
| mathd_algebra_433 | have h₁ := h₀ 8 ⟶ have h₂ : Real.sqrt (2 * 8 - 7) = 3 := by<br>  have h₃ : Real.sqrt (2 * 8 - 7) = 3 := by<br>    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  exact h₃ ⟶ linarith |
| mathd_numbertheory_780 | have h₄ : m = 43 := by<br>  have h₅ : m ≤ 99 := by<br>    linarith [h₁.1, h₁.2]<br>  have h₆ : m ≥ 10 := by<br>    linarith [h₁.1]<br>  interval_cases m <;> norm_num at h₂ h₃ <;> omega ⟶ omega |
| imo_1964_p1_2 | have h : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by<br>  have h1 : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by<br>    induction n with<br>    \| zero =><br>      norm_num<br>    \| succ n ih =><br>      rcases ih with (ih \| ih \| ih) <;> simp [pow_succ, Nat.mul_mod, ih] at *<br>      <;> omega<br>  exact h1 ⟶ omega |
| aime_1984_p15 | field_simp at h₀ h₁ h₂ h₃ ⟶ linarith |
| amc12b_2002_p6 | constructor ⟶ all_goals<br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  ring_nf at *<br>  nlinarith [sq_pos_of_ne_zero h₀.1, sq_pos_of_ne_zero h₀.2, sq_pos_of_ne_zero (show (2 : ℝ) ≠ 0 by norm_num)] |
| mathd_algebra_13 | aesop ⟶ case left =><br>  have h₁ := h₀ 0<br>  have h₂ := h₀ 1<br>  have h₃ := h₀ (-2)<br>  norm_num at h₁ h₂ h₃<br>  <;> linarith ⟶ case right =><br>  have h₁ : b = 10 := by<br>    have h₂ := h₀ 6<br>    have h₃ := h₀ 8<br>    have h₄ := h₀ 10<br>    have h₅ := h₀ 12<br>    norm_num at h₂ h₃ h₄ h₅<br>    field_simp at h₂ h₃ h₄ h₅<br>    ring_nf at h₂ h₃ h₄ h₅<br>    linarith<br>  exact h₁ |
| mathd_algebra_151 | have h1 : Int.ceil (Real.sqrt 27) = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  norm_num<br>  constructor <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (by norm_num : 0 ≤ (27 : ℝ)),<br>    Real.sqrt_nonneg 26, Real.sq_sqrt (by norm_num : 0 ≤ (26 : ℝ)),<br>    Real.sqrt_nonneg 25, Real.sq_sqrt (by norm_num : 0 ≤ (25 : ℝ)),<br>    Real.sqrt_nonneg 24, Real.sq_sqrt (by norm_num : 0 ≤ (24 : ℝ))] ⟶ have h2 : Int.floor (Real.sqrt 26) = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num<br>  <;> norm_num<br>  <;><br>  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ omega |
| amc12_2001_p9 | have h₂ := h₀ 600 (by norm_num) 500 (by norm_num) ⟶ simp only [h₁, mul_comm] at h₂ ⟶ simp_all ⟶ linarith |
| mathd_algebra_43 | simp only [h₀, h₁, h₂] at * ⟶ linarith |
| mathd_algebra_405 | simp only [Finset.card] ⟶ have h₁ : ∀ x ∈ S, x = 1 ∨ x = 2 := by<br>  intro x hx<br>  have h₂ : 0 < x ∧ x^2 + 4 * x + 4 < 20 := by<br>    simpa [hx] using h₀ x<br>  have h₃ : x = 1 ∨ x = 2 := by<br>    have h₄ : x ≤ 2 := by<br>      nlinarith<br>    have h₅ : x ≥ 1 := by<br>      nlinarith<br>    omega<br>  exact h₃ ⟶ have h₂ : S = {1, 2} := by<br>  ext x<br>  simp [h₀]<br>  all_goals aesop ⟶ simp_all |
| amc12a_2015_p10 | have h₃ := h₁ ⟶ have h₄ : 0 < x := by linarith ⟶ have h₅ : y < 26 := by<br>  nlinarith ⟶ interval_cases y <;> omega |
| mathd_algebra_55 | aesop ⟶ norm_num |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | aesop ⟶ field_simp ⟶ rw [le_div_iff (by positivity)] ⟶ nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - 1), sq_nonneg (x - Real.sqrt 2 / 2)]<br><;> norm_num |
| mathd_algebra_214 | simp only [h₀, h₁, sub_eq_add_neg, neg_mul, neg_neg] at * ⟶ linarith |
| amc12a_2013_p8 | have h₄ : x * y = 2 := by<br>  have h₅ : x ≠ 0 := h₀<br>  have h₆ : y ≠ 0 := h₁<br>  have h₇ : x + 2 / x = y + 2 / y := h₃<br>  field_simp at h₇<br>  ring_nf at h₇ ⊢<br>  apply mul_left_cancel₀ (sub_ne_zero.mpr h₂)<br>  nlinarith ⟶ linarith |
| mathd_algebra_480 | have h₃ := h₁ 0 (by norm_num) ⟶ have h₄ : Real.pi < 4 := by<br>  have := Real.pi_lt_31416<br>  norm_num at this ⊢<br>  <;> linarith ⟶ have h₅ : f π = 2 := by<br>  apply h₁<br>  constructor<br>  · linarith [Real.pi_pos]<br>  · linarith [Real.pi_pos] ⟶ linarith |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | rw [add_comm] ⟶ use x^2 + y^2 + z^2 - x * y - y * z - z * x ⟶ linarith |
| mathd_algebra_234 | ring_nf ⟶ nlinarith [pow_two d, pow_two (d ^ 2)] |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| amc12a_2008_p8 | have h₃ : y = 1 := by<br>  nlinarith [h₁] ⟶ have h₄ : x = Real.sqrt 2 := by<br>  rw [h₃] at h₂<br>  nlinarith [Real.sq_sqrt (show 0 ≤ 2 by norm_num), Real.sqrt_nonneg 2] ⟶ nlinarith |
| mathd_algebra_536 | field_simp [Nat.factorial_succ, Nat.factorial_zero, Nat.factorial_succ] ⟶ norm_num<br><;> ring<br><;> nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 9 from by norm_num), Real.sqrt_nonneg 9] |
| mathd_algebra_22 | field_simp [Real.logb, show (5 : ℝ) ≠ 0 by norm_num, show (5 : ℝ) ≠ 1 by norm_num] ⟶ linarith |
| mathd_numbertheory_22 | have h₂ : b = 3 ∨ b = 1 := by<br>  have h₃ : b ≤ 9 := by linarith<br>  interval_cases b <;> norm_num at h₁ ⊢ <;><br>  (try contradiction) <;><br>  (try omega) <;><br>  (try simp_all) ⟶ omega |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| imo_1984_p2 | have h₅ : 0 ≤ a := by<br>  exact_mod_cast (le_of_lt h₀.1) ⟶ have h₆ : 0 ≤ b := by linarith ⟶ simp_all ⟶ have h₇ : 0 ≤ (a + b) ^ 2 := by positivity ⟶ have h₈ : 19 ≤ a + b := by<br>  by_contra h<br>  push_neg at h<br>  have h₈₁ : a + b ≤ 18 := by<br>    omega<br>  have h₈₂ : a ≤ 18 := by<br>    omega<br>  have h₈₃ : b ≤ 18 := by<br>    omega<br>  interval_cases a <;> interval_cases b <;> norm_num [Int.dvd_iff_emod_eq_zero] at h₄ h₁ h₂ h₃ h₈₁ h₈₂ h₈₃ ⊢<br>  <;> omega ⟶ omega |
| amc12b_2003_p9 | simp_all only [h₀, mul_add, mul_sub, mul_one, mul_zero, sub_add, sub_sub, sub_neg_eq_add, add_assoc, add_left_comm, add_comm] ⟶ linarith |
| amc12_2000_p11 | field_simp [h₀.1, h₀.2, mul_comm] ⟶ nlinarith [sq_nonneg (a - b), h₁] |
| mathd_algebra_132 | simp only [h₀, h₁, h₂] at * ⟶ linarith |
| numbertheory_nckeqnm1ckpnm1ckm1 | rw [← succ_pred_eq_of_pos h₀.1] ⟶ induction n <;><br>induction k <;><br>simp_all [Nat.choose_succ_succ, Nat.choose_zero_right, Nat.choose_one_right, Nat.zero_eq, Nat.succ_eq_add_one]<br><;><br>linarith |
| amc12b_2003_p17 | have : 0 < x * y := mul_pos h₀.1 h₀.2 ⟶ have h₃ : 0 < x * y * (x * y) := by nlinarith ⟶ have h₄ : Real.log (x * y) = 3 / 5 := by<br>  field_simp [Real.log_mul, h₀.1.ne', h₀.2.ne'] at *<br>  norm_num [Real.log_mul, Real.log_rpow, Real.log_div, h₁, h₂]<br>  all_goals nlinarith ⟶ linarith |
| mathd_numbertheory_232 | aesop ⟶ rfl |
| mathd_algebra_77 | constructor ⟶ all_goals<br>  simp_all only [h₂, h₃, h₄]<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  ring_nf<br>  nlinarith |
| mathd_algebra_11 | field_simp [h₀, h₁, sub_ne_zero, sub_ne_zero, sub_ne_zero, sub_ne_zero, sub_ne_zero,<br>  sub_ne_zero, sub_ne_zero, sub_ne_zero, sub_ne_zero] at h₂ ⊢ ⟶ linarith |
| mathd_algebra_159 | simp [h₀, h₁] at * ⟶ linarith |
| mathd_numbertheory_690 | constructor ⟶ decide ⟶ ·<br>  intro a ha<br>  norm_num [Nat.ModEq] at ha ⊢<br>  rcases ha with ⟨ha_pos, ha_3, ha_5, ha_7, ha_9⟩<br>  omega |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all only [Complex.ext_iff, Complex.I_mul_I, mul_pow, mul_one, mul_neg, mul_comm,<br>  mul_left_comm, mul_assoc, Complex.ext_iff, Complex.I_mul_I, mul_pow, mul_one,<br>  mul_neg, mul_comm, mul_left_comm, mul_assoc, Complex.ext_iff, Complex.I_mul_I, mul_pow,<br>  mul_one, mul_neg, mul_comm, mul_left_comm, mul_assoc, Complex.ext_iff, Complex.I_mul_I,<br>  mul_pow, mul_one, mul_neg, mul_comm, mul_left_comm, mul_assoc] ⟶ simp_all [Complex.ext_iff, Complex.I_mul_I, pow_two, pow_three]<br><;> ring<br><;> norm_num<br><;> linarith<br><;> ring<br><;> norm_num<br><;> linarith |
| mathd_numbertheory_326 | ring_nf at h₀ ⟶ apply Eq.symm ⟶ nlinarith [sq_nonneg (n - 4), sq_nonneg (n + 4), sq_nonneg (n - 3), sq_nonneg (n + 3)] |
| mathd_algebra_437 | norm_cast at h₀ h₁ ⟶ simp_all ⟶ have h₄ : n = -4 := by<br>  nlinarith [sq_nonneg (x - y), sq_nonneg (x + y), h₀, h₁, h₂, h₃] ⟶ omega |
| mathd_algebra_451 | simp_all ⟶ have h₄ := h₀.symm ⟶ have h₅ := h₁.symm ⟶ have h₆ := h₂.symm ⟶ simp_all |
| aime_1983_p9 | have h₁ : 0 < Real.sin x := Real.sin_pos_of_mem_Ioo ⟨by linarith [h₀.1], h₀.2⟩ ⟶ rw [le_div_iff (by nlinarith [Real.sin_sq_add_cos_sq x, h₀.1, h₀.2])] ⟶ have h₂ : 0 < Real.sin x ^ 2 := sq_pos_of_pos h₁ ⟶ nlinarith [sq_nonneg (x * Real.sin x - 2 / 3),<br>  Real.sin_sq_add_cos_sq x,<br>  sq_nonneg (Real.sin x + 2 / 3),<br>  sq_nonneg (Real.sin x - 2 / 3)] |
| mathd_algebra_267 | have h₃ : x = 0 := by<br>  have h₄ : x - 1 ≠ 0 := by<br>    intro h<br>    apply h₀<br>    linarith<br>  have h₅ : x + 2 ≠ 0 := by<br>    intro h<br>    apply h₁<br>    linarith<br>  have h₆ : (x + 1) / (x - 1) = (x - 2) / (x + 2) := h₂<br>  field_simp [h₄, h₅] at h₆<br>  ring_nf at h₆<br>  linarith ⟶ linarith |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | refine ⟨?_,?_⟩ ⟶ rw [← sub_eq_zero] at h₀ h₁ ⟶ apply Eq.symm ⟶ all_goals simp_all [Complex.ext_iff, add_comm] ⟶ all_goals<br>  norm_num<br>  constructor<br>  nlinarith<br>  nlinarith |
| imo_1974_p5 | aesop ⟶ . apply lt_of_sub_pos<br>  field_simp<br>  ring_nf<br>  nlinarith [mul_pos left left_1, mul_pos left left_2, mul_pos left right, mul_pos left_1 right, mul_pos left_2 right] ⟶ case right =><br>  apply lt_of_sub_pos<br>  field_simp<br>  ring_nf<br>  nlinarith [mul_pos left left_1, mul_pos left_1 left_2, mul_pos left_2 right, mul_pos right left, mul_pos left_1 right, mul_pos right left_2] |
| mathd_numbertheory_668 | aesop ⟶ rfl |
| mathd_algebra_251 | field_simp at h₁ ⟶ linarith |
| mathd_algebra_181 | field_simp [sub_ne_zero.mpr h₀] at h₁ ⟶ linarith |
| amc12a_2017_p2 | field_simp [h₀, h₁, mul_comm] ⟶ linarith |
| mathd_algebra_206 | simp_all only [h₀, h₂, h₃, zero_add, mul_zero, add_zero, mul_one, mul_neg, mul_assoc,<br>  mul_comm, mul_left_comm] ⟶ apply mul_left_cancel₀ (sub_ne_zero.mpr h₁) ⟶ nlinarith |
| induction_seq_mul2pnp1 | induction' n with n ih ⟶ omega ⟶ simp [ih, h₁, Nat.add_comm, Nat.add_left_comm, Nat.add_assoc] ⟶ cases n with<br>\| zero =><br>  simp<br>\| succ n =><br>  simp_all [Nat.pow_succ, Nat.mul_add, Nat.add_mul, Nat.mul_one, Nat.add_zero]<br>  ring<br>  <;> omega |
| mathd_numbertheory_629 | constructor ⟶ decide ⟶ ·<br>  intro t ht<br>  by_contra h<br>  push_neg at h<br>  have h1 : t < 18 := by linarith<br>  have h2 : Nat.lcm 12 t ^ 3 = (12 * t) ^ 2 := by<br>    simpa using ht.2<br>  have h3 : t < 18 := by linarith<br>  have h4 : t ≤ 17 := by<br>    omega<br>  interval_cases t <;> norm_num at h1 h2 h3 ⊢ <;> try {<br>    aesop<br>  } |
| mathd_algebra_89 | ring_nf ⟶ norm_cast ⟶ field_simp ⟶ ring_nf |
| imo_1961_p1 | have h₇ : a > 0 := by linarith ⟶ ring_nf ⟶ refine' ⟨h₇, ⟨_, _⟩⟩ <;> nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁),<br>  sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₃)] |
