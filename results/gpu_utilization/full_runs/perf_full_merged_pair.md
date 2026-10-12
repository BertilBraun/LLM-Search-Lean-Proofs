# Proof search: perf_full_merged_pair

Run `perf_full_merged_pair` on miniF2F-valid, git `45a2f9bfedb9ee38b74715dc0d775f515d668b87`, config `/workspace/runs/perf/configs/merged_pair.toml` (copied as `config.toml`). Started 2026-10-12T14:50:06+00:00, 11.8 min wall, 46 CPUs, load average 18.1 at start.

**Solved 155/244 (63.5%).** Solved only with proofs of 2 or more steps: 65. Verification failures (bugs): 1. Proofs that also verify without the per-step heartbeat wrappers: 155/155. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 56 | 0.8 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 21 | 0.467 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 1 | 0.05 |
| algebra | 18 | 15 | 0.833 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 90 | 120 | 134 | 139 | 144 | 153 | 155 |
| solve rate | 36.9% | 49.2% | 54.9% | 57.0% | 59.0% | 62.7% | 63.5% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 15 | 31 | 59 | 86 | 107 | 120 | 129 | 138 | 143 | 152 | 154 |
| solve rate | 6.1% | 12.7% | 24.2% | 35.2% | 43.9% | 49.2% | 52.9% | 56.6% | 58.6% | 62.3% | 63.1% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 52 | 66 | 108 | 122 | 127 | 132 | 136 | 143 | 148 | 152 | 155 |
| solve rate | 21.3% | 27.0% | 44.3% | 50.0% | 52.0% | 54.1% | 55.7% | 58.6% | 60.7% | 62.3% | 63.5% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 155 |
| wall_clock_budget | 47 |
| expansion_budget | 40 |
| frontier_exhausted | 2 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 19.6 | 3 | 64 | 64 | 4789 |
| nodes | 74.8 | 12 | 241 | 375 | 18258 |
| edges | 449 | 55 | 1458 | 1709 | 109486 |
| lean_seconds | 181 | 10.8 | 565 | 611 | 44051 |
| wall_seconds | 215 | 37 | 601 | 614 | 52538 |
| duplicates | 111 | 12.5 | 361 | 542 | 27153 |
| errors | 238 | 27.5 | 747 | 1022 | 57994 |
| timeouts | 2.5 | 0 | 12 | 31 | 611 |
| repl_failures | 0.0041 | 0 | 0 | 1 | 1 |
| verification_seconds | 2 | 0.721 | 5.14 | 30.7 | 488 |

solved (155 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 4.1 | 1 | 9 | 52 | 635 |
| nodes | 16.4 | 6 | 35 | 253 | 2538 |
| edges | 83.8 | 17 | 196 | 1194 | 12996 |
| lean_seconds | 26.8 | 2.88 | 85.9 | 557 | 4153 |
| wall_seconds | 43.9 | 13.2 | 140 | 611 | 6799 |
| duplicates | 20 | 3 | 46 | 329 | 3104 |
| errors | 44.8 | 10 | 115 | 630 | 6946 |
| timeouts | 0.194 | 0 | 0 | 12 | 30 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 3.14 | 1.47 | 7.61 | 30.7 | 487 |

unsolved (89 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 46.7 | 59 | 64 | 64 | 4154 |
| nodes | 177 | 182 | 312 | 375 | 15720 |
| edges | 1084 | 1292 | 1558 | 1709 | 96490 |
| lean_seconds | 448 | 519 | 593 | 611 | 39899 |
| wall_seconds | 514 | 600 | 609 | 614 | 45739 |
| duplicates | 270 | 310 | 431 | 542 | 24049 |
| errors | 574 | 628 | 880 | 1022 | 51048 |
| timeouts | 6.53 | 3 | 20 | 31 | 581 |
| repl_failures | 0.0112 | 0 | 0 | 1 | 1 |
| verification_seconds | 0.00875 | 0 | 0 | 0.779 | 0.779 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 48556 | 30941 | 70.3% | 0.637 | 13315 | 8679 | 20849 | 20260 | 0 | 589 | 0 | 57 | 0 |
| aesop | 4330 | 3606 | 8.2% | 0.833 | 575 | 2380 | 1375 | 1365 | 0 | 10 | 0 | 3 | 10 |
| simp_all | 4642 | 2559 | 5.8% | 0.551 | 1130 | 1753 | 1759 | 1757 | 0 | 2 | 0 | 3 | 7 |
| nlinarith | 4666 | 1546 | 3.5% | 0.331 | 7 | 32 | 4627 | 4626 | 0 | 1 | 0 | 5 | 5 |
| field_simp | 4713 | 915 | 2.1% | 0.194 | 442 | 883 | 3388 | 3387 | 0 | 1 | 0 | 1 | 6 |
| decide | 4773 | 848 | 1.9% | 0.178 | 45 | 7 | 4721 | 4720 | 0 | 1 | 0 | 24 | 26 |
| ring_nf | 4698 | 839 | 1.9% | 0.178 | 1027 | 3670 | 1 | 0 | 0 | 1 | 0 | 5 | 8 |
| norm_num | 4711 | 774 | 1.8% | 0.164 | 182 | 4527 | 2 | 0 | 0 | 2 | 0 | 4 | 4 |
| linarith | 4731 | 687 | 1.6% | 0.145 | 34 | 29 | 4668 | 4668 | 0 | 0 | 0 | 31 | 31 |
| simp | 4713 | 595 | 1.4% | 0.126 | 636 | 394 | 3683 | 3682 | 0 | 1 | 0 | 0 | 2 |
| rfl | 4721 | 204 | 0.5% | 0.0432 | 5 | 31 | 4685 | 4682 | 0 | 2 | 1 | 4 | 4 |
| constructor | 4727 | 194 | 0.4% | 0.041 | 516 | 73 | 4138 | 4137 | 0 | 1 | 0 | 0 | 5 |
| omega | 4762 | 169 | 0.4% | 0.0355 | 38 | 14 | 4710 | 4710 | 0 | 0 | 0 | 19 | 19 |
| intros | 4743 | 142 | 0.3% | 0.03 | 62 | 4681 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 90 |
| 2 | 35 |
| 3 | 15 |
| 4 | 14 |
| 5 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | aesop ⟶ norm_num |
| mathd_algebra_214 | simp only [h₀, h₁] at * ⟶ linarith |
| mathd_algebra_73 | apply mul_right_cancel₀ (sub_ne_zero.mpr h₁) ⟶ linear_combination h₀ - (p - x) * (q - x) |
| numbertheory_sqmod4in01d | have h : (a ^ 2) % 4 = 0 ∨ (a ^ 2) % 4 = 1 := by<br>  have h₁ : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega<br>  rcases h₁ with (h₁ \| h₁ \| h₁ \| h₁) <;><br>    simp [h₁, pow_two, Int.mul_emod, Int.add_emod, Int.sub_emod] ⟶ omega |
| mathd_algebra_547 | subst h₀; subst h₁; norm_num; ⟶ rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num |
| mathd_algebra_43 | simp [h₀, h₁, h₂] at * ⟶ linarith |
| amc12b_2003_p9 | simp [h₀, h₁, sub_eq_add_neg] at h₀ h₁ ⊢ ⟶ linarith |
| mathd_algebra_28 | aesop ⟶ nlinarith [sq_nonneg (w + 5 / 4)] |
| numbertheory_sqmod3in01d | have h : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases h with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_22 | simp [Real.logb]<br><;> norm_num<br><;> ring ⟶ field_simp |
| mathd_algebra_433 | have h₁ := h₀ 8 ⟶ have h₂ : f 8 = (1 : ℝ) := by<br>  rw [h₁]<br>  have h₃ : Real.sqrt (2 * 8 - 7) = 3 := by<br>    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  rw [h₃]<br>  <;> norm_num<br>  <;> ring_nf<br>  <;> norm_num ⟶ linarith |
| mathd_algebra_116 | have h₂ : x = (13 - Real.sqrt 131) / 4 := h₀ ⟶ nlinarith [Real.sqrt_nonneg 131, sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)] |
| mathd_algebra_132 | field_simp ⟶ simp [h₀, h₁, h₂] at * ⟶ linarith |
| induction_divisibility_3divnto3m2n | have h₁ : n^3 % 3 = n % 3 := by<br>  have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega<br>  rcases this with (h \| h \| h) <;> simp [h, pow_three, Nat.mul_mod, Nat.add_mod] ⟶ omega |
| amc12a_2013_p8 | field_simp at h₃ ⟶ have h₄ : x * y = 2 := by<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₂)<br>  nlinarith [sq_pos_of_ne_zero h₀, sq_pos_of_ne_zero h₁] ⟶ linarith |
| amc12a_2009_p9 | have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1] |
| amc12a_2013_p7 | simp_all ⟶ linarith |
| mathd_algebra_11 | field_simp [sub_ne_zero.mpr h₀, sub_ne_zero.mpr h₁] at h₂ ⊢ ⟶ linarith |
| mathd_algebra_245 | field_simp [h₀, mul_pow, pow_two, pow_one, mul_comm] ⟶ linarith |
| mathd_algebra_159 | have h₂ : b = -2 := by<br>  have h₂₁ := h₁<br>  rw [h₀] at h₂₁<br>  norm_num at h₂₁ ⊢<br>  <;> linarith ⟶ linarith |
| mathd_numbertheory_32 | have h₁ : S = Finset.filter (fun k => k ∣ 36) (Finset.range 37) := by<br>  ext k<br>  simp [h₀, Finset.mem_filter, Finset.mem_range] ⟶ aesop |
| mathd_numbertheory_257 | norm_num at h₀ h₁ ⟶ omega |
| mathd_algebra_67 | simp_all only [h₀, h₁, mul_neg, mul_one, mul_zero, neg_neg, neg_add_rev, neg_zero, add_zero,<br>  sub_eq_add_neg, neg_sub, sub_neg_eq_add, neg_neg, neg_zero] ⟶ norm_num |
| amc12_2000_p11 | have h₂ : a / b + b / a - a * b = 2 := by<br>  field_simp [h₀.1, h₀.2]<br>  nlinarith [mul_self_pos.mpr h₀.1, mul_self_pos.mpr h₀.2, sq_nonneg (a - b)] ⟶ linarith |
| mathd_numbertheory_22 | have h₂ : b ≤ 9 := by linarith ⟶ interval_cases b <;> norm_num at h₁ <;> omega |
| mathd_algebra_140 | have h₂ := h₁ 1 ⟶ aesop ⟶ nlinarith [h₁ 0, h₁ 1, h₁ 2, h₁ 3] |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all ⟶ simp [Complex.ext_iff] at h₀ ⊢ ⟶ constructor <;> simp_all [Complex.ext_iff, Complex.I_mul_I]<br><;> linarith |
| mathd_algebra_267 | field_simp [h₀, h₁, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₂ ⟶ linarith |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_numbertheory_35 | have h₁ := h₀ 24 ⟶ norm_num at h₁ |
| mathd_numbertheory_780 | have h₄ : m = 43 := by<br>  have h₄₁ : m ≤ 99 := by linarith<br>  have h₄₂ : m ≥ 10 := by linarith<br>  interval_cases m <;> norm_num at h₂ h₃ ⊢ <;> try omega <;> try contradiction <;> try omega ⟶ omega |
| mathd_numbertheory_668 | simp only [h₀, h₁, sub_eq_add_neg, add_comm, add_left_comm] ⟶ rfl |
| mathd_algebra_251 | have h₂ : x = 2 := by<br>  field_simp [h₀] at h₁<br>  ring_nf at h₁<br>  linarith ⟶ linarith |
| mathd_algebra_181 | field_simp [h₀, sub_eq_zero, sub_ne_zero, not_false_iff] at h₁ ⟶ linarith |
| amc12a_2015_p10 | rw [add_comm] at h₂ ⟶ have h₃ : y < 26 := by<br>  nlinarith ⟶ interval_cases y <;> omega |
| mathd_numbertheory_64 | constructor ⟶ decide ⟶ ·<br>  intro x hx<br>  simp only [Set.mem_setOf_eq, Nat.ModEq] at hx<br>  omega |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| amc12a_2017_p2 | field_simp ⟶ linarith |
| mathd_algebra_192 | aesop ⟶ norm_num [Complex.ext_iff, Complex.I_mul_I, Complex.ofReal_mul] |
| mathd_algebra_151 | have h1 : ⌈Real.sqrt 27⌉ = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 from by norm_num)] ⟶ have h2 : ⌊Real.sqrt 26⌋ = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ omega |
| mathd_algebra_206 | simp_all only [h₀, sq] ⟶ nlinarith [h₁, h₂, h₃, sq_pos_of_ne_zero (sub_ne_zero.mpr h₁)] |
| mathd_algebra_77 | constructor ⟶ all_goals<br>  simp_all only [sq, mul_add, mul_sub, mul_one, mul_neg, mul_assoc, mul_comm, mul_left_comm]<br>  ring_nf at h₃ h₄<br>  apply mul_left_cancel₀ (sub_ne_zero.2 h₁)<br>  nlinarith |
| aime_1984_p15 | ring_nf at * ⟶ linarith |
| mathd_algebra_536 | norm_num [Nat.factorial]<br><;> ring_nf<br><;> norm_num [Nat.factorial]<br><;> ring_nf<br><;> norm_num [Nat.factorial]<br><;> ring_nf<br><;> norm_num [Nat.factorial]<br><;> ring_nf<br><;> norm_num [Nat.factorial]<br><;> ring_nf<br><;> norm_num [Nat.factorial]<br><;> ring_nf<br><;> norm_num [Nat.factorial] ⟶ have h₀ : Real.sqrt 9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ linarith |
| mathd_algebra_437 | have h₄ : -18 < 101 := by<br>  norm_num [h₁]<br>  <;><br>  (try norm_num) <;><br>  (try linarith) <;><br>  (try nlinarith) <;><br>  (try ring_nf at * <;> linarith) <;><br>  (try nlinarith [h₁, h₀, h₂, h₃])<br>  <;><br>  (try linarith) ⟶ nlinarith [pow_two (x - y), pow_two (x + y), pow_two (x + 4), pow_two (x - 4)] |
| mathd_algebra_421 | field_simp [mul_comm] at h₁ h₃ ⟶ nlinarith [sq_nonneg (a - c), sq_nonneg (a + c)] |
| mathd_numbertheory_326 | have h₁ : n^3 - n = 720 := by linarith ⟶ ring_nf ⟶ have h₂ : n = 9 := by<br>  nlinarith [sq_nonneg (n - 9), sq_nonneg (n + 9)] ⟶ omega |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | ring_nf at h₀ ⊢ ⟶ use x ^ 2 + y ^ 2 + z ^ 2 - x * y - x * z - y * z ⟶ linarith |
| mathd_algebra_13 | aesop ⟶ next =><br>  have h₁ := h₀ 1<br>  have h₂ := h₀ (-1)<br>  have h₃ := h₀ 2<br>  have h₄ := h₀ (-2)<br>  norm_num [Nat.cast_ofNat] at h₁ h₂ h₃ h₄<br>  <;> ring_nf at h₁ h₂ h₃ h₄<br>  <;> nlinarith ⟶ case right =><br>  have h₁ := h₀ 4<br>  have h₂ := h₀ 6<br>  norm_num at h₁ h₂<br>  ring_nf at h₁ h₂<br>  norm_num at h₁ h₂<br>  linarith |
| mathd_numbertheory_629 | constructor ⟶ decide ⟶ ring_nf ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht_pos, ht_lcm⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num [Nat.lcm] at ht_lcm <;> omega |
| aime_1983_p9 | rw [le_div_iff (by nlinarith [Real.sin_pos_of_pos_of_lt_pi h₀.1 h₀.2])] ⟶ have h₁ : 0 < Real.sin x := Real.sin_pos_of_pos_of_lt_pi h₀.1 (by linarith [Real.pi_pos]) ⟶ nlinarith [sq_nonneg (x * sin x - 2 / 3), h₀.1, h₀.2, h₁, sq_nonneg (sin x - x)] |
| mathd_algebra_59 | ring_nf at h₀ ⟶ have h₁ : (4 : ℝ) ^ b = 4 := by linarith ⟶ have h₂ : b = 1 := by<br>  apply_fun (fun x => Real.logb 4 x) at h₁<br>  field_simp at h₁<br>  linarith ⟶ linarith |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | aesop ⟶ field_simp ⟶ rw [le_div_iff (by positivity)] ⟶ nlinarith [sq_nonneg (x - Real.sqrt 2 / 2), Real.sq_sqrt (show 0 ≤ 2 by norm_num)] |
| imo_1964_p1_2 | ring_nf ⟶ have h : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 ∨ 2 ^ n % 7 = 1 := by<br>  have h₂ : ∀ n : ℕ, 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 ∨ 2 ^ n % 7 = 1 := by<br>    intro n<br>    induction n with<br>    \| zero =><br>      simp<br>    \| succ n ih =><br>      simp [pow_succ, Int.mul_emod, ih]<br>      all_goals omega<br>  exact h₂ n ⟶ omega |
| amc12b_2002_p6 | constructor ⟶ case left =><br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  ring_nf at h₂ h₃ h₄<br>  nlinarith [sq_pos_of_ne_zero h₀.1, sq_pos_of_ne_zero h₀.2] ⟶ rw [← sub_eq_zero] ⟶ ·<br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  have h₅ := h₁ a<br>  have h₆ := h₁ (-b)<br>  have h₇ := h₁ b<br>  have h₈ := h₀.1<br>  have h₉ := h₀.2<br>  nlinarith [sq_pos_of_ne_zero h₈, sq_pos_of_ne_zero h₉] |
| mathd_algebra_480 | have h₃ := h₁ 2 (by norm_num) ⟶ have h₄ : Real.pi < 4 := by<br>  have := Real.pi_lt_31416<br>  norm_num at this ⊢<br>  <;> linarith ⟶ have h₅ : f Real.pi = 2 := by<br>  rw [h₁]<br>  constructor<br>  · linarith [Real.pi_pos]<br>  · linarith [Real.pi_pos] ⟶ linarith |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | refine ⟨?_,?_⟩ ⟶ rw [← sub_eq_zero] at h₁ ⟶ all_goals<br>  apply eq_of_sub_eq_zero<br>  simp_all [Complex.ext_iff, mul_comm] ⟶ all_goals<br>  constructor <;> linarith |
| amc12b_2003_p17 | field_simp ⟶ aesop ⟶ field_simp [Real.log_mul, Real.log_rpow] at h₁ h₂ ⊢ ⟶ linarith |
| amc12_2001_p9 | have h₂ := h₀ 500 (by norm_num) 600 (by norm_num) ⟶ have h₃ := h₀ 600 (by norm_num) 500 (by norm_num) ⟶ ring_nf at h₂ h₃ ⟶ linarith |
| mathd_algebra_323 | simp ⟶ have h₁ := h 3 ⟶ norm_num at h₁ ⟶ have h₂ : σ.symm 19 = 3 := by<br>  have h₃ : σ 3 = 19 := by<br>    simpa [h] using h₁<br>  rw [← h₃]<br>  congr<br>  <;> simp [h]<br>  <;> ring_nf<br>  <;> norm_num ⟶ linarith |
| amc12b_2003_p6 | rw [h₀] at h₁ h₂ ⟶ cases' eq_or_ne a 0 with ha₀ ha₀ <;> simp_all ⟶ field_simp ⟶ {<br>  apply or_iff_not_imp_left.mpr<br>  intro h<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h)<br>  nlinarith [sq_sqrt (show 0 ≤ 3 by norm_num),<br>    sq_nonneg (a * r ^ 2),<br>    sq_nonneg (a * r ^ 2 + a * r ^ 1),<br>    sq_nonneg (a * r ^ 2 + a * r ^ 0),<br>    sq_nonneg (a * r ^ 2 - a * r ^ 1),<br>    sq_nonneg (a * r ^ 2 - a * r ^ 0)]<br>} |
| mathd_numbertheory_690 | constructor ⟶ simp ⟶ all_goals simp [Nat.ModEq, Nat.add_mod, Nat.mul_mod, Nat.mod_mod] ⟶ ·<br>  intro a h<br>  rcases h with ⟨ha_pos, ha_mod3, ha_mod5, ha_mod7, ha_mod9⟩<br>  by_contra h'<br>  push_neg at h'<br>  interval_cases a <;> omega |
| mathd_algebra_493 | simp [h₀, sq, mul_comm] ⟶ have h₁ : (4 : ℝ) * Real.sqrt 4 = 8 := by<br>  have h₁ : Real.sqrt 4 = 2 := by<br>    rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num<br>  rw [h₁]<br>  <;> ring_nf<br>  <;> norm_num ⟶ have h₂ : √(4 * 4 - 4 * Real.sqrt 4 + 1) = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  <;> linarith ⟶ nlinarith |
| mathd_algebra_451 | have h₄ := h₀ ⟶ have h₅ := h₁.symm ⟶ have h₆ := h₂.symm ⟶ simp_all |
| amc12a_2008_p8 | have h₃ : y = 1 := by<br>  have h₃₁ : y = 1 := by<br>    have h₃₂ : y^3 = 1 := h₁<br>    have h₃₃ : y > 0 := h₀.2<br>    have h₃₄ : y = 1 := by<br>      have h₃₅ : y^3 = 1 := h₃₂<br>      have h₃₆ : y = 1 := by<br>        apply le_antisymm<br>        ·<br>          nlinarith [sq_nonneg (y - 1), sq_nonneg (y + 1), sq_nonneg (y^2 - 1), sq_nonneg (y^2 + 1)]<br>        ·<br>          nlinarith [sq_nonneg (y - 1), sq_nonneg (y + 1), sq_nonneg (y^2 - 1), sq_nonneg (y^2 + 1)]<br>      exact h₃₆<br>    exact h₃₄<br>  exact h₃₁ ⟶ have h₄ : x = Real.sqrt 2 := by<br>  rw [h₃] at h₂<br>  nlinarith [Real.sqrt_nonneg 2, Real.sq_sqrt (by nlinarith : 0 ≤ (2 : ℝ)), h₁] ⟶ nlinarith |
