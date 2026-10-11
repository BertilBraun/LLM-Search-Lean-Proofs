# phase1_fewshot_search_qwen3.5-2b-base vs phase0_automation_baseline

**Solved 117/244 (48.0%) vs 79/244 (32.4%) for row 0**: 38 newly solved, 0 lost. Proofs using at least one policy step: 51. Row 0 ran 256 expansions and 300 s per theorem with 32 processes; see each run's config for its budget.

## By category

| category | problems | row 0 | this run | newly solved | lost |
|---|---|---|---|---|---|
| mathd_algebra | 70 | 28 | 46 | 18 | 0 |
| mathd_numbertheory | 60 | 38 | 40 | 2 | 0 |
| amc12 | 45 | 8 | 13 | 5 | 0 |
| aime | 15 | 0 | 0 | 0 | 0 |
| imo | 20 | 0 | 0 | 0 | 0 |
| algebra | 18 | 5 | 13 | 8 | 0 |
| numbertheory | 8 | 0 | 2 | 2 | 0 |
| induction | 8 | 0 | 3 | 3 | 0 |

## Anytime curves (solved theorems at budget)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| row 0 | 59 | 72 | 77 | 79 | 79 | 79 | 79 |
| this run | 77 | 91 | 102 | 107 | 110 | 116 | 117 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 609.441 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| row 0 | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| this run | 40 | 55 | 60 | 74 | 91 | 97 | 106 | 108 | 111 | 115 | 117 | 117 |

## Cost per theorem

| quantity | value |
|---|---|
| mean / median generated tokens | 53687 / 26099 |
| total generated tokens | 13,099,602 |
| generated tokens per solved theorem | 111,962 |
| mean prompt tokens (computed once per request) | 19607 |
| mean / median wall seconds | 290.8 / 150.4 |
| mean Lean seconds | 74.8 |
| mean expansions | 28.3 |

## Throughput in the search

| quantity | value |
|---|---|
| run wall minutes | 53.6 |
| policy requests / samples | 6,827 / 109,232 |
| samples/s over the policy window | 34.2 |
| generated tokens/s | 4154 |
| mean request latency s | 7.68 |
| summed request s / summed Lean s | 52,414 / 18,245 |
| distinct candidates per request | 10.4 |
| duplicate / failed sample fraction | 1.5% / 33.3% |
| prompt cache hit rate | 95.6% |
| requests without candidates (unattributed tokens) | 0 (0) |
| prompts too long | 0 |
| GPU utilization mean / median | 89% / 97% |
| readings at ≥ 90% utilization | 69% of 644 |
| mean power W / peak memory MiB | 334 / 22746 |

## Newly solved (P = policy step, A = automation)

- `algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x`: [P] intro x hx ⟶ [P] have h₁ : 2 - √2 ≥ 2 - x - 1 / (2 * x) := by
  have h₂ : 0 < x := hx
  field_simp [h₂.ne']
  rw [div_le_iff (by positivity)]
  nlinarith [sq_sqrt (by positivity : 0 ≤ (2 : ℝ)), sq_nonneg (x - Real.sqrt 2 / 2)]
exact h₁
- `algebra_apb4leq8ta4pb4`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), h₀]
- `algebra_binomnegdiscrineq_10alt28asqp1`: [P] have h₁ : a ≤ 28 * a ^ 2 + 1 / 10 := by
  nlinarith [sq_nonneg (a - 1), sq_nonneg (a - 1 / 14)] ⟶ [P] have h₁ : a ≤ 28 * a ^ 2 + 1 / 10 := h₁ ⟶ [P] norm_num at h₁ ⟶ [P] have h₁ : a ≤ 28 * a ^ 2 + 1 / 10 := h₁ ⟶ [P] have h₁ : 10 * a ≤ 28 * a ^ 2 + 1 := by
  nlinarith [sq_nonneg (a - 1), sq_nonneg (a - 1 / 7)] ⟶ [A] linarith
- `algebra_manipexpr_apbeq2cceqiacpbceqm2`: [P] have h₂ : a * Complex.I + b * Complex.I = -2 ⟶ [P] simp_all [Complex.ext_iff]
<;> ring_nf at *
<;> norm_num
<;> linarith ⟶ [A] simp_all
- `algebra_sqineq_2at2pclta2c2p41pc`: [P] nlinarith [sq_nonneg (a - (2 + c)), sq_nonneg (c - 1)]
- `algebra_sqineq_2unitcircatblt1`: [P] nlinarith [sq_nonneg (a - b), h₀]
- `algebra_sqineq_36azm9asqle36zsq`: [A] simp ⟶ [A] ring_nf ⟶ [P] have h₁ : a * z * 36 ≤ a ^ 2 * 9 + z ^ 2 * 36 := by
  nlinarith [sq_nonneg (a - 3 * z), sq_nonneg (a - 2 * z)] ⟶ [A] linarith
- `algebra_sqineq_4bap1lt4bsqpap1sq`: [P] have h : 4 * b * (a + 1) ≤ 4 * b ^ 2 + (a + 1) ^ 2 := by
  nlinarith [sq_nonneg (a + 1 - 2 * b), sq_nonneg (a - 1), sq_nonneg (b - 1)]
exact h
- `amc12_2000_p11`: [P] have h₃ : a ≠ 0 := h₀.1
have h₄ : b ≠ 0 := h₀.2
have h₅ : a * b ≠ 0 := mul_ne_zero h₃ h₄
field_simp [h₅]
nlinarith [sq_nonneg (a - 1), sq_nonneg (b - 1), h₁, sq_nonneg (a - b)]
- `amc12a_2008_p8`: [P] have h₃ : y = 1 := by
  nlinarith ⟶ [P] have h₃ : y = 1 := by
  nlinarith [sq_nonneg (y - 1)] ⟶ [P] have h₃ : y = 1 := by
  nlinarith [sq_sqrt (show 0 ≤ 1 by norm_num)] ⟶ [P] have h₃ : y = 1 := by
  nlinarith [sq_nonneg (y - 1), h₁] ⟶ [A] ring_nf ⟶ [P] have h₄ : 0 < Real.sqrt 2 := by
  exact Real.sqrt_pos.mpr (by norm_num) ⟶ [P] have h₄ : 0 < √2 := by
  exact Real.sqrt_pos.mpr (by norm_num) ⟶ [P] have h₄ : 0 < √2 := by positivity ⟶ [P] have h₅ : √2 > 0 := by
  exact Real.sqrt_pos.mpr (by norm_num) ⟶ [P] have h₁ : x ^ 3 = √2 * 2 := by
  nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num),
    sq_nonneg (x - √2),
    sq_nonneg (y - 1)]
exact h₁
- `amc12a_2009_p5`: [P] nlinarith [sq_nonneg (x - 5)]
- `amc12a_2011_p18`: [P] have h₁ : |x + y| + |x - y| = 2 := h₀ ⟶ [A] ring_nf ⟶ [P] cases' le_total 0 (x + y) with h h <;>
cases' le_total 0 (x - y) with hh h <;>
simp_all [abs_of_nonneg, abs_of_nonpos, sub_eq_add_neg]
all_goals
  nlinarith
- `amc12a_2016_p3`: [A] field_simp ⟶ [P] norm_num at h₀ ⟶ [A] norm_num ⟶ [A] simp_all ⟶ [P] have h₁ : ∀ (x y : ℝ), ¬y = 0 → f x y = x - y * ↑⌊x / y⌋ := h₀ ⟶ [A] field_simp ⟶ [P] simp_all [Int.floor_eq_iff]
<;> norm_num ⟶ [P] have h : ∀ (x y : ℝ), ¬y = 0 → f x y = x - y * ↑⌊x / y⌋ := h₁ ⟶ [A] simp_all ⟶ [P] have h : ∀ (x y : ℝ), ¬y = 0 → f x y = x - y * ↑⌊x / y⌋ := h ⟶ [A] field_simp ⟶ [P] have h₁ : (15 + 2 * ⌊-15 / 16⌋ * 8) * 40 = -40 := by
  norm_num [h] ⟶ [P] norm_num
<;> ring_nf
<;> norm_cast
<;> linarith
- `induction_divisibility_3div2tooddnp1`: [P] induction n with
| zero => norm_num
| succ n ih =>
  simp_all [Nat.dvd_iff_mod_eq_zero, pow_succ, mul_comm, mul_assoc, mul_left_comm]
  <;> ring_nf at * <;> omega
- `induction_sum2kp1npqsqm1`: [A] ring_nf ⟶ [P] have h : ∑ x in Finset.range n, (3 + x * 2) = (n + 1) ^ 2 - 1 := by
  induction n with
  | zero => simp
  | succ n ih =>
    simp_all [Finset.sum_range_succ, Nat.cast_add, Nat.cast_mul, Nat.cast_one]
    <;> ring_nf at *
    <;> omega ⟶ [A] omega
- `induction_sum_1oktkp1`: [P] induction n with
| zero => simp
| succ n hi =>
  simp_all [Finset.sum_range_succ, Finset.sum_range_one, mul_succ, Nat.cast_zero, Nat.cast_succ,
    add_comm, add_left_comm, add_assoc, mul_add, add_mul, mul_one, div_eq_mul_inv, one_div,
    add_sub_cancel]
  <;> field_simp [Nat.cast_add, Nat.cast_one, Nat.cast_sub, Nat.cast_mul, Nat.cast_div]
  <;> ring_nf
  <;> norm_num
  <;> linarith
- `mathd_algebra_11`: [P] have h₃ : a - 2 * b ≠ 0 := by
  intro h₄
  apply h₁
  linarith
field_simp [h₃] at h₂ ⊢ ⟶ [A] ring_nf ⟶ [P] have h : a ≠ b := h₀ ⟶ [P] field_simp at * ⟶ [P] have h₃ : a - 2 * b ≠ 0 := by
  intro h₃
  contradiction ⟶ [P] have h₁ : a^6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h₁ : a^6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h₁ : a ^ 6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h₁ : a ^ 6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h₄ : a ^ 6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h₄ : a ^ 6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h₄ : a^6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h : a ^ 6 + 1 ≠ 0 := by
  nlinarith [sq_nonneg (a^2 - 1), sq_nonneg (a^3 - 1)] ⟶ [P] have h₄ : a - b ≠ 0 := by
  intro h₄
  apply h₀
  linarith ⟶ [P] have h₅ : a + b * 11 = 2 * (a - b) := by
  nlinarith [h₀, h₁, h₂] ⟶ [A] simp_all
- `mathd_algebra_116`: [P] have h₂ : (13 - Real.sqrt 131) / 4 = (13 - Real.sqrt 131) / 4 := by rfl ⟶ [P] have h₃ : (13 - Real.sqrt 131) / 4 = (13 - Real.sqrt 131) / 4 := rfl
nlinarith [Real.sqrt_nonneg 131, Real.sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num), h₁]
- `mathd_algebra_140`: [P] nlinarith [h₁ 0, h₁ 1, h₁ 2, h₀.2.2, h₀.1, h₀.1]
- `mathd_algebra_181`: [P] have h₂ : (n + 5) / (n - 3) = 2 := h₁
field_simp [h₀] at h₂ ⟶ [P] ring_nf at h₁ h₂ ⊢ ⟶ [P] have h₃ : n ≠ 3 := h₀
field_simp [h₃] at h₁ h₂ ⊢ ⟶ [P] norm_num at h₀ h₁ h₂ ⟶ [P] have h₄ : (n + 5) / (-3 + n) = 2 := h₁
have h₅ : n ≠ 3 := h₃
have h₆ : -3 + n ≠ 0 := by
  intro h
  apply h₅
  linarith
have h₇ : (n + 5) / (-3 + n) = 2 := h₁
have h₈ : n = 11 := by
  field_simp [h₆] at h₇
  linarith
exact h₈
- `mathd_algebra_192`: [P] simp_all [Complex.ext_iff, Complex.I_mul_I] ⟶ [A] norm_num
- `mathd_algebra_22`: [P] simp [logb] ⟶ [A] field_simp ⟶ [A] linarith
- `mathd_algebra_234`: [P] nlinarith [sq_nonneg (d - 1), sq_nonneg (d - 1 / 3)]
- `mathd_algebra_251`: [P] have h : x = 2 := by
  field_simp at h₁
  nlinarith
exact h
- `mathd_algebra_28`: [P] obtain ⟨x, hx⟩ := h₁
have h₂ : f x = 2 * x ^ 2 + 5 * x + c := h₀ x
rw [h₂] at hx ⟶ [P] ring_nf at h₀ h₂ ⊢ ⟶ [P] nlinarith [sq_nonneg (x + 5 / 4)]
- `mathd_algebra_327`: [A] simp_all ⟶ [P] have h₁ : 5⁻¹ * |9 + 2 * a| < 1 := h₀ ⟶ [A] simp_all ⟶ [P] have h₁ : 5⁻¹ * |9 + 2 * a| < 1 := by simpa using h₁ ⟶ [P] norm_num at h₁ ⟶ [P] have h₁ : |9 + 2 * a| < 5 := by
  nlinarith ⟶ [A] simp_all ⟶ [P] have h₁ : |9 + 2 * a| < 5 := h₁
have h₂ : -7 < a := by
  linarith [abs_lt.mp h₁]
have h₃ : a < -2 := by
  linarith [abs_lt.mp h₁]
exact ⟨h₂, h₃⟩
- `mathd_algebra_410`: [P] nlinarith [sq_nonneg (x - 3)]
- `mathd_algebra_421`: [P] nlinarith [sq_nonneg (a - c), h₀, h₁, h₂, h₃, h₄]
- `mathd_algebra_433`: [P] have h₁ : ∀ (x : ℝ), f x = 3 * √(2 * x - 7) - 8 := by
  intro x
  rw [h₀] ⟶ [P] have h₂ : ∀ (x : ℝ), f x = 3 * Real.sqrt (2 * x - 7) - 8 := by
  simpa using h₀ ⟶ [P] have h₃ : f 8 = 3 * Real.sqrt (2 * 8 - 7) - 8 := by
  simpa using h₁ 8 ⟶ [P] have h₄ : (2 * 8 - 7 : ℝ) ≥ 0 := by norm_num ⟶ [P] have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₄ : 2 * 8 - 7 ≥ 0 := by nlinarith ⟶ [P] have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₄₁ : 2 * 8 - 7 ≥ 0 := by
  norm_num ⟶ [P] have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₄ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₄ : 2 * 8 - 7 ≥ 0 := by
  norm_num ⟶ [P] have h₄₁ : 2 * 8 - 7 ≥ 0 := by nlinarith ⟶ [P] have h₄₁ : 2 * 8 - 7 ≥ 0 := by
  norm_num ⟶ [P] have h₄₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₅ : Real.sqrt (2 * 8 - 7) = 3 := by
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
rw [h₅] at h₃
norm_num at h₄
norm_num at h₄ h₅
linarith
- `mathd_algebra_437`: [P] have h₄ : (x + y) ^ 3 = -45 - 101 := by
  nlinarith [sq_nonneg (x + y), sq_nonneg (x - y)] ⟶ [P] have h₅ : (x + y) ^ 3 = -146 := by
  nlinarith ⟶ [P] have h₆ : x + y = -4 := by
  nlinarith [sq_nonneg (x + y), h₀, h₁, h₂]
nlinarith
- `mathd_algebra_493`: [A] simp_all ⟶ [P] have h₁ : f 4 = 4 ^ 2 - 4 * √4 + 1 := by
  simp_all [h₀] ⟶ [A] ring_nf ⟶ [P] have h₂ : f 4 = 4 ^ 2 - 4 * √4 + 1 := by
  norm_num [h₀] ⟶ [P] have h₃ : √4 = 2 := by
  norm_num [Real.sqrt_eq_iff_sq_eq] ⟶ [A] simp ⟶ [P] have h₁ : (2 : ℝ) ≠ 0 := by norm_num ⟶ [P] have h₁ : (2 : ℝ) ≠ 0 := by norm_num ⟶ [A] ring_nf ⟶ [P] have h₁ : √4 = 2 := by rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ [P] have h₄ : √4 = 2 := by
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num ⟶ [P] have h₅ : ∀ (x : ℝ), Real.sqrt x ≥ 0 := by
  intro x
  exact Real.sqrt_nonneg x ⟶ [P] norm_num at *
nlinarith [Real.sqrt_nonneg 4, Real.sqrt_nonneg (17 - Real.sqrt 4 * 4),
  Real.sq_sqrt (show 0 ≤ 4 by norm_num),
  Real.sq_sqrt (show 0 ≤ (17 - Real.sqrt 4 * 4) by
    nlinarith [Real.sqrt_nonneg 4])]
- `mathd_algebra_536`: [P] field_simp [Nat.factorial] ⟶ [A] ring_nf ⟶ [P] have : √9 = 3 := by
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
rw [this]
norm_num
- `mathd_algebra_547`: [P] have h₂ : (5 : ℝ) ^ 3 - 2 ^ 2 = 121 := by norm_num ⟶ [P] have h : √(x ^ 3 - 2 ^ y) = 11 := by
  rw [h₀, h₁]
  rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num
exact h
- `mathd_algebra_89`: [P] field_simp [h₀]
ring ⟶ [P] have h₁ : b ≠ 0 := h₀ ⟶ [A] simp_all ⟶ [P] have h₂ : b ≠ 0 := h₁
have h₃ : b ^ 6 * 3136 = (b ^ 2 * 4) ^ 3 * 49 := by
  have h₄ : b ^ 6 * 3136 = (b ^ 6) * 3136 := by ring
  rw [h₄]
  have h₅ : (b ^ 2 * 4) ^ 3 * 49 = (b ^ 2) ^ 3 * 4 ^ 3 * 49 := by ring
  rw [h₅]
  have h₆ : (b ^ 2) ^ 3 * 4 ^ 3 * 49 = (b ^ 2 * 4) ^ 3 * 49 := by
    ring
  rw [h₆]
  ring
exact h₃
- `mathd_numbertheory_22`: [P] have h₂ : (10 * b + 6).sqrt * (10 * b + 6).sqrt = 10 * b + 6 := by
  rw [h₁] ⟶ [P] interval_cases b <;> norm_num at h₀ h₁ h₂ ⊢
- `mathd_numbertheory_326`: [P] have h₁ : n ≠ 0 := by
  intro hn
  rw [hn] at h₀
  norm_num at h₀ ⟶ [A] ring_nf ⟶ [P] have n_pos : 0 < n := by
  nlinarith [sq_nonneg (n - 1), sq_nonneg (n + 1)]
nlinarith [sq_nonneg (n - 1), sq_nonneg (n + 1)]
- `numbertheory_2dvd4expn`: [P] cases n ⟶ [A] omega ⟶ [A] omega
- `numbertheory_nckeqnm1ckpnm1ckm1`: [A] aesop ⟶ [P] cases k ⟶ [P] cases n
all_goals
  simp_all [Nat.choose_succ_succ, Nat.succ_eq_add_one] ⟶ [P] cases n
all_goals simp_all [Nat.succ_eq_add_one, Nat.choose_succ_succ, Nat.add_comm, Nat.add_left_comm, Nat.add_assoc]

## Lost against row 0

none
