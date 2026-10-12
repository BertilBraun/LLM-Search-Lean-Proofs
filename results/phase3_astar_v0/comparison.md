# phase3_astar_v0 vs phase0_automation_baseline

**Solved 155/244 (63.5%) vs 79/244 (32.4%) for row 0**: 76 newly solved, 0 lost. Proofs using at least one policy step: 90. Row 0 ran 256 expansions and 300 s per theorem with 32 processes; see each run's config for its budget.

## By category

| category | problems | row 0 | this run | newly solved | lost |
|---|---|---|---|---|---|
| mathd_algebra | 70 | 28 | 58 | 30 | 0 |
| mathd_numbertheory | 60 | 38 | 49 | 11 | 0 |
| amc12 | 45 | 8 | 19 | 11 | 0 |
| aime | 15 | 0 | 2 | 2 | 0 |
| imo | 20 | 0 | 2 | 2 | 0 |
| algebra | 18 | 5 | 15 | 10 | 0 |
| numbertheory | 8 | 0 | 4 | 4 | 0 |
| induction | 8 | 0 | 6 | 6 | 0 |

## Anytime curves (solved theorems at budget)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| row 0 | 59 | 72 | 77 | 79 | 79 | 79 | 79 |
| this run | 84 | 119 | 131 | 139 | 146 | 152 | 155 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 613.161 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| row 0 | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| this run | 33 | 55 | 80 | 105 | 123 | 127 | 139 | 147 | 148 | 151 | 155 | 155 |

## Cost per theorem

| quantity | value |
|---|---|
| mean / median generated tokens | 12208 / 977 |
| total generated tokens | 2,978,648 |
| generated tokens per solved theorem | 19,217 |
| mean prompt tokens (computed once per request) | 4157 |
| mean / median wall seconds | 175.0 / 17.8 |
| mean Lean seconds | 114.8 |
| mean expansions | 22.1 |

## Throughput in the search

| quantity | value |
|---|---|
| run wall minutes | 24.2 |
| policy requests / samples | 5,299 / 84,784 |
| samples/s over the policy window | 59.6 |
| generated tokens/s | 2117 |
| mean request latency s | 2.46 |
| summed request s / summed Lean s | 13,019 / 28,004 |
| distinct candidates per request | 10.6 |
| duplicate / failed sample fraction | 30.5% / 3.4% |
| prompt cache hit rate | 86.7% |
| requests without candidates (unattributed tokens) | 0 (0) |
| prompts too long | 0 |

## Newly solved (P = policy step, A = automation)

- `aime_1984_p15`: [P] ring_nf at * ⟶ [A] linarith
- `aime_1991_p1`: [P] have h3 : x ≤ 71 := by
  nlinarith ⟶ [P] interval_cases x <;> try {
  omega
} ⟶ [P] all_goals nlinarith
- `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`: [P] refine' ⟨_, _⟩ ⟶ [P] ring_nf at h₀ h₁ ⊢ ⟶ [P] all_goals
  apply Eq.symm
  apply Eq.symm
  ring_nf at h₀ h₁ ⊢
  simp_all [Complex.ext_iff]
  constructor <;> nlinarith
- `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`: [A] aesop ⟶ [A] norm_num ⟶ [P] have h₁ : (2 : ℝ) ≤ 2 - Real.sqrt 2 + x⁻¹ * (1 / 2) + x := by
  have h₂ : 0 < Real.sqrt 2 := by norm_num
  have h₃ : 0 < x := by linarith
  have h₄ : 0 < x ^ 2 := by positivity
  have h₅ : 0 < x ^ 3 := by positivity
  have h₆ : 0 < x ^ 4 := by positivity
  field_simp
  rw [le_div_iff (by positivity)]
  nlinarith [Real.sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - 1),
    sq_nonneg (x - Real.sqrt 2 / 2), sq_nonneg (x - 1 + Real.sqrt 2 / 2)] ⟶ [A] linarith
- `algebra_apb4leq8ta4pb4`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), sq_nonneg (a ^ 2 - b ^ 2), sq_nonneg (a ^ 2 + b ^ 2),
  sq_nonneg (a ^ 2 - 2 * a * b + b ^ 2), sq_nonneg (a ^ 2 + 2 * a * b + b ^ 2)]
- `algebra_binomnegdiscrineq_10alt28asqp1`: [P] nlinarith [sq_nonneg (a - 1/5)]
- `algebra_manipexpr_apbeq2cceqiacpbceqm2`: [A] simp_all ⟶ [P] simp_all [Complex.ext_iff, Complex.I_mul_I] ⟶ [A] linarith
- `algebra_sqineq_2at2pclta2c2p41pc`: [P] nlinarith [sq_nonneg (a - c - 2)]
- `algebra_sqineq_2unitcircatblt1`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]
- `algebra_sqineq_36azm9asqle36zsq`: [P] nlinarith [sq_nonneg (a - 2 * z)]
- `algebra_sqineq_4bap1lt4bsqpap1sq`: [A] ring_nf ⟶ [P] nlinarith [sq_nonneg (b - (a + 1) / 2)]
- `algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3`: [P] rw [dvd_iff_exists_eq_mul_left] ⟶ [P] use x^2 + y^2 + z^2 - x * y - y * z - z * x ⟶ [A] linarith
- `amc12_2000_p11`: [P] have h₂ : a / b + b / a - a * b = 2 := by
  have h₃ : a / b + b / a - a * b = 2 := by
    have h₄ : a ≠ 0 := h₀.1
    have h₅ : b ≠ 0 := h₀.2
    field_simp [h₄, h₅]
    nlinarith [h₁, mul_self_nonneg (a - b)]
  exact h₃ ⟶ [A] linarith
- `amc12_2000_p5`: [P] cases' le_total 0 (x - 2) with h h <;>
simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;>
linarith
- `amc12a_2009_p5`: [P] nlinarith [sq_nonneg (x + 1), sq_nonneg (x - 1)]
- `amc12a_2009_p9`: [A] simp_all ⟶ [P] have h₂ := h₀ (-3) ⟶ [P] have h₃ := h₀ 0 ⟶ [A] simp_all ⟶ [P] linarith [h₀ 0, h₀ 1, h₀ 2]
- `amc12a_2011_p18`: [P] cases' le_total 0 (x + y) with h₁ h₁ <;>
cases' le_total 0 (x - y) with h₂ h₂ <;>
simp_all only [abs_of_nonneg, abs_of_nonpos, sub_nonneg, sub_nonpos] <;>
nlinarith [sq_nonneg (x - 3), sq_nonneg (y - 3), sq_nonneg (x + 3), sq_nonneg (y + 3)]
- `amc12a_2013_p8`: [P] have h₄ : x * y = 2 := by
  field_simp [h₀, h₁, h₂, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₃
  have h₅ : x * y - 2 = 0 := by
    apply mul_left_cancel₀ (sub_ne_zero.mpr h₂)
    nlinarith
  linarith ⟶ [A] linarith
- `amc12a_2015_p10`: [P] have h₃ : x ≤ 80 := by
  nlinarith ⟶ [P] have h₄ : y ≤ 80 := by nlinarith ⟶ [P] interval_cases y <;> try {
  omega
} <;> try {
  interval_cases x <;> omega
}
- `amc12b_2002_p6`: [A] constructor ⟶ [P] ·
  have h₂ := h₁ 0
  have h₃ := h₁ 1
  simp at h₂ h₃
  nlinarith [sq_pos_of_ne_zero h₀.1, sq_pos_of_ne_zero h₀.2, sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.1), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₀.2)] ⟶ [P] ·
  have h₂ := h₁ 0
  have h₃ := h₁ 1
  have h₄ := h₁ (-1)
  have h₅ := h₁ 2
  have h₆ := h₁ (-2)
  have h₇ := h₁ (a / 2)
  have h₈ := h₁ (-a / 2)
  field_simp [h₀.1, h₀.2] at h₂ h₃ h₄ h₅ h₆ h₇ h₈
  linarith [h₂, h₃, h₄, h₅, h₆, h₇, h₈]
- `amc12b_2003_p17`: [A] field_simp ⟶ [P] simp [Real.log_mul, h₀.1.ne', h₀.2.ne', Real.log_pow, h₀.1.ne', h₀.2.ne'] at h₁ h₂ ⊢ ⟶ [A] linarith
- `amc12b_2004_p3`: [P] have h1 : 2 ^ x * 3 ^ y = 1296 := h₀ ⟶ [P] have h2 : x ≤ 10 := by
  by_contra h
  push_neg at h
  have h3 : x ≥ 11 := by omega
  have h4 : 2 ^ x ≥ 2 ^ 11 := by
    apply Nat.pow_le_pow_of_le_right (show 0 < 2 by norm_num)
    <;> omega
  have h5 : 3 ^ y ≥ 1 := by
    apply Nat.one_le_pow
    norm_num
  have h6 : 2 ^ x * 3 ^ y ≥ 2 ^ 11 * 1 := by
    nlinarith
  have h7 : 2 ^ 11 * 1 = 2048 := by norm_num
  have h8 : 2 ^ x * 3 ^ y ≥ 2048 := by nlinarith
  have h9 : 2 ^ x * 3 ^ y = 1296 := h1
  linarith ⟶ [P] have h3 : y ≤ 15 := by
  by_contra h
  have h4 : y ≥ 16 := by omega
  have h5 : 3 ^ y ≥ 3 ^ 16 := by exact pow_le_pow_right (by norm_num) h4
  have h6 : 2 ^ x * 3 ^ y ≥ 2 ^ 0 * 3 ^ 16 := by
    have h7 : 2 ^ x ≥ 2 ^ 0 := by
      apply pow_le_pow_right
      norm_num
      all_goals omega
    nlinarith
  norm_num at h1
  all_goals nlinarith ⟶ [P] interval_cases x <;> interval_cases y <;> simp_all
- `amc12b_2020_p5`: [P] field_simp at h₀ h₁ ⟶ [P] ring_nf at h₀ h₁ ⟶ [P] norm_cast at h₀ h₁ ⟶ [A] omega
- `imo_1961_p1`: [A] ring_nf ⟶ [P] have h₇ : a^2 < 3 * b^2 := by
  nlinarith [sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₂), sq_pos_of_ne_zero (sub_ne_zero_of_ne h₃),
    Real.sqrt_nonneg (x * y - z ^ 2)] ⟶ [P] refine' ⟨_, _, _⟩
<;> nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)]
<;> nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)]
<;> nlinarith [sq_nonneg (x - y), sq_nonneg (y - z), sq_nonneg (z - x)]
- `imo_1974_p5`: [A] aesop ⟶ [P] case left =>
  apply lt_of_sub_pos
  field_simp
  ring_nf
  nlinarith [mul_pos left left_1, mul_pos left left_2, mul_pos right left_1, mul_pos right left_2] ⟶ [P] ·
  have h₀ : 0 < a + b + d := by linarith
  have h₁ : 0 < a + b + c := by linarith
  have h₂ : 0 < b + c + d := by linarith
  have h₃ : 0 < a + c + d := by linarith
  have h₄ : 0 < a * b := by positivity
  have h₅ : 0 < a * c := by positivity
  have h₆ : 0 < a * d := by positivity
  have h₇ : 0 < b * c := by positivity
  have h₈ : 0 < b * d := by positivity
  have h₉ : 0 < c * d := by positivity
  field_simp
  rw [← sub_pos]
  field_simp
  ring_nf
  nlinarith
- `induction_divisibility_3div2tooddnp1`: [P] induction n with
| zero =>
  norm_num
| succ n ih =>
  simp only [Nat.mul_succ, Nat.add_succ, pow_succ, pow_add, pow_one, Nat.mul_zero, Nat.add_zero] at ih ⊢
  omega
- `induction_divisibility_3divnto3m2n`: [P] have h : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ [P] rcases h with (h | h | h) <;>
simp [h, Nat.dvd_iff_mod_eq_zero, Nat.pow_succ, Nat.mul_mod, Nat.add_mod, Nat.mod_eq_of_lt]
- `induction_divisibility_9div10tonm1`: [P] induction n with
| zero => contradiction
| succ n ih =>
  cases n with
  | zero => norm_num
  | succ n =>
    simp [Nat.pow_succ, Nat.mul_sub_left_distrib] at ih ⊢
    omega
- `induction_ineq_nsqlefactn`: [P] induction' h₀ with n hn ⟶ [A] decide ⟶ [P] { simp_all [Nat.factorial_succ, Nat.succ_mul, Nat.mul_succ]
  nlinarith }
- `induction_sum2kp1npqsqm1`: [P] induction n with
| zero =>
  simp
| succ n hn =>
  simp_all [Finset.sum_range_succ, Nat.succ_eq_add_one]
  ring_nf
  omega
- `induction_sum_1oktkp1`: [P] induction n with
| zero =>
  simp
| succ n ih =>
  simp_all [Finset.sum_range_succ, mul_add, mul_comm, mul_left_comm, mul_assoc]
  field_simp
  ring
- `mathd_algebra_11`: [P] have h₄ : a - 2 * b ≠ 0 := by
  intro h₅
  apply h₁
  linarith ⟶ [P] have h₅ : a - b ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] have h₆ : (a + 11 * b) / (a - b) = 2 := by
  field_simp [h₄, h₅] at h₂ ⊢
  nlinarith ⟶ [A] linarith
- `mathd_algebra_116`: [P] simp_all only [sq, mul_one, mul_add, mul_sub, mul_comm, mul_left_comm, mul_right_comm] ⟶ [P] nlinarith [Real.sq_sqrt (show 0 ≤ 131 by norm_num)]
- `mathd_algebra_13`: [A] aesop ⟶ [P] ·
  have h₁ := h₀ 4 (by norm_num) (by norm_num)
  have h₂ := h₀ 6 (by norm_num) (by norm_num)
  norm_num at h₁ h₂
  linarith ⟶ [P] {
  have h₁ := h₀ 4
  have h₂ := h₀ 0
  have h₃ := h₀ 3
  have h₄ := h₀ 5
  norm_num at h₁ h₂ h₃ h₄
  all_goals linarith
}
- `mathd_algebra_131`: [A] simp_all ⟶ [P] have h₄ : a - 1 ≠ 0 := by
  by_contra h
  have eq1 : a = 1 := by linarith
  rw [eq1] at h₁
  nlinarith ⟶ [P] have h₅ : b - 1 ≠ 0 := by
  by_contra h
  have h₆ : b = 1 := by linarith
  rw [h₆] at h₂
  nlinarith ⟶ [A] field_simp ⟶ [P] nlinarith [sq_pos_of_ne_zero (sub_ne_zero.mpr h₃), sq_pos_of_ne_zero (sub_ne_zero.mpr h₄), sq_pos_of_ne_zero (sub_ne_zero.mpr h₅)]
- `mathd_algebra_140`: [P] have h2 := h₁ 1 ⟶ [A] aesop ⟶ [P] nlinarith [h₁ 0, h₁ 1, h₁ 2, h₁ 3, h₁ 4, h₁ 5, h₁ 6, h₁ 7, h₁ 8, h₁ 9]
- `mathd_algebra_151`: [P] have h1 : 27 < 1001 := by norm_num ⟶ [P] have h2 : √27 > 5 := by
  have h2 : (5 : ℝ) < √27 := by
    apply Real.lt_sqrt_of_sq_lt
    norm_num
  linarith ⟶ [P] have h3 : Real.sqrt 26 < 6 := by
  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show (0 : ℝ) ≤ 26 by norm_num)] ⟶ [P] have h4 : ⌈(Real.sqrt 27 : ℝ)⌉ = 6 := by
  rw [Int.ceil_eq_iff]
  constructor <;> norm_num <;>
  nlinarith [Real.sqrt_nonneg 27, Real.sq_sqrt (show 0 ≤ 27 by norm_num)] ⟶ [P] have h5 : ⌊Real.sqrt 26⌋ = 5 := by
  rw [Int.floor_eq_iff]
  constructor <;> norm_num <;>
  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (show 0 ≤ (26 : ℝ) by norm_num)] ⟶ [A] omega
- `mathd_algebra_181`: [P] have h₂ : n - 3 ≠ 0 := by
  intro h
  apply h₀
  linarith ⟶ [P] have h₃ : n = 11 := by
  field_simp [h₂] at h₁
  linarith ⟶ [A] linarith
- `mathd_algebra_192`: [A] simp_all ⟶ [P] norm_num [Complex.ext_iff, pow_two]
- `mathd_algebra_206`: [P] rw [h₀] at h₂ h₃ ⟶ [P] apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ [A] nlinarith
- `mathd_algebra_22`: [P] simp [Real.logb, show (5: ℝ) ≠ 0 by norm_num, show (4 : ℝ) ≠ 0 by norm_num]
<;> ring
<;> norm_num
<;> linarith
- `mathd_algebra_234`: [P] field_simp at h₀ ⊢ ⟶ [P] nlinarith [h₀, sq_nonneg (3 * d), sq_nonneg (5 * d), sq_nonneg (3 * d - 5 * d)]
- `mathd_algebra_251`: [P] have h₂ : x = 2 := by
  have h₃ : x ≠ 0 := h₀
  have h₄ : 3 + 1 / x = 7 / x := h₁
  have h₅ : x = 2 := by
    field_simp at h₄ ⊢
    nlinarith
  exact h₅ ⟶ [A] linarith
- `mathd_algebra_267`: [P] apply Eq.symm ⟶ [P] field_simp [h₀, h₁, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₂ ⟶ [A] linarith
- `mathd_algebra_28`: [A] aesop ⟶ [P] nlinarith [sq_nonneg (w + 5 / 4)]
- `mathd_algebra_323`: [A] simp ⟶ [P] have h₁ := h 3 ⟶ [P] norm_num at h₁ ⟶ [P] have h₂ : (σ.symm 19) = (3 : ℝ) := by
  rw [show 19 = σ 3 by linarith [h₁]]
  simp [← h]
  <;> norm_num
  <;>
  (try
    {
      norm_num
    })
  <;>
  (try
    {
      aesop
    }) ⟶ [A] linarith
- `mathd_algebra_327`: [P] constructor <;>
cases' le_total 0 (9 + 2 * a) with h h <;>
simp_all only [abs_of_nonneg, abs_of_nonpos, le_of_lt] <;>
linarith
- `mathd_algebra_393`: [A] simp_all ⟶ [P] have h1 : σ 2 = 33 := by
  rw [h₀]
  norm_num ⟶ [A] simp_all ⟶ [P] have h2 : σ 2 = 33 := by
  rw [h₀]
  norm_num ⟶ [P] rw [show 33 = σ 2 by linarith [h2]] ⟶ [A] simp
- `mathd_algebra_405`: [P] have h₁ : S = Finset.filter (fun x => 0 < x ∧ x^2 + 4*x + 4 < 20) (Finset.range 21) := by
  ext x
  simp [h₀, Finset.mem_filter]
  <;> omega ⟶ [A] aesop
- `mathd_algebra_410`: [A] aesop ⟶ [P] nlinarith [sq_nonneg (x - 3)]
- `mathd_algebra_421`: [P] nlinarith [sq_nonneg (a - c), sq_nonneg (a + c + 2)]
- `mathd_algebra_433`: [P] have h₁ : f 8 = 1 := by
  rw [h₀]
  have h₂ : sqrt (2 * (8 : ℝ) - 7) = 3 := by
    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
  rw [h₂]
  norm_num ⟶ [A] linarith
- `mathd_algebra_437`: [P] have h₄ : n = -4 := by
  have h₅ : (x : ℝ) < (n : ℝ) := by exact_mod_cast h₂
  have h₆ : (n : ℝ) < (y : ℝ) := by exact_mod_cast h₃
  have h₇ : (x : ℝ) ^ 3 = -45 := by norm_num [h₀]
  have h₈ : (y : ℝ) ^ 3 = -101 := by norm_num [h₁]
  have h₉ : (n : ℝ) = -4 := by
    nlinarith [pow_two_nonneg ((x - 3) * (x + 3)), pow_two_nonneg (y - 4), pow_two_nonneg (y + 4),
      pow_two_nonneg ((x + 4 : ℝ) * (x - 4 : ℝ)), pow_two_nonneg (y - 5 : ℝ), pow_two_nonneg (y + 5 : ℝ)]
  exact_mod_cast h₉ ⟶ [A] omega
- `mathd_algebra_480`: [P] have h_pi_pos : (0 : ℝ) ≤ Real.pi ∧ Real.pi < 4 := by
  have h_pos : 0 < Real.pi := Real.pi_pos
  have h_bound : Real.pi < 4 := by
    have := Real.pi_gt_31415
    have := Real.pi_lt_31416
    norm_num at *
    <;> linarith
  constructor
  · linarith
  · linarith ⟶ [A] simp_all
- `mathd_algebra_493`: [P] have h₁ : f 4 = 9 := by
  rw [h₀ 4]
  have h₁ : Real.sqrt 4 = 2 := by
    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
  rw [h₁]
  norm_num ⟶ [P] have h₂ : f (f 4) = 70 := by
  rw [h₁]
  have h₃ : f 9 = 9 ^ 2 - 4 * Real.sqrt 9 + 1 := by
    apply h₀
  rw [h₃]
  have h₄ : Real.sqrt 9 = 3 := by
    norm_num [Real.sqrt_eq_iff_sq_eq]
  rw [h₄]
  norm_num ⟶ [A] linarith
- `mathd_algebra_510`: [P] rw [Real.sqrt_eq_iff_sq_eq] <;> nlinarith [sq_nonneg (x - y)]
- `mathd_algebra_536`: [P] have h_main : (Nat.factorial 3 : ℝ) * ((2 : ℝ) ^ 3 + Real.sqrt (9 : ℝ)) / 2 = 33 := by
  have h₁ : (Nat.factorial 3 : ℝ) = (6 : ℝ) := by
    norm_num [Nat.factorial]
    <;>
    simp_all [Nat.factorial]
    <;>
    norm_num
    <;>
    linarith
  have h₂ : (Real.sqrt (9 : ℝ) : ℝ) = (3 : ℝ) := by
    rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
  rw [h₁, h₂]
  <;> ring_nf
  <;> norm_num
  <;>
  linarith ⟶ [A] linarith
- `mathd_algebra_547`: [P] subst h₀; subst h₁; norm_num ⟶ [P] rw [Real.sqrt_eq_iff_mul_self_eq] <;> norm_num
- `mathd_algebra_73`: [P] apply mul_left_cancel₀ (sub_ne_zero.mpr h₁) ⟶ [A] ring_nf ⟶ [P] linear_combination h₀
- `mathd_algebra_77`: [A] simp_all ⟶ [A] constructor ⟶ [P] all_goals
  apply mul_left_cancel₀ (sub_ne_zero.mpr h₁)
  nlinarith
- `mathd_algebra_89`: [A] simp ⟶ [P] have h₁ : b ^ 2 ≠ 0 := by
  intro h
  apply h₀
  nlinarith ⟶ [P] field_simp [h₀, h₁, pow_ne_zero, pow_two, mul_ne_zero] ⟶ [A] ring_nf ⟶ [P] have h₂ : b^6 * 3136 = (b^2 * 4)^3 * 49 := by
  ring_nf
  <;> nlinarith
  <;> ring_nf
  <;> nlinarith ⟶ [A] aesop
- `mathd_numbertheory_22`: [P] have h₂ : b ≤ 9 := by linarith ⟶ [P] interval_cases b <;> norm_num at h₁ <;> omega
- `mathd_numbertheory_257`: [P] rcases h₀ with ⟨h₀_left, h₀_right⟩ ⟶ [P] interval_cases x <;> norm_num [Finset.sum_range_succ] at h₁
<;> omega
- `mathd_numbertheory_32`: [P] have h₁ : S = Finset.filter (fun n ↦ n ∣ 36) (Finset.range 37) := by
  ext n
  simp [h₀] ⟶ [A] aesop
- `mathd_numbertheory_326`: [P] ring_nf at h₀ ⟶ [P] have h : n^3 + (-n) = 720 := by linarith ⟶ [P] have h₁ : n + 1 = 10 := by
  nlinarith [sq_nonneg (n - 10), sq_nonneg (n + 1), sq_nonneg (n ^ 2 - 100), sq_nonneg (n ^ 2 + 100)] ⟶ [A] omega
- `mathd_numbertheory_35`: [P] have h₁ : (∑ k in S, k) = 24 := by
  have h₂ := h₀ 196
  have h₃ := h₀ 21
  have h₄ := h₀ 14
  have h₅ := h₀ 7
  have h₆ := h₀ 3
  have h₇ := h₀ 2
  have h₈ := h₀ 1
  norm_num at *
  <;>
  (try omega) <;>
  (try
    {
      simp_all [Finset.sum_eq_multiset_sum]
      <;> norm_num
      <;> omega
    }) <;>
  (try
    {
      norm_num at *
      <;> omega
    })
  <;>
  (try
    {
      omega
    })
  <;>
  (try
    {
      aesop
    }) ⟶ [A] omega
- `mathd_numbertheory_412`: [P] simp [h₀, h₁, pow_two, pow_three, Int.mul_emod, Int.add_emod, Int.sub_emod]
- `mathd_numbertheory_629`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro t ht
  rcases ht with ⟨ht_pos, ht_lcm⟩
  by_contra h
  push_neg at h
  interval_cases t <;> norm_num [Nat.lcm] at ht_lcm <;> omega
- `mathd_numbertheory_64`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro x hx
  simp [Nat.ModEq] at hx
  omega
- `mathd_numbertheory_690`: [A] constructor ⟶ [A] decide ⟶ [P] ·
  intro a
  rintro ⟨ha_pos, ha_mod2, ha_mod5, ha_mod7, ha_mod9⟩
  by_contra h
  push_neg at h
  interval_cases a <;> norm_num [Nat.ModEq] at ha_mod2 ha_mod5 ha_mod7 ha_mod9 <;> omega
- `mathd_numbertheory_780`: [P] rcases h₁ with ⟨h₁, h₄⟩ ⟶ [P] interval_cases m <;> omega
- `mathd_numbertheory_84`: [P] norm_num [Int.floor_eq_iff]
- `numbertheory_2dvd4expn`: [P] induction n with
| zero => contradiction
| succ n ih =>
  simp_all [Nat.pow_succ, Nat.mul_succ]
  omega
- `numbertheory_nckeqnm1ckpnm1ckm1`: [P] cases n <;> cases k <;> simp_all [choose, Nat.succ_mul, Nat.mul_succ]
<;> omega
- `numbertheory_sqmod3in01d`: [P] have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ [P] rcases this with (h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]
- `numbertheory_sqmod4in01d`: [P] have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega ⟶ [P] rcases this with (h | h | h | h) <;>
simp [h, pow_two, Int.mul_emod, Int.add_emod]

## Lost against row 0

none
