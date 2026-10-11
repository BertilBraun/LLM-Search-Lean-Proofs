# Proof search: phase1_fewshot_search_qwen3.5-2b

Run `phase1_fewshot_search_qwen3.5-2b` on miniF2F-valid, git `ff395053726f7ee18aa3ea02ce0deeadcd4bf724`, config `experiments/configs/phase1_fewshot_search_qwen3.5-2b.toml` (copied as `config.toml`). Started 2026-10-11T18:26:18+00:00, 42.1 min wall, 46 CPUs, load average 54.0 at start.

**Solved 115/244 (47.1%).** Solved only with proofs of 2 or more steps: 38. Verification failures (bugs): 0. Proofs that also verify without the per-step heartbeat wrappers: 115/115. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 41 | 0.586 |
| mathd_numbertheory | 60 | 42 | 0.7 |
| amc12 | 45 | 13 | 0.289 |
| aime | 15 | 1 | 0.0667 |
| imo | 20 | 0 | 0 |
| algebra | 18 | 12 | 0.667 |
| numbertheory | 8 | 3 | 0.375 |
| induction | 8 | 3 | 0.375 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 77 | 91 | 100 | 107 | 111 | 114 | 115 |
| solve rate | 31.6% | 37.3% | 41.0% | 43.9% | 45.5% | 46.7% | 47.1% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 40 | 55 | 63 | 76 | 95 | 99 | 105 | 110 | 111 | 115 | 115 |
| solve rate | 16.4% | 22.5% | 25.8% | 31.1% | 38.9% | 40.6% | 43.0% | 45.1% | 45.5% | 47.1% | 47.1% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 62 | 77 | 92 | 99 | 107 | 109 | 111 | 114 | 115 | 115 | 115 |
| solve rate | 25.4% | 31.6% | 37.7% | 40.6% | 43.9% | 44.7% | 45.5% | 46.7% | 47.1% | 47.1% | 47.1% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 115 |
| expansion_budget | 72 |
| frontier_exhausted | 36 |
| wall_clock_budget | 21 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 25.5 | 3 | 64 | 64 | 6220 |
| nodes | 56.6 | 9.5 | 157 | 316 | 13821 |
| edges | 633 | 83 | 1664 | 1763 | 154529 |
| lean_seconds | 63.6 | 8.93 | 187 | 529 | 15523 |
| wall_seconds | 212 | 27.5 | 590 | 607 | 51752 |
| duplicates | 119 | 14 | 332 | 700 | 29001 |
| errors | 475 | 61.5 | 1270 | 1467 | 116010 |
| timeouts | 0.344 | 0 | 1 | 17 | 84 |
| repl_failures | 0.291 | 0 | 0 | 65 | 71 |
| verification_seconds | 0.787 | 0 | 1.94 | 21.6 | 192 |

solved (115 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 2.99 | 1 | 5 | 50 | 344 |
| nodes | 9.47 | 3 | 21 | 181 | 1089 |
| edges | 63.3 | 13 | 128 | 1394 | 7282 |
| lean_seconds | 7.16 | 0.778 | 14 | 159 | 824 |
| wall_seconds | 20.8 | 3.16 | 44.6 | 290 | 2396 |
| duplicates | 10.7 | 2 | 20 | 206 | 1225 |
| errors | 48.1 | 7 | 91 | 1163 | 5532 |
| timeouts | 0.0174 | 0 | 0 | 2 | 2 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 1.67 | 1.07 | 3.73 | 21.6 | 192 |

unsolved (129 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 45.6 | 64 | 64 | 64 | 5876 |
| nodes | 98.7 | 107 | 197 | 316 | 12732 |
| edges | 1141 | 1533 | 1694 | 1763 | 147247 |
| lean_seconds | 114 | 94 | 268 | 529 | 14699 |
| wall_seconds | 383 | 462 | 602 | 607 | 49356 |
| duplicates | 215 | 238 | 392 | 700 | 27776 |
| errors | 856 | 1085 | 1334 | 1467 | 110478 |
| timeouts | 0.636 | 0 | 2 | 17 | 82 |
| repl_failures | 0.55 | 0 | 0 | 65 | 71 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 74698 | 7651 | 49.3% | 0.102 | 7557 | 2637 | 62698 | 68639 | 0 | 67 | 12 | 37 | 0 |
| aesop | 5795 | 2504 | 16.1% | 0.432 | 907 | 2816 | 2072 | 2049 | 0 | 12 | 11 | 2 | 4 |
| simp_all | 6149 | 1242 | 8.0% | 0.202 | 1485 | 2190 | 2474 | 2463 | 0 | 0 | 11 | 3 | 32 |
| nlinarith | 6146 | 1191 | 7.7% | 0.194 | 9 | 710 | 5427 | 5427 | 0 | 0 | 0 | 3 | 3 |
| field_simp | 6150 | 637 | 4.1% | 0.104 | 358 | 1391 | 4401 | 4394 | 0 | 1 | 6 | 0 | 2 |
| ring_nf | 6107 | 538 | 3.5% | 0.0881 | 1201 | 4904 | 2 | 0 | 0 | 2 | 0 | 5 | 11 |
| norm_num | 6171 | 497 | 3.2% | 0.0805 | 178 | 5992 | 1 | 0 | 0 | 1 | 0 | 7 | 9 |
| linarith | 6171 | 420 | 2.7% | 0.0681 | 50 | 641 | 5480 | 5480 | 0 | 0 | 0 | 17 | 17 |
| simp | 6179 | 374 | 2.4% | 0.0605 | 797 | 672 | 4710 | 4704 | 0 | 0 | 6 | 0 | 3 |
| decide | 6220 | 129 | 0.8% | 0.0207 | 95 | 69 | 6056 | 6050 | 0 | 0 | 6 | 24 | 24 |
| rfl | 6179 | 94.4 | 0.6% | 0.0153 | 6 | 147 | 6026 | 6019 | 0 | 1 | 6 | 5 | 5 |
| constructor | 6184 | 83 | 0.5% | 0.0134 | 596 | 196 | 5392 | 5386 | 0 | 0 | 6 | 0 | 1 |
| intros | 6184 | 81.2 | 0.5% | 0.0131 | 90 | 6094 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| omega | 6196 | 70.8 | 0.5% | 0.0114 | 248 | 542 | 5406 | 5399 | 0 | 0 | 7 | 12 | 12 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 77 |
| 2 | 18 |
| 3 | 8 |
| 4 | 2 |
| 5 | 2 |
| 6 | 2 |
| 8 | 1 |
| 11 | 2 |
| 12 | 1 |
| 13 | 1 |
| 16 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | ring_nf at h₀ h₁ ⊢ ⟶ rw [h₀, h₁] ⟶ norm_num |
| amc12a_2009_p9 | simp_all ⟶ have h₂ : ∀ x, f x = a * x ^ 2 + b * x + c := h₁ ⟶ simp_all ⟶ have h₁ := h₀ 0<br>have h₂ := h₀ 1<br>have h₃ := h₀ (-1)<br>nlinarith [h₁, h₂, h₃] |
| mathd_algebra_116 | have h₂ : 2 * x ^ 2 - 13 * x = -k := by linarith ⟶ field_simp [h₀] at h₁ h₂ ⊢ ⟶ ring_nf at h₂ ⊢<br>nlinarith [Real.sqrt_nonneg 131, Real.sq_sqrt (show 0 ≤ 131 by norm_num)] |
| mathd_numbertheory_257 | have h₂ : x = 45 := by<br>  ring_nf at h₁ ⊢<br>  <;> omega ⟶ omega |
| mathd_algebra_547 | rw [h₀, h₁]<br>ring_nf ⟶ norm_num [Real.sqrt_eq_iff_sq_eq] |
| amc12_2001_p9 | simp_all ⟶ have h₂ : f 600 = f (500 * 1.2) := by<br>  norm_num at h₀ ⊢<br>  <;> simp_all [h₀]<br>  <;> ring_nf at h₀ ⊢<br>  <;> linarith<br>rw [h₂]<br>norm_num at h₁ ⊢ ⟶ field_simp ⟶ have h₁' : f 600 = f (500 * 1.2) := h₂ ⟶ simp_all ⟶ have h₂ : f 500 * 2 = 3 * 2 := by<br>  calc<br>    f 500 * 2 = f 500 * 2 := rfl<br>    _ = 3 * 2 := by rw [h₁] ⟶ norm_num ⟶ have h₃ : f (500) = 3 := h₁<br>calc<br>  f 600 * 2 = f (500 * 1.2) * 2 := by rw [h₁']<br>  _ = f 500 * 2 / 1.2 := by<br>    field_simp [h₀]<br>    <;> norm_num<br>  _ = 3 * 2 / 1.2 := by rw [h₃]<br>  _ = 5 := by norm_num |
| amc12a_2008_p8 | ring_nf ⟶ aesop ⟶ have h₁ : y ^ 3 = 1 := h₁ ⟶ have hx : 0 < x := by<br>  nlinarith [h₁, h₂, h₁]<br>have hy : 0 < y := by<br>  nlinarith [h₁, h₂, h₁] ⟶ simp_all ⟶ have h₃ : 0 < x := by linarith<br>have h₄ : 0 < y := by linarith ⟶ simp_all ⟶ have h₁' := h₂<br>have h₂' := h₁<br>have h₃' := h₄<br>have h₄' := h₃ ⟶ simp_all ⟶ have h₅ : x = Real.sqrt 2 := by<br>  have h₅₁ : x^2 = 2 := by<br>    nlinarith [h₁', h₂', h₃', h₄']<br>  have h₅₂ : 0 < 2 := by norm_num<br>  nlinarith [Real.sqrt_nonneg 2, Real.sq_sqrt (show 0 ≤ 2 by norm_num)]<br>rw [h₅] ⟶ have h₆ : x = Real.sqrt 2 := by rw [h₅]<br>have h₇ : (Real.sqrt 2) ^ 3 = Real.sqrt 2 * 2 := by<br>  simp [Real.sq_sqrt, pow_three, mul_assoc]<br>  <;> norm_num<br>  <;> field_simp [Real.sqrt_eq_iff_sq_eq]<br>  <;> norm_num<br>  <;> ring_nf<br>  <;> norm_num<br>  <;> linarith<br>exact h₇ |
| mathd_algebra_245 | simp ⟶ have h₁ : x ≠ 0 := h₀<br>field_simp [h₁] ⟶ linarith |
| mathd_algebra_28 | simp_all ⟶ have : ∃ x, 2 * x ^ 2 + 5 * x + c ≤ 0 := h₁<br>cases' this with x hx<br>have h₂ : 2 * x ^ 2 + 5 * x + c ≤ 0 := hx<br>nlinarith [sq_nonneg (x + 5/4)] |
| mathd_algebra_35 | simp_all ⟶ norm_num |
| mathd_algebra_192 | simp only [Complex.ext_iff, pow_one, mul_assoc, mul_comm, mul_left_comm] ⟶ field_simp [Complex.ext_iff]<br>ring_nf ⟶ ring_nf at * ⟶ rw [h₀, h₁, h₂] ⟶ norm_num |
| mathd_algebra_110 | simp [Complex.ext_iff] ⟶ rw [h₀, h₁] ⟶ norm_num |
| aime_1984_p15 | norm_num at h₀ h₁ h₂ h₃ ⊢ ⟶ linarith |
| mathd_algebra_433 | simp_all ⟶ have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₁ : (2 * 8 - 7) ≥ 0 := by nlinarith ⟶ have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₁ : (2 * 8 - 7) ≥ 0 := by norm_num ⟶ norm_num ⟶ have h₂ : 2 * 8 - 7 ≥ 0 := by norm_num ⟶ have h₁ : 2 * 8 - 7 ≥ 0 := by norm_num<br>nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show 0 ≤ 9 by norm_num)] |
| mathd_algebra_43 | simp_all ⟶ linarith |
| mathd_algebra_214 | rw [h₀] ⟶ have h₁ : f 4 = 4 := h₁ ⟶ have h₁ : f 4 = 4 := h₁ ⟶ have h₂ : ∀ x, f x = a * (x - 2) ^ 2 + 3 := h₀ ⟶ simp_all ⟶ linarith |
| mathd_algebra_536 | norm_num [Nat.factorial] ⟶ field_simp ⟶ nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num)] |
| mathd_algebra_22 | norm_num [logb] ⟶ have h₁ : Real.log 625 = Real.log (5^4) := by norm_num<br>have h₂ : Real.log 25 = Real.log (5^2) := by norm_num<br>rw [h₁, h₂]<br>simp [Real.log_mul, Real.log_rpow]<br>ring_nf<br>field_simp [Real.log_pow] |
| algebra_binomnegdiscrineq_10alt28asqp1 | have h : ∀ x, 10 * x ≤ 28 * x ^ 2 + 1 := by<br>  intro x<br>  nlinarith [sq_nonneg (4 * x - 1), sq_nonneg (3 * x)] ⟶ ring_nf ⟶ have h₁ : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := h ⟶ simp_all ⟶ have h₁' : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := h₁ ⟶ simp_all ⟶ have h₁' : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := by<br>  intro x<br>  nlinarith [sq_nonneg (x - 1)] ⟶ have h₁'' : ∀ (x : ℕ), 10 * x ≤ 28 * x ^ 2 + 1 := h₁' ⟶ have h : ∀ x : ℕ, 10 * x ≤ 28 * x ^ 2 + 1 := h₁' ⟶ have h : a * 10 ≤ 1 + a ^ 2 * 28 := by<br>  nlinarith [sq_nonneg (a * 10 - 1), sq_nonneg (a ^ 2 * 28 - 1)] ⟶ linarith |
| amc12_2000_p11 | field_simp [h₀, h₁] ⟶ nlinarith [sq_nonneg (a - b), h₀, h₁] |
| amc12b_2003_p9 | rw [h₀] ⟶ ring_nf ⟶ simp_all ⟶ linarith |
| algebra_2complexrootspoly_xsqp49eqxp7itxpn7i | simp [Complex.ext_iff] ⟶ constructor ⟶ cases x ⟶ ring_nf ⟶ simp [Complex.ext_iff, pow_two] at *<br><;> ring_nf<br><;> norm_num ⟶ simp [Complex.ext_iff, pow_two, Complex.ext_iff]<br><;> ring<br><;> norm_num |
| mathd_algebra_132 | simp_all ⟶ linarith |
| algebra_sqineq_36azm9asqle36zsq | simp ⟶ nlinarith [sq_nonneg (a - 2 * z)] |
| amc12a_2013_p7 | simp_all ⟶ linarith |
| mathd_numbertheory_232 | simp_all ⟶ rfl |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | have h₂ : a * c + b * c = (a + b) * c := by ring ⟶ calc<br>  a * c + b * c = (a + b) * c := by rw [h₂]<br>  _ = (2 * c) * c := by rw [h₀]<br>  _ = 2 * c ^ 2 := by ring<br>  _ = 2 * Complex.I ^ 2 := by rw [h₁]<br>  _ = 2 * (Complex.I * Complex.I) := by<br>    simp [Complex.I_mul_I]<br>    <;> ring_nf<br>    <;> norm_num<br>  _ = 2 * -1 := by<br>    norm_num<br>  _ = -2 := by ring |
| mathd_algebra_89 | simp ⟶ have h₁ : b ≠ 0 := h₀<br>field_simp [h₁] ⟶ have h_ne : b ≠ 0 := h₀<br>calc<br>  (7 * b ^ 3) ^ 2 * 64 = (7 * b ^ 3) ^ 2 * 64 := rfl<br>  _ = 49 * (4 * b ^ 2) ^ 3 := by<br>    ring_nf<br>    <;><br>    simp [pow_two, mul_assoc, mul_comm, mul_left_comm] at h₁ ⊢<br>    <;><br>    nlinarith [sq_nonneg (b - 7/4)] |
| mathd_algebra_67 | simp only [h₀, h₁] ⟶ norm_num |
| mathd_numbertheory_326 | have h₁ : (n - 1) * n * (n + 1) = 720 := h₀ ⟶ ring_nf ⟶ simp_all ⟶ ring_nf at h₁ ⊢ ⟶ have h₁ : n * (n^2 - 1) = 720 := by<br>  linarith<br>nlinarith [sq_nonneg (1 - n), sq_nonneg (n^2 - 1)] |
| numbertheory_2dvd4expn | simp_all ⟶ cases n with<br>  \| zero => simp_all [Nat.one_ne_zero]<br>  \| succ n =><br>    rw [Nat.pow_succ]<br>    simp [Nat.dvd_iff_mod_eq_zero, h₀]<br>    omega |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| mathd_algebra_251 | ring_nf at * ⟶ have h₂ : x = 2 := by<br>  field_simp [h₀] at h₁<br>  ring_nf at h₁ ⊢<br>  linarith<br>exact h₂ |
| mathd_numbertheory_412 | have h₂ : (x + 1) % 19 = 5 := by<br>  omega<br>have h₃ : (y + 5) % 19 = 12 := by<br>  omega ⟶ simp only [Int.add_emod, Int.mul_emod, Int.emod_emod, pow_two, pow_three] ⟶ simp_all |
| amc12a_2017_p2 | have h₃ : x + y = 4 * (x * y) := h₂ ⟶ have : x ≠ 0 := h₀<br>have : y ≠ 0 := h₁<br>field_simp [h₀, h₁] at * ⟶ linarith |
| induction_seq_mul2pnp1 | by_contra! n<br>by_contra! h ⟶ simp_all ⟶ by_contra! h ⟶ by_contra h_contra ⟶ by_contra h_contra ⟶ by_contra! h_contra ⟶ by_contra h ⟶ by_contra! h_contra ⟶ have h2 : u 0 = 0 := h₀<br>have h3 : ∀ (n : ℕ), u (n + 1) = 2 * u n + (n + 1) := h₁<br>have h4 : u 1 = 2 * u 0 + 1 := by<br>  apply h3<br>  <;> norm_num<br>have h5 : u 2 = 2 * u 1 + 2 := by<br>  apply h3<br>  <;> norm_num<br>have h6 : u 3 = 2 * u 2 + 3 := by<br>  apply h3<br>  <;> norm_num ⟶ aesop ⟶ apply n ⟶ ring_nf ⟶ cases n_1 with<br> \| zero =><br>    simp_all [pow_succ, mul_zero, add_zero]<br> \| succ n₁ =><br>    induction n₁ <;> simp_all [pow_succ, mul_add, add_assoc, mul_one]<br>    <;> ring_nf at *<br>    <;> omega |
| mathd_algebra_181 | simp_all ⟶ have h₂ : n ≠ 3 := h₀ ⟶ simp_all ⟶ have h₃ : n ≠ 3 := h₂ ⟶ have h₄ : n ≠ 3 := h₃ ⟶ have h₃' : n ≠ 3 := h₃ ⟶ have h₃' : n ≠ 3 := h₃ ⟶ have h₅ : (n + 5) / (n - 3) = 2 := h₁ ⟶ simp_all ⟶ have h₄ : n ≠ 3 := by<br>  intro h<br>  apply h₃'<br>  exact h ⟶ simp_all ⟶ have h₁ : n ≠ 3 := by exact h₄ ⟶ simp_all ⟶ have h₂ : n ≠ 3 := h₁ ⟶ simp_all ⟶ have h₆ : n - 3 ≠ 0 := by<br>  intro h<br>  apply h₂<br>  linarith<br>field_simp [h₆] at h₅<br>nlinarith [sq_nonneg (n - 11)] |
