# Proof search: phase5_expansions_visible_student_v2

Run `phase5_expansions_visible_student_v2` on miniF2F-valid, git `131b69ffd84c4d6a99ad7f0aad69103ff1ddffe1`, config `experiments/configs/reasoning/phase5_expansions_visible_student_v2.toml` (copied as `config.toml`). Started 2026-10-15T18:23:28+00:00, 124.4 min wall, 46 CPUs, load average 56.3 at start.

**Solved 166/244 (68.0%).** Solved only with proofs of 2 or more steps: 40. Verification failures (bugs): 1. Proofs that also verify without the per-step heartbeat wrappers: 166/166. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 62 | 0.886 |
| mathd_numbertheory | 60 | 50 | 0.833 |
| amc12 | 45 | 23 | 0.511 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 2 | 0.1 |
| algebra | 18 | 16 | 0.889 |
| numbertheory | 8 | 5 | 0.625 |
| induction | 8 | 6 | 0.75 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 126 | 138 | 145 | 153 | 157 | 165 | 166 |
| solve rate | 51.6% | 56.6% | 59.4% | 62.7% | 64.3% | 67.6% | 68.0% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 | 7200 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 20 | 26 | 53 | 56 | 58 | 61 | 70 | 117 | 128 | 139 | 147 | 156 | 163 | 165 | 166 |
| solve rate | 8.2% | 10.7% | 21.7% | 23.0% | 23.8% | 25.0% | 28.7% | 48.0% | 52.5% | 57.0% | 60.2% | 63.9% | 66.8% | 67.6% | 68.0% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 1200 | 1800 | 3600 | 7200 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 70 | 84 | 125 | 132 | 142 | 149 | 159 | 162 | 163 | 164 | 165 | 166 | 166 | 166 | 166 |
| solve rate | 28.7% | 34.4% | 51.2% | 54.1% | 58.2% | 61.1% | 65.2% | 66.4% | 66.8% | 67.2% | 67.6% | 68.0% | 68.0% | 68.0% | 68.0% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 166 |
| expansion_budget | 54 |
| frontier_exhausted | 12 |
| wall_clock_budget | 12 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 18.8 | 1 | 64 | 64 | 4577 |
| nodes | 56.7 | 5 | 200 | 407 | 13837 |
| edges | 360 | 19 | 1285 | 1446 | 87875 |
| lean_seconds | 339 | 4.24 | 1029 | 4833 | 82673 |
| wall_seconds | 1925 | 166 | 6696 | 7214 | 469793 |
| duplicates | 53.1 | 2 | 198 | 381 | 12949 |
| errors | 250 | 13 | 891 | 1153 | 60886 |
| timeouts | 8.93 | 0 | 26 | 276 | 2179 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 1.83 | 0.855 | 3.74 | 24.7 | 446 |

solved (166 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 2.82 | 1 | 6 | 46 | 468 |
| nodes | 9.46 | 4 | 21 | 218 | 1571 |
| edges | 42.7 | 9 | 117 | 898 | 7091 |
| lean_seconds | 17.6 | 1.97 | 31.4 | 847 | 2927 |
| wall_seconds | 278 | 102 | 771 | 4995 | 46198 |
| duplicates | 6.31 | 1 | 15 | 104 | 1048 |
| errors | 30 | 5 | 93 | 730 | 4979 |
| timeouts | 0.349 | 0 | 0 | 24 | 58 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.68 | 1.43 | 6.7 | 24.7 | 446 |

unsolved (78 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 52.7 | 64 | 64 | 64 | 4109 |
| nodes | 157 | 170 | 274 | 407 | 12266 |
| edges | 1036 | 1212 | 1368 | 1446 | 80784 |
| lean_seconds | 1022 | 452 | 3380 | 4833 | 79746 |
| wall_seconds | 5431 | 6234 | 7203 | 7214 | 423595 |
| duplicates | 153 | 148 | 270 | 381 | 11901 |
| errors | 717 | 824 | 1050 | 1153 | 55907 |
| timeouts | 27.2 | 4 | 84 | 276 | 2121 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 56661 | 74558 | 90.2% | 1.32 | 9633 | 7838 | 35995 | 38760 | 0 | 2162 | 0 | 101 | 0 |
| omega | 4577 | 2707 | 3.3% | 0.592 | 28 | 1 | 4548 | 4548 | 0 | 0 | 0 | 27 | 27 |
| simp_all | 4345 | 2040 | 2.5% | 0.469 | 1696 | 1120 | 1529 | 1525 | 0 | 4 | 0 | 3 | 15 |
| nlinarith | 4234 | 1805 | 2.2% | 0.426 | 14 | 5 | 4215 | 4205 | 0 | 10 | 0 | 12 | 12 |
| field_simp | 4534 | 653 | 0.8% | 0.144 | 614 | 420 | 3500 | 3500 | 0 | 0 | 0 | 0 | 3 |
| ring_nf | 4451 | 546 | 0.7% | 0.123 | 920 | 3529 | 2 | 0 | 0 | 2 | 0 | 8 | 15 |
| rfl | 4523 | 171 | 0.2% | 0.0378 | 3 | 3 | 4517 | 4516 | 0 | 1 | 0 | 3 | 3 |
| constructor | 4550 | 167 | 0.2% | 0.0366 | 685 | 33 | 3832 | 3832 | 0 | 0 | 0 | 13 | 15 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 126 |
| 2 | 15 |
| 3 | 8 |
| 4 | 6 |
| 5 | 8 |
| 6 | 1 |
| 8 | 1 |
| 9 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| induction_divisibility_3divnto3m2n | have h : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases h with (h \| h \| h) <;> simp [h, pow_three, Nat.dvd_iff_mod_eq_zero, Nat.mul_mod, Nat.add_mod, Nat.mod_mod] at * <;> omega |
| mathd_algebra_13 | have h₁ := h₀ 0<br>have h₂ := h₀ 1<br>have h₃ := h₀ 2<br>have h₄ := h₀ 4<br>have h₅ := h₀ 6<br>have h₆ := h₀ 7<br>field_simp at h₁ h₂ h₃ h₄ h₅ h₆<br>norm_num at h₁ h₂ h₃ h₄ h₅ h₆<br>ring_nf at h₁ h₂ h₃ h₄ h₅ h₆ ⟶ exact ⟨by linarith, by linarith⟩ |
| mathd_numbertheory_32 | have h₁ : ∑ k in Finset.filter (λ k => k ∣ 36) (Finset.range 37), k = 91 := by<br>  rfl ⟶ have h₂ : S = Finset.filter (fun k => k ∣ 36) (Finset.range 37) := by<br>  ext x<br>  simp only [h₀]<br>  <;> simp_all [Finset.mem_filter]<br>  <;> tauto<br>rw [h₂] at *<br>exact h₁ |
| mathd_algebra_59 | ring_nf at h₀ ⊢ ⟶ have h₁ : (4 : ℝ) ^ b = 4 := by linarith<br>have h₂ : b = 1 := by<br>  apply_fun fun x ↦ Real.logb 4 x at h₁<br>  simp at h₁ ⊢<br>  linarith<br>exact h₂ |
| mathd_algebra_22 | field_simp [Real.logb, Real.log_rpow, Real.log_pow] ⟶ ring_nf |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | have h₁ : x^3 + y^3 + z^3 = (x + y + z + 6) * (x^2 + y^2 + z^2 - x * y - x * z - y * z) := by<br>  linarith [sq_nonneg (x + y + z), sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)] ⟶ simp_all |
| amc12_2000_p11 | field_simp [h₀] at *<br>ring ⟶ have h₂ : a * b = a - b := h₁<br>have h₃ : a ^ 2 - a ^ 2 * b ^ 2 + b ^ 2 = a * b * 2 := by<br>  nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), sq_nonneg (a * b - 1)]<br>exact h₃ |
| mathd_numbertheory_156 | have h_main : Nat.gcd (n + 7) (2 * n + 1) ∣ 13 := by<br>  have h₁ : Nat.gcd (n + 7) (2 * n + 1) ∣ (n + 7) := Nat.gcd_dvd_left (n + 7) (2 * n + 1)<br>  have h₂ : Nat.gcd (n + 7) (2 * n + 1) ∣ (2 * n + 1) := Nat.gcd_dvd_right (n + 7) (2 * n + 1)<br>  have h₃ : Nat.gcd (n + 7) (2 * n + 1) ∣ 2 * (n + 7) := dvd_mul_of_dvd_right h₁ 2<br>  have h₄ : Nat.gcd (n + 7) (2 * n + 1) ∣ 2 * (n + 7) - (2 * n + 1) := Nat.dvd_sub' h₃ h₂<br>  have h₅ : 2 * (n + 7) - (2 * n + 1) = 13 := by<br>    ring_nf<br>    omega<br>  rw [h₅] at h₄<br>  exact h₄<br>have h_final : Nat.gcd (n + 7) (2 * n + 1) ≤ 13 := by<br>  have h₆ : Nat.gcd (n + 7) (2 * n + 1) ∣ 13 := h_main<br>  have h₇ : Nat.gcd (n + 7) (2 * n + 1) ≤ 13 := by<br>    apply Nat.le_of_dvd (by norm_num) h₆<br>  exact h₇ ⟶ omega |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⊢<br>ring_nf at h₀ h₁ ⊢ ⟶ norm_cast at h₀ h₁ ⊢<br>ring_nf at h₀ h₁ ⊢ ⟶ omega |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | rw [h₁] at h₀ ⊢<br>ring_nf at h₀ ⊢ ⟶ have h₂ : a * Complex.I + b * Complex.I = (a + b) * Complex.I := by ring<br>rw [h₂, h₀]<br>simp [Complex.ext_iff, Complex.I_mul_I] |
| mathd_algebra_73 | ring_nf at h₀<br>apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)<br>ring_nf at h₀ ⊢ ⟶ ring_nf ⟶ ring_nf at h₀ ⊢<br>linear_combination h₀ |
| mathd_algebra_393 | have h₁ : σ.toFun 2 = 33 := by<br>  rw [h₀]<br>  <;> norm_num ⟶ simp_all ⟶ have h₂ : σ 2 = 33 := by<br>  rw [h₀]<br>  norm_num [h₁]<br>rw [← h₂]<br>simp [Function.comp_id, h₁] |
| mathd_numbertheory_232 | simp_all ⟶ rfl |
| numbertheory_2dvd4expn | apply dvd_pow<br><;> norm_num ⟶ omega |
| amc12b_2003_p6 | have h₃ : r ^ 2 = 3 := by<br>  have h₄ : u 1 = a * r := by<br>    simp [h₀, mul_one]<br>  have h₅ : u 3 = a * r ^ 3 := by<br>    simp [h₀, mul_one]<br>  rw [h₁, h₂] at *<br>  have h₆ : a * r = 2 := by linarith<br>  have h₇ : a * r ^ 3 = 6 := by linarith<br>  have h₈ : r ≠ 0 := by<br>    by_contra h<br>    rw [h] at h₆<br>    norm_num at h₆<br>  have h₉ : r ^ 2 = 3 := by<br>    have h₁₀ : r ^ 3 = (r ^ 2) * r := by ring<br>    rw [h₁₀] at h₇<br>    have h₁₁ : a * (r ^ 2) * r = 6 := by linarith<br>    have h₁₂ : a * r = 2 := by linarith<br>    have h₁₃ : (r ^ 2) * (a * r) = 6 := by<br>      ring_nf at h₁₁ ⊢<br>      linarith<br>    rw [h₁₂] at h₁₃<br>    linarith<br>  exact h₉<br>have h₄ : r = Real.sqrt 3 ∨ r = -Real.sqrt 3 := by<br>  have : r ^ 2 = 3 := h₃<br>  have : r = Real.sqrt 3 ∨ r = -Real.sqrt 3 := by<br>    apply or_iff_not_imp_left.mpr<br>    intro h<br>    apply mul_left_cancel₀ (sub_ne_zero.mpr h)<br>    nlinarith [Real.sqrt_nonneg 3, Real.sq_sqrt (show 0 ≤ 3 by norm_num)]<br>  exact this ⟶ cases' h₄ with h₄ h₄ ⟶ ring_nf ⟶ case inl =><br>  have h₅ : u 0 = a := by<br>    rw [h₀ 0]<br>    <;> simp [pow_zero]<br>  have h₆ : a = 2 / r := by<br>    have : a * r = 2 := by<br>      simpa [h₀ 1] using h₁<br>    have h₇ : r ≠ 0 := by<br>      rw [h₄]<br>      norm_num [Real.sqrt_eq_zero]<br>    field_simp at this ⊢<br>    linarith<br>  rw [h₅, h₆]<br>  rw [h₄]<br>  <;> norm_num<br>  <;> field_simp<br>  <;> ring<br>  <;> norm_num<br>  <;> linarith [Real.sqrt_nonneg 3]<br>case inr =><br>  have h₅ : u 0 = a := by<br>    rw [h₀ 0]<br>    <;> simp [pow_zero]<br>  have h₆ : a = 2 / r := by<br>    have : a * r = 2 := by<br>      simpa [h₀ 1] using h₁<br>    have h₇ : r ≠ 0 := by<br>      rw [h₄]<br>      norm_num [Real.sqrt_eq_zero]<br>    field_simp at this ⊢<br>    linarith<br>  rw [h₅, h₆]<br>  rw [h₄]<br>  <;> norm_num<br>  <;> field_simp<br>  <;> ring<br>  <;> norm_num<br>  <;> linarith [Real.sqrt_nonneg 3] |
| mathd_algebra_131 | simp_all ⟶ have h₄ : a + b = 7/2 := by<br>  have h₅ : 2 * a ^ 2 - 7 * a + 2 = 0 := h₁<br>  have h₆ : 2 * b ^ 2 - 7 * b + 2 = 0 := h₂<br>  have h₇ : a ≠ b := h₃<br>  have h₈ : a + b = 7/2 := by<br>    apply eq_of_sub_eq_zero<br>    field_simp at h₅ h₆ ⊢<br>    ring_nf at h₅ h₆ ⊢<br>    nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₇)]<br>  exact h₈<br>have h₅ : a * b = 1 := by<br>  have h₆ : 2 * a ^ 2 - 7 * a + 2 = 0 := h₁<br>  have h₇ : 2 * b ^ 2 - 7 * b + 2 = 0 := h₂<br>  have h₈ : a ≠ b := h₃<br>  have h₉ : a * b = 1 := by<br>    apply eq_of_sub_eq_zero<br>    field_simp at h₆ h₇ ⊢<br>    ring_nf at h₆ h₇ ⊢<br>    nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₈)]<br>  exact h₉ ⟶ field_simp [(show a - 1 ≠ 0 by nlinarith), (show b - 1 ≠ 0 by nlinarith)] ⟶ nlinarith |
| mathd_numbertheory_629 | constructor<br>· constructor<br>  · norm_num<br>  · norm_num [Nat.lcm] ⟶ · intro t ht<br>  have h₁ : 0 < t := ht.1<br>  have h₂ : Nat.lcm 12 t ^ 3 = (12 * t) ^ 2 := ht.2<br>  by_contra h<br>  have h₃ : t < 18 := by linarith<br>  interval_cases t <;> norm_num at h₂ ⊢ <;> try contradiction |
| mathd_algebra_536 | field_simp ⟶ norm_num [factorial, Real.sqrt_eq_iff_sq_eq]<br><;> norm_num<br><;> ring_nf<br><;> norm_num<br><;> nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show 0 ≤ 9 by norm_num)] |
| numbertheory_prmdvsneqnsqmodpeq0 | refine' ⟨fun h => _, fun h => _⟩ ⟶ simp_all [Int.ModEq, Int.emod_eq_emod_iff_emod_sub_eq_zero, pow_two] ⟶ exact dvd_mul_of_dvd_left h n ⟶ have h₁ : (p : ℤ) ∣ n ^ 2 := by<br>  simpa [Int.emod_eq_emod_iff_emod_sub_eq_zero] using h<br>have h₂ : (p : ℤ) ∣ n := by<br>  apply (Int.prime_iff_natAbs_prime.mpr (by exact_mod_cast h₀)).dvd_of_dvd_pow<br>  exact h₁<br>exact_mod_cast h₂ |
| mathd_numbertheory_780 | simp_all ⟶ have h₄ : m ∣ (x - 36) := h₃ ⟶ have h₅ : m ∣ (x - 36) := h₄<br>have h₆ : x ≡ 36 [ZMOD m] := by<br>  rw [Int.ModEq]<br>  simpa [Int.emod_eq_emod_iff_emod_sub_eq_zero] using h₅ ⟶ have h₇ : m = 43 := by<br>  have h₈ : m ∣ x - 36 := h₃<br>  have h₉ : m ≥ 10 := by linarith<br>  have h₁₀ : m ≤ 99 := by linarith<br>  interval_cases m <;> norm_num at h₂ h₃ h₆ ⊢ <;><br>    (try contradiction) <;><br>    (try omega) <;><br>    (try norm_num) <;><br>    (try ring_nf at h₂ h₃ h₆ ⊢ <;> omega) ⟶ omega |
| mathd_algebra_509 | have h₁ : Real.sqrt 80 = 4 * Real.sqrt 5 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  <;> ring_nf<br>  <;> norm_num<br>  <;><br>  (try ring_nf) <;><br>  (try norm_num) <;><br>  (try field_simp) <;><br>  (try norm_num) <;><br>  (try ring_nf) <;><br>  (try norm_num)<br>  <;><br>  nlinarith [Real.sqrt_nonneg 5, Real.sq_sqrt (show 0 ≤ 5 by norm_num)]<br>have h₂ : Real.sqrt 845 = 13 * Real.sqrt 5 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  <;> ring_nf<br>  <;> norm_num<br>  <;><br>  (try ring_nf) <;><br>  (try norm_num) <;><br>  (try field_simp) <;><br>  (try norm_num) <;><br>  (try ring_nf) <;><br>  (try norm_num)<br>  <;><br>  nlinarith [Real.sqrt_nonneg 5, Real.sq_sqrt (show 0 ≤ 5 by norm_num)]<br>have h₃ : Real.sqrt 45 = 3 * Real.sqrt 5 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>  <;> ring_nf<br>  <;> norm_num<br>  <;><br>  (try ring_nf) <;><br>  (try norm_num) <;><br>  (try field_simp) <;><br>  (try norm_num) <;><br>  (try ring_nf) <;><br>  (try norm_num)<br>  <;><br>  nlinarith [Real.sqrt_nonneg 5, Real.sq_sqrt (show 0 ≤ 5 by norm_num)]<br>rw [h₁, h₂, h₃]<br>field_simp [Real.sqrt_eq_iff_sq_eq]<br>ring_nf ⟶ norm_num [h₁, h₂, h₃, Real.sqrt_eq_iff_sq_eq] ⟶ field_simp [h₁, h₂, h₃, Real.sqrt_eq_iff_sq_eq]<br>ring_nf ⟶ have h₄ : √4 = 2 := by rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>have h₅ : √9 = 3 := by rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num<br>ring_nf at * ⟶ rw [h₄, h₅]<br>ring |
| mathd_numbertheory_64 | simp [IsLeast, Nat.ModEq, Nat.ModEq.refl] ⟶ ring_nf ⟶ intro x hx<br>have h : x * 30 % 47 = 42 := hx<br>have h₁ : x ≥ 39 := by<br>  by_contra h₂<br>  have h₃ : x ≤ 38 := by omega<br>  have h₄ : x * 30 % 47 ≠ 42 := by<br>    have h₅ : x < 39 := by omega<br>    interval_cases x <;> norm_num at h ⊢ <;> omega<br>  contradiction<br>exact h₁ |
| mathd_numbertheory_690 | constructor ⟶ decide ⟶ intro a ha ⟶ simp_all [Nat.ModEq, Nat.ModEq]<br><;> omega |
| mathd_numbertheory_35 | have h_sqrt : Nat.sqrt 196 = 14 := by norm_num ⟶ rw [h_sqrt] at h₀<br>have h₁ : (1 : ℕ) ∣ 14 := by norm_num<br>have h₂ : (2 : ℕ) ∣ 14 := by norm_num<br>have h₃ : (7 : ℕ) ∣ 14 := by norm_num<br>have h₄ : (14 : ℕ) ∣ 14 := by norm_num ⟶ have h_sum : ∑ k in Finset.filter (fun k => k ∣ 14) (Finset.range 15), k = 24 := by<br>  rfl ⟶ simp_all ⟶ rw [← h_sum] ⟶ simp_all [Finset.sum_range_succ, Finset.sum_range_succ] |
| amc12a_2015_p10 | have h₃ : (x + 1) * (y + 1) = 81 := by<br>  have h₄ : x + y + x * y = 80 := h₂<br>  have h₅ : (x + 1) * (y + 1) = x + y + x * y + 1 := by ring<br>  rw [h₅] at h₅<br>  linarith<br>have h₄ : y + 1 > 1 := by linarith<br>have h₅ : y + 1 < x + 1 := by linarith ⟶ have h₆ : y + 1 ≥ 3 := by<br>  have : y + 1 > 2 := by<br>    have : y ≥ 2 := by<br>      by_contra h<br>      push_neg at h<br>      interval_cases y <;> norm_num at h₀ h₁ h₂ h₃ h₄ h₅ ⊢ <;><br>        (try omega) <;><br>        (try {<br>          linarith<br>        })<br>    linarith<br>  linarith ⟶ have : y + 1 ∣ 81 := by<br>  use x + 1<br>  <;> linarith<br>have : y + 1 = 3 ∨ y + 1 = 9 ∨ y + 1 = 27 ∨ y + 1 = 81 := by<br>  have : y + 1 ≤ 81 := by<br>    nlinarith<br>  have : y + 1 ≥ 3 := h₆<br>  have : y + 1 ∣ 81 := by<br>    use x + 1<br>    <;> linarith<br>  interval_cases y + 1 <;> norm_num at this ⊢ <;> omega<br>rcases this with (h \| h \| h \| h) <;><br>  (try { nlinarith }) <;><br>  (try { linarith }) <;><br>  (try { nlinarith }) <;><br>  (try { linarith }) |
| mathd_algebra_493 | simp only [h₀, pow_two, mul_comm]<br>norm_num ⟶ have h₁ : Real.sqrt 4 = 2 := by<br>  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ simp_all ⟶ rw [show (16 - 4 * 2 + 1 : ℝ) = 9 by norm_num]<br>rw [show Real.sqrt (9 : ℝ) = 3 by norm_num [Real.sqrt_eq_iff_sq_eq]]<br>ring |
| mathd_algebra_185 | simp_all ⟶ apply Eq.symm ⟶ simp only [Finset.card] ⟶ simp_all [abs_lt, Int.emod_eq_of_lt] ⟶ have h₂ : s = Finset.Icc (-12) 4 := by<br>  ext x<br>  simp only [h₁, Finset.mem_Icc]<br>  constructor <;> intro h <;> constructor <;> linarith<br>rw [h₂]<br>rfl |
| amc12b_2003_p17 | have h₃ : Real.log (x * y ^ 3) = 1 := h₁<br>have h₄ : Real.log (x ^ 2 * y) = 1 := h₂ ⟶ have h₅ : Real.log (x * y ^ 3) = 1 := h₁<br>have h₆ : Real.log (x ^ 2 * y) = 1 := h₂<br>field_simp [Real.log_mul, Real.log_pow] at h₅ h₆ ⊢<br>ring_nf at h₅ h₆ ⊢ ⟶ have h₇ := h₁<br>have h₈ := h₂ ⟶ have h₉ := h₁<br>have h₁₀ := h₂ ⟶ norm_num at h₁ h₂<br>field_simp [Real.log_mul, Real.log_rpow, h₀.1.ne', h₀.2.ne'] at h₁ h₂ ⊢<br>linarith |
| mathd_algebra_323 | simp [h] ⟶ simp_all [pow_three] ⟶ simp [h, pow_succ, mul_assoc, mul_comm, mul_left_comm, sub_eq_add_neg, add_assoc] ⟶ simp [h, σ.symm_apply_eq, mul_comm, mul_assoc, mul_left_comm] ⟶ have h₁ : σ.symm 19 = 3 := by<br>  have h₂ : σ 3 = 19 := by<br>    rw [h]<br>    norm_num<br>  rw [← h₂]<br>  simpa using σ.symm.symm 19<br>rw [h₁]<br>ring |
| algebra_amgm_sumasqdivbsqgeqsumbdiva | field_simp [h₀.1.ne', h₀.2.1.ne', h₀.2.2.ne'] ⟶ have h₁ : 0 < a := h₀.1<br>have h₂ : 0 < b := h₀.2.1<br>have h₃ : 0 < c := h₀.2.2<br>have h₄ : 0 < a * b := mul_pos h₁ h₂<br>have h₅ : 0 < a * c := mul_pos h₁ h₃<br>have h₆ : 0 < b * c := mul_pos h₂ h₃<br>have h₇ : 0 < a * b * c := by positivity<br>have h₈ : 0 < a^2 := pow_pos h₁ 2<br>have h₉ : 0 < b^2 := pow_pos h₂ 2<br>have h₁₀ : 0 < c^2 := pow_pos h₃ 2<br>have h₁₁ : 0 < a^2 * b^2 := by positivity<br>have h₁₂ : 0 < a^2 * c^2 := by positivity<br>have h₁₃ : 0 < b^2 * c^2 := by positivity<br>field_simp [h₁, h₂, h₃, h₄, h₅, h₆, h₇, h₈, h₉, h₁₀, h₁₁, h₁₂, h₁₃]<br>rw [div_le_div_iff (by positivity) (by positivity)] ⟶ ring_nf at * ⟶ nlinarith [sq_nonneg (b * c ^ 2 - c * a ^ 2), sq_nonneg (c * a ^ 2 - a * b ^ 2), sq_nonneg (a * b ^ 2 - b * c ^ 2), mul_pos h₁ h₂, mul_pos h₂ h₃, mul_pos h₃ h₁] |
| mathd_algebra_433 | have h₁ := h₀ 8 ⟶ rw [h₁] ⟶ ring_nf ⟶ norm_num [Real.sqrt_eq_iff_sq_eq, sq, mul_comm] at * ⟶ ring_nf ⟶ simp_all ⟶ have h₂ : √9 = 3 := by<br>  rw [Real.sqrt_eq_iff_sq_eq]<br>  <;> norm_num ⟶ nlinarith |
| mathd_algebra_482 | have h₆ : m ^ 2 - 12 * m + k = 0 := by<br>  rw [h₂] at h₃<br>  exact_mod_cast h₃<br>have h₇ : n ^ 2 - 12 * n + k = 0 := by<br>  rw [h₂] at h₄<br>  exact_mod_cast h₄<br>have h₈ : m ≠ n := h₅ ⟶ ring_nf at h₆ h₇ ⟶ have h₉ : m + n = 12 := by<br>  have h₉₁ : (m : ℝ) + n = 12 := by<br>    apply eq_of_sub_eq_zero<br>    have h₉₂ : (m - n : ℝ) * (m + n - 12) = 0 := by<br>      ring_nf at h₆ h₇ ⊢<br>      linarith<br>    have h₉₃ : (m : ℝ) ≠ (n : ℝ) := by<br>      norm_cast<br>      <;> simp_all [h₅]<br>    have h₉₄ : (m + n : ℝ) - 12 = 0 := by<br>      apply eq_of_sub_eq_zero<br>      apply mul_left_cancel₀ (sub_ne_zero.mpr h₉₃)<br>      linarith<br>    norm_num at h₉₄ ⊢<br>    <;> linarith<br>  have h₉₅ : (m : ℝ) + (n : ℝ) = 12 := by<br>    linarith<br>  norm_cast at h₉₅ ⊢<br>  <;> linarith ⟶ have h₁₀ : m = 5 ∧ n = 7 ∨ m = 7 ∧ n = 5 := by<br>  have : m ≤ 12 := by linarith<br>  have : n ≤ 12 := by linarith<br>  interval_cases m <;> interval_cases n <;> norm_num [Nat.Prime] at h₀ h₁ h₅ ⊢ <;> tauto ⟶ rcases h₁₀ with (⟨rfl, rfl⟩ \| ⟨rfl, rfl⟩) <;> norm_num at h₆ h₇ <;><br>  (try norm_num at h₆ h₇) <;><br>  (try linarith) <;><br>  (try ring_nf at h₆ h₇) <;><br>  (try linarith) |
| mathd_algebra_89 | simp_all ⟶ have h₁ : (7 * b ^ 3) ^ 2 * ((4 * b ^ 2) ^ 3)⁻¹ = 49 / 64 := by<br>  have h₂ : b ≠ 0 := h₀<br>  have h₃ : (7 * b ^ 3) ^ 2 = 49 * b ^ 6 := by<br>    ring<br>  have h₄ : ((4 * b ^ 2) ^ 3)⁻¹ = 1 / (64 * b ^ 6) := by<br>    have h₅ : ((4 * b ^ 2) ^ 3) = 64 * b ^ 6 := by<br>      ring<br>    rw [h₅]<br>    <;> field_simp [h₂]<br>    <;> ring<br>  rw [h₃, h₄]<br>  field_simp [h₂]<br>  <;> ring ⟶ exact h₁ |
| mathd_algebra_480 | simp_all ⟶ have h₃ : 0 ≤ Real.pi := by<br>  exact Real.pi_pos.le<br>have h₄ : Real.pi < 4 := by<br>  have := Real.pi_gt_31415<br>  have := Real.pi_lt_31416<br>  norm_num at *<br>  <;> linarith<br>rw [h₁ Real.pi h₃ h₄]<br><;> norm_num |
| amc12a_2016_p3 | norm_num [h₀] ⟶ have h₁ : ⌊-(15 / 16 : ℝ)⌋ = -1 := by<br>  norm_num [Int.floor_eq_iff]<br>rw [h₁]<br>norm_num<br><;> rfl |
| numbertheory_nckeqnm1ckpnm1ckm1 | cases' h₁ with h₁ h₁ ⟶ simp_all ⟶ induction n with<br>\| zero => contradiction<br>\| succ n ih => cases' h₀ with n hn <;> simp_all [Nat.choose_succ_succ, Nat.choose_zero_right, Nat.choose_one_right] ⟶ simp_all ⟶ ring_nf ⟶ induction k <;> simp_all [Nat.choose_succ_succ] ⟶ ring_nf ⟶ simp [Nat.choose_succ_succ, Nat.add_comm, Nat.add_left_comm, Nat.add_assoc] ⟶ constructor |
| amc12a_2003_p24 | constructor ⟶ case left =><br>  use 2, 2<br>  constructor<br>  · norm_num<br>  · constructor<br>    · norm_num<br>    · norm_num [Real.logb, Real.log_div, Real.log_one] ⟶ ring_nf<br>simp [Real.logb, Real.log_div, Real.log_rpow, Real.log_one, Real.log_mul, Real.log_pow] ⟶ intro y hy<br>rcases hy with ⟨a, b, h1, h2, h3⟩<br>have : 0 < a := by linarith<br>have : 0 < b := by linarith<br>have : 0 < Real.log a := Real.log_pos (by linarith)<br>have : 0 < Real.log b := Real.log_pos (by linarith)<br>field_simp [Real.log_mul, Real.log_inv, Real.log_div] at *<br>ring_nf at * ⟶ have h : y = (a.log * b.log * 2 + (-a.log ^ 2 - b.log ^ 2)) / (a.log * b.log) := by<br>  field_simp at h3 ⊢<br>  linarith<br>rw [h]<br>have h4 : 0 < a.log * b.log := by positivity<br>have h5 : a.log * b.log * 2 + (-a.log ^ 2 - b.log ^ 2) ≤ 0 := by<br>  nlinarith [sq_nonneg (a.log - b.log)]<br>have h6 : (a.log * b.log * 2 + (-a.log ^ 2 - b.log ^ 2)) / (a.log * b.log) ≤ 0 := by<br>  apply div_nonpos_of_nonpos_of_nonneg<br>  · linarith<br>  · linarith<br>exact h6 |
| mathd_algebra_437 | norm_num [pow_three] at h₀ h₁ ⟶ have h_x_lt_y : x < y := by<br>  have h₄ : x * (x * x) = -45 := h₀<br>  have h₅ : y * (y * y) = -101 := h₁<br>  have h₆ : x < y := by<br>    exact by<br>      nlinarith [sq_pos_of_neg (show x < 0 by nlinarith), sq_pos_of_neg (show y < 0 by nlinarith)]<br>  exact h₆ ⟶ nlinarith [sq_nonneg (x - y), sq_nonneg (x + y)] |
| algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4 | have h₃ : 0 ≤ x * y := by nlinarith<br>have h₄ : 0 ≤ Real.sqrt (x * y) := Real.sqrt_nonneg (x * y)<br>have h₅ : 0 ≤ x - y := by linarith<br>have h₆ : 0 ≤ (x - y) * Real.sqrt (x * y) := by nlinarith<br>have h₇ : (Real.sqrt (x * y) * (x - y)) ^ 2 = (x + y) ^ 2 := by<br>  rw [h₂]<br>  <;> ring ⟶ field_simp ⟶ nlinarith [sq_nonneg (x - y - 2 * Real.sqrt (x * y)), Real.sq_sqrt (show 0 ≤ x * y by nlinarith)] |
| mathd_algebra_422 | field_simp ⟶ have h₂ := h₀ (x + 1)<br>have h₃ := h₀ x<br>simp [h₀, h₀, mul_comm, mul_assoc, mul_left_comm] at h₁ h₂ h₃ ⟶ have h₄ := h₁<br>ring_nf at h₄ ⟶ have h₅ := congr_arg σ.toFun h₄<br>rw [h₀] at h₅ ⟶ field_simp at h₁ h₄ h₅ ⊢<br>linarith |
