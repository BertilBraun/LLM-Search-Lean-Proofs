# Follow-up study: operating the node of 2026-11-15

Written 2026-11-16 at about 17:30 UTC by the agent that set this node up and ran step 1 on it. It is meant to be enough on
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
  - The chain deploys master's head (expected `0191a12`, which is ab78ace plus docs) right after run 7 (section 3).
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
- `study_chain.conf` (in `/workspace/step1_chain_tools/`) is prepared but **not installed**: the arms are on hold.

### Other processes of ours

- `relay_after_j.sh` (pid in `/workspace/runs/step1_chain/relay_after_j.pid`) is a one-shot relay.
  - It waits for the planned STOPPED after run 7 (text "step k failed 3 times").
  - When that appears it moves the marker to `STOPPED.deploy_ab78ace_boundary`, deletes `attempts_k` and runs
    `supervisorctl start step1_chain`.
  - Any other STOPPED is left alone.
  - It is not supervisord-hosted. After a container restart it is gone, but then supervisord restarts `step1_chain` with
    the current file anyway.
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
- After a container restart, supervisord starts the driver, which continues at the first step not done. The launcher
  resumes an interrupted run (sessions are recorded per run), and `grpo_loop.sh servers` restarts servers that do not
  answer.

| Step | What | Marker / state |
|---|---|---|
| a | anchors (runs 1, 2) | done |
| b | T = 26,804 into the token-capped configs | done |
| c | calibration set, calibration run, constants | done (`done_c_select`, `done_c_run`, `done_c_constants`) |
| (hold after c) | | `released_after_c` (released) |
| d | three value-free pilots | done |
| f | run 6, completion | done |
| g | run 5, final value | done |
| h | value servers back to v0, run 6 with block_sum | done (`done_h_value_v0`, `done_h`) |
| i | run 8 (v35, value v0) | done |
| j | run 7 (v35, final value) | **running** (1,998 of 2,000 at 17:10) |
| deploy_ab78ace | stash the node-local edits, fetch, `git merge --ff-only origin/master` (whatever its head is then), `git stash pop`; writes `edits/before_ab78ace.diff`, `after_ab78ace.diff`, `*.status`, `ab78ace_edit_difference.txt`; stops unless the edited lines are identical and both token-capped configs still read `max_generated_tokens = 26804` | next |
| k | `stop_model.sh` on all 8, then `LOOP_CONFIG=experiments/configs/grpo/followup/base.toml deployment/grpo_loop.sh servers` (all 8 on v0's weights) | next |
| (hold before e) | the driver writes `HOLD` and exits if the file `hold_before_e` exists | currently released (`hold_before_e.released`, `.released_2`) |
| e1 | the no-reasoning pilot alone, list `runs_reasoning_e1_pilot.toml` (`step1_run4_pilot_no_reasoning_T_cap14400`, 200 statements, 14,400 s wall cap) | next |
| boundary | waits up to 15 min for `ORDER_READY`; without it, runs 3 and 4 go in file order | `done_e_boundary` |
| e2 | runs 3 and 4 from `runs_reasoning_e2.toml` (file order, as written now) | then `done_all`, servers stay up |

**What happens by itself from now on:**
1. The old driver process (pid 198106, the file before the deploy step existed) finishes run 7. `attempts_k` was preset
   to 3, so its `attempt k` writes `STOPPED` "step k failed 3 times" and it exits 0.
2. The relay moves that marker to `STOPPED.deploy_ab78ace_boundary`, deletes `attempts_k` and starts `step1_chain` again,
   now with the current file.
3. The current driver runs `deploy_ab78ace`, then k, then e1.
4. At the boundary it waits up to 15 minutes, then runs e2, then writes `done_all`.

**What the operator does at the boundary:**
- If the new start-order code (probe statements with the longest earlier searches first) is reviewed and on master, the
  coordinator sends a commit and a run-list change.
- During the e1 pilot or the boundary wait:
  1. Deploy it: stash, `git merge --ff-only <commit>`, pop, and record the diffs as section 4 says.
  2. Rewrite `experiments/configs/grpo/followup/step1/runs_reasoning_e2.toml` as instructed.
  3. `echo "<commit and what changed>" > /workspace/runs/step1_chain/ORDER_READY`.
- If nothing comes within 15 minutes of the pilot's acceptance, the driver goes on in file order. Tell the coordinator.

To hold the chain at the next step boundary without disturbing a run, touch a marker the running file checks. Only
`hold_before_e` is checked, and only before e1. To stop safely between runs, wait for a run's ledger line, then
`supervisorctl stop step1_chain`. To resume after a STOPPED: read it, fix the cause, move it aside (keep a renamed
copy), then `supervisorctl start step1_chain`.

Markers in `/workspace/runs/step1_chain/` and what they mean:

| Marker | Meaning |
|---|---|
| `done_<step>` | step finished |
| `attempts_<step>` | tries so far; ≥ 3 makes the next try stop the chain |
| `attempts_e.before_cap14400` | the old e's counter, kept |
| `STOPPED` | the chain is stopped; its text says why |
| `STOPPED.deploy_boundary` | the planned stop before deploying 3309652 (2026-11-15) |
| `STOPPED.step_e_pilot_rejected` | the first no-reasoning pilot, rejected at 1.00% wall stops with the 7,200 s cap |
| `STOPPED.deploy_ab78ace_boundary` | will be written by the relay |
| `HOLD` | the driver exits 0 at start |
| `HOLD.after_c`, `HOLD.after_h` | old holds, released |
| `hold_before_e`, `hold_before_e.released*` | the hold switch before e; released |
| `released_after_c` | the hold after c happened once |
| `ORDER_READY` | operator → driver: runs 3/4 use the new order |
| `done_all` | the whole list ran |

Other files there: `chain.log`, `supervisor.log`, `edits/` (copies and diffs of every node-local edit), reports
(`anchor1_report.txt`, `anchor2_report.txt`, `anchors_load.txt`, `anchors_pair.txt`, `run5_*`, `run6_*`, `run8_*`,
`pilots_load.txt`, `token_budget.txt`, `automation_constants.txt`, `calibration_select.log`), readings
(`checks_before_anchor.log`, `readings_run1_5min.log`, `run5_restart_readings_*.log`, `run8_restart_readings.log`,
`run7_restart_readings.log`), `power_limits.txt` and `sampler_reasoning.tsv`.

### The study driver (prepared, on hold)

- `/workspace/step1_chain_tools/study_chain.sh` has state in `/workspace/runs/study_chain/`.
- It implements S1 only:
  - `deployment/arm_loop.sh --kind "shared sampling" experiments/configs/grpo/followup/shared_sampling.toml`.
  - It polls every 60 s until `finished.json`, restarts the loop through `arm_loop.sh` if it is found not running, and
    stops on `health_stop.json`.
  - Then `experiments/slice_trees.py --trees $LEAN_SEARCH_RUNS/followup_shared_sampling/trees --slices 4 --output
    …/slices`, then `HOLD`.
- To start it: `cp /workspace/step1_chain_tools/study_chain.conf /etc/supervisor/conf.d/ && supervisorctl reread &&
  supervisorctl update`.
- S2-S6 (learning-rate rounds, held-out ranking, arms) are **not written**.
- Untested: it has not been run once.

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
| `runs_reasoning_e2.toml` | runs 3 and 4 of it |

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
  - `deployment/arm_loop.sh --kind "shared sampling" experiments/configs/grpo/followup/shared_sampling.toml`, or
    `deployment/arm_loop.sh experiments/configs/grpo/followup/arms/<A>.toml`.
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
  - None of these has been run on this node; read their docstrings and DESIGN.md "Step 2" first.

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
| step1_run7_v35_value_final | v35 | final | visible | 2,000 | running (1,236 solved at 1,998) | | | |

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
  pid is in `C:\Projects\Lean-Proofs\node_backup\2026-11-15\pull_results.pid`: Git Bash pid 16324, Windows pid 21220.
  - Every 10 minutes it tars over SSH, excluding `trees`, `*.json.gz`, `weights` and `merges`:
    - `runs/step1_chain`, `runs/probe_evaluations`, `runs/calibration_evaluations`, `runs/probe_runs`,
      `runs/held_out_evaluations`, `runs/throughput`, `runs/backstop_replay`;
    - `runs/servers/*.log`, `*.cpus`, `*.members`;
    - `setup_logs`, `node_environment.sh` and `step1_chain_tools`.
  - It unpacks into `…\2026-11-15\live\` and writes `live\last_pull.txt`.
  - Check it is alive: `ps -p 16324` in Git Bash, and `cat …/live/last_pull.txt` (under 10 minutes old).
  - Stop it with `kill 16324` (Git Bash) or `Stop-Process -Id 21220`.
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

1. **Now:** run 7 finishes, then deploy master's head with the edits kept, then all 8 servers back on v0. All of this is
   automatic (section 3).
2. **e1:** the no-reasoning pilot at the 14,400 s cap (200 statements). If rejected, the chain stops and the coordinator
   decides.
3. **Boundary:** up to 15 minutes for `ORDER_READY` (the start-order feature: longest searches first). Without it, runs
   3 and 4 go in file order.
4. **e2:** run 3 (visible, 2,000 statements at T = 26,804), then run 4 (no reasoning, 2,000 statements). Run 4 may take
   10-25 h. Then `done_all`, with the servers up.
5. **Owed to the coordinator:**
   - run 7's report: the 2x2 of policy (v0, v35) by value (v0, final), per band, and the pairs run 8 against run 7 and
     run 5 against run 7;
   - for the pilot, run 3 and run 4: bulk (≥ 100 searches running) against tail readings from `sampler_reasoning.tsv`.
     That covers GPU utilisation, tokens/s per GPU, policy requests/s, Lean cores in use of 96, REPL run-queue wait
     share, throttling, expansions per hour, Lean against model-wait seconds per expansion, and the minutes with fewer
     than 56 and fewer than 20 searches;
   - what ended the searches; mean and maximum expansions; the longest search's wall time;
   - `probe_compare.py pair --across-search-modes` run 3 against run 4, and `--descriptive-across-settings` run 3
     against the pooled anchors.
   - Count searches running from `chain.log`'s finish lines: running = min(112, statements not yet finished).
6. **After that, on the owner's word only:** step 2 (shared sampling 48M tokens → 4 slices → learning-rate rounds for A
   per-tactic, B pure proof success, C expert iteration window 1 and 4 → held-out ranking without gate runs), then arms
   A and B (16 phases × 12M tokens, one probe run of each final checkpoint).
   - Only S1 is prepared, in `study_chain.sh`, and it is not tested.
   - The owner's rules for the arms: stop at the first valid-Lean collapse, capture and report; pull adapters of phases
     8 and 16.
