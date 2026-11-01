# Review Y: design of expert-iteration round 1 (branch `expert-iteration-1`, 7f95602 + 51f00c1 on affea2b)

Scope: the design of the round. That covers which data it selects, the training recipe, leakage, the evaluation and
decision rule, the KL reference, rollback, and the node window. Code correctness is only covered where it changes
the design. I read the plan (scratchpad `expert_iteration_plan.md`) and `git diff affea2b..expert-iteration-1`
(`rl/expert_iteration_data.py`, `experiments/grpo_expert_iteration.py`, `configs/grpo/expert_iteration_1.toml`,
`health_checks.py`, `grpo_loop.py`, `loop.py`, `loop_config.py`, `probe_rating.py`, `serving.py`, the README section
"Expert iteration"). I also read the parts of `tactic_labels.py`, `graph_labels.py`, `training/sft.py`,
`policy_trainer.py`, `statement_sources.py`, `pool_v3.toml`, `loop.toml`, `phase.toml`, the search template, review G's
noise model and DESIGN.md's reward-fix notes that the round depends on. No loop data is available locally, so the
volume and noise estimates below come from the configs, earlier reviews and the plan's own numbers.

## Summary

The round is well built. It uses the recorded prompt and token ids, which removes format drift. Rejected and pre-fix
versions are filtered per expansion. The caps are deduplicated by state, and their order is global and seeded. The
publish path reuses the rollback code. The KL reference is configurable. I found no blocker. Several design choices
need to change before the round runs, or at least need measuring:

- The SFT trains at T = 1 on samples drawn at T = 0.8, so it sharpens the policy beyond what the filter selects.
- The definition of "easy" lets the repeatedly searched easy states escape the 20% cap.
- The validation loss mixes the expert-iteration data with the replay data, so forgetting cannot be seen.
- The decision rule in effect requires about +1.1 points of observed improvement, not the "not worse" it is described
  as.
- The held-out gate compares against v0, not v25.
- The node window is about 2 h 40 min on the plan's own estimates, with no dry run before the GPUs are taken.

## Findings

### 1. should-fix: SFT at temperature 1 on samples drawn at 0.8 sharpens the policy beyond the filter's signal

**Problem.**
- Every example is a sample drawn at T = 0.8:
  - `[policy] temperature = 0.8` in `configs/grpo/search/visible_student_v2.toml:68`;
  - `default_temperature = 0.8` in `phase.toml:95`.
- GRPO scores those tokens at the sampling temperature: the logits are divided by `ExpansionTexts.temperature`
  (rl/README "Trainer"; `phase.toml:6`: "trains on its sampled tokens at the sampling temperature").
- `training/sft.py` takes the NLL of plain logits (`CompletionLoss`, sft.py:291-332). Maximising
  E_{x~p^(1/0.8)}[log p(x)] at T = 1 moves p itself towards p^1.25. Once v26 serves at 0.8 again, it samples roughly
  as v25 did at T ≈ 0.64.
- This adds to the selection signal that rejection-sampling fine-tuning is meant to contribute:
  - Per-sample success on the held-out states will likely rise from sharpening alone. That biases the held-out gate
    (finding 6) towards passing.
  - The 8 samples per expansion become less diverse. That costs the search breadth, and it shrinks GRPO's
    within-group variance after the round: fewer trainable groups, so GRPO gets slower still.

**Evidence of scale.** A phase moves the advantaged tokens' ratio by about 1.0005, about 5e-4 nats per token. An epoch
of consistent NLL gradient at 5e-5 with Adam (about 200-330 steps, below) moves the NLL of the policy's own samples
by tenths of a nat per token. The temperature term is a large part of that.

**Fix (pick one).**
- (a) Give `sft.py` an optional per-example logit temperature: divide the logits by the recorded `temperature`, as
  `policy_trainer` does, for the expert-iteration examples only (replay stays at T = 1, as in GRPO's replay). Then
  only the filter moves the T = 0.8 sampling distribution.
- (b) Keep T = 1, accept the sharpening knowingly, and add a diversity check to the gate (finding 8).

In either case, record the step-0 and final validation NLL on the expert-iteration validation set alone (finding 3).
Divided by the completion tokens, it measures how far the round moved the policy.

### 2. should-fix: "easy only if easy in every tree" lets the most repeated easy states escape the easy cap

**Problem.**
- `selected_completions` marks a state easy only if every tree's expansion of it was easy:
  `easy = all(member.easy for member in members)` (expert_iteration_data.py:384).
- `TreeBlocks.easy` requires all 8 first-round samples to be all-proof-graph blocks, and an infrastructure failure
  makes a state not easy (`:251-256`).
- The states searched most often are the below-band statements' roots and early states, the easiest in the data.
  Each repeat is a fresh chance for one off-graph sample.

**Computation.** A state whose per-sample proof-graph rate is 0.95 is easy in one expansion with probability
0.95^8 = 0.66. It is easy in all of 3 trees with probability 0.29, and in all of 5 with 0.13. The states the cap was
written for therefore mostly count as hard, so the reported "easy share" understates the real one. The cap protects
least exactly where the plan's risk 2 ("below-band statements re-solve the same easy proofs") lives.

**Fix.**
- Pool the first-round samples over all expansions of the state: easy when at least 7/8 of the pooled samples are
  all-proof-graph blocks (infrastructure failures left out of the count).
- Report the share of examples from below-band statements in the build README. `TreeEntry.summary.below_band`
  already carries the origin (`statement_sources.outcomes_by_origin`, :90-95).

### 3. should-fix: one validation loss mixes the expert-iteration and replay validation sets, so forgetting is invisible

**Problem.**
- `run_training` appends 1,000 replay validation examples to the expert-iteration validation examples
  (grpo_expert_iteration.py:340-347).
- `sft.validation_metrics` returns one token-mean loss over the whole list (sft.py:398-418).
- The expert-iteration part (about 5% of 10-15k examples, about 600) will fall steadily, because it is the policy's
  own distribution being sharpened. The replay part is the forgetting signal, and it is averaged into the same
  number. A rising replay loss can therefore show as a flat or falling curve.

**Fix.**
- Evaluate the two sets separately. Either call `validation_metrics` twice in `on_evaluation`, or pass a list of
  named sets to `train`.
- Stop or flag the round if the replay validation loss rises more than a few percent over step 0. The original
  SFT's validation loss is the reference.
- Step 0 is already evaluated (`evaluate_now(0)`, sft.py:545), so the baseline comes free.

### 4. should-fix: the decision rule in effect demands about +1.1 points observed, and its reference is a mix of versions and conditions

**Problem 1: the margin.**
- The rule keeps v26 if `paired.difference >= 0 and paired.lower > -0.02` (grpo_expert_iteration.py:91, 438). The
  README describes this as kept "unless the paired difference may be worse".
- The −2 margin was taken from "the run-to-run noise per third". Review G's model has about 21 discordant problems
  per pair of runs of one third, that is 12.6% (2026-10-29_review_g.md:37-40).

**Computation.**
- Over the whole set: about 63 discordant problems out of 501, so the SE of the mean paired difference is
  √63 / 501 ≈ 1.6 points, and the 95% half-width is about 3.1 points.
- `lower > −2` therefore holds only when the observed difference is at least +1.1 points, which makes the `≥ 0`
  condition redundant.
- How often v26 is kept, by its true effect:

  | True effect | P(keep) |
  |---|---|
  | 0 | ~24% |
  | +1.5 points | ~60% |
  | +3 points | ~89% |
  | −1 point | ~9% |

- That is a reasonable rule for an intervention that also sharpens the policy (finding 1). But it is a superiority
  test, not the non-inferiority test the docs describe, and the owner should choose it knowingly.

**Problem 2: the reference.**
- Each problem's latest run comes from v21, v23 or v25, one third each.
- At the observed +3 points over 9 phases, that mix is about 0.7 points below v25 on average, which biases the test
  towards keeping v26.
- The reference runs also used older published value models.
- Reference runs ran beside sampling with 56 of 112 REPLs. v26 runs alone at 112. The total load on vLLM is similar
  (112 searches either way), so the effect of the 30-minute cap is probably small (about 3% of searches stop on it,
  `loop.toml:213-216`). But it is one run per side, and review W notes that run-level effects are not in the
  bootstrap, so the real coverage is below 95%.

**Fix.**
- State the rule's real operating characteristic in the README and DESIGN, or change it to what is meant. For
  non-inferiority: `difference ≥ 0`, or `lower > −3`. To demand evidence: keep the rule as it is.
- In `compare`, also print:
  - the paired difference split by reference version (the v25 third alone, the v23 third, the v21 third);
  - `wall_clock_stops` of v26 against its references, and the difference recomputed on the problems where neither
    run hit the cap;
  - the joint-scale rating of v26 against `latest_pass` (already computed) as a tie-breaker.
- If the signs disagree, roll back.

### 5. should-fix: the shortest-route and open-claim filters drop verified structured blocks; measure the bias before training

**Problem 1: the shortest-route filter.**
- `block_verdict` drops any block whose last state is not `node_steps − tactics` steps from a proof
  (expert_iteration_data.py:211-220). `node_steps` is the tree's shortest route in top-level tactics, over every
  sibling (`tactic_labels.remaining_steps`, :233-236).
- So at any state where some sample closed the goal in one tactic (`nlinarith [...]`), every verified multi-tactic
  closer is dropped. Examples are `have h := ...; nlinarith [h]` and a `have … :=` decomposition: their last state
  is 0, while `node_steps − k < 0`.
- This filter also does useful work: it is what removes closed-form filler inside successful blocks. Inside a
  closing edge the filler state is labelled PROOF_GRAPH, because `judge` checks `is_on_proof_graph` before
  `adds_only_closed_form_hypotheses` (tactic_labels.py:340-345).
- The cost is a systematic tilt towards the fewest-tactic, automation-heavy block at each state. That is the
  direction of the hacking episode's "linarith/nlinarith openings" and "have … := 1,261 → 242" (DESIGN.md:1068-1070).
  Review T's revert rule treats "tactics per complete block down > 25%" as damage.

**Problem 2: the open-claim filter.**
- `leaves_claim_open` is set for a bare claim that the block leaves open even when the tree later proves it, and the
  tactic is then still PROOF_GRAPH (tactic_labels.py:290-310).
- So `CLAIM_LEFT_OPEN` also drops verified decompositions: claim now, prove it in the next expansion.
- The post-fix reward ranks "proved claim > failed attempt ≥ bare claim" (DESIGN.md:1081). The round therefore
  teaches something stricter than the reward does: never decompose across expansions.

**Fix.**
- Make `build` report the block-length distribution, the `have … :=` share and the linarith/nlinarith-opening share
  for three groups:
  - the kept examples;
  - all blocks that passed the label filter (all PROOF_GRAPH, before the route and claim checks);
  - the reference phases' `BlockHabits` (or the last 3 phases' health lines, which already hold tactics per complete
    block).
- Write an explicit rule into the README: if the kept examples' mean tactics per complete block is more than 25%
  below the phases', relax the route filter. Two ways to relax it:
  - (i) the shortest route in expansions (edges) rather than in tactics: a closing block always qualifies;
  - (ii) keep a block with `r_last < node_steps` whose every tactic strictly reduces the remaining steps, and drop
    filler explicitly with `adds_only_closed_form_hypotheses` and `adds_only_redundant_hypotheses` on its
    consecutive states.
- Count separately the claims left open whose tactic is PROOF_GRAPH (verified decompositions). Consider keeping them
  up to a capped share.

### 6. should-fix: the held-out gate compares with v0, not with the version the round continues

**Problem.**
- The gate is `candidate ≥ 0.9 × version 0` for valid Lean and success (grpo_expert_iteration.py:434-437).
- The held-out set is 512 states × 8 samples, so the per-sample SE is about 0.8 points (more, since samples cluster
  by state).
- v26 can therefore lose several points against v25 and still pass, as long as it stays above 0.9 × v0. With
  finding 1, per-sample success may rise while valid Lean or diversity falls.

**Fix.**
- Also load the latest held-out run of a non-rejected version before the round (v25's, or the newest one; the
  directories are `held_out_states_vNNNN`).
- Require valid Lean ≥ (that run's rate − 2 SE) as well as the 0.9 × v0 rule.
- Print both comparisons.

### 7. should-fix: the round does not fit the 2.5 h window with margin, and the GPUs are taken before anything checks the training's size

**Problem.** The plan's own figures sum to about 2 h 40 min. The two largest items can each run 20-30 min over.

| Step | Estimate |
|---|---|
| Stop | 2 min |
| Train | 40-50 min |
| Publish | 3-5 min |
| Servers and `check` | 4-6 min |
| Held-out states | 5 min |
| Probe | 60-80 min |
| Decision and restart | 5-10 min |

- **Training.** It has 13-22M tokens at 7-9k tokens/s, which is 25-52 min, plus loading, compiling and tokenising the
  replay. There are also 5 evaluations of about 1M tokens each:
  - they run on the main rank only, while three GPUs wait at a barrier (sft.py:527-545);
  - they take about 1.5-3 min each.
  - The total is 40-70 min.
  - `train()` saves only at the end (sft.py:607), so a late crash loses the whole run.
- **Probe.** One third takes about 50 min at 56 REPLs (`loop.toml:214-216`). The whole set at 112 REPLs is about 75
  min plus the tail of searches near the 30-minute cap, so 75-90 min. The plan says 60-80.

**Fix.**
- Add `train --dry-run`: tokenise, apply the replay budgets, `plan_steps`, print the steps, the tokens and the share
  of completion tokens per source, then exit before loading the model. Run it on the CPU while the loop samples.
  Stop the loop only when steps × (tokens per step / 8k per second) fits.
- Set `[sft.optimization] max_steps` as the hard cap.
- Cut the in-training evaluations to 3: step 0, the midpoint and the end.
- Run the held-out states first and skip the probe if they fail. The README orders them that way but does not say to
  skip the probe.
- Before `train`, check `df /dev/shm`. The persistent trainer's parked bases and handoff (about 28 GiB,
  `grpo_loop.sh:42`) must not still occupy the 32 GiB tmpfs that NCCL uses.

### 8. should-fix: the gate does not measure diversity or habits, though they are what the round is most likely to change

**Problem.** The decision uses the held-out rates and probe solves only. The health checks that would catch collapsed
diversity, or a shift in explanations and habits, only fire after phase 26 and only as warnings:
- `distinct_samples < 0.75 ×` the reference;
- `explanation_characters < 0.7 ×`;
- `bare_haves`.

The v26 run produces the needed data anyway:
- the probe trees in `evaluations/probe_v0026/`;
- 8 samples per held-out state.

**Fix.**
- In `compare`, compute `BlockHabits` and the distinct blocks per expansion from the v26 probe trees, using the same
  function the loop uses for "Block habits of probe slot <s>". Compute them for the reference slots' trees as well.
- Compute the distinct blocks per held-out state for v26 and for v25's held-out run.
- Roll back if the distinct blocks fall below 0.75 × v25's or the median explanation characters below 0.7 × v25's.
  These are the loop's own thresholds, applied before the restart instead of after it.

### 9. should-fix: phase 26 trains on v25's samples as if they were v26's; stop the loop right after a publish instead

**Problem.**
- After the restart, phase 26 trains on its interrupted trees, "sampled by both versions" (rl/README:851).
- The old log-probabilities are the trainer's own, under v26, and there is no importance correction
  (README "Trainer", line 190).
- Across one GRPO phase, about 1.0005 per token, that is harmless. Across the round it is a large step (finding 1),
  so phase 26's advantages from v25 samples are applied to a policy that already moved.
- `sampler_agreement_by_version` will also show a large gap for v25's samples in phase 26. The README asks the owner
  to check that the round's samples "look like earlier phases'". The v25 rows will not, and that is expected.

**Fix.**
- Build whenever convenient. Then stop the loop right after a phase publishes and sampling starts, so the next phase
  holds almost no samples from the version before the round. Train from that newest version, with
  `last_phase` = the phase that just closed.
- Alternatively, record in the README that the v25 rows of phase 26's `sampler_agreement_by_version` will diverge.
- The README's version numbers (`--version 26`, `rollback --version 25`, the trigger "from v25") are hard-coded. Write
  them as "the version `publish-adapter` printed" and "the version before it".

### 10. minor: the replay shares are counted in tokens including prompts, but the loss is normalised over completion tokens

**Problem.**
- `replay_token_budgets` uses `token_count`, prompt plus completion (expert_iteration_data.py:456-459, :450-452).
- `sft.train` scales the loss by the step's completion tokens (sft.py:554).
- Expert-iteration examples are about half prompt (about 190-250 prompt tokens against about 210 generated in the
  held-out run). Math solutions are mostly completion.
- So by gradient the shares are roughly 56% expert iteration, 28% Lean and 16% math, not 60/30/10.

**Fix.** Budget by `completion_token_count`, or print the completion-token shares in the train summary. The dry run
from finding 7 would show them.

### 11. minor: rollback after the round skips v26, and leaves the KL reference pointing at it

**Problem.**
- `last_good_version` takes the newest version whose phase health line had a clean held-out evaluation
  (health_checks.py:464-477).
- The loop checks the held-out rates of the version a phase published (loop.py:1319). v26's offline run is never
  read, as the README says.
- If v27 (phase 26's publish) collapses, the automatic rollback goes to v25 or earlier and discards the round, even
  though v26 passed the same held-out test.
- `kl_reference_policy_adapter` still names the round's adapter. GRPO then continues v25's policy while being pulled
  towards v26, and the reported "KL to the starting policy" starts at KL(v25 ‖ v26) rather than near 0.

**Fix.**
- After the restart, request a held-out evaluation at phase 26's pause (`request-evaluation --target
  held_out_states`), so that v27 gets a healthy record soon.
- Document the rule in the README: after an automatic rollback past the round, choose deliberately. Either
  `rollback --version 26` by hand, or unset `kl_reference_policy_adapter`.
- A later code change could let `last_good_version` also accept versions with a passing offline held-out summary.
  Writing a synthetic health line would overwrite the phase's record, because `read_health_history` keys records by
  phase.

### 12. minor: moving the KL reference is right, but the dashboard and the threshold need to show the switch

**Assessment.**
- KL to v0 sat flat at about 0.053 under a 0.01 coefficient while GRPO's net movement is tiny. That suggests the
  penalty is near its balance point, that is, it binds.
- Kept with v0 as the reference, it would pull the round back. Moving it to v26 is correct.
- The free reference scoring in phase 26 depends on the string match between `current.policy_adapter` and the
  configured path:
  - the publish stores `str(adapter.absolute())`;
  - the config holds the literal path.
  A path through a symlink, or a different `LEAN_SEARCH_CHECKPOINTS`, only costs one extra scoring pass, so this is
  low risk.

**Problem.**
- The `kl_to_starting_policy` series, and its absolute 0.5 threshold, silently change meaning at v26. The tile will
  read near 0, and the total drift from v0 is no longer measured.
- The habit reference phases (1-2) are unaffected, which is fine: the round's effect on habits shows against them.

**Fix.**
- Record the KL reference adapter in the phase outcome or health line, and mark the switch on the Training chart.
- Optionally score KL to v0 once, offline, on phase 26's sequences, to know the total drift.

### 13. minor: leakage is excluded correctly by name; add one cheap check on content

**Assessment.**
- Probe and gate statements are excluded from the curriculum (`statements.held_out`, `statement_sources.py:129`) and
  dropped again in `build`.
- Pool v3 deduplicates statements across corpora and is built from decontaminated corpora (`pool_v3.toml:1-4`), so
  name matching is reliable inside the pool.
- miniF2F is excluded by name.
- Held-out states are excluded by exact goal key only. Their statements come from Goedel SFT v2 and STP Lean Workbook
  validation proofs. Pool v3 drops every statement selected for tracing, which probably includes them. If it does
  not, states of the same statements that differ from the held-out states (other hypothesis names, other steps)
  enter the SFT data.

**Fix.** In `build`, also count the trees whose `formal_statement` (whitespace-normalised) equals:
- a held-out state's `step.formal_statement`, or
- a probe, gate or miniF2F statement.

Report the count, which should be 0.

### 14. minor: the selection keeps whatever filler survives in a tree's only proof, and could use feedback-round successes

**Problem.**
- When the tree's only proof at a state is the filler block, `node_steps` includes the filler step, so the block is
  on the shortest route and kept.
- The phase-level closed-form filler share is about 1%, so the effect is small. Still, the build summary should show
  it, since filler was part of the reward-hacking episode.

**Fix.** Add `closed_form_filler_share` (the `BlockHabits` measure) for the kept examples to the build README.

**Suggestion for a second round.** States the first round failed but the feedback round solved are the hard ones. A
hindsight example would pair the first-round prompt with the feedback round's verified block, retokenised.

### 15. minor: wording

- README: "easy states (every first-round sample a proof-graph block, which GRPO gives no advantage)". GRPO still
  ranks such samples by score: gain, steps, and c per wasted tactic (`phase.toml:2-6`). Write "little advantage".
- README "Decision": "lower 95% bound above −2 points (the run-to-run noise per third)". See finding 4. The
  whole-set interval is about ±3 points, not ±2.

## Answers to the questions asked

- **The SFT target.**
  - All-PROOF_GRAPH plus no open claim is a sound verified target.
  - The shortest-route filter makes it the fewest-tactic block per state (finding 5). Hashing does make the choice
    among the kept blocks independent of length, but the filter in front of it is length-biased.
  - The explanations are not filtered, only reported. Compare their p10, median and p90 with the reference median
    (findings 5 and 8).
  - At 5e-5 for one epoch the round moves the policy by orders of magnitude more than a GRPO phase does. The main
    risk is sharpening and lost diversity, not forgetting (findings 1 and 8).
- **Replay.** 30% Lean and 10% math is adequate against forgetting, and generous for data this close to the policy.
  It is about 44% by gradient (finding 10). What it lacks is a separate measurement (finding 3).
- **Post-fix data and caps.** Post-fix-only per expansion is right. The caps of 2 blocks per state and 6 states per
  statement handle the repeat searches. The easy cap does not, because of how easy is defined (finding 2).
- **Leakage.** Probe, gate and miniF2F are reliably excluded by name. The held-out states are excluded only by exact
  key: add a content check (finding 13).
- **Evaluation.** The rule is valid but stricter than described, and its reference is biased by about 0.7 points in
  v26's favour (finding 4). The held-out gate is too lenient (finding 6). It misses diversity and habits (finding 8).
- **KL reference.** Moving it is right. Make the switch visible (finding 12), and handle a rollback past the round
  (finding 11).
- **Rollback.** The manual path is safe: `rollback --version 25` re-merges v25 in 3-5 min. The automatic path skips
  v26 (finding 11).
- **The window.** It is tight, with no dry run before the GPUs are taken (finding 7).

## Verdict

**Not yet ready. It is ready once findings 2, 3, 4 (the decision documented or changed), 6 and 7 (dry run and a step
cap) are done.** They are small:
- the pooled easy definition;
- two validation sets;
- the held-out comparison with v25 in `compare`;
- a `--dry-run` with `max_steps`;
- edits to the README and DESIGN.

Finding 1 is the one real design decision: either train at the sampling temperature, or accept the sharpening and
gate on diversity (finding 8). One of the two should be in place before the run. Without either, a probe gain cannot
be told apart from a lower effective temperature, and a lost-diversity regression would surface only after GRPO
restarts. Findings 5 and 9 cost nothing on the node if the build reports the block statistics and the stop is timed
right after a publish. Everything else can follow the round.

## Re-review (6d2a6ec)

I read `git diff 51f00c1..6d2a6ec`, mostly in the worktree `agent-aadf25b31c554727b`:
- `expert_iteration_data.py`, `expert_iteration_decision.py`, `grpo_expert_iteration.py` (train, dry run, compare);
- `probe_rating.paired_comparison`, `tree_summary.search_habits`, the `sft.py` validation sets;
- `health_checks.continued_version` and `publish_adapter_by_hand`, `grpo_loop.sh stop`;
- the three variant configs, and the README section "Expert iteration" with its node sequence.

The node build has changed the numbers my estimates rested on. It kept 6,826 training examples, 2.9M tokens of which
1.28M are completion tokens: a quarter of the plan's 8-13M. With replay that is about 5M tokens per epoch, about 76
optimiser steps of 65k tokens.

### Status per finding

| # | Status | Note |
|---|---|---|
| 1 sharpening (T = 1 on T = 0.8 samples) | **Accepted by the owner, documented** | The README's "Sharpening" paragraph and DESIGN.md say it correctly. It now also affects the variant screen (N1). |
| 2 easy cap | **Fixed** | `is_easy` pools the first-round samples over every tree (at least 7/8, infrastructure failures left out). The samples are tallied for every expansion that passes the version and held-out filters, so a tree in which the state was not solved counts against easy, which is right. `CompletionSelector` keeps a global top-k per state as trees arrive, so memory stays bounded and the result matches selecting from all trees at once. The below-band share is reported. |
| 3 one mixed validation loss | **Fixed** | The expert-iteration loss is the main validation loss, and the replay loss is a separate `ValidationSet`. Both are in `training_summary.json`, at three evaluations. Remaining gap: the screen's "rose more than a few percent" is not a number. Write one, e.g. 2% over step 0 (step 0 is identical for all three variants, since they share the same start). |
| 4 decision rule | **Fixed (documented and instrumented)** | The rule is kept and now described as a demand for evidence, with the operating characteristic quoted. `compare` prints the difference per reference version, the difference without wall-clock stops, both sides' stop counts and the joint-scale ratings. "A rating below the latest pass while the paired difference is positive is a reason to roll back" is advice for the operator only, not one of the coded checks. That is acceptable, but say so. |
| 5 route and claim filters | Deferred | `compare` now prints the bare-have share and the tactics per complete block from the probe trees, so the effect will at least show afterwards. No threshold acts on it. |
| 6 held-out against the reference | **Partly fixed** (should-fix) | See R6 below. |
| 7 window and dry run | **Fixed for one candidate**, but see N3 and N4 | `train --dry-run` on the CPU prints the examples, completion-token shares and steps. `train` refuses before using any GPU time when the adapter exists, when the base is wrong, or when disk or `/dev/shm` is short. It runs three evaluations. The README orders the held-out states before the probe. The training is now short (about 76 steps per epoch), so no `max_steps` is needed. |
| 8 diversity and habits in the gate | **Fixed** | Distinct blocks per expansion at least 0.75× and the median explanation at least 0.7× the references' probe trees. These are the loop's own `[health]` fractions, and the default `RewardConfig` uses `off_graph_min_expanded_nodes = 4`, the same as `phase.toml`. |
| 9 stale samples, hard-coded versions | **Fixed** | The README says to stop right after a publish. `grpo_loop.sh stop` now waits up to 300 s and removes `loop.pid` only after the loop has exited. The diverging `sampler_agreement_by_version` rows are documented. No version numbers are fixed in advance. `publish-adapter` refuses an adapter whose version a phase has since moved on from (`continued_from.json`), and still allows the second variant of the same round. |
| 10 replay shares by completion tokens | **Fixed** | `replay_token_budgets` and `examples_within_completion_tokens`. The dry run prints the shares. |
| 11 rollback past the round | **Fixed (documented)** | The manual choice and `request-evaluation --target held_out_states` after the restart are in the README. The code change to `last_good_version` was not made, which is acceptable. |
| 12 KL dashboard marker, 13 content-level leakage check, 14 filler | Deferred | Acceptable for this round. |
| 15 wording | **Fixed** | |

**R6. The held-out check against the reference is unpaired and uses a per-sample SE that is too small.**

**Problem.**
- `candidate.valid_rate >= reference.valid_rate - 2 × sqrt(p(1-p)/n)` (expert_iteration_decision.py:57, :71-75) has
  three gaps:
  - n = 4,096 samples, but the 8 samples of a state are strongly correlated, because the state's difficulty
    largely decides validity;
  - the reference run's own noise is not in the bound;
  - the two runs are on the same 512 states but are not paired.
- With p ≈ 0.61, the bound is about 1.5 points. The true SD of the difference between two runs of equal policies
  is about 1.4-1.9 points, for a within-state correlation of 0.1-0.3.

**Effect.**
- A candidate exactly as valid as its reference fails this check 14-21% of the time on noise alone.
- In its own `compare`, that rolls back a good round.
- In the head-to-head it silently decides for F.

**Fix.**
- Pair per state (same states; mean per-state difference of valid samples out of 8, bootstrapped over the 512
  states), and require the lower 95% bound above about −2 points.
- Minimal alternative: use 2 × sqrt(SE_ref² + SE_cand²) and inflate it by the design effect. That alone brings the
  false-fail rate under about 5%.

### Problems in the three-variant sequence

**N1. should-fix: screening on the lowest expert-iteration validation loss ranks the variants by how hard they
trained, which means how much they sharpen.**

**Problem.**
- The expert-iteration validation set is the policy's own samples at T = 0.8. Fitting them with T = 1 logits
  lowers their NLL through sharpening alone (finding 1, accepted).
- With about 76 steps an epoch, overfitting is unlikely to reverse that. So the screen will almost surely order the
  variants C < B < A.
- The consequences:
  - A, the planned and gentlest variant, is never published or probed;
  - F (the default whenever S does not clearly beat it) is the most sharpened variant;
  - B and C differ only in epochs, so the two probes measure close neighbours and say little about the dose.

**Fix (no code).** Use the replay screen to drop variants that forgot. Of the rest, bracket: publish the gentlest
survivor first as F, the default, and the strongest survivor as S. S then has to beat F head to head before it is
kept, and the two probes span the range of doses. A cleaner, small code alternative is to score the expert-iteration
validation loss with logits divided by the recorded temperature, where pure sharpening raises the loss instead of
lowering it.

**N2. should-fix: the winner rule keeps nothing in one case where it should keep S.**

**Problem.**
- Step 7 reads: "S if it passes its own compare and beats F; else F if it passes its own; else none".
- Take the case where S passes its own `compare`, F fails its own, and S is not at least about +1 point over F
  head to head. The paired difference against F needs a lower bound above −2, so S would need +1 point observed.
- The rule then keeps nothing, although S passed the same test that would have kept F.

**Fix.** S if it passes its own and (F fails its own or S beats F); else F if it passes its own; else none.

**N3. should-fix: the held-out pre-check that saves a probe cannot be run with `compare`.**

**Problem.**
- Step 5 says to run the probe only "if it passes `compare`'s held-out checks".
- `compare` calls `whole_set_run(found.runs, version)` first (grpo_expert_iteration.py:592), which exits with "No
  finished whole-set probe run" before computing anything.
- The operator would have to apply the 0.9 × v0 and reference − 2 SE rules by hand, twice, under time pressure.

**Fix.** Add `compare --held-out-only`, which runs only the held-out checks and exits non-zero on a failure, or have
`compare` print the held-out checks before it requires the probe run.

**N4. should-fix (owner confirmation): the off-loop time is now about 4.5-5 h, not 2.5 h.**

| Step | Time |
|---|---|
| Stop | 2 min |
| Train A, B and C (README: 15-20, 15-20 and 30 min) | 60-70 min |
| Screen | 5 min |
| F: publish 5, servers and check 6, held-out 5, probe 75-90 | 91-106 min |
| S: the same plus a stop | 93-108 min |
| Three compares (each labels about 1,000 probe trees on one process) | 10-20 min |
| Final rollback merge, if any | 0-5 min |
| Restart | 5 min |
| **Total** | **about 4 h 30 min to 5 h 10 min** |

The README gives no total. The owner should confirm this window, and the recurring watchdog should cover the whole
of it.

To cut the time:
- skip S's probe when S's held-out run is worse than F's (the paired check from R6);
- run the probe-tree labelling in `compare` on a process pool, or cache it between the three calls.

**N5. minor: two looks raise the false-keep rate.** If both variants are truly neutral, at least one passes its own
`compare` with probability about 30-38%, against about 24% for a single candidate. The two tests share the same
reference runs, so they are positively correlated. Put that in the README's "What the probe rule means".

**N6. minor: losing variants stay non-rejected.**
- When F wins, `rollback --version F` rejects S. When none wins, `rollback --version k` rejects only S, and F keeps
  its whole-set probe and held-out runs as an ordinary version. When S wins, F likewise stays.
- Later `compare` runs exclude F only while it is newer than the round they continue. A later round continuing a
  newer version would take F's whole-set run as many problems' reference, along with the joint-scale fit, although F
  never served the loop.
- Fix: reject every published variant that is not kept (`rejected_versions.jsonl` with a reason), or exclude by
  hand-publish trigger in `earlier_references`.

### Verdict

**Ready to run once N2 and N3 are fixed and the owner has confirmed the 4.5-5 h window (N4).** N2 is a one-line
change to the README rule. N3 needs a small `compare` option, or a printout before the probe check.

Strongly recommended before the run, and free:
- N1: bracket the gentlest and the strongest surviving variant, and make the gentlest the default;
- a number for the replay screen (finding 3).

R6 should be fixed too. Its noise can roll back a round as good as its reference with probability about 1 in 5,
and a design-effect-inflated difference SE is a few lines.

Everything else from the first review is fixed, documented, or deferred by the owner's choice.

## Final check (d018335)

I checked these against `git diff 6d2a6ec..d018335` and the README section "Expert iteration".

- **N1 (screen): sound.**
  - `screened` drops a variant whose replay loss rose more than 3% from its first evaluation to its last, and treats
    a missing replay curve as a failure.
  - Of the survivors, in the order gentlest to strongest, it publishes the first as F (the default) and the last as
    S.
  - The expert-iteration loss no longer ranks anything, and the docstring says why.
  - The README covers one survivor (publish it alone) and none (restart, nothing published).
- **N2 (winner rule): correct.** The rule is "S if S passes its own and (F fails its own or S beats F); else F if F
  passes its own; else neither". It is the same in README step 7 and in `against_verdict`'s printed text.
- **N3 (`compare --held-out-only`): correct.**
  - It reads only the three held-out runs and the reference version, never a probe run.
  - It exits 1 on a failure. Steps 5 and 6 gate the probe on it.
- **R6 (paired held-out check): sound.**
  - It uses the per-state valid rate from each run's `trees/<state>.json.gz`, which `search_states` writes for every
    held-out run, through `root_samples`, the same count as `sample_success`.
  - It is paired by state name and bootstrapped over the states, with a lower bound above −2 points.
  - With no readable trees it yields NaN and the check fails closed. That is the safe direction, but a missing
    reference trees directory would reject every variant.
- **Also sound:**
  - `stopped_loop_refusal`, shared by `train` and `publish-adapter`: the loop's pid, live jobs, or a stage other than
    sampling.
  - `continued_version` now also refuses a rejected base, or a base that a rollback has replaced since. That does not
    block S: F's trigger is not a rollback's.
  - In the F-won path, `rollback --version F` publishes F's adapter path verbatim, so it matches the
    `kl_reference_policy_adapter` that `compare` prints.

**Runnable as written: yes.** Two notes for the operator, neither of which blocks the run:
1. If a variant's probe was skipped, then `compare --version <it>` and any `--against` that names it exit with "No
   finished whole-set probe run". Read that as "fails its own compare", as step 6 says, and apply the step 7 rule to
   what remains.
2. Before stopping the loop, check that `evaluations/held_out_states_v<the reference version>/trees/` holds the 512
   trees (see R6). The reference version is the newest version up to k that has a held-out run and is not rejected.

Still open, minor: N6. When no variant wins, F stays a non-rejected version. Reject it by hand if it should not serve
as a reference in later rounds.

**Verdict: GO.**
