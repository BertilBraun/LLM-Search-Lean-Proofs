# phase2_sft_v1_search vs phase0_automation_baseline

**Solved 148/244 (60.7%) vs 79/244 (32.4%) for row 0**: 69 newly solved, 0 lost. Proofs using at least one policy step: 82. Row 0 ran 256 expansions and 300 s per theorem with 32 processes; see each run's config for its budget.

## By category

| category | problems | row 0 | this run | newly solved | lost |
|---|---|---|---|---|---|
| mathd_algebra | 70 | 28 | 53 | 25 | 0 |
| mathd_numbertheory | 60 | 38 | 49 | 11 | 0 |
| amc12 | 45 | 8 | 17 | 9 | 0 |
| aime | 15 | 0 | 2 | 2 | 0 |
| imo | 20 | 0 | 1 | 1 | 0 |
| algebra | 18 | 5 | 16 | 11 | 0 |
| numbertheory | 8 | 0 | 4 | 4 | 0 |
| induction | 8 | 0 | 6 | 6 | 0 |

## Anytime curves (solved theorems at budget)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| row 0 | 59 | 72 | 77 | 79 | 79 | 79 | 79 |
| this run | 84 | 104 | 123 | 129 | 140 | 145 | 148 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 607.027 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| row 0 | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| this run | 40 | 57 | 85 | 108 | 119 | 125 | 133 | 143 | 144 | 145 | 148 | 148 |

## Cost per theorem

| quantity | value |
|---|---|
| mean / median generated tokens | 12611 / 1416 |
| total generated tokens | 3,077,055 |
| generated tokens per solved theorem | 20,791 |
| mean prompt tokens (computed once per request) | 5924 |
| mean / median wall seconds | 176.5 / 25.0 |
| mean Lean seconds | 132.5 |
| mean expansions | 24.0 |

## Throughput in the search

| quantity | value |
|---|---|
| run wall minutes | 24.0 |
| policy requests / samples | 5,758 / 92,128 |
| samples/s over the policy window | 65.2 |
| generated tokens/s | 2200 |
| mean request latency s | 1.81 |
| summed request s / summed Lean s | 10,404 / 32,323 |
| distinct candidates per request | 9.6 |
| duplicate / failed sample fraction | 37.2% / 3.0% |
| prompt cache hit rate | 88.6% |
| requests without candidates (unattributed tokens) | 0 (0) |
| prompts too long | 0 |

## Newly solved (P = policy step, A = automation)

- `aime_1984_p15`: [P] field_simp at h₀ h₁ h₂ h₃ ⟶ [A] linarith
- `aime_1991_p1`: [A] aesop ⟶ [P] ring_nf at h₁ h₂ ⊢ ⟶ [P] have h₃ := h₁ ⟶ [P] have h₄ := h₂ ⟶ [A] simp_all ⟶ [P] have h₅ : x ≤ 71 := by
  nlinarith ⟶ [P] have h₆ : y ≤ 71 := by
  nlinarith ⟶ [P] have h₇ : x * y ≤ 71 * 71 := by nlinarith ⟶ [A] simp_all ⟶ [P] interval_cases x <;> try {
  omega
} <;> try {
  interval_cases y <;> omega
}
- `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`: [P] have h₂ : x + e = 7 := h₀ ⟶ [P] have h₃ := h₁ ⟶ [A] simp_all ⟶ [P] ring_nf at h₂ h₃ ⟶ [A] constructor ⟶ [P] all_goals
  apply eq_of_sub_eq_zero
  rw [← sub_eq_zero] at *
  simp_all [Complex.ext_iff]
  constructor <;> linarith
- `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`: [P] intro x hx ⟶ [A] field_simp ⟶ [P] rw [div_le_iff (by positivity)] ⟶ [P] nlinarith [Real.mul_self_sqrt (by norm_num : (0 : ℝ) ≤ 2), sq_nonneg (x - 1), sq_nonneg (x + 1), sq_nonneg (x - Real.sqrt 2 / 2), sq_nonneg (x + Real.sqrt 2 / 2)]
- `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`: [A] aesop ⟶ [P] nlinarith [sq_sqrt (mul_nonneg left.le right.le), sq_nonneg (x - y), sq_nonneg (x + y),
  sq_nonneg (x - y + 2 * Real.sqrt (x * y)), sq_nonneg (x - y - 2 * Real.sqrt (x * y))]
- `algebra_amgm_sumasqdivbsqgeqsumbdiva`: [P] have h₁ : 0 < a * b := by
  exact mul_pos h₀.1 h₀.2.1 ⟶ [P] have h₂ : 0 < b * c := by
  exact mul_pos h₀.2.1 h₀.2.2 ⟶ [P] have h₃ : 0 < c * a := by
  exact mul_pos h₀.2.2 h₀.1 ⟶ [P] have h₄ : 0 < a^2 := by nlinarith ⟶ [P] have h₅ : 0 < b^2 := by nlinarith ⟶ [P] have h₆ : 0 < c^2 := by nlinarith ⟶ [P] have h₇ : 0 < a * b * c := by
  exact mul_pos (mul_pos h₀.1 h₀.2.1) h₀.2.2 ⟶ [P] field_simp [h₀.1.ne', h₀.2.1.ne', h₀.2.2.ne'] ⟶ [P] rw [div_le_div_iff (by positivity) (by positivity)] ⟶ [P] nlinarith [sq_nonneg (a^2 * c - b^2 * a), sq_nonneg (b^2 * a - c^2 * b), sq_nonneg (c^2 * b - a^2 * c)]
- `algebra_apb4leq8ta4pb4`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), sq_nonneg (a ^ 2 - b ^ 2), sq_nonneg (a ^ 2 + b ^ 2),
  sq_nonneg (a ^ 2 - 2 * a * b + b ^ 2), sq_nonneg (a ^ 2 + 2 * a * b + b ^ 2)]
- `algebra_binomnegdiscrineq_10alt28asqp1`: [P] nlinarith [sq_nonneg (a - 1/5)]
- `algebra_manipexpr_apbeq2cceqiacpbceqm2`: [P] rw [h₁] at h₀ ⟶ [P] rw [h₁] at * ⟶ [A] simp_all ⟶ [P] rw [← sub_eq_zero] at h₀ ⊢ ⟶ [A] simp ⟶ [P] rw [← sub_eq_zero] at h₀ ⊢ ⟶ [A] simp ⟶ [P] rw [← sub_eq_zero] at h₀ <;> simp_all [Complex.ext_iff, pow_two, Complex.I_mul_I]
<;> ring
<;> norm_num
<;> linarith
- `algebra_sqineq_2at2pclta2c2p41pc`: [P] nlinarith [sq_nonneg (a - 2 - c), sq_nonneg (a - 2 + c), sq_nonneg (a + c - 2)]
- `algebra_sqineq_2unitcircatblt1`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]
- `algebra_sqineq_36azm9asqle36zsq`: [P] nlinarith [sq_nonneg (a - 2 * z)]
- `algebra_sqineq_4bap1lt4bsqpap1sq`: [P] nlinarith [sq_nonneg (2 * b - (a + 1))]
- `amc12_2000_p11`: [P] have h₂ : a ≠ 0 := h₀.1 ⟶ [P] have h₃ : b ≠ 0 := h₀.2 ⟶ [A] field_simp ⟶ [A] ring_nf ⟶ [A] simp_all ⟶ [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]
- `amc12_2000_p5`: [P] cases' le_total 0 (x - 2) with h h <;>
  simp_all only [abs_of_nonneg, abs_of_nonpos, sub_eq_add_neg, neg_add_rev] <;>
  linarith
- `amc12a_2008_p8`: [P] ring_nf at h₂ ⟶ [A] ring_nf ⟶ [A] aesop ⟶ [P] have h₃ : x^2 = 2 * y^2 := by
  nlinarith ⟶ [A] simp_all ⟶ [P] have h₄ : x^3 = x * x^2 := by ring ⟶ [P] rw [h₄, h₃] ⟶ [A] ring_nf ⟶ [A] simp ⟶ [P] have h₅ : y^3 = 1 := h₁ ⟶ [A] simp_all ⟶ [P] have h₆ : y = 1 := by
  nlinarith ⟶ [P] have h₇ : x^2 = 2 := by
  rw [h₆] at h₃
  nlinarith ⟶ [P] have h₈ : x = Real.sqrt 2 := by
  nlinarith [Real.sqrt_nonneg 2, Real.sq_sqrt (show 0 ≤ 2 by norm_num)] ⟶ [A] simp_all
- `amc12a_2009_p5`: [P] ring_nf at h₀ ⟶ [A] simp_all ⟶ [A] norm_num
- `amc12a_2009_p9`: [P] have h₂ := h₀ 0 ⟶ [P] have h₃ := h₁ 0 ⟶ [P] simp at h₂ h₃ ⟶ [P] have h₄ := h₁ 3 ⟶ [P] have h₅ := h₀ 0 ⟶ [P] simp at h₅ ⟶ [P] have h₆ := h₀ 0 ⟶ [P] have h₇ := h₀ 1 ⟶ [P] have h₈ := h₀ 2 ⟶ [P] have h₉ := h₀ (-1) ⟶ [P] have h₁₀ := h₀ (-2) ⟶ [P] norm_num at h₆ h₇ h₈ h₉ h₁₀ ⟶ [A] simp_all
- `amc12a_2011_p18`: [P] cases' le_total 0 (x + y) with h₁ h₁ <;>
cases' le_total 0 (x - y) with h₂ h₂ <;>
simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;>
nlinarith
- `amc12a_2013_p8`: [P] field_simp at h₃ ⟶ [P] ring_nf at h₃ ⟶ [A] simp_all ⟶ [P] apply mul_left_cancel₀ (sub_ne_zero.mpr h₂) ⟶ [A] linarith
- `amc12b_2002_p6`: [P] have h₂ := h₁ 0 ⟶ [P] have h₃ := h₁ 1 ⟶ [P] have h₄ := h₁ (-1) ⟶ [P] have h₅ := h₁ 2 ⟶ [A] constructor ⟶ [P] all_goals
  ring_nf at h₂ h₃ h₄ h₅
  nlinarith [sq_pos_of_ne_zero (show a ≠ 0 by intro h; apply h₀.1 <;> linarith), sq_pos_of_ne_zero (show b ≠ 0 by intro h; apply h₀.2 <;> linarith)]
- `amc12b_2020_p5`: [P] field_simp at h₀ h₁ ⟶ [P] ring_nf at h₀ h₁ ⟶ [P] norm_cast at h₀ h₁ ⟶ [A] omega
- `imo_1984_p2`: [P] by_contra h₅ ⟶ [P] push_neg at h₅ ⟶ [P] have h₆ : a + b ≤ 18 := by linarith ⟶ [P] have h₇ : a ≤ 18 := by omega ⟶ [P] have h₈ : b ≤ 18 := by linarith ⟶ [P] have h₉ : a ≤ 18 := by linarith ⟶ [P] have h₁₀ : b ≤ 18 := by linarith ⟶ [A] simp_all ⟶ [P] have h₇ : a ≤ 18 := by linarith ⟶ [P] have h_b : b ≤ 18 := by linarith ⟶ [A] simp_all ⟶ [P] have h_a : a ≤ 18 := by linarith ⟶ [P] have h₈ : a ≤ 18 := by linarith ⟶ [P] have h₉ : b ≥ 1 := by omega ⟶ [P] have h₁₀ : a ≥ 1 := by linarith ⟶ [P] interval_cases a <;> interval_cases b <;> omega
- `induction_divisibility_3div2tooddnp1`: [P] induction n with
| zero =>
  norm_num
| succ n ih =>
  simp only [Nat.mul_succ, Nat.add_succ, pow_succ] at *
  omega
- `induction_divisibility_3divnto3m2n`: [P] apply Nat.dvd_of_mod_eq_zero ⟶ [P] have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ [P] rcases this with (h | h | h) <;> simp [h, Nat.pow_succ, Nat.mul_mod, Nat.add_mod]
- `induction_divisibility_9div10tonm1`: [P] apply Nat.dvd_of_mod_eq_zero ⟶ [P] rw [← Nat.mod_add_div (10^n) 9] ⟶ [P] simp [pow_mod, h₀]
- `induction_ineq_nsqlefactn`: [P] induction' h₀ with n h₁
<;> simp_all [Nat.factorial_succ, Nat.mul_succ]
<;> nlinarith
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
  simp_all [Finset.sum_range_succ, mul_add, mul_comm, mul_left_comm, mul_assoc]
  field_simp
  ring
- `mathd_algebra_11`: [P] have h₃ : a - 2 * b ≠ 0 := by
  intro h
  apply h₁
  linarith ⟶ [P] have h₄ : a - b ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] field_simp [h₃, h₄] at h₂ ⊢ ⟶ [A] linarith
- `mathd_algebra_116`: [P] rw [h₀] at h₁ ⟶ [P] nlinarith [Real.sqrt_pos.mpr (show (0 : ℝ) < (131 : ℝ) by norm_num), Real.sq_sqrt (show (0 : ℝ) ≤ (131 : ℝ) by norm_num)]
- `mathd_algebra_13`: [P] have h₁ := h₀ 6 ⟶ [P] have h₂ := h₀ 0 ⟶ [P] have h₃ := h₀ 1 ⟶ [P] have h₄ := h₀ 2 ⟶ [P] have h₅ := h₀ 3 ⟶ [P] have h₆ := h₀ 4 ⟶ [P] have h₇ := h₀ 5 ⟶ [P] have h₈ := h₀ 6 ⟶ [P] have h₉ := h₀ 7 ⟶ [P] have h₁₀ := h₀ 8 ⟶ [P] have h₁₁ := h₀ 9 ⟶ [P] have h₁₂ := h₀ 10 ⟶ [P] norm_num at h₁ h₂ h₃ h₄ h₅ h₆ h₇ h₈ h₉ h₁₀ h₁₁ h₁₂ ⟶ [A] constructor ⟶ [P] all_goals
  nlinarith
- `mathd_algebra_140`: [P] have h₂ := h₁ 0 ⟶ [P] have h₃ := h₁ 1 ⟶ [P] have h₄ := h₁ (-1) ⟶ [A] linarith
- `mathd_algebra_151`: [P] have h1 : (Real.sqrt 27 : ℝ) > 4 := by
  have h₁ : (4 : ℝ) < Real.sqrt 27 := by
    apply Real.lt_sqrt_of_sq_lt
    norm_num
  linarith ⟶ [A] simp_all ⟶ [P] have h2 : 4 < Real.sqrt 27 := h1 ⟶ [P] have h3 : √26 < √27 := by
  apply Real.sqrt_lt_sqrt
  <;> norm_num
  <;> linarith ⟶ [P] have h4 : Real.sqrt 26 < Real.sqrt 27 := h3 ⟶ [A] simp_all ⟶ [P] have h5 : ⌊Real.sqrt 26⌋ = 5 := by
  rw [Int.floor_eq_iff]
  constructor <;> norm_num <;> nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ [A] simp_all ⟶ [P] have h6 : ⌈√27⌉ = 6 := by
  rw [Int.ceil_eq_iff]
  constructor <;> norm_num <;>
    nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 by norm_num)] ⟶ [A] omega
- `mathd_algebra_181`: [P] have h₂ : n - 3 ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] field_simp at h₁ ⟶ [A] linarith
- `mathd_algebra_192`: [A] simp_all ⟶ [P] norm_num [ Complex.ext_iff, Complex.I_mul_I ]
<;> ring
<;> norm_num
<;> ring
- `mathd_algebra_206`: [P] simp only [h₀] at h₂ h₃ ⟶ [P] have h₄ : b * (b + a + 1) = 0 := by linarith ⟶ [A] aesop ⟶ [P] all_goals
  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)
  nlinarith
- `mathd_algebra_22`: [P] simp [Real.logb]
<;> norm_num
<;> field_simp
<;> ring
<;> norm_num
- `mathd_algebra_234`: [P] field_simp at h₀ ⊢ ⟶ [P] nlinarith [sq_nonneg (d - 5 / 3), sq_nonneg (d + 5 / 3)]
- `mathd_algebra_251`: [P] field_simp at h₁ ⟶ [A] linarith
- `mathd_algebra_267`: [P] have h₃ : x - 1 ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] have h₄ : x + 2 ≠ 0 := by
  intro h
  apply h₁
  linarith ⟶ [P] field_simp [h₃, h₄] at h₂ ⟶ [A] linarith
- `mathd_algebra_28`: [P] rcases h₁ with ⟨x, hx⟩ ⟶ [P] have h₁ := h₀ x ⟶ [P] nlinarith [sq_nonneg (x + 5 / 4)]
- `mathd_algebra_327`: [P] constructor <;>
cases' le_total 0 (9 + 2*a) with h h <;>
simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;>
linarith
- `mathd_algebra_410`: [A] simp_all ⟶ [P] nlinarith [sq_nonneg (x - 3)]
- `mathd_algebra_421`: [P] nlinarith [sq_nonneg (a - c), sq_nonneg (a + c + 2)]
- `mathd_algebra_433`: [P] have h₁ := h₀ 8 ⟶ [P] have h₂ : 2 * 8 - 7 = 9 := by norm_num ⟶ [P] have h₃ : Real.sqrt 9 = 3 := by
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ [A] simp_all ⟶ [P] ring_nf
<;> norm_num
<;> linarith
- `mathd_algebra_437`: [P] have h₄ : (x : ℝ) < (n : ℝ) := by exact_mod_cast h₂ ⟶ [P] have h₅ : (n : ℝ) < y := h₃ ⟶ [P] have h₆ := h₀ ⟶ [P] have h₇ : y^3 = -101 := h₁ ⟶ [P] have h₈ : x < (n : ℝ) := by exact_mod_cast h₄ ⟶ [P] have h₉ : (n : ℝ) < y := h₅ ⟶ [P] have h₁₀ := h₆ ⟶ [P] have h₁₁ := h₇ ⟶ [P] have h₁₂ : x < (n : ℝ) := by exact_mod_cast h₈ ⟶ [P] have h₁₃ := h₉ ⟶ [P] have h₁₄ := h₆ ⟶ [P] have h₁₅ := h₁₁ ⟶ [P] nlinarith [sq_nonneg (x + y), sq_nonneg (x - y), sq_nonneg (x - 1), sq_nonneg (y - 1)]
- `mathd_algebra_451`: [A] simp_all ⟶ [P] rw [h₃] at * ⟶ [A] simp_all ⟶ [P] rw [← h₂] ⟶ [A] simp ⟶ [P] have h₃ := h₂.symm ⟶ [P] have h₄ := h₀ ⟶ [P] simp_all only [Equiv.symm_apply_eq, h₁, h₂, h₃, h₄]
- `mathd_algebra_493`: [A] simp_all ⟶ [A] norm_num ⟶ [P] have h1 : Real.sqrt 4 = 2 := by
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ [A] ring_nf ⟶ [P] norm_num [h1] ⟶ [A] ring_nf ⟶ [P] have h2 : Real.sqrt 9 = 3 := by
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ [A] linarith
- `mathd_algebra_510`: [P] have h₂ : x ^ 2 + y ^ 2 = (x + y) ^ 2 - 2 * (x * y) := by ring ⟶ [P] rw [h₂, h₀, h₁] ⟶ [A] norm_num ⟶ [P] rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num
- `mathd_algebra_536`: [A] field_simp ⟶ [A] ring_nf ⟶ [P] norm_num [Nat.factorial] ⟶ [P] nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show 0 ≤ 9 by norm_num)]
- `mathd_algebra_547`: [A] simp_all ⟶ [P] norm_num [Real.sqrt_eq_iff_mul_self_eq, pow_succ, mul_assoc]
- `mathd_algebra_73`: [P] apply mul_left_cancel₀ (sub_ne_zero.mpr h₁) ⟶ [P] linear_combination h₀ - (r - p) * (r - q)
- `mathd_algebra_77`: [A] simp_all ⟶ [A] constructor ⟶ [P] all_goals
  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)
  nlinarith
- `mathd_numbertheory_22`: [P] have h₂ : 0 ≤ 10 * b + 6 := by linarith ⟶ [P] have h₃ := h₁ ⟶ [A] simp_all ⟶ [P] interval_cases h₁ : b <;> norm_num [h₃] at h₃ <;> omega
- `mathd_numbertheory_257`: [P] norm_num at h₁ ⟶ [A] omega
- `mathd_numbertheory_32`: [P] have h1 : S = Finset.filter (fun n => n ∣ 36) (Finset.range 37) := by
  ext n
  simp [h₀]
  all_goals norm_num ⟶ [A] aesop
- `mathd_numbertheory_326`: [P] ring_nf at h₀ ⟶ [P] have h₁ : -n + n^3 = 720 := h₀ ⟶ [A] simp_all ⟶ [P] apply Eq.symm ⟶ [P] nlinarith [sq_nonneg (n - 9), sq_nonneg (n + 9), sq_nonneg (n - 2), sq_nonneg (n + 2),
  sq_nonneg (n - 18), sq_nonneg (n + 18), sq_nonneg (n - 4), sq_nonneg (n + 4),
  sq_nonneg (n - 27), sq_nonneg (n + 27), sq_nonneg (n - 36), sq_nonneg (n + 36)]
- `mathd_numbertheory_35`: [P] have h₁ := h₀ 1 ⟶ [P] have h₂ := h₀ 2 ⟶ [P] have h₃ := h₀ 3 ⟶ [P] norm_num [Finset.sum_range_succ] at h₁ h₂ h₃ ⊢
- `mathd_numbertheory_412`: [P] simp [h₀, h₁, pow_two, pow_three, Int.mul_emod, Int.add_emod]
- `mathd_numbertheory_629`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro t ht
  rcases ht with ⟨ht0, ht1⟩
  by_contra h
  push_neg at h
  interval_cases t <;> norm_num [Nat.lcm] at ht1 <;> omega
- `mathd_numbertheory_64`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro x
  intro h
  simp [Nat.ModEq] at h
  omega
- `mathd_numbertheory_690`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro a
  rintro ⟨ha, h1, h2, h3, h4⟩
  norm_num [Nat.ModEq] at *
  omega
- `mathd_numbertheory_780`: [A] aesop ⟶ [P] interval_cases m <;> omega
- `mathd_numbertheory_84`: [P] norm_num [Int.floor_eq_iff]
- `numbertheory_2dvd4expn`: [P] induction n with
| zero =>
  simp_all
| succ n ih =>
  simp_all [Nat.pow_succ, Nat.mul_succ]
  all_goals omega
- `numbertheory_nckeqnm1ckpnm1ckm1`: [P] cases n with
| zero =>
  simp_all [Nat.choose_zero_right, Nat.choose_one_right]
| succ n =>
  cases k with
  | zero =>
    simp_all [Nat.choose_zero_right, Nat.choose_one_right]
  | succ k =>
    simp_all [Nat.choose_succ_succ, Nat.choose_succ_right_eq]
    <;> omega
- `numbertheory_sqmod3in01d`: [P] have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ [P] rcases this with (h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]
- `numbertheory_sqmod4in01d`: [P] have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ [P] rcases this with (h | h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]

## Lost against row 0

none
