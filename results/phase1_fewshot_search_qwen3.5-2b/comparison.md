# phase1_fewshot_search_qwen3.5-2b vs phase0_automation_baseline

**Solved 115/244 (47.1%) vs 79/244 (32.4%) for row 0**: 36 newly solved, 0 lost. Proofs using at least one policy step: 49. Row 0 ran 256 expansions and 300 s per theorem with 32 processes; see each run's config for its budget.

## By category

| category | problems | row 0 | this run | newly solved | lost |
|---|---|---|---|---|---|
| mathd_algebra | 70 | 28 | 41 | 13 | 0 |
| mathd_numbertheory | 60 | 38 | 42 | 4 | 0 |
| amc12 | 45 | 8 | 13 | 5 | 0 |
| aime | 15 | 0 | 1 | 1 | 0 |
| imo | 20 | 0 | 0 | 0 | 0 |
| algebra | 18 | 5 | 12 | 7 | 0 |
| numbertheory | 8 | 0 | 3 | 3 | 0 |
| induction | 8 | 0 | 3 | 3 | 0 |

## Anytime curves (solved theorems at budget)

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| row 0 | 59 | 72 | 77 | 79 | 79 | 79 | 79 |
| this run | 77 | 91 | 100 | 107 | 111 | 114 | 115 |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 | 606.708 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| row 0 | 41 | 57 | 77 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 | 79 |
| this run | 40 | 55 | 63 | 76 | 95 | 99 | 105 | 110 | 111 | 115 | 115 | 115 |

## Cost per theorem

| quantity | value |
|---|---|
| mean / median generated tokens | 34255 / 4805 |
| total generated tokens | 8,358,151 |
| generated tokens per solved theorem | 72,680 |
| mean prompt tokens (computed once per request) | 17451 |
| mean / median wall seconds | 212.1 / 27.5 |
| mean Lean seconds | 63.6 |
| mean expansions | 25.5 |

## Throughput in the search

| quantity | value |
|---|---|
| run wall minutes | 42.1 |
| policy requests / samples | 6,136 / 98,176 |
| samples/s over the policy window | 39.5 |
| generated tokens/s | 3379 |
| mean request latency s | 5.86 |
| summed request s / summed Lean s | 35,972 / 15,523 |
| distinct candidates per request | 12.3 |
| duplicate / failed sample fraction | 3.0% / 20.3% |
| prompt cache hit rate | 93.9% |
| requests without candidates (unattributed tokens) | 1 (3,870) |
| prompts too long | 4 |
| GPU utilization mean / median | 81% / 95% |
| readings at ≥ 90% utilization | 57% of 507 |
| mean power W / peak memory MiB | 318 / 23918 |

## Newly solved (P = policy step, A = automation)

- `aime_1984_p15`: [P] norm_num at h₀ h₁ h₂ h₃ ⊢ ⟶ [A] linarith
- `algebra_apb4leq8ta4pb4`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b)]
- `algebra_binomnegdiscrineq_10alt28asqp1`: [P] have h : ∀ x, 10 * x ≤ 28 * x ^ 2 + 1 := by
  intro x
  nlinarith [sq_nonneg (4 * x - 1), sq_nonneg (3 * x)] ⟶ [A] ring_nf ⟶ [P] have h₁ : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := h ⟶ [A] simp_all ⟶ [P] have h₁' : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := h₁ ⟶ [A] simp_all ⟶ [P] have h₁' : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := by
  intro x
  nlinarith [sq_nonneg (x - 1)] ⟶ [P] have h₁'' : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := h₁' ⟶ [P] have h : ∀ x : ℕ, 10 * x ≤ 28 * x ^ 2 + 1 := h₁' ⟶ [P] have h : a * 10 ≤ 1 + a ^ 2 * 28 := by
  nlinarith [sq_nonneg (a * 10 - 1), sq_nonneg (a ^ 2 * 28 - 1)] ⟶ [A] linarith
- `algebra_manipexpr_apbeq2cceqiacpbceqm2`: [P] have h₂ : a * c + b * c = (a + b) * c := by ring ⟶ [P] calc
  a * c + b * c = (a + b) * c := by rw [h₂]
  _ = (2 * c) * c := by rw [h₀]
  _ = 2 * c ^ 2 := by ring
  _ = 2 * Complex.I ^ 2 := by rw [h₁]
  _ = 2 * (Complex.I * Complex.I) := by
    simp [Complex.I_mul_I]
    <;> ring_nf
    <;> norm_num
  _ = 2 * -1 := by
    norm_num
  _ = -2 := by ring
- `algebra_sqineq_2at2pclta2c2p41pc`: [P] nlinarith [sq_nonneg (a - (2 + c)), sq_nonneg (c - 2)]
- `algebra_sqineq_2unitcircatblt1`: [P] nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), h₀]
- `algebra_sqineq_36azm9asqle36zsq`: [A] simp ⟶ [P] nlinarith [sq_nonneg (a - 2 * z)]
- `algebra_sqineq_4bap1lt4bsqpap1sq`: [P] nlinarith [sq_nonneg (a + 1 - 2 * b)]
- `amc12_2000_p11`: [P] field_simp [h₀, h₁] ⟶ [P] nlinarith [sq_nonneg (a - b), h₀, h₁]
- `amc12_2001_p9`: [A] simp_all ⟶ [P] have h₂ : f 600 = f (500 * 1.2) := by
  norm_num at h₀ ⊢
  <;> simp_all [h₀]
  <;> ring_nf at h₀ ⊢
  <;> linarith
rw [h₂]
norm_num at h₁ ⊢ ⟶ [A] field_simp ⟶ [P] have h₁' : f 600 = f (500 * 1.2) := h₂ ⟶ [A] simp_all ⟶ [P] have h₂ : f 500 * 2 = 3 * 2 := by
  calc
    f 500 * 2 = f 500 * 2 := rfl
    _ = 3 * 2 := by rw [h₁] ⟶ [A] norm_num ⟶ [P] have h₃ : f (500) = 3 := h₁
calc
  f 600 * 2 = f (500 * 1.2) * 2 := by rw [h₁']
  _ = f 500 * 2 / 1.2 := by
    field_simp [h₀]
    <;> norm_num
  _ = 3 * 2 / 1.2 := by rw [h₃]
  _ = 5 := by norm_num
- `amc12a_2008_p8`: [A] ring_nf ⟶ [A] aesop ⟶ [P] have h₁ : y ^ 3 = 1 := h₁ ⟶ [P] have hx : 0 < x := by
  nlinarith [h₁, h₂, h₁]
have hy : 0 < y := by
  nlinarith [h₁, h₂, h₁] ⟶ [A] simp_all ⟶ [P] have h₃ : 0 < x := by linarith
have h₄ : 0 < y := by linarith ⟶ [A] simp_all ⟶ [P] have h₁' := h₂
have h₂' := h₁
have h₃' := h₄
have h₄' := h₃ ⟶ [A] simp_all ⟶ [P] have h₅ : x = Real.sqrt 2 := by
  have h₅₁ : x^2 = 2 := by
    nlinarith [h₁', h₂', h₃', h₄']
  have h₅₂ : 0 < 2 := by norm_num
  nlinarith [Real.sqrt_nonneg 2, Real.sq_sqrt (show 0 ≤ 2 by norm_num)]
rw [h₅] ⟶ [P] have h₆ : x = Real.sqrt 2 := by rw [h₅]
have h₇ : (Real.sqrt 2) ^ 3 = Real.sqrt 2 * 2 := by
  simp [Real.sq_sqrt, pow_three, mul_assoc]
  <;> norm_num
  <;> field_simp [Real.sqrt_eq_iff_sq_eq]
  <;> norm_num
  <;> ring_nf
  <;> norm_num
  <;> linarith
exact h₇
- `amc12a_2009_p5`: [P] nlinarith [sq_nonneg (x^2 - 5), h₀]
- `amc12a_2009_p9`: [A] simp_all ⟶ [P] have h₂ : ∀ x, f x = a * x ^ 2 + b * x + c := h₁ ⟶ [A] simp_all ⟶ [P] have h₁ := h₀ 0
have h₂ := h₀ 1
have h₃ := h₀ (-1)
nlinarith [h₁, h₂, h₃]
- `induction_seq_mul2pnp1`: [P] by_contra! n
by_contra! h ⟶ [A] simp_all ⟶ [P] by_contra! h ⟶ [P] by_contra h_contra ⟶ [P] by_contra h_contra ⟶ [P] by_contra! h_contra ⟶ [P] by_contra h ⟶ [P] by_contra! h_contra ⟶ [P] have h2 : u 0 = 0 := h₀
have h3 : ∀ (n : ℕ), u (n + 1) = 2 * u n + (n + 1) := h₁
have h4 : u 1 = 2 * u 0 + 1 := by
  apply h3
  <;> norm_num
have h5 : u 2 = 2 * u 1 + 2 := by
  apply h3
  <;> norm_num
have h6 : u 3 = 2 * u 2 + 3 := by
  apply h3
  <;> norm_num ⟶ [A] aesop ⟶ [P] apply n ⟶ [A] ring_nf ⟶ [P] cases n_1 with
 | zero =>
    simp_all [pow_succ, mul_zero, add_zero]
 | succ n₁ =>
    induction n₁ <;> simp_all [pow_succ, mul_add, add_assoc, mul_one]
    <;> ring_nf at *
    <;> omega
- `induction_sum2kp1npqsqm1`: [P] induction n with
  | zero => simp [Finset.sum_range_zero]
  | succ n ih =>
    simp_all [Finset.sum_range_succ, pow_succ, Nat.cast_add, Nat.cast_one]
    <;> ring_nf at *
    <;> omega
- `induction_sum_1oktkp1`: [P] induction n with
| zero => norm_num
| succ n ih =>
  simp_all [Finset.sum_range_succ, Nat.cast_add, Nat.cast_one]
  <;> ring_nf
  <;> field_simp
  <;> ring_nf
  <;> norm_num
  <;> linarith
- `mathd_algebra_116`: [P] have h₂ : 2 * x ^ 2 - 13 * x = -k := by linarith ⟶ [P] field_simp [h₀] at h₁ h₂ ⊢ ⟶ [P] ring_nf at h₂ ⊢
nlinarith [Real.sqrt_nonneg 131, Real.sq_sqrt (show 0 ≤ 131 by norm_num)]
- `mathd_algebra_181`: [A] simp_all ⟶ [P] have h₂ : n ≠ 3 := h₀ ⟶ [A] simp_all ⟶ [P] have h₃ : n ≠ 3 := h₂ ⟶ [P] have h₄ : n ≠ 3 := h₃ ⟶ [P] have h₃' : n ≠ 3 := h₃ ⟶ [P] have h₃' : n ≠ 3 := h₃ ⟶ [P] have h₅ : (n + 5) / (n - 3) = 2 := h₁ ⟶ [A] simp_all ⟶ [P] have h₄ : n ≠ 3 := by
  intro h
  apply h₃'
  exact h ⟶ [A] simp_all ⟶ [P] have h₁ : n ≠ 3 := by exact h₄ ⟶ [A] simp_all ⟶ [P] have h₂ : n ≠ 3 := h₁ ⟶ [A] simp_all ⟶ [P] have h₆ : n - 3 ≠ 0 := by
  intro h
  apply h₂
  linarith
field_simp [h₆] at h₅
nlinarith [sq_nonneg (n - 11)]
- `mathd_algebra_192`: [P] simp only [Complex.ext_iff, pow_one, mul_assoc, mul_comm, mul_left_comm] ⟶ [P] field_simp [Complex.ext_iff]
ring_nf ⟶ [P] ring_nf at * ⟶ [P] rw [h₀, h₁, h₂] ⟶ [A] norm_num
- `mathd_algebra_22`: [P] norm_num [logb] ⟶ [P] have h₁ : Real.log 625 = Real.log (5^4) := by norm_num
have h₂ : Real.log 25 = Real.log (5^2) := by norm_num
rw [h₁, h₂]
simp [Real.log_mul, Real.log_rpow]
ring_nf
field_simp [Real.log_pow]
- `mathd_algebra_234`: [P] nlinarith [sq_nonneg (d - 1), sq_nonneg (d - 9 / 25), h₀, h₀]
- `mathd_algebra_251`: [P] ring_nf at * ⟶ [P] have h₂ : x = 2 := by
  field_simp [h₀] at h₁
  ring_nf at h₁ ⊢
  linarith
exact h₂
- `mathd_algebra_28`: [A] simp_all ⟶ [P] have : ∃ x, 2 * x ^ 2 + 5 * x + c ≤ 0 := h₁
cases' this with x hx
have h₂ : 2 * x ^ 2 + 5 * x + c ≤ 0 := hx
nlinarith [sq_nonneg (x + 5/4)]
- `mathd_algebra_410`: [P] nlinarith [sq_nonneg (x - 3), h₀]
- `mathd_algebra_421`: [P] nlinarith [sq_nonneg (a - c), h₄, h₂]
- `mathd_algebra_433`: [A] simp_all ⟶ [P] have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₁ : (2 * 8 - 7) ≥ 0 := by nlinarith ⟶ [P] have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₁ : (2 * 8 - 7) ≥ 0 := by norm_num ⟶ [A] norm_num ⟶ [P] have h₂ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ [P] have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num
nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show 0 ≤ 9 by norm_num)]
- `mathd_algebra_536`: [P] norm_num [Nat.factorial] ⟶ [A] field_simp ⟶ [P] nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num)]
- `mathd_algebra_547`: [P] rw [h₀, h₁]
ring_nf ⟶ [P] norm_num [Real.sqrt_eq_iff_sq_eq]
- `mathd_algebra_89`: [A] simp ⟶ [P] have h₁ : b ≠ 0 := h₀
field_simp [h₁] ⟶ [P] have h_ne : b ≠ 0 := h₀
calc
  (7 * b ^ 3) ^ 2 * 64 = (7 * b ^ 3) ^ 2 * 64 := rfl
  _ = 49 * (4 * b ^ 2) ^ 3 := by
    ring_nf
    <;>
    simp [pow_two, mul_assoc, mul_comm, mul_left_comm] at h₁ ⊢
    <;>
    nlinarith [sq_nonneg (b - 7/4)]
- `mathd_numbertheory_257`: [P] have h₂ : x = 45 := by
  ring_nf at h₁ ⊢
  <;> omega ⟶ [A] omega
- `mathd_numbertheory_326`: [P] have h₁ : (n - 1) * n * (n + 1) = 720 := h₀ ⟶ [A] ring_nf ⟶ [A] simp_all ⟶ [P] ring_nf at h₁ ⊢ ⟶ [P] have h₁ : n * (n^2 - 1) = 720 := by
  linarith
nlinarith [sq_nonneg (1 - n), sq_nonneg (n^2 - 1)]
- `mathd_numbertheory_412`: [P] have h₂ : (x + 1) % 19 = 5 := by
  omega
have h₃ : (y + 5) % 19 = 12 := by
  omega ⟶ [P] simp only [Int.add_emod, Int.mul_emod, Int.emod_emod, pow_two, pow_three] ⟶ [A] simp_all
- `mathd_numbertheory_84`: [P] norm_num [Int.floor_eq_iff]
- `numbertheory_2dvd4expn`: [A] simp_all ⟶ [P] cases n with
  | zero => simp_all [Nat.one_ne_zero]
  | succ n =>
    rw [Nat.pow_succ]
    simp [Nat.dvd_iff_mod_eq_zero, h₀]
    omega
- `numbertheory_nckeqnm1ckpnm1ckm1`: [P] cases n with
  | zero =>
    simp_all [Nat.choose]
  | succ n =>
    cases k with
    | zero =>
      simp_all [Nat.choose]
    | succ m =>
      simp_all [Nat.choose, Nat.succ_eq_add_one]
      <;> ring_nf
      <;> norm_num
      <;> simp_all [Nat.choose, Nat.succ_eq_add_one]
- `numbertheory_sqmod4in01d`: [P] have h : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by omega
rcases h with (h | h | h | h) <;>
  simp [h, pow_two, Int.mul_emod, Int.emod_emod]
<;>
  cases' h with h <;>
    cases' h with h <;>
      simp [h, pow_two, Int.mul_emod, Int.emod_emod]
<;>
  rw [← sub_eq_zero] <;>
  simp [Int.add_assoc, Int.add_comm, Int.add_left_comm, Int.mul_assoc, Int.mul_comm, Int.mul_left_comm]

## Lost against row 0

none
