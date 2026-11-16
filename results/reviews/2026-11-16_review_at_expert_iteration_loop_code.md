# Review AT: expert iteration inside the loop (arms C and D), code by simulation

**Verdict: merge.** No must-fix found. S1-S3 should land before arms C and D start on the node.

Branch `worktree-agent-af77525dfc814e9c3` at **2db23ca**. While I was working, the worktree held uncommitted edits
(`RoundSkip`, refusals of unused overlay settings, and others). Every result below was therefore re-run on a
`git archive 2db23ca` snapshot, not on the worktree. I ran the production loop with the branch's fakes
(`tests/rl/loop_fakes.py`, `test_loop_budget.token_world`, `test_loop_expert_iteration.round_world`) in WSL. My scripts
and tests are in `C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_at\`
(`tests/test_review_at_*.py`, `equivalence.py`, `golden_check.py`, `publish_crash.py`, `arm_configs.sh`, results in
`snapshot_results.txt`). At the snapshot the branch's own `test_loop_expert_iteration.py`, `test_followup_arms.py`
and `tests/graph/test_expert_iteration_round.py` pass: **118 passed**. Not run: a node or a GPU, and the real-data
builder (item 7, see the end).

## Must fix

None.

## Should fix

- **S1. A crash during the publish writes the phase's round record twice.** I crashed once or twice in phase 4's
  publish, then restarted:
  - the merge on the disk path (`publish_phase`), or the durable write on the handoff path (`record_durably`);
  - on the handoff path, also `servers.serve` before the version's record.

  The result was a second `expert_iteration` line for phase 4 (`[1, 2, 3, 4, 4, 5, ...]`, and three lines after two
  crashes). In D there was also an extra `grpo` line, and in a value phase an extra `value_training` line. This
  happened in 12 of the 60 restart cases: C and D, merge × {disk, handoff} × {once, twice}, and serve × handoff ×
  {once, twice}. Versions, phase records, tokens and training starts matched the uninterrupted run in all 60.

  Cause: `GrpoLoop.publish` writes the metrics (`loop.py:1897-1898`) before the version is recorded, and the restart
  sees `current.trigger != phase_trigger(phase)` again.

  This is **pre-existing for GRPO**: the same crash on master with arm A gives 7 `grpo` lines for 6 phases and 4
  `value_training` lines for 3 value phases (`publish_crash.py`, disk merge, handoff merge and handoff serve). The
  branch adds a new family with the same flaw. That family is the only per-phase record of C's update. The design's
  "optimizer steps per phase" comparison (A against B2, C's trained tokens) would count a phase twice unless readers
  deduplicate it.

  Fix: write the three families once per phase, for example behind a marker in the loop's progress, or after the
  record with a check. Alternatively, have every reader keep the last line per `last_phase` / `policy_version`. Test
  it with a crash in the merge and in the serve.
- **S2. A round with zero optimizer steps is recorded and published as trained.** Setup: the branch's tiny-model
  harness (`tests/graph/test_expert_iteration_round.py` helpers), 6 examples, and a step bigger than the data (the
  remainder of a step is dropped, `sft.plan_steps`).

  `train_expert_iteration` returns `steps 0` and saves the start adapter unchanged (`adapter_change` 0.0, curve
  `[0]`). `round_record` then writes `skipped=False, optimizer_steps=0, mean_loss=None`.

  In the loop, C publishes a "trained" round that changed nothing, and an extra merge and wake. This is reachable: the
  minimum of 100 examples is commented as "about one optimizer step" (`loop_config.py`,
  `expert_iteration_min_examples`), so rounds of roughly 100-150 examples can plan 0 steps after packing.

  The uncommitted worktree edits add `RoundSkip.NO_OPTIMIZER_STEP` for the record. The trainer should also skip the
  round, so that no unchanged adapter is published as the round's.
- **S3. Round settings without rounds load silently.** Arm A's loop config with `expert_iteration_every_phases = 4`,
  `expert_iteration_window_phases = 4` or `expert_iteration_config = "r.toml"` loads, and no round ever runs. The
  same holds for `overlay_configs` with an A overlay setting `loop.training.expert_iteration_*`, and for a C overlay
  setting `phase.policy.data.credit` or `phase.policy.optimization.learning_rate` (both unused in C). A D overlay that
  forgets `policy_update` would therefore run as A without a word.

  The uncommitted edits refuse a recipe without rounds (loop config) and unused overlay settings (`unused_settings`),
  but not `expert_iteration_every_phases` / `_window_phases` in a loop config with `policy_update = "grpo"`. Refuse
  those in `parse_loop_config` too.

## Notes

- **N1. The new family is not on the dashboard.** `RunReader` reads C's and D's `expert_iteration.jsonl`, all 24
  columns, and `run_alerts` runs on simulated A, C and D runs without error. But `ExpertIterationPhase` is not in
  `families.FAMILIES` (`families.py:752`), and no page or chart shows it. In C the GRPO charts are empty, so a C
  round's size is visible only in `loop.log` and the jsonl. The replay-loss alert is a `loop.log` `Alert:` line, which
  `loop_errors` picks up (inferred from reading).
- **N2. Contradictions that load (observed).** These may be wanted, but each is silent:
  - C with `expert_iteration_every_phases = 4`: phases 1-3 train no policy at all.
  - D with an interval larger than `max_phases`: never a round.
  - A window larger than `max_phases`.

  A one-line warning at load would do.
- **N3. A reused build is recognised only by its window** (`built_for`, `expert_iteration_rounds.py:58`): the summary's
  `(last_phase, window_phases)`. Inferred from reading: a recipe selection change, a new seed offset or a rejected
  version added between a finished build and the restart reuses the old data. Comparing the seed and
  `rejected_versions` too would close it.
- **N4. The round's peak GPU memory covers only part of the phase** (reading): the peak is reset after the first
  validation (`expert_iteration_training.py:144-146`), so it covers neither that validation nor D's GRPO update before
  the round. "GRPO + round in one process" is therefore not measured by `peak_memory_gib`; see the node list.
- **N5. The fakes cannot pin token boundaries on the handoff path.** With `persistent = true` and the trainer's host
  handoff, which is what the arms run, searches resume before the durable write. The fakes' tree-to-phase assignment
  then depends on event-loop timing: arm A on itself gave `[3,3,2,3,...]` against `[3,3,3,3,...]`, and master against
  master differs the same way (93-154 differences, all tree placement and what follows from it). The branch's golden
  file and its round tests run the disk path only. Trainer requests, versions, the event sequence and served weights
  were identical across master, master again and the branch on the handoff path too.
- **N6. Arm C's phase records show 0 trees and 0 groups** (reading `resident_trainer.train`: `len(grpo.parts)` is 0
  without a GRPO section). The log reads "Phase k trained ...: 0 trees, 0 groups, an expert-iteration round". This is
  harmless: nothing downstream reads `outcome.trees`.

## What I simulated

| Check | Setup | Outcome |
|---|---|---|
| A/B unchanged: records | 6 phases, value every 2, credits per_tactic (A), sequence (B1), proof_success (B2); master src+tests vs master again vs branch src with master's fakes vs branch src+fakes; every file under the run (trees decompressed), trainer requests, events, served weights; timestamps and `*_seconds` dropped, `status.jsonl` left out | disk path: **identical** apart from phase.json's new `"expert_iteration": null` and one tree's `started_phase`, which flips between two master runs as well; handoff path: master is not reproducible against itself (N5), and requests, versions and events are identical |
| A/B unchanged: configs | `followup_arm.py` on A, B1, B2 (placeholders filled), master vs branch | identical apart from the output directory in `phase_config` |
| Golden file | `tests/rl/golden/grpo_only_loop.json` recomputed 10× on master 6575e2f and 10× on the snapshot | equal 10/10 and 10/10 |
| C and D, 8 phases | window 4, D every 4, `max_phases = 8`, value every 2, persistent, handoff and disk | one version per phase in A, C and D; C rounds at 1-8 with windows `(k, 4)`, each continuing version k-1's adapter, no GRPO request; D rounds at 4 and 8 only, GRPO 1-8, the build after the pause's release and before `train 4`; versions in D `policy ×3, expert_iteration` twice; KL reference `start-adapter` throughout; token boundaries and tokens (disk) and value cadence `[2,4,6,8]` with the same windows identical across A, C and D; `max_generated_tokens = 1000` ends all three after phase 4; health judged versions 1-8 |
| Restarts | crash in phase 4 at: before the build, after the build, before training, between GRPO and the round (D), during value training after the round, after `phase.json`, in the merge or durable write, in the serve; once and twice in a row; C and D; disk and handoff (60 cases) | versions, phase records, tokens (disk), builds (one finished build per round; after one the build is reused) as uninterrupted; every training of phase 4 started from published v3 (no round trained onto a half-updated adapter); **12 cases duplicate metric lines (S1)** |
| Degenerate data | real `CompletionSelector`: all states easy, zero trees, one statement (validation fraction 0.5), one hard state among 20 easy; loop with the fake builder at 0, 99 and 100 examples plus a crash before training | all easy: 0 examples (20 easy states dropped); zero trees: 0; one statement: wholly validation, 0 train; easy share capped; the loop records `skipped` with the count, C publishes v3's adapter, D publishes GRPO alone, and the restart decides the same; 0 optimizer steps: S2 |
| Config validation | every 0 and -4; window 0 and -1; minimum examples 0; unknown `policy_update`; misspelled key; string window; D without a starting adapter; D not persistent; C without a recipe | all 11 refused at load with a `ValueError`; contradictions that load: S3, N2 |
| Records readers | `RunReader`, `downsampled` and `run_alerts` on simulated A, C and D runs; C and D loop configs from `followup_arm.py` loaded, with `recipe_refusals` against the real phase template and recipe | all read; no refusals; N1 |

**Not run (item 7):** the real-data builder. WSL has neither the `Qwen/Qwen3.5-4B` tokenizer nor the old run's held-out
sets or held-out states file. Rebuilding a run directory for it would have taken well over the 20 minutes allowed. The
loop calls the hand-run `grpo_expert_iteration.py build` itself on the round config it writes (`loop_services.py`,
`SubprocessExpertIterationBuilder`), so the two paths share the selection code by construction (reading).

## Node smoke tests (only checkable on the 4x RTX 3090 node)

1. **One C phase and one D round phase on the persistent trainer.** `optimizer_steps > 0` and a non-zero
   `parameter_change_norm`. Exactly one policy merge in `/dev/shm/.../handoff`: the round's, and in D not GRPO's too.
   The published adapter is `phase_000k/expert_iteration/adapter`. `phase_parameter_change_norm` is at least the
   round's change.
2. **GPU memory in D's phase 4.** Read `nvidia-smi` and the trainer log across GRPO, park, round and merge, in one
   process, with no OOM. Record the true peak over both updates, not only `peak_memory_gib` (N4). Note the round's
   fresh AdamW state beside the parked models' CUDA contexts.
3. **`/dev/shm`.** Parked models (~28 GiB) plus one policy merge plus, in value phases, the value merge, with
   headroom. No second copy of the policy base for the round.
4. **Round build.** Seconds and peak host memory of 16 processes beside the paused searches' REPLs, for a 4-phase
   window (the hand-run round: 2,947 trees, ~80 s). The build's `summary.json` must be in
   `<run>/expert_iteration/phase_000k/`.
5. **Time per round.** Round training seconds and the pause's total against A's pause, and the train timeout of the
   first round phase (120 min for the first of its kind).
6. **Stop during a build** (`deployment/grpo_loop.sh stop` while `build.log` grows). The build's process group must
   be gone, `children/expert_iteration/build.pid` removed, and the restart must rebuild. After a `kill -9` of the loop
   during a build, the restart must refuse while the builder lives.
7. **Replay inside the trainer.** `--data-root` reaches the trainer, the replay files resolve, and the Lean and math
   replay counts in the `Expert-iteration update of phase k` line are non-zero.

## Re-review (2026-11-16)

**Verdict for head 041389e: merge.** S1, S2 and S3 are resolved, and nothing new needs fixing before C and D start.

I tested git-archive snapshots of 68a6970 and then of head 041389e, never the moving worktree. My scripts and tests
are in the same scratchpad directory: `tests/test_review_at_rereview.py`, `tests/test_review_at_torn.py`,
`run_rereview.sh`. Results are in `rereview_results_68a6970.txt` and `rereview_results.txt`.

At head, the branch's `test_loop_expert_iteration.py`, `test_followup_arms.py`, `tests/graph/test_expert_iteration_round.py`
and `tests/monitoring/test_store.py` give **200 passed**. All my review tests together give 271 passed and 20 skipped
(combinations that do not exist, such as arm A at a round's build). The one failure is the known one: the fakes'
token boundaries on the handoff path are not reproducible, even master against itself (N5).

- **S1 (duplicate records after a crash while publishing): resolved.**
  - *Setup.* Every training attempt now writes its own numbers into `phase.json` (GRPO steps, value trees, round
    steps), so a stale record shows. I crashed at phase 4 at every point: before and after the build, before
    training, between the updates, during value training, after `phase.json`, in the merge or durable write, and in
    the serve. Each crash happened once and twice in a row, on the disk and the handoff path, for arms A, C and D:
    80 cases.
  - *Result.* In every case there is exactly one `grpo`, `value_training` and `expert_iteration` line per phase. The
    lines sit at the right phases: GRPO 1-8 (none in C), value 2, 4, 6, 8, rounds C 1-8 and D 4 and 8. Each line
    holds the numbers of the `phase.json` the version was published from. After a crash once `phase.json` was written
    the phase trains again, and the record holds the second attempt's numbers. A crash after the record but before
    the version keeps the first record, which belongs to that same, published outcome. My original 60 cases now match
    the uninterrupted run in full.
  - *Torn last line (041389e).* At each publishing crash point (merge on disk, merge on handoff, serve on handoff), I
    cut the last line of `grpo`, `value_training`, `expert_iteration` or all three at the first byte, at half, at all
    but the last byte, and as a whole line without its newline: 48 cases.
  - *Result.* Every case restarts once and publishes through phase 8. There is one record per phase and kind,
    holding the published outcome's numbers, and every line of the three files parses.
  - *68a6970 without this commit.* A torn `grpo` line stopped every later restart with `JSONDecodeError`.
  - *Damaged complete lines.* A cut last line *with* its newline, and a damaged middle line, both stop the loop
    loudly (`JSONDecodeError`) as intended. See N7.
- **S2 (zero-step round): resolved.** The trainer now checks `plan_steps` before training and returns no round
  (`resident_trainer.py`). The loop records `skipped = true, skip = "no_optimizer_step"`. I ran it with
  `stepless_phases = {4}`, with no crash and with a crash after `phase.json`, in the merge or in the serve, on both
  paths (16 cases).
  - C publishes v3's adapter unchanged.
  - D publishes its GRPO update alone.
  - There is one round line per round phase, the same after every restart.

  The branch's `test_a_round_trains_only_when_its_data_fills_an_optimizer_step` passes. `train_expert_iteration`
  called directly still saves a 0-step adapter, but the resident path no longer reaches it.
- **S3 (round settings without rounds): resolved.**
  - Refused at load: a GRPO loop config with `expert_iteration_every_phases`, `_window_phases` or `_config`.
  - Refused by `overlay_configs`: an A overlay with a round interval, window or round learning rate, and a C overlay
    with `phase.policy.data.credit` or `phase.policy.optimization.learning_rate`.
  - My 11 bad configs are still refused at load.
  - The shipped C and D overlays still write and load, with no recipe refusals.
  - N2's contradictions still load: C with `expert_iteration_every_phases = 4`, and a D interval or window larger than
    `max_phases`. That is a note only.
- **A and B against master: unchanged.**
  - Records (disk path), 6 phases with credits per_tactic, sequence and proof_success: identical to master apart from
    one tree's `started_phase`, which flips between two master runs too.
  - Uninterrupted runs at 041389e against 2db23ca: likewise only `started_phase`.
  - The golden file: 10/10 on master and 10/10 at 041389e.
  - `followup_arm.py` configs for A, B1 and B2: identical apart from the output directory.
  - Handoff path: as before, master is not reproducible against itself.
- **The other reviewer's points: tests exist and pass at head.**
  - `test_a_restart_in_publishing_*`: publishes once, records the round's adapter, serves from host memory, trains
    and builds nothing again, matches the uninterrupted run's versions and phases, writes the round record once. Each
    is parametrised for arm C and arm D.
  - `test_a_crash_while_publishing_*`: A, C and D × merge, durable write and the servers' start.
  - `test_the_loops_round_trains_the_adapter_the_hand_run_trainer_trains`, `..._takes_the_hand_run_trainers_steps`
    and `test_on_two_ranks_the_loops_round_trains_the_hand_run_trainers_adapter`.

### New notes

- **N7. Two cases of a damaged metrics line need a better message.**
  - A damaged complete line stops the loop at every restart. The error names neither the file nor the line:
    `JSONDecodeError: Unterminated string starting at: line 1 column 506` comes from `written_for_phase`
    (`store.py`). Naming the path and line number would let the operator repair it in a minute.
  - Cutting a torn final line is silent. One `loop.log` line ("cut a torn last line of grpo.jsonl, N bytes") would
    keep the record honest.
  - Inferred from reading: if a torn line were ever found only at a *later* phase's publish, the cut would drop that
    earlier phase's record without a word. This cannot happen in order, because the record is written before the
    version.
- N1-N6 stand as written. N5 still means the fakes cannot pin token boundaries on the handoff path. The node smoke
  tests are unchanged.
