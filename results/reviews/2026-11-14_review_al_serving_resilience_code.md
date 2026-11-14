# Review AL: serving resilience (tolerated searches, rotation, restart swap), code by simulation

Branch `worktree-agent-ad4eaf34f0251a7ca` (0ff3a78, 719f539). WSL: the branch's touched `tests/rl` files 241 passed;
the trial merge with master `tests/rl` 1,431 passed. Scenarios drive the real `ToleratedSearches`, `ProbeServers`
and `ServerRotation` against an extended fake vLLM (4 policy + 4 value, timed 500s, slow completions and /health,
sleeping, revived with other weights; a restart closes and revives the fake), each under a timeout. Equivalence runs
master's and the branch's `search_problem_set` with fake models, pool and `search_problem` that send real requests.
Loop items use `loop_fakes` with a restart-semantics `FakeServers`. Not run: real vLLM, the shell scripts,
`verify_served`, the real `VllmServers`. Scripts: `C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_al\`.

## Scenarios (standalone evaluation; no scenario hung, none duplicated a result)

| Scenario | Expected | Observed |
|---|---|---|
| No failure, against master | identical files | `config.toml`, `progress.json`, sorted `results.jsonl` byte-identical; `stop_idle_processes` calls identical (5,4,3,2,1,0); line order jitters equally master vs master |
| One 500, against master | others identical | sorted results identical; one `retried` line in `failures.jsonl`; no restart |
| 500s for 6 s / 30 s, /health 200, recheck 1 s / 5 s | retries, no restart | 11 / 8 retried, max 1 per statement, 0 dropped, no restart |
| Dead until restarted | one restart, all results | 2 retried, restart session `policy-gpu1`, 40/40 |
| Dies again right after its restart | second restart | 2 sessions, 40/40 |
| Keeps dying (value-gpu0) | stop at the 4th death | `ServerRecoveryError` after 3 restart sessions; 60/300 results kept; no run.json |
| Two die at once; all 4 policy; all 8 | one restart of all dead | one restart of exactly the dead set; 40/40 or 200/200 |
| Dies while another restarts (restart takes 2 s) | both restarted | **policy-gpu2 never restarted**: run ends 200/200, accepted, gpu2 dead to the end, nothing records it (F1) |
| /health 200, completions 500 forever | restart, or the run rejected | never restarted; 61-62 retries, 1 statement dropped at 200 (F6) |
| Slow server (client timeout 1 s) | server failure | `ReadTimeout` retried 37×, 1 dropped, never restarted (F6; real timeout 900 s) |
| /health 11 s once, completions fine | no restart | **live server restarted** after one 500 (single 10-s probe, F5) |
| Sleeping server (health 200) | restart or skip-proof | 63 failures, 1 dropped, never restarted |
| `ValueError`, Lean crash (`RuntimeError`) in a search | surface | surface, run ends, as on master |
| HTTP 400 in a search | surface (non-server) | **retried 3×, dropped**, run rejected (F7) |
| One statement fails 4 times | dropped | `retried`×3 + `dropped`; 39/40; not in results |
| Cancel (Ctrl-C) inside a restart | clean stop | `CancelledError`; 16 results, 2 `retried` lines; server left dead; no session |
| Supervisor: process 1 cancelled mid-restart, process 2 resumes | each statement once | 40/40, no duplicate; counters reset (F2) |
| Restart comes up with other weights, the shipped kind of check | caught | **not caught**: run completes, 4 results from the other weights (F8); a root/answer check catches it |

Loop harness: a burst of transient `ConnectError`s with healthy servers pauses 3 times ("Every server answers") and
restarts nothing; two phases under restart semantics (released servers unhealthy while stopped) need no recovery; a
start failing at the publish stops the loop with all servers down (F3, F4). `recover_servers` cannot run while a new
version is unrecorded: `run_phase` holds `pause_lock` through publish, `await durable` and the evaluations, so a restart
reads the recorded version. The loop never served or believed it served a wrong version in these runs.

## Must fix before merge

- **F1. A server that dies during a check is never restarted.** `evaluation.py` `ToleratedSearches.check_servers`
  l. 623/642: failures with `failed_at <= checked_at` are skipped, and `checked_at` is set when the check *ends*. A
  server that dies after `dead_servers()` returned (here: during another's restart) fails its searches inside the
  window; the rotation then leaves it out, so no later failure comes. Throughput drops by a server for the rest of the
  run, silently, and the run is accepted. Fix: set `checked_at` to the time `dead_servers()` was *called*, and before
  `feeding.set()` call `dead_servers()` again and loop while it names servers (inside the restart cap).
- **F2. The caps are per process, not per run.** `ToleratedSearches.__init__` l. 556/558: `restarts` and `failures`
  start at 0 in each process. Under the on-node supervisor (in use for the anchors) a GPU that kills its server gets 3
  restarts per resume, forever; a statement that kills its server is searched 4 times per resume. Fix: seed
  `restarts` from sessions with `serving.restarted` and `failures` from `failures.jsonl` (an explicit
  `--retry-dropped` to reset), and exit with a distinct status the supervisor does not resume.

## Must fix before an arm runs on the restart path

- **F3. The loop cannot resume by itself after a crash in training or publishing.** `loop.py` l. 875 calls
  `VllmServers.check()` (`loop_services.py` l. 702), which raises when a server is down. Under `restart` the training
  GPUs' servers are *stopped* during training, so any crash there (trainer OOM, SIGTERM, a failed start) leaves every
  server down and the rerun refuses ("start them"). `serve(current)` on the next line starts them anyway: skip `check()`
  under `restart`.
- **F4. One failed start ends the loop.** `put_weights` l. 645-665 → `start_servers` raises on the first server that
  does not come up. The node logged a value server segfaulting at a fresh start (13:07); 8 starts per phase turn a
  per-start rate p into ~8p per phase. Retry each failed start once or twice (as `recover_servers` restarts), then stop.
- **F9. Measure `stop_model.sh` on the node before the first arm.** `release` stops the 8 servers in one call, one
  after another (`stop_model.sh` l. 33-37, up to 60 s each). If the container's PID 1 does not reap, the exited API
  server stays a zombie, `kill -0 -- -pgid` keeps succeeding and every stop takes the full 60 s: 8 min per phase. Stop
  per GPU in parallel and treat a group of zombies only as gone.
- **Pid files after a reboot.** `stop_model.sh` kills `-$(cat pid)`; after a reboot the pid file names a dead process
  whose number may now be a live group leader (the supervisor, a setsid'd job): the first restart kills it. Record
  `/proc/sys/kernel/random/boot_id` and the start time in the pid file and refuse a mismatch (or keep pid files in
  `/dev/shm`, emptied by a reboot). The restart path calls `stop_model.sh` 8× per phase, so it is the first to hit this.

## Should

- **F5. One slow /health is a death.** `ProbeServers.dead_servers` l. 552 uses `is_healthy` once with a 10-s timeout
  (the loop, `loop.py` l. 930, re-checks after draining, so it only pauses). The old run saw 32 ConnectTimeouts (30 s
  connect) in 10 bursts without a death: if /health stalls with them, each burst in a standalone run kills a live
  server (~20 searches lost, shown with an 11-s /health) and spends a restart; four bursts stop the run. Probe 3× over ~30 s and check the pid file's process before calling a server dead.
- **F6. Healthy but broken servers are never restarted.** A server whose completions 500 or hang while /health is 200
  (stuck engine, sleeping server) is taken back every 5 s (`rotation.take_back` l. 66) and fails statements until they
  are dropped; at the real 900-s timeout the run crawls for hours, then is rejected. The loop has the same gap. Count
  consecutive server errors per server in `ServerRotation`; after N (say 5) with no success, report it to the recovery
  as dead; or make `dead_servers` send one short completion with a 30-s timeout.
- **F7. 4xx errors are retried as server failures.** `ToleratedSearches.work` l. 593 catches every `httpx.HTTPError`.
  A deterministic 400 is retried 3×, dropped, and the run can never be accepted. Use `is_server_error(error)`
  (`rotation.py` l. 17) and re-raise otherwise, as on master.
- **F8. The verification does not check which weights a server holds.** `verify_served` l. 505 checks shape, not
  identity. A process answering on the port that `serve_model.sh` did not start (its health loop l. 91 accepts any
  answer) passes. `served_model_root` already exists: require `root == assigned weights` in `ProbeServers.restart` and
  after `put_weights` in `serve_checkpoint`; `serve_model.sh` should refuse to start when the port already answers.
- **The skip trusts a sleeping server.** `already_serves` l. 416 / `holds_start_weights` l. 378: a server a dead
  in-place loop left paused and asleep (level 2, weights discarded; log without a wake line) is skipped (shown: fresh
  log + sleep line + `is_sleeping` true → `skipped ('policy-gpu0',)`); the verify request then waits on the paused
  server up to the request timeout and exits with a traceback (`probe_evaluate.py` l. 273 does not catch httpx errors).
  Add `not await is_sleeping(url)` and treat any sleep/pause line as a swap marker.
- **Interrupts mid-restart leave orphans.** On cancel, `start_server`'s `process.wait()` is abandoned; at most the bash
  child is killed at loop shutdown, never the setsid'd vLLM, and `finally: remove_merges` deletes the merges it is loading.
  SIGTERM (no handler in `probe_evaluate.py`) skips every `finally`. Terminate and wait the child in a `finally`, and
  install a SIGTERM handler that cancels the main task.
- **`summary.json` counts dropped statements as unsolved** (`search_summary` l. 209: `problems=len(problems)`, solved
  from results). Rejected runs are not rated, but the summary and the log line read as a solve rate. Add `dropped`.

## Minor

- Under `restart` each loop start restarts all 8 servers (~200 s) even when they hold the current version (twice on a
  resume in `PUBLISHING`); log names to the second collide (`serve_model.sh` l. 44) and old logs are never pruned;
  `swap_skipped` (l. 740) is true for a run whose only weights came from restarts; standalone failed searches' tokens
  are recorded nowhere.

## Restart path cost and safety (on paper)

Per pause: 8 sequential stops (~5-10 s each; 60 s each if PID 1 does not reap) plus the measured ~200 s start, against
~10-30 s for sleep and wake: about +4-5 min. A phase samples ~1 h at B = 12M and 3.4k tokens/s (review AH), so ~7%,
~1.2 h per 16-phase arm, plus ~200 s per probe run (unless skipped) and per loop start. Memory: the start needs free
≥ 0.62 × 23.6 = 14.6 GiB, then 6.6 GiB, leaving ~2.4 GiB for the ~1 GiB parked rank: the wake's margin, but checked
strictly, so an unemptied allocator cache fails the start (and with F4 the loop); training gains the ~1.6 GiB the
sleeping servers held. `/dev/shm`: ~12 GiB of handed-off merges read once, as the reload did. Ports: address reuse is
fine; a D-state survivor keeps the port and the start fails fast. CPU: four parallel starts while Lean is paused fit
61 cores; the early resume begins after `serve` returns.

## Untested risky paths (in the order I would add tests)

1. F1's window: kill a second fake inside `ProbeServers.start`, assert it is restarted (20 lines on `run_scenario`).
2. `VllmServers` under `restart`: stopped servers unhealthy, a crash during training, a resume that must start them
   (F3); a start failing once at the publish (F4).
3. A tolerance through `run_problem_set_evaluation` and `probe_evaluate`'s run.json (only a stub search is tested);
   `serve_model.sh`/`stop_model.sh` against a stale pid file and a taken port.

## Expected merge conflicts with master

`git merge-tree`: one textual conflict, `tests/rl/test_shipped_grpo_configs.py` (master: concurrency 84,
`phase_generated_tokens = 12_000_000`, `max_phases = 16`; branch: `serving.swap = RESTART`): keep master's lines and add
the branch's `serving=` line. `rl/loop.py`, `rl/loop_services.py` and `followup/base.toml` merge cleanly; `rl/loop_config.py`
is untouched by the branch (it changes `expert_iteration/loop_config.py`). Logically compatible: in the failure handler
master books the lost tokens (`self.lose_search(fed.name, SearchEnd.SERVER_FAILURE)`) before the branch's new
`or await self.servers.unhealthy()` runs, so `TreeStore.generated_tokens` and `lost_tokens` are as master expects; an
earlier recovery only means fewer lost searches. `put_weights` replaces `serve_weights` without touching master's
`loop_services` changes. After the resolution `tests/rl` passes in full (1,431).

## Re-review (a285a03..302372b)

Head 302372b: `tests/rl` 1,665 passed, 1 failed once (`test_on_the_restart_path_a_crash_in_training_leaves_the_released_servers_down`;
5/5 passes alone and with `-k`, so a flake to watch). Same harness on the new API, with fingerprints from the fakes'
top log-probabilities, `DeathRule(5, 3, 0.3 s)`. Equivalence against master 0d32f13: config, progress, sorted results
and idle-REPL stops identical, with and without a tolerance; with one 500 only the retried statement differs.

Fixed as claimed: F1 (a server dying during another's restart is restarted); F2 (caps seeded across processes; after
exit 4 a rerun stops at the first death); F3/F4 (crashes in training and publishing resume by themselves); F5 (one
11-s /health or 4 quick 500s: no restart); F6 (500s or hangs behind a healthy /health: restarted; still failing:
exit 4, no crawl); F7 (400 and `ValueError` surface); F8 (another root, shifts 0.5 and 0.06 refused); sleeping servers
are not skipped; SIGTERM exits 143 after `finally`, the start's bash terminated, the server left to its pid file;
`summary.json` excludes dropped statements; a `sleep` in a pid file, a pid file 10 min older than its vLLM and a vLLM
of another name are never signalled, a fresh vLLM is.

Still diverging:
- **Must fix before an arm runs on the restart path: the orphan rule kills unrelated jobs after a reboot.**
  `server_pid.sh` `orphaned_server_group`: a pid file from a day ago naming a process group whose leader exited
  (here a setsid'd shell that left a `sleep`) is trusted because every live member started after the file was
  written, which is true of every process after a reboot; `stop_model.sh` killed the `sleep`. Refuse a pid file whose
  mtime is before `btime`, and require a member's command line to be vLLM's (the engine core's).
- **Should: a streak alone condemns a server.** 8 quick 500s, or a 2-s stall under 1-s timeouts (16 `ReadTimeout`s),
  restarted a live server with /health fine. With the real timeouts only connect bursts produce such streaks (the old
  run: ~3 per burst), so it is rare but spends a restart each time. Confirm a streak with one short completion first.
- **Measure before relying on F8: `FINGERPRINT_TOLERANCE = 0.05` is unmeasured.** A shift of 0.04 passed, and 5
  results from the other weights were kept. On the node: two cold starts of one merge must agree within it, and
  v_k against v_k+1 must differ beyond it on the three prompts, or adjacent versions are not told apart.
- Minor: a restart cancelled mid-way writes no session, so four kills inside restarts left the count at 0; a rerun
  after exit 4 has no restarts left and no reset flag; a resume in publishing starts every server twice (~400 s).

Verdict: merge after the orphan-rule fix (a few lines). An arm may run on the restart path once that fix is in and
the node measurements are done: `stop_model.sh` per server (zombies), two cold starts per merge for the fingerprint
tolerance, and v_k against v_k+1.
