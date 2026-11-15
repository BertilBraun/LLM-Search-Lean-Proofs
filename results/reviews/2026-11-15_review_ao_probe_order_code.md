# Review AO: probe submission order, GPU power records, reserve refusal, durable-copy affinity, code

Branch `worktree-agent-ab19668c33deedbef` (c8f2039, 4f9eacd, a258d8c, c43f952, a88e657). I ran the affected tests in WSL
(test_submission_order, test_probe_runs_script, test_gpu_power, test_cpu_layout, test_node_pinning, test_loop_handoff,
test_loop -k gpu/order/...): 117 passed. I also checked the LoopProgress round trip with `phase_start_gpus` and the
parser on `[Not Supported]` and on an "Unable to determine the device handle" line. Not run: a node, real nvidia-smi.

## Item 1: what the order touches (traced)

Selection is unchanged: `probe_evaluate.evaluate` l. 274-275 takes the pilot before `in_submission_order` (l. 335).
Nothing depends on position. Exploration is seeded by `"{seed}:{problem.name}"` (search.py l. 378). Policy sampling
carries no seed at all (nothing passes `seed=`), so each search is a fresh random draw in either order. Server
rotation follows request timing, the REPL pool is LIFO by release, and `common_headers` is set-based. Results,
`stops_by_stratum` and `dropped_statements` are keyed by name over the file-order list. `stratum_outcomes` sorts its
strata. A resume runs `pending_problems` in the current order. The sort key is right for every study set: LPT only
needs it to rise with search length, and that holds for the gate set's tactic count plus root value too. A tie keeps
file order (a stable sort).

## Comparability: where wall-clock time reaches a result

- It does through: the 60 s tactic backstop (it kills the REPL; `max_wall_clock_timeouts_per_tactic = 1` then disables
  that sweep tactic for the rest of the tree); the 120 s replay after any restart; the 300 s command timeout
  (`verify_state`; a failed verification rejects a found proof); the 7,200 s search cap; the policy request timeout
  (900 s; a TransportError counts as a server error, so the whole search is redone from scratch).
- It does not, here: the DeathRule probes (run only after a failure), the idle-stop (tail only, idle REPLs only), the
  token budget (counts tokens), the retries (a fresh draw either way). vLLM's batch-dependent numerics are noise, not
  a bias.
- Load estimate. Hard statements at 140 searches used 74 cores, about 0.53 a search, so 112 all-hard searches use
  about 59 of Lean's 96 CPUs. Those 96 CPUs are 48 physical cores (n, n+96), so at least 11 cores, and in practice
  more, run two REPLs, and a Zen 2 thread with a busy sibling runs at roughly 0.6-0.7x.
- The peak is not new. In file order the hard third (about 670 statements, 6 waves of 112) already runs at all-hard
  load, except its last wave, whose co-runners finish and leave it mostly a core of its own. The new order puts that
  hardest wave first, at full load. So the 100-200 longest-proof statements run about 1.4x slower in Lean than in the
  anchors, and everything else sees about the same load.
- At 1.4x, a step above about 43 s unloaded crosses 60 s. Such steps exist: 200k-heartbeat sweep tactics; at 100k,
  2 of 10 former timeouts still hit 60 s; DESIGN l. 1444 reports proof-path `nlinarith` steps at 17-59 s.
- Expected effect: a few statements a run, all in the top band, all against the new-order run. That is too small for
  the acceptance gate, but it is not noise: it is a bias in the stratum where gains matter most.
- How a run would show it: more `wall_clock_timeouts` in `step_statistics` and more `repl_failures` in the top band,
  higher Lean-seconds per expansion there, and lost solves where the anchors' proof path has a step above ~40 s.
- Recorded today only per search: `SearchResult.step_statistics[].wall_clock_timeouts` in results.jsonl
  (`Accounting.timeouts` lumps both kinds). It is not in run.json, the summary, the ledger or `probe_rating`.

## Must fix before merge

- **M1. A deploy now mixes orders inside the anchors.** `probe_runs.sh` l. 95 starts each run's `probe_evaluate.py`
  from the current checkout, and the order comes from the config at each session (`evaluate` l. 303, 335). A `git pull`
  during run 1 starts run 2 (the A/A repeat, `runs_anchor.toml`) hardest-first, so the noise floor mixes orders. A
  resumed run 1 would also finish its remaining hard statements hardest-first. Nothing refuses this; only
  sessions.jsonl shows it. Fix: a run keeps its first session's order (read it from `read_sessions` and log any
  differing config). Deploy only after run 2 has started, or decide explicitly which order the anchors use.
- **M2. A hung nvidia-smi blocks the run, which contradicts the docstring.** `gpu_power.gpu_power_states` l. 49:
  on timeout, `subprocess.run` kills the child and then calls `process.wait()` with no timeout on POSIX (checked in
  3.12). nvidia-smi typically hangs in uninterruptible sleep in the driver (a wedged GPU, a GPU off the bus), and
  SIGKILL does not end it. The hang hits three places: probe start (`evaluate` l. 303, synchronous on the event loop,
  under the serving lock), probe end (l. 371, before run.json is written), and the loop (l. 1083 before the first
  search; l. 1417, where the phase never closes while the process looks alive to the watchdog).
  Fix: `Popen` plus `communicate(timeout)`; on timeout, kill and `communicate(timeout=1)` inside a `try`, then return
  None without reaping. Add a module-level latch so that after one hang every later call returns None; without it
  each phase leaves one more stuck process (no threads pile up, since each call is awaited).
- **M3. The argument cannot be checked from the run record.** Add to `probe_evaluation.run_record` (l. 1015) and
  `StratumStops`: the tactic wall-clock timeouts in total and per stratum, the statements with at least one, and REPL
  failures (summed from `step_statistics`). Have `probe_rating` print each paired run's order(s) and these counts
  beside the anchors'. Gate the switch on the zero-cost check under "Verdict".

## Should fix

- **S1. The reserve refusal is reached only through launchers.** `pinning_check` runs only in `node_checks.py pinning`.
  `grpo_loop.sh` l. 52 calls it with `|| true`, and the direct `background.sh python experiments/probe_evaluate.py`
  documented in `gate_evaluation.toml` l. 6-8 never runs it. Fix: run `pinning_check` in `record_session_pinning`
  (node_pinning.py l. 241) when `require_background`, and refuse there.
  Arithmetic: 96 + 8 = 104 ≤ 105.3 passes; `144-191` passes; the message is right.
  A malformed `SERVER_RESERVE_CORES` raises a traceback from `current_pinning` (l. 102), outside the try in
  `node_checks` l. 110, and `nan` passes every check. Fix: validate it as a finite number ≥ 0 and refuse in one line.
  The override is recorded only in pinning.jsonl, which is fine. Add it to `layout_differences` so a resume with
  another reserve shows.
- **S2. The clocks are read at idle moments.** Every reading falls at a session start after the swap, a run's end or
  a phase boundary, so `clocks.sm` and `clocks.mem` read idle or boost values and show nothing about throttling. Fix:
  record `clocks.max.sm`, `clocks_event_reasons.active` (`clocks_throttle_reasons.active` on older drivers),
  `power.draw` and `temperature.gpu`, or sample them during the run. The power limits themselves are right.
- **S3. A GPU off the bus loses every GPU's reading.** It makes nvidia-smi exit non-zero (`check=True`) or print a
  line that does not parse (`parsed_states` returns None for all). Fix: keep the lines that parse and record the
  missing indices. A restart's session (`ProbeServers.restart`, l. 831) records `gpus=None`, which is exactly when
  a reading matters most: query there in a thread.

## Minor

- `phase_start_gpus` None means both "not queried" and "query failed". After a failed query, a mid-phase restart
  (loop.py l. 1083) stores the restart's reading as the phase start. Use a separate flag.
- `thread_on_cpus` really is per thread (Linux affinity is per task; the TID comes from `get_native_id`), and the
  `finally` restores it on every exit path, including a cancelled awaiter, since the worker thread runs on.
  `copytree` and `rmtree` are single-threaded with no pool or child process (the CPU merge already goes through
  `taskset`). The `sendfile` copy runs in that thread, but page-cache writeback runs in unbound kworkers on any CPU,
  so "moved off Lean's CPUs" holds for the copy, not for its I/O. The default `TRAINING_CPU_LIST` is the servers'
  CPUs, which is fine (servers use under 4 cores) and NUMA-local to the handoff. There is no test of the restore after
  an exception.
- `probe_runs.sh`: the empty `passed_on` array is safe under `set -u` (bash ≥ 4.4), and the quoting and the detached
  re-exec are right. An option after the lists (`runs.toml --allow-other-pinning`) is read as a list path and fails
  in `probe_runs.py check` with an unrelated message. Passing the flag to every run sets
  `other_pinning_allowed=True` on sessions whose layout is unchanged (l. 243). Record it only when
  `layout_differences` is non-empty.
- The documented pid check matches `orphaned_server_group`'s use of `server_member` (the `written` and `group` args).
- Tests: the most important missing one runs `search_problem_set` with a fake search in both orders and asserts the
  same results by name, the same summary and the same `stops_by_stratum`. Also missing: a resume where a file-order
  session is followed by a longest-first one (after M1, it keeps file order). The GPU tests cannot model a D-state
  hang; test M2's latch instead. The rest test behaviour, not implementation.

## Verdict

Comparability: likely fine, not shown. Pair new-order runs with file-order anchors only after this zero-cost check
on the two anchors' results.jsonl:
- Sum `wall_clock_timeouts` per statement and place each search in time (completion order and `wall_seconds`).
- Compare the top band's rate during its full-load middle with its low-load last wave.
- Count statements whose proof path has a step above 40 s; that count bounds the bias.
If timeouts are about zero, or equal in the middle and the tail, pair freely. If not, run one v0 in the new order
(4 h) and compare its flips against both anchors with the A/A flip count.
**Merge after fixes** (M1-M3), with the study's order switched on only after that check.

## Re-review (76757f7, 7dc0230, 21d99dd, ae3ea5d)

WSL: `tests/rl` and `tests/monitoring` **1962 passed**. I ran `lean_loads` and the old-record reads against
`node_backup/2026-11-14/anchor_v0_value_v0_run1`.
- **Order removed completely.** Against master, `evaluation.py`, `fixed_targets.py` and the configs are untouched.
  Selection, pilots, resume and `ProbeRunStart` are as on master, and the sessions gain only `gpus` (default None).
  A master run resumed here behaves identically: old sessions.jsonl, run.json and pinning.jsonl read, and the identity
  is unchanged. M1 no longer applies.
- **M2 resolved.** `Popen` plus `communicate(timeout)`, a kill without a wait, and the `hung` latch: at most 10 s
  once per process at probe start, at probe end (before run.json) and at each phase close, then None at once. The
  killed process stays a zombie, or stuck in D state, only until it ends; any later `Popen` in the process (asyncio's
  included) reaps it. That is one entry and one pipe fd over 30 h, which does not matter. A lost GPU drops only its
  own line. Minor: one slow nvidia-smi (>10 s) latches the query off for the rest of a 30 h loop; a restart's
  session still records `gpus=None`.
- **M3 resolved, and the figures are right.** 3,001 tactic wall-clock timeouts in 379 statements, 11 REPL failures,
  180,964 policy attempts, 4.03 Lean s per attempt, all equal to a raw count of results.jsonl. Old run.json files read
  with `lean_load = ()`, and `probe_compare load` reads results.jsonl, so it works for any run directory.
- **The figures change the earlier estimate.** 2,957 of the 3,001 wall-clock timeouts are policy steps, beside 7,422
  policy heartbeat timeouts. The 60 s backstop fires in 19% of the anchor's statements, so load does reach
  outcomes, and a Lean-heavier checkpoint loads its own searches. Read the load table on every pairing, and look at
  which policy blocks pass 60 s under 50k heartbeats (a study question, not this branch's).
- **Reserve refusal resolved.** `record_session_pinning` refuses the quota and the reserve whenever exactly one
  background setting is set. Unpinned runs and tests skip it. The study node's 96 + 8 ≤ 105.326 passes, and
  `abc`/`-50`/`nan`/`inf` are refused in one line (`node_checks` now catches it too). Note that a loop on a node whose
  file sets `BACKGROUND_CPU_LIST` is now refused where `grpo_loop.sh`'s `|| true` let it start.
- Nothing new is dangerous. **Verdict: merge.**
