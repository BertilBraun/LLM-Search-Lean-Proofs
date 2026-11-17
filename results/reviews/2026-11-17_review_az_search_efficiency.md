# Review AZ: search efficiency package and offline training throughput (use in the RL loop and the study)

Reviewer AZ, 2026-11-17. Independent of review AY (not read). Scope:

1. `worktree-agent-a884d29b93192b24f`, `git diff 33c96ea..3949496` (result cache, timeout skip, spare processes,
   measurement scripts).
2. `offline-training-throughput`, `git diff cb3d446..7f58dd7` (padded packed rows, dynamo recompile limit, median
   steady throughput).

Focus: what turning the switches on in the closed-loop arms would change in what the study compares and measures.

Tests (WSL, one suite at a time):

- Efficiency branch: `tests/lean tests/search` 490 passed, 167 skipped (Lean-dependent ones skip locally; the node ran
  `tests/lean` at the head: 489 passed). `tests/rl
  tests/expert_iteration tests/value` 2552 passed, 40 skipped, 0 failed (the loop golden test included: B1 does not
  show in any test, because none pins a run config digest).
- Throughput branch: `tests/training tests/rl/test_offline_build.py tests/rl/test_offline_configs.py` 151 passed, 9
  skipped.
- Digest check (scratch script, not committed): `planned_run_config_sha256` of `step1_run9_v0_value_v0_ordered`
  on master gives `eee4c06b…` (the digest recorded by runs 1, 2 and 9 on the node); on the efficiency branch, all
  switches off, it gives `25327704…`.

## Verdicts

- **Efficiency branch: not ready to merge** (B1: the default-off switches change every run config's digest, so every
  probe run made after the merge has another search identity than the step-1 anchors). Once B1 is fixed the
  mechanisms themselves look correct; S1-S5 are about using them in the study without breaking comparability or
  losing sight of what they do.
- **Throughput branch: ready to merge** after S6 is decided (the dynamo recompile limit is not behind the new setting:
  it changes every trainer with `compile_layers`, arms A-D and the value trainer included). The padding itself is
  correct and is a no-op at the default 0, so arms C and D are unchanged by it.

## Blocking

### B1. The new config fields change the run config digest at their defaults

`src/lean_search/search/config.py:41` (`LeanConfig.spare_processes: int = 0`), `src/lean_search/search/search.py:139-140`
(`SearchConfig.result_cache: bool = False`, `timeout_skip: TimeoutSkipConfig = field(default_factory=...)`).

`run_config_sha256` (`rl/probe_evaluation.py:388`) hashes `run_config_text`, which is `toml_text(without_none(asdict(config)))`
(`rl/search_models.py:92`). Only None-valued fields drop out; `0`, `False` and a default `TimeoutSkipConfig` table are
written, so every config gets three new keys and a new digest. Measured: the planned digest of run 9 goes from
`eee4c06b…` (master; identical to what runs 1, 2 and 9 recorded on the node) to `25327704…` with the branch, switches
all off.

Failure scenarios once this is merged and deployed:

- Arms' probe runs vs the v0 anchors (`step1_run1/2_v0_value_v0`): `arm_comparison.check_comparable`
  (`rl/arm_comparison.py:164-165`) refuses "The runs differ in their search config" unless `--across-search-modes` is
  passed to `probe_compare.py`, which also switches off the check that protects against a real config difference.
  `run_identity` (`rl/probe_evaluation.py:166-173`) embeds the digest, so `probe_rating` pools no new v0 run with the
  anchors.
- A probe run started before the deploy and resumed after it is refused by `refuse_another_start`
  (`experiments/probe_evaluate.py`, the identity) and by `probe_run_list.start_mismatches` ("run config digest",
  `rl/probe_run_list.py:202`). The chains deploy master by themselves at boundaries; a crash-and-resume across a deploy
  would stop the chain.
- The learning-rate step's gate comparisons (`rl/rate_ranking.py:155`) and the offline arm's comparisons against the
  v35 runs inherit the same split if any of their runs straddle the deploy.

Suggested fix: keep the digest of an unchanged config unchanged.

- Make the outcome-changing switches None by default (`result_cache: bool | None = None`,
  `timeout_skip: TimeoutSkipConfig | None = None`, None meaning off), so `without_none` drops them; or drop
  default-valued new fields in `run_config_text`.
- Leave `lean.spare_processes` out of the identity altogether (it changes timing, not outcomes): e.g. zero it before
  hashing in `run_config_sha256`, so the owner can turn spares on for probe runs without making them incomparable.
- Pin it with a test: the digest of `probe_run_config` for `followup/probe_evaluation.toml` equals `eee4c06b…` (or
  equals master's at the merge), and a second test that turning `spare_processes` on keeps it.

## Should fix

### S1. Probe and held-out evaluations share the loop's search config file: decide and enforce where the switches go

`experiments/configs/grpo/followup/base.toml:100` (`sampling.search_config = visible_student_v2.toml`) and
`probe_evaluation.toml:10` name the same file (`modes/no_reasoning.toml` names `no_reasoning_student_v2.toml`, which
the token-capped step-1 configs also build on). If the switches are turned on by editing that search config, the arms'
probe runs change too, and then:

- the timeout skip changes probe outcomes slightly (on run 4: 25 successful steps lost, 0 on proof paths at 2 stops;
  2 proofs lost at 1 stop), and the result cache changes Lean seconds per attempt by about 6%;
- the start-order check's "Lean-load figures match" and every Lean-load comparison against the anchors
  (`rl/lean_load.py`: wall-clock stops, REPL failures, Lean s per policy attempt) compare runs with and without the
  switches: the skip removes about 6% of the real stops (528 of 8,705 on run 4), the cache removes about 6% of Lean
  seconds.

`study_configs.sampling_refusal` already refuses an arm whose sampling (search config bytes included) differs from the
shared sampling run's, so the switches must also be set before step 2's shared sampling, not between it and the arms.

Suggested fix: put the switches in the sampling mode files' search configs only (copies of the two student configs
with `[search] result_cache = true`, `[search.timeout_skip] enabled = true`, `[lean] spare_processes = N`), keep
`probe_evaluation.toml`'s search config unchanged (spares may go everywhere once B1 keeps them out of the digest), and
add a `test_study_configs` case that the probe evaluation's search config has the cache and skip off. If the owner
wants them in probe runs too, that needs a v0 A/A with the switches on before any arm is compared with the anchors.

### S2. The new counters reach no phase record, dashboard or log

`Accounting.cached_tactics / cache_saved_seconds / skipped_timeouts` and `StepStatistics.skipped_timeouts` are written
into `results.jsonl` and the trees only. `rl/phase_metrics.search_phase_record` (`SearchPhase`), `rl/tree_summary.py`,
`monitoring/families.py` and `rl/lean_load.py` do not read them, and `LeanRepl.spare_swaps / spare_misses` are read by
nothing but `experiments/analysis/restart_cost.py`.

Failure scenario: arm B's policy drifts toward long `nlinarith` hint lists; the skip fires more each phase, and the
dashboard's "wall-clock timeout" edges (`tree_statistics.EdgeKindCounts.wall_clock_timeout`, which counts skipped edges
through `EdgeKind.WALL_CLOCK_TIMEOUT`) rise while the real stops fall, with nothing to tell the two apart in the
loop. Likewise nobody can see on the node whether spares are ready when kills come in bursts (the restart-cost test
swapped 56 of 80 kills with 8 spares; p90 6.8 s), or whether 8-12 is enough at 112 searches.

Suggested fix: add `skipped_timeouts`, `cached_tactics` and `cache_saved_seconds` to `SearchPhase` (summed over the
phase's trees, like `lean_seconds`), a skipped count beside the wall-clock stops in `lean_load` (`LOAD_HEADER`), and log
the pool's spare swaps, misses and ready count with the loop's periodic Lean/host-memory line and at the end of each
evaluation.

### S3. No config-level tests; the "defaults keep existing configs" property is not pinned

`tests/lean/test_timeout_skip.py`, `test_search_memory.py`, `test_spare_processes.py`, `test_memory.py` test the
mechanisms with in-code configs. Missing:

- `parse_run_config` refusals: `lean.spare_processes = -1`, `search.timeout_skip.max_wall_clock_timeouts = 0`
  (`search/config.py:59-60, 81-82`);
- a TOML with `[search] result_cache = true` and `[search.timeout_skip] enabled = true` loads into the expected
  dataclasses (nothing else exercises the table names the owner will type);
- the digest pin of B1;
- a search with both switches off produces the same tree record as before (the edge now always carries
  `cached_tactics: 0` and accounting three more keys; old records read back with defaults, which is fine, but nothing
  pins that an off search is otherwise unchanged; `tests/rl/golden/grpo_only_loop.json` covers the loop's records, not
  a tree).

### S4. Documentation for the loop is missing

Only `src/lean_search/lean/README.md` describes the switches. `src/lean_search/rl/README.md` (how a loop turns them on,
that they belong in the sampling search config and must be on from the shared sampling onward), `DESIGN.md`
"Follow-up study: controlled arms" (Automatic rules: identical for every arm; the label of a skipped tactic; Lean-load
health counting only real stops), and `deployment/README.md` / `results/followup_node_operations.md` (spares' memory
and CPUs) say nothing. The host-memory budget (`rl/host_memory.budget_conditions`) assumes the paused searches' REPLs
are stopped during training and evaluating; spares are not stopped by `stop_idle_processes` or `stop_processes`, so
the budget should name them (small: 0.24 GiB private each, about 3 GiB at 12, plus the shared olean pages they keep
mapped), or the training pause should stop them too.

### S5. The nlinarith summary's "successes" and "gained" columns are dominated by one or two jobs

`experiments/analysis/nlinarith_variants.py:539` `weighted_lines` scales each stratum by count / jobs. In the 17+
heartbeat-timeout stratum (13 jobs standing for about 9,000 calls, about 696 each) a single job
(`lean_workbook_30814`, edge 385) succeeds for linear, goal_hints, degree and cap8 while the original and `full` hit the
heartbeat limit. That one job is 696 of the 696-794 "gained" of every variant, and is most of why degree's scaled
successes (2,843) exceed the original's (2,210). Similarly degree's two 7-12 wall-clock gains are two tactics of one tree
(`lean_workbook_plus_49922`, edges 22 and 61). The "hours" column for the wall-clock and heartbeat strata rests on 12-13
jobs each with large weights.

The conclusion in `results/followup_progress.md` (master `83de1dc`): "only the degree-bounded variant keeps most
successes (93%)" is supported (in the four success strata the original re-run succeeds on 119 jobs; degree keeps 111
and loses 8, goal_hints loses 29, cap8 32, linear 53); "No default change; a search A/B would be needed" is the right call.
"cutting nlinarith time by about 29% (about 20% of all Lean time)" is a point estimate with a wide interval (strata of
12-13 jobs, timed alone at 32 processes rather than under 112 searches) and should be quoted as such.

Suggested fix: print bootstrap intervals (resample jobs within strata) for hours, kept and lost, and drop or footnote
"gained" and the variants' total successes; state that the population counts every policy `nlinarith` step while the
jobs are only plain `nlinarith [...]` forms. For the A/B, decide first what text a successful step records: if the
search runs `lean_search_nlinarith degree [...]` in place of the policy's `nlinarith [...]`, the proofs that train arms
C and D (and the published data) must still verify with plain Mathlib, which "plain nlinarith has a certificate too,
but may take longer to find it" does not guarantee within 50k heartbeats.

### S6 (throughput branch). The recompile limit applies to every trainer, not only the offline arm

`src/lean_search/training/sft.py` (7f58dd7), `load_trainable_model`: `torch._dynamo.config.recompile_limit` is raised
to 64 whenever `optimization.compile_layers` is true. `load_trainable_model` is used by the GRPO policy trainer
(`rl/policy_trainer.py:619`), the value trainer (`value/graph_trainer.py:443`), the resident trainer
(`training/resident.py:271`) and expert-iteration rounds (`rl/expert_iteration_training.py:107`); the study's
`expert_iteration.toml` and phase policy have `compile_layers = true`. So arms A-D and value training all change at the
default `packed_length_multiple = 0`: more shapes compiled instead of falling back to eager (small numerical
differences, more compile time in the first steps of each trainer process, more kernels resident in the one
persistent trainer of arm D). It is the same for every arm, and no arm has run, so it does not bias the comparison; it
does make "arms C, D unchanged at the default" untrue, and it lands in the untested-on-the-node area of section 8 B
(GPU memory of GRPO plus a round in one trainer process, recompiles).

Suggested fix: either tie the raise to the offline arm (a setting, or the caller), or keep it global and add it to
the smoke-test list for arms C and D (compile time of the first GRPO step and of a round, peak reserved memory) and to
the commit/README wording.

## Nits

- N1. `src/lean_search/lean/memory.py:10-18` `TacticInput` has no wall-clock limit: a success cached from a run with
  the policy's 60 s limit is reused for a call with another `timeout_seconds` (the sweep's `None` means the same 60 s
  emergency stop today, so harmless now). One comment line or include it in the key.
- N2. `src/lean_search/lean/pool.py:60-66, 87-90` `SpareProcesses.close` cancels the `_close_later` tasks it keeps in
  `_starting`; a cancelled `LeanRepl.close` skips `_kill_process` (the CancelledError leaves `wait_for`). The REPL has
  had stdin closed and should exit on EOF, so this only risks a stray process until then. Keep closing tasks in their
  own set and await them without cancelling.
- N3. `src/lean_search/lean/pool.py:68-85` after a failed spare start the task sleeps and ends; nothing calls `fill`
  again until the next `take`, so a transient failure leaves fewer spares until the next kill (which then misses).
  Refill at the end of `_start_one` (if not closed).
- N4. `LeanRepl.spare_swaps` also counts the restart of a REPL that `stop_idle_processes` or `stop_processes` stopped
  (its next use goes through `_ensure_healthy`, `use_spare=True`); after each training pause the first N searches take
  the spares. Fine behaviour; the lean README's list ("a wall-clock kill, a crash or panic, the memory or proof-state
  limit") should name it, and S2's log should not read swaps as kills.
- N5. `src/lean_search/search/summary.py` adds a "skipped timeouts" column to every run's markdown summary, a column
  of zeros when the skip is off; `CostMetric` has no entry for the new accounting fields. Either is fine; decide.
- N6. `experiments/analysis/nlinarith_variants.py:246-259` `read_population` counts every policy step whose tactic name is
  `nlinarith` (also `nlinarith!`, `only`, config forms), while `select_jobs` keeps only plain forms; the scaling
  assumes the plain form is representative. Say so in the summary.
- N7. `experiments/analysis/nlinarith_variants.py` jobs come from the 1,972 statements with a header in the probe set;
  the population from all 2,000. Negligible, but the header line says it.
- N8. Throughput branch: `steady_tokens_per_second` is now the median per-step rate. It reads higher than the
  sustained rate whenever stalls recur (validations, recompiles, checkpoint writes); fine for its use (a record, not a
  budget), but the summary label "steady" should say "median step" where the owner reads it, and nothing should plan
  wall time from it.
- N9. Throughput branch: validation batches (`validation_metrics`) are not padded, so validation points can still
  meet new kernel specializations; harmless (no grad), only a small stall at each validation.

## Checked and fine

- **Result cache correctness.** The key is the state's whole tactic path with each step's heartbeat limit, plus the
  tactic and its limit (`memory.TacticInput`); wall-clock stops and REPL failures are never cached
  (`memory.is_deterministic`); deterministic panics are cached as errors, so a panic is not re-triggered. A cached
  success hands back the recorded `ProofState`; on a restarted process it is replayed through the existing path
  (tested: `test_a_cached_state_from_a_killed_process_is_replayed_to_continue`). Outcomes, edges, children, labels
  and proofs are the same as without the cache; only `elapsed_seconds` / `lean_seconds` drop, and Lean seconds feed no
  reward, value label, priority or phase-ending rule (checked `grpo_groups`, `advantages`, `token_credit`, `loop.py`,
  `search/` priority code).
- **Skip labels.** `Failure.from_lean` maps `LeanTimeout(skipped=True)` to `SKIPPED_TIMEOUT` before the wall-clock case;
  `graph_labels.failure_edge_kind` gives `EdgeKind.WALL_CLOCK_TIMEOUT` (a failure, so L = -1 like a real stop, the
  first failing tactic for token credit), `is_negative_label` is true, `phase_metrics.failure_tier` and
  `search_variants.error_category` say timeout, `preferences.TIMEOUT_FAILURES` includes it,
  `policy/expander.FEEDBACK_FAILURE_KINDS` excludes it like a wall-clock stop, `tree_summary.judged_by_lean` and
  `ran_completely` treat it like any failure (the valid-Lean rate counts it invalid, as a real stop). Every
  `match failure.kind` in `src/` was checked for an unhandled member.
- **Does the skip teach the right thing.** On run 4 the rule at 2 stops avoids 528 real stops and turns 25 successful
  steps into -1 labels, none on a proof path; the label is right for the great majority of skipped calls. It cannot amplify itself: a skip needs
  two real stops of the same text in the same search, the memory is per search, and a policy pushed away from hanging
  texts makes it fire less. What it hides: the true outcome of the skipped call (its message is the synthetic "Not
  run" one) and, under heavier Lean load (no-reasoning mode, the longest-first start), it spreads load-induced stops to
  later samples of the same text in that search. Both are small at 2 stops; S2 makes them visible.
- **Expert-iteration data and value labels.** Only verified proof-graph blocks train C and D; a skipped edge is never
  on a proof graph; the cache yields identical states and proofs (`test_a_proof_through_a_cached_tactic_verifies`).
  Value labels come from the graph; a skip can turn a node with a single would-be success into a dead end, which run 4
  says did not happen on a proof path.
- **Token matching.** Generated tokens per phase are charged per request and are untouched by either switch; phases
  end on tokens, so faster Lean does not change what an arm trains on, only how long a phase takes.
- **Automation sweep.** It already disables a tactic after one wall-clock or heartbeat stop (`expanders.AutomationConfig`),
  counted from `SearchTree._timeouts_by_text`, which excludes skipped edges; with the threshold at 1 that changes
  nothing.
- **Spares mechanics.** `take` drops unhealthy spares; `_adopt` moves the process, its environments, stderr reader and
  proof-state count and opens a new session so states replay; spares start from the event-loop thread (PDEATHSIG holds,
  so a crashed loop leaves none); `pool.close` cancels starting spares and closes ready ones (tested); `_restart` of
  released REPLs does not consume spares; all six pool constructions (`loop_services`, `evaluation`, `single_step`,
  `pool_search`, `search_service`, the two experiment scripts) pass the config's value.
- **Spares' memory and CPUs.** Measured 0.24 GiB private per ready spare (3.49 GiB resident, the rest shared olean
  pages); at 112 searches plus 12 spares the addition is about 3 GiB against the 182.6 GiB limit. Spares are children
  of the search process, so they inherit its CPU list (socket 1 for Lean) and niceness, and idle at 0 CPU; their imports
  cost what the restarts they replace cost. Pools persist across loop phases and server restarts; a loop restart
  makes a new pool.
- **Config validation.** Negative spares and `max_wall_clock_timeouts < 1` are refused at load; unknown keys are
  refused by `from_json_object`, so a mistyped table name fails loudly.
- **Padding (throughput branch).** `-sum(lengths) % multiple` padding as its own segment with ignored labels and
  restarted positions, appended at the end (causal layers, the linear-attention layers included, cannot see it);
  the loss scale uses the precomputed completion tokens; `tokens` and tokens per second count real tokens, the padding
  only `padded_tokens`; at `packed_length_multiple = 0` `pack` builds the same tensors as before. The offline config
  test now allows exactly that one key to differ from the expert-iteration recipe.
- **nlinarith method.** States are rebuilt from the tree path and checked goal for goal (`same_goals`), 300 of 300
  rebuilt; every variant runs on the same state in a seeded random order after a `skip` that forces any replay first,
  at the search's 50k heartbeats and 60 s; the 3949496 fix (a step that closes its goal while others stay open counts
  as a success) is right for block steps and applies to the original and variants alike; `full` reproduces the
  original's success or failure on all 300 jobs (3 differ only between error and wall-clock stop), a good check of
  the reimplementation.

## Questions for the owner

1. Where should the switches be on: only in the arms' training sampling (and step 2's shared sampling, which must
   match), or also in the arms' probe runs? The latter needs a v0 A/A with the switches on before arms are compared
   with the anchors (S1).
2. Spares in probe runs and held-out evaluations as well (timing only, once B1 keeps them out of the run identity)?
   How many: the measurement suggests 8-12 per pool; with three pools alive at once (sampling, held-out, a probe run)
   that is up to 36 idle processes.
3. Should the arms' Lean-load health readings count skipped calls with the real stops (they are labelled as stops) or
   apart (as the branch does)? Apart is better for load, together for "what the policy tried".
4. The bounded-nlinarith A/B: should a successful bounded call record the policy's `nlinarith [...]` text (what the
   policy learns to write) and must every recorded proof then re-verify with plain Mathlib within the limits?
