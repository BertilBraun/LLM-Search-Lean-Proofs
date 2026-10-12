# phase3_astar_v0_sft_v2 vs phase0_automation_baseline

**Solved 157/244 (64.3%) vs 79/244 (32.4%) for row 0**: 78 newly solved, 0 lost. Proofs using at least one policy step: 94. Row 0 ran 256 expansions and 300 s per theorem with 32 processes; see each run's config for its budget.

## By category

| category | problems | row 0 | this run | newly solved | lost |
|---|---|---|---|---|---|
| mathd_algebra | 70 | 28 | 55 | 27 | 0 |
| mathd_numbertheory | 60 | 38 | 49 | 11 | 0 |
| amc12 | 45 | 8 | 20 | 12 | 0 |
| aime | 15 | 0 | 2 | 2 | 0 |
| imo | 20 | 0 | 4 | 4 | 0 |
| algebra | 18 | 5 | 16 | 11 | 0 |
| numbertheory | 8 | 0 | 4 | 4 | 0 |
| induction | 8 | 0 | 7 | 7 | 0 |

## Anytime curves (solved theorems at budget)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| row 0 | 59 | 72 | 77 | 79 | 79 | 79 | 79 |
| this run | 89 | 123 | 133 | 138 | 144 | 153 | 157 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 609.928 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| row 0 | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| this run | 34 | 52 | 79 | 106 | 124 | 126 | 137 | 145 | 148 | 153 | 157 | 157 |

## Cost per theorem

| quantity | value |
|---|---|
| mean / median generated tokens | 8338 / 1004 |
| total generated tokens | 2,034,356 |
| generated tokens per solved theorem | 12,958 |
| mean prompt tokens (computed once per request) | 4189 |
| mean / median wall seconds | 175.3 / 18.5 |
| mean Lean seconds | 123.5 |
| mean expansions | 21.6 |

## Throughput in the search

| quantity | value |
|---|---|
| run wall minutes | 24.3 |
| policy requests / samples | 5,159 / 82,544 |
| samples/s over the policy window | 58.2 |
| generated tokens/s | 1434 |
| mean request latency s | 2.12 |
| summed request s / summed Lean s | 10,932 / 30,130 |
| distinct candidates per request | 10.6 |
| duplicate / failed sample fraction | 32.5% / 1.4% |
| prompt cache hit rate | 86.5% |
| requests without candidates (unattributed tokens) | 0 (0) |
| prompts too long | 0 |

## Newly solved (P = policy step, A = automation)

- `aime_1983_p9`: [P] have h₁ : 0 < Real.sin x := Real.sin_pos_of_mem_Ioo ⟨by linarith [h₀.1], h₀.2⟩ ⟶ [P] rw [le_div_iff (by nlinarith [Real.sin_sq_add_cos_sq x, h₀.1, h₀.2])] ⟶ [P] have h₂ : 0 < Real.sin x ^ 2 := sq_pos_of_pos h₁ ⟶ [P] nlinarith [sq_nonneg (x * Real.sin x - 2 / 3),
  Real.sin_sq_add_cos_sq x,
  sq_nonneg (Real.sin x + 2 / 3),
  sq_nonneg (Real.sin x - 2 / 3)]
- `aime_1984_p15`: [P] field_simp at h₀ h₁ h₂ h₃ ⟶ [A] linarith
- `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`: [P] refine ⟨?_,?_⟩ ⟶ [P] rw [← sub_eq_zero] at h₀ h₁ ⟶ [P] apply Eq.symm ⟶ [P] all_goals simp_all [Complex.ext_iff, add_comm] ⟶ [P] all_goals
  norm_num
  constructor
  nlinarith
  nlinarith
- `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`: [A] aesop ⟶ [A] field_simp ⟶ [P] rw [le_div_iff (by positivity)] ⟶ [P] nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - 1), sq_nonneg (x - Real.sqrt 2 / 2)]
<;> norm_num
- `algebra_amgm_sqrtxymulxmyeqxpy_xpygeq4`: [P] nlinarith [sq_nonneg (x - y), sq_sqrt (mul_nonneg h₀.1.le h₀.2.le),
  mul_self_nonneg (x - y - 2 * Real.sqrt (x * y))]
- `algebra_apb4leq8ta4pb4`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), sq_nonneg (a + b - 2 * a), sq_nonneg (a + b - 2 * b)]
- `algebra_binomnegdiscrineq_10alt28asqp1`: [P] nlinarith [sq_nonneg (a - 1 / 5)]
- `algebra_manipexpr_apbeq2cceqiacpbceqm2`: [P] simp_all only [Complex.ext_iff, Complex.I_mul_I, mul_pow, mul_one, mul_neg, mul_comm,
  mul_left_comm, mul_assoc, Complex.ext_iff, Complex.I_mul_I, mul_pow, mul_one,
  mul_neg, mul_comm, mul_left_comm, mul_assoc, Complex.ext_iff, Complex.I_mul_I, mul_pow,
  mul_one, mul_neg, mul_comm, mul_left_comm, mul_assoc, Complex.ext_iff, Complex.I_mul_I,
  mul_pow, mul_one, mul_neg, mul_comm, mul_left_comm, mul_assoc] ⟶ [P] simp_all [Complex.ext_iff, Complex.I_mul_I, pow_two, pow_three]
<;> ring
<;> norm_num
<;> linarith
<;> ring
<;> norm_num
<;> linarith
- `algebra_sqineq_2at2pclta2c2p41pc`: [P] nlinarith [sq_nonneg (a - (c + 2))]
- `algebra_sqineq_2unitcircatblt1`: [P] nlinarith [sq_nonneg (a - b)]
- `algebra_sqineq_36azm9asqle36zsq`: [P] nlinarith [sq_nonneg (a - 2 * z)]
- `algebra_sqineq_4bap1lt4bsqpap1sq`: [P] nlinarith [sq_nonneg (a + 1 - 2 * b)]
- `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`: [P] rw [add_comm] ⟶ [P] use x^2 + y^2 + z^2 - x * y - y * z - z * x ⟶ [A] linarith
- `amc12_2000_p11`: [P] field_simp [h₀.1, h₀.2, mul_comm] ⟶ [P] nlinarith [sq_nonneg (a - b), h₁]
- `amc12_2000_p5`: [P] cases' abs_cases (x - 2) with h₂ h₂ <;> linarith
- `amc12_2001_p9`: [P] have h₂ := h₀ 600 (by norm_num) 500 (by norm_num) ⟶ [P] simp only [h₁, mul_comm] at h₂ ⟶ [A] simp_all ⟶ [A] linarith
- `amc12a_2008_p8`: [P] have h₃ : y = 1 := by
  nlinarith [h₁] ⟶ [P] have h₄ : x = Real.sqrt 2 := by
  rw [h₃] at h₂
  nlinarith [Real.sq_sqrt (show 0 ≤ 2 by norm_num), Real.sqrt_nonneg 2] ⟶ [A] nlinarith
- `amc12a_2009_p5`: [P] nlinarith [sq_nonneg (x - 3), sq_nonneg (x + 1), sq_nonneg (x - 2)]
- `amc12a_2009_p9`: [A] simp_all ⟶ [P] have h₂ := h₀ (-3) ⟶ [A] simp_all ⟶ [P] linarith [h₀ 0, h₀ 1, h₀ 2]
- `amc12a_2011_p18`: [P] cases' le_total 0 (x + y) with h₁ h₁ <;> cases' le_total 0 (x - y) with h₂ h₂ <;>
  simp_all only [abs_of_nonneg, abs_of_nonpos, add_nonneg, add_nonpos, sub_nonneg, sub_nonpos] <;>
  nlinarith
- `amc12a_2013_p8`: [P] have h₄ : x * y = 2 := by
  have h₅ : x ≠ 0 := h₀
  have h₆ : y ≠ 0 := h₁
  have h₇ : x + 2 / x = y + 2 / y := h₃
  field_simp at h₇
  ring_nf at h₇ ⊢
  apply mul_left_cancel₀ (sub_ne_zero.mpr h₂)
  nlinarith ⟶ [A] linarith
- `amc12a_2015_p10`: [P] have h₃ := h₁ ⟶ [P] have h₄ : 0 < x := by linarith ⟶ [P] have h₅ : y < 26 := by
  nlinarith ⟶ [P] interval_cases y <;> omega
- `amc12b_2002_p6`: [A] constructor ⟶ [P] all_goals
  have h₂ := h₁ 0
  have h₃ := h₁ 1
  have h₄ := h₁ (-1)
  ring_nf at *
  nlinarith [sq_pos_of_ne_zero h₀.1, sq_pos_of_ne_zero h₀.2, sq_pos_of_ne_zero (show (2 : ℝ) ≠ 0 by norm_num)]
- `amc12b_2003_p17`: [P] have : 0 < x * y := mul_pos h₀.1 h₀.2 ⟶ [P] have h₃ : 0 < x * y * (x * y) := by nlinarith ⟶ [P] have h₄ : Real.log (x * y) = 3 / 5 := by
  field_simp [Real.log_mul, h₀.1.ne', h₀.2.ne'] at *
  norm_num [Real.log_mul, Real.log_rpow, Real.log_div, h₁, h₂]
  all_goals nlinarith ⟶ [A] linarith
- `amc12b_2020_p5`: [P] field_simp at h₀ h₁ ⟶ [P] ring_nf at h₀ h₁ ⟶ [P] norm_cast at h₀ h₁ ⟶ [A] omega
- `imo_1961_p1`: [P] have h₇ : a > 0 := by linarith ⟶ [A] ring_nf ⟶ [P] refine' ⟨h₇, ⟨_, _⟩⟩ <;> nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁),
  sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₃)]
- `imo_1964_p1_2`: [P] have h : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by
  have h1 : 2 ^ n % 7 = 1 ∨ 2 ^ n % 7 = 2 ∨ 2 ^ n % 7 = 4 := by
    induction n with
    | zero =>
      norm_num
    | succ n ih =>
      rcases ih with (ih | ih | ih) <;> simp [pow_succ, Nat.mul_mod, ih] at *
      <;> omega
  exact h1 ⟶ [A] omega
- `imo_1974_p5`: [A] aesop ⟶ [P] . apply lt_of_sub_pos
  field_simp
  ring_nf
  nlinarith [mul_pos left left_1, mul_pos left left_2, mul_pos left right, mul_pos left_1 right, mul_pos left_2 right] ⟶ [P] case right =>
  apply lt_of_sub_pos
  field_simp
  ring_nf
  nlinarith [mul_pos left left_1, mul_pos left_1 left_2, mul_pos left_2 right, mul_pos right left, mul_pos left_1 right, mul_pos right left_2]
- `imo_1984_p2`: [P] have h₅ : 0 ≤ a := by
  exact_mod_cast (le_of_lt h₀.1) ⟶ [P] have h₆ : 0 ≤ b := by linarith ⟶ [A] simp_all ⟶ [P] have h₇ : 0 ≤ (a + b) ^ 2 := by positivity ⟶ [P] have h₈ : 19 ≤ a + b := by
  by_contra h
  push_neg at h
  have h₈₁ : a + b ≤ 18 := by
    omega
  have h₈₂ : a ≤ 18 := by
    omega
  have h₈₃ : b ≤ 18 := by
    omega
  interval_cases a <;> interval_cases b <;> norm_num [Int.dvd_iff_emod_eq_zero] at h₄ h₁ h₂ h₃ h₈₁ h₈₂ h₈₃ ⊢
  <;> omega ⟶ [A] omega
- `induction_divisibility_3div2tooddnp1`: [P] induction n with
| zero =>
  simp
| succ n ih =>
  simp_all [Nat.pow_succ, Nat.mul_succ]
  omega
- `induction_divisibility_3divnto3m2n`: [P] have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ [P] rcases this with (h | h | h) <;>
simp [h, Nat.dvd_iff_mod_eq_zero, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_mod]
<;>
omega
- `induction_divisibility_9div10tonm1`: [P] induction' h₀ with n hn
<;> simp_all [Nat.pow_succ, Nat.mul_mod, Nat.add_mod]
<;> omega
- `induction_ineq_nsqlefactn`: [P] induction' h₀ with n h₀
<;> simp_all [Nat.factorial]
<;> nlinarith
- `induction_seq_mul2pnp1`: [P] induction' n with n ih ⟶ [A] omega ⟶ [P] simp [ih, h₁, Nat.add_comm, Nat.add_left_comm, Nat.add_assoc] ⟶ [P] cases n with
| zero =>
  simp
| succ n =>
  simp_all [Nat.pow_succ, Nat.mul_add, Nat.add_mul, Nat.mul_one, Nat.add_zero]
  ring
  <;> omega
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
- `mathd_algebra_11`: [P] field_simp [h₀, h₁, sub_ne_zero, sub_ne_zero, sub_ne_zero, sub_ne_zero, sub_ne_zero,
  sub_ne_zero, sub_ne_zero, sub_ne_zero, sub_ne_zero] at h₂ ⊢ ⟶ [A] linarith
- `mathd_algebra_116`: [P] ring_nf at h₁ ⟶ [P] nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)]
- `mathd_algebra_13`: [A] aesop ⟶ [P] case left =>
  have h₁ := h₀ 0
  have h₂ := h₀ 1
  have h₃ := h₀ (-2)
  norm_num at h₁ h₂ h₃
  <;> linarith ⟶ [P] case right =>
  have h₁ : b = 10 := by
    have h₂ := h₀ 6
    have h₃ := h₀ 8
    have h₄ := h₀ 10
    have h₅ := h₀ 12
    norm_num at h₂ h₃ h₄ h₅
    field_simp at h₂ h₃ h₄ h₅
    ring_nf at h₂ h₃ h₄ h₅
    linarith
  exact h₁
- `mathd_algebra_140`: [P] have h₂ : a * b - 3 * c = -9 := by
  have h₃ := h₁ 1
  have h₄ := h₁ (-3 / 4)
  have h₅ := h₁ (1 / 3)
  have h₆ := h₁ (-1 / 2)
  have h₇ := h₁ (-1 / 3)
  have h₈ := h₁ 2
  have h₉ := h₁ (-2)
  have h₁₀ := h₁ (-3)
  have h₁₁ := h₁ 0
  have h₁₂ := h₁ 3
  have h₁₃ := h₁ 4
  have h₁₄ := h₁ 5
  have h₁₅ := h₁ 6
  have h₁₆ := h₁ 7
  have h₁₇ := h₁ 8
  have h₁₈ := h₁ 9
  have h₁₉ := h₁ 10
  norm_num at *
  nlinarith ⟶ [A] linarith
- `mathd_algebra_151`: [P] have h1 : Int.ceil (Real.sqrt 27) = 6 := by
  rw [Int.ceil_eq_iff]
  norm_num
  constructor <;>
  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (by norm_num : 0 ≤ (27 : ℝ)),
    Real.sqrt_nonneg 26, Real.sq_sqrt (by norm_num : 0 ≤ (26 : ℝ)),
    Real.sqrt_nonneg 25, Real.sq_sqrt (by norm_num : 0 ≤ (25 : ℝ)),
    Real.sqrt_nonneg 24, Real.sq_sqrt (by norm_num : 0 ≤ (24 : ℝ))] ⟶ [P] have h2 : Int.floor (Real.sqrt 26) = 5 := by
  rw [Int.floor_eq_iff]
  constructor <;> norm_num
  <;> norm_num
  <;>
  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ 26 by norm_num)] ⟶ [A] omega
- `mathd_algebra_181`: [P] field_simp [sub_ne_zero.mpr h₀] at h₁ ⟶ [A] linarith
- `mathd_algebra_192`: [A] simp_all ⟶ [P] ring_nf
<;> simp [Complex.ext_iff, pow_two, pow_three]
<;> norm_num
<;> ring_nf
<;> norm_num
<;> ring_nf
<;> norm_num
- `mathd_algebra_206`: [P] simp_all only [h₀, h₂, h₃, zero_add, mul_zero, add_zero, mul_one, mul_neg, mul_assoc,
  mul_comm, mul_left_comm] ⟶ [P] apply mul_left_cancel₀ (sub_ne_zero.mpr h₁) ⟶ [A] nlinarith
- `mathd_algebra_22`: [P] field_simp [Real.logb, show (5 : ℝ) ≠ 0 by norm_num, show (5 : ℝ) ≠ 1 by norm_num] ⟶ [A] linarith
- `mathd_algebra_234`: [A] ring_nf ⟶ [P] nlinarith [pow_two d, pow_two (d ^ 2)]
- `mathd_algebra_251`: [P] field_simp at h₁ ⟶ [A] linarith
- `mathd_algebra_267`: [P] have h₃ : x = 0 := by
  have h₄ : x - 1 ≠ 0 := by
    intro h
    apply h₀
    linarith
  have h₅ : x + 2 ≠ 0 := by
    intro h
    apply h₁
    linarith
  have h₆ : (x + 1) / (x - 1) = (x - 2) / (x + 2) := h₂
  field_simp [h₄, h₅] at h₆
  ring_nf at h₆
  linarith ⟶ [A] linarith
- `mathd_algebra_28`: [A] aesop ⟶ [P] nlinarith [sq_nonneg (w + 5 / 4)]
- `mathd_algebra_327`: [P] constructor <;>
cases' le_total 0 (9 + 2 * a) with h h <;>
cases' le_total 0 a with ha ha <;>
simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;>
linarith
- `mathd_algebra_405`: [P] simp only [Finset.card] ⟶ [P] have h₁ : ∀ x ∈ S, x = 1 ∨ x = 2 := by
  intro x hx
  have h₂ : 0 < x ∧ x^2 + 4 * x + 4 < 20 := by
    simpa [hx] using h₀ x
  have h₃ : x = 1 ∨ x = 2 := by
    have h₄ : x ≤ 2 := by
      nlinarith
    have h₅ : x ≥ 1 := by
      nlinarith
    omega
  exact h₃ ⟶ [P] have h₂ : S = {1, 2} := by
  ext x
  simp [h₀]
  all_goals aesop ⟶ [A] simp_all
- `mathd_algebra_410`: [P] nlinarith [sq_nonneg (x - 3)]
- `mathd_algebra_421`: [P] nlinarith [sq_nonneg (a - c)]
- `mathd_algebra_433`: [P] have h₁ := h₀ 8 ⟶ [P] have h₂ : Real.sqrt (2 * 8 - 7) = 3 := by
  have h₃ : Real.sqrt (2 * 8 - 7) = 3 := by
    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
  exact h₃ ⟶ [A] linarith
- `mathd_algebra_437`: [P] norm_cast at h₀ h₁ ⟶ [A] simp_all ⟶ [P] have h₄ : n = -4 := by
  nlinarith [sq_nonneg (x - y), sq_nonneg (x + y), h₀, h₁, h₂, h₃] ⟶ [A] omega
- `mathd_algebra_451`: [A] simp_all ⟶ [P] have h₄ := h₀.symm ⟶ [P] have h₅ := h₁.symm ⟶ [P] have h₆ := h₂.symm ⟶ [A] simp_all
- `mathd_algebra_480`: [P] have h₃ := h₁ 0 (by norm_num) ⟶ [P] have h₄ : Real.pi < 4 := by
  have := Real.pi_lt_31416
  norm_num at this ⊢
  <;> linarith ⟶ [P] have h₅ : f π = 2 := by
  apply h₁
  constructor
  · linarith [Real.pi_pos]
  · linarith [Real.pi_pos] ⟶ [A] linarith
- `mathd_algebra_510`: [P] rw [Real.sqrt_eq_iff_sq_eq] <;> nlinarith [h₀, h₁]
- `mathd_algebra_536`: [P] field_simp [Nat.factorial_succ, Nat.factorial_zero, Nat.factorial_succ] ⟶ [P] norm_num
<;> ring
<;> nlinarith [Real.sq_sqrt (show (0 : ℝ) ≤ 9 from by norm_num), Real.sqrt_nonneg 9]
- `mathd_algebra_547`: [P] simp_all only [h₀, h₁, one_pow, sub_eq_add_neg, add_comm, add_left_comm, add_assoc] ⟶ [P] norm_num [Real.sqrt_eq_iff_sq_eq]
- `mathd_algebra_73`: [P] have h₂ : x = p + q - r := by
  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)
  linear_combination h₀ - (p + q - r) * (p + q - r) ⟶ [A] simp_all
- `mathd_algebra_77`: [A] constructor ⟶ [P] all_goals
  simp_all only [h₂, h₃, h₄]
  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)
  ring_nf
  nlinarith
- `mathd_algebra_89`: [A] ring_nf ⟶ [P] norm_cast ⟶ [A] field_simp ⟶ [A] ring_nf
- `mathd_numbertheory_22`: [P] have h₂ : b = 3 ∨ b = 1 := by
  have h₃ : b ≤ 9 := by linarith
  interval_cases b <;> norm_num at h₁ ⊢ <;>
  (try contradiction) <;>
  (try omega) <;>
  (try simp_all) ⟶ [A] omega
- `mathd_numbertheory_257`: [P] rcases h₀ with ⟨h₀_left, h₀_right⟩ ⟶ [P] interval_cases x <;> simp_all (config := {decide := true})
- `mathd_numbertheory_32`: [P] have h₁ : S = Finset.filter (λ n => n ∣ 36) (Finset.range 37) := by
  ext n
  simp [h₀]
  <;> tauto ⟶ [A] aesop
- `mathd_numbertheory_326`: [P] ring_nf at h₀ ⟶ [P] apply Eq.symm ⟶ [P] nlinarith [sq_nonneg (n - 4), sq_nonneg (n + 4), sq_nonneg (n - 3), sq_nonneg (n + 3)]
- `mathd_numbertheory_35`: [P] have h₁ := h₀ 24 ⟶ [P] norm_num at h₁
- `mathd_numbertheory_412`: [P] simp [h₀, h₁, pow_two, pow_three, Int.mul_emod, Int.add_emod]
- `mathd_numbertheory_629`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro t ht
  by_contra h
  push_neg at h
  have h1 : t < 18 := by linarith
  have h2 : Nat.lcm 12 t ^ 3 = (12 * t) ^ 2 := by
    simpa using ht.2
  have h3 : t < 18 := by linarith
  have h4 : t ≤ 17 := by
    omega
  interval_cases t <;> norm_num at h1 h2 h3 ⊢ <;> try {
    aesop
  }
- `mathd_numbertheory_64`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro x hx
  norm_num [Nat.ModEq] at hx
  omega
- `mathd_numbertheory_690`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro a ha
  norm_num [Nat.ModEq] at ha ⊢
  rcases ha with ⟨ha_pos, ha_3, ha_5, ha_7, ha_9⟩
  omega
- `mathd_numbertheory_780`: [P] have h₄ : m = 43 := by
  have h₅ : m ≤ 99 := by
    linarith [h₁.1, h₁.2]
  have h₆ : m ≥ 10 := by
    linarith [h₁.1]
  interval_cases m <;> norm_num at h₂ h₃ <;> omega ⟶ [A] omega
- `mathd_numbertheory_84`: [P] norm_num [Int.floor_eq_iff]
- `numbertheory_2dvd4expn`: [P] induction n with
| zero =>
  simp_all [Nat.zero_eq]
| succ n ih =>
  simp_all [Nat.pow_succ, Nat.mul_succ, Nat.add_assoc]
  all_goals omega
- `numbertheory_nckeqnm1ckpnm1ckm1`: [P] rw [← succ_pred_eq_of_pos h₀.1] ⟶ [P] induction n <;>
induction k <;>
simp_all [Nat.choose_succ_succ, Nat.choose_zero_right, Nat.choose_one_right, Nat.zero_eq, Nat.succ_eq_add_one]
<;>
linarith
- `numbertheory_sqmod3in01d`: [P] have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ [P] rcases this with (h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]
- `numbertheory_sqmod4in01d`: [P] have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ [P] rcases this with (h | h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]

## Lost against row 0

none
