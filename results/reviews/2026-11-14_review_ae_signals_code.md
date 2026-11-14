# Review AE: follow-up signals (WP2, WP3, WP4a), code

Branch `followup-signals` (e7222bb..7e57041) against master; read in `.claude/worktrees/followup-signals`. Tests (WSL):
`tests/rl tests/policy tests/search tests/graph` 1932 passed, 21 skipped; ruff clean. Audit of B2 on 600 solved trees
of phases 20, 25, 30 of `grpo_loop_v1` (17,784 group samples, 2,223 groups) with the production `label_graph`,
`policy_tactics`, `policy_groups`:
`C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\proof_success_audit.py`.

## Must fix before merge

1. **B2 as implemented is not "A without its shaping": it judges the block's *last* state, A and the step-0 analysis
   its *any/first* state. 11.7% of samples flip, and failing tails beat valid ones.**
   `rl/grpo_groups.py:118` `GroupSample.advances_on_proof_graph` (r = 1 iff forward edge and the last reached label is
   `PROOF_GRAPH`) follows DESIGN's B2 row and WP3's test list ("graph then off-graph (0)"). But DESIGN's justification
   for B2 as the control ("85% of A's anchor reward is the 0/1 'reached the proof graph' B2 uses; A and B2 differ by
   δ, the local term, the within-block costs and where the credit lands") and `experiments/analysis/training_signal.py:166`
   (`on_proof_graph`: any tactic labelled `PROOF_GRAPH`, no edge check) both use the other rule. In A
   (`judged_in_block`) a block whose first state is on the proof graph and whose valid tail ends in an unknown/off-graph
   state scores R(proof graph) − c, i.e. its global part stays (1 − λ); B2 gives it 0, the same as a Lean error.
   - Measured: 2,081 of 17,784 samples (11.7%; 30% of the script's positives) pass through the proof graph on a forward
     edge and then continue validly off it: script and A positive, B2 0. Meanwhile 1,857 of B2's 7,025 positives
     (26%) carry a failing tail, every token of which (failing tactic included) is trained up. So B2's gradient prefers
     "good tactic; error" over "good tactic; valid step the search never explored", which A charges equally (−c each).
     A policy can raise r without proving more by failing instead of continuing (or by stopping), and step 2's
     "two implementations must agree" check and the ≥ 95% agreement gate are computed on a different B2.
   - Fix (owner decides; code is one line either way): (a) r = 1 iff a forward edge and *any* state of the kept prefix
     is labelled proof graph: A minus shaping, as the DESIGN argument and the analysis assume, no tail asymmetry; or
     (b) keep the last-state rule and rewrite the DESIGN rationale, saying B2 also differs from A in which state is
     judged. In both cases make `training_signal.on_proof_graph` call the production property and re-run the step-0
     numbers (the "~85% shared reward" claim), so the gate compares the B2 that trains. I recommend (a).

## Must fix before step 2's C round (not before merge)

2. **A phase window cannot select step 2's slices.** `experiments/grpo_expert_iteration.py:186` `loop_inputs` filters
   `index_entries` by `TreeEntry.phase`; the shared sampling run never ends a phase, so every tree is phase 1, `last_phase`
   resolves to `progress.phase − 1 = 0` and `phase_window` raises "empty" (loud, at least). Window 1 and window 4 would
   in any case select the same trees. Cleanest fix: `build`/`count` take explicit tree directories, as
   `grpo_phase.py --trees` does (`[data] tree_directories` or `--trees DIR...`, replacing the phase filter; held-out,
   rejected and minimum-version filters unchanged, minimum 0 for v0's trees). Then A, B1, B2 and C read the very same
   slice directories. Writing slices as phases would mean rewriting `index.jsonl`, which the loop's phase entries,
   health and dashboard read: no.

## Should

3. **B2 rewards sideways and backward moves on the proof graph.** 542 of 7,025 positives (7.7%) reach a proof-graph state
   no closer than the group's node, e.g. `have h6 : 2 / (x + y) ^ 2 ≥ 2` at 16 → 21 remaining steps, `intro` at 1 → 1.
   This is by design (B2 has no δ), but the name "advances" and DESIGN's "advances along the found proof" suggest
   otherwise. Log per phase, for every arm and from the trees, the share of positives with target steps ≥ node steps,
   the failing-tail share and tactics per block, so B2's drift into safe filler or short blocks is visible; no current
   alert watches those (`health_checks` watches bare `have` openings and claims proved only).
4. **Token segments are not by position outside per-tactic credit** (`rl/token_credit.py:51-58`: everything is
   `EXPLANATION`), although WP3's row asks "segments by position whatever the credit". So `mean_explanation_tokens`
   (`policy_data.py:315`) is the whole completion for B1 and B2, and feeds the `EXPLANATION_LENGTH` alert
   (`health_checks.py:337`) and the dashboard. Fix now, cheaply: compute segments with the per-tactic layout whenever
   one span per tactic exists and only replace the values with `whole`; advantages stay bit-identical. WP5 still moves
   the alert to tree counts.
5. **Nothing logs B2's own quantities.** `data_metrics` writes `mean_global_reward`, `mean_local_reward`,
   `local_advantage_share` and trained-group tactic counts, all per-tactic notions; for B2 log the multiplicity-weighted
   mean r over all groups and over trained groups. `tree_statistics.py:271` counts `groups_with_signal` with
   `PER_TACTIC`; pass the arm's credit (the loop already holds it, `loop.py:784`). `reward_replay.py:419` stays
   per-tactic (an offline tool for reward changes; fine). Nothing else that decides (phase end, stop, rollback) depends
   on the mode: `phase_due` counts groups with the arm's credit (`tree_summary.trainable_groups`), the stop and
   rollback read held-out evaluations only.
6. **Test gaps.** B2 on real-shaped trees has no case for a sibling state or transposition onto the graph (1), a
   repeat merged with its executed edge, an unverified proof (0, via `UNVERIFIED_PROOF` not being forward), or a
   goal-closing block that is a sibling of an earlier proof (1). `loop_inputs` (where the window meets the run
   directory) has no test; review Z's blocker was in exactly such untested experiment glue: a tmp run with
   `versions.jsonl`, an index and no `reward_fix.json` would cover it. WP2's row asked for "REPAIR nodes inherit the
   sampled block's value" (true via `dataclasses.replace` in `search.py:639`, untested). Block boundaries are only
   tested with whole-UTF-8 pieces; one case with a multi-byte character split across tokens at the block's first
   character (`ByteDecoder` from `test_token_credit.py`) would pin the shared-range path.

## Minor

7. **Last-label rule against the search's own child.** Advance then a redundant hypothesis into an off-graph node scores
   1; a redundant step whose node is on the proof graph scores 0 (`judge` tests redundancy before proof-graph
   membership). 22 + 15 of 17,784 samples: negligible, but if option (b) of finding 1 is kept, also requiring
   `node_classes[target] == PROOF_GRAPH` makes r exactly "the search's child is on the found proof".
8. **Window edges.** Samples a carried tree took before the pause that opened the window's first phase (version
   published two phases earlier) fall outside every window, since that tree is indexed in phase `first`; if wanted,
   the minimum for phase `first`'s trees could be the version two phases back. In window mode `reward_fix.json` is
   ignored by design, so on `grpo_loop_v1` a window reaching before phase 15 silently includes reward-hacked phases.
   `summary.json`/README of a build record the phases but not `window_phases` or `minimum_version`; add both.
   Rollbacks, rejected versions and a window wider than the run behave correctly (checked against the old
   `versions.jsonl`: phase k's trees are sampled by the version "phase k−1" published). The default path is
   equivalent to master (same entries filter, same minimum via the same trigger match) and pinned by
   `test_without_a_window_the_reward_fix_decides_the_phases_and_versions_as_before` against `read_markers`.
9. **Block log-probability.** Token selection is right at both fences, after a dropped `by` line, for forced and cut
   forced samples, and the assert holds (only the inserted opening has `None`, and its decoded range ends at the block
   start; a misdecode returns `None` before the loop). The unaligned fallback is safe for ordering: a whole-completion
   sum is never above its block's sum (all terms ≤ 0), so such a sample can only rank lower, and expert-iteration
   round 1 saw 0 token mismatches; it is counted (`unaligned_samples`, written to `policy.json` by `run_search.py`).
   With the switch off, merging and order are unchanged (same values, dict insertion order kept). The decode runs
   synchronously on the event loop in `PolicyExpander.sample`; ~10 ms per expansion is fine, and stopping
   `decoded_offsets` at the block's end would halve it. Edges now record the block value with no marker in the tree:
   readers that compare across trees (`expert_iteration/preferences.py` `likelihood_order`, `more_likely`) must not
   pool trees of both settings; record the switch in the tree's run summary. GRPO is unaffected: its ratios use the
   trainer's own re-scored old log-probabilities and `SampledTokens` per-token values, never `Edge.log_probability`.
   Run 6 needs the automation constant re-derived for block sums (−2.8 was for whole samples).
10. **Existing modes are unchanged.** `has_signal` and `token_credits` dispatch to the same values as before for
    `PER_TACTIC` and `SEQUENCE`; the moved alignment functions are byte-identical; the new golden test
    `test_per_tactic_and_sequence_advantages_of_the_design_example_are_unchanged` would fail on any change to group
    advantages, the pre-existing per-segment tests on token credits. Style is fine; `labels: tuple` in
    `test_advantages.py` lacks its element type.

## Re-review (6816f30, 61dce9b, bc44e8a, bcc0da0, 6e534f8, c98ff60, 22ffac4; probe package ignored)

Affected suites 573 passed, ruff clean. Audit with production code, 500 solved trees of phases 4/20/25/30 (14,272
samples): `reaches_audit.py` beside the first script.
1. **Resolved.** No sample scores 1 without a proof-graph tactic or on a non-forward edge. The 0s with a proof-graph
   tactic are all unverified proofs (26). The 0s whose forward child is on the graph are all the accepted redundant
   precedence (12). 22% of positives pass through the graph into an off-graph child, as intended. Failing and valid
   tails now score alike. `training_signal.py` uses `tree_policy_data(credit=proof_success)` and `reaches_proof_graph`,
   so the analysis agrees by construction.
2. **Resolved.** `tree_directories` (exclusive with `last_phase`/`window_phases`) read every `*.json.gz` like
   `grpo_phase.py --trees`, from version 0 minus rejected ones. A first-round version mix is refused unless
   `allow_mixed_versions`. Tested on tmp runs. Minor: `build` refuses a mix only after labelling (run `count` first);
   the below-band share reads 0 for directories; unrecorded versions under `allow_mixed_versions` drop silently.
3. **Resolved.** Segments by position; trained values are `whole` (sequence/proof success) or unchanged (per-tactic),
   identical by construction. 0 mismatches on the 14,272 samples. Equal explanation means across modes pinned by a test.
4. **Resolved.** New tests: sibling, transposition, merged repeat, unverified proof, `round_trees` on tmp runs, the
   repair's log-probability, and a multi-byte first character.
5. **New, minor.** `block_mean`'s unaligned fallback stays conservative (completion sum ≤ block mean). `reward_replay`
   builds `TacticReward` without `steps_gained`, so take no no-closer share from replays. Failing tails are 37% of
   positives here, but stopping scores the same, so no incentive is left. Neither this nor the redundant precedence
   needs a change before step 2.

**Verdict: merge.**
