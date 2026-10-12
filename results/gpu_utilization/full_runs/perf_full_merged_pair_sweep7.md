# Proof search: perf_full_merged_pair_sweep7

Run `perf_full_merged_pair_sweep7` on miniF2F-valid, git `45a2f9bfedb9ee38b74715dc0d775f515d668b87`, config `/workspace/runs/perf/configs/merged_pair_sweep7.toml` (copied as `config.toml`). Started 2026-10-12T15:02:00+00:00, 11.8 min wall, 46 CPUs, load average 33.0 at start.

**Solved 154/244 (63.1%).** Solved only with proofs of 2 or more steps: 70. Verification failures (bugs): 1. Proofs that also verify without the per-step heartbeat wrappers: 154/154. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 56 | 0.8 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 20 | 0.444 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 1 | 0.05 |
| algebra | 18 | 16 | 0.889 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 6 | 0.75 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 84 | 119 | 131 | 141 | 149 | 152 | 154 |
| solve rate | 34.4% | 48.8% | 53.7% | 57.8% | 61.1% | 62.3% | 63.1% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 19 | 39 | 58 | 81 | 104 | 120 | 133 | 144 | 148 | 151 | 153 |
| solve rate | 7.8% | 16.0% | 23.8% | 33.2% | 42.6% | 49.2% | 54.5% | 59.0% | 60.7% | 61.9% | 62.7% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 59 | 87 | 111 | 123 | 132 | 142 | 145 | 150 | 151 | 151 | 154 |
| solve rate | 24.2% | 35.7% | 45.5% | 50.4% | 54.1% | 58.2% | 59.4% | 61.5% | 61.9% | 61.9% | 63.1% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 154 |
| expansion_budget | 53 |
| wall_clock_budget | 35 |
| frontier_exhausted | 2 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 21.4 | 3 | 64 | 64 | 5211 |
| nodes | 78.7 | 12.5 | 249 | 383 | 19205 |
| edges | 360 | 41 | 1131 | 1289 | 87730 |
| lean_seconds | 150 | 9.38 | 503 | 599 | 36705 |
| wall_seconds | 206 | 33.6 | 600 | 614 | 50194 |
| duplicates | 72.3 | 7 | 222 | 427 | 17636 |
| errors | 192 | 21 | 611 | 816 | 46950 |
| timeouts | 2.27 | 0 | 10 | 33 | 553 |
| repl_failures | 0.0082 | 0 | 0 | 2 | 2 |
| verification_seconds | 1.77 | 0.689 | 4.12 | 30.4 | 432 |

solved (154 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.56 | 1 | 8 | 55 | 549 |
| nodes | 12.5 | 6 | 24 | 171 | 1920 |
| edges | 50.6 | 13.5 | 118 | 938 | 7796 |
| lean_seconds | 16.5 | 1.56 | 27.5 | 540 | 2544 |
| wall_seconds | 35.7 | 13.2 | 75.9 | 609 | 5499 |
| duplicates | 9.05 | 1 | 25 | 195 | 1394 |
| errors | 28.2 | 6 | 60 | 577 | 4348 |
| timeouts | 0.201 | 0 | 0 | 13 | 31 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.81 | 1.44 | 6.26 | 30.4 | 432 |

unsolved (90 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 51.8 | 64 | 64 | 64 | 4662 |
| nodes | 192 | 204 | 324 | 383 | 17285 |
| edges | 888 | 990 | 1232 | 1289 | 79934 |
| lean_seconds | 380 | 408 | 563 | 599 | 34161 |
| wall_seconds | 497 | 542 | 606 | 614 | 44695 |
| duplicates | 180 | 185 | 285 | 427 | 16242 |
| errors | 473 | 515 | 677 | 816 | 42602 |
| timeouts | 5.8 | 2 | 18 | 33 | 522 |
| repl_failures | 0.0222 | 0 | 0 | 2 | 2 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 51723 | 29495 | 80.4% | 0.57 | 14594 | 11209 | 22291 | 21746 | 0 | 545 | 1 | 62 | 0 |
| simp_all | 5071 | 2748 | 7.5% | 0.542 | 1355 | 1898 | 1818 | 1815 | 0 | 3 | 0 | 10 | 21 |
| nlinarith | 5127 | 1573 | 4.3% | 0.307 | 25 | 41 | 5061 | 5060 | 0 | 1 | 0 | 24 | 24 |
| field_simp | 5111 | 968 | 2.6% | 0.189 | 887 | 528 | 3696 | 3694 | 0 | 1 | 1 | 0 | 3 |
| ring_nf | 5147 | 808 | 2.2% | 0.157 | 1304 | 3841 | 2 | 0 | 0 | 2 | 0 | 13 | 17 |
| omega | 5211 | 758 | 2.1% | 0.145 | 67 | 17 | 5127 | 5127 | 0 | 0 | 0 | 30 | 30 |
| rfl | 5160 | 166 | 0.5% | 0.0321 | 4 | 41 | 5115 | 5114 | 0 | 1 | 0 | 3 | 3 |
| constructor | 5180 | 164 | 0.4% | 0.0316 | 725 | 61 | 4394 | 4394 | 0 | 0 | 0 | 13 | 21 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 84 |
| 2 | 43 |
| 3 | 17 |
| 4 | 5 |
| 5 | 5 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_73 | have : x = p + q - r := by<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  linear_combination h₀ ⟶ simp_all |
| mathd_algebra_55 | rw [h₀, h₁]; field_simp ⟶ ring_nf |
| amc12_2001_p9 | have h₂ : f 600 = 5 / 2 := by<br>  rw [show 600 = 500 * (600 / 500 : ℝ) by norm_num]<br>  rw [h₀ 500 (by norm_num) (600 / 500 : ℝ) (by norm_num)]<br>  norm_num [h₁] ⟶ simp_all |
| mathd_algebra_48 | simp [h₀, h₁, Complex.ext_iff, add_comm] ⟶ ring_nf |
| mathd_algebra_116 | have h₂ : k = 19 / 4 := by<br>  have h₃ : x = (13 - Real.sqrt 131) / 4 := h₀<br>  rw [h₃] at h₁<br>  ring_nf at h₁ ⊢<br>  nlinarith [sq_sqrt (by positivity : (0 : ℝ) ≤ 131), Real.sqrt_nonneg 131, Real.sq_sqrt (by positivity : (0 : ℝ) ≤ 131)] ⟶ simp_all |
| mathd_algebra_35 | simp_all ⟶ ring_nf |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| amc12b_2003_p9 | simp_all only [h₀, sub_eq_add_neg, neg_add_rev, neg_neg, mul_one, mul_zero, mul_neg, mul_pow] ⟶ nlinarith |
| numbertheory_sqmod3in01d | have h : (a ^ 2) % 3 = 0 ∨ (a ^ 2) % 3 = 1 := by<br>  have h₁ : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega<br>  rcases h₁ with (h₁ \| h₁ \| h₁) <;> simp [h₁, pow_two, Int.mul_emod] ⟶ omega |
| mathd_algebra_132 | field_simp ⟶ simp only [h₀, h₁, h₂] at * ⟶ nlinarith |
| mathd_algebra_192 | simp [h₀, h₁, h₂, Complex.I_mul_I, mul_assoc, mul_comm, mul_left_comm] ⟶ ring<br><;> simp [Complex.ext_iff]<br><;> norm_num |
| mathd_algebra_214 | simp only [h₀, h₁] at * ⟶ nlinarith |
| amc12a_2013_p7 | simp_all ⟶ nlinarith |
| mathd_algebra_43 | simp [h₀, h₁, h₂] at * ⟶ nlinarith |
| mathd_numbertheory_22 | have h₂ : b = 3 ∨ b = 1 := by<br>  have h₃ : b ≤ 9 := by linarith<br>  interval_cases b <;> norm_num at h₁ ⊢ <;><br>  (try omega) <;><br>  (try ring_nf at h₁ ⊢ <;> omega) <;><br>  (try norm_num at h₁ ⊢ <;> omega) ⟶ omega |
| mathd_algebra_245 | field_simp [h₀, pow_two, pow_three, mul_assoc] ⟶ ring_nf |
| mathd_algebra_234 | field_simp at h₀ ⊢ ⟶ nlinarith [sq_nonneg (d : ℝ), sq_nonneg (d : ℝ)] |
| mathd_algebra_28 | rcases h₁ with ⟨x, h₁⟩ ⟶ simp [h₀, h₁] at * ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| amc12a_2009_p9 | simp_all ⟶ have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1] |
| mathd_algebra_410 | simp [h₀, sq] ⟶ nlinarith [sq_nonneg (x - 3)] |
| amc12a_2013_p8 | field_simp [h₀, h₁] at h₃ ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₂) ⟶ nlinarith |
| mathd_numbertheory_257 | simp_all [Finset.sum_range_succ, Nat.dvd_iff_mod_eq_zero] ⟶ omega |
| amc12b_2020_p5 | have h₂ : (a : ℚ) = 42 := by<br>  field_simp at h₀ h₁<br>  linarith ⟶ exact_mod_cast h₂ |
| mathd_numbertheory_232 | simp_all ⟶ rfl |
| amc12b_2003_p17 | field_simp [Real.log_mul, Real.log_rpow, h₀.1.ne', h₀.2.ne'] at * ⟶ nlinarith |
| mathd_numbertheory_35 | have h₁ : ∑ k ∈ S, k = 24 := by<br>  have h₂ : ∑ k ∈ S, k = 24 := by<br>    have h₃ := h₀ 196<br>    have h₄ := h₀ 184<br>    have h₅ := h₀ 190<br>    have h₆ := h₀ 185<br>    have h₇ := h₀ 186<br>    have h₈ := h₀ 187<br>    have h₉ := h₀ 188<br>    have h₁₀ := h₀ 189<br>    have h₁₁ := h₀ 183<br>    have h₁₂ := h₀ 192<br>    have h₁₃ := h₀ 191<br>    norm_num at h₃ h₄ h₅ h₆ h₇ h₈ h₉ h₁₀ h₁₁ h₁₂ h₁₃<br>    <;> linarith<br>  exact h₂ ⟶ omega |
| mathd_numbertheory_461 | rw [h₀, Finset.card_filter] ⟶ constructor |
| mathd_algebra_11 | field_simp [h₀, h₁, sub_eq_zero, sub_ne_zero, sub_eq_iff_eq_add, add_comm, add_left_comm,<br>  add_assoc] at h₂ ⊢ ⟶ nlinarith |
| mathd_algebra_159 | have h₂ : b = -2 := by<br>  have h₃ := h₀ 1<br>  simp at h₃<br>  nlinarith [h₁, h₃] ⟶ simp_all |
| mathd_algebra_433 | simp_all ⟶ norm_num ⟶ nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show 0 ≤ 9 by norm_num)] |
| mathd_algebra_110 | simp [h₀, h₁, Complex.ext_iff, Complex.I_mul_I] ⟶ ring_nf |
| mathd_numbertheory_64 | constructor ⟶ constructor ⟶ ·<br>  intro x hx<br>  norm_num [Nat.ModEq, Nat.mod_eq_of_lt] at hx<br>  omega |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp [h₁, Complex.ext_iff, Complex.I_mul_I] at h₀ ⊢ ⟶ constructor <;> linarith |
| mathd_algebra_67 | simp [h₀, h₁, sub_eq_add_neg] ⟶ ring_nf |
| mathd_algebra_267 | have h₃ : x = 0 := by<br>  have h₄ : x - 1 ≠ 0 := by intro h; apply h₀; linarith<br>  have h₅ : x + 2 ≠ 0 := by intro h; apply h₁; linarith<br>  have h₆ : (x + 1) * (x + 2) = (x - 2) * (x - 1) := by<br>    field_simp [h₄, h₅] at h₂<br>    <;> linarith<br>  nlinarith ⟶ simp_all |
| induction_divisibility_3divnto3m2n | have h : n^3 % 3 = n % 3 := by<br>  have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega<br>  rcases this with (h \| h \| h) <;> simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_mod] ⟶ omega |
| mathd_numbertheory_32 | apply Eq.symm ⟶ have h₁ : S = Finset.filter (fun n => n ∣ 36) (Finset.range (37)) := by<br>  ext n<br>  simp [h₀] ⟶ simp [h₁, h₀, Finset.sum_filter]<br><;> rfl |
| mathd_numbertheory_780 | cases' h₁ with h₁_left h₁_right ⟶ interval_cases m <;> omega |
| mathd_numbertheory_326 | rw [← sub_eq_zero] at h₀ ⟶ nlinarith [sq_nonneg (n - 1), sq_nonneg (n + 1), sq_nonneg (n - 10), sq_nonneg (n + 10)] |
| mathd_algebra_251 | field_simp at h₁ ⟶ nlinarith |
| mathd_algebra_140 | have h₂ := h₁ 0 ⟶ simp_all ⟶ linarith [h₁ 1, h₁ 2] |
| mathd_algebra_22 | ring_nf ⟶ simp [Real.logb, show (625:ℝ) = 25 ^ 2 by norm_num]<br><;> norm_num |
| mathd_algebra_77 | constructor ⟶ all_goals<br>  simp_all only [h₂, h₃, h₄, pow_two, mul_add, mul_one, mul_zero, add_assoc, add_left_comm]<br>  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)<br>  nlinarith |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | field_simp ⟶ nlinarith [sq_sqrt (mul_nonneg h₀.1.le h₀.2.le),<br>  mul_self_nonneg (x - y),<br>  mul_self_nonneg (Real.sqrt (x * y) - (x - y) / 2)] |
| mathd_algebra_181 | have h₂ : n + 5 = 2 * (n - 3) := by<br>  field_simp [sub_ne_zero.mpr h₀] at h₁ ⊢<br>  linarith ⟶ nlinarith |
| mathd_numbertheory_668 | have h₂ : l - r = 1 := by<br>  simp [h₀, h₁, Int.ofNat_add, Int.ofNat_mul, Int.ofNat_sub]<br>  <;> norm_num [Int.ofNat_add, Int.ofNat_mul, Int.ofNat_sub]<br>  <;> rfl ⟶ simp_all |
| amc12a_2017_p2 | field_simp [h₀, h₁, mul_comm] ⟶ nlinarith |
| mathd_algebra_206 | simp only [h₀, h₁, h₂, h₃] at * ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁)] |
| mathd_algebra_13 | constructor ⟶ all_goals<br>  have h₁ := h₀ 7<br>  have h₂ := h₀ 4<br>  have h₃ := h₀ 2<br>  have h₄ := h₀ (-1)<br>  field_simp [(show (7 : ℝ) - 3 ≠ 0 by norm_num), (show (7 : ℝ) - 5 ≠ 0 by norm_num),<br>    (show (4 : ℝ) - 3 ≠ 0 by norm_num), (show (4 : ℝ) - 5 ≠ 0 by norm_num),<br>    (show (2 : ℝ) - 3 ≠ 0 by norm_num), (show (2 : ℝ) - 5 ≠ 0 by norm_num),<br>    (show (-1 : ℝ) - 3 ≠ 0 by norm_num), (show (-1 : ℝ) - 5 ≠ 0 by norm_num)] at h₁ h₂ h₃ h₄<br>  linarith |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp ⟶ rw [div_le_iff (by positivity), ← sub_nonneg] ⟶ nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - 1), sq_nonneg (x - Real.sqrt 2 / 2)] |
| induction_ineq_nsqlefactn | induction' h₀ with n hn ⟶ simp [Nat.factorial] ⟶ cases n with<br>\| zero =><br>  simp<br>\| succ n =><br>  simp_all [Nat.factorial_succ, Nat.pow_succ]<br>  nlinarith |
| amc12_2000_p11 | field_simp [h₀.1, h₀.2, h₁] ⟶ ring_nf ⟶ nlinarith [h₀, h₁, sq_nonneg (a - b), sq_nonneg (a + b)] |
| mathd_algebra_451 | have h₄ := h₀ ⟶ simp_all ⟶ simp only [h₁, h₂, h₃, h₄, eq_comm] ⟶ simp_all [h₁, h₂, h₃, h₄, eq_comm] |
| mathd_algebra_151 | have h1 : Int.ceil (Real.sqrt 27) = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 by norm_num)] ⟶ have h2 : Int.floor (Real.sqrt 26) = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 from by norm_num)] ⟶ omega |
| mathd_algebra_480 | have h₃ : Real.pi < 4 := by<br>  have := Real.pi_lt_31416<br>  norm_num at this ⊢<br>  <;> linarith ⟶ rw [h₁] ⟶ exact ⟨by linarith [Real.pi_pos], h₃⟩ |
| imo_1964_p1_2 | have h : 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 := by<br>  have h1 : ∀ n : ℕ, 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 := by<br>    intro n<br>    induction n with<br>    \| zero =><br>      simp<br>    \| succ n ih =><br>      simp [pow_succ, ih, Nat.mul_mod, Nat.add_mod, Nat.mod_eq_of_lt]<br>      <;> omega<br>  exact h1 n ⟶ omega |
| mathd_algebra_393 | simp_all ⟶ have h₁ : σ (2 : ℝ) = 33 := by<br>  rw [h₀]<br>  norm_num ⟶ have h₂ : σ 2 = 33 := h₁ ⟶ have h₃ : σ.symm 33 = 2 := by<br>  have h₄ : (σ.symm 33) = 2 := by<br>    have h₅ : σ 2 = 33 := h₂<br>    have h₆ : σ.symm 33 = 2 := by<br>      apply Eq.symm<br>      rw [← h₅]<br>      norm_num<br>    exact h₆<br>  exact h₄ ⟶ simp_all |
| aime_1984_p15 | field_simp [sub_eq_zero, add_comm, add_left_comm, add_assoc] at h₀ h₁ h₂ h₃ ⊢ ⟶ nlinarith |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | constructor ⟶ ring_nf at h₀ h₁ ⊢ ⟶ all_goals simp_all [Complex.ext_iff] ⟶ all_goals<br>  ring_nf at h₀ h₁ ⊢<br>  constructor <;> linarith |
| mathd_numbertheory_629 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  ·<br>    norm_num [Nat.lcm] ⟶ ring_nf ⟶ ·<br>  intro t ht<br>  norm_num at ht<br>  rcases ht with ⟨ht1, ht2⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases t <;> norm_num [Nat.lcm] at ht2 <;> omega |
| amc12a_2015_p10 | have h₁ : x + y + x * y = 80 := h₂ ⟶ have h₃ : x > 1 := by linarith ⟶ simp_all ⟶ have h₄ : x ≤ 45 := by<br>  nlinarith ⟶ interval_cases x <;> omega |
| mathd_algebra_437 | have h₄ : (x : ℝ) < (n : ℝ) := by exact_mod_cast h₂ ⟶ have h₅ := h₃ ⟶ nlinarith [pow_two_nonneg (x - y), pow_two_nonneg (x + y), pow_two_nonneg (x - 2), pow_two_nonneg (x + 2)] |
| aime_1983_p9 | rw [le_div_iff (by nlinarith [Real.sin_pos_of_pos_of_lt_pi h₀.1 (by linarith : x < Real.pi)])] ⟶ have h₁ : 0 ≤ Real.sin x ^ 2 := by nlinarith [Real.sin_sq_add_cos_sq x] ⟶ nlinarith [sq_nonneg (x * Real.sin x - 2 / 3), sq_nonneg (x * Real.cos x - 1 / 3),<br>  mul_self_nonneg (Real.sin x - 2 / 3), mul_self_nonneg (Real.cos x - 1 / 3)]<br><;> linarith<br><;> norm_num |
| amc12b_2002_p6 | constructor ⟶ {<br>  have h2 := h₁ 0<br>  have h3 := h₁ 1<br>  have h4 := h₁ (-1)<br>  simp [h₀] at h2 h3 h4<br>  linarith<br>} ⟶ have h₂ := h₁ 0 ⟶ simp_all ⟶ linarith [h₁ 0, h₁ 1, h₁ (-1)] |
| mathd_numbertheory_690 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  constructor<br>  ·<br>    norm_num [Nat.ModEq]<br>  ·<br>    norm_num [Nat.ModEq] ⟶ ·<br>  intro n hn<br>  by_contra h<br>  push_neg at h<br>  interval_cases n <;> simp_all (config := {decide := true}) |
| mathd_algebra_536 | have h₁ : (3! : ℝ) = 6 := by simp [Nat.factorial] ⟶ have h₂ : Real.sqrt 9 = 3 := by<br>  rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num ⟶ nlinarith |
| mathd_algebra_59 | norm_num at h₀ ⟶ have h₁ : (4 : ℝ) ^ b = 12 - 8 := by linarith ⟶ have h₂ : (4 : ℝ) ^ b = 4 := by linarith ⟶ have h₃ : b = 1 := by<br>  apply_fun (fun x => logb 4 x) at h₂<br>  field_simp at h₂<br>  linarith ⟶ simp_all |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | rw [add_comm] ⟶ use x^2 + y^2 + z^2 - x * y - y * z - z * x ⟶ nlinarith |
| mathd_algebra_89 | ring_nf ⟶ norm_num ⟶ have h₁ : b^6 * ((b^2 * 4)^3)^(-1 : ℤ) * 49 = 49 / 64 := by<br>  have h₂ : b^6 * ((b^2 * 4)^3)^((-1 : ℤ)) * 49 = 49 / 64 := by<br>    field_simp [h₀]<br>    <;> ring_nf<br>    <;> norm_num<br>    <;> ring_nf<br>    <;> norm_num<br>    <;> linarith<br>  exact h₂ ⟶ field_simp at h₁ ⊢ ⟶ exact h₁ |
| amc12a_2008_p8 | have h₃ : 0 < Real.sqrt 2 := Real.sqrt_pos.mpr (by norm_num) ⟶ have h₄ : 0 < y^2 := by nlinarith ⟶ nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num),<br>  mul_self_nonneg (x - Real.sqrt 2),<br>  mul_self_nonneg (x + Real.sqrt 2),<br>  mul_self_nonneg (y - 1),<br>  mul_self_nonneg (y + 1)] |
