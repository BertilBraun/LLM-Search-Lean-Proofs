# Review AK: serving resilience (tolerated searches, rotation, restart swap, swap skip), code

Branch `worktree-agent-ad4eaf34f0251a7ca` (0ff3a78, 719f539) against master. In WSL the branch's
`test_tolerated_searches`, `test_probe_serving`, `test_probe_evaluation` and `test_shipped_grpo_configs` pass (205). A scratch
script (`...\scratchpad\review_ak\probe_tolerance.py`) drove `ToleratedSearches` directly: a search that raises a 400 was
searched 4 times, then dropped (the run is rejected); a `ValueError` surfaced at once. `git merge-tree` against master shows
one conflict only, in `tests/rl/test_shipped_grpo_configs.py`; `loop.py` and `loop_config.py` merge cleanly.
Not run: anything on a GPU, vLLM, the resident trainer, `VllmServers`, `serve_model.sh`.

## Checked and sound

- `ToleratedSearches` (evaluation.py l. 560-645): one check per failure burst. The lock serialises checks; `checked_at`
  lets failures from before a check ended skip it; restarts cannot race; `appendleft` happens before the lock is taken
  and `feeding.clear()` runs on the lock's fast path, so no worker takes a statement back before the check. A statement
  sits in the queue or one search at a time and is written once. TaskGroup cancellation is clean. Non-httpx errors
  (Lean, `ValueError`) surface. Retries are counted per statement and restarts per run.
- Integrity of a retry: trees and accounting come only from the completed attempt (`on_completed`), and the wall clock
  of a search starts again. Restarts use the run's merges (digest-addressed, written atomically), never the loop's version.
- The hand-off window in the brief does not occur now: `recover_servers` waits on `pause_lock`, which `run_phase` holds
  through `await durable`, so `read_current` is already the new version when a restart can run. Finding 9 hardens this.

## Findings

### Must fix before merge

1. **The skip treats a sleeping server as one that holds its start weights** (`probe_evaluation.holds_start_weights`
   l. 378, `already_serves` l. 416). Sleep level 2 drops the weights and logs neither marker. A server put to sleep and
   never woken (an in-place loop stopped during training, the default path) passes the skip. `verify_served` then
   requests from a sleeping engine: the request fails or hangs until the 1,800 s timeout, outside the handled errors.
   Master's `swap_weights` handled this case. Fix: `if await is_sleeping(server.url): return False` first, plus a test
   on `FakeVllmServer` with `sleeping = True`.
2. **Every `httpx.HTTPError` is retried as a server failure** (`ToleratedSearches.work` l. 593). A 4xx (context length,
   a wrong model name, a malformed request from a bug) costs 4 full searches, then the statement is dropped. The run is
   rejected, and every rerun "under the same name" repeats it, so the run can never be accepted, and no traceback says
   why (the scratch run above). Fix: `if self.tolerance is None or not is_server_error(error): raise`, using the
   rotation's `is_server_error`, plus a test that a 400 raises.
3. **The skip's "never swapped" comes from vLLM log text, so unknown means "no swap"** (`SWAP_MARKERS` l. 372). If a
   vLLM upgrade, a different reload route (`publish_weights.py`, a future `/update_weights`) or a changed log level
   drops those lines, a server that started from v0's merges and was swapped to vk passes as v0. That is the anchor
   case, the one the skip exists for: the anchor would be rated with vk's weights and nothing would say so. Fix: make
   the evidence ours. `server_control.release_gpu`/`restore_gpu` write `<name>.swapped` before acting, and
   `serve_model.sh` deletes it at start. Skip only with no such file, matching pid and log, and the vLLM version the
   markers were checked on (`run_environment` already reads it). Otherwise ship the skip off until finding 7's
   fingerprint exists.

### Must fix before an arm runs on the restart path

4. **A loop that crashed during training cannot resume on its own** (`VllmServers.check` l. 702, called by
   `GrpoLoop.session`). In restart mode `release` stops the training GPUs' servers by design, so after any crash in
   TRAINING or PUBLISHING, `check()` raises "Servers not answering". The operator (or the supervisor) must run
   `grpo_loop.sh servers`, then `serve(current)` cold-starts all 8 a second time (~400 s). Training is the longest
   stage, and the node rebooted twice. Fix: under `SwapMethod.RESTART`, skip `check()`; `serve()` stops and starts
   every server anyway (`start_server` runs `stop_model.sh` first).
5. **One failed cold start ends the loop** (`start_servers` l. 675 via `put_weights` l. 645). The restart path turns
   ~0 starts a phase into 8, or 12 with the value swaps around a value arm. One of today's three segfaults was at a
   fresh start. Fix: retry a failed start once (stop and start, the old log kept) before raising, and log the retry.
6. **The restart path has no test and no node measurement.** `test_loop` uses fake servers. Nothing exercises
   `VllmServers.release` stopping the released servers, `serve` starting all of them per GPU in policy-then-value
   order, `serve_value` restarting value servers only, or a failed start. On the node, vLLM's startup check asks for
   `utilization × total` free. With the trainer's ~1 GiB context, the second server's 0.28 share leaves roughly 1 GiB
   of margin, and the trainer's caching allocator after a phase may hold more. Fix: a `VllmServers` test with
   recording start and stop commands (and a resume from TRAINING, finding 4). Then one full phase on the node with
   `nvidia-smi` logged before each start and the pause segments recorded: stopping is serial (up to 60 s a server),
   about 200 s for 8 starts, plus value restarts.

### Should

7. **`verify_served` proves the server answers, not which weights it holds** (l. 505). The previous checkpoint's
   merges, or the base without its adapter for the policy, give usable blocks. Any trained value model puts over 0.5 of
   its mass on the bins. Cheap and strong: at merge time (already on the CPU, in the merging process), compute the
   top-k next-token log-probabilities of two fixed prompts per merged model and store them beside `MERGED_MARKER`.
   `verify_served` compares each server with them (bf16 against fp32: about 0.05 nats max). That also checks the skip
   and every restart against ground truth. Also assert `/v1/models` `root == assigned.weights` after a restart.
8. **The probe restarts on a single missed `/health`** (`ProbeServers.dead_servers` l. 552). The check has a 10 s
   timeout and runs while the GPUs are loaded. `start_server` then kills a live server (`stop_model.sh`), fails its
   in-flight requests (more retries) and spends one of the 3 restarts. The loop drains and checks again before it
   restarts; the probe does not. Fix: re-check after ~15 s and restart only on two consecutive misses.
9. **Restart the loop's servers from what is served, not from `read_current`** (`recover_servers`, loop.py l. 1021).
   It is correct today only because of where `pause_lock` happens to be held (see above). Keep a
   `served_model: ModelVersion`: set it in `publish` to the version served (the hand-off paths included), update it
   in `record_durably` and `roll_back`, and use it in `recover_servers`.
10. **In-flight searches through an outage are biased** (probe). While a server restarts, the searches in flight run
    on one server fewer, and their wall clock includes the outage. A `WALL_CLOCK_BUDGET` stop then is recorded as
    unsolved and counts toward the 1% rejection. Fix: record each outage window in `failures.jsonl`. Then either search
    again a wall-clock stop whose search overlapped one, or exclude the paused time from the search clock, as the
    loop's `PauseGate` does.
11. **The loop's new trigger** (loop.py l. 930) fixes the real gap: with the rotation hiding a dead server, the old
    10-of-20 rule would rarely fill, and the server would stay dead. The cost: every failing worker runs its own
    8-request health sweep. Under throttling, a `/health` slower than 10 s (the client's connect timeout is 30 s) makes
    each transient error a full drain pause. A hung server holds that drain until the 1,800 s request timeout. A
    server that keeps dying is restarted without a limit. Fix: one health sweep per burst (a timestamp as in
    `ToleratedSearches`), a cap on restarts per hour (then stop with an alert), and a check of health before the drain.
12. **The skip ignores launch arguments** (`already_serves`). A server started by hand or by `grpo_loop.sh servers`
    with another `MAX_MODEL_LEN`, `MAX_NUM_SEQS` or a missing `--logprobs-mode` is kept. A different maximum length
    changes the search results. Fix: compare `/proc/<pid>/cmdline` with the arguments `weights_start_command` would use.
13. **`CORE_DUMPS=1` can stop the server from starting or fill the volume** (serve_model.sh l. 47). Under `set -e`,
    `ulimit -c unlimited` fails when the container's hard limit is lower, and the server never starts. A relative
    `core_pattern` writes into vLLM's working directory, the repository (`start_server`'s cwd). A core holds the API
    and engine processes' anonymous memory (pinned buffers included), tens of GB each, on the volume that holds the
    checkpoints. Fix: `ulimit -S -c "$(ulimit -H -c)" || true`, launch from `${server_directory}/cores`, and log `df`
    there. The rotated logs are never pruned (8 a publish on the restart path), and two starts in the same second
    overwrite one. Quoting is fine; nothing kills by name.

### Minor

14. Rotation (`take_back` l. 66): if `healthy` raises anything but a transport error, the task dies unobserved and the
    server stays out for the rest of the run. A `PoolTimeout` (on the client side) leaves a healthy server out. A
    `leave_out` after `close` leaves an orphan task. All servers out falls back to the turn order, which is correct.
    Uneven load changes only speed, since all servers of a kind serve the same weights.
15. Evaluating `held` with an `await` per server runs the checks one after another, which is fine. With an empty
    `root` (the hand-off removed), `names()` is empty and the server is swapped, which is safe.
16. The failure counts and the restart budget are kept in memory for each session. `retried_statements` takes the
    maximum per name, so 2 + 2 failures across sessions read as 2. `swap_skipped` ignores restart sessions.
17. Every failed search restarts its REPL (`pool.acquire` on an exception). One server death fails up to all searches
    in flight at once: that many Lean restarts with their header loads, during a vLLM cold start, on a host that ran
    out of headroom twice. Measure it on the node once.

## Tests

The new tests check behaviour (fake vLLM servers through the real rotation and `ProbeServers`), not the implementation.
Missing, in priority order: the restart path of `VllmServers` through a full phase pause and a resume from TRAINING
(findings 4-6); a 4xx raises (2); a sleeping server is not skipped (1); a second server dies during a restart (its
failures skip the check, so the next failure must trigger one).

## Verdict

Merge after fixes 1-3. Run no arm with `swap = "restart"` (719f539 makes it the study's default) before 4-6, and run
none on the skip before finding 7's fingerprint, or turn the skip off.

## Re-review (a285a03..302372b)
The suites touched (394 tests) pass in WSL. Scratch: `...\scratchpad\review_ak\orphan_probe.sh`.
- **1, 2, 4, 5 resolved.** A sleeping server is never skipped. Only `is_server_error` is retried; a 4xx raises with
  its traceback. Skipping `check()` on the restart path hides nothing: `serve()` starts every server and
  `put_weights` raises on one that stays down, and in place the check is unchanged. A start is retried twice, its
  logs kept. Minor: `arm_loop.sh`'s `grpo_loop.sh servers` is a second cold start (~200 s) on the restart path.
- **3 resolved for the loop's paths.** `mark_swapped` lives in `loop_services` only. `expert_iteration/serving.py`
  l. 302, `publish_weights.py` and `grpo_single_step.py` swap without it, which leaves the four 0.31.0 log strings,
  tested only on synthetic logs. I found no pass if the strings are right. Should: write the marker inside
  `server_control`, and grep one real swapped log on the node for each string.
- **6 holds servers to each other, not to the merge.** A skipped server counts as fresh, so a wrong skip writes a
  wrong reference. Fully in place, no reference is ever written. Top-5 of 3 generic prompts within 0.05 nats does not
  separate adjacent GRPO versions (~1e-3 to 1e-2 nats a token per phase). A near-tie top-1 can flip under bf16. The
  stored vLLM version is never compared. On the restart path, `check_started_from` (a digest-addressed merge as the
  root) already guarantees the weights. Sound would be: a CPU reference at merge time, `prompt_logprobs` over ~256
  tokens of a real proof, and a node-measured noise floor at least 5x below the adjacent-version distance. Until
  then the docs should not claim it detects wrong weights.
- **7: new must-fix.** `orphaned_server_group` (server_pid.sh l. 262) signals an unrelated group after a reboot.
  Its only guard, `started >= written - 60`, has no upper bound, and after a reboot every process is newer than the
  stale pid file. Reproduced: a live child of an exited leader, against a 3-hour-old pid file, returns that group,
  so `stop_model.sh` (run at every start) would TERM and then KILL it. Fix: a pid file older than `/proc/stat` btime
  is stale and never signalled (also in `server_processes.py`), each member's command line must be vLLM's, and its
  start must fall before `written + SERVER_START_TIMEOUT`. `trusted_server_pid` is sound. Minor: it greps the name
  as a regex, and the final `KILL` goes out even to an empty group. Nothing kills by name.
- **8: none needed before an arm.** `recover_servers` reading the current version is correct under `pause_lock`.
  The outage bias affects probe ratings only (should). The loop's restart cap per hour and the launch arguments in
  the skip are shoulds.

**Verdict**: merge after fix 7. Arms may run on the restart path after the node measurements (GPU memory per start,
pause segments), with the fingerprint tolerance measured there first: a false mismatch stops a probe run.

## Final check (21fe885)
- **1 Kill safety: no wrong signal found.** `orphan_probe2.sh` (scratchpad) runs on harmless sleeps of its own:
  - Refused: a pid file 10 s older than boot (stale, status 1); a foreign leaderless group with no record, or forged into `.members` (status 2, nothing signalled, pid file kept); a `VLLM::EngineCore`-titled child unrecorded, recorded with another start, or older than `written + 900` s.
  - Accepted only: the titled child recorded exactly as `serve_model.sh` would record it.
  - A reused pid needs the same start second and membership of the dead server's group, so only the server's own descendants qualify. A `.members` file from before a reboot cannot match a start time after boot, and a by-hand restart leaves an empty old group (stale, nothing signalled). No KILL goes to an empty group; nothing matches by name.
- **The opposite failure is real.** `trusted_server_pid` needs, for the live leader: argv[0] or argv[1] equal to `vllm` or ending `/vllm`; an argv element exactly `serve`; `--served-model-name` immediately followed by exactly `<name>`; the pid file written since boot; and the process start within 60 s of the pid file's mtime. If vLLM 0.31 retitles its API process (setproctitle), or `setsid` forks, a live server is reported stale: its pid file is removed, nothing is stopped, and the next start refuses the port. That fails safe but strands GPU memory. Verify once on the node with:
  `source deployment/environment.sh; source deployment/server_pid.sh; for f in "$LEAN_SEARCH_RUNS"/servers/*.pid; do n=$(basename "$f" .pid); p=$(cat "$f"); echo "$n pid=$p pgid=$(ps -o pgid= -p "$p" | tr -d ' ') trusted=$(trusted_server_pid "$f" "$n" || echo NO)"; for m in $(live_group_members "$p"); do echo "  $m $(tr '\0' ' ' < /proc/$m/cmdline | cut -c1-80) member=$(server_member "$m" "${f%.pid}.members" "$(stat -c %Y "$f")" && echo yes || echo NO)"; done; done`
  Pass: `trusted` equals `pid` equals `pgid` for every server, and every member reads `member=yes`.
- **2 Fingerprint: no silent wrong weights on the restart path.** The guarantee there is the content-addressed merge plus `check_started_from` (realpath root equals the merge). A reference is written only from such a start. The 20 listed tokens make a missing reference token unlikely. What remains uncaught is a merge that is wrong for its own digest (a merge bug, disk corruption): every reference comes from those same files. That needs the CPU reference and is not a blocker.
- **3 Loop: no gap.** `stop` is set only by a terminal stop (a failure, a signal, a hard stop, the end). A loop that is not stopping takes the unchanged path, and an early return under `stop` ends the worker (`while not stop.is_set()`).

**Verdict: safe to merge.** Run the command above on the node before the first arm on the restart path.
