# Review Z: expert-iteration round 1, code (correctness)

Branch `expert-iteration-1` (7f95602, 51f00c1) on master affea2b; read in the worktree
`.claude/worktrees/agent-aadf25b31c554727b`. Tests: `tests/rl` 1009 passed, 5 skipped (WSL venv). Scratch checks in
`C:\Users\berti\AppData\Local\Temp\claude\C--Projects-Lean-Proofs\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\`.

## Findings

1. **blocker: `train` crashes on the replay validation set: `chosen` is given a generator.**
   `experiments/grpo_expert_iteration.py:342` calls `chosen(read_reasoning_examples(DATA_DIRECTORY / replay.validation), ...)`.
   `reasoning/dataset.py:245` `read_examples` is a generator, and `training_phase.py:239` evaluates
   `random.Random(seed).sample(list(items), min(count, len(items)))`, so `len(items)` runs on the generator.
   - Failure: with the shipped config (`[replay] validation` set), every rank raises
     `TypeError: object of type 'generator' has no len()`. This happens after the tokenizer load, the expert-data read
     and the Lean and math replay tokenization (minutes on each of the 4 ranks), and before `train()` starts. The loop is
     stopped at that point (README step 3), so a GPU window is lost and the code needs a fix on the node. Nothing gets
     corrupted.
   - Fix: `chosen(list(read_reasoning_examples(...)), ...)`. Also add a test that runs `run_training`'s data assembly
     (or factor it into a function and test that), since no test imports `experiments/grpo_expert_iteration.py`.
   - Verified: `scratchpad/chosen_generator.py` reproduces the TypeError with the real `read_examples` and `chosen`.

2. **should-fix: the `loop.pid` refusal in `publish-adapter` never fires after `grpo_loop.sh stop`.**
   `experiments/grpo_loop.py:269-273` refuses while `/proc/<loop.pid>` exists, but `deployment/grpo_loop.sh:98-100`
   sends SIGTERM and immediately `rm -f loop.pid`. The stop itself takes 1-2 minutes (README step 2).
   - Failure: the operator runs `stop` and then `publish-adapter` right away. The pid check passes while the loop
     process is still alive and shutting down; the `children/` check catches only its jobs. Today the stage check
     (`progress.stage != SAMPLING`) prevents an actual double publish, because the loop's publishes happen only outside
     SAMPLING. But the guard that the README and docstring advertise does nothing, and anything the shutting-down loop
     still writes (`progress.json`, status) races with the publish.
   - Fix: make `stop` wait for the process to exit before removing `loop.pid` (`while kill -0 $pid; do sleep 1; done`).
     Or have `running_loop` look for a live `grpo_loop.py ... run` process for this config, e.g. by scanning
     `/proc/*/cmdline`, instead of relying on the pid file.
   - Verified by reading the script; not run.

3. **should-fix: `build` holds every per-tree-capped example with full token tuples in the parent before any cross-tree
   dedup, while the loop is running.**
   At `experiments/grpo_expert_iteration.py:229-232`, `completions += tree.completions` keeps every tree's kept blocks.
   Each one carries `input_ids` as a tuple of Python ints, and the dedup by state and the per-statement cap
   (`selected_completions`) run only at the end. Below-band statements are searched again and again, so the same
   states come back from many trees.
   - Measured: an unpickled 2,000-token tuple costs about 80 KB (`scratchpad/completion_memory.py`). So 100k-300k
     completions take roughly 8-24 GB in the parent, which runs beside the loop (step 1 runs during phase 26's
     sampling, with the REPLs and the ~28 GB of `/dev/shm`). The final selection is at most
     `blocks_per_state x states_per_statement` = 12 per statement, so almost all of that memory is thrown away.
   - Related: if a worker is OOM-killed, `Pool.imap_unordered` never returns and the build hangs instead of failing.
     The `functools.partial` also pickles the whole `CompletionFilter` (held-out goal keys) into every chunk of 4 trees.
   - Fix: dedupe in the parent as results arrive. Per state, keep only the `blocks_per_state` best blocks under the
     global `block_order`/`completion_order` (as `capped_blocks` does) plus the running `all(easy)` and
     `any(on_root_route)` flags; this keeps exactly what the final selection would. Pass the filter through a `Pool`
     `initializer`. At minimum, read `count`'s "states on the trees' shortest proofs" first and estimate about
     2x that x 80 KB before running `build` beside the loop.
   - Not verified on the node (the tree counts are not available locally).

4. **minor: a policy adapter on another recorded base is refused only after the 45-minute training, and the check
   compares with the serving name instead of the adapter chain.**
   `health_checks.py:604` requires `adapter_config.json`'s `base_model_name_or_path == serving.policy_base_model`.
   PEFT's `save_pretrained` keeps the base the initial adapter already recorded (it only fills in `None`). So the
   round's adapter records whatever the chain from `phase5_sft_visible_student_v2` recorded.
   - Failure: if any link in that chain was trained with a local model path, the round's adapter carries that path.
     `publish-adapter` then refuses it after training, with the loop stopped, even though the loop continues that
     same chain every phase. The local configs and results say `Qwen/Qwen3.5-4B` throughout, so this is unlikely.
   - Fix: in `train`, before loading anything, run the same check on the current adapter (`read_current(...)` then
     `check_continued_adapter(current_adapter, "", base)`), so a mismatch shows before the GPU time is spent. Or accept
     the base that the current adapter records.
   - Not verified on the node's adapter files.

5. **minor: the minimum-version filter works on version numbers, so a post-fix rollback to a pre-fix policy would pass.**
   `expert_iteration_data.py:233` (`expansion_verdict`) keeps any `policy_version >= minimum_version`. A rollback
   publishes a new, higher version that carries an older adapter. If a collapse after the reward fix ever rolled back to
   a pre-fix version, that version's samples would count as post-fix. This is the same gap as review X's finding 2,
   and it is unlikely today. The claim and shortest-route filters remove most of what the minimum guards against.
   - Fix: build the allowed set from `models/versions.jsonl`: a version counts if its `policy_adapter` is that of a
     `phase <n>` version with n >= the fix's first phase.
   - Not verified against the node's versions.jsonl.

6. **minor: nothing ties the published adapter to the version it continued, and the README hardcodes 25/26.**
   `train` continues whatever `current.json` names at train time. `publish-adapter` does not check that the adapter
   continued the version it is about to supersede, and README steps 4, 6 and 7 hardcode `from v25`, `--phase 25`,
   `--version 26` and `rollback --version 25`.
   - Failure: the loop advances once more between `build`/`train` and the stop (or is restarted by mistake). Then
     `publish-adapter` silently replaces the GRPO progress since the train-time version, and `rollback --version 25`
     rolls back two versions.
   - Fix: `train` writes the continued version and adapter beside the adapter (e.g. `continued_from.json`), and
     `publish-adapter` refuses unless it equals `current.policy_adapter`. `compare` already prints
     `--version {version - 1}`; the README could say "the version before" instead of fixed numbers.

7. **minor: the KL reference's free scoring depends on exact string equality, and `compare` does not print the
   string.**
   `policy_trainer.py:427` takes the free path only if `initial_adapter == reference_adapter` as strings.
   `publish-adapter` stores `str(Path(arg).absolute())`, which does not resolve symlinks. A different spelling in
   `loop.toml` (symlinked `/workspace`, a relative path) costs one reference-scoring pass in phase 26. Correctness is
   not affected: the swap path loads the same weights and asserts rank and scale.
   - Fix: on "Keep", `compare` prints the exact `policy_adapter` of the round's version to paste into
     `kl_reference_policy_adapter`.

8. **minor: `count`'s heading promises a version filter its table does not apply.**
   `experiments/grpo_expert_iteration.py` `count` prints "samples of versions >= X except [...]", but the per-phase
   numbers are all solved trees of non-held-out statements, regardless of version. Phase f's trees, sampled mostly by
   the pre-fix version, are counted in full. The build's counts are right.
   - Fix: reword the heading, or note that the filter applies only in `build`.

9. **minor: `count` and `build` read `trees/index.jsonl` while the loop appends to it.**
   `TreeStore.__init__` (`tree_store.py:64-66`) `json.loads` every line. A line torn by a concurrent append crashes
   `count` or `build` with a JSONDecodeError (harmless; rerun). Entries are written after their tree file, so the
   phases 1-25 data is complete.
   - Fix: none needed; or skip an unparsable last line.

## Checked and found correct

- **Token equality with `PolicySequence.tokenized`.** Same `tokenizer.encode(expansion.prompt, add_special_tokens=False)`,
  same `completion_tokens` (recorded ids, end of turn included as recorded). Re-tokenized, forced (inserted) and
  undecodable (`offsets is None`) samples are dropped. The loop has one expansion per (node, round), so its
  `texts_by_prompt` and the per-expansion prompt here agree. `ended_turn = False` without forcing cannot be kept: a
  cut-off visible sample is unparsed, hence FAILING.
- **Labelling.** `label_graph` and `policy_tactics` exactly as the loop calls them, with
  `off_graph_min_expanded_nodes` = 4. Repeats resolve to the executed edge of the same node (`edge_id_by_text` is per
  expansion). Infrastructure failures are detected through `effective_kind`. For a proving block the shortest-route
  test is exact (it needs `len == remaining_steps(node)`). Feedback-round expansions are dropped and play no part in
  `easy`. Name repair is off in the loop's search config, so the old-format repaired policy edges (text and outcome of
  the repair, tokens of the original) do not arise.
- **Version filters.** Applied per expansion. Rejected versions are read strictly from `rejected_versions.jsonl`. The
  minimum version comes from the first `phase <first_phase>` version; `publish-adapter` refuses `phase <n>` triggers,
  so it cannot shift that.
- **Dedup, caps, order.** Capping per tree and then globally keeps the global top-k, because both orders are pure
  hashes. The final order is sorted by `completion_order`. The only nondeterminism is metadata (`policy_version`) when
  two trees recorded byte-identical prompt and tokens.
- **Train.** `initial_adapter` comes from `current.json` at train time. The adapter keeps its rank and alpha
  (`PeftModel.from_pretrained`, `is_trainable`). The output goes outside the phase directories, which retention
  (`prune_phase_adapters`) never touches. The DDP and torchrun environment is the original SFT's. Interval and
  validation size are set after `plan_steps`.
- **`publish-adapter` and rollback.** The versions log is written before `current.json`. `reuse_merges` points at the
  current version's on-disk merges: recorded versions always hold `weights/v*/` paths, and the `/dev/shm` handoffs
  are only served before the durable record. `prune` keeps the reused value directory. It deletes v25's policy merge,
  so a rollback after the round merges v25 again on the CPU from its still-retained phase adapter (correct, 3-5 min).
  The stage check is sound: the loop is back in SAMPLING only after `record_durably` finished. The automatic rollback
  (`GrpoLoop.roll_back`, `publish_rollback` with the loop's own publisher) behaves as before. The refactor only
  re-reads `versions.jsonl`.
- **KL reference.** `phase_config_text` passes it as `reference_adapter`. Phase 26 (`initial == reference`) uses `old`
  for free. Later phases swap the reference weights in place (rank and scale asserted, same keys since SFT continued
  the same adapter). Nothing else reads `[initial] policy_adapter` as the reference.
- **`compare`.** Pairing is against each problem's latest earlier run of another, non-rejected version; runs are sorted
  by finish time and the candidate's own repeats are excluded. Thresholds match DESIGN.md (difference >= 0,
  lower > -2 points; held out >= 0.9x of v0).
- Design note, not a defect: phase 26 trains its v25-sampled trees as if the round's adapter had sampled them (no
  sampler correction; `old` is the round's). PPO clipping bounds this, and the README states it.

## Verdict

**Not safe to run as is: `train` (step 3) crashes (finding 1).** It is a one-line fix and corrupts nothing, but it
costs a stopped-loop window, so fix it before the round. Before running `build` beside the live loop, estimate its
memory (finding 3) or make the dedup incremental. Make the `publish-adapter` guard real (finding 2), or follow the
README's "wait for the stop in loop.log" strictly. With finding 1 fixed and those two precautions, the round cannot
silently corrupt the live loop: the data is token-for-token the loop's, the publish, rollback and KL-reference paths
are correct, and the automatic rollback is unchanged. Findings 4-9 can follow.

## Re-review

Fix commit 6d2a6ec (`git diff 51f00c1..6d2a6ec`), read in the same worktree. Tests: `tests/rl tests/training
tests/expert_iteration tests/monitoring` 1532 passed, 42 skipped (WSL venv).

### Status of the findings

| # | Status | How |
|---|---|---|
| Z1 | fixed | `expert_iteration_data.training_data` reads the replay validation file into a list and samples with `random.Random(seed).sample`; it draws the same examples `chosen` would have. Tested: `test_training_data_*` (the parts, the replay share by completion tokens, the replay validation drawn apart). |
| Z2 | fixed | `grpo_loop.sh stop` waits up to 300 s for `kill -0` to fail, removes `loop.pid` only after the process has exited, and otherwise exits 1 with the servers left running. |
| Z3 | fixed | `CompletionSelector` adds trees as they arrive and keeps at most `blocks_per_state` blocks per state. Checked: random per-tree-capped inputs give exactly global `capped_blocks`' blocks and representatives, 0 mismatches in 300 trials (`scratchpad/selector_property.py`); an evicted block that comes back is evicted again. A worker death raises `BrokenProcessPool` and stops the build before anything is written. The filter goes to each worker once, through the `initializer`. The node's build (13k blocks before the caps) makes the memory question moot anyway. |
| Z4 | fixed | `training_refusals` runs `check_continued_adapter` on the current adapter against `[sft] model` before any GPU time. |
| Z5 | open (minor) | `expansion_verdict` still compares version numbers. Accepted as before; unlikely today. |
| Z6 | fixed, with a gap | `continued_from.json` and `continued_version` refuse an adapter when a phase has published since the version it continued; the README no longer fixes version numbers. The gap: a rollback since that version still passes; see R2. |
| Z7 | fixed | `compare` prints the exact `policy_adapter` to set in `kl_reference_policy_adapter`. |
| Z8 | fixed | `count`'s heading now says it counts every tree. |
| Z9 | fixed | `index_entries` drops an unparsable last line only and raises on any earlier one. |

The named validation sets in `training/sft.py` do not change the behaviour of other SFT callers. `validation_sets`
defaults to `()`, and `EvaluationRecord.sets` defaults to `()`, which adds only an empty `"sets": []` to their
`evaluations.jsonl`. Older records still parse. `run_training` passes the replay set only when it is non-empty, so
`validation_metrics` never sees an empty set (it would divide by zero).

The variant configs are fine. B and C differ from A only in `run_name`, learning rate and epochs (asserted by
`test_expert_iteration_variants_differ_only_in_run_name_learning_rate_and_epochs`), and all three read A's data
directory.

Checked and correct in the new code:
- Pre-flight: free space via `shutil.disk_usage`; the refusals are printed in a dry run and raised in a real run.
- `continued_from.json` is written by rank 0 after `train()` saved the adapter, and the training summary after it.
- The pooled easy states: `samples[-1]` is always the current expansion's tally.
- `paired_comparison` takes, per problem, the latest reference run in finish order, and returns NaN intervals (not a
  crash) when nothing pairs.
- `--against` uses the other version's whole-set run and held-out run. Its rollback hints match the README's step 8.
- Variants published one after another: S passes `continued_version`, since F's trigger is not a phase's. S's publish
  prunes F's merge, and a later `rollback --version F` merges F again on the CPU from its adapter, which is outside
  retention.

### New findings

R1. **should-fix: README step 2 says to stop on the wrong log line, and `train` does not check the stage.**
   README "The round on the node" step 2 says to stop right after `loop.log` shows "Published version <k>". `publish()`
   logs that line before the phase's paused evaluations, its health check and `close_phase`, so the stage is still
   PUBLISHING or EVALUATING (with the handoff path, the searches have already resumed early, so it looks like
   sampling). `run_training`'s refusals do not include the stage check that `publish-adapter` applies.
   - Failure: the operator stops at that line. A, B and C train (about 1 h of GPU time; `current.json` holds v_k by
     then, because the cancelled durable record's thread runs to completion before exit). Then `publish-adapter`
     refuses: "The loop stopped in its publishing stage". The loop must be restarted to finish the phase (servers,
     evaluations, health check) and stopped again before the publish can go through. Nothing is corrupted, but there
     is an unplanned restart, and R2 applies if that phase's health check then rolls back.
   - Fix: add `read_progress(paths.progress).stage != PhaseStage.SAMPLING` to `training_refusals` (shown as a "would
     refuse" line in the dry run). In step 2, wait for "Phase <k> pause: ..." (logged in `close_phase`, after which
     the stage is SAMPLING), or for `grpo_loop.py status` to show the sampling stage.
   - Verified by reading `GrpoLoop.publish`, `run_phase` and `close_phase` (`loop.py` ~1160-1200, ~2012-2045); not run.

R2. **should-fix: `continued_version` accepts an adapter whose version was rolled back from or rejected since.**
   `health_checks.continued_version` refuses only when a later version has a `phase <n>` trigger.
   - Failure: the adapters continue v_k. Before they are published (for example on the restart that R1 forces), the
     phase's health check finds v_k's held-out states collapsed. It then rejects v_k (`loop.py:1336`) and publishes
     the rollback v_{k+1} (trigger "rollback to v_j after phase n"). `publish-adapter` then accepts the round's
     adapter, a fine-tune of the collapsed, rejected v_k, and the loop continues from it. The same happens after a
     hand `rollback` from v_k.
   - Fix: also refuse when `continued.version` is in `rejected_versions.jsonl`, and when any later version is neither
     another variant of the round (an adapter whose `continued_from.json` names the same version) nor a rollback to
     one of them. At minimum, refuse on a later `rollback to v...` trigger whose target is not the continued version.
   - Verified by reading; not run.

R3. **should-fix (README logic): step 7's winner rule can drop a variant that passed.**
   The rule is "S if it passes its own compare and beats F; else F if it passes its own; else none". "Beats F" is
   `compare --version S --against F` passing every check, including a paired difference of at least 0 with its lower
   bound above -2 points, which means about +1 point over F.
   - Failure: S passes its own compare, F fails its own, and S is not about 1 point ahead of F head to head. The rule
     gives "none" and rolls back to v_k, discarding the passing S.
   - Fix: "S if it passes its own compare and (F fails its own or S beats F); else F if it passes its own; else none".

R4. **minor: the diversity checks pass silently when the references have no trees.**
   In `round_checks`, the distinct-blocks and explanation floors are fractions of the references' values. With no
   readable reference trees (`policy_expansions == 0`, an empty `explanation_character_bins`) both floors are 0 and
   both checks pass whatever the candidate did. The loop's probe runs do write trees, so this matters only for old or
   pruned runs.
   - Fix: fail the check, or report it as unmeasured, when `reference_habits.policy_expansions == 0`.

R5. **minor: the pooled easy share also counts samples from trees where the state is off the proof graph.**
   `StateSamples` comes from every filtered first-round expansion of a state, including trees where that state is not
   on the proof graph, because those trees proved the statement another way. There its blocks label off-graph or
   unknown and dilute the state's proof-graph share. This errs towards calling fewer states easy, so the 20% cap binds
   less. It is conservative and not a defect; noted so the README's "pooled over every tree that searched it" is read
   that way.

R6. **minor:** `build` prints its progress lines every 250 trees without `flush=True`, so under `background.sh` they
   appear late. And `latest_held_out_version` raises a bare `ValueError` from `max()` if no non-rejected held-out run
   at or below the continued version exists (v0's always does).

### Verdict

**Safe to run.** Z1-Z4 and Z6-Z9 are fixed; Z5 stays open as a minor. The data, the training data and the selection
are correct and tested, and the SFT change does not alter other callers. One operator correction first: stop the loop
only after "Phase <k> pause:" is logged (or `grpo_loop.py status` shows the sampling stage), not at "Published version
<k>" (R1). That keeps R2's scenario off the planned path. Use R3's corrected winner rule at step 7. R1's `train` stage
refusal and R2's rejected/rollback refusal are small code changes worth making before the run, but no corruption
follows from either if the stop is placed correctly. R4-R6 can follow.

## Final check (d018335)

Diff `6d2a6ec..d018335`, read for anything that would break the node run. Tests: `tests/rl tests/training
tests/expert_iteration tests/monitoring` 1544 passed, 42 skipped.

**Each step of the node run:**
- **Stop.** `stopped_loop_refusal` (live `loop.pid`, live `children/` jobs, stage not SAMPLING) is shared by `train`
  and `publish-adapter`, so a stop outside the sampling stage is caught before any GPU time. Neither `grpo_evaluate.py`
  started by hand nor `grpo_loop.sh servers` writes `children/` records, so the evaluations and servers between the
  publishes do not block the second publish.
- **Train.** The dry run prints the refusals and continues. All four torchrun ranks run the same refusals.
- **Screen.** It reads `replay_loss_change`, a new required field of `training_summary.json`. That is fine because A,
  B and C are trained with this commit. A summary written by 6d2a6ec would not parse.
- **Publish F, then publish S.** S passes `continued_version`: F's trigger is neither a phase's nor a rollback's, and
  F is not rejected. No step in the README runs a rollback before S's publish, which the new refusal would block.
- **The paired held-out check.** It reads `held_out_states_v*/trees/<state>.json.gz`, which `single_step.search_states`
  writes for the loop's runs and for `grpo_evaluate.py`'s. Without reference trees the interval is NaN and the check
  fails, so it errs towards rejecting the variant.
- **`--held-out-only`.** It exits 1 on a failure, as documented.
- **The decision.** The full `compare` of a variant whose probe was skipped exits with "No finished whole-set probe
  run", consistent with "fails its own compare". `against_verdict` states the corrected winner rule.
- **Restart.** The diversity checks now fail when the references have no trees (R4).

**Go.** R1-R4 are fixed and I found nothing in this diff that breaks the node run. Two notes for the operator:
- If F's probe was skipped, `compare --version S --against F` cannot run. It isn't needed then: F has failed its own,
  so S wins if it passes its own.
- Train A, B and C with this commit (the `screen` field above).
