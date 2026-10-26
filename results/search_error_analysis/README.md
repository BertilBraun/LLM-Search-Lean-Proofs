# Search-tree error analysis: failed edges, "no progress" duplicates, wasted Lean time

Offline analysis of recorded search trees (no Lean run). Main run: `phase5_expansions_visible_student` (4B visible
student, n = 16, 64 expansions, 7-tactic sweep `omega constructor rfl field_simp ring_nf simp_all nlinarith`, 10 s
wall clock per tactic, default 200k heartbeats), 244 miniF2F-valid trees, 171 solved. Comparisons: visible student
v2 (166), the same v1 model without explanations (157), round-2 student thinking (160) / non-thinking (154), 2B SFT v2
A* (157, 13-tactic sweep). The analysis scripts were one-off and are not in the repository.

**Method.** Every edge is classified by the first line of its Lean message (Lean reports errors in source order),
normalized and matched against ~40 rules, then grouped into tiers: (1) malformed Lean (parse errors, names that do not
exist in the pinned Mathlib), (2) Lean that is invalid in this state (unknown local hypothesis names, ill-typed terms),
(3) well-formed, well-typed tactics that do not work here, (4) timeouts. Unknown identifiers are split heuristically:
no dot and `h…`/`ih`/short names are local, everything else is a library name. Policy samples are de-duplicated before
execution (identical blocks of one request become one edge), so per-sample rates are estimated as
failed blocks / (16 × expansions with a policy request); failing blocks are almost always unique, so this is close to
the true per-sample rate (a lower bound; samples that did not parse are not edges).

## Key numbers (visible student, 92,654 edges)

| | edges | failed | share of all failed |
|---|---|---|---|
| automation sweep | 32,710 | 23,172 (70.8%) | 37.8% |
| policy, distinct blocks | 56,419 | 38,191 (67.7%) | 62.2% |
| policy, repeats of a sweep tactic (not run) | 3,525 | (2,587 repeat a failed sweep edge) | – |

- Failure kinds of the 61,363 failed edges: error 59,372 (96.8%), wall-clock timeout 1,990 (3.2%), heartbeat timeout
  1, forbidden 0. The 10 s wall clock always fires before 200k heartbeats under 120 REPLs on 46 CPUs.
- **Policy per sample** (16 × 4,751 expansions = 76,016 samples): ~53.6% fail at their first tactic. Of all samples,
  **5.0% are malformed Lean** (syntax 1.8%, non-existent library names 3.2%), **8.8% are invalid in their state**
  (unknown hypothesis names 3.0%, ill-typed terms 5.8%), **33.7% are well-formed tactics that do not work there**,
  2.6% time out, and 3.4% repeat a sweep tactic that already failed at that node (not run again).
- In blocks: 1,368 + 2,464 = 3,832 of 56,419 blocks (6.8%) are malformed, 6,686 (11.9%) invalid in their state, 25,648
  (45.5%) valid but failing, 1,967 (3.5%) time out. Counting a parse error or unknown library name *anywhere* in the
  (1,000-character) message instead of only the first error raises "malformed" from 5.0% to 5.9% of samples.

## 1. Errors and timeouts

### Why the search's error share (66%) is far above the per-step evaluation (24% error + 3% timeout)

| group (visible student) | expansions | blocks / expansion | failed % of blocks | est. failed % of samples |
|---|---|---|---|---|
| all expansions | 4,751 | 12.6 | 67.7 | 53.6 |
| root expansion, problems eventually proved | 115 | 7.5 | 50.5 | **23.6** |
| root expansion, problems never proved | 73 | 13.8 | 66.0 | 57.4 |
| all expansions of proved problems | 448 | 10.8 | 59.1 | 39.9 |
| all expansions of never-proved problems | 4,303 | 12.8 | 68.5 | 55.1 |

1. **The sweep** contributes 37.8% of failed edges by design: `rfl`, `omega`, `nlinarith` fail on 99.3–99.8% of the
   nodes they run on, `constructor` on 86%. It is cheap (6.9% of Lean seconds).
2. **De-duplication**: 16 samples become 12.6 distinct blocks on average (7.5 at easy roots). Successful blocks repeat
   (`norm_num`, `nlinarith [...]` that works), failing ones rarely do, so per edge the failure share is inflated
   (50.5% of blocks vs 23.6% of samples at easy roots).
3. **State distribution**: 90.6% of policy expansions belong to the 73 never-proved problems (64 expansions each, deep,
   often dead states); there 55% of samples fail. The evaluation's 512 states are mid-proof states of known Lean
   Workbook/Goedel proofs: provable, in-distribution, and not pre-filtered by the sweep. The search only runs the policy
   on states the sweep could not close. At roots of eventually-proved problems the search's per-sample rate (23.6%;
   v2: 22.0%) matches the evaluation (v2: 23.7% error + 3.2% timeout).

### Top failure categories (policy, failed at the first tactic; 38,191 blocks)

| # | category | tier | blocks | % of failed | % of blocks |
|---|---|---|---|---|---|
| 1 | linarith/nlinarith failed | 3 | 8,773 | 23.0 | 15.5 |
| 2 | simp/simp_all/field_simp made no progress | 3 | 4,215 | 11.0 | 7.5 |
| 3 | rw: pattern not found / not an equation | 3 | 3,039 | 8.0 | 5.4 |
| 4 | type mismatch | 2 | 2,321 | 6.1 | 4.1 |
| 5 | unknown library name (hallucinated / other Mathlib version) | 1 | 2,320 | 6.1 | 4.1 |
| 6 | unknown local name (hypothesis not in context) | 2 | 2,251 | 5.9 | 4.0 |
| 7 | simp loop: maximum recursion depth | 3 | 2,040 | 5.3 | 3.6 |
| 8 | wall-clock timeout | 4 | 1,966 | 5.1 | 3.5 |
| 9 | unsolved goals (inside a nested `by` / focus block) | 3 | 1,927 | 5.0 | 3.4 |
| 10 | omega could not prove | 3 | 1,831 | 4.8 | 3.2 |
| 11 | other elaboration (invalid field notation, ambiguous, `have := by` without type) | 2 | 838 | 2.2 | 1.5 |
| 12 | failed to synthesize instance | 2 | 795 | 2.1 | 1.4 |
| 13 | contradiction / assumption failed | 3 | 729 | 1.9 | 1.3 |
| 14 | rfl failed | 3 | 650 | 1.7 | 1.2 |
| 15 | interval_cases: no bound found | 3 | 547 | 1.4 | 1.0 |
| – | syntax (all kinds, see below) | 1 | 1,368 | 3.6 | 2.4 |
| – | apply failed to unify, cases/induction/constructor not applicable, `decide` with free variables, `intro` too many binders, numeral where a proof is expected, function expected, unknown field | 2–3 | 3,094 | 8.1 | 5.5 |

Syntax errors (1,368): other parse errors 510 (prose or a bare term as a tactic, `[f k | for k in s]`), **inaccessible
names copied from the goal (`rw [x✝]`) 487**, unknown tactic 122 (`alpha`, `normalization`), cut-off blocks 139 (89% of
"unexpected end of input" are budget-forced answers ending at 1,280 tokens, often repetition loops), Lean 3 style 104
(`assume`, `cases' h with a ⟨b, c⟩`), empty 6. Lean 3 syntax and wrong fences are negligible.

Examples (state abbreviated to three hypotheses and the target):

| category | state | tactic | message |
|---|---|---|---|
| linarith failed | `f : ℝ → ℝ → ℝ; h₀ : ∀ x y, y ≠ 0 → f x y = x - y * ↑⌊x / y⌋ ⊢ (15 + ↑⌊-(15 / 16)⌋ * 2 * 8) * 40 = -40` | `norm_num [Int.floor_eq_iff] <;> norm_num <;> linarith` | linarith failed to find a contradiction |
| linarith failed | `u v : ℕ; S : Set ℕ; … ⊢ ↑u + ↑v = 64 * 2` | `linarith` | linarith failed to find a contradiction |
| no progress | `⊢ -828 + ((52 + 6 * √43) ^ (3 / 2) + -(52 + -(6 * √43)) ^ (3 / 2)) = 0` | `ring_nf <;> simp [Real.sqrt_eq_iff_sq_eq] <;> …` | simp made no progress |
| no progress | `k m n : ℕ; c : ℕ → ℕ; … ⊢ ∏ x ∈ Finset.Icc 1 n, (x * x + x) ∣ …` | `simp_all only [Finset.prod_Icc_succ_top, Nat.cast_zero, …]` | simp_all made no progress |
| rw pattern | `y a b : ℝ; hb1 : 1 < b; … ⊢ (b * a⁻¹).log * b.log⁻¹ + … ≤ 0` | `rw [h14, h15] at h ⏎ rw [h8, h9] at h …` | rewrite failed, did not find instance of the pattern `a⁻¹.log` |
| rw pattern | `n : ℕ; x : ℝ; … ⊢ 1 / (x * 2).sin = 1 / x.tan - 1 / (2 * x).tan` | `rw [Finset.sum_Icc_succ_top (by linarith)] …` | did not find instance of the pattern `∑ k ∈ Finset.Icc ?m (?n + 1), ?f k` |
| type mismatch | `n : ℕ; h₁ : (2 * n).divisors.card = 28 … ⊢ 35 = (n * 6).divisors.card` | `use n` | type mismatch `n` |
| type mismatch | `a : ℕ → ℝ; h₀ : ∀ n, \|a n\| < 1 … ⊢ False` | `exact h₇` | type mismatch `h₇` |
| unknown library name | `f : ℂ → ℂ; … ⊢ (∑ y ∈ (f ⁻¹' {0}).toFinset, y) * 2 = 7` | `simp_all [Finset.sum_eq_zero_of_fintype_empty, Polynomial.sum_roots]` | unknown constant `Finset.sum_eq_zero_of_fintype_empty` |
| unknown library name | `n : ℕ; h₆ : (2 * n).divisors.card = 28 … ⊢ (n * 6).divisors.card = 35` | `… simp [h₈, h₉, Nat.divisors, Nat.card_fin, Nat.card_insert, …]` | unknown constant `Nat.card_fin` |
| unknown local name | `a b : ℝ; f : ℝ → ℝ; … ⊢ a + b = -1` | `simp only [h₀, h₂, h₃] at h₄ h₅` | unknown identifier `h₄` |
| unknown local name | `a b : ℕ; h₀ : 0 < a ∧ 0 < b; h₁ : … ⊢ ↑a ^ 2 = …` | `field_simp [h₂]` | unknown identifier `h₂` |
| simp loop | `S : Finset ℕ; h₀ : ∀ n, n ∈ S ↔ 2 ≤ n ∧ 171 ≡ 80 [MOD n] … ⊢ 111 = ∑ k ∈ S, k` | `simp_all [Finset.sum_filter]` | simp failed, nested error: maximum recursion depth |
| simp loop | `n : ℕ := 810000; … ⊢ 123 = (Finset.filter (· ∣ 810000) (Finset.Ico 1 810001)).card - 2` | `decide` | maximum recursion depth has been reached |
| timeout | same state as above | `rfl` | wall-clock limit |
| timeout | `k : ℕ; h₀ : k = 2008 ^ 2 + 2 ^ 2008 ⊢ (…) % 10 = 6` | `norm_num [Nat.pow_mod, Nat.add_mod, …] <;> rfl` | wall-clock limit |
| unsolved goals | `x : ℝ; a : x.cos ^ 2 + … = 1 ⊢ x * 2 = π ∨ …` | `have h1 : Real.cos x ^ 2 = (1 + Real.cos (2 * x)) / 2 := by rw [Real.cos_sq]` | unsolved goals |
| unsolved goals | `a : ℕ → ℝ; h₀ : a 0 = 1; … ⊢ ∀ n, a n - √(a n) = 2` | `all_goals intro n; induction n with \| zero => … \| succ n ih => …` | unsolved goals, case zero.zero |
| omega | `a b : ℕ; h₁ : a * b + 1 ∣ a ^ 2 + b ^ 2 ⊢ …` | `have h₂ : (a ^ 2 + b ^ 2) % (1 + a * b) = 0 := by omega` | omega could not prove the goal |
| omega | `u v : ℕ; S : Set ℕ; … ⊢ ↑u + ↑v = 64 * 2` | `have h_u_mod : u % 50 = 23 := by omega …` | omega could not prove the goal |
| elaboration | `p : ℕ; f : ℕ → ℕ; … ⊢ i ≤ ⌊√(↑p / 3)⌋₊` | `exact Nat.floor_le.1 h5` | invalid field notation |
| elaboration | `f : ℕ → ℕ ⊢ ¬f (f ?w) = 1987 + ?w` | `tauto` | internal exception #4 |
| instance | `x e : ℂ; h₀ : x + e = 7; … ⊢ e = 11` | `all_goals nlinarith [h₀, h₁]` | failed to synthesize `LinearOrder ℂ` |
| instance | `n : ℕ; … ⊢ (n * 6).divisors.card = 35` | `have h₄ : n.digits 10 < 10 := by …` | failed to synthesize `OfNat (List ℕ) 10` |
| contradiction | `n : ℕ ⊢ False` | `exact False.elim (by contradiction)` | tactic 'contradiction' failed |
| contradiction | `a : ℕ → ℚ; h₀ : a 1 = 1; … ⊢ False` | `contradiction` | tactic 'contradiction' failed |
| rfl | `f : ℝ → ℝ → ℝ; … ⊢ 3 / 8 + -(2 / 5 * ↑⌈15 / 16⌉) = -(1 / 40)` | `norm_num [Int.ceil_eq_iff] <;> rfl` | The rfl tactic failed |
| rfl | `n : ℕ; … ⊢ (Finset.filter (· ∣ n * 6) (Finset.Ico 1 (n * 6 + 1))).card = 35` | `have h₄ : … = 35 := by apply Eq.symm; rfl` | The rfl tactic failed |
| interval_cases | `n : ℕ; h₀ : 2 ≤ n; … ⊢ False` | `interval_cases n <;> simp_all (config := {decide := true})` | could not find upper bound on n |
| interval_cases | `n : ℕ; h₀ : 0 < n; … ⊢ n ≤ 306` | `{ interval_cases n <;> simp_all [...] }` | could not find upper bound on n |
| syntax | `t s : ℝ; n✝ : ℤ; n : ℕ … ⊢ …` | `rw [x✝] at * ⏎ norm_num` | `<input>:2:7: expected token` |
| syntax | `x : ℝ; h₀ : x = (∑ …) / … ⊢ 241 ≤ …` | `… nlinarith [Real.cos_le_one (k * π / 180) \| for k in Finset.Icc 1 44]` | `<input>:5:51: expected ']'` |

### First tactic vs later tactics

38,191 policy blocks fail at their first tactic (no child); 4,919 more (8.7% of blocks) fail at a later tactic and
still yield a child (3,697) or a duplicate (1,222) from the valid prefix. The tier mix of later-tactic failures is
the same as for first-tactic failures (malformed 7.3%, invalid here 17.0%, valid but failing 71.9%, timeout 3.7%).
The visible model writes long blocks: one-line blocks fail 58.6%, 9–16-line blocks 79.1% (any error 95.2%). Blocks
headed by `have` (32% of blocks) fail 72.6% (41.3% without explanations): the error is usually inside the nested
`by` proof. `exact …` (99.7%), `linarith` (99.8%) and `nlinarith […]` (99.4%) almost never work, because the sweep
already closes the states where they would.

### Across runs (estimated per-sample shares; failed = no tactic applied; repeats of sweep tactics excluded)

| run | solved | edges failed | policy blocks failed | malformed | invalid in state | valid but fails | timeout | root of proved problems, failed |
|---|---|---|---|---|---|---|---|---|
| visible student | 171 | 66.2% | 67.7% | 5.0% | 8.8% | 33.7% | 2.6% | 22.9% |
| visible student v2 | 166 | 66.2% | 67.3% | 5.2% | 8.6% | 33.3% | 2.7% | 21.4% |
| same v1 model, no explanation | 157 | 58.3% | 54.3% | 2.6% | 3.4% | 25.8% | 1.2% | 12.3% |
| round-2 student, thinking | 160 | 61.1% | 59.5% | 4.8% | 6.4% | 27.4% | 0.9% | 21.0% |
| round-2 student, no thinking | 154 | 56.7% | 51.7% | 2.9% | 4.6% | 25.0% | 1.5% | 19.0% |
| 2B SFT v2, A* (13-tactic sweep) | 157 | 53.8% | 49.7% | 2.1% | 4.9% | 21.0% | 0.5% | 14.2% |

Explanations (and thinking) make the policy write longer, more ambitious blocks: about twice the malformed and
invalid rates and more timeouts, yet more solved problems. Non-reasoning policies emit one top-level tactic, so they
never fail later in a block.

### Conclusion: how much is genuinely invalid Lean?

- **About 5% of policy samples are malformed** (syntax or non-existent names); ~95% are syntactically valid Lean with
  real names. Lean 3 syntax and format problems are below 0.2%. The largest syntactic item is copying `x✝`/`h✝` from
  the goal (0.6% of samples), which no prompt-level fix of the model can make valid: the name is inaccessible.
- **About 14% do not elaborate in their state** (malformed + unknown local hypotheses + ill-typed terms), i.e. ~86% of
  samples are valid Lean *in context*.
- **Two thirds of all policy failures are well-formed, well-typed tactics that do not prove what they claim**
  (linarith/nlinarith/omega/simp/rfl failing, rw patterns absent, nested proofs with unsolved goals). This is the
  search working as intended: they are mathematical guesses, verified by Lean.
- "99% valid Lean" is a meaningful target only for the syntax-and-names tier (5% → ~1% is plausible). As a target for
  all failures it is not meaningful: the failure rate is dominated by hard and dead states in unsolved problems
  (55% there, 23% at the roots of solvable problems), and a stronger prover would still fail most guesses on
  unprovable states.

**Levers**, by expected value:
1. Show inaccessible hypotheses differently or rename them (e.g. a `rename_i` pass or naming `x✝` before prompting);
   0.6% of samples, trivially fixable in the harness.
2. Name check before Lean: resolve every identifier against the pinned environment's constant list plus the state's
   local context (the retriever already has 199,810 premise names); reject or repair (nearest name) the 3.2% library and
   3.0% local misses. Constrained decoding is not needed for syntax (1.8%).
3. Training on errors: the search trees carry 38k negative blocks per run; DPO/negative pairs on malformed and
   ill-typed blocks (tiers 1–2, 13.8% of samples) target exactly the invalid part, and error-conditioned repair
   (append the Lean message, resample) turns "unknown identifier"/"type mismatch" into a second try.
4. Shorter blocks in visible mode: blocks with 9+ lines fail ~80%; a length penalty or training on short blocks
   shrinks every tier at once.
5. Lowering the sweep cost is not a lever for Lean time (the sweep is 9.9% of Lean seconds); it only lowers the
   reported error share. Timeouts are the lever (section 3).

## 2. "No progress" duplicates

**What the state key contains.** `ProofState.goals` is the REPL's pretty-printed goal list; each goal string holds the
case tag (`case neg`), every hypothesis line (`h₅ : x 5 = …`, `n : ℕ := 810000` for let-bound values, inaccessible
`x✝`) and the target. `goal_key` = tuple of these strings with whitespace collapsed (`normalize_goal`), in goal order.
Nothing about hypotheses is dropped. A `have h : A := …` always adds a line, so it can never look like the parent; Lean
does not prune unused hypotheses in tactic mode either. **The user's hypothesis (an unused inference is pruned) cannot
produce a same-state duplicate in our representation.** The closest real effect: `simp_all` absorbs hypotheses that
it can prove from the others, so `have …` followed by `simp_all` returns to an earlier state (2 self-duplicates; 52
ancestor duplicates where the sweep's `simp_all` undid the parent's `have`). Those states are genuinely identical.

**Who produces them** (visible student: 6,568 self-duplicates = 49.1% of 13,377 duplicates, 7.1% of all edges, 2.1% of
Lean seconds):

| source | tactic | self-duplicates | share |
|---|---|---|---|
| sweep | `ring_nf` | 3,234 | 49.2% |
| sweep | `field_simp`, `simp_all` | 172 + 7 | 2.7% |
| policy | `norm_num` (incl. `norm_num at h`, `norm_num [lemmas]`; 60 with a later failing tactic) | 2,119 | 32.3% |
| policy | `ring_nf` (+ `ring_nf at …`; 73 with a later failure) | 290 | 4.4% |
| policy | `all_goals norm_num` / `try` wrappers | 151 | 2.3% |
| policy | other combinations of the above (69 with a later failure) | 116 | 1.8% |
| policy | `case tag` focus, then a failing block | 106 | 1.6% |
| policy | `exfalso` on a goal that is already `False` (54 with a later failure) | 104 | 1.6% |
| policy | `ring` | 78 | 1.2% |
| policy | `simp`, `field_simp`, `norm_cast`, `rw`, `congr`, `apply`, `have … ; simp_all` | 186 | 2.8% |

In the 2B A* run, the sweep's `intros` adds 5,161 self-duplicates (34% of its 15,198; it succeeds without binders and
never fails) and the sweep's `norm_num` 3,936.

**Why the printed goal is unchanged.** These tactics do not fail when nothing visible changes: across the six runs
there is not a single "ring_nf failed" or "norm_num failed to simplify" message; `ring_nf` (sweep) never fails except by
timeout and returns to the same state on 69% of its runs, plain `norm_num` failed 2 times in 700 policy uses and
`ring` (which falls back to `ring_nf`) never failed in 182. Either the no-progress check is absent in the pinned Mathlib
or these tactics rebuild the term in a form (numeral representation, instance paths) that differs internally but prints
identically. `simp`/`simp_all`/`field_simp` do check and fail with "made no progress" (6,554 + 2,742 such failures), so their
rare self-duplicates (48 + 7 + 215) are such invisible rewrites. `intros`, `exfalso` on `False`, `try …` and `all_goals`
over a no-op are true no-ops. Partial blocks (388) are a no-op prefix followed by a failing tactic, i.e. failures in
disguise.

**False duplicates?** Merging two states is only wrong when they differ in something the pretty-printer hides:
numeral and coercion types (`(3 / 2 : ℝ)` and `3 / 2 : ℕ` both print `3 / 2`, rpow and npow both print `x ^ 2`),
instance paths, implicit arguments, or elided proofs (`⟨2, ⋯⟩`, in 120 of 14,633 nodes; harmless, proofs of one
proposition are definitionally equal). Hypothesis names, types, let values, case tags and goal order are all in the
key. Empirical check: at nodes where a tactic t0 alone returned to the same state, I looked for blocks "t0; t1" where
t1 alone failed with an error at that node; if t0 hid progress, t1 should succeed after it. In 47 such pairs (visible,
v2; the non-reasoning runs have no multi-tactic blocks) t1 failed after t0 every time. **No evidence of false
duplicates; the theoretical risk (types hidden by printing) remains for real-exponent and cast-heavy problems such as
`aime_1990_p2` and `amc12b_2021_p21`.** The opposite error exists and is harmless: metavariable numbering (`?m.7883`)
and hypothesis-name differences keep equivalent states apart.

Other duplicate kinds (visible): 4.1% back to an ancestor (546; sweep `simp_all` 104, policy `norm_num` 87, sweep
`ring_nf` 82: normalizers undoing the parent's rewriting or absorbing a `have`), 20.8% the same state as a sibling
(2,788; mostly different policy texts with the same effect), 26.0% a transposition to another branch (3,475). All are
correct merges.

**Cost.** Self-duplicates cost 1,781 Lean seconds (2.1%) and, on the policy side, 3,155 of 56,419 distinct blocks
(5.6%). The sweep's `ring_nf` returns to its parent on 3,234 of its 4,687 runs (9.9% of all sweep edges) but costs only
0.7% of Lean time and also produced 1,049 children and 9 proof steps, so it is better kept. Dropping `intros` from the sweep (as the 7-tactic
sweep already does) removes the 2B run's largest source.

## 3. Wasted Lean time

| (visible student, 83,691 Lean seconds) | edges | Lean s | share |
|---|---|---|---|
| policy, failed | 38,191 | 60,716 | 72.6% |
| policy, child | 10,150 | 10,616 | 12.7% |
| policy, duplicate | 8,078 | 4,103 | 4.9% |
| sweep, failed | 23,172 | 5,735 | 6.9% |
| sweep, child + duplicate | 9,538 | 2,521 | 3.0% |
| **all wall-clock timeouts** (incl. partial blocks) | 2,173 | **35,054** | **41.9%** |

- **Timeouts are the waste**: 2.3% of edges consume 41.9% of Lean time, 16.1 s each (10 s limit plus kill, restart
  and replay). Timed-out policy blocks contain `nlinarith` (1,130 of 2,149), `norm_num` (748), `simp_all` (660),
  `omega` (403), `interval_cases` (260). Only one heartbeat timeout occurred: the default 200k heartbeats never bind
  before the 10 s wall clock under load.
- Successful steps are fast: proof-path edges p50 0.21 s, p95 2.4 s, 13 of 273 above 3 s; all policy child or
  duplicate edges p95 3.6 s.
- Failing `nlinarith`-headed blocks cost 10,865 s (4.3 s mean), `all_goals`-headed 7,965 s, `have`-headed 22,096 s.
  `linarith failed` costs 14,899 s, simp loops (`maximum recursion depth`) 3,457 s.
- The sweep's expensive members are `omega` (2,490 s, 27 proof steps) and `simp_all` (2,364 s, 6), then `nlinarith`
  (1,871 s, 13). `rfl` and `constructor` cost ~0.02 s per call.
- Failures concentrate: 30 of 244 problems hold 49.6% of the failed policy blocks (e.g. `algebra_amgm_prod1toneq1_sum1tongeqn`
  734, `mathd_numbertheory_303` 728).

## Recommendations

1. **Policy heartbeat cap** (e.g. 25k–50k per tactic, as in the expert-iteration loop, which cut Lean per expansion
   by 32% there) and a shorter wall clock for policy blocks (3–5 s): targets 42% of Lean time; 5% of proof-path steps
   took over 3 s under load, so measure solve rate at the new cap.
2. **Harness fixes for invalid Lean**: rename inaccessible hypotheses before prompting; check identifiers against the
   environment and local context, then reject or repair before running Lean.
3. **Train on the search's own negatives** (malformed and ill-typed blocks as rejected samples; error-message repair).
4. **Shorter visible blocks**; long nested `have … := by` blocks fail ~80%.
5. **No-progress steps**: treat a step whose goal key equals the parent's as a failed edge for training labels (it is
   counted as a duplicate today) and penalize no-op samples (`norm_num`/`ring_nf`/`exfalso` that change nothing) in
   policy training. Keep the goal-key de-duplication; no false merges were found. If real-exponent and cast-heavy
   problems matter, a secondary key printed with numeral and coercion types shown (pretty-printer options, if the
   pinned Lean has them) would remove the residual risk.
6. Report the policy's per-sample failure rate, not the per-edge share, when comparing with the evaluation.
