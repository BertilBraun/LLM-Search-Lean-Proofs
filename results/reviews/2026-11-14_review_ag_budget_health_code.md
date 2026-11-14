# Review AG: token-budget phases, run end, seed offset (WP1) and health across arms (WP5), code

Branch `worktree-agent-a1f7eaa0dbb612621` (e40c958 WP1, 3925d19 WP5) against master; read in the worktree. Tests (WSL,
worktree `src` first on the path): `test_loop_budget`, `test_health_across_arms`, `test_options_arm`, `test_phase_signals`,
`test_loop_health`, `test_shipped_grpo_configs`, `test_grpo_trainer`, `test_loop`: 631 passed; ruff check and format
clean. Real-tree checks on `grpo_loop_v1` (node_backup 2026-11-01), with the production `label_graph`, `policy_tactics`,
`block_habits` and the cached Qwen3.5 tokenizer: `scratchpad/habits_check.py` (120 trees each of phases 1, 12, 25) and
`scratchpad/proof_graph_rates.py` (150 trees each of phases 1, 4, 12, 20, 28), in
`C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\`.

## Must fix before merge

1. **The two new tail habits are shares of all judged samples, so they mostly track how often samples reach the proof
   graph, not what happens after it.** `rl/tree_summary.py:312-313` (`block_habits`) and `rl/health_checks.py`
   `with_habits` divide `failing_after_proof_graph` and `unproved_claim_after_proof_graph` by `block_samples`. Only
   samples whose block reaches a `PROOF_GRAPH` state can count, and that share changes a lot. Measured over 150 trees
   per phase:

   | phase | reached the proof graph | failing after it / judged | failing after it / reached | unproved claim / judged | unproved claim / reached |
   |---|---|---|---|---|---|
   | 1 | 10.9% | 1.76% | 16.2% | 0.09% | 0.85% |
   | 4 | 10.8% | 3.82% | 35.2% | 0.29% | 2.68% |
   | 12 | 5.4% | 1.53% | 28.4% | 0.20% | 3.75% |
   | 28 | 7.3% | 2.77% | 38.0% | 0.18% | 2.43% |

   Against phase 1, phase 12 reads 0.87× on the shipped measure (no warning) but 1.76× conditional on reaching the
   graph. So the shipped measure misses the habit whenever the policy or the curriculum reaches the graph less often,
   and warns whenever an arm reaches it more often. That second case is a better policy, or the easier below-band
   statements `compared` prefers. Comparing these shares between A and B2 then compares their proof-graph coverage.
   The unproved-claim share sits at 0.1-0.3%, a few dozen sample-weighted, clustered events per phase, so a 1.5× rule
   on it is mostly noise. Why now: `TreeSummary` is written once per tree into `index.jsonl`, so a denominator added
   after an arm's phase 1 cannot reach that arm's reference without rescanning its trees.
   Fix: add `BlockHabits.proof_graph_samples` (samples with any `PROOF_GRAPH` tactic) and divide both habits by it, in
   `with_habits` and in the below-band variants. Log the reach share beside them. Give the unproved-claim rule a
   minimum count, or chart it only.

## Should fix

2. **A health measurement can delete training data.** `explanation_token_count` runs inside `tree_summary`
   (`loop.py:1063`, `keep_tree`). Any exception in it marks the tree `SUMMARY_FAILED`, which leaves it out of the store
   and out of training, so a decode problem would quietly change an arm's data. One `self.decoder` (an HF fast
   tokenizer) is shared by up to `concurrency` (56) `to_thread` workers at once. Decode is read-only, so the risk is low;
   on real trees it was exact (0 prefix mismatches in 1,962 samples) and cost 0.08-0.13 s per tree on one thread, which
   is fine. Fix: compute the explanation tokens in their own try (on failure: 0 samples, logged) and leave the tree in.
   A test with a decoder that raises should keep the tree.
3. **The loss shares do not measure what their docstring claims** (`policy_trainer.py:163` `loss_shares`, `:768`). The
   value of a GRPO surrogate is about Σ w·A at ratio 1, near 0 by construction (old phase 30: −0.012 per step), while
   the replay term is 0.1 × an NLL of order 0.3-1. The replay share will therefore read about 70-90% in every GRPO arm
   whatever the update did. The KL share (0.01 × k3, about 1e-4) will read about 0. "How much of the update the anchors
   take" is a statement about gradients. Fix: log the three absolute term values per phase and drop the shares. If
   shares are wanted, take each term's gradient norm on one step per phase (one extra backward per term). Keep the
   optimizer steps, which is what DESIGN's 1.5× A-vs-B2 rule uses.
4. **The sampling-only end depends on an unvalidated convention** (`loop_config.py:88-90`, `loop.py:885`
   `run_ended`). `max_generated_tokens` stops only "while no phase is due". With `phase_generated_tokens = 0` (minutes
   mode), step 2's 4-9 h run trains at `max_sampling_minutes` (120). With B ≤ max that is not a multiple of B, a
   training run stops in the middle of a phase and leaves sampled tokens untrained. Also, `ends_with` reads tokens
   1..k while `run_ended` reads 1..k+1, so trees from the drain can end a run that `ends_with` called not last. Fix:
   `parse_loop_config` refuses `max_generated_tokens` without `phase_generated_tokens`, and requires it either
   < B (sampling-only) or a multiple of B. Then have one predicate decide the end, used in both places.
5. **Lost compute is logged but never raises an alert.** Lost searches (`SERVER_FAILURE`, `STOPPED`) are excluded from
   the budget, so real compute can differ between arms at equal counted tokens. On the old run's numbers:
   - Server failures: 32 searches in 15.7k trees (0.2%), negligible.
   - Restarts: 13 sessions; each cut-off loses about the paused-search tokens, about 56 × 30-40k ≈ 2M at concurrency
     56, about 1% of a 192M arm per restart. These are owner-driven, not policy-driven.
   - In flight at the end: about 2-4M, length-biased toward arms with longer (unsolved) searches. Arms differ by a
     fraction of that, under 1%.

   So the rule is not materially exploitable, unless a policy starts failing servers, which nothing would flag. Fix:
   an alert in `close_phase` when `lost_generated_tokens` exceeds about 2% of B, and the arm's run total of lost tokens
   in the end line (`end_text`), so the write-up can state real compute.
6. **The end of a run looks like a crash.** At the end, `run` writes `LoopState.STOPPED` (`loop.py:949`) and exits 0
   with `loop.pid` left behind. `grpo_loop.sh status`, the dashboard and the watchdog cannot tell "ended at phase 16"
   from a SIGTERM or a crash, and the servers keep running and costing money. Fix: add a `LoopState.ENDED` (or a
   `run_end.json` marker) that `status` prints. In `grpo_loop.sh`, document that after the end `stop` must be run to
   free the GPUs.

## Minor

7. **Tokens that are never counted and never logged.** A stop that cancels `keep_tree` while it awaits
   `tree_summary` (`loop.py:1063`, now slower) loses a finished search with no record. A crash between `os.replace`
   and the index append (`tree_store.py` `add`) leaves an orphan tree file. `resident_trainer.prepare_new` trains it
   (it globs `*.json.gz`), but it is not counted and its statement is fed again. Both are rare. Fix: record
   `STOPPED` in a `finally` around the summary, and on start reconcile phase-directory files that are missing from the
   index (log them, then delete or index them).
8. **A torn line stops the loop from starting.** A partial last line in `searches_without_tree.jsonl`
   (`tree_store.py:104`) makes `TreeStore()` raise. That hits the loop and also `grpo_loop.py status` and analyses
   that read while the loop appends. `index.jsonl` already had this problem; now there are two files. Fix: skip a final
   line that fails to parse, with a warning, in both readers.
9. **The production token count is a second, lower count.** `CountingExpander` (`loop_services.py:100`) counts yielded
   batches only, and misses `context.abandoned_batches`, which the search charges (`search.py:530`). So lost and paused
   tokens read slightly below the accounting. They are logged only, so this does not affect the budget; say so in the
   docstring or charge the abandoned batches too. `self.tokens` also keeps an entry for every statement that was given
   up.
10. **A phase can be empty.** Token phases have no tree condition: an overshoot ≥ B (at the design's B = 200k smoke
    test, or after a long benchmark-scoring wait) makes phase k+1 due at its first check with almost no trees, and it
    trains and publishes a near-identical version. Fix: require at least one finished tree in the phase, or at least
    say so in the log.
11. **Seeds.** Every controllable draw of sampling and GRPO/value training moves together: trainer, reference draw,
    `ReplayCycle`, replay selection, v0 value replay (`graph_trainer` by the optimization seed), `torch.manual_seed`
    in `resident.py`, exploration, curriculum. LoRA dropout is 0. The probe, the fixed sets, the evaluations
    (`evaluation_run_config` has no offset), the renamings and the value benchmark stay fixed. With offset 0 the phase,
    curriculum and exploration seeds are pinned to master by tests. Not covered:
    - vLLM's sampler is unseeded, and Lean timeouts run on the wall clock, so even offset 0 does not reproduce a run.
      Say this beside `seed_offset`.
    - The expert-iteration selection and replay seeds (`expert_iteration_data.py:70,86`) must join the offset when
      WP4b brings C/D into the loop.
12. **Resuming an old run.** The explanation-token reference of a pre-change run directory averages the trainer's
    figure (trained samples) with the new all-sample figure from the trees (about 97-104 against 114 tokens), which
    can raise a spurious `explanation_length` alert. Only `grpo_loop_v1` is affected; a note in the README is enough.
    Otherwise new fields default safely, the minutes mode is unchanged (pinned by tests), and `loop.toml` parses.
13. **Phase 1 is a biased reference.** It only holds searches that finished within the first B tokens: short and
    solved ones, while long searches spill into phase 2. This holds in every arm alike, but phase-2 habit shifts partly
    reflect it. Consider `reference_phases = 2`, or note it in the write-up.
14. **Not visible on the dashboard.** The new token fields (`PhaseTiming`, `PhaseRecord`) and the two tail habits are
    not shown, and the long-sampling alert goes to loop.log only. Fine as documented.

## Checked and correct

Budget:
- The single source is `SearchResult.accounting.generated_tokens`, written once per search: the index entry or one
  without-tree record, never both.
- It includes harvesting, feedback rounds and unparsed samples, and excludes evaluations.
- The count is cumulative k·B over finish phases, so the 30 s granularity (about 0.2-0.4M, 2-3% of B at the new
  node's estimated rate) and pause drains are paid back. The only residue is at the last phase.
- Held-over searches count in full in phase k+1. Restarts recompute the boundaries from the two append-only files.

Run and evaluations:
- At `max_phases` the last phase is trained, published, served and health-checked with no early or beside-held-out
  resume, and a restart stops at once.
- `at_each_pause` cannot run twice per phase (`loop_seconds` moves only at training); the hard-stop baseline check
  accepts it.

Health with `None` GRPO statistics:
- Every branch is safe: alerts, `phase_health`, `last_good_version`, the health record read back, and the dashboard
  (null-tolerant).
- The collapse stop reads only the held-out states. Thresholds are unchanged.

## Tests

Mostly behaviour, through the fake loop. Gaps, most important first:
- **A restart in the pause (stage TRAINING and EVALUATING) in token mode** that asserts exactly one training request
  per phase and the same next boundary. The restart tests stop only on tree counts during sampling.
- **Searches held over a pause.** `TOKEN_TOML` runs at concurrency 1, so the "whole tree counts in k+1" rule is
  untested.
- **The two tail habits on a real labelled tree** (the tests feed hand-made label tuples), and an explanation-token
  count with a real BPE token that straddles the fence.
- `test_the_loss_shares_are_of_the_summed_term_magnitudes` restates the formula (see 3).

## Re-review (979e83f)

8 affected test modules: 669 passed three times; ruff clean. Recomputed with 979e83f's health code on all trees of
`grpo_loop_v1` phases 1, 4, 12, 16, 20, 28 (`scratchpad/tail_alerts.py`).

1. **Must-fix: resolved.** Both tails divide by `proof_graph_samples` (below band: the right population). The phase-1
   reference (16.2% failing, 1.08% unproved) gives thresholds of 26.2% and 4.08%.
   - Phase 12 (below band 24.8%, 3.0%) does not warn; phase 4 (reward hacking, 39.0%) does.
   - **Healthy late phases warn**: 20 (35.8%) and 28 (33.8%). The failing tail climbs 16% to 32-36% over a run whose
     probe improved. Should: a rise of about +20 points, `reference_phases = 2` for these checks, or chart-only.
     This can follow merge, since the counts are stored per tree.
   - **The minimum suppresses instead of falling back**: phase 16's below band has 959 graph-reaching samples
     (< 1,000), so both checks are skipped, although all statements (3,689) are at 28.8% / 4.7%, both above
     threshold. Should: fall back to all statements.
2. **Should items: resolved.**
   - Health-only failures keep the tree.
   - `UpdateSize` is right under DDP (replicated LoRA, summed gradients) and comparable across GRPO arms of one LoRA
     shape; a phase without GRPO logs "not measured". C and D's trainer must emit it in WP4b.
   - The run-end rules, FINISHED, `finished.json` and `token_budget.json` work; the pid removal works because
     `background.sh` execs.
   - The lost-token alert works but, at concurrency 84, fires on every restart (about 3M lost against 240k). Minor:
     alert on `SERVER_FAILURE` tokens alone.
3. **base.toml: correct.** Step 2 must override with B above 48M and `max_phases = 0`.
4. **Restart test: the real race is still tested**; only the timing-dependent expectation is gone.
5. **Nothing new and dangerous.** Verdict: **merge**; the two tail calibrations can follow.
