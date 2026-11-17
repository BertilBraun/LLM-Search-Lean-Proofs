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
