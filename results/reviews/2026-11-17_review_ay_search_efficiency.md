# Review AY: search efficiency package and offline training throughput (2026-11-17)

Independent review, correctness and soundness. Branches:

1. `worktree-agent-a884d29b93192b24f` at 3949496 (five commits on 33c96ea): `[search] result_cache`,
   `[search.timeout_skip]`, `[lean] spare_processes`, the nlinarith / restart-cost measurement scripts.
2. `offline-training-throughput` at 7f58dd7 (one commit on cb3d446): `packed_length_multiple`, the dynamo
   recompile limit, the median throughput.

No code was changed; nothing committed. Tests (WSL, one suite at a time): the
four new test files at 3949496, 41 passed; `tests/lean tests/search tests/rl tests/expert_iteration tests/value` at
3949496, 3042 passed, 207 skipped (Lean- and GPU-dependent tests skip in WSL, so the cache and spare paths are
exercised only through the fake REPL); `tests/training` plus `tests/rl/test_offline_{build,configs}.py` at 7f58dd7,
151 passed, 9 skipped (the GPU packing tests among the skips).

## Verdicts

- **Search efficiency (3949496): approve, no blocking defect.** The cache key is sound under the README's own premise
  (replay is deterministic for an identical chain of commands; the key is that chain), cached successes from a dead
  process are replayed like any stale state, proofs are verified exactly as before, the skip label reaches every
  consumer as a wall-clock timeout and never as an infrastructure failure or success, and spares are adopted, refilled
  and closed without leaks in the paths the code can reach. With all three switches off, search behaviour is
  identical; the written records are not byte-identical (four always-written keys, N1). Fix S1 before the cache's
  savings are reported; S2 before the nlinarith numbers are used to pick a variant.
- **Offline training throughput (7f58dd7): approve with S3.** The pad segment is its own varlen sequence with ignored
  labels, restarts its positions, and is invisible to the loss, the per-example accounting and attention; at
  `packed_length_multiple = 0` packing is unchanged. But the raised recompile limit is not tied to that switch: it
  changes every `compile_layers` trainer of the study (S3).

## Blocking

None.

## Should fix

**S1. `cache_saved_seconds` counts replays and restarts, not just the tactic.** `lean/repl.py:664-666`
(`_remembered_outcome`): `seconds` wraps the whole `_guarded(self._apply_tactic, ...)`, which includes
`_ensure_healthy` (a restart at the proof-state or memory limit, a spare swap or a full import) and `_live_state` (the
replay of the state's entire path after any kill). Scenario: a wall-clock kill at node N; the next block at N runs
`t1` first and pays the replay of N's path (often 5-30 s on deep nodes) inside `t1`'s recorded seconds; a later block
`t1; t2` at N hits the cache and adds those seconds to `BlockResult.cached_seconds`, `Accounting.cache_saved_seconds`,
although re-running `t1` there would only have cost `t1` itself (N is live by then). The inflation concentrates on
exactly the timeout-heavy states, so "seconds saved" from a run would overstate the feature against the offline 11.6%
estimate. Fix: time only `_run_tactic` (return the elapsed seconds from `_apply_tactic`, or measure inside it after
`_live_state`), and record that in `Remembered.seconds`.

**S2. `nlinarith_variants.py` measures in a different base environment than the search.**
`experiments/analysis/nlinarith_variants.py:583` appends `VARIANT_DEFINITIONS` to `BASE_ENVIRONMENT_DEFINITIONS` for
every job, the `original` runs included. The lean README (Proof states and replay) documents that appending one
unrelated line to the base definitions moved one `nlinarith` step from 16.4 s to 98 s, and flipped 4 of 500 traced
proofs between success and the wall clock. So the `original` column is not the search's `nlinarith`: its seconds and
outcomes are those of another chain, and the per-variant savings (e.g. `cap8` 16%, `degree` 71% of the original's
hours) mix the variant's effect with chaos from the changed chain. The summary's own check (`full` vs `original`,
103% hours, identical successes) only shows the reimplementation matches inside the modified environment. Fix: run
`original` in a REPL with the production base definitions (the job state rebuilt twice, or two REPLs per job), report
how far its seconds move from the recorded `net_seconds`, and state in the summary that adopting a variant means
changing the production chain, which itself reshuffles the heavy steps' run times.

**S3 (training). The raised dynamo recompile limit applies to every `compile_layers` trainer, not to the offline arm
only.** `training/sft.py:408-410` raises `torch._dynamo.config.recompile_limit` to 64 inside `load_trainable_model`
whenever `compile_layers` is on, independent of `packed_length_multiple`. `load_trainable_model` also loads the GRPO
policy trainer, the resident trainer, expert-iteration training, DPO and the value trainers, and `compile_layers = true`
is set in `followup/expert_iteration.toml`, `grpo/phase*.toml` and others. After this merge those runs compile the
LoRA projections that ran eager before (the commit's own comment: "at the default 8 some ran eager"): different kernels
(bf16 rounding differs between compiled and eager), more first-phase compile time and possibly peak memory. Arms of the
controls study trained before and after the merge would then differ in a way no config shows, and
`test_the_fine_tuning_is_the_expert_iteration_recipes_but_for_padded_packed_rows` keeps passing because the change is
not in the recipe. The setting is also process-global and sticky (`max`). Fix: make it a recipe field (e.g.
`[sft.optimization] compiled_shapes_limit`, default unchanged at torch's 8, 64 in `offline_arm.toml`), or, if it is
wanted everywhere, record it as a study-wide recipe change in `results/followup_progress.md` and check the resident
trainer's peak memory once.

## Nits

**N1. Records are not byte-identical with the switches off, and readers before this branch reject them.**
`search/tree.py:152` (`Edge.cached_tactics`), `search/search.py:180-184` (`Accounting.cached_tactics`,
`cache_saved_seconds`, `skipped_timeouts`), `search/search.py:197` (`StepStatistics.skipped_timeouts`): `to_json` writes
every field (`dataclasses.asdict`), so every edge and result gains these keys at 0, and `records.from_json_object`
raises `unknown keys` on them in any reader at an older commit (another worktree's analysis, the node's tools if they
lag the search code). Additive keys are this repository's convention, so this is a note for the deploy order (every
reader at or after this commit before a run with it writes trees), not a request to change the format.
`summary.py:410` also always renders the new "skipped timeouts" column.

**N2. The skip counter mixes heartbeat limits.** `lean/memory.py:58-69` counts wall-clock stops per text only. The sweep
runs `nlinarith` at 200k heartbeats and the policy at 50k; two sweep stops make the policy's `nlinarith` a
SKIPPED_TIMEOUT, labelled a wall-clock timeout, where at 50k a heartbeat-counted slow run would have ended as a
HEARTBEAT_TIMEOUT (same timeout tier, but `EdgeKind.HEARTBEAT_TIMEOUT` and in `FEEDBACK_FAILURE_KINDS`). Either key
the counter on `(text, heartbeats)` or say in the README that the limit does not count.

**N3. Spare refill under-fills after a dead spare or a failed start.** `lean/pool.py:48-58, 77-90`: `_close_later` puts
the closing task into `_starting`, which `fill()` counts as a spare being started, so `take()` that discards a dead
spare does not start its replacement; nothing calls `fill()` when the close ends. Likewise `_start_one`'s failure path
sleeps `retry_seconds` and returns without retrying (the name suggests a retry). Effect: one spare fewer until the next
`take()`, which is then a miss. Fix: keep closing tasks in a separate set, and call `self.fill()` after the
failure sleep (or rename `retry_seconds` to what it is, a back-off before the slot can refill).

**N4. Spares also serve restarts that are not mid-use kills.** `lean/repl.py:936-947`: `_ensure_healthy` takes a spare
for any unhealthy process, including REPLs stopped by `stop_idle_processes` (evaluation and single-step tails) or
`stop_processes` (`release_lean_memory`) when they are next used. That is usually welcome, but the README's scope
("a REPL that must replace its process while in use") understates it, and `spare_swaps` / `spare_misses` then do not count
kills alone. `stop_processes` (the loop's host-memory release) does not touch spares either, only
`stop_idle_processes` is mentioned in the README. Also `spare_swaps` / `spare_misses` are never logged or
recorded anywhere (grep finds only `repl.py`), so a run with spares cannot show how often they helped. Suggest a pool
summary line (swaps, misses) in the search services' logs and a README sentence.

**N5. `close()` can miss a closing task created after it gathered.** `lean/pool.py:60-66`: a `take()` that runs during
`close()`'s awaits (a REPL still in use during pool shutdown) can `_close_later` a dead spare after the `gather`
snapshot; the task is then never awaited ("Task was destroyed but it is pending" at loop shutdown). Harmless for
processes (PDEATHSIG), cosmetic for logs.

**N6. Tests that cannot fail for the reason their name gives.**
- `tests/lean/test_search_memory.py:61` `test_a_proof_through_a_cached_tactic_verifies`: the fake REPL verifies every
  theorem command (`fake_repl.py`: no errors, no axioms), so it checks that the search returns the proof, not that
  verification of a cached-path proof is unchanged. Either rename it or assert on the theorem command the fake
  received (`project.requests("cmd")`: the executed proof with both steps wrapped in their heartbeat limits).
- `tests/lean/test_spare_processes.py:96` `test_a_taken_spare_is_replaced_in_the_background` asserts
  `spare_swaps == 1`; the refill is only implied by `spares_ready` not timing out. Assert on `pool.spares.ready == 1`
  after the swap instead.
- Missing: a spare taken through `_ensure_healthy` at the proof-state limit; a dead ready spare skipped by `take()`;
  the `(text, heartbeats)` question of N2; a cached deterministic panic (no process death on recall).
- Training: `tests/training/test_packing_gpu.py::test_packed_losses_match_each_example_alone` has no padded variant;
  one call with `length_multiple=64` would pin down that the pad segment changes no loss (GPU-only, like its sibling).

**N7. Validation rows are not padded.** `training/sft.py:447` (`validation_metrics` -> `micro_batch` without the
multiple): validation still meets both Triton specializations, so the "every row runs the same specialization" claim
holds for training steps only. One-off cost per rank; mention it or pass the multiple.

**N8. `packed_length_multiple` is ignored outside `sft.train`.** `rl/expert_iteration_training.py:158`,
`rl/policy_trainer.py:339, 595, 683, 857`, `training/dpo.py:187` build micro-batches without it, though it sits in the
shared `OptimizationConfig`. A recipe that sets it there gets nothing, silently. Plumb it, or reject a non-zero value
in those trainers.

**N9. `steady_tokens_per_second` changed meaning under the same name.** `rl/offline_arm.py:488-499`: before, total tokens
over total seconds after warm-up; now the median per-step rate. Fine as a measure (a compile stall no longer sets it),
but throughput records written before 7f58dd7 (O2's first training) and after are not comparable, and the median of
per-step rates is not the rate that sets a token-matched run's duration. Note it next to the record, or keep both.

**N10. Script nit.** `nlinarith_variants.py:310` assumes `CLK_TCK = 100`; use `os.sysconf("SC_CLK_TCK")`.

## Checked and fine

Result cache:
- Key (`memory.py:9-22`): header, statement, the state's full tactic path with each step's heartbeat limit, the
  normalized tactic, its heartbeat limit. Everything the REPL's answer depends on besides the wall clock: the
  environment chain (import, header commands, base definitions) is the same in every process of the pool and in a
  spare, REPL commands are pure in their `env` snapshot (name generator, macro scopes included), and the root's
  auxiliary-environment repair is itself a function of the statement. Equal goals reached by different paths are
  different keys, as they must be (matchers, metavariables, fresh-name counters).
- Only deterministic outcomes are stored (`is_deterministic`): successes, errors (forbidden and empty texts, panics
  from `DETERMINISTIC_PANICS`), heartbeat timeouts. Wall-clock stops and every `ReplFailure` (crash, replay failure or
  mismatch, restart failure) run again. A replay failure of the parent is never attributed to the tactic.
- A cached `ProofState` keeps its old session and proof-state id; session ids are uuid4 and change on every restart and
  spare adoption, so a stale one is replayed by `_live_state` (with the goal check) before use and never used against
  the wrong process; the replayed-state cache is cleared on restart and on adoption. Within its own session the id stays
  valid (the REPL frees no states; the proof-state limit restarts the process).
- The not-in-key wall-clock limit only matters when candidates differ in `timeout_seconds` (they do not today: sweep
  and policy both use the search's), and then the cache can only turn a load-dependent stop into the deterministic
  outcome.
- Proofs through cached steps: the cached state's `tactics` / `tactic_heartbeats` equal what a re-run would give, so
  `verify_state` re-elaborates the identical `executed_proof` from scratch; nothing in verification reads the cache.
- Concurrency: one `SearchMemory` per `_TheoremSearch`; every Lean call of a search goes through its one REPL's lock,
  and candidates of a batch run sequentially; overlap and early scoring touch only the models. No cross-search sharing.
- `normalized_tactic` is idempotent, so normalizing before the memory and again in `_apply_tactic` is harmless.

Timeout skip:
- `Failure.from_lean` maps `skipped=True` before the wall-clock case; `failure_edge_kind` -> `EdgeKind.WALL_CLOCK_TIMEOUT`
  (so GRPO groups and rewards, graph labels, value labels, tree statistics and phase health see a wall-clock timeout);
  `failure_tier` -> TIMEOUT; `error_category` -> TIMEOUT; preferences' `TIMEOUT_FAILURES`; `is_negative_label` true;
  not in `FEEDBACK_FAILURE_KINDS` (like the wall clock); excluded from `unknown_names` exactly like a timeout. No
  consumer treats it as infrastructure or success; the GRPO reward has no Lean-seconds term, so the near-zero seconds
  of a skipped edge change no reward.
- Counted apart: `Accounting.skipped_timeouts` (not `timeouts`), `StepStatistics.skipped_timeouts`, `lean_load` counts
  only real stops; `SearchTree._timeouts_by_text` (the sweep's per-tactic disable) counts only real stops, consistent
  with the skip firing only after real stops.
- Counting per search survives restarts (Python-side counter); a skip is not recorded as a stop; a skip avoids the
  replay and the kill (decided before `_guarded`); the block keeps its valid prefix; the cache is consulted first.
- Config validation (`max_wall_clock_timeouts >= 1`) and the off path (`memory is None` -> the old `_guarded` call).

Spares:
- Adoption (`repl.py:978-995`): process, stderr drain task and tail, environments, header failures and proof-state count
  move over; new session; replayed states cleared; `_must_restart` false; the spare is marked closed with no process,
  so closing it later is a no-op. `_recover` then reloads the headers the old process had that the spare lacks.
- `take()` is synchronous, so two REPLs never get the same spare; a spare is in `_ready` only after all headers loaded
  (never mid-request); dead ones are skipped. Spares inherit the orchestrator's affinity (Lean CPUs: the event-loop
  thread is never re-pinned; `thread_on_cpus` runs in worker threads), niceness, RLIMIT_DATA and PDEATHSIG through the
  same `preexec_fn`, started from tasks on the event-loop thread.
- Cancellation: a cancelled start kills the process (`_request`'s BaseException path or the subprocess transport's own
  cleanup) and `close()` awaits all starts; `pool.close()` closes spares before the REPLs; no task survives
  (`test_closing_the_pool_while_spares_start_leaves_no_task`, and I traced the paths).
- Off (`spare_processes = 0`): `spares is None`, `_replace_process(use_spare=True)` falls through to `_start_process`
  without counting a miss; every pool constructor passes the config value; negative values rejected.

Off-switch behaviour of the search: with `result_cache = false` and `timeout_skip.enabled = false`, `self.memory` is
None and `apply_block` makes the same calls in the same order as at 33c96ea; only the always-zero record fields differ
(N1).

Training branch:
- `pack()` (sft.py:289-304): the pad segment's labels are all `IGNORE_INDEX`, its positions restart at 0, it is its own
  `cu_seqlens` segment for varlen attention and the varlen convolution (and the gated delta rule through the same
  `cu_seq_lens_q`), so no real token attends to it and it attends to none; the last real token's target is the first
  pad label (ignored), as at an example boundary. `searchsorted` over `sequence_starts[1:]` maps real targets to the
  same example indices as before. Step accounting keeps real tokens (`token_count`) apart from `input_ids.numel()`.
  At 0 the token lists and tensors are the same as before (int64, same values). `pad_token_id` is the tokenizer's, as
  `collate` already relies on.
- `recompile_limit` exists in the pinned torch 2.13.
- The median-rate test exercises the production function with a stalled step.

Measurements read: `node_backup/2026-11-15/search_efficiency/{restart_cost,nlinarith}/summary.md` (median kill cost
6.23 s -> 0.21 s with 8 spares, 56 of 80 kills swapped, p90 6.80 s when spares run out; a ready spare holds 0.24 GiB
private), consistent with the code paths above.

## Re-review (2026-11-17), training branch

`offline-training-throughput` at 6ba3260 (fixes in 7f58dd7..6ba3260). Tests: TRAINING_TESTS_PLACEHOLDER

- **S3 fixed.** The recompile limit is now the recipe field `[sft.optimization] compiled_shapes_limit` (0 leaves
  torch's own limit untouched, `set_compiled_shapes_limit`), 64 only in `offline_arm.toml`;
  `test_no_other_shipped_recipe_pads_packed_rows_or_raises_the_compiled_shapes` pins that no other shipped recipe sets
  it (or the padding), and the recipe-equality test names both offline-only keys. Every trainer that loads through
  `load_trainable_model` honours the field, so it means the same wherever it is set. Note: the dynamo setting is
  process-global, so a process that loads a 64-limit model and later a 0-limit one keeps 64; no shipped process does
  that (the offline arm trains in its own process).
- **N7 fixed.** `evaluate` and `validation_metrics` take `packed_length_multiple`, `train` passes the recipe's. The
  pad segment has no targets, so `rows`, `bincount(..., minlength=len(indices))` and the exact-match count are
  unchanged; the validation loss moves only by kernel rounding.
- **N8 fixed as documentation.** The field's comment and `results/followup_node_operations.md` say only
  `training/sft.train` uses it, and the shipped-recipes test keeps it out of the other trainers' configs. A non-zero
  value in another trainer's recipe would still be ignored silently; acceptable with the test.
- **N9 fixed.** Two named rates, `median_step_tokens_per_second` and `sustained_tokens_per_second` (the old
  aggregate), in `throughput.json` and the training summary; the docs say to plan wall time from the sustained one and
  that O2's first trainings wrote `steady_tokens_per_second` with the sustained meaning. The pulled
  `live/runs/offline_chain/chain.log` has one throughput line (5,752 tokens/s, `steady_tokens_per_second`) from the
  driver before 7f58dd7, so that reading is right. Nothing reads these files back through `from_json_object`
  (`offline_chain.sh` copies the line as text), so the rename breaks no reader; the study-chain fake was updated.
- **New:** nothing found. Verdict: approve.

## Re-review (2026-11-17), efficiency branch

`worktree-agent-a884d29b93192b24f` at ab1256d (fix wave 3949496..ab1256d). Tests: EFFICIENCY_TESTS_PLACEHOLDER

### Earlier findings

- **S1 fixed.** `_apply_tactic` times only `_run_tactic`, after `_live_state` (`_tactic_seconds`, set in a `finally`);
  `_remembered_outcome` resets and records it. A restart in `_ensure_healthy` or a replay failure leaves 0, and those
  outcomes are not cached anyway. `test_cached_seconds_leave_out_the_replay_before_the_tactic` replays a 1 s step before
  the cached one and checks the credit stays under 0.5 s.
- **S2 addressed, not measured.** The script gained `--plain-environment` (the original text without the
  definitions), bootstrap intervals, a "where the gained successes come from" table and a limitations section; N10 is
  fixed (`SC_CLK_TCK`). The plain-environment rerun has not been run (the pulled summary has no such table), so the
  "71% of the time" is still variant environment against variant environment. With the switch on, the sampling's
  environment is that variant environment, so the figure is right for "nlinarith against degree inside the sampling";
  it says nothing about what the switch costs or saves against the plain base definitions the anchors ran with (every
  heavy step's run time moves with the definitions, lean README). The owner decided without it (DESIGN.md); fine as
  long as no write-up quotes the 29% as a saving against step 1. Also, the "gained" column is not evidence of gains:
  degree's 794 scaled gains come from 4 jobs, one of them 88%.
- **N1 fixed.** `record_fields.written_when_set` / `record_dict` (used by `records.to_json`, so by trees, results,
  phase records, `write_json_atomically`, and by the metrics writer) leave the new counters out at their defaults.
  `record_dict` mirrors `dataclasses.asdict` (dataclasses, named tuples, lists, tuples, dicts, deep copies), so records
  with the switches off are byte-identical to master's, and readers fill the defaults. Run config: the switches are
  None when off and `without_none` drops them, so a plain config's text and digest are master's; `run_config_sha256`
  also drops `spare_processes`. The step-cost table shows the skip column only after a skip.
  `test_a_search_with_the_switches_off_writes_its_tree_as_before` checks a tree.
- **N2 fixed.** The skip counter is keyed by (text, heartbeat limit); the README says so.
- **N3 fixed.** Dead spares close in a separate `_closing` set that `fill()` does not count; a failed start removes
  itself from `_starting` after the back-off and refills. Tests: a dead ready spare is skipped (a miss, not a swap), a
  failed start is retried. New nit N13 below.
- **N4 fixed.** README scope widened (a stopped REPL's first use), `stop_processes` named; `LeanReplPool.spare_text`
  is logged with the loop's host-memory line (the evaluation and pool-search processes do not log it; fine).
- **N5 fixed.** `close()` awaits `_closing` until it is empty.
- **N6 fixed.** The verification test asserts the theorem command with both steps wrapped as executed; the refill test
  checks a new spare pid; new tests for the proof-state limit taking a spare, a cached panic not run again, the pool
  summary line.

### New code: bounded nlinarith, digest rule, record fields, sampling configs

Checked and sound:

- **No wrong proof can be accepted.** `verify_state` re-elaborates `theorem ... := by <executed proof>` (every step
  rewritten by `variant_tactic` and wrapped in its heartbeat limit) from scratch in the base environment with the
  definitions, then `#print axioms` against the standard axioms, as for every proof. The variant is metaprogramming
  only: it adds `sq_nonneg` / `mul_self_nonneg` facts and products built by `mkAppM` from Mathlib lemmas to
  linarith's hypotheses, and the kernel checks the final term. `partial def leanSearchDegree` only chooses products
  and never appears in a proof term. The forbidden-token check runs on the written text before the rewrite (steps in
  `_apply_tactic`; verification with `user_text = state.proof`), and `lean_search_nlinarith` is itself forbidden, so a
  policy cannot reach the variant or the wrapper directly; the rewrite emits only that keyword and a fixed variant name.
- **Recorded and executed text stay in lockstep.** The rewrite happens in one place, `_run_tactic`, so steps, replays
  (`_replay` -> `_run_tactic`) and re-runs agree. It is a pure function of (written text, pool config); the pool's
  config cannot change under a search (spares are built from it and `_adopt` asserts equality), and `_run_block`
  asserts that the search's variant is its REPL's (moved there in ab1256d, so REPL-less searches still build). The
  cache, the skip counter, the identifier check, name repair, de-duplication, `_replayed_states` and the tree all key
  on the written text, consistently. Rewrite coverage (tests): bare, hints, multi-line hints, after `<;>`, inside a
  nested `by`, inside `first`; left as written: `only`, `(config := ...)`, `!`, names containing the word, `linarith`.
- **Evaluations never see it.** `evaluation_run_config` sets `result_cache`, `timeout_skip`, `nlinarith_variant` and
  `spare_processes` to None; every pool is built with `search_repl_config` of the config its searches use (loop,
  evaluation, single step, pool search, search service, `run_search.py`, `search_variants.py`); fixed-target and probe
  evaluations build their own pools from evaluation configs; the options arm derives its config from the loop's (same
  variant). The sampling configs equal the student configs but for the switches
  (`test_a_sampling_config_is_its_student_config_but_for_the_switches`), the probe config has none, and an arm whose
  sampling record names another search config is refused against the shared run.
- **Digest rule.** Off: absent (None, dropped from the TOML), master's digests hold; spares never in the digest; on:
  the variant changes the digest (tested).

Should fix:

**S4. Variant-only proofs cannot be told apart in the records.** `search/search.py:826` keeps `plain_verified` for the
search's first proof only; harvested proofs (the sampling configs harvest up to 16 more expansions) and the
proof-graph nodes training reads carry no flag, although every `_verify` call computes it. The lean README says proofs
with `plain_verified = False` train the policy all the same but "must be filtered out of anything published as" plain
Mathlib; from the records that filter works for first proofs only, otherwise only by re-verifying every proof in plain
Lean. Rare by the measurement (degree's gains come from 4 of 300 jobs), but anything exported from the arms' trees (a
pool, a dataset, known proofs) would mix them in silently. Fix: keep `plain_verified` per proved node (`NodeRecord`,
`written_when_set(None)`) and count `plain_verified is False` proofs in the phase record. Related and latent: with
`[renaming]` on, `rl/renaming.search_problem` checks the proof against the original statement with `verify_proof` on
the written text (no rewrite), so a variant-only proof there becomes unsolved and loses its tree, unlike the same proof
without renaming. Renaming is off in the study (`followup/base.toml`); a README sentence, or refusing renaming together
with a variant, would keep it from surprising anyone.

**S5. The Lean-backed variant tests have not run since the variant was added.**
`tests/lean/test_nlinarith_variant.py::test_a_variant_proof_verifies_with_its_definitions` and
`::test_the_variant_fails_where_its_products_are_missing` need the REPL (skipped in WSL). The node's
`search_efficiency/lean_tests.log` (489 passed) finished at 16:24 UTC; 9dec8e1 is from 17:22 UTC. The experiment
showed that the definitions elaborate and the tactic runs in tactic mode, but not that the heartbeat-wrapped variant
verifies inside a `theorem` (the path every accepted proof now takes) or replays after a kill. Run the Lean tests on
the node before step 2's sampling uses the switch, and add one with the variant inside a nested
`have h : ... := by nlinarith [...]` (flattened and not) verified as executed, and one replay after a wall-clock kill.

Nits:

**N11. The variant definitions need Mathlib's linarith in every header.** `repl.py` `_base_definitions` appends
`VARIANT_DEFINITIONS` (`Linarith`, `sq_nonneg`, `mul_pos_of_neg_of_neg`) to the base command; a header that imports
Lean but not that part of Mathlib now fails every start with the message at `repl.py:927` ("needs Lean itself
(`import Mathlib` or `import Lean`)"), which is then wrong. The pools' headers import Mathlib, so only a future data
source would hit it; name the real requirement in that message when the variant is on.

**N12. Plain re-verification of a variant-only proof can stall the search's REPL.** `verify_state` always runs the plain
check; for a step only the variant finishes in time, plain `nlinarith` may spend the declaration's 200k heartbeats or
run into the 300 s command limit, which kills the process. The README states the cost; since the result is only a
statistic in the sampling, a shorter limit for the plain check under the variant would cap it.

**N13. A spare that can never start retries forever.** `pool.py` `_start_one`: a persistent failure (a broken project,
the memory cap during import) now logs an exception every `retry_seconds` (5 s) per spare slot for the whole run.
Back off exponentially or cap the attempts, and count the failures in the log line.

Trade-off, not a defect (DESIGN.md, the owner's decision): with degree on, about 7% of the policy's successful plain
`nlinarith` calls (161 scaled, 53-293) fail in the arms' sampling and become negative labels for texts that plain
Mathlib, and the evaluations, accept; the reverse case is rare (S4).

Verdicts: training branch, approve. Efficiency branch, approve once S5's node run passes (no code change needed unless
it fails); S4 before anything is exported from the arms' trees.
