# Review BN: verified-progress credit (code)

Scope: the uncommitted change around `CreditMode.VERIFIED_PROGRESS`: `GroupSample.verified_progress`
(`grpo_groups.py`), `advantages.py`, `token_credit.py`, `policy_data.py`, `training_phase.py`, `monitoring/families.py`,
README "Verified progress", `screens/V_2e-5.toml`, `run_screens.sh`, `tests/rl/test_verified_progress.py`.

**The change was edited while I reviewed it.** The first snapshot used only `complete` and the last tactic. The
snapshot reviewed here adds the `clean` rule (no `WASTED_LABELS` tactic anywhere, last tactic not `adds_claim`). It
also drops unscored sequences from the policy data, computes the new metrics over all groups, and adds `GrpoPhase`
fields. Line numbers refer to that later snapshot. Checks: `test_verified_progress.py` 26 passed and
`test_followup_screens.py` passed. `ruff check` and `ruff format --check` on src are clean. The golden loop test fails
(B1).

## Blocking

**B1. The golden loop record test fails.** The failing test is
`tests/rl/test_loop_expert_iteration.py::test_a_grpo_only_loop_records_what_it_recorded_before_expert_iteration`.
Cause: the 5 new `GrpoPhase` fields (`families.py:357-363`, filled at `training_phase.py:543-547`) are written into
`metrics/grpo.jsonl`. Only the `metrics` item differs from `tests/rl/golden/grpo_only_loop.json`; phases, requests and
versions are identical. Fix: regenerate the golden file. Before committing, check that the diff is only these 5 keys per
grpo line.

## Should fix

**S1. Check 1: "last state" is right for the rule now stated.** The code at `grpo_groups.py:148-165` checked out:
- **The last tactic.** For a clean block (`complete`, so no FAILING or MASKED), `tactics[-1]` is the last executed
  tactic. `edge_tactics` gives the last applied tactic the edge target's goals, so the label describes the block's
  final state.
- **"Closer".** `steps_gained = node_steps - remaining_steps`, with `node_steps` read from
  `labels.remaining_steps[edges[0].parent_id]`, the group's node. So "closer" means strictly closer than the group's
  node.
- **A closed goal.** `judge` returns PROOF_GRAPH with `remaining_steps=0` only when the target node is on the proof
  graph. That gives `steps_gained = node_steps ≥ 1`, so r = 1.
- **Edge kinds.** An unverified proof gets FAILING on its last tactic and `UNVERIFIED_PROOF` is not a forward kind,
  so r = 0 either way. TRANSPOSITION and SIBLING_STATE are forward kinds. REPEAT samples use `effective_kind` and their
  executed edge's tactics, so they come out right.
- **Unknown mid-block.** An UNKNOWN label mid-block is free: it is not in `WASTED_LABELS`. Only an UNKNOWN last label
  gives None.

The ordering is right too. `clean` is checked before the None return, so a wasted block or a final bare `have` that
ends in an unknown state gets 0, not None.

No code change is needed for this. The rule is the strictest corner, though. A goal-closing block with one mid-block
`REDUNDANT_HYPOTHESIS` (for example `simp at h` turning h into a type already in context) scores 0, the same as a Lean
error. Before the run, count how many complete closing blocks the clean rule zeroes on A's or B2's trees. One
`tree_policy_data` pass in `experiments/analysis/training_signal.py` would do it. Then the owner knows the price.

**S2. The claim watch misreports advantages under this credit.** In `claim_watch.py:189-196`, `tree_watch` selects
groups by `has_signal(config.credit)`. It then sums `credited_advantages(...).sequence`, which is the per-tactic score
advantage, and its docstring says this is "as the trainer credits it". Under `verified_progress` (and already under
`proof_success`), the trainer uses a different number. A V-screen claim watch would show advantages the trainer never
applied. Fix: add `SampleAdvantages.whole(mode)` holding the match from `token_credit.py:55-61`. Use it in
`token_credits` and in `tree_watch`, and cap only under per-tactic.

**S3. Missing tests for the rule (synthetic only, no real labeller).**
- None of the tests runs `verified_progress` through the real labeller. `tests/graph/test_grpo_groups.py:325-373`
  has real-tree cases for proof-success: a redundant step on a found proof, back to an ancestor, sibling, transposition,
  unverified proof. Add the same for verified progress, plus a real closing block. The property is only as right as the
  labels and kinds, and the synthetic `sample()` always uses NEW_STATE.
- Add synthetic cases for:
  - progress then a detour: (PROOF_GRAPH closer, PROOF_GRAPH with `steps_gained ≤ 0`) → 0;
  - UNKNOWN mid-block then PROOF_GRAPH → 1, which pins "an unknown mid-block is free";
  - an ending that adds a claim with an UNKNOWN label → 0, not None;
  - TRANSPOSITION and SIBLING_STATE kinds → 1;
  - an `UNVERIFIED_PROOF` kind → 0.
- Extend the credit-mode parametrizations to `VERIFIED_PROGRESS`:
  - `tests/graph/test_grpo_groups.py:395` (trainable counts);
  - `tests/graph/test_tree_statistics.py:181`;
  - `tests/rl/test_token_credit.py:110`: every token gets the whole advantage even when the spans split by tactic.

**S4. Two metric tests have stale names and do not pin "all groups".** The tests
`test_the_phase_records_the_mean_verified_progress_of_the_trained_samples` and `..._share_of_trained_samples_without_a_score`
say "trained". The metric is now over all groups' samples (`policy_data.py:393`). Their one group trains either way, so
they would pass under both definitions. Fix: rename them to "of all samples" and add a second group without a signal
whose r would move the mean.

## Minor

**M1. Comments are stale against the clean rule.** `advantages.py:20-21` and the test name
`test_a_complete_block_ending_in_an_unknown_state_has_no_score` say "complete block". It should be "clean block".

**M2. Defensive or unused pieces (CLAUDE.md: no checks for impossible cases).**
- `advantages.py:101` checks `verified_progress_baseline is None`. This cannot be true when `progress` is not None.
  Replace it with `assert` or drop it.
- `grpo_groups.py:153-154` handles empty `tactics`, which cannot happen: `edge_tactics` always yields at least one
  tactic, and an unparsed sample has one FAILING tactic.
- `GroupAdvantages.verified_progress_baseline` (`advantages.py:53`) is written but never read. Remove it.
- The `= None` / `= 0` defaults on `SampleAdvantages.verified_progress`, `GroupAdvantages.verified_progress_baseline`
  and `PolicyDataParts.unscored` exist only so old constructors compile. A future constructor that forgets the field
  would silently leave every V sample untrained. Make them required, and update the two `SampleAdvantages(...)` in
  `tests/rl/test_token_credit.py`.

**M3. Name shadowing.** The parameter `verified_progress_baseline` of `sample_advantages` (`advantages.py:91`)
shadows the module function of the same name (`:105`). Rename the function to `progress_baseline`.

**M4. Dashboard numbers keyed to per-tactic credit or to the trained-group count.** These are expected under the
new credit and are not bugs:
- `mean_local_reward`, `mean_global_reward`, `local_advantage_share` and `capped_*` are per-tactic quantities and
  mean nothing under V. B2 had the same.
- The "Few mixed groups" alert (`monitoring/alerts.py:167`, < 20%) and the cross-arm
  `trainable_groups_per_thousand_tokens` will read lower than A's simply because the 0/1 rule is stricter.
- `untrained_token_share` no longer counts the dropped unscored sequences; `unscored_sequences` holds them.

The health checks are credit-agnostic and fine: KL and clip fraction (first round), habit alerts, valid Lean.
`has_signal` reaches `tree_summary.trainable_groups` and `tree_statistics.groups_with_signal` under the loop's credit.
The screens are token-paced (`phase_generated_tokens`), so `min_trainable_groups` does not gate them.

**M5. The README says tactics per block are "watched (below about 2.0)", but no health check exists for it.** It is
only charted (`pages.js:593`, `mean_block_tactics`). Say "charted, checked by hand", or add a NOTE-level check.

**M6. Analysis scripts skip the new mode.** `experiments/analysis/training_signal.py:254` iterates three credit modes
and leaves out `VERIFIED_PROGRESS`. Nothing breaks. Add it if the screen gets the same signal analysis.

**M7. Small issues in the tests and the screen script.**
- Several groups reuse `edge_id=0` for two samples (`"c"`/`"x"` beside `"a"`/`"step"`), which is harmless without
  texts.
- `test_the_phase_counts_the_sequences_left_out_without_a_score` rebuilds the `verified_progress_sequences` group
  inline; share one builder.
- `run_screens.sh:2` still says "The two GRPO screens".

**M8. Style.** The 4-line docstring on `verified_progress` goes against the global "one short line" rule. It matches
the neighbouring `reaches_proof_graph`, so follow the repo's convention.

## Paths checked and found fine (check 2)

- **Matches on `CreditMode`.** The only `match` blocks are `GroupAdvantages.has_signal` and `token_credits`. Both
  cover the new member, and neither falls through.
- **Who builds `SampleAdvantages` and `GroupAdvantages`.** Only `sample_advantages` and `group_advantages` in
  production. Tests and the analysis scripts use keywords.
- **The trainer paths.** `prepare_policy_tree` → `tree_policy_data`, which skips unscored samples at
  `policy_data.py:327-329` and counts them. The resident trainer's `PhasePreparation` → `combined_policy_data`, which
  sums `unscored`. Both go on to `data_metrics` and `grpo_phase_record`.
- **Expert-iteration data** does not use credit.
- **`reward_replay` and the analysis scripts** use only `PER_TACTIC`, `SEQUENCE` and `PROOF_SUCCESS` explicitly.
- **The `cap_wasted_block_explanation` guard** rejects V with the cap. The V screen's phase config loads
  (`test_the_v_screens_phase_config...`).

## Verdict

The rule is implemented as now documented, and the field reaches every trainer path. After B1 (regenerate the golden
after checking the diff), the V screen can start. Do S2 before anyone reads a claim watch of V. S3 and S4 are cheap and
should land with the commit. S1's count is worth one analysis pass, so the owner knows how many verified closing proofs
the clean rule scores 0.

## Re-review (same day, after the fixes)

Ran `test_verified_progress.py`, `test_token_credit.py`, `test_claim_watch.py` and `tests/graph/test_grpo_groups.py`
(122 passed, 1 failed), plus the golden loop test (passed). `ruff check` and `ruff format --check` on src and tests
are clean.

- **B1 is fixed.** The golden test passes.
- **S2 is fixed.** `SampleAdvantages.whole(mode)` covers all four modes. `token_credits` uses it, and so does
  `tree_watch`. Under per-tactic credit the claim watch still sums the capped `sequence`, so it gives the same numbers
  as before.
- **S3 is fixed apart from one wrong expectation.** The real-labeller cases (redundant step on a found proof, return to
  an ancestor, sibling, transposition, closing proof, unverified proof) are correct. So are the token-credit tests.
  The new parametrization `test_trainable_groups_are_counted_with_the_phases_credit[verified_progress-0]` fails
  (`tests/graph/test_grpo_groups.py:459`), and the code is right, not the test. In `two_proofs_tree` the root's
  shortest proof is `exact p` (1 step). `intro` reaches `⊢ q`, which also has 1 step left, so it is no closer and
  scores 0, while `exact p` scores 1. The root group therefore has mixed r and trains. The expectation should be
  `(CreditMode.VERIFIED_PROGRESS, 1)`. That makes it a useful real-tree pin of the "no closer than the node" rule. Also
  fix the fixture's docstring: under verified progress, not every sample of the root group gets r = 1.
- **S4 is fixed.** The mean is now pinned over all groups.
- **Minor fixes.**
  - Done: the comments say "clean", the empty-tactics guard and the unused field are removed,
    `SampleAdvantages.verified_progress` is required, the shadowing is gone, and the `run_screens.sh` wording is fixed.
  - The README wording is accurate now: "charted (no health check), and the orchestrator reads it against about 2.0".
  - Left, cosmetic only: the `progress_baseline is None` check (`advantages.py`), which cannot be true when `progress`
    is set, and the `PolicyDataParts.unscored = 0` default.

**Verdict:** ready once the one test expectation is changed to 1. Nothing blocks the V screen.
