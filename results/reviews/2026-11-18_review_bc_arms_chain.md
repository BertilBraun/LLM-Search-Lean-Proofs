# Review BC: the arms driver (A adopted, smoke test, C, D), node operations

Branch `worktree-agent-ab9fe6ed21f69d9fd`, head `b5199ee` (one commit on master `0e04599`). Focus as in reviews AU and
BA: will `deployment/arms_chain.sh` run unattended and correctly on the node.

**How it was checked.** I read the driver against the real tools: `arm_loop.sh`, `grpo_loop.sh`, `probe_runs.sh`,
`probe_compare.py`, `followup_arm.py`/`study_configs.py`, the loop's stages, files and log lines, the persistent
trainer, `probe_run_list.py` and `chain_helpers.sh`.

The node, read-only:
- The checkout is at `0e04599`, the branch's parent.
- Arm A runs: pid 788377, `python experiments/grpo_loop.py --config /workspace/runs/followup_configs/followup_A/loop.toml run`, phase 2, stage evaluating.
- `loop_state.json`'s first two fields, the "Loop followup_A: version" line and the "GPU memory before the wake" line are exactly what the driver's `sed` and regular expressions expect.
- `study_chain` and `offline_chain` both stand at HOLD.
- Arm A's phase 1: 392 trees, 257 solved, 12.19M tokens, publishing 135 s.

WSL: `test_arms_chain_script.py`, `test_arms_chain.py`, `test_study_chain_script.py`, `test_offline_chain_script.py`,
`test_followup_arms.py`: 323 passed.

**Verdict: merge after fixes.** B1 is a two-line lock that prevents two loops of one arm. S1-S3 decide whether the
chain stops for reasons that have nothing to do with the arms.

## Blocking

**B1. A driver restarted while its `arm_loop.sh` is still starting a loop can start that arm a second time.**
`deployment/arms_chain.sh:125-132, 175-189`; `deployment/arm_loop.sh` (no lock); `grpo_loop.py run` takes no per-run
lock (none in `loop.py`/`grpo_loop.py`).
- `start_loop` runs `setsid --wait deployment/arm_loop.sh …`. The point of `setsid` is that a `supervisorctl
  stop|restart arms_chain` does not stop it, and the ops note invites such restarts ("the next start adopts them").
- But `arm_loop.sh` spends minutes before it writes `loop.pid`: `followup_arm.py`, `grpo_loop.sh init` (v0's merges, a
  fresh run for C, D and both smoke runs) and `grpo_loop.sh servers` (8 servers, about 3-4 minutes).
- A driver started again in that window sees no live `loop.pid` and no `finished.json`. It counts an attempt and calls
  `start_loop` again: `stop_model.sh --all`, then a second `arm_loop.sh`.
- The outcome depends on where the first one was:
  - In `servers`: its server start fails and it exits. Harmless.
  - In `init`: both run `init` on the same run at once, then both start servers and both start `grpo_loop.py run` on the
    same run directory. Two loops of one arm, the later `loop.pid` overwriting the earlier: the arm's trees, phases and
    versions are corrupted.
- The adoption tests kill the driver only while the fake loop runs, never while `arm_loop.sh` is in flight.
- Fix (small): hold a per-run lock for the loop's whole life. In `arm_loop.sh`, before anything, `exec 9>
  "${run_directory}.lock"; flock -n 9 || { echo "another start of ${name} is in flight or its loop runs" >&2; exit 1;
  }`. The detached loop inherits fd 9 through `grpo_loop.sh loop`'s `nohup … &`, so the lock is held until the loop
  exits, and a second `arm_loop.sh` fails cleanly (an attempt; the next poll then adopts the loop).
- Alternatively the driver records the `setsid` child's pid with its start time and waits while it lives before
  calling `start_loop`.
- Add a test: kill the driver while a slow fake `arm_loop.sh` is in flight, then require exactly one loop start.

## Should fix

**S1. "STOPPED" no longer means idle for this driver, because its loops outlive it.**
`deployment/chain_helpers.sh:29-34`; `study_chain.sh:89`; `offline_chain.sh:94`.
- `other_chain_idle` treats a chain at STOPPED as idle. That was true for the step-2 and offline drivers, whose GPU
  jobs live in the driver's process group.
- The arms driver can be STOPPED while an arm's loop runs on, in its own session:
  - an adopted A when the driver stops on a missing mode file, a non-idle other chain or a bad CPU layout at start;
  - the smoke D loop when the kill's command-line check fails (`arms_chain.sh:116-117`);
  - any loop when `wait_loop_exit` uses up its attempts;
  - any later STOPPED cause during an arm's run.
- An operator who then starts O1 or another step-2 run passes the guard. That driver's `stop_model.sh --all` takes the
  servers from under a running arm, and its training meets an arm's GPUs.
- Fix: in `other_chain_idle`, or in a check the other two drivers call before their first server or GPU action, also
  require that no loop runs. `experiments/node_checks.py servers-free` (live `*/loop.pid` and `children/` jobs, the
  serving lock) does exactly that and exits 1. A refusal should STOP the calling driver with that text.

**S2. The documented way to stop an arm's loop makes the driver start it again.**
Ops doc line 599 ("To stop an arm's loop itself: … grpo_loop.sh stop"); `arms_chain.sh:186-188`.
- `grpo_loop.sh stop` sends SIGTERM. The loop ends "stopped", without `finished.json` or `health_stop.json`.
- Within 60 s the running driver counts an attempt and resumes it through `arm_loop.sh`, after `stop_model.sh --all`,
  up to three times, then writes STOPPED.
- Fix: the doc says to `supervisorctl stop arms_chain` first and to start the driver again only to resume the arm. Or
  better: the driver honours a pause file (`$state/pause_<arm>`: no restart, a plain "paused" STOPPED).

**S3. Two smoke gates may fail on a sound loop, and their failure STOPs the chain before arm C.**
`src/lean_search/rl/arms_chain.py:34, 45, 513-532`.
- **"round trained" at 2M tokens.**
  - Arm A's phase 1 solved 257 of 392 trees in 12.19M tokens. A 2M-token phase holds about 65 trees, about 43 solved,
    and those are the first to finish, the easiest ones, which the selector's easy-example dropping thins further.
  - DESIGN's own estimate is about 8 optimizer steps (roughly 700 examples) per 12M tokens. That is about 120 examples
    per 2M tokens, against `expert_iteration_min_examples = 100`.
  - A round skipped for too few examples is correct loop behaviour, yet it fails the gate.
  - Fix: raise the smoke budget to 4-6M (about 10-20 minutes more sampling per run). Or size it from arm A's phase-1
    solved count with a margin, and say in the report how many examples the round had against the minimum.
- **"GPU memory while training" ≤ 95% of nvidia-smi's total.**
  - No measurement backs the threshold. Arm A's `phase.json` records only post-stage memory (0.05 GiB reserved), and
    nothing records its training peak.
  - A 4B LoRA GRPO step with compiled layers and 16,384-token micro-batches can reserve close to 24 GiB through the
    caching allocator without ever failing. D's GRPO plus a round in one process reserves more.
  - Fix: either measure first (sample arm A's training stage now: the driver adopts A for about 15 more phases and could
    run the same sampler there) and set the gate from that, or make it a reading and keep "no out-of-memory" and "GPU
    memory before the wake" as the gates.

## Nits

**N1.** `arms_chain.sh:116`: the kill checks only that the pid's command line names `grpo_loop.py`. Also require
`followup_smoke_D/loop.toml` in it: only one loop should run at that moment, but an exact match costs nothing.

**N2.** `arms_chain.sh:69-73`: adoption trusts `loop.pid` with `kill -0` alone. A pid reused after a container restart
would be adopted and waited on forever. The risk is tiny here (A's pid is 788377, and pids restart near 1), but the
kill path's command-line check could be shared: `grpo_loop.py` and the run's `loop.toml`.

**N3.** `arms_chain.sh:128` (`gpus_free` in `start_loop`) writes STOPPED after 5 minutes. When a loop died during
`training`, the persistent trainer goes on until its current command ends, then exits by itself ("once the loop's
process is gone"). A crash mid-training then becomes a manual STOPPED instead of a resume about 15 minutes later.
Consider waiting longer on the restart path, or exiting 1 (counted) instead of STOPPED there.

**N4.** `arms_chain.sh:104-108`: `publishing_since` resets whenever one 5 s poll does not read "1 publishing". The
file is written atomically, so this only happens at a real stage change. Fine, but a missed kill fails the smoke test
outright ("no kill record"). The doc says how to repeat D's smoke run; a line in `smoke_report.md` with that recipe
would save looking it up.

**N5.** Ops doc install step 0: also name the risk that does remain while A runs. During the stash, fast-forward, pop
window, the loop's jobs started then (held-out evaluation, a trainer restart) read the checkout. The diff from
`0e04599` touches nothing they import (checked: no loop, trainer or evaluation module imports `study_configs` or
`arms_chain`), so it is safe; deploy between pauses if possible.

## Checked and fine

- **Command lines and file formats.** All checked against the real tools and found consistent:
  - `arm_loop.sh --kind smoke|arm --mode <mode> <overlay>`: parse order; `followup_arm.py` accepts `--kind smoke`, the
    `SMOKE_SETTINGS` budget refusals and the `sampling.json` binding.
  - `probe_runs.sh --foreground` with `PROBE_CONCURRENCY=112`, exits 3 and 4.
  - `probe_compare.py pair --x/--y` with bare run names (`run_directory` adds `probe_`); the ordered and file-order
    configs pair, only noted.
  - The run-list fields match `PlannedRun`.
  - `versions.jsonl` triggers ("phase N"), `phase_directory_name`, `phases.jsonl` and metric lines, the "Loop <run>:
    version" start line, the wake line.
- **Adoption touches nothing.** A live `loop.pid` means polling only: no `stop_model.sh`, no `arm_loop.sh`. The arms'
  loops run in their own session (`setsid`), so `stopasgroup` stops only a probe run or a comparison.
- **The kill.** By pid from the smoke D run's `loop.pid` after a command-line check, once, recorded. The restart is
  marked and not counted. The persistent trainer stops by itself once the loop is gone, and `gpus_free` plus
  `arm_loop.sh`'s servers-free check wait for that.
- **Health stop.**
  - The arm is never restarted (the poll condition and `health_stopped`).
  - The driver writes a report, stops the servers and writes STOPPED.
  - The `word_<arm>` handling is explicit: an unknown word stops the chain; `evaluate` on a version-0 stop STOPs at
    `probe-list`, which is documented.
- **Servers stopped where they must be.** Before every loop start (`arm_loop.sh` keeps answering servers) and at HOLD.
  Probe runs put their own checkpoint and value model on the servers.
- **Other drivers.** `declare -F` checks for the current helpers in all three drivers (BA S2). The guards are placed
  before the first server or GPU action, both ways. Both other chains are at HOLD on the node.
- **Deploying `0e04599..b5199ee` while A runs.** The change is additive for everything the loop's jobs import.
  `followup_arm.py --kind arm` writes A's configs unchanged, so a resume of A finds them identical. Reinstalling the
  study and offline copies at their HOLD is harmless, and `chain_helpers.sh` gained only comments.
- **Adapters.** Staged and renamed, manifest last. The PC script fetches each arm once, checks it with `sha256sum -c`
  against the manifest and renames it into place; LoRA adapters only.
- **Tests run the production driver.** The fake loop walks the real stages and writes `loop_state.json` as the real
  one. They cover adoption, death and restart, three failed starts, a health stop with both words, a smoke failure and
  a missed kill, probe exits 3 and 4, a kill at each later step, the other chains both ways, and GPUs held.
- **Untested:** B1's window, S1, and anything sized by real data (S3).

## Must be smoke-checked on the node at first run

1. The adoption line ("A: its loop runs (pid 788377): adopted") and no `loop_A_start` attempt while A runs.
2. At A's end: `adapters_A.log` naming four adapters (phases 8 and 16), `probe/runs_A.toml` with
   `value_version` = the version that first published phase 16's value adapter, the probe's start-order line, and the
   two comparison files plus `A_against_run7.txt`.
3. Smoke C: the "built in N s" line, the `expert_iteration` metric line not skipped (S3), `readings_C.tsv` rows in
   the training stage with the GPU peaks.
4. Smoke D: the kill line about 30 s into "1 publishing", a second "Loop followup_smoke_D: version" line, no second
   "trained", and `smoke_report.md`.
5. After the smoke, arm C's start: servers stopped first, then `arm_loop.sh --kind arm … arms/C.toml`.

## Re-review (2026-11-18)

Fixes `b5199ee..f61d1d3`. WSL: `test_arm_loop_lock.py`, `test_arms_chain_script.py`, `test_arms_chain.py`,
`test_study_chain_script.py`, `test_offline_chain_script.py`, `test_followup_arms.py`: 353 passed.

Node, read-only:
- Arm A is pid 788377 (phase 3, training).
- Two `loop.pid` files exist: `followup_A`'s, and a stale one in `followup_shared_sampling.failed_value_benchmark_20261118`
  (pid 617372, no such process).
- No `*.lock` files yet; `pid_max` is 4,194,304.

**Verdict: merge.** Every finding is fixed or reduced to a nit; the new mechanisms hold up. Three new nits and two
smoke points below.

| Finding | Status | Note |
|---|---|---|
| B1 two loops of one arm | Fixed | See "The lock" below. |
| S1 STOPPED arms chain with a live loop | Fixed | `no_other_loop` (`chain_helpers.sh:40-59`), called by all three drivers before their first server or GPU action. See below. |
| S2 a stopped arm restarted | Fixed | `pause_<key>`: a loop found neither alive nor in flight with the file present STOPs "paused" (`arms_chain.sh:236-237`); doc "Stopping an arm by hand". |
| S3 smoke gates that fail on a sound loop | Fixed | 6M tokens (the comment's own numbers: about 60 examples at 2M, so about 180 at 6M against the floor of 100). The GPU peak is now a reading. The round's skip reason is spelled out. |
| N1 kill command-line match | Fixed | `grep grpo_loop.py \| grep -q followup_configs/followup_smoke_D/loop.toml`. |
| N2 adoption trusts `kill -0` | Mostly fixed | `loop_process_alive` requires `grpo_loop.py` in the command line, though not the run's own config (only one loop runs at a time, so this is enough). `no_other_loop` still uses bare `kill -0`: see N8. |
| N3 5-minute GPU wait | Fixed | `wait_gpus`: up to 1 hour of polling, then `gpus_free`'s five checks. |
| N4 missed-kill recipe | Fixed | Written into `smoke_report.md` when the kill gate fails. |
| N5 deploy window | Fixed (doc) | Install step 0 names it and says to deploy in the sampling stage. |

**The lock.**
- **Placement.** `arm_loop.sh` opens `<run>.lock` on fd 9 and takes it with `flock -n` after its `finished.json` and
  pinning preconditions, before `servers-free`, `init`, `servers` and `loop`.
- **Who holds it.**
  - `init`, `servers` and the `node_checks` calls run with `9>&-`, so the servers it starts never hold the lock (tested
    with a detached stand-in server).
  - `grpo_loop.sh loop` passes fd 9 to the nohup'd loop through `background.sh`'s `exec taskset … python`, so the loop
    holds it for its life and releases it when it exits (tested).
  - Everything the loop starts later inherits nothing: the persistent trainer, the evaluation jobs, the vLLM servers
    (via `bash -c serve_model.sh`) and the Lean REPLs all go through asyncio/subprocess with the default
    `close_fds=True`.
- **A second start fails cleanly.** It exits 1 with a clear message while another start is in flight or the loop lives
  (tested). The driver counts that as an attempt and adopts on the next poll.
- **The driver.** `loop_alive` is a live `grpo_loop.py` process, or the lock held. A held lock without a process is "a
  start in flight", waited on for up to 30 minutes, then STOPPED with the `fuser -v` hint. Adoption of a restarted
  driver mid-start is therefore right.
- **Arm A's current loop holds no lock** (started before the lock existed). It is adopted by its process alone, and a
  restart of A after its death takes the lock as usual.

**`no_other_loop`, and whether it ever refuses a driver's own restart.**
- Arms chain: its own five runs are exempt (`followup_{A,C,D,smoke_C,smoke_D}`), so adopting its own arm or resuming
  its own smoke run is never refused.
- Step 2: its own shared run is exempt (`no_other_loop "${shared_run}"`), so resuming its own sampling is never refused.
- Offline chain: it runs no loop of its own and exempts none, which is correct.
- A loop of another run alive, or a start of one in flight, STOPs the calling driver, which is what S1 asked for.
- The stale `followup_shared_sampling.failed_value_benchmark_20261118/loop.pid` names a dead pid, so it refuses
  nothing today (see N8).

**The health-stop switch and the chain's end.**
- With `on_health_stop` absent or `wait`: report, servers stopped, STOPPED, as before.
- With `continue`: report once (`done_health_report_<arm>`), the loop marked done, `run_arm` skips the evaluation, and
  the next arm's `start_loop` stops the servers.
- At the end every health-stopped arm without a word STOPs with servers stopped. With a word,
  `evaluate_arm` runs; already-evaluated arms are no-ops through their markers.
- Comparisons now take every other arm with a probe run, so an arm evaluated at the end is compared with all of them.
- An unknown switch or word STOPs. `evaluate` on a version-0 stop STOPs at `probe-list`, as the health report now says.

**The smoke changes.** `value_every_phases = 1` is added to `SMOKE_SETTINGS`, so each smoke phase trains the value
model too: D's phase is GRPO, value and a round in one trainer process. The new gate "value model trained in the
phase" compares version 1's value adapter with version 0's. Both fine.

### New nits

**N6.** `chain_helpers.sh:38`: `run_lock_held` probes by taking the lock (`flock -n <lock> true`) for an instant. An
`arm_loop.sh` taking it in that same instant would fail "another start in flight". That costs one counted attempt and
a minute; it can only happen when another driver starts while an arm is being started, which the other guards already
refuse. Harmless; `flock -n -s`, or testing with `fuser`, would avoid even that.

**N7.** Any process that inherits fd 9 from the loop and outlives it keeps the run "in flight". After the smoke D kill
the driver would then wait 30 minutes and STOP. Nothing in the loop forks without `close_fds` today: the children
checked above all close it, and nothing in `loop.py` or `loop_services.py` imports multiprocessing or ProcessPool. A
future `fork`-started pool in the loop would change that. Worth one line in `arm_loop.sh`'s comment, and a smoke point
(below).

**N8.** `chain_helpers.sh:47-50`: `no_other_loop` judges a `loop.pid` by `kill -0` alone, while the arms driver now
uses `loop_process_alive` (command line names `grpo_loop.py`). A stale `loop.pid`, such as the
`followup_shared_sampling.failed_value_benchmark_20261118` one on the node, would STOP all three drivers if its pid
were ever reused. That is unlikely with `pid_max` 4.19M and pids near 0.8M, but sharing the command-line check (move
`loop_process_alive` into the helpers) makes the three drivers agree.

### Further smoke points for the first run

6. After the smoke D kill: `fuser -v /workspace/runs/followup_smoke_D.lock` shows nobody within a minute or two (the
   persistent trainer and the servers never held it), so the restart happens at once rather than after the 30-minute
   in-flight wait.
7. After arm C's first start by the driver: `fuser -v /workspace/runs/followup_C.lock` names only the loop's python.
