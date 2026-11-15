# Review AM: node portability (cgroup v1 quota, CPU lists, server niceness, tracker members), code

Branch `cgroup-v1-quota` (347f96b, e30104c, cf3acd2, c14be9e, d61ade6, def7da0). WSL (non-root, 4 CPUs, cgroup v2):
`tests/monitoring`, `test_node_pinning.py`, `test_serve_model.py`, `test_server_starts.py` 231 passed, 1 skipped (the
root-only niceness test). Kill scenarios run `stop_model.sh` against harmless processes started by the script (a
fake `vllm` sleeper, a real `multiprocessing.resource_tracker` reading a FIFO, `python -c` sleepers). Not run: real
vLLM, a root shell, a cgroup v1 kernel. Scripts: `C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_am\`.

## Kill safety (stop_model.sh, orphaned group, leader exited)

| State | Expected | Observed |
|---|---|---|
| vLLM + tracker recorded while the leader lived (parent = group) | stopped | stopped; **60 s**, SIGKILL to the group (tracker ignores TERM) |
| Tracker recorded after its parent died (recorded parent 1) | refused | refused, nothing signalled |
| Plus an unrecorded `python -c` in the group | refused | refused, all 3 alive |
| Old two-field `.members`, live tracker | refused | refused (vLLM members alone would still pass: compatible) |
| `.members` of another group | refused | refused |
| Recorded pid with another start (branch test) | refused | refused |

The SIGKILL goes to `-group`, not to the verified pids. That is safe: a pgid cannot be reused while any process holds
it, and only a member's own children or a process of the same session (the server's) can join it. The window
between the last `live_group_members` and `kill` is the only race, as on master. Under `setsid nohup taskset nice
vllm` every step execs (the `&` child of a non-job-control shell is no group leader, so `setsid` does not fork):
the pid file names the API process and its start time is the fork's, so `trusted_server_pid` holds. The branch test
covers this.

## Must fix before merge

- **M1. The niceness reset needs CAP_SYS_NICE, not root, and Docker does not grant it by default.**
  `serve_model.sh` l. 49-53. Lowering the niceness needs CAP_SYS_NICE (or RLIMIT_NICE). Docker's default capability
  set leaves it out, so root in a Vast container is very likely refused. Nothing in the repo shows the node allows it.
  Without it, every server start from a niced caller is now refused: the loop runs through `background.sh` whenever
  the node file sets `BACKGROUND_CPU_LIST` (`grpo_loop.sh` l. 92), and it starts servers at the session start, on
  publish and on restart; `probe_evaluate.py` and `held_out_evaluate.py` restart through the same path. On master
  those starts worked, slowly, at nice 19 on Lean's CPUs. With the branch, `start_server` retries twice, then the
  run or the loop stops. That happens hours in, on the restart path, and on v2 nodes too ("v2 unchanged" does not
  hold for this). Fix:
  (a) On the node, now: `grep CapEff /proc/self/status`, and `nice -n 19 nice -n -19 nice` must print 0. Also run
  `test_a_server_started_by_a_niced_caller_runs_at_niceness_zero` there as root.
  (b) Check it where the launchers start. In `node_checks.py pinning`, have a forked child call `os.nice(19)` then
  `os.setpriority(..., 0)`, and refuse on EPERM. Print the same in `grpo_loop.sh node-check`.
  (c) If the node does not allow it, the privilege-free design: `background.sh` only pins, the Lean REPL spawn raises
  its own children to nice 19 (raising needs no privilege), and `serve_model.sh` only resets the affinity.
  Change the message "needs root" to name CAP_SYS_NICE.

## Should fix (before the first arm on this node)

- **S1. Training ranks and the persistent trainer run on Lean's CPUs at nice 19.** `loop_services.training_launcher`
  l. 345-350 (used by `SubprocessTrainer` l. 396 and `PersistentTrainer` l. 590) prepends only `command_prefix`, so
  the ranks inherit the loop's `taskset 48-95,144-191 nice 19`. Ranks for GPUs 0-2 then run on the remote socket and
  share 96 CPUs with REPLs at equal niceness: data loading, collation, NCCL proxy threads and the optimizer step. That
  slows every pause, and more while training runs next to a search (README "36"). Fix: the launcher prepends
  `taskset --cpu-list ${TRAINING_CPU_LIST:-$SERVER_CPU_LIST} nice -n <-os.nice(0)>`, under M1's caveat (affinity only
  under M1(c)). `run_in_background` still pins the preparation thread. `expert_iteration/trainer.py` l. 740-741 already
  does the affinity half. Apply it to every arm alike, and log it.
- **S2. No check that the Lean and server sets are disjoint.** `node_pinning.pinning_refusals` l. 115-137. That split
  is the point of the layout, but a node file that sets only `BACKGROUND_CPU_LIST` (or a typo) leaves
  `SERVER_CPU_LIST` at the whole cpuset (`environment.sh` l. 47), and servers share Lean's cores silently. Fix: when
  `SERVER_CPU_LIST` differs from the cpuset default, refuse an overlap with the background set. Also print the
  overlap in counts of physical cores (n, n+96).
- **S3. "Below the quota" leaves almost nothing.** l. 128: 96 CPUs pass against 105.3 cores, which leaves 9.3 cores
  for 8 vLLM processes, 2-4 DDP ranks and the orchestrator. The README's own rule is "leave at least 6", and that was
  with 4 servers. Fix: refuse `quota - len(pinned) < FEEDER_RESERVE_CORES` (named constant, e.g. 8) and print the
  headroom, unless the throughput test shows 96 does not throttle.
- **S4. Node file failures.** `environment.sh` l. 22-24, observed:
  - A failing command in the file exits every script with status 1 and **no message**.
  - Without `set -e` (the README's `source deployment/environment.sh && pytest` pattern, interactive `on_node.sh`
    use), a syntax error prints, half-applies the file and continues with status 0.
  - A relative `LEAN_SEARCH_NODE_ENVIRONMENT` is accepted and resolved against the working directory.

  Fix: require an absolute path; run `bash -n "$file"` first and fail with the file's name; follow `source` with
  `|| { echo "node environment $file failed" >&2; exit 1; }`. Record the file's path and sha256 in `pinning.jsonl`
  (`node_checks record`). Only the three CPU settings are recorded today, not mirrors or `NCCL_P2P_DISABLE` set there.
- **S5. Old `BACKGROUND_CPUS=` commands.** The first refusal a launcher hits is `pinning_refusals`' "Set exactly one
  of ...", without background.sh's useful hint (the node file; `BACKGROUND_CPU_LIST=` unsets it). Add the hint there.
  Still in the old form (they fail on this node): `probe_runs.sh` l. 5, `arm_loop.sh` l. 6, `held_out_evaluate.py`
  l. 4-6, `background.sh` l. 5, `deployment/README.md` l. 177, `followup/step1/runs_{anchor,calibration,reasoning}.toml`,
  `followup/gate_evaluation.toml`, `followup/shared_sampling.toml`, `grpo/expert_iteration_1*.toml`,
  `grpo_expert_iteration.py` l. 5, `rl/README.md` l. 1017. `experiments/phase6_loop.py` l. 449 hard-codes it.
- **S6. Tests are not hermetic on the node.** Scripts under test source the real `/workspace/node_environment.sh`.
  `test_without_server_cpu_list_a_server_runs_on_every_cpu_the_cgroup_allows` removes `SERVER_CPU_LIST`, then the
  node file sets `0-47,96-143`, so the test fails on the node. Fix: an autouse fixture sets
  `LEAN_SEARCH_NODE_ENVIRONMENT` to a missing path.
- **S7. Measure the 60 s stop.** The tracker ignores SIGTERM. My scenario took the full 60 s, but its FIFO is held
  open read-write. A real tracker should see EOF once the EngineCore dies, so measure on the node. If stops do take
  60 s, `release` of 8 servers costs 8 min per phase (review AL F9). Fix: after TERM, once only verified trackers
  remain, SIGKILL those pids at once. The README's "ends in SIGKILL after 60 s" is unverified.

## Minor

- `serve_model.sh` l. 44: `taskset --cpu-list X true` rejects only malformed lists and an empty intersection. `0-500`
  and `0,9999` pass on 4 CPUs, and the server silently gets the intersection. `.cpus` records the truth, but nothing
  compares it with the list, and `stop_model.sh` deletes it, so no run keeps it. Compare in `record_server_cpus` and
  copy each server's `.cpus` into `pinning.jsonl`.
- Silent fallbacks remain: `environment.sh` l. 43 (`nproc`), `system_sampler.available_cores` (`os.cpu_count`),
  `cpu_snapshot` (/proc totals), and `pinning_refusals` skips the quota rule when it reads none (printed only as
  "none"). The helpers read the cgroup root, not `/proc/self/cgroup`: under `--cgroupns=host` or LXC they read the
  host's `-1`/`max` and fall back. Make node-check fail on "no quota" with `nproc --all` > the cpuset's size.
- `cgroup.py`: `exists()` where the shell uses `-r`. The v1 `cpu_counters` raises FileNotFoundError when
  `cpuacct.usage` exists without `cpu/cpu.stat`. A v1 limit set on a parent is not seen
  (`memory.stat`'s `hierarchical_memory_limit`). None of these matters on this node. The shell and Python helpers agree
  on every shared fake tree. Units are right (v1 `cpuacct.usage` in ns, v2 `usage_usec`; throttled time is not read).
- `node_checks.py pinning`: a malformed list (`48-95, 144-191`) raises a traceback from `parse_cpu_list`; catch it
  and refuse in one line. Parser edge cases (stride, duplicates, descending, whitespace) match taskset, except that
  taskset accepts CPUs beyond the host, which the allowed-CPU check then catches.
- The default of the last 32 CPUs when neither setting is given (`background.sh`, `background_set`) is harmless here
  (160-191, socket 1), and the study launchers refuse it. `background.sh` could also refuse it once a node file exists.
- `LEAN_SEARCH_VLLM_EXECUTABLE` is a test hook in a production script. It is acceptable because the trust check still
  needs a `vllm` command line.

## Re-review (bce49b0, 44e5bed, 175eca7)

Ran on the new head in WSL (non-root): the affected tests (monitoring, node_pinning, serve_model, server_starts,
lean process_handling and repl, loop_services, merge) **404 passed**. I reran the kill scenarios and the new
scenario scripts in `scratchpad\review_am\` (`rr_scenarios.sh`, `siblings.py`).
- **M1 resolved without privilege.** Path traced: probe run or loop -> `background.sh` (taskset only, nice 0) ->
  `start_server` -> `bash -c serve_model.sh`. That script now does taskset only, and a niced caller gets a warning,
  not a refusal. Observed: a server started under `BACKGROUND_CPU_LIST=0` runs on `SERVER_CPU_LIST=1-3` at nice 0;
  `.cpus` reads `1-3 0`; the pid file is trusted; the stop works. Nothing on this path lowers a niceness. REPLs:
  `repl_process_setup` runs in `preexec_fn` before exec, so the REPL never runs below 19 and there is no race. Every
  spawn (first start, crash restart, the pool's idle-stop and start) goes through `LeanRepl._start_process`, and every
  `LeanReplConfig()` in src keeps the default 19. Not niced: the one-shot `lake env env -0` and old
  `phase4_premise_names.py` (`lake env lean`).
- **S1 resolved.** `training_launcher` (subprocess and persistent trainer), the CPU merges and
  `expert_iteration/trainer.py` start on `TRAINING_CPU_LIST` at the caller's niceness of 0.
  **S2, S4, S5, S6 resolved.** S4: an absolute path is required, there is a `bash -n` check and a dry run, and a
  failure exits 1 with the file's name, with or without `set -e`, and applies nothing. **S3 partly:** the reserve is a
  warning, not a refusal. That is acceptable while 8 is a placeholder; make it a refusal once the throughput test
  measures it.
- **Kill safety unchanged.** I reran all 5 harmless-process cases; the results match the first review's table. The
  verified tracker group still takes 60 s (S7 stays open, measure it on the node).
- **Sibling check** on a fake node topology (n, n+96):
  - pass: `48-95,144-191` against `0-47,96-143`, and `144-191` against `0-47,96-143`;
  - refuse: `144-191` against `0-191` and against `0-95`; a server or training list with one extra hyperthread
    (48, or 95 sharing a core with 191).
  - On a single-socket fake (n, n+8) overlaps are refused, and `0-15` against `12-15` is refused once a node file
    exists (only a warning without one).
- **New, minor:**
  - The dry run executes the node file twice: an `echo` in it ran 2 times. That is harmless while the file "may only
    set variables". Enforcing that with a line pattern (`^export NAME=`) would make it true.
  - Without a `thread_siblings_list` (a container hiding the topology) every CPU counts as its own core and the
    sibling check passes silently. Warn when the topology is empty.
  - Other `background.sh` jobs (tracing, data building) now run at nice 0 on their pinned CPUs. That is harmless now
    that servers and training are elsewhere.
  - REPLs are at nice 19 in unpinned runs too.

  Nothing new is dangerous. **Verdict: merge.**
