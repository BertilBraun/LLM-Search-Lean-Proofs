# Proof search: perf_full_merged_pair_sweep7_limit5

Run `perf_full_merged_pair_sweep7_limit5` on miniF2F-valid, git `45a2f9bfedb9ee38b74715dc0d775f515d668b87`, config `/workspace/runs/perf/configs/merged_pair_sweep7_limit5.toml` (copied as `config.toml`). Started 2026-10-12T15:13:55+00:00, 11.8 min wall, 46 CPUs, load average 33.7 at start.

**Solved 153/244 (62.7%).** Solved only with proofs of 2 or more steps: 64. Verification failures (bugs): 1. Proofs that also verify without the per-step heartbeat wrappers: 153/153. Statements that failed to start: 0.

## By category

| category | problems | solved | solve rate |
|---|---|---|---|
| mathd_algebra | 70 | 54 | 0.771 |
| mathd_numbertheory | 60 | 49 | 0.817 |
| amc12 | 45 | 21 | 0.467 |
| aime | 15 | 2 | 0.133 |
| imo | 20 | 1 | 0.05 |
| algebra | 18 | 15 | 0.833 |
| numbertheory | 8 | 4 | 0.5 |
| induction | 8 | 7 | 0.875 |

## Anytime curves

A theorem counts as solved at budget b if its proof was found after spending at most b in that unit (per theorem). Wall seconds were measured under the run's concurrency.

| expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| solved | 89 | 117 | 127 | 140 | 146 | 150 | 153 |
| solve rate | 36.5% | 48.0% | 52.0% | 57.4% | 59.8% | 61.5% | 62.7% |

| wall_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 23 | 42 | 58 | 81 | 105 | 117 | 130 | 145 | 145 | 147 | 153 |
| solve rate | 9.4% | 17.2% | 23.8% | 33.2% | 43.0% | 48.0% | 53.3% | 59.4% | 59.4% | 60.2% | 62.7% |

| lean_seconds ≤ | 1 | 2 | 5 | 10 | 20 | 30 | 60 | 120 | 180 | 300 | 600 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| solved | 62 | 85 | 114 | 123 | 129 | 135 | 145 | 146 | 146 | 149 | 153 |
| solve rate | 25.4% | 34.8% | 46.7% | 50.4% | 52.9% | 55.3% | 59.4% | 59.8% | 59.8% | 61.1% | 62.7% |

## Stop reasons

| stop reason | problems |
|---|---|
| proved | 153 |
| expansion_budget | 54 |
| wall_clock_budget | 33 |
| frontier_exhausted | 4 |

## Cost per theorem

all (244 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 20.7 | 3 | 64 | 64 | 5043 |
| nodes | 77 | 12 | 246 | 390 | 18798 |
| edges | 351 | 47.5 | 1132 | 1314 | 85685 |
| lean_seconds | 157 | 8.62 | 532 | 603 | 38391 |
| wall_seconds | 205 | 37.2 | 601 | 609 | 49938 |
| duplicates | 70.4 | 6.5 | 235 | 368 | 17175 |
| errors | 187 | 22 | 607 | 817 | 45565 |
| timeouts | 4.14 | 0 | 16 | 44 | 1011 |
| repl_failures | 0.0041 | 0 | 0 | 1 | 1 |
| verification_seconds | 1.46 | 0.587 | 4 | 20.9 | 357 |

solved (153 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 3.56 | 1 | 7 | 46 | 544 |
| nodes | 13.3 | 5 | 26 | 191 | 2037 |
| edges | 51.4 | 12 | 118 | 798 | 7869 |
| lean_seconds | 23.5 | 1.62 | 39.1 | 502 | 3594 |
| wall_seconds | 40.8 | 12 | 78.1 | 557 | 6242 |
| duplicates | 8.49 | 1 | 19 | 154 | 1299 |
| errors | 28.5 | 6 | 60 | 527 | 4359 |
| timeouts | 0.484 | 0 | 0 | 21 | 74 |
| repl_failures | 0 | 0 | 0 | 0 | 0 |
| verification_seconds | 2.33 | 1.36 | 5.82 | 20.9 | 357 |

unsolved (91 theorems):

| quantity | mean | median | p90 | max | total |
|---|---|---|---|---|---|
| expansions | 49.4 | 64 | 64 | 64 | 4499 |
| nodes | 184 | 188 | 301 | 390 | 16761 |
| edges | 855 | 985 | 1229 | 1314 | 77816 |
| lean_seconds | 382 | 406 | 570 | 603 | 34797 |
| wall_seconds | 480 | 531 | 606 | 609 | 43696 |
| duplicates | 174 | 184 | 283 | 368 | 15876 |
| errors | 453 | 506 | 675 | 817 | 41206 |
| timeouts | 10.3 | 4 | 31 | 44 | 937 |
| repl_failures | 0.011 | 0 | 0 | 1 | 1 |
| verification_seconds | 0 | 0 | 0 | 0 | 0 |

## Compute by step

Lean seconds per step text over all searches (policy steps pooled). Failures = no tactic applied; closing = the step produced a proof that verified or not; on proof paths = steps of found proofs; REPL failures (crash, failed replay) are infrastructure, not the step's fault.

| step | attempts | Lean s | share | mean s | children | duplicates | failures | errors | heartbeat timeouts | wall-clock timeouts | REPL failures | closing | on proof paths |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| <policy> | 50842 | 30688 | 80.0% | 0.604 | 14412 | 10975 | 22075 | 21074 | 0 | 1002 | 0 | 64 | 0 |
| simp_all | 4905 | 2693 | 7.0% | 0.549 | 1329 | 1789 | 1787 | 1784 | 0 | 3 | 0 | 9 | 23 |
| nlinarith | 4929 | 1624 | 4.2% | 0.33 | 27 | 34 | 4868 | 4866 | 0 | 2 | 0 | 23 | 23 |
| omega | 5043 | 1140 | 3.0% | 0.226 | 64 | 13 | 4966 | 4966 | 0 | 0 | 0 | 30 | 30 |
| field_simp | 4992 | 924 | 2.4% | 0.185 | 854 | 482 | 3656 | 3656 | 0 | 0 | 0 | 0 | 3 |
| ring_nf | 4988 | 823 | 2.1% | 0.165 | 1211 | 3776 | 1 | 0 | 0 | 1 | 0 | 9 | 10 |
| rfl | 4974 | 237 | 0.6% | 0.0477 | 5 | 40 | 4929 | 4927 | 0 | 2 | 0 | 5 | 5 |
| constructor | 5012 | 234 | 0.6% | 0.0468 | 652 | 66 | 4294 | 4292 | 0 | 1 | 1 | 14 | 21 |

## Proof depths

| steps | solved |
|---|---|
| 1 | 89 |
| 2 | 34 |
| 3 | 22 |
| 4 | 7 |
| 5 | 1 |

Proofs with 2 or more steps:

| problem | steps |
|---|---|
| mathd_algebra_48 | simp_all ⟶ ring_nf |
| mathd_algebra_43 | simp only [h₀, h₁, h₂] at * ⟶ nlinarith |
| mathd_algebra_116 | have h₂ : k = 19 / 4 := by<br>  rw [eq_comm] at h₀<br>  rw [sq] at h₁<br>  ring_nf at h₁ ⊢<br>  nlinarith [sq_sqrt (show (0 : ℝ) ≤ 131 by norm_num)] ⟶ simp_all |
| mathd_algebra_214 | simp only [h₀, h₁, sub_eq_add_neg, add_assoc] at * ⟶ nlinarith |
| amc12b_2003_p9 | simp only [h₀, h₁, h₀] at * ⟶ nlinarith |
| mathd_algebra_547 | simp_all ⟶ rw [Real.sqrt_eq_iff_sq_eq] <;> norm_num |
| mathd_algebra_110 | simp_all ⟶ ring<br><;> simp [Complex.ext_iff]<br><;> ring<br><;> simp [Complex.ext_iff]<br><;> ring |
| mathd_algebra_35 | simp_all ⟶ ring_nf |
| mathd_algebra_132 | simp [h₀, h₁, h₂] at * ⟶ nlinarith |
| induction_divisibility_3divnto3m2n | have : n % 3 = 0 ∨ n % 3 = 1 ∨ n % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, Nat.dvd_iff_mod_eq_zero, Nat.pow_succ, Nat.mul_mod, Nat.add_mod]<br><;><br>omega |
| numbertheory_sqmod4in01d | have : (a^2) % 4 = 0 ∨ (a^2) % 4 = 1 := by<br>  have : a % 4 = 0 ∨ a % 4 = 1 ∨ a % 4 = 2 ∨ a % 4 = 3 := by<br>    omega<br>  rcases this with (h \| h \| h \| h) <;><br>    simp [h, pow_two, Int.mul_emod, Int.add_emod] ⟶ omega |
| numbertheory_sqmod3in01d | have : a % 3 = 0 ∨ a % 3 = 1 ∨ a % 3 = 2 := by omega ⟶ rcases this with (h \| h \| h) <;><br>simp [h, pow_two, Int.mul_emod, Int.add_emod] |
| mathd_numbertheory_232 | simp only [h₀, h₁, h₂] at * ⟶ rfl |
| amc12a_2013_p8 | field_simp at h₃ ⟶ have h₄ : x * y = 2 := by<br>  have h₄ : x * y = 2 := by<br>    apply mul_left_cancel₀ (sub_ne_zero.mpr h₂)<br>    nlinarith<br>  exact h₄ ⟶ simp_all |
| mathd_algebra_536 | have h_main : (3! * (2^3 + Real.sqrt 9)) / 2 = 33 := by<br>  have h₁ : Real.sqrt 9 = 3 := by<br>    rw [Real.sqrt_eq_iff_sq_eq (by positivity) (by norm_num)]<br>    nlinarith<br>  have h₂ : (3! : ℝ) = 6 := by<br>    norm_num [Nat.factorial]<br>    <;> simp_all [Nat.factorial]<br>    <;> norm_num<br>  rw [h₁, h₂]<br>  norm_num<br>  <;><br>  ring_nf at *<br>  <;><br>  norm_num<br>  <;><br>  linarith ⟶ simp_all |
| mathd_algebra_159 | simp [h₀, h₁] at * ⟶ nlinarith |
| mathd_algebra_73 | apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁) ⟶ linear_combination h₀ |
| mathd_algebra_11 | field_simp [sub_ne_zero.mpr h₀, sub_ne_zero.mpr h₁] at h₂ ⊢ ⟶ nlinarith |
| mathd_numbertheory_780 | rcases h₁ with ⟨h₁_left, h₁_right⟩ ⟶ interval_cases m <;> omega |
| mathd_numbertheory_22 | have h₂ : b = 3 ∨ b = 1 := by<br>  have h₃ : b = 3 ∨ b = 1 := by<br>    have h₄ : b < 10 := h₀<br>    have h₅ : (10 * b + 6).sqrt * (10 * b + 6).sqrt = 10 * b + 6 := h₁<br>    have h₆ : b = 3 ∨ b = 1 := by<br>      interval_cases b <;> norm_num at h₅ ⊢ <;> try contradiction <;> try nlinarith [Real.sq_sqrt (by norm_num : (0 : ℝ) ≤ 10 * b + 6)]<br>    exact h₆<br>  exact h₃ ⟶ omega |
| mathd_numbertheory_109 | simp only [h₀, Finset.sum_eq_multiset_sum, Finset.Icc, Finset.mem_Icc, Finset.mem_range] ⟶ constructor |
| mathd_algebra_28 | simp_all ⟶ obtain ⟨x, hx⟩ := h₁ ⟶ nlinarith [sq_nonneg (x + 5 / 4)] |
| amc12a_2009_p9 | have h₂ := h₀ (-3) ⟶ simp_all ⟶ linarith [h₀ 0, h₀ 1] |
| induction_divisibility_9div10tonm1 | have h1 : (10 : ℕ) ^ n % 9 = 1 := by<br>  induction' h₀ with k hk<br>  all_goals simp_all [Nat.pow_succ, Nat.mul_mod] ⟶ omega |
| amc12_2000_p11 | field_simp [h₀.1, h₀.2, mul_comm] at h₁ ⊢ ⟶ nlinarith [sq_nonneg (a - b), sq_nonneg (a + b), h₁, h₀] |
| mathd_algebra_140 | have h₂ := h₁ 0 ⟶ simp_all ⟶ linarith [h₁ 0, h₁ 1, h₁ 2] |
| mathd_algebra_13 | constructor ⟶ {<br>  have h₁ := h₀ 1<br>  have h₂ := h₀ 2<br>  have h₃ := h₀ 3<br>  have h₄ := h₀ 4<br>  have h₅ := h₀ 5<br>  have h₆ := h₀ 6<br>  have h₇ := h₀ 7<br>  have h₈ := h₀ 8<br>  have h₉ := h₀ 9<br>  have h₁₀ := h₀ 10<br>  norm_num at h₁ h₂ h₃ h₄ h₅ h₆ h₇ h₈ h₉ h₁₀<br>  <;> linarith<br>} ⟶ case right =><br>  have h₁ := h₀ 6<br>  norm_num [h₀, h₁] at h₁<br>  have h₂ := h₀ 7<br>  norm_num [h₀, h₂] at h₂<br>  linarith |
| mathd_algebra_22 | simp [Real.logb, show (5 : ℝ) ≠ 0 by norm_num, show (5 : ℝ) ≠ 1 by norm_num] ⟶ field_simp<br><;> ring_nf<br><;> norm_num<br><;> linarith |
| amc12a_2015_p10 | have h₃ : y ≤ x - 1 := by linarith ⟶ have h₄ : y ≤ 25 := by<br>  nlinarith ⟶ interval_cases y <;> omega |
| mathd_numbertheory_64 | constructor ⟶ constructor ⟶ ·<br>  intro x hx<br>  simp_all [Nat.ModEq]<br>  omega |
| mathd_algebra_267 | field_simp [h₀, h₁, sub_eq_zero, add_eq_zero_iff_eq_neg] at h₂ ⟶ nlinarith |
| mathd_algebra_433 | simp_all ⟶ ring_nf ⟶ nlinarith [Real.sqrt_nonneg 9, Real.sq_sqrt (show (0 : ℝ) ≤ 9 by norm_num)] |
| algebra_manipexpr_apbeq2cceqiacpbceqm2 | simp_all only [h₁, Complex.ext_iff, mul_sub, mul_one, mul_add, mul_comm, mul_left_comm,<br>  mul_right_comm] ⟶ simp_all ⟶ nlinarith |
| mathd_numbertheory_668 | simp_all ⟶ rfl |
| mathd_algebra_251 | have : x = 2 := by<br>  field_simp at h₁<br>  linarith ⟶ simp_all |
| mathd_algebra_181 | field_simp [sub_ne_zero.mpr h₀] at h₁ ⟶ nlinarith |
| algebra_amgm_faxinrrp2msqrt2geq2mxm1div2x | intro x hx ⟶ field_simp [pow_two, mul_comm] ⟶ rw [div_le_iff (by positivity)] ⟶ nlinarith [sq_sqrt (show 0 ≤ 2 by norm_num), sq_nonneg (x - 1), sq_nonneg (x - Real.sqrt 2 / 2)] |
| amc12a_2017_p2 | field_simp [h₀, h₁, mul_comm] at h₂ ⊢ ⟶ nlinarith |
| mathd_numbertheory_257 | simp_all [Finset.sum_range_succ, Nat.dvd_iff_mod_eq_zero] ⟶ omega |
| mathd_numbertheory_326 | have h₁ : n^3 - n = 720 := by<br>  linarith ⟶ nlinarith [h₀, h₁, sq_nonneg (n - 1), sq_nonneg (n + 1), sq_nonneg (n^2 - 1)] |
| mathd_algebra_480 | simp_all ⟶ have h₃ : f (Real.pi) = 2 := by<br>  have h₃₁ : 0 ≤ Real.pi := by linarith [Real.pi_pos]<br>  have h₃₂ : Real.pi < 4 := by<br>    have := Real.pi_gt_31415<br>    have := Real.pi_lt_31416<br>    norm_num [Real.pi_gt_31415, Real.pi_lt_31416] at *<br>    <;> linarith<br>  have h₃₃ : f (Real.pi) = 2 := by<br>    have h₃₄ := h₁ (Real.pi) h₃₁ h₃₂<br>    exact h₃₄<br>  exact h₃₃ ⟶ simp_all |
| algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4 | have h₂ : e = 11 := by<br>  simp [Complex.ext_iff] at h₀ h₁ ⊢<br>  constructor <;><br>  (try simp_all) <;><br>  (try linarith) <;><br>  (try ring_nf at *) <;><br>  (try norm_num at *) <;><br>  (try linarith) <;><br>  (try<br>    {<br>      simp_all [Complex.ext_iff]<br>      <;><br>      norm_num<br>      <;><br>      linarith<br>    }) ⟶ have h₃ : x = -4 := by<br>  rw [h₂] at h₀<br>  linear_combination h₀ ⟶ simp_all |
| mathd_algebra_77 | constructor ⟶ all_goals<br>  simp_all only [h₂, zero_add, mul_zero, zero_mul, mul_one, one_mul, add_zero]<br>  apply mul_left_cancel₀ (sub_ne_zero_of_ne h₁)<br>  ring_nf<br>  nlinarith |
| amc12b_2002_p6 | constructor ⟶ case left =><br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  have h₅ := h₁ 2<br>  have h₆ := h₁ (-2)<br>  field_simp [h₀.1, h₀.2] at h₂ h₃ h₄ h₅ h₆<br>  ring_nf at h₂ h₃ h₄ h₅ h₆<br>  nlinarith ⟶ case right =><br>  have h₂ := h₁ 0<br>  have h₃ := h₁ 1<br>  have h₄ := h₁ (-1)<br>  ring_nf at h₂ h₃ h₄<br>  nlinarith [sq_pos_of_ne_zero h₀.1, sq_pos_of_ne_zero h₀.2] |
| mathd_numbertheory_32 | rw [Finset.sum_eq_multiset_sum] ⟶ have h₁ : S = Finset.filter (fun k => k ∣ 36) (Finset.range 37) := by<br>  ext n<br>  simp [h₀]<br>  all_goals tauto ⟶ simp [h₀, h₁, Nat.dvd_iff_mod_eq_zero, Finset.filter_eq, Finset.mem_range, Finset.mem_filter, Finset.mem_singleton] ⟶ constructor |
| amc12_2001_p9 | have h₂ := h₀ 500 (by norm_num) 600 (by norm_num) ⟶ have h₃ := h₀ 600 (by norm_num) 500 (by norm_num) ⟶ norm_num at h₂ h₃<br><;> linarith |
| amc12b_2020_p5 | field_simp at h₀ h₁ ⟶ ring_nf at h₀ h₁ ⟶ norm_cast at h₀ h₁ ⟶ omega |
| mathd_numbertheory_35 | have h₁ := h₀ 0 ⟶ have h₂ := h₀ 196 ⟶ norm_num [Finset.sum_eq_multiset_sum] at h₀ h₁ h₂ |
| mathd_algebra_151 | have h₁ : ⌈Real.sqrt 27⌉ = 6 := by<br>  rw [Int.ceil_eq_iff] <;><br>  norm_num [Real.sqrt_le_iff, Real.lt_sqrt] <;><br>  norm_num ⟶ have h₂ : Int.floor (Real.sqrt 26) = 5 := by<br>  rw [Int.floor_eq_iff]<br>  constructor <;> norm_num <;><br>  nlinarith [Real.sqrt_nonneg 26, Real.sq_sqrt (by norm_num : (0 : ℝ) ≤ 26),<br>    Real.sqrt_nonneg 27, Real.sq_sqrt (by norm_num : (0 : ℝ) ≤ 27)] ⟶ omega |
| amc12a_2003_p1 | simp_all ⟶ rfl |
| mathd_algebra_206 | rw [h₀] at h₂ h₃ ⟶ nlinarith [h₂, h₃, sq_pos_of_ne_zero (sub_ne_zero_of_ne h₁)] |
| mathd_algebra_89 | field_simp [h₀, mul_comm] ⟶ ring_nf<br><;> simp_all [pow_two, pow_three, mul_assoc]<br><;> ring_nf<br><;> norm_cast<br><;> linarith |
| mathd_algebra_437 | norm_cast at * ⟶ simp_all ⟶ nlinarith [pow_two (x - y), pow_two (x + y)] |
| induction_seq_mul2pnp1 | induction' n with n hn ⟶ all_goals simp_all [Nat.pow_succ, Nat.mul_add, Nat.add_mul, Nat.mul_one, Nat.mul_zero, Nat.add_zero] ⟶ cases n with<br>\| zero =><br>  simp_all [Nat.succ_eq_add_one]<br>\| succ n =><br>  cases n with<br>  \| zero =><br>    simp_all [Nat.succ_eq_add_one]<br>  \| succ n =><br>    simp_all [Nat.succ_eq_add_one]<br>    all_goals ring<br>    all_goals omega |
| imo_1964_p1_2 | rw [Nat.dvd_iff_mod_eq_zero] ⟶ have h : 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 ∨ 2^n % 7 = 1 := by<br>  have h1 : 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 ∨ 2^n % 7 = 1 := by<br>    have h2 : ∀ n, 2^n % 7 = 1 ∨ 2^n % 7 = 2 ∨ 2^n % 7 = 4 ∨ 2^n % 7 = 1 := by<br>      intro n<br>      induction n with<br>      \| zero =><br>        simp [pow_zero]<br>      \| succ n ih =><br>        rcases ih with (h \| h \| h \| h) <;><br>        simp [pow_succ, Nat.mul_mod, h]<br>    exact h2 n<br>  exact h1 ⟶ omega |
| mathd_numbertheory_629 | constructor ⟶ ·<br>  constructor<br>  ·<br>    norm_num<br>  ·<br>    norm_num [Nat.lcm] ⟶ ·<br>  intro t ht<br>  rcases ht with ⟨ht1, ht2⟩<br>  by_contra h₁<br>  have h₂ : t ≤ 18 := by linarith<br>  interval_cases t <;> norm_num [Nat.lcm] at ht2 <;> omega |
| amc12b_2003_p17 | field_simp ⟶ rcases h₀ with ⟨h₀x, h₀y⟩ ⟶ field_simp [Real.log_mul, Real.log_inv, Real.log_rpow] at h₁ h₂ ⊢ ⟶ nlinarith |
| mathd_numbertheory_690 | constructor ⟶ field_simp ⟶ all_goals norm_num [Nat.ModEq] ⟶ ·<br>  intro a h<br>  by_contra h'<br>  push_neg at h'<br>  have h₁ : 0 < a := h.1<br>  have h₂ : a % 3 = 2 := h.2.1<br>  have h₃ : a % 5 = 4 := h.2.2.1<br>  have h₄ : a % 7 = 6 := h.2.2.2.1<br>  have h₅ : a % 9 = 8 := h.2.2.2.2<br>  interval_cases a <;> omega |
| mathd_algebra_323 | field_simp ⟶ have := h 3 ⟶ norm_num at this ⟶ have : σ.symm 19 = 3 := by<br>  simp_all [eq_comm] ⟶ simp_all |
| amc12a_2016_p3 | have h₁ := h₀ (3 / 8) (-(2 / 5)) (by norm_num) ⟶ have h₂ : ⌊(3 / 8 : ℝ) / (-(2 / 5 : ℝ))⌋ = -1 := by<br>  norm_num [Int.floor_eq_iff, Int.ofNat]<br>  <;> norm_num<br>  <;><br>  (try ring_nf at *)<br>  <;><br>  (try norm_num)<br>  <;><br>  (try linarith)<br>  <;><br>  (try norm_num)<br>  <;><br>  (try ring_nf)<br>  <;><br>  (try norm_num)<br>  <;><br>  (try linarith) ⟶ simp_all<br><;> norm_num<br><;> linarith |
| mathd_algebra_421 | simp_all ⟶ norm_num at h₀ h₁ h₂ h₃ ⟶ nlinarith [sq_nonneg (a - c)] |
| algebra_xmysqpymzsqpzmxsqeqxyz_xpypzp6dvdx3y3z3 | rw [add_assoc] ⟶ use (x^2 + y^2 + z^2 - x*y - y*z - z*x) ⟶ nlinarith |
| amc12a_2008_p8 | have h₃ : y = 1 := by<br>  nlinarith [pow_two_nonneg (y - 1), pow_two_nonneg (y + 1)] ⟶ rw [h₃] at h₂ ⟶ have h₄ : x = Real.sqrt 2 := by<br>  nlinarith [Real.sqrt_pos.mpr (by linarith : (0 : ℝ) < 2), Real.sq_sqrt (show (0 : ℝ) ≤ 2 by linarith)] ⟶ nlinarith |
| aime_1983_p9 | rw [le_div_iff (by nlinarith [Real.sin_pos_of_pos_of_lt_pi h₀.1 h₀.2, Real.sin_le_one x, Real.sin_le_one x])] ⟶ have h₁ : 0 ≤ Real.sin x * Real.sin x := by nlinarith [Real.sin_sq_add_cos_sq x] ⟶ have h₂ : 0 ≤ Real.sin x ^ 2 := by nlinarith [Real.sin_sq_le_one x] ⟶ nlinarith [sq_nonneg (x * Real.sin x - 2 / 3)] |
