# Review bp: `verified_fraction` credit (uncommitted diff, 2026-11-22)

Scope: `git diff` plus `tests/rl/test_verified_fraction.py` and `experiments/configs/grpo/followup/screens/F_2e-5.toml`.

Run (WSL, one suite at a time): `tests/rl/test_verified_fraction.py` 13 passed; `test_token_credit.py`,
`test_claim_progress.py`, `test_verified_progress.py` 95 passed; `tests/graph/test_grpo_groups.py`,
`test_reward_replay.py` 77 passed; `test_followup_screens.py` 17 passed; the golden
`test_a_grpo_only_loop_records_what_it_recorded_before_expert_iteration` passed. `ruff check` and `ruff format --check`
clean on the touched files.

## Correctness of `steps_gained / node_steps`

- `node_steps` is the group node's remaining steps everywhere a `GroupSample` is built: `group_sample` passes the same
  `labels.remaining_steps[edges[0].parent_id]` it gives `tactic_reward` (groups come from `edges_by_parent()[node_id]`,
  so parent = group node). `rl_samples.sample` and `test_claim_progress.block` pass `NODE_STEPS`, the value their
  `tactic_reward` calls use. Every other construction is `dataclasses.replace(sample, tactics=...)`
  (`reward_replay.old_group`, `bare_have_credit`, `continuation_credit`, `test_reward_replay`) and keeps `node_steps`;
  `old_tactic_reward` delegates proof-graph tactics to `tactic_reward` with the same node steps.
- The assert holds. `verified_fraction` reaches it only when `verified_progress == 1`, which requires
  `last.steps_gained > 0` (so not None). `steps_gained = node_steps - outcome.remaining_steps`, and every
  `remaining_steps` is >= 0: graph distances (Dijkstra from proved nodes), `route_steps` (target's + tactics left, index
  <= applied - 1), the key minimum in `TacticGraph.remaining_steps`, and 0 for a proof end (`judge` with no goals on a
  proof-graph node). So `0 < steps_gained <= node_steps` for transpositions, siblings, repeats (outcomes of the executed
  edge, re-based on this group's `node_steps`) and blocks ending at the proof's end (exactly 1). `node_steps` is never 0
  for a group (distance 0 is only a goal-less verified proof, never expanded), and the division is unreachable then
  anyway. Checked on the real labeller (scratch run, not committed): sibling 0.5 (node 2 steps), transposition 0.5,
  closing 1.0, failure 0.0.
- `steps_gained` can exceed the block's tactic count (a key-matched state shorter than the block's route), never the
  node's remaining steps; that is intended ("steps its last state gained").
- Multiplicity: `scored_baseline` weights by `multiplicity` as the V baseline did; `mean_verified_fraction` uses
  `weighted_samples`, as `mean_verified_progress`. Consistent.

## Consumers

All handled: both `match` statements (`whole`, `has_signal`); `token_credits` goes through `whole` (non-per-tactic
branch); left-out sequences via `UNSCORED_LEFT_OUT` and `whole(...) is None` (same semantics as before for V, and
`credited_advantages` changes only `sequence`); `claim_watch` uses `has_signal`/`whole` and skips None;
`tree_summary.trainable_groups` and `graph_statistics` use `has_signal(credit)`; `study_configs.ARM_SETTINGS` already
allows `phase.policy.data.credit`. The analysis scripts build `SampleAdvantages` only through `group_advantages`
(`bare_have_credit`, `continuation_credit`, `training_signal` use fixed per-tactic/sequence/proof-success modes), so the
new required field breaks none of them.

## Serialization

`GroupSample` is never persisted: groups are rebuilt from tree records each phase (`label_phase_data`,
`single_step`, `bare_have_credit`), the resident trainer receives `PolicySequence`s and writes `PhaseOutcome` JSON,
and `reward_replay` rebuilds groups from records. The `grpo_expert_iteration.py` process pool pickles within one code
version. A required field breaks no recorded data. `GrpoPhase.mean_verified_fraction` defaults to 0.0, so old
`grpo.jsonl` rows still parse.

## Findings

### Blocking

None.

### Should fix

1. **F changes the advantage scale as well as the length incentive, at V's learning rate.** There is no per-group std
   normalization (`policy_trainer` divides by a fixed token normalizer), so F's advantages are V's scaled by about
   1/`node_steps` per group: at a 5-step node a one-step block against a failure is 0.2 apart instead of 1, at a
   10-step root 0.1. The "don't fail" contrast far from the proof shrinks by the same factor, and the effective step
   size of the whole phase drops several-fold at 2e-5. An F result below V can then be the smaller step, not the
   incentive. Either pre-register that confound in `results/followup_progress.md`, or record the mean |advantage| per
   trained token (or per sample) in `PolicyDataMetrics` so F's and V's update sizes can be compared; the screen still
   tests what the owner asked for.
2. **Tests miss the real labeller and the multiplicity weights.** Add fraction assertions next to the V ones in
   `tests/graph/test_grpo_groups.py` (values verified above): sibling `intro q` 0.5, transposition `jump` 0.5,
   closing `close` 1.0; and one `test_verified_fraction.py` case that a sample with multiplicity 3 weighs three times
   in the fraction baseline (e.g. `sample("step", PROOF_GRAPH, multiplicity=3)` with an error: baseline
   `3 · 0.25 / 4`).

### Minor

3. One more unit case would pin the definition: a block whose last state gained fewer steps than it has tactics
   (`sample("detour", PROOF_GRAPH, PROOF_GRAPH, steps=(2, 3))` scores 1/4, not 2/4), so the r is the last state's gain,
   not the block's length.
4. Stale comments in `policy_data.py`: `PolicyDataParts.unscored` ("under verified-progress credit") and
   `PolicyDataMetrics.unscored_sequences` ("no verified-progress r (that credit only)") now cover both credits;
   `results/followup_progress.md` line 357's list of metrics reaching `metrics/grpo.jsonl` lacks
   `mean_verified_fraction`.
5. `verified_fraction` (and its assert) now runs in every credit mode, through `group_advantages`' fraction baseline
   and `data_metrics`. The invariant holds (above), but a violation would stop the A/B2/V screens and every arm, not
   only F. Acceptable as written; worth knowing.
6. `relative` is a generic public name in `advantages.py`; `relative_to_baseline` or keeping it local would read
   better. Cosmetic.

## Verdict

Correct and complete for every consumer; no recorded data is affected; style and lint clean. Ship after adding the
real-labeller and multiplicity tests (2). Finding 1 does not block the screen but should be pre-registered or measured
before F is read against V.

## Re-review (2026-11-22)

All findings are addressed in the working tree.

- 1 (scale): pre-registered in `results/followup_progress.md` ("Owner, 2026-11-22: fix the block length"). Advantages
  are not divided by the group's spread, so F's update is smaller. The per-phase parameter change (V: 2.3-2.7%) is read
  beside the result, and a much smaller change makes a weaker F inconclusive rather than negative. No new metric is
  needed for that reading.
- 2 (tests): `tests/graph/test_grpo_groups.py` now has the real-labeller cases (sibling 0.5, transposition 0.5,
  closing 1.0); these match the scratch run above. `test_verified_fraction.py` adds the multiplicity-3 baseline case
  (error's advantage −3 · 0.25 / 4) and `steps=(2, 3)` → 1/4.
- 3–6 (minor): the `policy_data.py` comments now name `UNSCORED_LEFT_OUT`, `relative` is renamed to `minus_baseline`
  (no other callers), and the F toml names "Progress fraction". Finding 5 (the assert runs in every mode) stays
  accepted as written.

Run (single suites): `test_verified_fraction.py` 15 passed; `tests/graph/test_grpo_groups.py` 57 passed;
`test_verified_progress.py` + `test_token_credit.py` 50 passed. `ruff check` and `ruff format --check` clean.

**Verdict: approve.**
