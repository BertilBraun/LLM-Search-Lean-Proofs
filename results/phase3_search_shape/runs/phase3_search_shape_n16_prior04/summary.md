# Proof search: phase3_search_shape_n16_prior04

Run `phase3_search_shape_n16_prior04` on miniF2F-valid, git `874e8fe559e2fa0332e8fd3b8370c4baf0a3eec9`, config `experiments/configs/phase3_search_shape_n16_prior04.toml` (copied as `config.toml`). Started 2026-10-12T20:57:29+00:00, 61.2 min wall, 46 CPUs, load average 15.3 at start.

**Solved 153/244 (62.7%).** Solved only with proofs of 2 or more steps: 58. Verification failures (bugs): 0. Proofs that also verify without the per-step heartbeat wrappers: 153/153. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 55 | 0.786 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 18 | 0.4 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 1 | 0.05 |
| algebra | 18 | 16 | 0.889 |
| numbertheory | 8 | 5 | 0.625 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 95 | 112 | 133 | 140 | 145 | 150 | 153 |
| solve rate | 38.9% | 45.9% | 54.5% | 57.4% | 59.4% | 61.5% | 62.7% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 19 | 37 | 58 | 79 | 109 | 121 | 132 | 140 | 142 | 147 | 152 | 153 | 153 | 153 |
| solve rate | 7.8% | 15.2% | 23.8% | 32.4% | 44.7% | 49.6% | 54.1% | 57.4% | 58.2% | 60.2% | 62.3% | 62.7% | 62.7% | 62.7% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 60 | 89 | 113 | 128 | 135 | 138 | 140 | 142 | 144 | 148 | 153 | 153 | 153 | 153 |
| solve rate | 24.6% | 36.5% | 46.3% | 52.5% | 55.3% | 56.6% | 57.4% | 58.2% | 59.0% | 60.7% | 62.7% | 62.7% | 62.7% | 62.7% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 153 |
| expansion_budget | 82 |
| frontier_exhausted | 5 |
| wall_clock_budget | 4 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 25.2 | 3 | 64 | 64 | 6137 |
| nodes | 74.5 | 13.5 | 218 | 385 | 18174 |
| edges | 433 | 42.5 | 1210 | 1375 | 105615 |
| lean_seconds | 285 | 7.29 | 785 | 3586 | 69650 |
| wall_seconds | 333 | 31.2 | 836 | 3614 | 81352 |
| duplicates | 90 | 7 | 275 | 523 | 21966 |
| errors | 242 | 20 | 694 | 947 | 59013 |
| timeouts | 6.56 | 0 | 13 | 215 | 1601 |
| repl_failures | 0.0082 | 0 | 0 | 2 | 2 |
| verification_seconds | 1.59 | 0.641 | 3.77 | 33.1 | 389 |

solved (153 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.69 | 1 | 6 | 49 | 565 |
| nodes | 11.9 | 5 | 26 | 149 | 1819 |
| edges | 56.3 | 11 | 111 | 976 | 8609 |
| lean_seconds | 26.1 | 1.58 | 25.6 | 583 | 3987 |
| wall_seconds | 44.9 | 11.8 | 89.1 | 648 | 6864 |
| duplicates | 9.18 | 1 | 19 | 186 | 1404 |
| errors | 33.8 | 6 | 62 | 607 | 5179 |
| timeouts | 0.399 | 0 | 0 | 19 | 61 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.54 | 1.37 | 5.28 | 33.1 | 389 |

unsolved (91 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 61.2 | 64 | 64 | 64 | 5572 |
| nodes | 180 | 178 | 287 | 385 | 16355 |
| edges | 1066 | 1133 | 1285 | 1375 | 97006 |
| lean_seconds | 722 | 395 | 1983 | 3586 | 65664 |
| wall_seconds | 819 | 515 | 1993 | 3614 | 74488 |
| duplicates | 226 | 222 | 327 | 523 | 20562 |
| errors | 592 | 588 | 786 | 947 | 53834 |
| timeouts | 16.9 | 2 | 60 | 215 | 1540 |
| repl_failures | 0.022 | 0 | 0 | 2 | 2 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 63181 | 60051 | 86.3% | 0.95 | 13782 | 13944 | 30351 | 28760 | 1 | 1591 | 0 | 72 | 0 |
| simp_all | 5921 | 3097 | 4.4% | 0.523 | 1395 | 2203 | 2323 | 2319 | 0 | 4 | 0 | 4 | 22 |
| nlinarith | 6062 | 2434 | 3.5% | 0.401 | 26 | 18 | 6018 | 6017 | 0 | 1 | 0 | 24 | 25 |
| omega | 6131 | 1544 | 2.2% | 0.252 | 41 | 10 | 6080 | 6079 | 0 | 1 | 0 | 26 | 27 |
| field_simp | 6094 | 1179 | 1.7% | 0.193 | 985 | 688 | 4421 | 4420 | 0 | 0 | 1 | 0 | 10 |
| ring_nf | 6054 | 910 | 1.3% | 0.15 | 1054 | 4998 | 2 | 0 | 0 | 2 | 0 | 10 | 19 |
| constructor | 6111 | 213 | 0.3% | 0.0349 | 644 | 87 | 5380 | 5379 | 0 | 0 | 1 | 14 | 22 |
| rfl | 6061 | 194 | 0.3% | 0.0321 | 3 | 18 | 6040 | 6039 | 0 | 1 | 0 | 3 | 3 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 95 |
| 2 | 18 |
| 3 | 18 |
| 4 | 12 |
| 5 | 4 |
| 6 | 2 |
| 7 | 3 |
| 8 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | rw [h₀, h₁] ⟶ ring_nf |
| numbertheory_sqmod4in01d | have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ rcases this with (h \| h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_algebra_55 | simp_all ⟶ ring_nf |
| mathd_numbertheory_461 | simp_all ⟶ constructor |
| mathd_algebra_214 | simp_all ⟶ nlinarith |
| mathd_algebra_28 | obtain ⟨x, hx⟩ := h₁ ⟶ simp_all ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| amc12b_2003_p9 | simp only [h₀] at h₁ ⊢ ⟶ nlinarith |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| amc12a_2013_p7 | simp_all ⟶ nlinarith |
| mathd_algebra_132 | field_simp ⟶ simp_all ⟶ nlinarith |
| mathd_algebra_73 | apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ ring_nf ⟶ linear_combination h₀ |
| mathd_numbertheory_64 | constructor ⟶ constructor ⟶ ·<br>  intro x hx<br>  simp [Nat.ModEq, Nat.mod_eq_of_lt] at hx<br>  omega |
| mathd_algebra_234 | field_simp at h₀ ⊢ ⟶ nlinarith [sq_nonneg (3 * d ^ 2), sq_nonneg (3 * d)] |
| amc12b_2020_p5 | ring_nf at h₀ h₁ ⟶ field_simp at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| mathd_algebra_159 | simp [h₀, h₁] at * ⟶ nlinarith |
| mathd_numbertheory_257 | norm_num at h₁ ⟶ omega |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp ⟶ rw [div_le_iff (by positivity)] ⟶ nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num),<br>  sq_nonneg (x - 1),<br>  sq_nonneg (x - Real.sqrt 2 / 2)] |
| mathd_algebra_110 | simp_all ⟶ simp [Complex.ext_iff, pow_two] ⟶ ring_nf |
| induction_divisibility_3divnto3m2n | apply Nat.dvd_of_mod_eq_zero ⟶ have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;> simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod] |
| amc12a_2013_p8 | field_simp at h₃ ⟶ apply mul_left_cancel₀ (sub_ne_zero_of_ne h₂) ⟶ nlinarith |
| mathd_algebra_11 | have h₃ : a - b ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ have h₄ : a - 2 * b ≠ 0 := by<br>  intro h<br>  apply h₁<br>  linarith ⟶ field_simp [h₃, h₄] at h₂ ⊢ ⟶ nlinarith |
| mathd_algebra_433 | have := h₀ 8 ⟶ rw [this] ⟶ ring_nf at this ⊢ ⟶ nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num),<br>  Real.sqrt_nonneg 9] |
| amc12_2000_p11 | field_simp [h₀.1, h₀.2] ⟶ ring_nf ⟶ nlinarith [sq (a - b), sq (a + b)] |
| mathd_numbertheory_22 | have h₂ : b ≤ 9 := by linarith ⟶ interval_cases b <;> norm_num at h₁ h₂ ⊢ |
| mathd_algebra_192 | simp_all ⟶ ring_nf ⟶ ring<br><;> simp [Complex.ext_iff, pow_three]<br><;> ring |
| mathd_numbertheory_780 | have h₄ : m ≤ 99 := by linarith ⟶ have h₅ : m ≥ 10 := by linarith ⟶ interval_cases m <;> omega |
| mathd_numbertheory_326 | ring_nf at h₀ ⟶ ring_nf ⟶ nlinarith [sq_nonneg (n - 7), sq_nonneg (n + 7)] |
| mathd_algebra_251 | field_simp at h₁ ⟶ nlinarith |
| mathd_algebra_151 | have h₀ : ⌈Real.sqrt 27⌉ = 6 := by<br>  rw [Int.ceil_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 by norm_num)] ⟶ have h₁ : Int.floor (Real.sqrt 26) = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;> nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ omega |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_algebra_267 | have h₃ : x - 1 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ have h₄ : x + 2 ≠ 0 := by<br>  intro h<br>  apply h₁<br>  linarith ⟶ field_simp at h₂ ⟶ nlinarith |
| mathd_algebra_181 | have h₂ : n - 3 ≠ 0 := by<br>  intro h<br>  apply h₀<br>  linarith ⟶ field_simp at h₁ ⟶ nlinarith |
| amc12a_2017_p2 | field_simp ⟶ nlinarith |
| mathd_numbertheory_32 | have h₁ : S = Finset.filter (fun n => n ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀] ⟶ rw [h₁] ⟶ constructor |
| amc12a_2015_p10 | ring_nf at h₂ ⟶ rw [add_assoc] at h₂ ⟶ have h₃ : y ≤ 25 := by<br>  nlinarith ⟶ interval_cases y <;> omega |
| mathd_algebra_536 | norm_num [Nat.factorial] ⟶ field_simp ⟶ nlinarith [Real.sq_sqrt (show 0 ≤ 9 from by norm_num), Real.sqrt_nonneg 9] |
| mathd_algebra_206 | simp only [h₀] at h₂ h₃ ⟶ nlinarith [h₂, h₃, sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁)] |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all ⟶ rw [← sub_eq_zero] at h₀ ⊢ ⟶ simp [Complex.ext_iff, Complex.I_mul_I] at h₀ ⊢ ⟶ constructor <;> linarith |
| mathd_algebra_13 | constructor ⟶ all_goals<br>  have h₁ := h₀ 2<br>  have h₂ := h₀ 4<br>  have h₃ := h₀ 6<br>  have h₄ := h₀ 8<br>  simp [sub_eq_zero, sub_ne_zero, add_comm, add_left_comm, add_assoc] at h₁ h₂ h₃ h₄<br>  field_simp [sub_eq_zero, sub_ne_zero, add_comm, add_left_comm, add_assoc] at h₁ h₂ h₃ h₄<br>  ring_nf at h₁ h₂ h₃ h₄<br>  nlinarith |
| mathd_numbertheory_629 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  ·<br>    norm_num [Nat.lcm] ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht0, ht1⟩<br>  by_contra h<br>  push_neg at h<br>  have h1 : t ≤ 18 := by omega<br>  interval_cases t <;> norm_num [Nat.lcm, Nat.gcd_eq_right] at ht1 <;> omega |
| mathd_algebra_437 | norm_cast at h₀ h₁ ⟶ rw [eq_comm] ⟶ simp_all ⟶ norm_cast at * ⟶ norm_num at h₀ h₁ <;><br>ring_nf at h₀ h₁ <;><br>nlinarith [pow_two_nonneg (x - y), pow_two_nonneg (x + y)] |
| mathd_algebra_77 | constructor ⟶ {<br>  simp_all only [sq, mul_comm]<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  nlinarith<br>} ⟶ rw [h₂] at h₃ h₄ ⟶ next =><br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  nlinarith |
| aime_1984_p15 | field_simp at h₀ h₁ h₂ h₃ ⟶ nlinarith |
| mathd_algebra_59 | norm_num at h₀ ⟶ have h₁ : (4 : ℝ) ^ b = 4 := by linarith ⟶ simp_all ⟶ have h₂ : b = 1 := by<br>  apply_fun (fun x => Real.logb 4 x) at h₁<br>  simp_all ⟶ simp_all |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | ring_nf ⟶ use x ^ 2 + y ^ 2 + z ^ 2 - x * y - y * z - z * x ⟶ nlinarith |
| amc12b_2002_p6 | constructor ⟶ simp_all ⟶ ·<br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  simp [h₀] at h₂ h₃ h₄<br>  all_goals nlinarith [sq_nonneg (a + b), sq_nonneg (a - b)] ⟶ simp_all ⟶ apply mul_left_cancel₀ (sub_ne_zero.mpr h₀.2) ⟶ field_simp ⟶ nlinarith [h₁ 0, h₁ 1, h₁ (-1)] |
| aime_1983_p9 | rw [le_div_iff] ⟶ have h₁ := Real.sin_sq_add_cos_sq x ⟶ nlinarith [sq_nonneg (x * Real.sin x - 2 / 3)] ⟶ exact mul_pos h₀.1 (Real.sin_pos_of_pos_of_lt_pi h₀.1 (by linarith)) |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | constructor ⟶ ring_nf at h₀ h₁ ⊢ ⟶ all_goals apply mul_left_cancel₀ (show (2 : ℂ) ≠ 0 by norm_num) ⟶ rw [← sub_eq_zero] at h₀ h₁ ⟶ field_simp ⟶ rw [← sub_eq_zero] at h₀ h₁ ⟶ all_goals<br>  ring_nf at h₀ h₁<br>  simp [Complex.ext_iff, pow_two] at h₀ h₁ ⊢<br>  constructor <;> linarith |
| mathd_algebra_451 | have h₄ := h₀.symm ⟶ have h₅ := h₁.symm ⟶ have h₆ := h₂.symm ⟶ simp_all |
| induction_seq_mul2pnp1 | induction' n with n ih ⟶ omega ⟶ ring_nf ⟶ simp_all [Nat.pow_succ, Nat.mul_succ, Nat.mul_zero, Nat.add_zero] ⟶ cases n ⟶ norm_num [h₀, h₁] ⟶ simp_all [Nat.add_assoc, Nat.add_comm, Nat.add_left_comm]<br><;> omega |
| mathd_algebra_89 | ring_nf ⟶ norm_cast ⟶ norm_num<br><;> ring_nf<br><;> field_simp [h₀]<br><;> ring_nf<br><;> linarith |
| mathd_algebra_493 | simp_all ⟶ norm_num ⟶ have h₁ : Real.sqrt 4 = 2 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ have h₂ := Real.sqrt_nonneg (16 - 4 * Real.sqrt 4 + 1) ⟶ simp_all ⟶ nlinarith [sq_sqrt (show 0 ≤ 16 - 4 * 2 + 1 by norm_num)] |
| imo_1961_p1 | ring_nf ⟶ have h₇ : a > 0 := by linarith ⟶ refine' ⟨h₇, _, _⟩ ⟶ nlinarith ⟶ nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₁),<br>  sq_pos_of_ne_zero (sub_ne_zero.mpr h₂),<br>  sq_pos_of_ne_zero (sub_ne_zero.mpr h₃)] |
| mathd_numbertheory_690 | constructor ⟶ field_simp ⟶ all_goals norm_num [Nat.ModEq, Nat.ModEq] ⟶ ·<br>  intro a ha<br>  rcases ha with ⟨ha_pos, ha_mod2, ha_mod5, ha_mod7, ha_mod9⟩<br>  by_contra h<br>  push_neg at h<br>  interval_cases a <;> omega |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | field_simp ⟶ have h₃ : 0 ≤ Real.sqrt (x * y) := Real.sqrt_nonneg (x * y) ⟶ have h₄ := sq_sqrt (mul_nonneg h₀.1.le h₀.2.le) ⟶ nlinarith [sq_nonneg (x - y), sq_sqrt (mul_nonneg h₀.1.le h₀.2.le),<br>  sq_nonneg (x - y - 2 * Real.sqrt (x * y))] |
| numbertheory_prmdvsneqnsqmodpeq0 | field_simp ⟶ constructor <;> intro h ⟶ rw [Int.dvd_iff_emod_eq_zero] at h ⊢ ⟶ simp [h, pow_two, Int.mul_emod] ⟶ haveI : Fact p.Prime := ⟨h₀⟩ ⟶ have h₁ : (p : ℤ) ∣ n^2 := h ⟶ simp_all ⟶ exact (Int.prime_iff_natAbs_prime.mpr (by simpa using h₀)).dvd_of_dvd_pow h₁ |
| amc12b_2003_p17 | field_simp ⟶ have h₃ : 0 < x * y := mul_pos h₀.1 h₀.2 ⟶ have h₄ : 0 < x * y ^ 3 := by<br>  apply mul_pos h₀.1 (pow_pos h₀.2 3) ⟶ have h₅ : 0 < x ^ 2 * y := by nlinarith ⟶ field_simp [Real.log_mul, Real.log_rpow, Real.log_inv, h₀.1.ne', h₀.2.ne'] at * ⟶ nlinarith |
| amc12a_2008_p8 | ring_nf ⟶ have h₃ : 0 < x ∧ 0 < y := h₀ ⟶ have h₄ : y = 1 := by<br>  nlinarith [h₁] ⟶ simp_all ⟶ nlinarith [h₂, h₃, Real.sqrt_nonneg 2, sq_sqrt (show 0 ≤ 2 by norm_num), mul_self_nonneg (x - Real.sqrt 2)] |
