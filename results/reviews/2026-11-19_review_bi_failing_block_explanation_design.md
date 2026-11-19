# Review BI: `cap_failing_block_explanation` (design, RL incentives, deployment)

Scope: the uncommitted diff (policy_data.py, study_configs.py, arms A/D, README paragraph, tests) and the untracked
`experiments/analysis/continuation_credit.py`. Ran `tests/rl/test_policy_data.py` (38 passed) and
`tests/rl/test_followup_arms.py` (72 passed); `ruff check` / `ruff format --check` clean on the changed files.

The code does what it says: in per-tactic credit, a sample with any `FAILING` tactic gets `sequence = min(sequence, 0)`
before `token_credits`. Only explanation tokens read `sequence` there (token_credit.py:53-74), so tactic and closing
credit, `has_signal`, baselines and every other sample are unchanged. Both training paths read the phase's
`policy.data` (training_phase.py:290, resident_trainer.py:233). The trainer normalizes by a constant
(sequences × 256 tokens), so 0-advantage explanation tokens do not dilute the other tokens' gradient. My concerns are
about what the switch leaves out and what it does to incentives nearby.

## Blocking

None.

## Should fix

**S1. The label set is narrower than the incentive it targets, and the cap turns a soft ordering into a sharp
drop.** A wasted continuation after progress costs the same −c (or more) at tactic level whatever its label:
`FAILING | NO_PROGRESS | REDUNDANT_HYPOTHESIS` all get `cost` (grpo_groups.py:271). A terminal unknown or off-graph
state after evidence also gets `cost` (grpo_groups.py:274). An appended open claim gets −c − c′ = −0.4
(grpo_groups.py:269). With the cap, only the `FAILING` ending loses its explanation credit: ≈ s − b ≈ +0.4 becomes 0.
The others keep theirs.
- The `try` route. `nlinarith [...]` that errors and `try nlinarith [...]` that does nothing both give the tactic
  −0.1. A `try` that fails leaves the state unchanged, so it is labelled `NO_PROGRESS`. The explanations then get 0
  and about +0.4. Reasoning that ends its plan with a hedged step (`try`, `all_goals try`, `first | … | skip`) is now
  preferred over reasoning that ends with a step that can fail.
- The claim route reopens a little. An appended open claim keeps an explanation of s − 0.4 − b. That is positive
  whenever s − b > 0.4, which is common on the graph (clean blocks average +0.43 to +0.51). In that case the claim
  beats the 0 an appended error now gets on the explanation channel. This inverts the README's ordering ("an appended
  error or claim never gains"; claim below error) in the channel that drove the bare-`have` drift.
- `continuation_credit.py` cannot see either route. Its "complete on graph" class (`sample_outcome`) includes these
  wasted endings, so the +0.43 to +0.51 comparison class is not clean either.

Fix: cap whenever a tactic after the anchor was charged for waste. That covers labels in `{FAILING, NO_PROGRESS,
REDUNDANT_HYPOTHESIS, UNPROVED_CLAIM}` plus a terminal unknown or off-graph tactic whose gain is `cost`; a
`GroupSample` property next to `has_failing_tactic` would hold it. At the least, before A restarts, split the
script's "complete on graph" into clean versus waste-ending (by label, with a `try` count). Then add the waste-ending
share to the per-phase watch with a stop line.

**S2. The stop/continue decision is not touched, so expecting shorter blocks is not supported by the mechanism.** The
token between two tactics is credited to the next tactic (token_credit.py:35-44). The closing fence after a complete
block gets 0 (token_credit.py:71). So "write another tactic" still pays at P(correct) > c/(c+δ) = 1/3, exactly as
before. The cap only stops reinforcing the reasoning that precedes such blocks. The README motivates the switch with
"Arm C … shortened its blocks where A did not" (README.md:181). The mechanism does not predict that A's blocks will
shorten, and the measured continuation tactics already net about 0 (+8 to +56 per phase).
Fix: state in the README that the per-tactic continuation bet is unchanged. Pre-register what should move (mean
tactics per sample, continue rate, the fails-after-graph share) and check it at phases 2 and 4. If shorter blocks are
the goal, the lever is the tactic-level cost on the failing tactic's own tokens, decoupled from the score so the
baseline does not fall the way it did in the c = 0.3/0.5 replays. That would be a separate switch.

**S3. On the node, there is no evidence that the switch fired or how much it removed.** `PolicyDataMetrics` has no
field for it, so a phase log cannot tell a capped run from an uncapped one. `claim_watch` reports the uncapped
`sequence` as the per-class advantage (claim_watch.py:185-193). The decomposition premium and the bare class's
advantage would then overstate what the explanation tokens actually get.
Fix: add `capped_explanation_sequences` and the summed explanation advantage removed (or the mean
explanation-token advantage of first-round sequences) to `PolicyDataMetrics`. Have `claim_watch` apply
`credited_advantages` with the phase's `policy.data`, or label its column "uncapped".

**S4. Deployment and controls.** A's rerun is running uncapped (phase 5 done). The loop reads `phase.toml` once at
start (loop.py:932), and `followup_arm.py` refuses to rewrite an existing config directory ("an arm's configs are
written once"). So the change reaches A only through a new `followup_configs/followup_A` and run directory, which
means a restart from v0. Hand-editing the running A's `phase.toml` and restarting would leave A with phases 1-5
uncapped and the rest capped, while D is capped from phase 1. That breaks the A/D shared-phase-config control that
`test_followup_arms.py` enforces.
Fix: record the decision in `followup_progress.md`. If A restarts, move both directories aside as for the bug rerun.

## Minor

- **M1. The chosen switch was never replayed.** `continuation_credit.py`'s `FAIL_NEVER_POSITIVE` caps sequence and
  tactics of fails-after-graph samples only. The shipped cap covers every `FAILING` sample (explanation only). That
  includes first-tactic errors and samples without a block, which have a positive `sequence` in groups whose baseline
  is low (for example groups with open claims at −0.45). The README's "Replayed, the alternatives did less" reads as
  if the chosen one was measured. Add a transform that calls `policy_data.credited_advantages` and report how many
  never-on-graph samples it changes.
- **M2. The explanation push is net negative.** Capping removes positive mass, so a trained group's explanation
  advantages no longer sum to about 0. Over trained samples the mean is about −(fails-after-graph share) × 0.38. With
  one pass and KL 0.01 to v0 this is mild, and the explanation-length and distinct-sample health checks watch it. Log
  the mean (S3).
- **M3. Comments and wording.**
  - A.toml/D.toml point to README "Claims"; the paragraph is "Failing blocks' explanation".
  - "About 85%" in the toml comment versus the README's own endpoints: 0.35/0.43 and 0.41/0.51 ≈ 80-81%.
  - policy_data.py:44: "the sample's score" should read "score minus baseline".
  - README.md:190-192: the whole-sequence fallback also happens when the span count differs from the tactic count
    (token_credit.py:53), not only on a token/text mismatch.
- **M4. The cap is a silent no-op under other credit modes.** With `credit = "sequence"` or `"proof_success"` the cap
  does nothing, and nothing refuses it. Refuse that combination where the config is loaded (ValueError), the same way
  C is refused GRPO settings.
- **M5. Clip-fraction and entropy averages count 0-advantage tokens as trained** (policy_trainer.py:709-726). The
  `max_clip_fraction = 0.1` health check becomes slightly less sensitive. Note it in the README.
- **M6. Test gaps.** No test caps a never-on-graph `FAILING` sample that has a positive `sequence`. No test covers the
  whole-sequence cap on mismatch or on a span-count difference, which the README claims.

## Notes

- **Claim switches.** The cap keys on the label, not the gain. A bare claim followed by a failing attempt (all gains 0
  after the claim) is capped too, which reinforces the claim fix; S1 is the exception.
- **Arm D.** Its expert-iteration rounds (SFT on verified proofs) are unaffected, and its GRPO equals A's.
  study_configs allows the key for any arm and `unused_settings` refuses it for C (tested). B1/B2 do not share A's
  reward or credit context (true since the claim switches); say so in the write-up.
- **Truncated and forced samples.** A block cut off mid-tactic or a sample without a block is `FAILING`, so it is
  capped (desirable). Forced-opening samples with clean blocks keep their credit. No new shift there.
- **Study validity.** A's credit has now been tuned twice after seeing its held-out results; C's has not. The
  progress file's caveat stands: the prefix of a failing block is still a useful child in a 16-expansion search,
  while the one-expansion held-out check penalises it fully. The cap moves A toward the held-out metric, so the probe
  run is the measure that decides.

## Verdict

Merge after fixes. S1 at minimum needs the waste-ending split measured, and preferably the cap widened to every
charged continuation. S3 is needed for on-node evidence and S4 must be recorded before A restarts. S2's README
correction and the minor items can come with it.

## Re-review (2026-11-19, fixes in the working tree)

I ran these suites one at a time: `test_policy_data` (45 passed), `test_followup_arms` (72), `test_claim_watch` (21)
and `test_reward_ordering` (123). `ruff check` and `ruff format --check` are clean on `src/lean_search/rl` and the
changed tests and scripts.

**Does `has_wasted_tactic` match the charged cases in `judged_in_block`?** It covers FAILING, or a gain below 0 on a
tactic not labelled proof graph.

The negative gains outside the proof graph are exactly the waste charges:
- a no-op, redundant step or error after the anchor, or before it, gets `cost`;
- a later open claim gets `cost + open_claim_cost`;
- an unknown or off-graph state that ends the block after evidence gets `cost`.

No other negative gain outside the proof graph exists. An off-graph state after an unknown anchor gains
(1 − λ)·μ·q ≥ 0, unknown after unknown gains 0, and an unknown or off-graph state in the middle after evidence gains
0. Tactics after an open claim gain 0 by design; a failing one is still caught through its FAILING label. Leaving out
proof-graph detours is right: they are progress judged on the graph, not wasted tokens.

Two charges are carried on `parts` instead of `gain`, so the predicate misses them:
- **An open claim as the anchor** (R − c′, score −0.45). It never reaches the graph, and its sequence advantage is
  positive only in a group whose baseline is below −0.45.
- **A no-op or redundant first tactic when no tactic reaches a state** (score −0.15). An error at the same place is
  capped through FAILING, so these two are treated differently. Its advantage is positive only when the baseline is
  below −0.15, which happens in groups dominated by open claims.

Both are tiny in mass. For consistency, either add `label in (NO_PROGRESS, REDUNDANT_HYPOTHESIS, UNPROVED_CLAIM)` to
the predicate or say in the README that charges on the anchor are not included. Not blocking.

**Other fixes.**
- Metrics: the counts are correct; only samples whose sequence actually changed are counted. They reach `phase.json`
  through `PhaseOutcome.policy.data`. `grpo_phase_record` (training_phase.py:508-545) does not copy them into the
  `grpo` monitoring family, so the per-phase dashboard does not show them. Minor: add them there.
- `claim_watch` and `bare_have_credit` now read the phase's `policy.data`. Requiring per-tactic credit is enforced at
  `PolicyDataConfig` construction, so a wrong config fails at loop start.
- README: the rule, the tactic-level bet left unchanged, the pre-registered metrics, the fallback cases and the
  tuning caveat match the code.

**README and comment wording (minor).**
- "A tactic charged within its block off the proof graph" should read "not labelled proof graph". A no-op returning
  to an ancestor that lies on the graph is still caught.
- The README lists "an open claim" without saying the anchored one is excluded.
- Three places still say "failing" and should say "failing or wasted": the comment at study_configs.py:50, the
  `EXPLANATION_CAP` comment in test_followup_arms.py, and the test name
  `test_the_failing_block_explanation_cap_is_on_…`.

**Tests (minor).** There is no test for an unknown or off-graph ending after evidence (gain −c), and none showing that
a proof-graph detour is not capped.

**Still open.** S4 is not in this diff; record the restart in followup_progress.md before A restarts. The replay
numbers (30-40% removed; −0.04 to −0.07 capped) come from a node file I did not see.

**Verdict: merge as is.** The anchor-charge gap and the wording, metric-wiring and test items above can follow. S4
must be recorded before A restarts.
