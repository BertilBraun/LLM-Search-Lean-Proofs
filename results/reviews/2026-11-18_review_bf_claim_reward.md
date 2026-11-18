# Review BF: the claim reward switches (2026-11-18)

Independent review, correctness focus. Branch `bare-have-claim-switches` at 2e54601 (one commit on master 7109590):
`[reward] claims_earn_progress` / `unproved_claim_cost` (on in `arms/A.toml`, `arms/D.toml`), `TacticOutcome.adds_claim`,
the like-with-like habit thresholds, the dashboard tiles, `experiments/analysis/bare_have_credit.py`. No code was
changed; nothing committed. Tests (WSL, at 2e54601):
`tests/rl tests/graph tests/search tests/monitoring`, 3433 passed, 80 skipped.

## Verdict

**Approve; no blocking defect.** The credit change is exactly the one described and is inert with both switches at
their defaults; the claim detection is right for the forms the drift consists of; the replay follows the trainer's
path closely enough for its conclusions, and its numbers check out against the local outputs. Two should-fix items
concern the replay's own production check and the operational merge (both small), plus nits.

## Blocking

None.

## Should fix

**S1. `--check-production` checks token placement, not group construction.**
`experiments/analysis/bare_have_credit.py:355` builds groups with `estimates = [None] * len(record.nodes)` while the
trainer uses `recorded_estimates(record, config.readout)` (`rl/training_phase.py:225-228`); line 407 then feeds the
script's own groups to `tree_policy_data` and asserts the token advantages equal. That proves the token credit matches
for the same groups, not that the groups are the trainer's. Today they are: estimates only enter through
`off_graph_value`, which returns 0 whenever `value_share` is 0, as in every arm. If an arm turns μ on, the replay
silently diverges while its "0 token mismatches" line still reads as a production match. Fix: use
`recorded_estimates(record, settings.phase_config.readout)` (one line), or assert `config.reward.value_share == 0`
and say so in the docstring.

**S2. Merging onto current master: deploy only at A's HOLD, and only through the rerun path.** Master moved to
2b73a6e (arms driver order file and holds, docs, tests); no file overlaps with this commit, so the merge is clean. What
it must watch is operational:
- The node runs the smoke test and arm C from the checkout; this commit changes `tactic_labels.py` and
  `health_checks.py`, which C's loop reads (habit warnings, claim labels for EI data through `leaves_claim_open`, which
  is unchanged). `results/followup_node_operations.md` (master, "A's old run ... Once the reward fix is merged") already
  says to deploy at the HOLD before A, never while C runs; keep to it.
- A must rerun from v0: the rerun path moves `followup_A` (phase 7), its configs, checkpoints, markers and `pause_A`
  aside before `hold_A` is removed. If someone only removes the hold, `arm_loop.sh` resumes `followup_A` at phase 8 with
  the new `[phase.reward]`, a silent mid-run recipe change (DESIGN.md forbids it); nothing in the loop compares the
  phase template with the run's. Suggest a guard: `followup_arm.py` (or the driver) refusing to resume an arm run whose
  written phase config differs from the overlay's.
- Reports should say that smoke and C ran on the code before the fix (health warnings judged every-statement against
  every-statement there only when the reference had no below-band values; see N3), A and D after it;
  `loops/<arm>.revisions` records it.

## Nits

**N1. `adds_claim` misses claims that open more than one goal.** `search/tactic_labels.py:108-123` (`claim_of`) accepts
only +1 goal with the first goal's hypotheses unchanged. `constructor <;> have h : A`, `all_goals have h : A` on two
goals, `have h : A ∧ B := ⟨?_, ?_⟩` or `obtain ⟨x, hx⟩ : ∃ x, P x` under `<;>` add claims but are not detected, so they
keep δ. None is a drift pattern in A's trees (the replay's classes come from `is_bare_have` openings), so this is a
documentation point: the README's "a claim adding a goal" means "exactly one". Checked and correct otherwise: bare
`have h : A`, flattened `have h : A := by …` opener, `obtain … : A`, `replace h : A`, `rsuffices` (claim reordered
last→first, adds the main goal: counted, consistent with `obtain`); not counted: `suffices` (replaces the goal), term
`have h : A := t` and unflattened `have … := by p` that closes A (hypotheses change), `obtain … := h`, `haveI`/`letI`
(always with a value), `show`/`calc`/`constructor`/`refine` (no keyword, `test_a_goal_split_adds_no_claim`).

**N2. The keyword search is anywhere in the tactic text.** `CLAIM_TACTIC.search(text)` (`tactic_labels.py:83, 128`)
matches `have` inside a term, a comment or a nested `by`, so a non-claim tactic whose text merely contains the word and
whose states happen to have the claim shape (same hypotheses, new first target, one more goal) would be marked
`adds_claim` and lose δ. The shape test makes it rare; the pre-existing `leaves_claim_open` has the same exposure.
Acceptable; a comment would help.

**N3. Below-band reference limits have no sample floor.** `rl/health_checks.py:285-296` scales the reference phases'
`below_band_*` values whatever their sample count; a reference with a handful of below-band blocks gives a noisy limit,
and `compared` (line 362) then prefers it over the every-statement limit. The current phase's below-band unproved-claim
share has a floor (`min_proof_graph_samples`, line 458), the bare-have share and the others do not (as before). These
are warnings only, so a note in the README or a minimum count of below-band blocks in the reference would do.
Dashboard: `app.js` now shows old phases (records without below-band limits) on every statement where it used to show
below-band; consistent with the new rule, worth a line in the README since history moves.

**N4. README numbers name fewer phases than they summarize.** `rl/README.md` "+13.6k to +21.0k summed token advantage
per phase" is arm A's phases 1-6 (local `replay3_A.json`: 19.6k, 20.2k, 21.0k, 17.8k, 21.0k, 13.6k); phase 7 is +4.4k,
step 2's v0 phase +25.9k, the 2e-5 start +18.2k / +8.4k. Everything else I recomputed matches: with both switches
the bare-have openings are negative on all ten phases (−1.6k to −16.8k); cost 0.2 leaves exactly two positive (A5
+3.7k, v0 +3.6k); either switch alone leaves eight of ten positive; bare claims proved in their block +0.22 to +0.30
per sample before, +0.16 to +0.23 after; trained groups unchanged; sign changes 109/1934 (5.6%) to 146/1091 (13.4%);
proof-graph positive advantage −2.1% (phase 1) to −5.3% (phase 4).

**N5. New `HealthThresholds` fields are written always.** `monitoring/families.py:717-720`: four `None` keys in every
health record from now on (the golden's only change), unreadable by readers before this commit. If the efficiency
branch (its `record_fields.written_when_set`) lands first, these four fields could use it and keep the golden as it
was; otherwise fine as additive keys.

## Checked and fine

- **Credit, switches off** (`rl/grpo_groups.py:237-283`): `open_claim_cost` equals `cost` when `unproved_claim_cost` is
  None, so the anchor `R − c` and the later `−c − c` are unchanged; `unpaid_claims` is False, so `step` is 0 and neither
  branch subtracts; `previous_steps` only feeds `claim_step`. The golden loop changed only in the four new threshold
  fields (three phases), all None/`null`; old records read (the fields default to None).
- **Credit, switches on**: an anchor claim on the proof graph loses `δ · min(1, max(0, steps_gained))` from its global
  part after `reference` was taken from the unreduced parts (line 265), so the next tactic is judged against the claim's
  state and the δ is dropped, not deferred; a later claim loses `min(step, max(0, gain.global))`, so its gain never
  goes below 0 for that reason. A detour claim (steps_gained ≤ the last proof-graph state's) loses nothing; a claim that
  gains two steps by a shorter route keeps the second. With μ = 0 the anchor's global part (0.85 + δ·steps_gained)
  stays ≥ the off-graph floor after the subtraction. `−0.45` as the anchor and `−0.4` later for an invented claim under
  0.3 follow from `reward_parts(0, −1)` = −0.15 and `c + c'`. Only `PROOF_GRAPH` claims are touched; unproved claims
  keep their label path, and everything after the first unproved claim still gains 0.
- **Label plumbing** (`tactic_labels.py:286-320`): `adds_claim` is set for every detected claim, proved in its block or
  not, and carried into the `UNPROVED_CLAIM` relabel; `leaves_claim_open` and the unproved-claim relabel are as before
  (the early `continue` for a block-proved claim now runs after setting `adds_claim`). `TacticReward` / `TacticOutcome`
  are not serialized anywhere, so no record changes.
- **Tests pin the orderings claimed** (`tests/rl/test_claim_progress.py`, `tests/graph/test_claim_progress_groups.py`):
  default keeps δ; a bare claim the tree proves scores R without δ; inline proof beats the bare claim by exactly the
  proof's step (and the closed-goal bonus on real trees); claim + proof equals one direct step; invented claim below an
  error in its group; under the arms' reward a valid continuation ≥ an error there, appending an error, an invented
  claim or a proof-graph claim never gains, for seven prefixes; detours keep their loss; unset cost equals c.
- **Configs**: A and D carry exactly the two keys (tests); the old run's phase config keeps claims earning progress;
  arm C refuses any `phase.reward.` key (`study_configs.unused_settings`, tested); the arm overlay merges into the
  shipped phase's `[reward]` without dropping its other keys (`test_an_arms_phase_config_is_its_credits_shipped_phase_
  at_the_chosen_rate`).
- **Health checks**: `compared` returns below-band value and limit together or every-statement value and limit
  together, never mixed; the unproved-claim check keeps its below-band sample floor and reports the matching sample
  count; the arm-A-like reference test reproduces the missed phase-6 warning (26.6% > 1.5 × 17.4%).
- **The replay** follows the trainer: `label_graph`, `policy_tactics` with the phase's `off_graph_min_expanded_nodes`,
  `policy_groups` with the phase's (or the variant's) `RewardConfig`, `groups_not_sampled_by` with the phase's excluded
  versions, `group_advantages`, `token_credits(..., CreditMode.PER_TACTIC)`, the trainer's `has_signal` for trained
  groups, the phase's own `training/phase_XXXX.toml`; token advantages asserted equal to `tree_policy_data`'s (0 or 1
  production mismatches per phase, the trainer's own count). Caveats beyond S1: it is a static replay on fixed trees
  (no policy feedback, so "negative on all ten phases" says the gradient's sign on these samples, not where training
  would go), and the "gained" lines of any variant are sums over few groups.
