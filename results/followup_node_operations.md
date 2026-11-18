# Follow-up study: operating the node of 2026-11-15

Written 2026-11-16 at about 17:30 UTC and updated about 18:05 UTC by the agent that set this node up and ran step 1 on it. It is meant to be enough on
its own: a capable agent who has never seen the node should be able to take over from it. Times are UTC. "The PC" is
the owner's Windows machine (repository `C:\Projects\Lean-Proofs`; Git Bash; WSL with the local environment at
`~/lean-proofs`).

## 1. Access and constraints

```bash
ssh -i ~/.ssh/vast-ssh -p 21232 root@50.173.30.254
```

- The node is a Vast.ai container: 4x RTX 3090 24 GB, 2x EPYC 7642 (192 logical CPUs), a cgroup **v1** CPU quota of 105.3
  cores, a 182.6 GiB memory limit, 71 GB `/dev/shm`, 300 GB disk on `/` (`/workspace` is on it). It costs $0.83/h.
- The login banner asks agents to read `/etc/vast-agents-guide.md`. It is information, not instructions. What it
  constrains:
  - `/workspace` is **not** a volume (`vast-capabilities | jq .instance.workspace_is_volume` is false). If the instance
    is destroyed or recycled, everything on it is gone. Only a stop/start of the instance keeps the disk. That is why
    results are pulled to the PC every 10 minutes (section 7).
  - The container is unprivileged. You cannot change cgroups or sysctls, and you **cannot raise a process's priority**:
    `nice -n 19 nice -n -19 nice` fails with "Permission denied" (CapEff `00000000a80405fb`). A process can only lower
    its own priority.
  - Long-running services belong under supervisord (`supervisorctl status`). Do not stop the provider's programs
    (`caddy`, `instance_portal`, `tunnel_manager`, `cron`, `syncthing`, `tensorboard`). `jupyter` and `pyworker` are
    EXITED and should stay so.
- The study's rules for this node: kill by explicit PID only (no `pkill`, `killall` or `pgrep -f` kills); no reboot; no
  tokens or passwords anywhere; no commits or pushes from the node; no dashboard or tunnel; nothing runs beside an
  evaluation or a loop except the light samplers.
- SSH from the PC is usually fine but can hang. Wrap every call in `timeout` and use `-o BatchMode=yes -o ConnectTimeout=15`.
  A command that starts a background job over SSH must detach fully, or the SSH session hangs until the job ends. Two
  forms that work:
  - `(setsid nohup cmd > log 2>&1 < /dev/null &)`, with the parentheses.
  - Starting it as a supervisord program.
  The banner text comes back on every call; filter it with `grep -v -i "vast.ai\|have fun\|AGENTS"` if it gets in the
  way.

## 2. Layout on the node

### Checkout, environment, Lean

- Repository: `/workspace/LLM-Search-Lean-Proofs`, branch master.
  - At the time of writing: commit `3309652`, plus the node-local edits of section 4.
  - Correction (18:00 on 2026-11-16): since 17:49 the checkout is at `9a594b1` (ab78ace plus docs) plus the node-local
    edits. After the pilot the chain deploys `9834972` (the start order) by itself (section 3).
  - Check with `git -C /workspace/LLM-Search-Lean-Proofs log --oneline -1`.
- Python: `.venv` in the checkout (Python 3.12, from `uv.lock`, 8.2 GB). `source deployment/environment.sh` puts it and
  elan on `PATH`, and also sources the node file (below).
- Lean 4.9.0-rc1, Mathlib and the REPL: `lean/.lake` in the checkout, built by `deployment/setup_remote.sh`.
- Base models: Hugging Face cache `/workspace/.hf_home` (13 GB): `Qwen/Qwen3.5-4B` @ `851bf6e`, `Qwen/Qwen3.5-2B` @
  `15852e8`. The runs read it with `HF_HUB_OFFLINE=1`.

### Downloads and the hand-made links

| Path | What |
|---|---|
| `/workspace/hf/lean4-prover-qwen3.5-4b-grpo-lora` | model repo `BertilBraun/lean4-prover-qwen3.5-4b-grpo-lora` (policy `v0_sft`, `expert_iteration_1b`, `latest` = v35; value `v0`, `latest`) |
| `/workspace/hf/lean4-search-grpo-qwen3.5-4b` | dataset `BertilBraun/lean4-search-grpo-qwen3.5-4b`, only `verified_pool/`, `fixed_sets/`, `sft_data/`, `expert_iteration_round_1/`, `run_logs/`, `search_trees/index.jsonl` |

The loop configs expect fixed paths. These symlinks were made by hand
(`/workspace/setup_logs/place_files.sh`) so that nothing is stored twice:

| Link | Target | Used as |
|---|---|---|
| `/workspace/checkpoints/data_rewrite_sft_numbered/adapter` | `hf/…lora/policy/v0_sft` | policy v0 (`followup/base.toml [initial] policy_adapter`) |
| `/workspace/checkpoints/phase3_value_v0/adapter` | `…/value/v0` | value v0 |
| `/workspace/checkpoints/grpo_loop_v1_expert_iteration_01b/adapter` | `…/policy/expert_iteration_1b` | old run's EI adapter |
| `/workspace/checkpoints/hf_policy_latest_v35/adapter` | `…/policy/latest` | old run's final policy v35 (runs 7, 8) |
| `/workspace/checkpoints/hf_value_latest/adapter` | `…/value/latest` | old run's final value model (runs 5, 7) |
| `/workspace/data/reasoning`, `data/sft`, `data/value` | `hf/…grpo-qwen3.5-4b/sft_data/*` | replay data (`lean_replay`, `math_replay`, `value_replay`) |
| `/workspace/data/expert_iteration/pool_v3` | `…/verified_pool` | the old pool |
| `/workspace/data/grpo/fixed_sets_by_characters` | `…/fixed_sets/fixed_sets_by_characters` | |
| `/workspace/data/grpo/renamings.jsonl` | `…/fixed_sets/renamings.jsonl` | |
| `/workspace/data/grpo_expert_iteration/grpo_loop_v1_round_1` | `…/expert_iteration_round_1` | |
| `/workspace/runs/grpo_loop_v1/trees/index.jsonl` | `…/search_trees/index.jsonl` | `--old-run-index` of `grpo_fixed_sets.py select-by-characters` (the calibration statements) |

Real copies, not links, because the configs pin their digests or because new sets are written beside them:

| File | sha256 | Source |
|---|---|---|
| `/workspace/data/grpo/fixed_sets/` (a real directory) | | the dataset's `fixed_sets/fixed_sets/*.jsonl`, plus probe v2 and new sets |
| `/workspace/data/grpo/fixed_sets/probe_v2.jsonl` | `2cf5a308…bfbbe` | PC `node_backup\2026-11-14\probe_v2\` (also `probe_v2_twins.jsonl` `b8caedcd…`, `probe_v2.selection.json`, `probe_v2_select.log`) |
| `/workspace/data/grpo/fixed_sets/calibration_200.jsonl` | `3652b215…` | drawn on the node in step 1c (with `calibration_200_twins.jsonl`) |
| `/workspace/data/followup/verified_pool_2026-11-01.jsonl` | `1b216b06…600c` (pinned in `followup/base.toml`) | the dataset's `verified_pool/verified.jsonl` |
| `/workspace/runs/phase5_eval_visible_student_v2_visible/states.jsonl` | `06fcb020…` (512 held-out states) | from `node_backup\2026-10-15\increment_2140.tar.zst` on the PC |

### CPU layout and the node file

- NUMA node 0 is CPUs `0-47,96-143`; node 1 is `48-95,144-191`.
- CPU n and CPU n+96 are SMT siblings of one physical core: `/sys/devices/system/cpu/cpu0/topology/thread_siblings_list`
  reads `0,96`.
- GPUs 0-2 hang off NUMA node 0 and GPU 3 off node 1 (`nvidia-smi topo -m`). There is no peer-to-peer path: NCCL
  all-reduce runs at about 3 GB/s.
- `/workspace/node_environment.sh` (sha256 `65453b91…7106`) is sourced by `deployment/environment.sh`. Its exact
  contents:

```bash
export BACKGROUND_CPU_LIST=48-95,144-191
export SERVER_CPU_LIST=0-47,96-143
export TRAINING_CPU_LIST=0-47,96-143
```

- What the three lists mean:
  - **Lean** (every search process and its REPLs, through `deployment/background.sh`) gets both threads of socket 1:
    96 logical CPUs, 48 physical cores.
  - **The 8 vLLM servers** get socket 0, which is local to GPUs 0-2.
  - **Training** (trainer ranks, merges) also gets socket 0; the servers are stopped while training on the restart path.
  - No physical core is shared between Lean and the servers. `python experiments/node_checks.py pinning` checks that,
    the sibling overlap and the quota headroom (96 + reserve 8 ≤ 105.3).
- REPLs lower themselves to nice 19. The search processes and servers run at nice 0.
- CPU quota: cgroup v1, `/sys/fs/cgroup/cpu/cpu.cfs_quota_us` (10532571) over `cpu.cfs_period_us` (100000).
  - Usage: `/sys/fs/cgroup/cpuacct/cpuacct.usage` (ns).
  - Throttling: `/sys/fs/cgroup/cpu/cpu.stat` (`nr_periods`, `nr_throttled`, `throttled_time` ns).
  - Memory limit: `/sys/fs/cgroup/memory/memory.limit_in_bytes`. There is no `cpu.max`.
  - The throttled count stood at 9 at the time of writing. It has not risen during any run; the two increments came
    during server restarts.
- Disk at the time of writing: 58 GB used, 243 GB free.
  - `/workspace/checkpoints` holds 26 GB (merges of every served weight set).
  - `/workspace/runs` holds 1.7 GB.

## 3. What is running and how

### supervisord programs (ours)

Configs are in `/etc/supervisor/conf.d/`, with copies in `/workspace/step1_chain_tools/`.

| Program | Conf | Command | What it does |
|---|---|---|---|
| `step1_chain` | `step1_chain.conf` | `/workspace/step1_chain_tools/step1_chain.sh` | step 1's chain driver (below). `autostart=true`, `autorestart=unexpected`, `exitcodes=0`: an exit 0 is final, any other exit is retried |
| `power_limits` | `power_limits.conf` | `/workspace/step1_chain_tools/power_limits.sh` | every 60 s: enforced GPU power limits, SM clocks, temperatures → `/workspace/runs/step1_chain/power_limits.txt` |
| `reasoning_sampler` | `reasoning_sampler.conf` | `/workspace/step1_chain_tools/sample_reasoning.sh /workspace/runs/step1_chain/sampler_reasoning.tsv` | every ~10 s (light): cgroup CPU and throttling, per-GPU utilisation and power, policy servers' cumulative generated tokens and requests, and the REPL processes' count, CPU seconds and run-queue wait (`/proc/<pid>/schedstat`) since the previous sample |

- Start, stop and status: `supervisorctl start|stop|status <program>`.
- Stopping `step1_chain` (`stopasgroup`) kills the launcher and its running `probe_evaluate.py`. The launcher resumes the
  interrupted run when started again, but stop it only between runs if you can.
- `study_chain.conf` (in `/workspace/step1_chain_tools/`) is the S1-only draft's and **not installed**; the step-2
  driver and its conf are in the repository (`deployment/study_chain.sh`, `.conf`; "The study driver" below).

### Other processes of ours

- `relay_after_e1.sh` (pid in `/workspace/runs/step1_chain/relay_after_e1.pid`, started 17:55 on 2026-11-16) is a
  one-shot relay. It waits for the stop of the driver that runs the pilot (e1):
  - **Pilot accepted:** STOPPED "step e2 failed 3 times", a planned stop, because `attempts_e2` was preset to 3. The
    relay moves it to `STOPPED.after_pilot_accepted`.
  - **Pilot rejected:** STOPPED "step e1: … rejected". The relay moves it to `STOPPED.e1_pilot_rejected_cap14400` and
    writes the marker `e1_rejected`.
  - In both cases it then deletes `attempts_e2` and runs `supervisorctl start step1_chain`.
  - Any other STOPPED is left alone.
  - It is not supervisord-hosted. After a container restart it is gone, but supervisord then restarts `step1_chain` with
    the current file. Only if the pilot had already been rejected before the restart would you need to do the relay's
    rejected branch by hand.
- `relay_after_j.sh` (the earlier relay) did its job at 17:48 and has exited.
- The 8 vLLM servers: started by `serve_model.sh` (`setsid`), each in its own process group, with pid files in
  `/workspace/runs/servers/`.

### The step-1 driver (`/workspace/step1_chain_tools/step1_chain.sh`)

- State directory: `/workspace/runs/step1_chain/`; log `chain.log` (also receives every launcher line).
- At start the driver exits 0 at once if `STOPPED`, `done_all` or `HOLD` exists. Otherwise it sleeps 60 s (boot
  ordering), sources `environment.sh` and runs each step whose `done_<step>` marker is missing.
- Each step increments `attempts_<step>`; a 4th attempt writes `STOPPED`.
- The launcher's exit codes:
  - 3 (a run rejected for wall-clock stops) and 4 (servers kept dying) write `STOPPED` and exit 0.
  - Any other non-zero exit is exit 1, so supervisord retries and the launcher resumes the interrupted run.
- **bash reads a running script lazily**, so never edit `step1_chain.sh` in place while it runs. Write a new file and
  `mv` it over the old one: the running bash keeps its old inode (`ls -l /proc/<pid>/fd/255` shows "(deleted)"), and the
  next start uses the new file. All driver changes so far were made this way.
- To make a running (old-file) driver stop at a step boundary, preset that step's `attempts_<step>` to 3: its next
  `attempt` writes STOPPED "step <x> failed 3 times". A relay or the operator then moves the STOPPED aside, deletes the
  `attempts` file and starts the chain again.
- After a container restart, supervisord starts the driver, which continues at the first step not done. The launcher
  resumes an interrupted run (sessions are recorded per run), and `grpo_loop.sh servers` restarts servers that do not
  answer.

| Step | What | State (2026-11-16 18:00) |
|---|---|---|
| a | anchors (runs 1, 2) | done |
| b | T = 26,804 into the token-capped configs | done |
| c | calibration set, calibration run, constants | done (`done_c_select`, `done_c_run`, `done_c_constants`) |
| d | three value-free pilots | done |
| f | run 6, completion | done |
| g | run 5, final value | done |
| h | value servers back to v0, run 6 with block_sum | done |
| i | run 8 (v35, value v0) | done |
| j | run 7 (v35, final value) | done (17:48, 1,236 of 2,000) |
| deploy_ab78ace | stash, fast-forward to origin/master's head, pop, check | done: deployed **9a594b1** (ab78ace plus docs) at 17:49 |
| k | all 8 servers stopped and started on v0's weights (`grpo_loop.sh servers` with `followup/base.toml`) | done 17:52 |
| e1 | the no-reasoning pilot alone, node-local list `runs_reasoning_e1_pilot.toml` (`step1_run4_pilot_no_reasoning_T_cap14400`, first 200 statements, `token_capped_evaluation.toml`, 14,400 s wall cap, file order) | **running since 17:55:07** on the old driver file (pid 238295) |
| boundary | (old file only) passes at once because `ORDER_READY` exists | |
| deploy_9834972 | stash, `git merge --ff-only 9834972` (the start order by expected search time), pop; diffs `edits/before_9834972.diff`, `after_9834972.diff`, `9834972_edit_difference.txt` (must be empty); T checked | next (new file) |
| e2 | `probe_runs.py check --concurrency 112` on node-local `runs_reasoning_e2_ordered.toml` (output `e2_check.txt`), then runs 3 `step1_run3_visible_T` and 4 `step1_run4_no_reasoning_T`, both on `token_capped_evaluation_ordered.toml` (`submission_order = "longest_expected_search_first"`). A background logger writes each run's first-session `start_order` into chain.log ("start order of <run>: …"); `run.json` (written at a run's end) holds `start_orders`. Skipped if `e1_rejected` exists | next |
| e2 reports | `run3_load_against_file_order.txt`, `run3_against_run4.txt` (`--across-search-modes`), `anchors_against_run3.txt` (`--descriptive-across-settings`), `reasoning_readings.txt` (bulk/tail readings of the pilot, run 3 and run 4 from `/workspace/step1_chain_tools/reasoning_readings.py`) | `done_e2_reports` |
| f_order_check | `runs_order_check.toml`: `step1_run9_v0_value_v0_ordered` (v0, value v0, 2,000, new order, not an anchor, 7,200 s cap) | |
| f reports | `run9_against_step1_run1_v0_value_v0.txt`, `run9_against_step1_run2_v0_value_v0.txt`, `run9_load_against_anchors.txt` | `done_f_reports` |
| HOLD | writes `HOLD` "waiting for the owner's decision on the arms' mode (…)"; servers stay up | |

**What happens by itself from now on:**
1. The pilot ends.
   - Accepted: the old driver passes the boundary and stops on purpose at e2.
   - Rejected: it stops with the rejection.
2. The relay moves the STOPPED aside (writing `e1_rejected` if rejected), deletes `attempts_e2` and restarts the chain.
3. The new driver deploys 9834972, then runs e2 (unless `e1_rejected`), writes the e2 reports, runs f and its reports,
   then writes HOLD.
4. Rough times: the pilot 1-3 h; run 3 3-4 h; run 4 10-25 h; f about 3 h.

Expect the start of an ordered run to be Lean-bound. The hardest statements start first, so Lean demand exceeds the 96
Lean CPUs in the first ~30 minutes and the GPUs are partly idle in the first hour. That is not a stall. Watch run 3's
wall-clock stops early (`run.json` is written only at the end; count `wall_clock_budget` in `results.jsonl`).

**What a new agent must check on arrival:**
- `supervisorctl status`: `step1_chain`, `power_limits` and `reasoning_sampler` should be RUNNING, unless HOLD was
  reached.
- `tail -30 /workspace/runs/step1_chain/chain.log`, and whether `STOPPED` or `HOLD` exists in
  `/workspace/runs/step1_chain/`.
- `cat /workspace/runs/probe_evaluations/ledger.tsv`.
- The relay, if the pilot has not ended: `ps -p $(cat /workspace/runs/step1_chain/relay_after_e1.pid)`.
- The PC pull: `live/last_pull.txt` under 10 minutes old (section 7).
- If the chain sits on a STOPPED that no relay handles, read its text, fix the cause, move it aside (renamed, not
  deleted) and `supervisorctl start step1_chain`.

To stop safely between runs, wait for a run's ledger line, then `supervisorctl stop step1_chain`.

Markers in `/workspace/runs/step1_chain/` and what they mean:

| Marker | Meaning |
|---|---|
| `done_<step>` | step finished |
| `attempts_<step>` | tries so far; ≥ 3 makes the next try stop the chain (used on purpose to stop an old-file driver at a boundary) |
| `attempts_e.before_cap14400` | the old e's counter, kept |
| `STOPPED` | the chain is stopped; its text says why |
| `STOPPED.deploy_boundary` | the planned stop before deploying 3309652 (2026-11-15) |
| `STOPPED.step_e_pilot_rejected` | the first no-reasoning pilot, rejected at 1.00% wall stops with the 7,200 s cap |
| `STOPPED.deploy_ab78ace_boundary` | the planned stop after run 7 (2026-11-16 17:48) |
| `STOPPED.after_pilot_accepted` / `STOPPED.e1_pilot_rejected_cap14400` | written by `relay_after_e1.sh` |
| `e1_rejected` | the second pilot was rejected: e2 skipped, f runs |
| `HOLD` | the driver exits 0 at start; the final HOLD says "waiting for the owner's decision on the arms' mode" |
| `HOLD.after_c`, `HOLD.after_h` | old holds, released |
| `hold_before_e`, `hold_before_e.released*` | the hold switch before e1; released |
| `released_after_c` | the hold after c happened once |
| `ORDER_READY` | written 17:55: the start order is reviewed (9834972); it only makes the old file's boundary pass at once |
| `done_e_boundary` | the old file's boundary passed |

Other files there:
- `chain.log`, `supervisor.log`, and `edits/` (copies and diffs of every node-local edit).
- Reports:
  - `anchor1_report.txt`, `anchor2_report.txt`, `anchors_load.txt`, `anchors_pair.txt`;
  - `run5_*`, `run6_*`, `run7_*`, `run8_*`;
  - `two_by_two.txt`, `pair_run8_run7.txt`, `pair_run5_run7.txt`;
  - `pilots_load.txt`, `token_budget.txt`, `automation_constants.txt`, `calibration_select.log`;
  - later the e2 and f reports named above.
- Readings: `checks_before_anchor.log`, `readings_run1_5min.log`, `run5_restart_readings_*.log`,
  `run8_restart_readings.log`, `run7_restart_readings.log`.
- `power_limits.txt` and `sampler_reasoning.tsv`.

### The study driver: step 2, arm A's learning rate (shrunk 2026-11-17, not installed)

The repository's `deployment/study_chain.sh` (supervisord program `study_chain`, conf `deployment/study_chain.conf`)
runs the learning-rate step unattended and ends in a HOLD with a report. Since the owner's decisions of 2026-11-17 the
step picks only arm A's GRPO rate: arm B is dropped, arm C takes the offline run O2's rate (the same expert-iteration
recipe and trainer) and a 4-phase window, D takes C's rate and window and A's rate. State and logs are in
`/workspace/runs/study_chain/` (log `chain.log`). The plan, the round configs and the report come from
`experiments/learning_rate_step.py` (logic in `src/lean_search/rl/learning_rate_step.py`); the helpers it shares with
the offline driver are in `deployment/chain_helpers.sh`. Reviews AU and AV (`results/reviews/2026-11-16_review_au_*`,
`_av_*`) covered the larger first version.

**What it runs, in this order** (node hours are estimates; the first real run sets them):

| Step | What | Markers | Hours |
|---|---|---|---|
| mode | `learning_rate_step.py check-mode` on `mode.toml` (refuses a search config with a per-search token cap) → `mode.txt` (standard output only; warnings go to `mode.err`): the mode's description, with a warning when the depth cap can bind, and its search config's sha256. The first start copies both to `mode.recorded` and `mode.recorded.txt`; every later start compares both | `mode.recorded*` | - |
| configs | `learning_rate_step.py write-configs`: `configs/A_<rate>.toml` (3 rounds: arm A's phase config at the rate), `rounds.tsv`, `held_out.tsv` | `done_configs` | - |
| S1 sampling | `stop_model.sh --all` (first start only: step 1's servers would otherwise be kept whatever they hold), then `arm_loop.sh --kind "shared sampling" --mode mode.toml followup/shared_sampling.toml` (one phase, 12M generated tokens, no training), polled every 60 s until `finished.json`; a loop found dead is started again through `arm_loop.sh`. After `finished.json` it waits (up to 10 minutes, then an attempt is counted and it exits 1; the 4th writes STOPPED) until the loop's process is gone, since `slice_trees.py` refuses while it lives | `done_s1_sampling`, `attempts_s1_sampling_start`, `attempts_s1_loop_exit` | 0.7-1 with visible reasoning (about 25M tokens/h at 112 searches, plus the servers' start and the loop's v0 baseline), up to about 1.5 without |
| S1 slices | `slice_trees.py --slices 1`: the phase's trees linked into `followup_shared_sampling/slices/slice_1` (a partial one moved aside first); a failure stops the chain | `done_s1_slices` | minutes |
| S3a | v0's held-out run `held_out_step2_v0`, on the servers the loop left on v0 | `done_held_out_step2_v0` | 0.2 |
| S2 | `stop_model.sh --all`, GPUs checked free (every GPU under 100 MiB used, from `nvidia-smi --query-gpu=index,memory.used`; idle reads 1 MiB), then A's three rounds one at a time on the 4 GPUs (`torchrun`, training CPUs, `HF_HUB_OFFLINE=1`): `grpo_phase.py --part policy` on `slice_1` with the loop's Lean and math replay at 2e-5, 5e-5, 1e-4 | `done_round_A_<rate>` | about 1.5 (3 × ~0.5) |
| S3b | before each run `grpo_loop.sh servers` (starts the servers not answering, the value servers too, which held-out runs do not use; answering ones are kept), then each variant's `held_out_evaluate.py --name step2_A_<rate>` (merge, policy servers restarted onto it, 512 states at concurrency 56), last v0 again as `held_out_step2_v0_end`. A run counts as done only if its `summary.json` names no dropped state (`learning_rate_step.py check-held-out`); otherwise the driver exits 1 and the next start resumes it under its name | `done_held_out_step2_A_<rate>`, `done_held_out_step2_v0_end` | about 0.8 (4 × ~12 min) |
| S4 | `rank_learning_rates.py` for A without gate runs (`rank_A.txt`), then `learning_rate_step.py report` → `learning_rates_report.md` | `done_s4_report` | minutes |
| HOLD | `stop_model.sh --all` (the policy servers hold the last held-out run's merge, and an arm's `arm_loop.sh` would keep them), then HOLD: "step 2 done: …learning_rates_report.md holds the arms' values (not applied); the servers are stopped" | `HOLD` | |

Altogether about 3-4 hours. Labels `A_2e-5`, `A_5e-5`, `A_1e-4`; run names and held-out names are `step2_<label>`,
outputs in `$LEAN_SEARCH_CHECKPOINTS/step2_<label>/`. A round's phase config is arm A's own (`arms/A.toml` through
`followup_arm`'s overlay code) at the variant's rate, v0 as start and KL reference, with the arm's phase-1 seeds (1
and "grpo-replay/1"); the trees are the shared phase's, sampled by v0 as the arm's phase 1 will be. Only the trainer
differs from the arm's first update (`grpo_phase.py`, not the persistent one).

**The tie rule** (`rate_ranking.tie_break`, DESIGN's, the owner may change it): among variants tied on the held-out
states, the lower rate.

**v0's baseline is run again** (`held_out_step2_v0`), not taken from `held_out_v0` of 2026-11-15: that run used older
code, the Lean side pinned to 48 CPUs (`BACKGROUND_CPUS=48`, `pinning.jsonl`) instead of today's 96, and visible
reasoning whatever the arms' mode; the rerun costs about 10 minutes. v0 runs a second time after the variants
(`held_out_step2_v0_end`): the step's A/A and drift check. The report shows both against the first run, paired per
state; the 2026-11-15 run descriptively, or why it could not be read.

**The report** (`learning_rates_report.md`): first the values for the arms' PLACEHOLDERs in a table of file,
setting, value and source, so a value can be copied as it is: A's rate and D's GRPO rate (A's chosen variant), C's and
D's expert-iteration rate (O2's, read from `/workspace/runs/offline_chain/rank_matched.txt` as `offline_arm.py
chosen-rate` reads it; a bold "O2 not ranked yet" with the reason when that file is missing or chose another subset);
a line that C's and D's window, read from `arms/C.toml`, is already set; a "Look first" line when A's chosen variant is
below v0 in success or valid Lean; then every variant minus v0 in valid Lean and
success with 95% intervals and their side ("above v0", "below v0", "within noise"), the rule's choice and reason, a
warning when the chosen variant is below v0, a note when it is within noise of v0; the rounds' sizes (trees, groups,
sequences, steps, trained tokens, KL to v0, clip fraction, trainer and wall time); v0's two runs and the earlier run;
wall-clock durations. Filling the PLACEHOLDERs is the orchestrator's job (node-local edits recorded as in section 4, or
committed and deployed).

**The modes.** `experiments/configs/grpo/followup/modes/visible.toml` and `modes/no_reasoning.toml`, each naming the
search config the arms sample with and their expansions per training search (raising them is that one number, and
`check-mode` warns once expansions plus harvesting exceed the depth cap). The driver takes whatever search config the
mode file names; held-out evaluations use the shared run's loop config, so they read `loop.sampling.search_config`,
the mode's. On the search-efficiency branch `evaluation_run_config` turns the efficiency switches (result cache,
timeout skip, warm spares, the bounded `nlinarith`) off for every evaluation, held-out runs included, so held-out
states stay on today's plain search, comparable with O2's held-out runs and the earlier v0 run. `followup_arm.py` (so `arm_loop.sh`) writes
`sampling.json` beside every loop.toml (search config, expansions, the search config's sha256) and refuses an arm whose
sampling differs from the shared run's: the arms sample in the step's mode or not at all.

**Install and start** (only on the owner's word, at a HOLD of the node's other drivers, with nothing else running):

0. The node's order. Step 2 samples in the arms' final mode and pins it (`mode.recorded.txt`, and `sampling.json`, which
   every arm is checked against), so it runs only once both are settled:
   - O2's gate has run and decided the mode (O2 against run 8: no reasoning if the offline policy beats it, otherwise
     visible), and
   - the search-efficiency branch is merged and deployed: the mode files then name `search/*_sampling.toml` (the
     switches on, as the owner wants in the arms' training sampling). A step 2 sampled with the plain search configs
     would leave every arm refused by the sampling binding, and would have to be sampled again.
   The offline chain must be at HOLD (or STOPPED) for the whole step, and step 2 must be at HOLD before O1's switch.
   A driver of this master stops itself (STOPPED, "the … chain … stands neither at HOLD nor STOPPED") before its first
   server or GPU action while the other has started and is neither (`other_chain_idle` in `chain_helpers.sh`). The
   offline driver's copy installed before this master has no such check, so either reinstall it now, at its HOLD,
   together with step 2's driver and the shared helpers (step 3 below), or give O1's switch only once step 2 is at HOLD,
   by hand. A driver beside an older `chain_helpers.sh` stops at once ("chain_helpers.sh is older than the driver").
1. Deploy a master that holds the driver, keeping the node-local edits (section 4). Never deploy while the driver runs:
   its steps must all use the same code, and a changed search config stops it.
2. Put the mode in place:
   `mkdir -p /workspace/runs/study_chain && cp experiments/configs/grpo/followup/modes/<visible|no_reasoning>.toml /workspace/runs/study_chain/mode.toml`.
   The driver refuses to start without the file. Changing the mode after a first start (even one that stopped before
   sampling) needs `mode.recorded` and `mode.recorded.txt` deleted; once the sampling has begun it must not change.
3. Install the driver as a copy, never editing a running file in place:
   ```bash
   cd /workspace/LLM-Search-Lean-Proofs
   cp deployment/study_chain.sh /workspace/step1_chain_tools/study_chain.sh.new
   cp deployment/chain_helpers.sh /workspace/step1_chain_tools/chain_helpers.sh.new   # sourced from beside the driver
   chmod +x /workspace/step1_chain_tools/study_chain.sh.new
   mv /workspace/step1_chain_tools/chain_helpers.sh.new /workspace/step1_chain_tools/chain_helpers.sh
   mv /workspace/step1_chain_tools/study_chain.sh.new /workspace/step1_chain_tools/study_chain.sh
   # The offline driver's copy beside them, at its HOLD (it then checks step 2 too); skip only if O1's switch waits.
   cp deployment/offline_chain.sh /workspace/step1_chain_tools/offline_chain.sh.new
   chmod +x /workspace/step1_chain_tools/offline_chain.sh.new
   mv /workspace/step1_chain_tools/offline_chain.sh.new /workspace/step1_chain_tools/offline_chain.sh
   cp deployment/study_chain.conf /workspace/step1_chain_tools/study_chain.conf
   cp deployment/study_chain.conf /etc/supervisor/conf.d/study_chain.conf
   supervisorctl reread && supervisorctl update        # autostart: it starts now
   ```
   A later driver change is installed the same way (`.new`, then `mv`): the running bash keeps the old file, and the
   new one takes effect at the next start only. `supervisorctl restart study_chain` mid-step kills the running loop,
   round or held-out run (in S1 it also uses up one of the three `s1_sampling_start` attempts).
4. Watch the first minutes: `tail -f /workspace/runs/study_chain/chain.log`, then the loop's
   `/workspace/runs/followup_shared_sampling/loop.log`. Extend the PC pull to `runs/study_chain`,
   `runs/followup_shared_sampling` (without `trees`) and `runs/followup_configs` (section 7).

**Markers in `/workspace/runs/study_chain/`**: `done_<step>` (step finished), `attempts_<step>` (tries; the 4th
writes STOPPED), `started_<step>` (first attempt's start; with the end in `timings.tsv`), `STOPPED` (text says why),
`HOLD`, `mode.recorded`, `mode.recorded.txt`. Logs: `chain.log`, `mode.err` (the mode check's standard error, which a
refusal quotes), `servers.log`, `slices.log`, `rounds/<label>.log` (and
`rounds/<label>.exit`, the trainer's exit status), `held_out/<name>.log`, `rank_A.txt`, `report.log`.

**Failures.** Any exit but 0 is retried by supervisord; a step's 4th attempt writes STOPPED and exits 0. STOPPED at
once: no or a refused `mode.toml`, a changed one or a changed search config, a health stop of the shared sampling run,
`stop_model.sh` refusing, GPUs still in use after five checks a minute apart (a dead round's torchrun workers live in
sessions of their own: find them with `nvidia-smi`, stop them by PID), servers that kept dying in a held-out run (exit
4), slicing, ranking or report failures. A round whose job died is trained again into a fresh output: the interrupted
`step2_<label>` is renamed `step2_<label>.interrupted_<time>`; a round is done only when its trainer exited 0 and left
`phase.json` and `policy/adapter`, so no half-trained adapter is evaluated (an output holding both whose `phase.json`
reads back whole (`learning_rate_step.py check-round`), left by a trainer that exited non-zero at its teardown or whose
driver died before marking it, is kept, with that attempt's exit status in `chain.log`). A held-out run resumes its
states, also after an exit 0 that dropped some. After fixing a STOPPED cause: rename STOPPED (e.g.
`STOPPED.<reason>`), delete the step's `attempts_<step>` if its tries were used up, `supervisorctl start study_chain`.

**Stopping safely.** Best between steps (after a "step … done" line in `chain.log`): `supervisorctl stop study_chain`.
It stops the current driver's process group: the shared sampling loop it started (SIGTERM saves the loop's state), a
held-out run. A round's torchrun workers may outlive it; check `nvidia-smi --query-gpu=index,memory.used --format=csv`
and `--query-compute-apps=pid,process_name`, stop them by PID. A loop started by an earlier driver instance (before an
exit 1) is not in that group: see `/workspace/runs/followup_shared_sampling/loop.pid` (stop it with
`LOOP_CONFIG=/workspace/runs/followup_configs/followup_shared_sampling/loop.toml deployment/grpo_loop.sh stop`). Servers
keep running (`deployment/stop_model.sh --all` stops them). `supervisorctl start study_chain` continues at the first
step not done. A start after HOLD or STOPPED does nothing.

**Tested only locally** (`tests/rl/test_study_chain_script.py`: the driver against stand-ins for every command, a kill
at each step, each stop, a live loop across its finish, failing starts, dropped held-out states, a start after HOLD;
`tests/rl/test_learning_rate_step.py`, `test_study_commands.py`, `test_learning_rate_report.py`: the report end to end
from files in their real formats). Not yet seen on the node: the real tools' run times and memory,
`nvidia-smi --query-gpu=index,memory.used` reading 1 MiB per idle GPU in this container (the threshold assumes it),
`slice_trees.py --slices 1` on a sampling-only run's trees, held-out runs restarting the policy servers onto each
variant.

### The offline arm's driver (written 2026-11-17, not installed)

`deployment/offline_chain.sh` (supervisord program `offline_chain`, conf `deployment/offline_chain.conf`) runs the
offline arm (DESIGN.md, "The offline arm") unattended. State and logs: `/workspace/runs/offline_chain/` (log
`chain.log`). Commands: `experiments/offline_arm.py` with `experiments/configs/grpo/followup/offline/offline_arm.toml`;
data under `$LEAN_SEARCH_DATA/offline_arm/` (`raw/` holds the two downloaded corpora, about 6.5 GB; they never go to the
PC).

**The owner's order (2026-11-17):** O2 (matched) runs completely, then the driver writes HOLD with the servers
stopped. O1 (pool) runs only on the owner's word and only at the rate O2's ranking chose: the switch is the file
`/workspace/runs/offline_chain/run_pool` (any content), only while step 2's driver (`study_chain`) is at HOLD,
STOPPED or not installed: an offline driver of a master with `other_chain_idle` stops itself otherwise, before its
first server or GPU action; an older installed copy does not, so check by hand. To give it:
`touch /workspace/runs/offline_chain/run_pool`, move
`HOLD` aside (`mv HOLD HOLD.after_matched`), `supervisorctl start offline_chain`.

| Step | What | Markers | Node hours |
|---|---|---|---|
| download | Goedel-LM/SFT_dataset_v2 and Leanabell SFT at phase 2's revisions, `HF_HUB_DISABLE_XET=1`, no token | `done_download` | 0.03 (measured) |
| prepare | exclusions, phase 2's normalization of both corpora (32 processes on the Lean CPUs), the pool's proofs recovered → `proofs.jsonl`, `preparation.json` | `done_prepare` | 0.07 (measured) |
| walk | every proof walked as the search runs blocks, 90 REPLs on the Lean CPUs, resumable → `walks.jsonl`, and `walk.json` (what decided the walks) | `done_walk` | about 3.6 (5.1 proofs/s; GPUs idle) |
| walk_record | `walk` again with the installed checkout: records `walk.json` for walks the detached data steps made (or checks it), walks the ones that raised | `done_walk_record` | minutes |
| build | examples (with the valid prefix of walks that failed at a block), states near a held-out state dropped, validation split, the matched subset → `matched/`, `pool/`, `build.json`, `README.md` (walk statuses per band) | `done_build` | 0.3-0.5 |
| flat_references | each held-out state's reference next step run flattened (16 REPLs) → `flat_references.jsonl` | `done_flat_references` | minutes |
| held_out_config | `held_out_loop.toml`: base.toml in the no-reasoning mode | `done_held_out_config` | - |
| matched | servers stopped; dry run (`dry_run_matched.log`: sizes, peak host memory; stops if 4 ranks would not fit); 5e-5 and 1e-4 trained (`training/<label>.log`; `chain.log` gets the throughput line after step 20); held-out runs of v0 (`offline_v0_no_reasoning`) and both rates; `rank_matched.txt` (both success measures, the choice on the flattened one); probe run `offline_arm_matched`; `matched_against_run8.txt`, `report_matched.md`; HOLD | `done_dry_run_matched`, `done_train_matched_<rate>`, `done_held_out_<name>`, `done_rank_matched`, `done_probe_list_matched`, `done_probe_matched`, `done_report_matched` | training 2 × about 3 (4 epochs of about 21M tokens), held-out 3 × 0.2, probe 4-5 |
| pool | on `run_pool` only: dry run, one training at the chosen rate, its held-out run, probe run `offline_arm_pool`, reports; HOLD | the same with `_pool` | training about 20 at most (about 565M tokens; see "Throughput"), held-out 0.2, probe 4-5 |

O2 to its HOLD: about 16 node hours from the start of the walk, 4 of them with the GPUs idle. O1 on top: about 25 at
most. Measured on 354 walked proofs: about 14 examples, 935 completion and 7,433 prompt tokens per proof.

**Throughput.** The 7.8k tokens/s of expert-iteration round 1 (4 GPUs) is that round's cumulative average: 5.03M tokens
over 645 training seconds in only 78 steps, the compilation and Triton autotuning of the first steps included. Phase 2's
10.8k (2 GPUs, `results/gpu_utilization/`) was measured over steps 6-16, after them, at 32k-token micro-batches on an
earlier node without power caps. Other differences: 4 ranks all-reduce the LoRA gradients every step at about 3 GB/s
(no peer-to-peer path on this node), and the slowest GPU (power-capped at about 262 W) sets the pace of every step. For
the offline examples nothing is wasted that a config could save: packing leaves no padding, the loss projects only the
completion positions onto the vocabulary (`training/sft.CompletionLoss`), the layers are compiled; the 535-token prompts
are 89% of the tokens and must run forward and backward (the LoRA gradients flow through their keys and values). The one
lever, 32k-token micro-batches, doubles the tokens per optimizer step and so changes the recipe; it is left to the
owner. Each training now writes `throughput.json` (over steps 11-20: the median step's rate, which a stall does not
set, and the sustained rate, all tokens over all seconds, which sets wall time; the warm-up seconds, peak GPU memory),
logs steps 1-20 one by one, and the driver copies the line into `chain.log`; the training summary holds both rates
over the whole run. O2's first two trainings wrote `steady_tokens_per_second` instead, the sustained rate. Plan wall
time from the sustained rate only. O2's first training (2026-11-17) ran fast steps at about 12.1k tokens/s after 8
steps stalled 20-45 s among the first 32 (Triton compiling again for row lengths divisible by 16 on each rank); from
commit 7f58dd7 on (not in O2's first trainings) the offline recipe pads packed rows to a multiple of 64
(`packed_length_multiple`, used by `training/sft.train`'s steps and validations only; the expert-iteration, GRPO, DPO
and value trainers ignore it) and lets dynamo compile up to 64 LoRA projection shapes (`compiled_shapes_limit`, set
only in `offline_arm.toml`; every other recipe keeps torch's 8). O1 at about 12k tokens/s sustained: about 13 h.

**The detached data steps of 2026-11-17.** Download, prepare and walk were started before the reviews, from a copy of
branch commit `0d663a4` in `/workspace/offline_arm_code` (`offline_data_steps.sh`, pid in `data_steps.pid`; `lean` and
`.venv` linked to the checkout's). They write the driver's markers (`done_download`, `done_prepare`, `done_walk`,
`started_*`, `timings.tsv`). Nothing restarts them after a container restart (the watchdog checks that the pid lives
and `walk.log` grows; if they died, start them again the same way: the walk resumes). `tests/rl/test_offline_walk_lean.py`
passed on the node from that copy before the walk (5 of 5). Their walks stay valid for the installed driver only if
the walk's sources are unchanged: `git diff 0d663a4 <deployed commit> -- src/lean_search/rl/offline_walk.py
src/lean_search/search/search.py src/lean_search/lean/plans.py src/lean_search/lean/text.py
src/lean_search/lean/hypotheses.py src/lean_search/lean/identifiers.py src/lean_search/lean/repl.py
src/lean_search/policy/prompts.py` must be empty, and `no_reasoning_student_v2.toml`'s search and policy sections
unchanged; else move `walks.jsonl` and `done_walk` aside (the walk runs again, about 3.6 h).

**Install and start** (only on the orchestrator's word, with nothing else running, and only once `done_walk` exists,
`chain.log` says "CPU steps done" and the pid in `data_steps.pid` is gone: the driver refuses with STOPPED while it
lives):

```bash
cd /workspace/LLM-Search-Lean-Proofs                      # a master holding the offline arm, node-local edits kept (section 4)
mkdir -p /workspace/runs/offline_chain
cp deployment/chain_helpers.sh /workspace/step1_chain_tools/chain_helpers.sh.new
cp deployment/offline_chain.sh /workspace/step1_chain_tools/offline_chain.sh.new
chmod +x /workspace/step1_chain_tools/offline_chain.sh.new
mv /workspace/step1_chain_tools/chain_helpers.sh.new /workspace/step1_chain_tools/chain_helpers.sh
mv /workspace/step1_chain_tools/offline_chain.sh.new /workspace/step1_chain_tools/offline_chain.sh
cp deployment/offline_chain.conf /etc/supervisor/conf.d/offline_chain.conf
supervisorctl reread && supervisorctl update                # autostart: it starts now
```

`chain_helpers.sh` is shared by `study_chain.sh` and `offline_chain.sh`: replace it only while both are at HOLD or
STOPPED (a driver sources it at each start).

**Failures and stops** as the step-2 driver's (`attempts_<step>`, the 4th writes STOPPED; `aside` for an interrupted
training output; `gpus_free` before each training). STOPPED at once: the detached data steps alive, no
`chain_helpers.sh` beside the driver, a refused server stop, GPUs that stay in use, a failed or memory-refused dry run,
a failed ranking, probe list, comparison or report, a probe run rejected for wall-clock stops (exit 3) or whose servers
kept dying (exit 4). `walk` exits 1 while more than 1% of all proofs' latest walks raised; the next start walks those
again. `build` refuses walks whose `walk.json` differs from the code and settings it runs with.

**A rejected probe run** (exit 3; not expected without reasoning at 16 expansions and 14,400 s): copy
`offline/probe_evaluation.toml` to one at the doubled cap (28,800 s), write the list with
`offline_arm.py probe-list --subset <s> --rate <chosen> --name offline_arm_<s>_cap28800 --evaluation-config <copy>
--output /workspace/runs/offline_chain/runs_<s>.toml`, run `PROBE_CONCURRENCY=112 deployment/probe_runs.sh <list>`, then
`offline_arm.py report --subset <s> --probe-name offline_arm_<s>_cap28800 > /workspace/runs/offline_chain/report_<s>.md`
(and `probe_compare.py pair --x offline_arm_<s>_cap28800 ... > <s>_against_run8.txt`). The run it is compared with
(run 8) ran at 7,200 s, which the report states as a setting difference. So that a restarted driver continues past the
subset: `touch done_probe_<s> done_report_<s>` in `/workspace/runs/offline_chain/` (`done_probe_list_<s>` exists
already), move STOPPED aside, `supervisorctl start offline_chain`. It then goes on to the HOLD after the matched subset
or the final HOLD.

Smoke points for the first run: `walk_record.log` (no difference refused), `build.json` (walk statuses per band, prefix
and dropped counts, matched completion tokens near 2M), `flat_references.log` (states with flattened references,
failures), `dry_run_matched.log` (shares near 60/30/10%, peak host memory), the throughput line in `chain.log`,
`rank_matched.txt` (both measures), `runs_matched.toml` (the chosen adapter), `report_matched.md` (gate and noise
floor).

### The arms driver (written 2026-11-18, not installed)

`deployment/arms_chain.sh` (supervisord program `arms_chain`, conf `deployment/arms_chain.conf`) runs the closed-loop
arms one after another: A, a smoke test of expert iteration inside the loop, C, D, then HOLD with the servers stopped.
State and logs: `/workspace/runs/arms_chain/` (log `chain.log`). Logic: `experiments/arms_chain.py`
(`src/lean_search/rl/arms_chain.py`). The sampling mode is step 2's file, `/workspace/runs/study_chain/mode.toml`
(`ARMS_CHAIN_MODE`), the one arm A was started with; `followup_arm.py` checks every arm against the shared run's
`sampling.json` as before.

| Step | What | Markers | Node hours |
|---|---|---|---|
| loop A | arm A's loop to `finished.json`. **Adopted**: while `followup_A/loop.pid` names a live `grpo_loop.py` process, or `followup_A.lock` is held (an `arm_loop.sh` start in flight: it holds the run's lock from its start and the detached loop keeps it for its whole life), the driver only polls (every 60 s); it touches no server and starts nothing. A lock held 30 min without a live loop is STOPPED (find the holder with `fuser -v`). A loop found neither running nor ended is started again: `stop_model.sh --all`, up to 1 h for the GPUs to read free (a dead loop's trainer first ends its command), `setsid --wait arm_loop.sh --kind arm --mode <mode> arms/A.toml` (arm_loop resumes it; its own session, so stopping the driver never stops a loop; the checkout's commit goes to `loops/A.revisions`) | `done_loop_A`, `attempts_loop_A_start` (3 tries, then STOPPED) | about 19 (A started about 07:15 UTC 2026-11-18) |
| adapters A | `arms_chain.py adapters`: the policy and value adapters of phase 8 and of the final checkpoint (phase 16; a health-stopped arm: its last good version), copied from `models/versions.jsonl`'s paths to `adapters/A/phase_00kk/{policy,value}/` with `sources.json` and `manifest.sha256` (sha256sum's format), written beside and renamed into place | `done_adapters_A` | minutes |
| probe A | `probe-list` → `probe/runs_A.toml`: `arm_A_phase16_run1`, the final policy with its own final value adapter (`value_version` = the version that first published it), `step1/probe_evaluation_ordered.toml` (anchors' settings, plain search, longest expected search first: the order check passed); `PROBE_CONCURRENCY=112 probe_runs.sh --foreground`; exit 3 or 4 STOPPED, others retried (it resumes) | `done_probe_list_A`, `done_probe_A` | 2-3.5 |
| compare A | `probe_compare.py pair` against the anchors (runs 1 and 2 pooled), run 7 (v35, final value; descriptive) and every other arm with a probe run done → `compare/<X>_against_<Y>.txt`; a failure is logged and the chain goes on | `done_compare_A` | minutes |
| report A | `report_A.md`: the loop's end, hours, the checkouts the driver started it from, a table per phase (trees, solved, tokens, held-out valid and success, alerts), the probe result, the comparison files (provisional: one run per arm), the adapters | `done_report_A` | - |
| smoke | below | `done_smoke_overlays`, `done_loop_smoke_C`, `done_loop_smoke_D`, `done_smoke` | about 2-2.5 |
| C, D | as A (D also compared with A and C) | `done_loop_C` ... | about 19 + 2-3.5 each |
| HOLD | `stop_model.sh --all`, then HOLD | `HOLD` | |

All told from now: A's remaining loop, then about 2-3.5 h (A's probe) + 2-2.5 h (smoke) + 2 × 21-23 h (C, D), so about
49-51 hours after arm A finishes; the idle gaps between steps are minutes (the copy, the comparisons).

**The smoke test** (before arm C's real run; reviews AS and AT, "Smoke on the node"; BC S3, BD S1-S3). `smoke-overlays`
derives `smoke/overlays/C.toml` and `D.toml` from `arms/C.toml` and `arms/D.toml` by code (`rl/arms_chain.smoke_overlay`,
`--kind smoke`: `study_configs.SMOKE_SETTINGS`): the name `followup_smoke_<arm>`, 6M generated tokens per phase (half an
arm's phase: at 2M the round would likely fall under the loop's floor of 100 examples), one phase, the value model
trained at that phase (`value_every_phases` 1), and D's round interval brought from 4 to 1. D's one phase so trains
GRPO, the value model and a round in one trainer process, with both merges in /dev/shm: the heaviest pause C (every
even phase) and D (every fourth) will meet. `tests/rl/test_arms_chain.py` pins that nothing else differs. Each smoke
loop starts with the servers stopped, samples every 5 s each GPU's `nvidia-smi` used memory (the allocator's reserved
memory included) and `/dev/shm`'s use with the loop's stage (`smoke/readings_<arm>.tsv`). Once D's loop has been
publishing phase 1 for 30 s, the driver kills it by PID (SIGKILL, after checking the PID's command line names
`grpo_loop.py` and `followup_configs/followup_smoke_D/loop.toml`; `smoke/kill_D.json`) and starts it again at once (no
attempt counted; `smoke/restarted_D`). With swap = "restart" the 30 s lands while the servers restart onto the
handed-off merges, before the version is recorded (not review AS's M1 point, the durable write itself); the driver
stops the servers before the restart, while a real crash would leave them up. Then `smoke-check` writes
`smoke_report.md`; arm C starts only if every gate passed, else STOPPED "the smoke test failed (...)".

| Gate (each smoke run) | Passes when |
|---|---|
| finished | `finished.json` with last phase 1, no `health_stop.json` |
| one version for the phase | exactly one version with trigger "phase 1" |
| value model trained in the phase | version 1's value adapter is not version 0's |
| round trained | exactly one `expert_iteration` line for phase 1: not skipped, optimizer steps > 0, LoRA change > 0, Lean and math replay examples > 0; the detail names the examples and solved trees, and a skip's reason ("skipped: too few examples ...") |
| round published | version 1's policy adapter is `.../expert_iteration/adapter` |
| GRPO then the round (D) | exactly one `grpo` line for phase 1 with steps > 0; the phase's LoRA change ≥ the round's |
| in-loop build | `<run>/expert_iteration/phase_0001/summary.json` exists |
| no out-of-memory | no "out of memory"/`OutOfMemoryError` in `training/trainer.log` |
| GPU memory before the wake | the last "GPU memory before the wake" line: free ≥ the servers' shares on every GPU |
| /dev/shm | peak use ≤ 90% of its size |
| killed while publishing (D) | the kill record says phase 1, stage publishing |
| restarted (D) | two loop starts in `loop.log` |
| nothing trained or built again (D) | `phase.json` and the build's `summary.json` older than the kill |
| one phase record and one version (D) | one `phases.jsonl` line and one version for phase 1 |

Readings only (in the report, never failing): every GPU's nvidia-smi peak in the training stage (the caching allocator
may reserve nearly a whole card without failing, and nothing calibrates a limit yet; the gates for real trouble are
"no out-of-memory" and "GPU memory before the wake"); the round's training seconds, peak allocated memory and tokens;
the build's seconds; the trainer's allocated/reserved memory after each stage (`phase.json`); compiled graphs and the
count of dynamo "recompile_limit" warnings (arm A's 2e-5 phase 1 hit the limit of 8 on all four ranks, so this is not
a gate); each phase's durations. Not covered, and listed in the report: the 4-phase window's build and round (watch
arm C's phase 4); a kill during the build and of one trainer rank during the round (AS 5); a stop during a build (AT 6);
the in-loop round against the hand-run `train` (AS 2); exactly one policy merge in the handoff (AT 1, only implied).

**After a health stop** (an arm's `health_stop.json`: its first held-out valid-Lean collapse). The arm is never started
again. The driver waits for the loop to exit and writes `health_report_<arm>.md` (the stop, the last four phases'
table, their alerts and policy updates; "evaluate is not possible" when the last good version is 0). Then the switch
file `/workspace/runs/arms_chain/on_health_stop` decides (read at each health stop; anything else STOPs):

- `wait`, or no file (the default): the servers are stopped and the chain writes STOPPED until the owner's word.
- `continue`: the next arm runs while the owner decides; at the end, before HOLD, the chain stops the servers and
  writes STOPPED "… waits for the owner's word" if the word is still missing, and after it evaluates the stopped arm
  (compared with every other arm's probe run).

The owner's word, given as a file:

```bash
echo skip > /workspace/runs/arms_chain/word_C        # no probe run of C; its adapters are copied
echo evaluate > /workspace/runs/arms_chain/word_C    # a probe run of C's last good version with its value model
mv /workspace/runs/arms_chain/STOPPED /workspace/runs/arms_chain/STOPPED.health_C
supervisorctl start arms_chain
```

`evaluate` with version 0 as the last good one stops again (nothing trained to evaluate): write `skip`.

**A bug found instead: fix it and rerun the arm** (the rules' third outcome). With the driver at STOPPED (or stopped:
`supervisorctl stop arms_chain`), and the arm's loop gone:

```bash
S=/workspace/runs/arms_chain; R=/workspace/runs; C=/workspace/checkpoints; X=C; T=$(date -u +%Y%m%dT%H%M%SZ)
mv $R/followup_$X $R/followup_$X.bug_$T
mv $R/followup_configs/followup_$X $R/followup_configs/followup_$X.bug_$T
for d in $C/followup_${X}_phase_* $C/followup_$X; do mv $d $d.bug_$T; done
mkdir -p $S/rerun_$T/probe $S/rerun_$T/adapters $S/rerun_$T/loops
for f in done_loop_$X started_loop_$X attempts_loop_${X}_start word_$X done_health_report_$X health_report_$X.md \
    health_report_$X.log started_adapters_$X done_adapters_$X adapters_$X.log adapters/$X done_probe_list_$X \
    started_probe_$X attempts_probe_$X done_probe_$X done_compare_$X done_report_$X report_$X.md report_$X.log \
    probe/runs_$X.toml pause_$X loops/$X.revisions loops/$X.log; do [[ -e $S/$f ]] && mv $S/$f $S/rerun_$T/$f; done
[[ -e $R/probe_evaluations/probe_arm_${X}_phase16_run1 ]] && mv $R/probe_evaluations/probe_arm_${X}_phase16_run1{,.bug_$T}
```

Check `ls $S | grep "_$X\b"` (the smoke runs' markers, `*_smoke_C`, stay). Deploy the fix (section 4) and start the
driver: it starts arm X afresh and evaluates it. Earlier arms hit by the same bug are rerun the same way; a probe run
of a stopped arm at another phase has another name (`probe/runs_X.toml` says which).

**The order and holds** (owner, 2026-11-18). `$state/order` holds the steps' order as words, on one line or several:
`A`, `C`, `D` and `smoke`, each at most once, `smoke` before `C` and `D` (unless `done_smoke` exists); without the file
the order is `A smoke C D`. It is read at each start; anything else STOPs the chain before it touches anything. Steps
done keep their markers and are skipped, so the order may change between starts. A step left out is not run; the
final HOLD names the order it finished. `$state/hold_<arm>` holds an arm back: when the order reaches it, the chain
stops the servers and writes HOLD "waiting for: <arm>"; the arm is not started, adopted, resumed or evaluated, its run
directory and markers are not touched (an arm held while its loop runs STOPs the chain), and the steps after it in
the order wait too (put an arm before the held one to run it meanwhile). To go on: remove `hold_<arm>`, move HOLD
aside (`mv HOLD HOLD.waiting_for_<arm>`), `supervisorctl start arms_chain`. A hold removed while the chain still
works through earlier steps simply never stops it.

**Today's sequence** (arm A stopped at phase 7 for the bare-`have` reward problem, 14:39 UTC 2026-11-18; `pause_A`
present, the chain STOPPED "A is paused"): first install the driver of this change (copy, `.new`, `mv`; it is
read at the next start), then

```bash
S=/workspace/runs/arms_chain
echo "smoke C A D" > $S/order
touch $S/hold_A
mv $S/STOPPED $S/STOPPED.A_paused_reward_fix
supervisorctl start arms_chain
```

The chain runs the smoke test (about 2-2.5 h), then arm C (about 21-23 h with its probe run), then HOLD "waiting for:
A". A's old run (`followup_A`, phase 7) is left as it is. Once the reward fix is merged: at that HOLD (never while C's
loop runs: its jobs read the checkout), deploy master (section 4), run the rerun path below for X=A (it moves
`followup_A`, its configs, checkpoints, markers and `pause_A` aside), remove `hold_A`, move HOLD aside and start the
chain: arm A starts from v0 through `arm_loop.sh`, then D runs. Each arm is compared with every other arm whose probe
run is done (A with C; D with C and A). Note that the smoke test and C then ran on the code before the fix, A and D
on the code after it; `loops/<arm>.revisions` and each report record which.

**Stopping an arm by hand** (BC S2). The driver starts a loop again within a minute when it finds it neither running
nor ended, so first tell it not to: `touch /workspace/runs/arms_chain/pause_<X>` (X = A, C, D, or `smoke_C`,
`smoke_D`), then `LOOP_CONFIG=/workspace/runs/followup_configs/followup_<X>/loop.toml deployment/grpo_loop.sh stop`
(SIGTERM by its PID, then the servers). The driver then writes STOPPED "<X> is paused". To resume: delete
`pause_<X>`, move STOPPED aside, `supervisorctl start arms_chain` (arm_loop.sh resumes the loop).

**Install** (only on the orchestrator's word; arm A may keep running, the driver adopts it):

0. Deploy a master holding the driver (section 4's stash, fast-forward, pop). The diff from `0e04599` adds files and
   changes only `study_configs.py` (a new overlay kind, additive), `followup_arm.py` (the kind), `arm_loop.sh` (the
   run lock; read only when a loop starts), the three drivers and `chain_helpers.sh`: nothing the running loop or its
   held-out jobs import, and arm A's configs are written the same (a restart of A through arm_loop.sh finds them
   identical). Check with `git diff --stat 0e04599 <new>`. What remains while A runs: jobs A's loop starts during the
   stash, fast-forward, pop window (a held-out run, a trainer restart) read the checkout then; the diff touches nothing
   they import, but deploy between pauses (in the sampling stage, `loop_state.json`) all the same.
1. Install the copies (the step-2 and offline drivers are at HOLD; their new copies also treat the arms chain as the
   other chain):
   ```bash
   cd /workspace/LLM-Search-Lean-Proofs
   T=/workspace/step1_chain_tools
   mkdir -p /workspace/runs/arms_chain
   for f in chain_helpers.sh arms_chain.sh study_chain.sh offline_chain.sh; do cp deployment/$f $T/$f.new; done
   chmod +x $T/arms_chain.sh.new $T/study_chain.sh.new $T/offline_chain.sh.new
   for f in chain_helpers.sh study_chain.sh offline_chain.sh arms_chain.sh; do mv $T/$f.new $T/$f; done
   cp deployment/arms_chain.conf $T/arms_chain.conf
   cp deployment/arms_chain.conf /etc/supervisor/conf.d/arms_chain.conf
   supervisorctl reread && supervisorctl update        # autostart: it starts now
   ```
2. Decide the health-stop switch with the owner: `echo continue > /workspace/runs/arms_chain/on_health_stop`, or
   leave it absent (wait). Check `tail /workspace/runs/arms_chain/chain.log`: "loop_A_start" must NOT appear while A
   runs; the line "A: its loop runs or a start of it is in flight (loop.pid ...): adopted" must. If A is not running at install time (it died), the driver starts it
   again through arm_loop.sh, which resumes it.
3. Extend the PC pull (section 7) to `runs/arms_chain` and `runs/followup_*` (without `trees`, `weights`, `merges`),
   and let it call `deployment/pull_arm_adapters.sh` after each pull (below).

A later driver change goes in the same way (`.new`, then `mv`). `supervisorctl stop|restart arms_chain` stops the
driver and a probe run in flight (resumed at the next start); the arms' loops (and an `arm_loop.sh` start in flight)
run in sessions of their own and keep running, and the next start adopts them. To stop an arm's loop itself, see
"Stopping an arm by hand" above.

**The other drivers** (`study_chain.sh`, `offline_chain.sh`) also check, before their first server or GPU action and
whatever the arms chain's markers say (its loops outlive it, so a STOPPED arms chain may still have one running), that
no loop of another run lives (`<run>/loop.pid`) and no start of one is in flight (`<run>.lock`): `no_other_loop` in
`chain_helpers.sh`. The arms driver checks the same for every run but its own.

**Stops** (STOPPED, its text says why; fix, rename it, delete the step's `attempts_*` if used up, start again): no mode
file; another chain started and neither at HOLD nor STOPPED; another run's loop alive or start in flight; a run lock
held 30 min without a loop; a paused arm found not running; a loop start failing 3 times; a loop not exiting 10 min
after it ended (3 times); GPUs held after the servers stopped and an hour's wait; a health stop with `wait` (above), or
at the end with `continue` and no word; an unknown `on_health_stop` or `word_<arm>`; a failed smoke test or smoke
health stop; a rejected probe run (exit 3: repeat it at a doubled cap under a new name, mark `done_probe_<X>` by hand)
or dying servers (exit 4); the adapters copy, probe list or compare plan failing.

**The PC's adapter pull.** The adapters (about 0.5 GB policy and 0.26 GB value each, so about 1.5 GB per arm) are not
in the 10-minute tar (it leaves out `*.safetensors`; re-sending them every pull would cost far more). The tar brings
`runs/arms_chain/adapters/<arm>/manifest.sha256` as soon as the driver wrote it; then

```bash
NODE_SSH="ssh -i ~/.ssh/vast-ssh -p 21232 -o ConnectTimeout=12 -o BatchMode=yes root@50.173.30.254" \
    bash deployment/pull_arm_adapters.sh node_backup/2026-11-15/live node_backup/2026-11-15/adapters
```

fetches each arm once (tar over SSH into a partial directory, `sha256sum -c` against the manifest, renamed to
`adapters/<arm>/` with a `verified` file); an arm already verified is skipped, so the pull loop may call it every
cycle. LoRA adapters only, never base models or merged weights.

**Smoke points for the first run:** the adoption line; at A's end `adapters_A.log` and `adapters/A/sources.json` (four
adapters, phases 8 and 16), `probe/runs_A.toml`, the probe's start order line; the smoke runs' `loop.log` (the round
line "built in N s", "Expert-iteration update of phase 1"), `smoke/readings_*.tsv` growing, the kill line in
`chain.log` and D's second "Loop followup_smoke_D: version" line, `smoke_report.md`. Not seen yet anywhere: the kill
landing inside D's publishing (a 30 s delay into a stage A's phase 1 held for 135-250 s; if it is missed the smoke
test fails with "no kill record", and `smoke_report.md` repeats this recipe; to repeat D's smoke run, move `runs/followup_smoke_D`, its
`followup_configs/followup_smoke_D` and `checkpoints/followup_smoke_D*` aside, delete `done_loop_smoke_D`,
`attempts_loop_smoke_D_start`, `smoke/kill_D.json`, `smoke/restarted_D` and `smoke/readings_D.tsv`, then rename STOPPED
and start the driver).

## 4. Node-local edits and deploying master

Edits to tracked files: uncommitted on the node and never pushed. Copies and diffs are in
`/workspace/runs/step1_chain/edits/`, pulled to the PC.

| File (`experiments/configs/grpo/followup/step1/`) | Edit | Why |
|---|---|---|
| `token_capped_visible.toml`, `token_capped_no_reasoning.toml` | `max_generated_tokens = "PLACEHOLDER T…"` → `max_generated_tokens = 26804` | T = 16 × 1,675 tokens per expansion from both anchors (`followup_step1.py token-budget`; T64 = 107,216) |
| `value_free_completion.toml` | placeholder entry → `step_log_probability = "completion"`, `automation_log_probability = -56.4`, `calibrated = true` | `followup_step1.py automation-constant` on the calibration run (3,491 steps) |
| `value_free_block_sum.toml` | → `block_sum`, `-5.35`, calibrated | same |
| `value_free_block_mean.toml` | → `block_mean`, `-0.142`, calibrated | same |
| `runs_value_free_full.toml` | `config = …value_free_completion.toml` | the pilots' winner (71 of 200) |
| `runs_old_value.toml` | `value = "/workspace/checkpoints/hf_value_latest/adapter"` | run 5 |

Untracked run lists written on the node (same folder):

| File | Contents |
|---|---|
| `runs_value_free_full_block_sum.toml` | `step1_run6_v0_no_value_block_sum` |
| `runs_v35_value_v0.toml` | `step1_run8_v35_value_v0` |
| `runs_v35_value_final.toml` | `step1_run7_v35_value_final` |
| `runs_reasoning_e1_pilot.toml` | the pilot entry of master's `runs_reasoning.toml` |
| `runs_reasoning_e2.toml` | runs 3 and 4 of it in file order (superseded, unused) |
| `runs_reasoning_e2_ordered.toml` | runs 3 and 4 of master 9834972's `runs_reasoning.toml`, both on `token_capped_evaluation_ordered.toml`: what step e2 runs |

The edits are in place as of 9a594b1, and the driver re-applies them across the 9834972 deploy. Copies of every list are
in `/workspace/runs/step1_chain/edits/`.

The tools used for the edits are in `/workspace/step1_chain_tools/`: `fill_placeholder.py`, `fill_run_lists.sh` and
`make_v35_lists.sh`.

**Deploying a newer master while keeping these** (what the driver's `deploy_ab78ace` step does):

```bash
cd /workspace/LLM-Search-Lean-Proofs
E=/workspace/runs/step1_chain/edits
git diff > $E/before_<commit>.diff; git status --short > $E/before_<commit>.status
git stash push -m "node-local edits before <commit>"
git fetch origin master && git merge --ff-only <commit>
git stash pop                      # a conflict here: stop, look, re-apply with fill_placeholder.py from the copies
git diff > $E/after_<commit>.diff; git status --short > $E/after_<commit>.status
diff <(grep -E '^[-+][^-+]' $E/before_<commit>.diff) <(grep -E '^[-+][^-+]' $E/after_<commit>.diff)   # must be empty
grep -x 'max_generated_tokens = 26804' experiments/configs/grpo/followup/step1/token_capped_*.toml
```

- Untracked files are not stashed and survive the merge.
- `uv sync --locked --extra ml` is needed only if `uv.lock` changed: `git diff <old> <new> -- uv.lock`.
- Do not deploy while a run is running: both runs of a comparison must use the same code.

## 5. Running jobs by hand

Always start with `cd /workspace/LLM-Search-Lean-Proofs && source deployment/environment.sh`. The node file supplies
the pinning, so do not set `BACKGROUND_CPUS`: setting both it and the list is refused.

- **Servers.**
  - `deployment/stop_model.sh --all` (or names) is the ordinary stop. It takes about 1-16 s and leaves GPU memory at
    1 MiB with no zombies.
  - `LOOP_CONFIG=experiments/configs/grpo/followup/base.toml deployment/grpo_loop.sh servers` starts every server that
    does not answer, on version 0 of `grpo_followup_base`: policy from `/workspace/checkpoints/grpo_followup_base/weights/v0000/policy`,
    value from `…/v0000/value`. All GPUs run in parallel, a GPU's two servers one after the other.
  - Start time: about 140-150 s for all 8 with warm compile caches; value servers alone 55-60 s; policy 4B merges about
    200 s; cold (first time on the node) about 8 min.
  - `serve_model.sh` pins each server to `SERVER_CPU_LIST` at its own niceness and writes `<name>.cpus`
    (`0-47,96-143 0`).
  - Ports: policy 8100-8103, value 8200-8203. `curl -s localhost:8100/v1/models` shows the served root (the weights
    directory).
- **Pid check.** All 8 must show trusted = pid = pgid, and every member must read `member=yes`. The 4th argument
  `"$p"` (the group) is required since the resource-tracker fix:

```bash
source deployment/environment.sh; source deployment/server_pid.sh; for f in "$LEAN_SEARCH_RUNS"/servers/*.pid; do n=$(basename "$f" .pid); p=$(cat "$f"); echo "$n pid=$p pgid=$(ps -o pgid= -p "$p" | tr -d ' ') trusted=$(trusted_server_pid "$f" "$n" || echo NO)"; for m in $(live_group_members "$p"); do echo "  $m $(tr '\0' ' ' < /proc/$m/cmdline | cut -c1-80) member=$(server_member "$m" "${f%.pid}.members" "$(stat -c %Y "$f")" "$p" && echo yes || echo NO)"; done; done
```

- **Probe runs** (`experiments/probe_evaluate.py` through the launcher):
  - `PROBE_CONCURRENCY=112 deployment/probe_runs.sh [--foreground] <run list.toml> …`.
  - It checks pinning, the servers and the lists, and starts the servers that do not answer. Each run merges its
    adapters, and with `[serving] swap = "restart"` restarts only the servers whose weights differ. Servers that already
    hold byte-identical weights are skipped ("already held by").
  - Then it searches, writes `$LEAN_SEARCH_RUNS/<output>/probe_<name>/` and a ledger line in `<output>/ledger.tsv`.
  - Detached mode writes `$LEAN_SEARCH_RUNS/probe_runs/<lists>.log` and `.pid`.
  - Exit codes:
    - 3: rejected (≥ 1% wall-clock stops; rerun under a new name with the cap doubled, and the runs it is compared with
      at that cap).
    - 4: servers kept dying (look before rerunning).
    - Other non-zero: rerun the same command to resume.
  - Probe concurrency 112, held-out concurrency 56, sampling concurrency 112: these are fixed for the study on this node.
- **Comparing runs:** `python experiments/probe_compare.py`:
  - `pair --x <runs> --x-label L --y <runs> --y-label M [--across-search-modes | --descriptive-across-settings]`
  - `against …`
  - `load <runs>`
  - A bare run name resolves under `probe_evaluations/`. Calibration runs are under `calibration_evaluations/`; pass
    the full path.
- **Step-1 helpers:** `python experiments/followup_step1.py token-budget <anchor dirs>` and
  `HF_HUB_OFFLINE=1 python experiments/followup_step1.py automation-constant <calibration run dir>`.
- **Held-out states:** `deployment/background.sh python experiments/held_out_evaluate.py --name <n> --arm <a> --phase <k>
  --policy-adapter <path>`.
  - Concurrency 56 comes from the loop config, and the tool refuses to run unpinned.
  - Done once on this node for v0 (name `v0`): 34.0% success, 58.7% valid Lean, 444 s. The output is
    `/workspace/runs/held_out_evaluations/held_out_v0/`.
- **Shared sampling and arms:**
  - `deployment/arm_loop.sh --kind "shared sampling" --mode <mode.toml> experiments/configs/grpo/followup/shared_sampling.toml`,
    or `deployment/arm_loop.sh --mode <mode.toml> experiments/configs/grpo/followup/arms/<A>.toml`. `--mode` is
    required: the sampling mode (`followup/modes/`; the study driver's copy is `/workspace/runs/study_chain/mode.toml`),
    the same file for the shared sampling run and every arm.
  - It writes configs via `experiments/followup_arm.py` into `$LEAN_SEARCH_RUNS/followup_configs/<name>/`, runs `init`
    once, starts the servers and the loop detached. `--status` shows the state.
  - Not run yet on this node. See the headers of `deployment/arm_loop.sh` and `experiments/followup_arm.py`, and
    DESIGN.md "Follow-up study: controlled arms" ("Arms", "Compute matching", "Step 2", "Step 3", "Automatic rules").
- **Slices:** `python experiments/slice_trees.py --trees <run>/trees --slices 4 --output <run>/slices`. Not run yet.
- **Learning-rate rounds:**
  - `experiments/grpo_phase.py --config <phase.toml> --trees <slice dir> --part policy --run-name … --lean-replay …
    --math-replay …` (under `torchrun` for 4 GPUs).
  - Expert iteration: `experiments/grpo_expert_iteration.py` (`count`, `build` with `[data] tree_directories`, `train`).
  - Then `experiments/rank_learning_rates.py --v0 v0 --variant <label> <rate> <held-out name> …`, without gate runs.
  - None of these has been run on this node; the study driver (section 3, "The study driver") runs them all.

## 6. Results

Run directories are under `/workspace/runs/probe_evaluations/` unless noted. Each holds `results.jsonl`, `run.json`,
`checkpoint.json`, `sessions.jsonl`, `pinning.jsonl`, `config.toml`, `progress.json` and `trees/`; trees are not pulled.

| Run | Policy | Value | Search | Statements | Solved | Wall stops | Hours | Accepted |
|---|---|---|---|---|---|---|---|---|
| step1_run1_v0_value_v0 (anchor) | v0 | v0 | visible, 16 exp. | 2,000 | 713 (35.65%) | 1 | 3.17 | yes |
| step1_run2_v0_value_v0 (anchor) | v0 | v0 | same | 2,000 | 716 (35.80%) | 0 | 3.58 | yes |
| `calibration_evaluations/probe_calibration_v0_value_v0` | v0 | v0 | same | 200 calibration | 65 | 0 | 1.21 | yes |
| step1_run6_pilot_completion | v0 | none | value-free, completion −56.4 | first 200 | 71 | 0 | 1.09 | yes |
| step1_run6_pilot_block_sum | v0 | none | block_sum −5.35 | first 200 | 68 | 0 | 0.74 | yes |
| step1_run6_pilot_block_mean | v0 | none | block_mean −0.142 | first 200 | 65 | 0 | 0.85 | yes |
| step1_run4_pilot_no_reasoning_T | v0 | v0 | no reasoning, T, 7,200 s cap | first 200 | 76 | 2 (1.00%) | 2.13 | **no** (rejected) |
| step1_run6_v0_no_value | v0 | none | completion | 2,000 | 642 (32.10%) | 0 | 3.08 | yes |
| step1_run5_v0_value_final | v0 | final (v35's value) | visible | 2,000 | 875 (43.75%) | 0 | 2.82 | yes |
| step1_run6_v0_no_value_block_sum | v0 | none | block_sum | 2,000 | 633 (31.65%) | 0 | 2.33 | yes |
| step1_run8_v35_value_v0 | v35 | v0 | visible | 2,000 | 1,083 (54.15%) | 3 | 3.57 | yes |
| step1_run7_v35_value_final | v35 | final | visible | 2,000 | 1,236 (61.80%) | 1 | 3.31 | yes |
| step1_run4_pilot_no_reasoning_T_cap14400 | v0 | v0 | no reasoning, T, 14,400 s cap | first 200 | running since 17:55 on 2026-11-16 | | | |

Other places:

| What | Where |
|---|---|
| Ledgers | `probe_evaluations/ledger.tsv`, `calibration_evaluations/ledger.tsv` |
| Launcher logs | `probe_runs/` |
| Held-out v0 | `held_out_evaluations/held_out_v0/` |
| Throughput test (2026-11-15) | `throughput/` (`measurements/analysis.jsonl`, `chain3.log`, samplers, `probe_tp_*`) |
| Backstop replay (300 timed-out steps plus controls alone) | `/workspace/runs/backstop_replay/` (`summary.md`, `details.txt`, `records.jsonl`) |
| Server logs | `/workspace/runs/servers/*.log`, older starts as `<name>.<time>.log` |
| Setup logs | `/workspace/setup_logs/` |

All of these are pulled to the PC (section 7), into `C:\Projects\Lean-Proofs\node_backup\2026-11-15\live\` with the
same relative paths. Trees and weights are not pulled.

Merged weights are in `/workspace/checkpoints/probe_evaluations/weights/<digest>/`:
- `f5c7509f…` is v0's policy.
- `f3156cea…` is value v0.
- `859c6f6a…` is the final value model.
- `0dfbe0c5…` is v35's policy.
- The servers' version 0 is in `grpo_followup_base/weights/v0000/`.

## 7. The PC side

- **Pull loop:** `C:\Projects\Lean-Proofs\node_backup\2026-11-15\pull_results.sh`, started detached from Git Bash. Its
  pid is in `C:\Projects\Lean-Proofs\node_backup\2026-11-15\pull_results.pid` (Git Bash pid; restarted 2026-11-17 12:06
  local time with the extended list below).
  - Every 10 minutes it tars over SSH, excluding `trees`, `*.json.gz`, `weights`, `merges`, `*.safetensors`, `*.bin`,
    `*.pt`:
    - `runs/step1_chain`, `runs/probe_evaluations`, `runs/calibration_evaluations`, `runs/probe_runs`,
      `runs/held_out_evaluations`, `runs/throughput`, `runs/backstop_replay`;
    - `runs/offline_chain`, `runs/lean_overhead`, `runs/study_chain` (added 2026-11-17);
    - `runs/servers/*.log`, `*.cpus`, `*.members`;
    - `setup_logs`, `node_environment.sh` and `step1_chain_tools`.
  - It unpacks into `…\2026-11-15\live\` and writes `live\last_pull.txt`.
  - Check it is alive: `ps -p $(cat pull_results.pid)` in Git Bash, and `cat …/live/last_pull.txt` (under 10 minutes
    old).
  - Stop it with `kill $(cat pull_results.pid)` (Git Bash), by that PID only.
  - Changing the list: write the new script to a separate file, check it with `bash -n` AND that it is not empty, then
    move it over, kill the old loop by PID and start a new one (bash reads a running script lazily).
  - Restart it: `cd /c/Projects/Lean-Proofs/node_backup/2026-11-15 && nohup bash pull_results.sh > pull_results.out 2>&1
    < /dev/null & echo $! > pull_results.pid`. It survives the shell that started it.
  - **When arms start**, add `runs/followup_*` (without `trees`, `weights` or `merges`; keep `loop.log`, `phases.jsonl`,
    `pinning.jsonl`, health records, `index.jsonl`, `metrics/`), `runs/followup_configs` and `runs/study_chain` to the
    tar list. Also pull each arm's retained policy and value adapters of phases 8 and 16 into
    `C:\Projects\Lean-Proofs\node_backup\2026-11-15\adapters\<arm>\` (LoRA adapters, a few hundred MB each).
- **`node_backup` folders:**

| Folder | Contents |
|---|---|
| `node_backup\2026-11-15\` | this node: `live\` (the pulls), `pull_results.*` |
| `node_backup\2026-11-14\` | the abandoned previous node: `probe_v2\` (the drawn probe set, the original), `live\`, anchor run 1 of that node |
| `node_backup\2026-11-01\hf_dataset\` | parts of the published dataset (`search_trees/index.jsonl` among them) |
| `node_backup\2026-10-15\` | old archives (`increment_2140.tar.zst` holds the held-out states file) |

- **Scripts on the PC:** the drivers and tools as written are in
  `C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\node2\chain\`.
  That is a session scratchpad and may disappear; the node copies are in `/workspace/step1_chain_tools/`, also pulled
  to `live\step1_chain_tools\`.

## 8. Known behaviours and pitfalls

- **Search efficiency switches** (from step 2 on, the arms' training sampling only; `src/lean_search/rl/README.md`,
  "Search efficiency switches"): the sampling pool keeps 8 spare REPL processes (`[lean] spare_processes`) beside its
  112, started on the same Lean CPUs (the background list) as the pool's own. Each holds about 0.24 GiB private memory
  (3.5 GiB resident, mostly the shared .olean pages), so 8 add about 2 GiB to the host-memory budget, counted with the
  other Lean processes; the training pause does not stop them. The loop's host-memory log lines name them ("spare REPL
  processes k of 8 ready; n replacements took one, m found none ready"); many misses mean kills come in bursts
  faster than about 8 per 6 s. Probe runs and held-out evaluations keep no spares and no cache or skip.

- **Downloads:** the Hugging Face xet backend stalled (files stuck at 0 bytes). With `HF_HUB_DISABLE_XET=1` downloads
  ran at about 30 MB/s. No token is needed; everything is public.
- **Cold starts:** the first 4B policy server start takes about 5 min (torch.compile caches in `~/.cache/vllm`, not
  persistent). Later restarts take about 60 s for value servers and about 200 s for policy servers.
- **The idle tail:** every probe run ends with 20-40 minutes in which the last few searches run with the GPUs mostly
  idle; the last statement can take 25 minutes alone. A healthy tail still adds a line to `chain.log` every few minutes
  and has `repl` processes using CPU. A stall shows no new `[k/2000]` line for much longer than the run's slowest
  searches (up to about 30 min), and the search processes use no CPU.
- **REPL crashes:** `ring_nf` on huge powers (`sqrt_17_problem`: `(4+√17)^2021…`) dies on memory (`std::bad_alloc` or GMP
  "Cannot allocate memory" at the 6 GiB data limit). On long Finset sums (`lean_workbook_23568'`) it dies of stack
  overflow (`Mathlib.Tactic.Ring.evalAdd` frames). They are counted as REPL failures; heartbeats do not stop them.
- **The 60 s tactic backstop is wall-clock:** about 3,000 timeouts in about 370 statements per v0 run.
  - The replay (`runs/backstop_replay/`) showed that none of the 300 sampled timed-out steps succeeds even alone with
    300 s, and that 235 of 236 reach the same prefix.
  - Contention alone pushed 31% of them past 60 s: they ran 1.5-1.7 times longer under load than alone.
  - Most slow steps are `nlinarith`. They end with "linarith failed" after more than 60 s of CPU without using up 50k
    heartbeats.
  - The owner decided the backstop stays wall-clock.
- **GPU power caps:** the host caps power below 350 W and moves the caps: GPU 0 about 295-316 W, GPU 1 350 W, GPU 2
  261-289 W, GPU 3 327-335 W. GPU 2 is the slowest. `power_limits.txt` records them every minute.
- **Throttling:** none so far. A throttled node would show `nr_throttled` rising in `/sys/fs/cgroup/cpu/cpu.stat`. With
  Lean on 96 CPUs plus servers at about 4 cores, CPU use peaked at about 74 cores of the 105.3 quota.
- **Throughput:** the probe is GPU-bound at 112 searches for v0. Lean seconds per expansion run about 5 on easy
  statements and 6-8 on hard ones; v35 is more Lean-heavy (5.5 s per policy attempt against 3.8-4.1).
- **The restart-path serving:** a run whose weights differ restarts only the servers concerned, from a content-addressed
  merge, in parallel across GPUs:
  - value servers about 3 min the first time, about 1 min later;
  - policy servers about 3.3 min.
  - The log shows "Stopped …", "Starting … (<merge>)", "Server … is healthy after N s", "… runs on CPUs 0-47,96-143 at
    niceness 0", "Weights put on [...] (restart); already held by [...]".
  - Servers holding identical weights are skipped.
- **Fingerprint lines:**
  - "Fingerprint of <merge> taken from <server>, just started from it" writes the reference.
  - "No fingerprint of <merge> and no server just started from it: its servers held to <server>" means the servers of
    that merge are compared with each other only.
  - The warning tolerance is 0.3 nats. Measured noise between servers with identical weights was up to 0.25 nats.
  - Above 1 nat the start fails.
- **Rejected runs and other exits:**
  - A rejected run (exit 3) shows "rejected" at the end of its line in `chain.log` and `False` in the ledger. The chain
    writes STOPPED.
  - Exit 4 means a server kept dying: read `/workspace/runs/servers/<name>.log` and the run's `sessions.jsonl` before
    anything else.
- **SSH flakiness:** sometimes a session hangs. Use `timeout`.
- **Agent tooling caveat:** subagents launched with the Agent tool blocked the parent for 25-40 minutes. Queue node work
  before delegating, or use `SendMessage` to resume an existing subagent, which runs in the background.

## 9. The plan from here

State at about 18:00 UTC on 2026-11-16. Everything up to the final HOLD runs by itself (section 3).

1. **Done:** run 7 (1,236 of 2,000), the deploy of 9a594b1, the 8 servers back on v0.
2. **e1, running:** the no-reasoning pilot `step1_run4_pilot_no_reasoning_T_cap14400` at the 14,400 s cap, in file
   order, on 9a594b1.
3. **After the pilot:** the relay restarts the chain, which deploys 9834972 (the start order).
   - Accepted pilot: e2 runs 3 and 4 in the new order (longest expected search first), then the e2 reports.
   - Rejected pilot: e2 is skipped (`e1_rejected`).
4. **f:** the order check run `step1_run9_v0_value_v0_ordered`, then its pairs against both anchors and its load.
5. **HOLD:** "waiting for the owner's decision on the arms' mode". The servers stay up.
6. **On the owner's word only**, the study:
   - step 2 (shrunk by the owner, 2026-11-17): one shared phase of 12M tokens → A's three per-tactic GRPO rounds
     (2e-5, 5e-5, 1e-4) → held-out ranking without gate runs; arm B dropped, C takes O2's rate and a 4-phase window, D
     takes C's rate and window and A's rate;
   - then the arms: 16 phases × 12M tokens each, with one probe run of each final checkpoint;
   - arms C and D need code that is not on the node.
   - The owner may first decide whether the arms sample with or without reasoning (runs 3 and 4 answer that).
   - Step 2 is automated by `deployment/study_chain.sh` (section 3, "The study driver"), tested locally only. Install
     it only on the owner's word, with his mode decision in `/workspace/runs/study_chain/mode.toml`.
   - The owner's rules for the arms: stop at the first valid-Lean collapse, capture and report; pull the adapters of
     phases 8 and 16 to the PC; extend the PC pull to the arms' run directories (section 7).

What the coordinator expects to be reported, from the files the chain writes in `/workspace/runs/step1_chain/`:
- **The pilot:** accepted or rejected, its wall-stop share, and its bulk/tail readings in `reasoning_readings.txt`.
  For the pilot alone run `/workspace/LLM-Search-Lean-Proofs/.venv/bin/python -I /workspace/step1_chain_tools/reasoning_readings.py step1_run4_pilot_no_reasoning_T_cap14400`.
  It includes the longest search's wall time.
- **Run 3:** started in the new order (the "start order of step1_run3_visible_T" line in chain.log); its early
  wall-clock stops; accepted.
- **Run 4:** accepted, with `run3_against_run4.txt`, `anchors_against_run3.txt`, `run3_load_against_file_order.txt`
  and `reasoning_readings.txt`.
- **f:** `run9_*` files.
- Running searches are counted from `chain.log`'s finish lines: running = min(112, statements not yet finished). Bulk
  means at least 100 running.

## 10. Least certain

1. **The automatic hand-offs between driver files.**
   - The 17:48 hand-off after run 7 worked: relay, deploy of 9a594b1 with the edits re-applied unchanged, servers back
     on v0.
   - The second one is untested: `relay_after_e1.sh`, the deploy of 9834972, e2 with the start-order logger, f, HOLD.
   - It fails safe: a STOPPED with its reason, and nothing runs. But it then needs someone to look.
2. **The reasoning sampler's REPL run-queue wait share** (`repl_run_queue_wait_share` in `reasoning_readings.py`).
   - It sums `/proc/<pid>/schedstat` deltas over REPLs alive in two consecutive samples.
   - It has not been checked against a known load; read it as indicative.
   - `reasoning_readings.py` also assumes `results.jsonl` lines are written in finish order, to split bulk from tail.
3. **The step-2 driver `study_chain.sh` has never run on the node.** It is tested against stand-ins only; its first
   run must be watched (section 3, "The study driver", lists what is not yet seen). The arms (step 3) are not
   automated.
