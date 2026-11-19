# Review BH: cap on a failing block's explanation credit (`cap_failing_block_explanation`)

Scope: the uncommitted change (policy_data.py, study_configs.py, arms A/D TOMLs, README paragraph, tests) and the
untracked `experiments/analysis/continuation_credit.py`. Ran `tests/rl/test_policy_data.py` (38 passed) and
`tests/rl/test_followup_arms.py` (72 passed) in WSL; `ruff check` and `ruff format --check` clean on the touched files.

## What I verified

- **Effect is confined to explanation tokens in per-tactic mode.** `token_credits` (token_credit.py:55-74) uses
  `advantages.sequence` only for EXPLANATION tokens under PER_TACTIC; tactics get `advantages.tactics[i]`, closing gets
  `advantages.closing` (always None for a failing block, since `complete` is False). SEQUENCE/PROOF_SUCCESS are guarded
  out in `credited_advantages` (policy_data.py:268-269) and tested.
- **`has_signal` and group selection are unchanged** (computed on the uncapped advantages at policy_data.py:284-285).
  A group cannot lose all its signal through the cap: the baseline is the scored samples' weighted mean, so any capped
  positive sequence has a negative counterpart that stays. `trained_groups` and every `PolicyDataMetrics` field read
  groups/labels/tactic magnitudes or token counts, never `sequence`, so metrics are consistent.
- **Config flow, both paths.** Arm TOML `[phase.policy.data]` → `overlay_configs` merge (key allowed in `ARM_SETTINGS`)
  → `phase_config_text` keeps the `policy` table → `TrainingPhaseConfig.policy.data` → `train_policy_phase`
  (`build_policy_data(..., grpo.data)`) and `PhasePreparation` (`resident_trainer.py:233,238` →
  `prepare_policy_tree(..., self.data)`). Arm A's end-to-end phase-config test and `test_arm_ds_phase_config_is_arm_as`
  cover the merge for both arms. D's expert-iteration half is SFT on proofs and reads no advantages.
- **Edge cases.** `sequence is None` → not capped, explanation stays untrained as before. Token/offset mismatch, a sample
  without a block, and any sample whose span count differs from its tactic count fall back to "every token is
  EXPLANATION" (token_credit.py:53,66) → the whole sequence is capped, tactics included (README states this for the
  mismatch case only).
- Capped tokens stay `trained` with advantage 0: they still count in the per-token loss denominator and the KL terms,
  exactly as a sample at the baseline does today. Fine.

No blocking issues.

## Should fix

1. **The claim watch reports uncapped explanation credit for arms A/D** — `src/lean_search/rl/claim_watch.py:183-193`.
   `tree_watch` sums `group_advantages(...).samples[i].sequence` as "where they train and with what advantage"; under
   per-tactic credit that value is exactly the explanation credit, and `claim_watch.py:270-316` prints per-sample
   advantages of on-graph decompositions vs direct openings and of the bare-have class. `reaches_proof_graph` includes
   partial blocks (CHILD outcome with a later failure → NEW_STATE, forward), so after A/D relaunch the watched
   "on-graph" advantages will include the +0.35..+0.41 failing-block credit the trainer no longer pays. The owner reads
   these per phase to judge drift. Fix: in `tree_watch`, apply `credited_advantages(sample, sample_advantages,
   config.policy.data)` when `config.policy is not None` (or report both raw and credited so pre/post-cap phases stay
   comparable), plus one test.

2. **No per-phase record of what the cap removed** — `policy_data.py:332-375`. In a controlled study the switch's size
   should be visible in the loop's own records, not only in an offline replay: e.g. `capped_explanation_samples`
   (sample-weighted, trained groups) and the summed positive sequence credit removed. Without it, a phase where the cap
   bites far more than the replayed 22-34% is indistinguishable from one where it does nothing. Cheap to compute in
   `tree_policy_data` (count where `credited_advantages` changed `sequence`) and carry through `PolicyDataParts`.

## Minor

3. `policy_data.py:271` re-implements `GroupSample.has_failing_tactic` (grpo_groups.py:142); use the property and drop
   the `TacticLabel` import.
4. `policy_data.py:266` docstring ("gives `sequence` to the explanation only") is false in the fallback cases above;
   and README (new paragraph, last sentence) names only the offset mismatch. The span-count/tactic-count mismatch and
   no-block samples also cap the tactic tokens; say "whenever tokens cannot be split by tactic" (span-count mismatches
   are not counted by `token_mismatch_sequences`).
5. Missing test for that fallback: a failing block whose completion has a different span count (or unrecorded/mismatched
   tokens) gets 0 on every token under the cap. The README asserts it; a test pins it.
6. Comments: the 3-line comment on `PolicyDataConfig.cap_failing_block_explanation` (policy_data.py:42-44) and the
   3-line TOML comments exceed the one-short-line rule; the field comment could be "Per-tactic only: a block with a
   failing tactic gets explanation credit ≤ 0." The TOML comments (A.toml:9-11, D.toml:17-19) point to README
   "Claims"; the paragraph is "Failing blocks' explanation".
7. `experiments/analysis/bare_have_credit.py:384` `--check-production` builds with `PolicyDataConfig()` (cap off) and
   its own token replay is uncapped, so on a capped run it no longer replays "the production code path" as its
   docstring says. Pass `settings.phase_config.policy.data` and apply `credited_advantages` in the base replay, or note
   the limitation.
8. Running arm A rerun is unaffected until relaunched (configs are written at launch); A.toml in the repo now differs
   from what the rerun ran. Worth one line in `results/followup_progress.md` so the rerun's config is not regenerated
   from the new TOML by mistake.

## Analysis script (`experiments/analysis/continuation_credit.py`)

Logic checks out: masked-cost charge lands on the FAILING tactic's gain or anchor parts consistently with how
`wasted_tactic_cost` is applied (local part); BASE is iterated first so `base_trained` is filled before lookups;
strict zips hold (one advantage per tactic). Minor only:

9. It has no variant replaying the adopted switch itself (`min(sequence, 0)` for every sample with a FAILING tactic,
   tactics untouched). `FAIL_NEVER_POSITIVE` (line 48) is the rejected "drop all positive credit" alternative and only
   covers the fails-after-graph class; the production cap also hits never-on-graph failing samples (off-graph or
   unknown prefix with positive value, unverified proofs). A `cap_explanation` transform would show the switch's
   actual reach on the same tables.
10. `sample_outcome` (line 138) counts any PROOF_GRAPH label as on-graph, while `reaches_proof_graph` (and the
    README's "reaching the proof graph") also requires a forward edge kind; back-to-ancestor/no-progress blocks with an
    on-graph intermediate state are classed differently. Small effect; either align or say so in the docstring.
11. `masked_cost` is accepted as a variant key (line 248) but neither the docstring example nor `--variants` help
    (line 300) mentions it.

## Verdict

**Merge after fixes**: 1 (claim watch consistency) and 2 (a per-phase metric of the cap) before arms A/D relaunch with
the switch; 3-8 are quick and can go in the same pass; 9-11 optional.

## Re-review (after the fixes; switch renamed `cap_wasted_block_explanation`)

Ran `test_policy_data.py` (49 passed), `test_followup_arms.py` (72), `test_claim_watch.py` (21); ruff clean.

**`has_wasted_tactic` (grpo_groups.py:145-152) is correct against `judged_in_block`.** A negative gain off the proof
graph arises only from a charge: c for a non-anchor failing/no-op/redundant tactic (leading no-ops before the anchor
included), c + c' for a non-anchor open claim, c for an unknown/off-graph state ending the block's states after
evidence. In the no-evidence branch a gain off the graph is R − R(unknown anchor) = μ·q ≥ 0 (off graph) or 0
(unknown), so there are no value-noise false positives; on-graph detours are excluded by the label. The reverse is
also clean: waste that does not reach a negative gain is either an anchor (gain None; an open-claim or no-op anchor
already scores at or below a failure, so its sequence is never above baseline in practice), a tactic after an open
claim (NO_GAIN by design, the claim itself is charged), or any waste with `wasted_tactic_cost = 0` (config edge).
Note only: unknown endings after evidence are valid, unverified continuations; capping their explanation is a real
change to the continue bet, which the README's "does not change: the tactic-level bet" paragraph slightly understates.

**Metrics plumbing is correct.** `ExplanationCap` is filled per trained group before the text lookup, carried in
`PolicyDataParts`, summed in `combined_policy_data` (both the whole-phase path and `resident_trainer.py:471`), and
the new `PolicyDataMetrics` fields default to 0 so old records load. It counts trained samples whose group has no
recorded text too (the docstring says "trained samples", so consistent).

**claim_watch is correct**: it applies `credited_advantages` with the phase's `policy.data`, default (cap off) for
arm C and for older runs, so earlier phases' readings are unchanged.

### Should fix

R1. **`bare_have_credit.py --check-production` now asserts on any capped run** (`bare_have_credit.py:383-384` vs
`:444-448`). Production is built with the phase's `policy.data` (cap on for A/D), but the script's own token replay
still uses `variant_advantages` → raw `group_advantages`, so `produced == credits.advantages` fails for the first
capped sample of a relaunched A/D phase. Fix: apply `credited_advantages(sample, sample_advantages,
settings.phase_config.policy.data)` to the base variant's replay (or all variants), so the check compares like with
like.

### Minor

R2. `continuation_credit.py:196-200` `has_charged_tactic` duplicates `GroupSample.has_wasted_tactic`; `WASTE_CAP`
can test `sample.has_wasted_tactic` directly, so the replay cannot drift from production. The `EXPLANATION_CAP`
comment (line ~57) still calls the failing-only cap `cap_wasted_block_explanation`; the production switch is
`WASTE_CAP`. Also, its base variant on a capped run's phases is uncapped (not what trained).
R3. `study_configs.py` comment still says "in a block with a failing tactic".
R4. Tests: no case for an unknown/off-graph ending after evidence (the parametrize covers no-op, redundant, open
claim), none that an on-graph detour with a negative gain is not capped, and no claim_watch test with the cap on.

### Verdict

**Merge after fixing R1** (one line plus a cap-on check in its use); R2-R4 are optional in the same pass. The
production change itself (`has_wasted_tactic`, `credited_advantages`, metrics, config refusal, claim watch) is
correct.
