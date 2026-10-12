# phase2_sft_v2_search vs phase0_automation_baseline

**Solved 148/244 (60.7%) vs 79/244 (32.4%) for row 0**: 69 newly solved, 0 lost. Proofs using at least one policy step: 85. Row 0 ran 256 expansions and 300 s per theorem with 32 processes; see each run's config for its budget.

## By category

| category | problems | row 0 | this run | newly solved | lost |
|---|---|---|---|---|---|
| mathd_algebra | 70 | 28 | 53 | 25 | 0 |
| mathd_numbertheory | 60 | 38 | 49 | 11 | 0 |
| amc12 | 45 | 8 | 18 | 10 | 0 |
| aime | 15 | 0 | 1 | 1 | 0 |
| imo | 20 | 0 | 1 | 1 | 0 |
| algebra | 18 | 5 | 15 | 10 | 0 |
| numbertheory | 8 | 0 | 4 | 4 | 0 |
| induction | 8 | 0 | 7 | 7 | 0 |

## Anytime curves (solved theorems at budget)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| row 0 | 59 | 72 | 77 | 79 | 79 | 79 | 79 |
| this run | 83 | 102 | 128 | 136 | 141 | 144 | 148 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 615.485 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| row 0 | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| this run | 33 | 47 | 69 | 91 | 118 | 124 | 135 | 140 | 140 | 146 | 148 | 148 |

## Cost per theorem

| quantity | value |
|---|---|
| mean / median generated tokens | 8684 / 1246 |
| total generated tokens | 2,118,971 |
| generated tokens per solved theorem | 14,317 |
| mean prompt tokens (computed once per request) | 5277 |
| mean / median wall seconds | 197.2 / 26.9 |
| mean Lean seconds | 155.1 |
| mean expansions | 22.5 |

## Throughput in the search

| quantity | value |
|---|---|
| run wall minutes | 25.5 |
| policy requests / samples | 5,412 / 86,592 |
| samples/s over the policy window | 58.4 |
| generated tokens/s | 1430 |
| mean request latency s | 1.82 |
| summed request s / summed Lean s | 9,842 / 37,843 |
| distinct candidates per request | 9.6 |
| duplicate / failed sample fraction | 38.5% / 1.4% |
| prompt cache hit rate | 86.7% |
| requests without candidates (unattributed tokens) | 0 (0) |
| prompts too long | 0 |

## Newly solved (P = policy step, A = automation)

- `aime_1984_p15`: [P] field_simp at h₀ h₁ h₂ h₃ ⟶ [A] linarith
- `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`: [A] constructor ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] apply Eq.symm ⟶ [P] rw [← sub_eq_zero] ⟶ [A] simp ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] linear_combination h₁ - 2 * h₀ ⟶ [P] linear_combination h₁ - h₀
- `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`: [P] intro x hx ⟶ [A] field_simp ⟶ [P] rw [div_le_iff (by positivity)] ⟶ [P] nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - Real.sqrt 2 / 2)]
- `algebra_amgm_sumasqdivbsqgeqsumbdiva`: [P] rcases h₀ with ⟨ha, hb, hc⟩ ⟶ [P] have h₁ : 0 < a * b := by positivity ⟶ [P] have h₂ : 0 < b * c := by positivity ⟶ [P] have h₃ : 0 < c * a := by positivity ⟶ [P] have h₄ : 0 < (a * b) * (b * c) := by positivity ⟶ [P] have h₅ : 0 < (b * c) * (c * a) := by positivity ⟶ [P] have h₆ : 0 < (c * a) * (a * b) := by positivity ⟶ [A] field_simp ⟶ [P] rw [div_le_div_iff (by positivity) (by positivity)] ⟶ [P] nlinarith [sq_nonneg (a^2 - b * c), sq_nonneg (b^2 - c * a), sq_nonneg (c^2 - a * b),
  sq_nonneg (a * b^2 - b * c^2), sq_nonneg (b * c^2 - c * a^2), sq_nonneg (c * a^2 - a * b^2)]
- `algebra_apb4leq8ta4pb4`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), sq_nonneg (a ^ 2 - b ^ 2), sq_nonneg (a ^ 2 + b ^ 2),
  sq_nonneg (a ^ 2 - 2 * a * b + b ^ 2), sq_nonneg (a ^ 2 + 2 * a * b + b ^ 2)]
- `algebra_binomnegdiscrineq_10alt28asqp1`: [P] nlinarith [sq_nonneg (a - 1 / 5)]
- `algebra_manipexpr_apbeq2cceqiacpbceqm2`: [P] rw [h₁] ⟶ [A] ring_nf ⟶ [A] aesop ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] rw [← sub_eq_zero] ⟶ [P] simp_all [Complex.ext_iff, Complex.I_mul_I]
<;> ring
<;> linarith
- `algebra_sqineq_2at2pclta2c2p41pc`: [P] nlinarith [sq_nonneg (a - c - 2)]
- `algebra_sqineq_2unitcircatblt1`: [P] nlinarith [sq_nonneg (a - b), h₀]
- `algebra_sqineq_36azm9asqle36zsq`: [P] nlinarith [sq_nonneg (a - 2 * z)]
- `algebra_sqineq_4bap1lt4bsqpap1sq`: [P] nlinarith [sq_nonneg (2 * b - (a + 1))]
- `amc12_2000_p11`: [P] have h₂ : a ≠ 0 := h₀.1 ⟶ [P] have h₃ : b ≠ 0 := h₀.2 ⟶ [A] field_simp ⟶ [A] ring_nf ⟶ [P] nlinarith [sq (a - b), sq (a + b), h₁, h₂, h₃]
- `amc12_2000_p5`: [P] cases' le_total 0 (x - 2) with h₂ h₂ <;>
simp_all [abs_of_nonneg, abs_of_nonpos, sub_eq_add_neg] <;>
linarith
- `amc12a_2009_p5`: [P] ring_nf at h₀ ⟶ [P] rw [h₀, show (5 : ℝ)^3 = 125 by norm_num]
<;> norm_num
- `amc12a_2009_p9`: [P] have h₂ := h₀ 0 ⟶ [P] have h₃ := h₀ 1 ⟶ [P] have h₄ := h₀ (-1) ⟶ [P] have h₅ := h₀ 2 ⟶ [P] have h₆ := h₀ (-2) ⟶ [P] have h₇ := h₀ 3 ⟶ [P] have h₈ := h₀ (-3) ⟶ [P] have h₉ := h₀ 4 ⟶ [P] have h₁₀ := h₀ (-4) ⟶ [P] have h₁₁ := h₀ 5 ⟶ [P] have h₁₂ := h₀ (-5) ⟶ [P] have h₁₃ := h₀ 6 ⟶ [P] have h₁₄ := h₀ (-6) ⟶ [P] norm_num at * ⟶ [A] simp_all
- `amc12a_2011_p18`: [P] cases' le_total 0 (x + y) with h₁ h₁ <;>
cases' le_total 0 (x - y) with h₂ h₂ <;>
simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;>
nlinarith
- `amc12a_2013_p8`: [P] field_simp at h₃ ⟶ [P] ring_nf at h₃ ⟶ [P] nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀),
  sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁), sq_nonneg (x - y), sq_nonneg (x - 1),
  sq_nonneg (y - 1)]
- `amc12a_2015_p10`: [P] ring_nf at h₂ ⟶ [P] have h₃ : y ≥ 1 := by linarith ⟶ [A] simp_all ⟶ [P] have h₄ : x + x * y + y = 80 := h₂ ⟶ [P] have h₅ := h₀ ⟶ [P] have h₆ : y < x := h₁ ⟶ [P] have h₇ : x + x * y + y = 80 := by linarith ⟶ [P] have h₈ : 1 ≤ y := by linarith ⟶ [P] have h₉ : 0 < y := by linarith ⟶ [P] have h₁₀ : y < x := by linarith ⟶ [A] simp_all ⟶ [P] revert x y ⟶ [P] intro x y h₁ h₂ h₃ h₄ ⟶ [P] have h₅ : y ≥ 1 := by linarith ⟶ [P] have h₆ : y ≤ 25 := by
  nlinarith ⟶ [P] interval_cases y <;> omega
- `amc12b_2002_p6`: [P] have h₂ := h₁ 0 ⟶ [P] have h₃ := h₁ 1 ⟶ [P] have h₄ := h₁ (-1) ⟶ [P] have h₅ := h₁ 2 ⟶ [P] have h₆ := h₁ (-2) ⟶ [P] have h₇ := h₁ 3 ⟶ [P] have h₈ := h₁ (-3) ⟶ [P] have h₉ := h₁ 4 ⟶ [P] have h₁₀ := h₁ (-4) ⟶ [P] have h₁₁ := h₁ 5 ⟶ [P] have h₁₂ := h₁ (-5) ⟶ [P] norm_num at h₂ h₃ h₄ h₅ h₆ h₇ h₈ h₉ h₁₀ h₁₁ h₁₂ ⟶ [A] constructor ⟶ [P] all_goals
  nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.1), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.2)]
- `amc12b_2003_p17`: [A] field_simp ⟶ [A] aesop ⟶ [P] have h₃ : 0 < x * y := mul_pos left right ⟶ [P] have h₄ : 0 < x * y ^ 3 := by positivity ⟶ [P] have h₅ : 0 < x ^ 2 * y := by positivity ⟶ [P] have h₆ : 0 < x ^ 2 * y ^ 3 := by positivity ⟶ [P] field_simp [Real.log_mul, Real.log_rpow] at h₁ h₂ ⊢ ⟶ [A] linarith
- `amc12b_2020_p5`: [P] ring_nf at h₀ h₁ ⟶ [P] field_simp at h₀ h₁ ⟶ [P] ring_nf at h₀ h₁ ⟶ [P] norm_cast at h₀ h₁ ⟶ [A] omega
- `imo_1961_p1`: [A] constructor ⟶ [A] linarith ⟶ [A] simp_all ⟶ [P] next =>
  constructor
  nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₁), sq_pos_of_ne_zero (sub_ne_zero.mpr h₂),
    sq_pos_of_ne_zero (sub_ne_zero.mpr h₃)]
  nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₁), sq_pos_of_ne_zero (sub_ne_zero.mpr h₂),
    sq_pos_of_ne_zero (sub_ne_zero.mpr h₃)]
- `induction_divisibility_3div2tooddnp1`: [P] induction n with
| zero =>
  simp
| succ n ih =>
  simp_all [Nat.pow_succ, Nat.mul_succ]
  omega
- `induction_divisibility_3divnto3m2n`: [P] apply Nat.dvd_of_mod_eq_zero ⟶ [P] have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ [P] rcases this with (h | h | h) <;> simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod]
- `induction_divisibility_9div10tonm1`: [P] apply Nat.dvd_of_mod_eq_zero ⟶ [P] rw [← Nat.mod_add_div (10 ^ n) 9] ⟶ [P] simp [Nat.pow_mod, Nat.mod_eq_of_lt h₀, Nat.add_mod, Nat.mul_mod, Nat.mod_mod]
- `induction_ineq_nsqlefactn`: [P] induction' h₀ with n hn ⟶ [A] decide ⟶ [P] cases n with
| zero => contradiction
| succ n =>
  simp_all [Nat.factorial_succ, Nat.pow_succ]
  nlinarith
- `induction_seq_mul2pnp1`: [P] induction' n with n ih ⟶ [A] omega ⟶ [P] cases n with
| zero => simp_all
| succ n =>
  simp_all [Nat.pow_succ, Nat.mul_succ]
  ring_nf
  omega
- `induction_sum2kp1npqsqm1`: [P] induction n with
| zero =>
  simp
| succ n ih =>
  simp_all [Finset.sum_range_succ, Nat.succ_eq_add_one, Nat.add_assoc]
  ring_nf
  omega
- `induction_sum_1oktkp1`: [P] induction n with
| zero =>
  simp
| succ n hn =>
  simp_all [Finset.sum_range_succ, Nat.cast_succ, Nat.cast_zero]
  field_simp
  ring
- `mathd_algebra_11`: [P] have h₃ : a - 2 * b ≠ 0 := by
  intro h
  apply h₁
  linarith ⟶ [P] have h₄ : a - b ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] field_simp at h₂ ⊢ ⟶ [A] linarith
- `mathd_algebra_116`: [P] rw [h₀] at h₁ ⟶ [P] ring_nf at h₁ ⟶ [P] nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)]
- `mathd_algebra_13`: [P] have h₁ := h₀ 6 ⟶ [P] have h₂ := h₀ (-1) ⟶ [P] norm_num at h₁ h₂ ⟶ [P] exact ⟨by linarith, by linarith⟩
- `mathd_algebra_140`: [P] have h₂ := h₁ 0 ⟶ [P] have h₃ := h₁ 1 ⟶ [P] have h₄ := h₁ (-1) ⟶ [A] linarith
- `mathd_algebra_151`: [P] have h_main : ⌈Real.sqrt 27⌉ = ⌈Real.sqrt 27⌉ := rfl ⟶ [P] have h_root_bounds : Real.sqrt 26 ≤ Real.sqrt 27 := by
  apply Real.sqrt_le_sqrt
  norm_num ⟶ [P] have h_sqrt27_lt : Real.sqrt 27 < Real.sqrt 28 := by
  apply Real.sqrt_lt_sqrt
  <;> norm_num ⟶ [A] simp_all ⟶ [P] have h_sqrt26 : Real.sqrt 26 < 5.1 := by
  rw [Real.sqrt_lt] <;> norm_num ⟶ [P] have h_sqrt26' : Real.sqrt 26 < 5.1 := h_sqrt26 ⟶ [A] simp_all ⟶ [P] have h_sqrt27_le : Real.sqrt 27 ≥ 5 := by
  have h₁ : Real.sqrt 27 ≥ 5 := by
    apply Real.le_sqrt_of_sq_le
    norm_num
  exact h₁ ⟶ [P] norm_num at h_root_bounds h_sqrt27_lt h_sqrt26' h_sqrt27_le ⟶ [A] simp_all ⟶ [P] have h_sqrt27_lt_6 : Real.sqrt 27 < 6 := by
  rw [Real.sqrt_lt] <;> norm_num ⟶ [P] have h_floor_sqrt26 : ⌊Real.sqrt 26⌋ = 5 := by
  rw [Int.floor_eq_iff]
  constructor <;> norm_num <;>
  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ [A] simp_all ⟶ [A] ring_nf ⟶ [P] have h_ceil_sqrt27 : ⌈Real.sqrt 27⌉ = 6 := by
  rw [Int.ceil_eq_iff]
  constructor <;> norm_num <;>
  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show (0 : ℝ) ≤ 27 by norm_num)] ⟶ [A] omega
- `mathd_algebra_181`: [P] have h₂ : n - 3 ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] field_simp at h₁ ⟶ [A] linarith
- `mathd_algebra_192`: [A] simp_all ⟶ [P] norm_num [Complex.ext_iff, Complex.I_mul_I]
- `mathd_algebra_206`: [P] simp only [h₀] at h₂ h₃ ⟶ [P] apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ [A] nlinarith
- `mathd_algebra_22`: [P] rw [Real.logb] ⟶ [A] field_simp ⟶ [A] linarith
- `mathd_algebra_234`: [P] nlinarith [pow_two_nonneg (d - 3/5), h₀]
- `mathd_algebra_251`: [P] field_simp at h₁ ⟶ [A] linarith
- `mathd_algebra_267`: [P] have h₃ : x - 1 ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] have h₄ : x + 2 ≠ 0 := by
  intro h
  apply h₁
  linarith ⟶ [P] field_simp at h₂ ⟶ [A] linarith
- `mathd_algebra_28`: [P] obtain ⟨x, hx⟩ := h₁ ⟶ [A] simp_all ⟶ [P] nlinarith [sq_nonneg (x + 5 / 4)]
- `mathd_algebra_327`: [P] constructor <;>
  by_contra <;>
  (try constructor) <;>
  (try constructor) <;>
  (try norm_num at h₀) <;>
  (try
    {
      cases' le_total 0 (9 + 2 * a) with h h <;>
      simp_all only [abs_of_nonneg, abs_of_nonpos, Subtype.prop] <;>
      linarith
    })
<;>
  (try linarith)
- `mathd_algebra_410`: [A] simp_all ⟶ [P] nlinarith [sq_nonneg (x - 3)]
- `mathd_algebra_421`: [P] ring_nf at h₀ h₁ h₂ h₃ ⟶ [A] aesop ⟶ [P] ring_nf at h₁ h₂ ⟶ [P] nlinarith [sq_nonneg (a - c)]
- `mathd_algebra_433`: [A] simp_all ⟶ [A] ring_nf ⟶ [P] nlinarith [Real.sqrt_nonneg 9, sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num),
  Real.sqrt_nonneg 3, sq_sqrt (show (0 : ℝ) ≤ 3 by norm_num)]
- `mathd_algebra_437`: [P] norm_cast at h₀ h₁ ⟶ [A] simp_all ⟶ [P] norm_cast at * ⟶ [P] norm_num at h₀ h₁ ⟶ [P] rw [eq_comm] ⟶ [A] simp ⟶ [P] nlinarith [sq_nonneg (x - 3), sq_nonneg (y - 3), sq_nonneg (x + 3), sq_nonneg (y + 3),
  sq_nonneg (x - y), sq_nonneg (x + y)]
- `mathd_algebra_493`: [P] rw [h₀] ⟶ [P] have h₁ : f 4 = 4^2 - 4 * Real.sqrt 4 + 1 := by rw [h₀] ⟶ [P] rw [h₁] ⟶ [A] norm_num ⟶ [P] have h₂ : Real.sqrt 4 = 2 := by norm_num [Real.sqrt_eq_iff_sq_eq] ⟶ [P] rw [h₂] ⟶ [A] ring_nf ⟶ [P] have h₃ : Real.sqrt 9 = 3 := by
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ [A] linarith
- `mathd_algebra_510`: [P] rw [Real.sqrt_eq_iff_sq_eq] <;> nlinarith
- `mathd_algebra_536`: [A] field_simp ⟶ [A] ring_nf ⟶ [P] norm_num [Nat.factorial] ⟶ [P] norm_num [Real.sqrt_eq_iff_sq_eq, sq, mul_add, mul_comm, add_mul, mul_left_comm]
<;> ring_nf
<;> norm_num
<;> nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num)]
- `mathd_algebra_547`: [A] simp_all ⟶ [P] rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
- `mathd_algebra_59`: [P] norm_num at h₀ ⟶ [P] have h₁ : (4 : ℝ) ^ b = 4 := by linarith ⟶ [A] simp_all ⟶ [P] norm_num at h₀ ⟶ [A] simp_all ⟶ [P] apply_fun fun x => Real.logb 4 x at h₁ ⟶ [A] simp_all
- `mathd_algebra_73`: [P] apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ [P] linear_combination h₀
- `mathd_algebra_77`: [P] simp only [h₂] at h₃ h₄ ⟶ [A] constructor ⟶ [A] simp_all ⟶ [P] all_goals
  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)
  nlinarith
- `mathd_numbertheory_22`: [P] have h₂ : b ≤ 9 := by linarith ⟶ [P] interval_cases b <;> norm_num at h₁ ⊢
- `mathd_numbertheory_257`: [P] norm_num at h₁ ⟶ [A] omega
- `mathd_numbertheory_32`: [P] have h₁ : S = Finset.filter (λ n => n ∣ 36) (Finset.range 37) := by
  ext n
  simp [h₀]
  all_goals
    aesop ⟶ [A] aesop
- `mathd_numbertheory_326`: [P] ring_nf at h₀ ⟶ [A] ring_nf ⟶ [P] nlinarith [sq_nonneg (n - 10), sq_nonneg (n + 10)]
- `mathd_numbertheory_35`: [P] have h₁ := h₀ 0 ⟶ [P] norm_num at h₁
- `mathd_numbertheory_412`: [P] simp [h₀, h₁, pow_succ, Int.mul_emod, Int.add_emod]
- `mathd_numbertheory_629`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro t ht
  rcases ht with ⟨ht1, ht2⟩
  by_contra h
  push_neg at h
  interval_cases t <;> norm_num at ht1 ht2 <;>
  simp_all [Nat.lcm, Nat.pow_succ]
  <;>
  norm_num at *
  <;>
  omega
- `mathd_numbertheory_64`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro x hx
  simp [Nat.ModEq] at hx
  omega
- `mathd_numbertheory_690`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro a h
  rcases h with ⟨ha₀, ha₁, ha₂, ha₃, ha₄⟩
  by_contra h
  push_neg at h
  interval_cases a <;> simp_all (config := {decide := true})
- `mathd_numbertheory_780`: [A] aesop ⟶ [P] interval_cases m <;> omega
- `mathd_numbertheory_84`: [P] norm_num [Int.floor_eq_iff]
- `numbertheory_2dvd4expn`: [P] induction n with
| zero =>
  simp_all
| succ n ih =>
  simp_all [Nat.pow_succ, Nat.mul_succ]
  omega
- `numbertheory_nckeqnm1ckpnm1ckm1`: [P] cases n <;> cases k <;> simp_all [choose, Nat.succ_mul, Nat.mul_succ]
<;> linarith
- `numbertheory_sqmod3in01d`: [P] have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ [P] rcases this with (h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]
- `numbertheory_sqmod4in01d`: [P] have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ [P] rcases this with (h | h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]

## Lost against row 0

none
