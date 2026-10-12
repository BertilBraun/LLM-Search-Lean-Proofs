# Proof search: phase2_sft_v2_search

Run `phase2_sft_v2_search` on miniF2F-valid, git `13ff6514cc3a1c2ddb3462713185568926aeecca`, config `experiments/configs/phase2_sft_v2_search.toml` (copied as `config.toml`). Started 2026-10-12T07:03:15+00:00, 25.5 min wall, 46 CPUs, load average 44.6 at start.

**Solved 148/244 (60.7%).** Solved only with proofs of 2 or more steps: 65. Verification failures (bugs): 1. Proofs that also verify without the per-step heartbeat wrappers: 148/148. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 53 | 0.757 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 18 | 0.4 |
| aime | 15 | 1 | 0.0667 |
| imo | 20 | 1 | 0.05 |
| algebra | 18 | 15 | 0.833 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 83 | 102 | 128 | 136 | 141 | 144 | 148 |
| solve rate | 34.0% | 41.8% | 52.5% | 55.7% | 57.8% | 59.0% | 60.7% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 33 | 47 | 69 | 91 | 118 | 124 | 135 | 140 | 140 | 146 | 148 |
| solve rate | 13.5% | 19.3% | 28.3% | 37.3% | 48.4% | 50.8% | 55.3% | 57.4% | 57.4% | 59.8% | 60.7% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 59 | 74 | 100 | 116 | 127 | 129 | 140 | 142 | 145 | 146 | 148 |
| solve rate | 24.2% | 30.3% | 41.0% | 47.5% | 52.0% | 52.9% | 57.4% | 58.2% | 59.4% | 59.8% | 60.7% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 148 |
| expansion_budget | 59 |
| wall_clock_budget | 35 |
| frontier_exhausted | 2 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 22.5 | 4 | 64 | 64 | 5501 |
| nodes | 71.7 | 15 | 220 | 384 | 17488 |
| edges | 500 | 73 | 1512 | 1726 | 121941 |
| lean_seconds | 155 | 17.7 | 534 | 597 | 37843 |
| wall_seconds | 197 | 26.9 | 601 | 615 | 48124 |
| duplicates | 137 | 19.5 | 423 | 681 | 33350 |
| errors | 263 | 39 | 816 | 1079 | 64264 |
| timeouts | 2.14 | 0 | 8 | 32 | 523 |
| repl_failures | 0.0041 | 0 | 0 | 1 | 1 |
| verification_seconds | 1.61 | 0.393 | 4.29 | 20.3 | 392 |

solved (148 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.83 | 1 | 7 | 60 | 567 |
| nodes | 13.5 | 5 | 27 | 149 | 1993 |
| edges | 74 | 18.5 | 127 | 1514 | 10948 |
| lean_seconds | 17.9 | 2.01 | 37.5 | 431 | 2650 |
| wall_seconds | 26.1 | 5.79 | 55.4 | 504 | 3868 |
| duplicates | 18.6 | 3.5 | 37 | 425 | 2754 |
| errors | 39.6 | 10 | 59 | 859 | 5863 |
| timeouts | 0.176 | 0 | 0 | 14 | 26 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.65 | 1.63 | 5.52 | 20.3 | 392 |

unsolved (96 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 51.4 | 64 | 64 | 64 | 4934 |
| nodes | 161 | 166 | 266 | 384 | 15495 |
| edges | 1156 | 1291 | 1649 | 1726 | 110993 |
| lean_seconds | 367 | 347 | 569 | 597 | 35193 |
| wall_seconds | 461 | 494 | 605 | 615 | 44256 |
| duplicates | 319 | 364 | 463 | 681 | 30596 |
| errors | 608 | 650 | 874 | 1079 | 58401 |
| timeouts | 5.18 | 2 | 17 | 32 | 497 |
| repl_failures | 0.0104 | 0 | 0 | 1 | 1 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 51489 | 25629 | 67.8% | 0.498 | 13847 | 10511 | 20572 | 20070 | 0 | 501 | 1 | 65 | 0 |
| aesop | 5208 | 3870 | 10.2% | 0.743 | 299 | 3162 | 1747 | 1739 | 0 | 8 | 0 | 3 | 8 |
| simp_all | 5369 | 2866 | 7.6% | 0.534 | 895 | 2521 | 1953 | 1949 | 0 | 4 | 0 | 4 | 25 |
| nlinarith | 5263 | 2073 | 5.5% | 0.394 | 5 | 24 | 5234 | 5227 | 0 | 7 | 0 | 4 | 4 |
| field_simp | 5458 | 637 | 1.7% | 0.117 | 338 | 990 | 4130 | 4130 | 0 | 0 | 0 | 0 | 7 |
| linarith | 5453 | 549 | 1.5% | 0.101 | 23 | 22 | 5408 | 5408 | 0 | 0 | 0 | 21 | 22 |
| norm_num | 5456 | 525 | 1.4% | 0.0963 | 102 | 5353 | 1 | 0 | 0 | 1 | 0 | 5 | 8 |
| ring_nf | 5429 | 523 | 1.4% | 0.0962 | 751 | 4677 | 1 | 0 | 0 | 1 | 0 | 5 | 12 |
| decide | 5501 | 427 | 1.1% | 0.0777 | 36 | 3 | 5462 | 5462 | 0 | 0 | 0 | 24 | 28 |
| simp | 5458 | 376 | 1.0% | 0.0688 | 463 | 553 | 4442 | 4442 | 0 | 0 | 0 | 0 | 2 |
| rfl | 5455 | 118 | 0.3% | 0.0216 | 14 | 15 | 5426 | 5425 | 0 | 1 | 0 | 4 | 4 |
| constructor | 5462 | 100 | 0.3% | 0.0184 | 406 | 84 | 4972 | 4972 | 0 | 0 | 0 | 0 | 7 |
| intros | 5463 | 66.8 | 0.2% | 0.0122 | 44 | 5419 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| omega | 5477 | 65.9 | 0.2% | 0.012 | 21 | 16 | 5440 | 5440 | 0 | 0 | 0 | 14 | 15 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 83 |
| 2 | 24 |
| 3 | 16 |
| 4 | 11 |
| 5 | 2 |
| 7 | 3 |
| 8 | 2 |
| 9 | 1 |
| 10 | 1 |
| 14 | 2 |
| 15 | 1 |
| 16 | 2 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| amc12a_2009_p5 | ring_nf at h₀ ⟶ rw [h₀, show (5 : ℝ)^3 = 125 by norm_num]<br><;> norm_num |
| mathd_algebra_48 | rw [h₀, h₁] ⟶ norm_num |
| mathd_algebra_547 | simp_all ⟶ rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| induction_divisibility_3divnto3m2n | apply Nat.dvd_of_mod_eq_zero ⟶ have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;> simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod] |
| mathd_algebra_73 | apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ linear_combination h₀ |
| mathd_numbertheory_64 | constructor ⟶ decide ⟶ ·<br>  intro x hx<br>  simp [Nat.ModEq] at hx<br>  omega |
| mathd_numbertheory_257 | norm_num at h₁ ⟶ omega |
| mathd_algebra_28 | obtain ⟨x, hx⟩ := h₁ ⟶ simp_all ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| mathd_algebra_35 | simp_all ⟶ norm_num |
| mathd_algebra_140 | have h₂ := h₁ 0 ⟶ have h₃ := h₁ 1 ⟶ have h₄ := h₁ (-1) ⟶ linarith |
| mathd_algebra_116 | rw [h₀] at h₁ ⟶ ring_nf at h₁ ⟶ nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)] |
| mathd_numbertheory_35 | have h₁ := h₀ 0 ⟶ norm_num at h₁ |
| mathd_algebra_433 | simp_all ⟶ ring_nf ⟶ nlinarith [Real.sqrt_nonneg 9, sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num),<br>  Real.sqrt_nonneg 3, sq_sqrt (show (0 : ℝ) ≤ 3 by norm_num)] |
| mathd_algebra_13 | have h₁ := h₀ 6 ⟶ have h₂ := h₀ (-1) ⟶ norm_num at h₁ h₂ ⟶ exact ⟨by linarith, by linarith⟩ |
| mathd_algebra_192 | simp_all ⟶ norm_num [Complex.ext_iff, Complex.I_mul_I] |
| mathd_numbertheory_32 | have h₁ : S = Finset.filter (λ n => n ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀]<br>  all_goals<br>    aesop ⟶ aesop |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp ⟶ rw [div_le_iff (by positivity)] ⟶ nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - Real.sqrt 2 / 2)] |
| mathd_algebra_110 | simp_all ⟶ ring<br><;> norm_num |
| mathd_numbertheory_780 | aesop ⟶ interval_cases m <;> omega |
| aime_1984_p15 | field_simp at h₀ h₁ h₂ h₃ ⟶ linarith |
| amc12a_2015_p10 | ring_nf at h₂ ⟶ have h₃ : y ≥ 1 := by linarith ⟶ simp_all ⟶ have h₄ : x + x * y + y = 80 := h₂ ⟶ have h₅ := h₀ ⟶ have h₆ : y < x := h₁ ⟶ have h₇ : x + x * y + y = 80 := by linarith ⟶ have h₈ : 1 ≤ y := by linarith ⟶ have h₉ : 0 < y := by linarith ⟶ have h₁₀ : y < x := by linarith ⟶ simp_all ⟶ revert x y ⟶ intro x y h₁ h₂ h₃ h₄ ⟶ have h₅ : y ≥ 1 := by linarith ⟶ have h₆ : y ≤ 25 := by<br>  nlinarith ⟶ interval_cases y <;> omega |
| amc12a_2009_p9 | have h₂ := h₀ 0 ⟶ have h₃ := h₀ 1 ⟶ have h₄ := h₀ (-1) ⟶ have h₅ := h₀ 2 ⟶ have h₆ := h₀ (-2) ⟶ have h₇ := h₀ 3 ⟶ have h₈ := h₀ (-3) ⟶ have h₉ := h₀ 4 ⟶ have h₁₀ := h₀ (-4) ⟶ have h₁₁ := h₀ 5 ⟶ have h₁₂ := h₀ (-5) ⟶ have h₁₃ := h₀ 6 ⟶ have h₁₄ := h₀ (-6) ⟶ norm_num at * ⟶ simp_all |
| mathd_algebra_43 | simp only [h₀, h₁, h₂] at * ⟶ linarith |
| mathd_algebra_55 | rw [h₀] ⟶ norm_num [h₀, h₁] |
| mathd_algebra_214 | simp_all ⟶ linarith |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_59 | norm_num at h₀ ⟶ have h₁ : (4 : ℝ) ^ b = 4 := by linarith ⟶ simp_all ⟶ norm_num at h₀ ⟶ simp_all ⟶ apply_fun fun x => Real.logb 4 x at h₁ ⟶ simp_all |
| amc12a_2013_p8 | field_simp at h₃ ⟶ ring_nf at h₃ ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀),<br>  sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁), sq_nonneg (x - y), sq_nonneg (x - 1),<br>  sq_nonneg (y - 1)] |
| amc12b_2020_p5 | ring_nf at h₀ h₁ ⟶ field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| mathd_algebra_22 | rw [Real.logb] ⟶ field_simp ⟶ linarith |
| mathd_numbertheory_22 | have h₂ : b ≤ 9 := by linarith ⟶ interval_cases b <;> norm_num at h₁ ⊢ |
| amc12b_2003_p9 | rw [h₀] at h₁ ⊢ ⟶ linarith [h₀ 2, h₀ 6] |
| mathd_algebra_151 | have h_main : ⌈Real.sqrt 27⌉ = ⌈Real.sqrt 27⌉ := rfl ⟶ have h_root_bounds : Real.sqrt 26 ≤ Real.sqrt 27 := by<br>  apply Real.sqrt_le_sqrt<br>  norm_num ⟶ have h_sqrt27_lt : Real.sqrt 27 < Real.sqrt 28 := by<br>  apply Real.sqrt_lt_sqrt<br>  <;> norm_num ⟶ simp_all ⟶ have h_sqrt26 : Real.sqrt 26 < 5.1 := by<br>  rw [Real.sqrt_lt] <;> norm_num ⟶ have h_sqrt26' : Real.sqrt 26 < 5.1 := h_sqrt26 ⟶ simp_all ⟶ have h_sqrt27_le : Real.sqrt 27 ≥ 5 := by<br>  have h₁ : Real.sqrt 27 ≥ 5 := by<br>    apply Real.le_sqrt_of_sq_le<br>    norm_num<br>  exact h₁ ⟶ norm_num at h_root_bounds h_sqrt27_lt h_sqrt26' h_sqrt27_le ⟶ simp_all ⟶ have h_sqrt27_lt_6 : Real.sqrt 27 < 6 := by<br>  rw [Real.sqrt_lt] <;> norm_num ⟶ have h_floor_sqrt26 : ⌊Real.sqrt 26⌋ = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ simp_all ⟶ ring_nf ⟶ have h_ceil_sqrt27 : ⌈Real.sqrt 27⌉ = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show (0 : ℝ) ≤ 27 by norm_num)] ⟶ omega |
| mathd_algebra_132 | norm_num ⟶ simp only [h₀, h₁] at h₂ ⟶ linarith |
| mathd_algebra_536 | field_simp ⟶ ring_nf ⟶ norm_num [Nat.factorial] ⟶ norm_num [Real.sqrt_eq_iff_sq_eq, sq, mul_add, mul_comm, add_mul, mul_left_comm]<br><;> ring_nf<br><;> norm_num<br><;> nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num)] |
| amc12b_2003_p17 | field_simp ⟶ aesop ⟶ have h₃ : 0 < x * y := mul_pos left right ⟶ have h₄ : 0 < x * y ^ 3 := by positivity ⟶ have h₅ : 0 < x ^ 2 * y := by positivity ⟶ have h₆ : 0 < x ^ 2 * y ^ 3 := by positivity ⟶ field_simp [Real.log_mul, Real.log_rpow] at h₁ h₂ ⊢ ⟶ linarith |
| amc12_2000_p11 | have h₂ : a ≠ 0 := h₀.1 ⟶ have h₃ : b ≠ 0 := h₀.2 ⟶ field_simp ⟶ ring_nf ⟶ nlinarith [sq (a - b), sq (a + b), h₁, h₂, h₃] |
| amc12a_2013_p7 | have h₃ := h₀ 5 ⟶ have h₄ := h₀ 4 ⟶ have h₅ := h₀ 3 ⟶ have h₆ := h₀ 2 ⟶ have h₇ := h₀ 1 ⟶ have h₈ := h₀ 0 ⟶ linarith [h₀ 0, h₀ 1, h₀ 2, h₀ 3, h₀ 4, h₀ 5, h₀ 6, h₀ 7, h₀ 8, h₁, h₂] |
| amc12b_2002_p6 | have h₂ := h₁ 0 ⟶ have h₃ := h₁ 1 ⟶ have h₄ := h₁ (-1) ⟶ have h₅ := h₁ 2 ⟶ have h₆ := h₁ (-2) ⟶ have h₇ := h₁ 3 ⟶ have h₈ := h₁ (-3) ⟶ have h₉ := h₁ 4 ⟶ have h₁₀ := h₁ (-4) ⟶ have h₁₁ := h₁ 5 ⟶ have h₁₂ := h₁ (-5) ⟶ norm_num at h₂ h₃ h₄ h₅ h₆ h₇ h₈ h₉ h₁₀ h₁₁ h₁₂ ⟶ constructor ⟶ all_goals<br>  nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.1), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.2)] |
| mathd_algebra_410 | simp_all ⟶ nlinarith [sq_nonneg (x - 3)] |
| mathd_numbertheory_232 | rw [h₂] ⟶ simp_all [ZMod.natCast_eq_natCast_iff, ZMod.natCast_eq_natCast_iff, Int.ModEq, Int.emod_eq_of_lt]<br><;> rfl |
| mathd_algebra_77 | simp only [h₂] at h₃ h₄ ⟶ constructor ⟶ simp_all ⟶ all_goals<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  nlinarith |
| mathd_algebra_11 | have h₃ : a - 2 * b ≠ 0 := by<br>  intro h<br>  apply h₁<br>  linarith ⟶ have h₄ : a - b ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ field_simp at h₂ ⊢ ⟶ linarith |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_numbertheory_690 | constructor ⟶ decide ⟶ ·<br>  intro a h<br>  rcases h with ⟨ha₀, ha₁, ha₂, ha₃, ha₄⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases a <;> simp_all (config := {decide := true}) |
| induction_divisibility_9div10tonm1 | apply Nat.dvd_of_mod_eq_zero ⟶ rw [← Nat.mod_add_div (10 ^ n) 9] ⟶ simp [Nat.pow_mod, Nat.mod_eq_of_lt h₀, Nat.add_mod, Nat.mul_mod, Nat.mod_mod] |
| mathd_algebra_421 | ring_nf at h₀ h₁ h₂ h₃ ⟶ aesop ⟶ ring_nf at h₁ h₂ ⟶ nlinarith [sq_nonneg (a - c)] |
| mathd_algebra_493 | rw [h₀] ⟶ have h₁ : f 4 = 4^2 - 4 * Real.sqrt 4 + 1 := by rw [h₀] ⟶ rw [h₁] ⟶ norm_num ⟶ have h₂ : Real.sqrt 4 = 2 := by norm_num [Real.sqrt_eq_iff_sq_eq] ⟶ rw [h₂] ⟶ ring_nf ⟶ have h₃ : Real.sqrt 9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ linarith |
| mathd_algebra_437 | norm_cast at h₀ h₁ ⟶ simp_all ⟶ norm_cast at * ⟶ norm_num at h₀ h₁ ⟶ rw [eq_comm] ⟶ simp ⟶ nlinarith [sq_nonneg (x - 3), sq_nonneg (y - 3), sq_nonneg (x + 3), sq_nonneg (y + 3),<br>  sq_nonneg (x - y), sq_nonneg (x + y)] |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | rw [h₁] ⟶ ring_nf ⟶ aesop ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ simp_all [Complex.ext_iff, Complex.I_mul_I]<br><;> ring<br><;> linarith |
| mathd_algebra_67 | simp_all ⟶ norm_num |
| mathd_numbertheory_326 | ring_nf at h₀ ⟶ ring_nf ⟶ nlinarith [sq_nonneg (n - 10), sq_nonneg (n + 10)] |
| induction_ineq_nsqlefactn | induction' h₀ with n hn ⟶ decide ⟶ cases n with<br>\| zero => contradiction<br>\| succ n =><br>  simp_all [Nat.factorial_succ, Nat.pow_succ]<br>  nlinarith |
| mathd_algebra_267 | have h₃ : x - 1 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ have h₄ : x + 2 ≠ 0 := by<br>  intro h<br>  apply h₁<br>  linarith ⟶ field_simp at h₂ ⟶ linarith |
| induction_seq_mul2pnp1 | induction' n with n ih ⟶ omega ⟶ cases n with<br>\| zero => simp_all<br>\| succ n =><br>  simp_all [Nat.pow_succ, Nat.mul_succ]<br>  ring_nf<br>  omega |
| mathd_algebra_206 | simp only [h₀] at h₂ h₃ ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ nlinarith |
| mathd_algebra_251 | field_simp at h₁ ⟶ linarith |
| mathd_numbertheory_668 | rw [h₀] ⟶ norm_num ⟶ aesop ⟶ rfl |
| mathd_algebra_181 | have h₂ : n - 3 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ field_simp at h₁ ⟶ linarith |
| mathd_numbertheory_629 | constructor ⟶ decide ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht1, ht2⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num at ht1 ht2 <;><br>  simp_all [Nat.lcm, Nat.pow_succ]<br>  <;><br>  norm_num at *<br>  <;><br>  omega |
| amc12a_2017_p2 | have h₃ : x ≠ 0 := h₀ ⟶ have h₄ : y ≠ 0 := h₁ ⟶ field_simp ⟶ linarith |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | constructor ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ apply Eq.symm ⟶ rw [← sub_eq_zero] ⟶ simp ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ rw [← sub_eq_zero] ⟶ linear_combination h₁ - 2 * h₀ ⟶ linear_combination h₁ - h₀ |
| imo_1961_p1 | constructor ⟶ linarith ⟶ simp_all ⟶ next =><br>  constructor<br>  nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₁), sq_pos_of_ne_zero (sub_ne_zero.mpr h₂),<br>    sq_pos_of_ne_zero (sub_ne_zero.mpr h₃)]<br>  nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₁), sq_pos_of_ne_zero (sub_ne_zero.mpr h₂),<br>    sq_pos_of_ne_zero (sub_ne_zero.mpr h₃)] |
| algebra_amgm_sumasqdivbsqgeqsumbdiva | rcases h₀ with ⟨ha, hb, hc⟩ ⟶ have h₁ : 0 < a * b := by positivity ⟶ have h₂ : 0 < b * c := by positivity ⟶ have h₃ : 0 < c * a := by positivity ⟶ have h₄ : 0 < (a * b) * (b * c) := by positivity ⟶ have h₅ : 0 < (b * c) * (c * a) := by positivity ⟶ have h₆ : 0 < (c * a) * (a * b) := by positivity ⟶ field_simp ⟶ rw [div_le_div_iff (by positivity) (by positivity)] ⟶ nlinarith [sq_nonneg (a^2 - b * c), sq_nonneg (b^2 - c * a), sq_nonneg (c^2 - a * b),<br>  sq_nonneg (a * b^2 - b * c^2), sq_nonneg (b * c^2 - c * a^2), sq_nonneg (c * a^2 - a * b^2)] |
