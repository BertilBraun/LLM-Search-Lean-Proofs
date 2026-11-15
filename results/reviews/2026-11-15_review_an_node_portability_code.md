# Review AN: node portability (cgroup v1, explicit CPU layout), code from the operator's side

Branch `cgroup-v1-quota` (6 commits on master). WSL: the branch's pinning, serve, server-start and monitoring tests
231 passed, 1 skipped. Own runs (`C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_an\`):
a real Python 3.12 `multiprocessing` spawn group (leader, resource tracker, engine stand-in) stopped by group SIGTERM,
leader alive and dead; `environment.sh` sourced before a node file appears, then `node_checks.py pinning` in a child.
Not run: the node, vLLM, torchrun. Layout = intended node file, loop started by `arm_loop.sh`.

## One arm phase: who runs where

| Process | Started by | CPUs | Nice | Problem |
|---|---|---|---|---|
| Loop (`grpo_loop.py run`, the search orchestrator) | `grpo_loop.sh loop` via `background.sh` | Lean set | 19 | GPU feeder on Lean's CPUs, equal priority with 84 REPLs (pre-existing, consistent) |
| Lean REPLs (sampling, 84) | loop | Lean set | 19 | none |
| 8 servers, first start | `arm_loop.sh` -> `grpo_loop.sh servers` (operator shell) | `SERVER_CPU_LIST` | 0 | none, if the shell's `SERVER_CPU_LIST` is not a stale default (F1) |
| 8 servers, restart after each publish | loop -> `bash -c serve_model.sh` | `SERVER_CPU_LIST` | 0 **only with CAP_SYS_NICE**, else refused | F2: without the capability every restart fails, the loop dies at its first pause with all servers stopped |
| Server restarted mid-sampling (failure tolerance) | loop, same path | as above | as above | F2; its warmup/compile threads add quota demand while Lean runs (S4) |
| Trainer: torchrun, 4 DDP ranks, their threads | loop (`run_logged`, inherits) | Lean set | 19 | ranks of GPUs 0-2 on the remote socket; model building at the first `prepare` loads Lean's CPUs during phase-1 sampling (S1) |
| Trainer's tree preparation / value labelling thread | trainer, re-pinned by `run_in_background` | Lean set | 19 | by design; consistent while value schedules are equal |
| Merges: GPU merge + handoff write to `/dev/shm` | trainer rank 0 | Lean set | 19 | during the pause, Lean stopped: performance only |
| Merges: durable copy of the 13 GB handoff (`record_durably`, loop.py:1811) | loop thread, after the wake | Lean set | 19 | runs beside the held-out states and the next sampling (S2) |
| Merges: CPU fallback (`publish_phase` without handoff), version 0 `init` | loop thread / `arm_loop.sh` shell | Lean set, nice 19 / all CPUs, nice 0 | | torch intra-op up to 96 threads; in the pause / before anything runs: harmless |
| Value-model training | trainer | Lean set | 19 | as trainer |
| Held-out states at each pause (`grpo_evaluate.py`, 56 REPLs) | loop (`run_logged`, `command_prefix` "") | Lean set | 19 | none |
| Health checks, habit and tokenizer measurements | loop threads (`asyncio.to_thread`) | Lean set | 19 | HF tokenizers' Rayon pool can fan out to 96 threads beside Lean, load depends on the arm's trees (S2) |
| System sampler (`grpo_loop.sh dashboard`) | operator, by hand | caller's (normally all) | caller's | not started by `arm_loop.sh`: per-run throttling exists only if someone started it (M3) |
| Probe runs: `probe_evaluate.py`, its REPLs; its server restarts | `probe_runs.sh` via `background.sh` | Lean set / `SERVER_CPU_LIST` | 19 / 0 (F2) | same layout as an arm |

Physical cores: with the intended file no core is shared between our servers and our Lean (n and n+96 are siblings;
verify on the node, checklist 2). They are shared with other tenants: the cpuset is the whole host, so tenants' load
(10-19) lands on Lean's siblings and varies between arms run at different times (S5). On socket 0 during a pause only
the restarting servers run (the trainer is on socket 1); on socket 1 during sampling Lean competes with the loop, the
trainer's preparation thread, the durable copy and tokenizer bursts. By construction the layout is the same in every
arm and probe run only when (a) every loop is started through `arm_loop.sh`, (b) no shell carries a stale
`SERVER_CPU_LIST`, (c) the container allows lowering niceness. None of the three is checked.

## Quota against the layout

105.3 cores of quota, 96 + 96 pinned CPUs: either side can push the cgroup over its quota, and CFS then stops every
process of the container for the rest of the period, whatever its CPU set. The check (`pinning_refusals`, set size
< quota) only guarantees Lean alone cannot exhaust it; it leaves 9.3 cores for 8 servers (16 processes) plus anything
else off the Lean set. Lean's real demand is min(|set|, busy REPLs + loop + helpers) ~ 84-90 at sampling concurrency
84 once later checkpoints are Lean-bound; 8 servers need ~6-12 (README: 4 vLLM processes ~3) and more while one
compiles after a restart. So throttling in late phases is plausible with `48-95,144-191` (grpo_loop_v1 was throttled at
123 cores); `144-191` cannot throttle but puts 84 REPLs on 48 CPUs. Throttling freezes Lean too, so it eats the 60 s
wall-clock backstop: an arm whose policy is more Lean-heavy throttles more, a load difference between arms. The right
launch check is min(|Lean set|, Lean concurrency + 4) + server reserve <= quota, the reserve from the throughput
test (warn, print the margin). Detection today: only the dashboard's system sampler (`cpu_throttled_fraction`) if it
runs for that run directory; `pinning.jsonl` and `run.json` hold no counters, probe runs have none at all (M3).

## Must fix before merge

- **F1. A stale default `SERVER_CPU_LIST` overrides the node file, and the check accepts overlapping sets.**
  `environment.sh:47` exports `SERVER_CPU_LIST=$(cgroup_allowed_cpus)` (0-191) whenever no value is set; the node
  file's `${SERVER_CPU_LIST-0-47,96-143}` then keeps 0-191 in every shell that sourced `environment.sh` before the file
  existed (any tmux/ssh shell from this morning's setup) and in all its children. Reproduced: after the node file
  appears, a child's `node_checks.py pinning` prints `BACKGROUND_CPU_LIST=2-3 SERVER_CPU_LIST=0-3` and exits 0. On the
  node: servers on all 192 CPUs, sharing Lean's, recorded but accepted. Fix: do not export a default in
  `environment.sh`; compute it in `serve_model.sh` (`server_cpus="${SERVER_CPU_LIST:-$(cgroup_allowed_cpus)}"`). In
  `node_pinning.pinning_refusals` refuse a background set that intersects `SERVER_CPU_LIST` unless the latter is all
  allowed CPUs (the old default), and refuse a pair sharing a physical core (`topology/thread_siblings_list`).
- **F2. The niceness reset fails closed at the first publish, hours in.** `serve_model.sh:48-53` refuses unless
  `nice -n -19` works from nice 19. Docker's default capability set has no CAP_SYS_NICE and RLIMIT_NICE is 0, so root in
  a container usually cannot; then every start from the loop, `probe_evaluate.py` or the expert-iteration service (all
  at nice 19 under `background.sh`) fails 3 times and the loop raises at the pause with all servers stopped, or a probe
  run dies at its first restart. Nothing checks it at launch. Fix now: `node_checks.py pinning` tries the reset in a
  child at nice 19 and refuses (`arm_loop.sh`, `probe_runs.sh`). Better (S1 too): do not nice the loop; nice and pin
  only the Lean processes (the REPL spawn in `LeanReplPool`, `grpo_evaluate`'s pool), so nothing ever raises priority.

## Must fix before an arm

- **M1. The loop's own layout is neither checked nor recorded by the loop.** `arm_loop.sh:93` records a separate
  `node_checks.py record` process; the README's "rerun `grpo_loop.sh loop` after a crash" records nothing, and with no
  node file or `BACKGROUND_CPU_LIST=` it runs unpinned at nice 0 (`grpo_loop.sh:91-96`) while `pinning.jsonl` still shows
  only the pinned starts. Same for `background.sh python experiments/probe_evaluate.py` by hand (last 32 CPUs when
  nothing is set). Fix: `grpo_loop.py run` and `probe_evaluate.py` call `append_pinning` on their run directory at
  every start and refuse unless `pinned_as_background`, as `held_out_evaluate.py:103` does; the loop logs each
  server's `<name>.cpus` after every start (the file is deleted at the next stop, so nothing else keeps it).
- **M2. Nothing compares a resumed run's layout with its first.** After a reboot, a node-file edit (the throughput test
  may switch to `144-191`) or a quota change, `probe_runs.py next` and `arm_loop.sh` resume and the run stays
  "comparable". Fix: refuse a resume whose `current_pinning()` differs from the run's first record in affinity,
  `cpu_count`, quota and the three settings.
- **M3. Throttling is not recorded per run.** Add `cpu_counters()` (usage, periods, throttled periods) and the boot
  time to each `PinningRecord`, write a closing record after each probe run (`probe_runs.sh:89`) and the counters in each
  phase's record, so the throttled share per run and phase is in the run directory; `arm_loop.sh` warns when no
  `record-system` runs for the arm's directory. Add the quota margin warning above to `node_checks.py pinning`.

## Should

- **S1.** The trainer inherits the loop's set and nice 19 (`loop_services.training_launcher`, 345-350, via `run_logged`):
  ranks of GPUs 0-2 run remote, and its model building at the first `prepare` loads Lean's CPUs in phase 1 of every arm
  (and again after any trainer death, which differs between arms). Prefix `taskset --cpu-list $SERVER_CPU_LIST` (the
  servers are stopped while it trains); `run_in_background` keeps the preparation thread on Lean's set.
- **S2.** Loop-side CPU work beside Lean: set `RAYON_NUM_THREADS`/`TOKENIZERS_PARALLELISM=false` in the loop's
  environment (`grpo_loop.sh loop`); run `record_durably`'s copy and the CPU-merge fallback off the Lean set.
- **S3.** A mid-sampling restart compiles with up to 32 inductor threads inside the shared quota: cap
  `TORCHINDUCTOR_COMPILE_THREADS` for servers. **S4.** Record host-wide busy CPUs (`/proc/stat` minus the cgroup's) and
  `/proc/loadavg` per phase: other tenants' load is the remaining uncontrolled CPU difference between arms.

## Minor

- The tracker's 60 s (README "Pid files ..."): measured, a group SIGTERM ends in 1 s with the leader alive and after
  it died; the tracker exits on EOF once the engine (holding its fd) exits, so 60 s only when the engine ignores
  SIGTERM. The orphan path needs an API-process crash; per-publish stops (API alive) take ~1 s, as on the node. The
  test's tracker keeps its own FIFO open (`57<>pipe`), unlike the real one. Fix the sentence.
- `grpo_loop.sh loop` prints "Loop started" when `background.sh` refused (both set); stale `BACKGROUND_CPUS=52`
  examples (`arm_loop.sh:6`, followup `shared_sampling.toml`, `gate_evaluation.toml`, `step1/runs_*.toml`) now fail
  here; `serve_model.sh:44` accepts a list partly outside the cpuset.
- Portability (item 5): on a cgroup v2 node the quota, counters and memory readers behave as on master; on a
  single-socket node without a node file the launchers work as before with `BACKGROUND_CPUS`. Not identical: servers
  now always run on all allowed CPUs at nice 0 whoever starts them, and starts from niced callers need CAP_SYS_NICE
  (F2; a regression for `grpo_expert_iteration.py` under `background.sh`).

## Operator checklist on the node (under 10 minutes, before a 30-hour arm)

1. `cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us /sys/fs/cgroup/cpuacct/cpuacct.usage; cat /sys/fs/cgroup/cpu/cpu.stat`:
   10532571, a counter, `nr_periods`/`nr_throttled` lines (else the sampler's throttling is blind).
2. `for c in 0 47 48 95; do cat /sys/devices/system/cpu/cpu$c/topology/thread_siblings_list; done`: `0,96 47,143 48,144
   95,191`; `lscpu | grep NUMA`: node0 `0-47,96-143`, node1 `48-95,144-191`.
3. `deployment/background.sh bash -c 'nice -n -19 nice; grep CapEff /proc/self/status'`: `0`. A `19` with "Permission
   denied" means every server restart fails (F2): do not start.
4. In every shell you will launch from: `echo "$SERVER_CPU_LIST|$BACKGROUND_CPU_LIST|$BACKGROUND_CPUS"` is empty or
   `0-47,96-143|48-95,144-191|` (never `0-191`, F1); then `bash -lc 'cd /workspace/LLM-Search-Lean-Proofs && source
   deployment/environment.sh && python experiments/node_checks.py pinning'`: those lists, 96 of 192, exit 0.
5. After `grpo_loop.sh servers`: `cat $LEAN_SEARCH_RUNS/servers/*.cpus`: 8 x `0-47,96-143 0`; one engine per server:
   `ps -o pid=,ni=,comm= -g $(cat $LEAN_SEARCH_RUNS/servers/policy-gpu0.pid)` then `taskset -cp <pid>`: same list.
6. Niced restart path: `deployment/stop_model.sh value-gpu3` then `LOOP_CONFIG=<arm config> deployment/background.sh
   python experiments/grpo_loop.py --config <arm config> start-servers`: `value-gpu3.cpus` = `0-47,96-143 0`.
7. 2 min after the arm starts: `p=$(cat $run/loop.pid); taskset -cp $p; ps -o ni= -p $p`: `48-95,144-191`, 19; last
   line of `$run/pinning.jsonl` shows that affinity, quota 105.3, `server_cpu_list` `0-47,96-143`.
8. `pgrep -af record-system` names the arm's run directory; `grep nr_throttled /sys/fs/cgroup/cpu/cpu.stat` twice 60 s
   apart during sampling: the difference near 0 (else note it; with M3 missing it is the only throttling record).

## Re-review (bce49b0; WSL: pinning, serve, server-start, monitoring, process-handling, loop-services tests 307 passed)

Arm phase on the new head, node file `BACKGROUND_CPU_LIST=48-95,144-191`, servers/training `0-47,96-143`: the loop
(orchestrator, health and habit threads, the durable copy) on Lean's set at nice 0; REPLs (sampling, held-out) nice 19
by their own `setpriority`; 8 servers at every start (arm_loop, publish restart, failure restart, probe restart) on
`0-47,96-143` at nice 0, each start logged with its `.cpus`; torchrun, ranks, GPU merges and handoff, CPU-merge fallback
(subprocess) on `0-47,96-143` at nice 0; the trainer's preparation/labelling thread on Lean's set at 19 (by design).
Under `swap = "restart"` with `gpus = [0,1,2,3]` all 8 servers are stopped while the ranks train, so during training
socket 0 holds only the trainer and its merges; the servers restart after it, and the held-out states run after that
(their REPLs on socket 1). Nothing heavy left at nice 19; nothing of ours shares a physical core across the two sets.
- F1 resolved: no exported default; a stale `SERVER_CPU_LIST=0-3` beside a node file is now refused (reproduced, exit 1).
- F2 resolved: nothing raises priority; `node-check` prints the capability for the record.
- M1 resolved: `grpo_loop.py run` records and checks its own session, hand restarts via `grpo_loop.sh loop` included
  (minor: a fresh loop is not required to be pinned; the study path has `arm_loop.sh`'s check). M2 resolved (loop,
  `probe_evaluate.py`, `held_out_evaluate.py`: affinity, CPU count, quota, all lists). M3 resolved: counters per session,
  in run.json, per phase; quota warning at set + 8-core reserve (96 + 8 < 105.3). Same layout by construction: yes.
- Should (new, not blocking): loop-process work now runs at nice 0 on Lean's CPUs, above the REPLs, chiefly the 13 GB
  `record_durably` copy (loop.py:1811) beside the held-out states and sampling; same every phase and arm. The missing
  `--allow-other-pinning` in `probe_runs.sh` does not matter for fresh anchor directories; on a changed layout the lists
  stop fail-closed and that run is resumed by hand through `background.sh ... probe_evaluate.py ... --allow-other-pinning`.
Verdict: merge.

Checklist (after deployment, before the anchors; fresh `ssh` login shell, repository directory):
1. `source deployment/environment.sh && python experiments/node_checks.py pinning`: the node file's two lines, `BACKGROUND_CPU_LIST=48-95,144-191 SERVER_CPU_LIST=0-47,96-143 TRAINING_CPU_LIST=0-47,96-143`, cpuset 0-191, quota 105.326, `background.sh pins CPUs 48-95,144-191 (96 of 192)`, `9.3 cores of the quota beside them (reserve 8)`, no warning, exit 0. Repeat `env | grep -E 'CPU_LIST|BACKGROUND_CPUS'` in every tmux shell you launch from: empty or exactly these lists.
2. `cat /sys/devices/system/cpu/cpu{0,47,48,95}/topology/thread_siblings_list`: `0,96 47,143 48,144 95,191`.
3. `cat /sys/fs/cgroup/cpuacct/cpuacct.usage; grep nr_ /sys/fs/cgroup/cpu/cpu.stat`: a counter; `nr_periods`, `nr_throttled`.
4. After `grpo_loop.sh servers`: `cat $LEAN_SEARCH_RUNS/servers/*.cpus`: 8 x `0-47,96-143 0`.
5. 5 min into the first anchor: `tail -n 1 $LEAN_SEARCH_RUNS/<output>/<run>/pinning.jsonl`: affinity 48-95,144-191, the three lists, a node_environment sha256, `cpu_counters` non-null; `ps -eo ni,psr,comm | awk '$3 ~ /repl|lean/' | sort | uniq -c | head`: ni 19, psr within 48-95/144-191; `ps -o ni=,psr= -p <probe_evaluate pid>`: 0.
6. `grep nr_throttled /sys/fs/cgroup/cpu/cpu.stat` twice 60 s apart during the anchor: difference near 0.
