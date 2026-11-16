# Review AS: expert iteration inside the loop (WP4b), code

**Verdict: merge after fixes.** M1 is a test the design requires. S1 and S2 should land before arm C runs. I found no
path that publishes a half-trained or stale adapter, skips a version or publishes two.

Branch `worktree-agent-af77525dfc814e9c3` (2db23ca, 8 commits on 40c266d; master has no code changes since). WSL:
`tests/rl/test_loop_expert_iteration.py` **44 passed**; `tests/rl/test_followup_arms.py` and
`tests/graph/test_expert_iteration_round.py` **74 passed**. The golden test, run on a `git archive` of 98604e0 (master's
code plus the test), **passed**, so the pin was really made on master. I also ran a scratch script for one round whose
data fills less than one optimizer step (S1). No node and no full suite.

## Must fix before merge

- **M1. The WP4b row's restart test "in publish" is missing for rounds.** DESIGN.md row 4b and review AB M6's
  resolution ask for "restarts in build, train and publish". The branch tests the build (`test_a_restart_during_a_rounds_build_*`),
  the training (`restart_in_round_training`) and the gap between D's two updates (`restart_between_the_updates`). It
  has no test of a restart in `PhaseStage.PUBLISHING`. That stage takes a separate path: `publish` (loop.py:1887-1898)
  writes the `grpo` and the new `expert_iteration` lines, then `handed_off_version` looks up the merge in host memory
  by the **round's** adapter path, then `record_durably` runs in the background (~13 GB copy). I read the code as
  correct: `clear_stale_handoff` keeps the merge while the version awaits its record, and `next_version` picks the
  round's adapter. No test holds it, though, and a kill during the durable copy is the likeliest kill on the node.
  - Fix: one D test with `FakeTrainer(handoff=...)`, killed after the round phase's version was served from host
    memory and before its record. Check that the phase publishes one version, that its policy adapter is
    `expert_iteration/adapter`, and that the servers loaded the handed-off round merge. Add the same check for C. Also
    pin the number of `expert_iteration` lines per phase (see N7).

## Should fix

- **S1. A round with enough examples can train zero optimizer steps and still be recorded as trained.** The skip rule
  is `summary.data.train_examples >= expert_iteration_min_examples` (loop.py:1859; default 100, loop_config.py:149).
  Its own comment says 100 examples is "about one optimizer step". `plan_steps` drops the last incomplete step, so a
  round plus replay that packs into fewer than 4 x 1 micro-batches of 16,384 tokens has **0 steps**. Packing is never
  perfect, so rounds of about 100-115 examples often fall here. I ran it (tiny model, `micro_batches_per_step` raised
  until the data is under one step): `steps 0, curve 1 point, replay change 0.0, parameter change 0.0`. The adapter
  is saved unchanged, `ExpertIterationOutcome` is not None, the record says `skipped = false, optimizer_steps = 0`,
  and the phase publishes a new adapter path that holds the old weights. Nothing breaks, but "skipped" is wrong.
  - Fix: decide in the trainer, where the steps are known. If `plan_steps(data.train, ...)` is empty, return no round
    (`expert_iteration = None`) and let the loop record the round as skipped (`round_record` then needs the reason).
    Or raise the floor to about 2 steps' worth. Test both sides of the boundary.
  - Practical risk is low: the hand-run round 1 had about 680 examples per phase. The case matters for early or sparse
    phases.
- **S2. No test ties the in-job trainer to the hand-run trainer that step 2 uses.** C's learning rate and window come
  from step 2's `grpo_expert_iteration.py train`, which runs `training/sft.train` with DDP.
  `expert_iteration_training.train_expert_iteration` is a re-implementation: it sums gradients with `sum_gradients`
  and has its own validation schedule. By reading, the arithmetic matches. DDP's mean of the per-rank gradients of
  `world_size / completion_tokens x loss` equals the sum at `1 / completion_tokens`. The warmup, cosine, clipping and
  `plan_steps` calls are the same, and the halfway validation matches the hand-run's `interval_steps = ceil(steps / 2)`
  (grpo_expert_iteration.py:466-470). The tests only compare the round with itself on two loaders (`rounds` fixture),
  so a later edit to either side would go unnoticed. If the two diverge, arm C no longer runs the recipe step 2 chose.
  - Fix: a CPU tiny-model test where `sft.train` (single process) and `train_expert_iteration` on the same
    `TrainingData`, seed and initial adapter give equal adapters and step losses. If feasible, a 2-rank gloo variant,
    including a step where one rank has no micro-batch.
- **S3. Contradictory keys are accepted silently.**
  1. `ARM_SETTINGS` (study_configs.py:36-44) lets any arm set `phase.policy.data.credit` and
     `phase.policy.optimization.learning_rate`. For C, `phase_config_text(..., grpo=False)` drops the whole `[policy]`
     table (loop.py:667), so a C overlay that sets a GRPO rate (an easy slip when filling in the placeholders) is
     ignored without a word.
  2. A GRPO arm may set `loop.training.expert_iteration_window_phases` or `_every_phases`, and `parse_loop_config`
     ignores them under `policy_update = "grpo"`. Only the `[expert_iteration]` table is refused
     (study_configs.py:167-169).
  3. `parse_loop_config` (loop_config.py:423) does not refuse `expert_iteration_config` set with
     `policy_update = "grpo"`.
  - Fix: in `overlay_configs`, refuse `phase.policy.*` when `policy_update = "expert_iteration"`, and refuse
    `loop.training.expert_iteration_*` when it is `"grpo"`. In `parse_loop_config`, refuse a non-empty
    `expert_iteration_config` under GRPO.
  - What is already refused at load: `every_phases`, `window_phases` or `min_examples` below 1, no persistent trainer,
    no recipe, no `[initial] policy_adapter`. That is tested, except `every_phases = 0`, which goes through the same
    `min(...) < 1` check. `recipe_refusals` runs at `GrpoLoop` construction, before anything starts. D cannot change
    its KL reference, since that key is not in the allow-list.

## Notes (minor or for later)

- **N1. The peak-memory figure under-reports what decides an OOM.** `torch.cuda.max_memory_allocated`
  (expert_iteration_training.py:207) leaves out the caching allocator's reserve and the CUDA context. It is also reset
  after the first validation (l. 146). For the stated purpose, "does the round fit", also record
  `max_memory_reserved`, the largest over the ranks. `StageMemory` already records reserved memory after each stage.
- **N2. Part of a round's time appears in no metric.** The build's seconds are only in the log line ("built in N s").
  `PauseSegments` deliberately has no field for them. `ExpertIterationPhase.training_seconds` covers the steps only:
  not the data assembly on 4 ranks, the three main-rank validations (1,000 replay examples each while the other ranks
  wait at the barrier) or the save. The design asks for "training time ... reported apart" and, under "Optimizer steps
  per phase", for "the replay tokens". The record has replay *example* counts and `trained_tokens` with the replay
  mixed in. Add `build_seconds`, the round's wall seconds and the replay completion tokens to `ExpertIterationPhase`.
  The round's own validation loss at the start and end would also help (it is in phase.json, under checkpoints).
- **N3. The replay validation subset changes every round.** `training_data` draws it with `f"{config.seed}/validation"`,
  and the replay seed now ends in `/phase-k` (expert_iteration_rounds.py:50). The within-round alert is fine. The
  replay-loss *level* is not comparable across rounds, so there is no forgetting trend over C's 16 phases. Use the
  recipe's seed without the phase for the validation draw.
- **N4. The optimizer and schedule restart every round.** Each round builds a new AdamW, warmup and cosine
  (expert_iteration_training.py:116-125), like the hand-run round and like GRPO's phases. That is deliberate in effect,
  but the README section does not say it. With W = 4, every block goes through four of these restarts. One line in
  rl/README.md is enough.
- **N5. `built_for` compares only `(last_phase, window_phases)`** (expert_iteration_rounds.py:58-63). Between a kill
  and a restart, an edited recipe (selection caps, seeds, `seed_offset`) would reuse the old build. Also, `build` does
  not delete an old `summary.json` before rewriting `train.jsonl`, and writes the summary with a plain `write_text`. A
  torn summary would make every restart fail in `read_build_summary` until someone deletes it by hand. Unlikely. A fix
  is to store the round's `[data]`/`[replay]` with the build and compare them, delete the summary at build start, and
  write it atomically.
- **N6. Trainer timeouts.** The timeouts are now kept per kind (value phase or not, with a round or not). Each kind's
  first phase gets 120 min, then 2x the median of that kind. With W = 4, C's round grows over phases 1-4: phase 4's
  value-plus-round phase is measured against phase 2's, which had half the window. The first phase's model build
  inflates the median, so a false timeout is unlikely. If one happens, it costs one retry, and in D a repeated GRPO
  update. Check the actual durations on the node (below).
- **N7. Records on a restart in PUBLISHING.** If the loop is killed after `write_expert_iteration_metrics` and before
  the version's record, the restart writes the `expert_iteration` line again, as it already does for `grpo`. Readers
  that sum `phase_trained_tokens` must keep the last line per phase. `ExpertIterationPhase` is not in
  `families.FAMILIES`, has no dashboard page, and its replay-loss alert is only a `loop.log` line, not a
  `monitoring/alerts.py` alert.
- **N8. A C phase whose round is skipped, with no value model due,** still publishes a version and restarts the 8
  servers (`swap = "restart"`, about 200 s) for unchanged weights. This is consistent with "one version per phase".
  Note it, or skip the server restart when both adapters are unchanged.
- **N9. Test gaps beyond M1 and S2.**
  - The handoff tests check the merge's *marker* (`[weights.adapter ...] == [round_outcome.adapter]`) and that a merge
    exists. They do not check that its tensors are base plus the round's adapter (rather than the GRPO update's).
  - The real `grpo_expert_iteration.py build` is never run on a `round.toml` the loop wrote (only
    `FakeExpertIterationBuilder`).
  - No `TrainerRank` test covers a C value phase with a round.
  - Several tests pack independent facts into one tuple assertion, against "one logical assertion per test name":
    `test_arm_cs_value_phase_without_a_round_trains_the_value_model_alone` (four facts),
    `test_the_health_check_judges_the_version_holding_the_round`, `test_arm_ds_round_keeps_the_kl_reference_at_the_start`.
- **N10. House style.**
  - `train_kind` returns `tuple[bool, bool]`, used as a dict key (loop_services.py:594). A `NamedTuple` would say
    which bool is which.
  - `GRPO_ONLY = "grpo"` (study_configs.py:47) repeats `PolicyUpdate.GRPO.value`.
  - `GrpoLoop.expert_iteration_build_seconds` is an attribute that passes a value from `train` to `finish_phase`.
    Return it with the outcome instead.
  - Several comments run past one line: `LoopTrainingConfig.policy_update` (6 lines), the `ExpertIterationResult`
    field comments (2-3 lines), `ExpertIterationPhase`. Everything else checks out: no abbreviations, type hints
    everywhere, dataclasses for every record and for `PolicySettings`, `GrpoUpdate` and `ExpertIterationRound`,
    `assert` for invariants (`summary is not None`, `request.expert_iteration is None` in the per-phase trainer) and
    `ValueError` for config.
- **N11. Arms A and B.** Their records do not change (the golden). Outside the records, two things change:
  - The persistent trainer always gets `--data-root`.
  - phase.json gains `"expert_iteration": null`, which old files read through its default.

  The golden runs the loop with `FakeTrainer`, so the `TrainerRank.train` refactor is covered by the unchanged
  tests/graph/test_resident_trainer.py, not the golden. By reading, the GRPO path is unchanged: `train_grpo` is the old
  body, the memory stages come in the same order, timings get + 0, the merge marker is `config.policy.model`, and
  timeouts go under the `(value, False)` kind.

## Checked and correct

1. **One version per phase.**
   - `TrainerRank.train` (resident_trainer.py:379-450) runs GRPO when the phase config has a policy section, then the
     round, then the value model, then one policy merge. The merge takes the last update's in-memory LoRA, so in D
     that is the round's.
   - `next_version` uses `PhaseOutcome.policy_adapter()` (the round's adapter when a round ran) under
     `phase_trigger(phase)`.
   - `check_health`, the held-out run of the served version, retention (`ADAPTER_KINDS` includes `expert_iteration`;
     `kept_adapters` goes by the versions' adapters) and the next phase's `initial_adapter` all see that version.
   - D's KL reference stays `[initial] policy_adapter` (tested).
   - A skipped round publishes the unchanged policy (C) or the GRPO update (D) under the phase's trigger, and the
     handoff takes unchanged weights from the current version.
2. **Data.**
   - The loop runs the hand-run builder itself as a subprocess, so selection, caps, easy share, held-out filters and
     the version rule are the hand-run round's.
   - The window `max(1, k - W + 1)..k` is built from `phase_window`. Its minimum version is the version published by
     the phase before the window (0 at the start).
   - Replay is 30% Lean and 10% math by completion tokens, from the shared `expert_iteration_data.training_data`, with
     files under `--data-root`. They are the same files as base.toml's replay.
   - The shipped recipe equals `expert_iteration_1.toml` except for the seeds and what the loop fills in (tested).
   - Zero solved trees build an empty, well-formed summary (`data_summary` and `selected` are empty-safe), which then
     skips.
3. **Rates and adapters.** GRPO's rate (`phase.policy.optimization.learning_rate`) and the round's
   (`expert_iteration.sft.optimization.learning_rate`) are separate keys with separate placeholders. A round continues
   the published adapter (C) or the GRPO adapter that `train_grpo` saved, after the barrier (D). The model structure is
   checked against GRPO's (`recipe_refusals`, plus the `ResidentModel.trainable` assert). C builds its resident policy
   from the round's settings and adds nothing to /dev/shm beyond what A uses.
4. **Failure.** An exception or OOM in a rank ends the job. `PersistentTrainer.train` retries once, then raises.
   `phase.json` is written only after the merges, and the reply only after `phase.json`, so a dead round never
   publishes. A stop cancels the build's process group. An orphaned build blocks the next start through the
   `children/**/*.pid` check.
5. **Restarts.**
   - In the build, it builds again. In training or between D's updates, it trains the whole phase again from the
     published adapter, reusing a finished build of the same window. `clear_stale_handoff` drops the first attempt's
     host merges in the TRAINING stage. Already published: `publish` skips retraining and records.
   - Token budgets are unaffected: rounds add nothing to the tree store.
   - `job_seconds` subtracts the build, so the pause's trainer-start segment stays honest.
6. **Golden.** Created in 98604e0 on 40c266d's code (verified by running it there) and unchanged since. It pins
   phases.jsonl, the `grpo`, `value_training`, `budget`, `health` and `timing` lines, the versions, and every phase
   config text sent, over three phases with a value phase.
7. **Overlays.** C and D use the same mechanism as A and B. A GRPO arm with `[expert_iteration]` is refused, and
   placeholders are refused by `followup_arm.py`. D's loop config is A's plus the four round keys, D's phase config is
   A's, and C's is the shipped phase.toml (tested).
8. **Seeds.** Selection and replay use the recipe's seed plus `/phase-k`, the trainer uses the phase number, and
   `seed_offset` moves all three. The hand-run configs keep their seeds.

## Smoke on the node before arm C runs

1. **One C round inside the persistent job, at the chosen W and rate, on step 2's trees or a short C run.** Record:
   data assembly seconds on 4 ranks; steps (at least 1 at the 100-example floor, see S1); peak allocated *and* reserved
   memory with 16,384-token packed micro-batches beside the parked value model; the main-rank validation time while
   the other ranks wait; compiled graphs (a new packing pattern may recompile).
2. **The same build and rate through the hand-run `train`.** Compare adapters and loss curves with step 1, unless S2's
   test lands first.
3. **One D round phase.** GRPO then the round, one handoff merge, and the servers load it. Check that the version's
   adapter is `expert_iteration/adapter` and that the health line names that version.
4. **The in-loop build.** Run `grpo_expert_iteration.py build` with 16 processes beside the trainer's preparation
   thread and the loop's search-metrics labelling. Check host memory and free /dev/shm, the build time for the largest
   window (W = 4), and that the tokenizer loads offline.
5. **Kills.**
   - The loop during the build: the orphaned build blocks restart with a clear message, and a finished orphan's
     summary is reused.
   - One trainer rank during the round: one retry, one version.
   - The loop during `record_durably` of a round phase (M1's case, for real).
6. **Durations of C's phases 1-4 with W = 4** against the 2x-median timeout (N6).
