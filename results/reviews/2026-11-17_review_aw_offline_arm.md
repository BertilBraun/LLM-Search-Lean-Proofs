# Review AW: the offline arm's node driver and operations

Branch `worktree-agent-af3691747bca0ee5a`, head `58454ab` on master `dca9a1f` (commits `0d663a4`, `58454ab`). Focus:
will `deployment/offline_chain.sh` run unattended on the node, correctly; the `chain_helpers.sh` extraction; the data
steps already running on the node from a code copy; whether the tests exercise the production driver.

Checks run: `tests/rl/test_offline_chain_script.py` and `tests/rl/test_study_chain_script.py` in WSL against the
worktree's `src`: 143 passed (2 min 35 s). The extracted helpers compared with the old `study_chain.sh` bodies by
`declare -f` after sourcing both: identical except `shared_loop_config` → `held_out_loop_config`. Every command line
the driver runs read against the real CLI (`held_out_evaluate.py`, `learning_rate_step.py check-held-out`,
`rank_learning_rates.py`, `offline_arm.py` and its subcommands, `probe_runs.sh`/`probe_runs.py`, `probe_compare.py`,
`stop_model.sh`, `grpo_loop.sh servers`, `background.sh`). Node, read only: `/workspace/offline_arm_code/COMMIT` is
`0d663a4`; `offline_data_steps.sh` (detached, pid 423420, alive) has marked `done_download` and `done_prepare` and is
walking (5,000 of 65,585 at 5.2 proofs/s at 11:08 UTC, no `the walk raised` status so far); `preparation.json` 65,585
recovered, 11 ambiguous, 0 missing; step 1's eight servers are up; `grpo_followup_base` (version 0) exists; the reference
probe runs of the report exist; RAM 252 GiB; disk 249 GB free; the node environment sets `BACKGROUND_CPU_LIST` and
`TRAINING_CPU_LIST`, not `BACKGROUND_CPUS`; `RESPECTED_PID_FILES` unset.

**Verdict: merge after fixes.** Nothing blocks. The driver's command lines match the real tools. Markers, attempts and
resume are sound at every kill point I could construct. No adapter is evaluated before its trainer wrote
`training_summary.json`. Every retry path is counted and ends in STOPPED. Servers are stopped only through
`stop_model.sh`, and the GPUs are checked before each training. `study_chain.sh` behaves identically after the
extraction. The data steps on the node ran the same walk and prepare code as the reviewed head, so the driver can
continue from their markers. The should-fix items are about the hand-over from those detached data steps to the
installed driver, and about what happens if a review fix changes the walk.

## Blocking

None.

## Should fix

**S1. Nothing stops the installed driver from walking beside the detached data-steps walk.**
`deployment/offline_chain.sh:72`, `results/followup_node_operations.md` "Install and start".

- **What happens:** the walk on the node is `offline_data_steps.sh`, run from `/workspace/offline_arm_code`. It is not
  supervised and writes the same `$state` and `walks.jsonl`. If the driver is installed before that script touches
  `done_walk` (about 3.5 h from now), supervisord starts it at once (autostart). After 60 s its `step walk` starts a
  second 90-REPL walk on the same 96 Lean CPUs and appends to the same file.
- **Consequences:**
  - Both walkers take the same remaining proofs, so the work is doubled.
  - 180 REPLs on 96 CPUs hit the search's wall-clock limits. Walks that would complete are recorded as
    `block failed`, they count as done, and they are never walked again: the data is biased without a sign.
  - `read_walks` (`experiments/offline_arm.py:361`) truncates the file to its last newline when it starts. It can cut
    a line the other walker is writing, and that line's remainder is then appended as garbage. The next `build` then
    fails on the JSON.
- **The doc does not cover it:** the install section says "at a HOLD, with nothing else running" but never mentions
  the data steps, the code copy or `data_steps.pid`.
- **Fix, both cheap:**
  1. In the ops note, add a line to the install section: install only once `done_walk` exists, `chain.log` says "CPU
     steps done", and the pid in `data_steps.pid` is gone.
  2. In the driver, before `step walk`, refuse (STOPPED) while `$state/data_steps.pid` names a live process whose
     cmdline contains `offline_data_steps.sh`. That check also covers pid reuse.

**S2. `build` accepts walks made by any walk code: a review fix to the walk is skipped without a sign.**
`deployment/offline_chain.sh:69-73`, `experiments/offline_arm.py:486-488`.

- **Today:** safe. `git diff 0d663a4..58454ab` touches only `results/followup_node_operations.md`, so the node's
  prepare and walk ran exactly the reviewed code. `proofs.jsonl` and `walks.jsonl` have the reviewed formats and
  semantics.
- **What a fix would hit:** `done_prepare` and `done_walk` make the installed driver skip both steps for good. Suppose
  a fix from this round of reviews touches what they produce: `rl/offline_walk.py`, the extracted
  `named_state`/`identifier_check`/`policy_plan`, `plan_block`/`normalize_tactic_block`, `walk_settings`, `[walk]`,
  `[data]`, the walk's search config, `recovered_candidates`, or the exclusions.
  - **A format change** (a field added to or removed from `WalkedProof`, `ProofWalk`, `WalkBlock` or `PoolProof`):
    `from_json_object` is strict. `build` raises `ValueError`, the step fails 3 times and the chain is STOPPED with
    only "step build failed 3 times" in `chain.log`, and nothing walks again.
  - **A change in meaning** with the same fields (the block draw, the normalization, the identifier check, the
    exclusions): the arm trains on the old blocks without a sign.
- **Fix:**
  1. Before merging, check each fix against this list. For any fix that is not walk-neutral, move `walks.jsonl` and
     `done_walk` aside before installing, and `proofs.jsonl` and `done_prepare` too for a prepare fix (3.5 h of Lean
     CPUs, GPUs idle).
  2. Better: `walk` writes `walk.json` beside `walks.jsonl` holding a sha256 over `offline_walk.py`, the walk settings
     and `[walk]`/`[data]`. `build` refuses on a mismatch, naming the fix: move the walks aside.

**S3. The walk's error limit is relative to the session, so it tightens with each resume.**
`experiments/offline_arm.py:421`.

- **The rule:** `statuses[ERROR] > MAX_ERROR_SHARE * len(remaining)`. A session that resumes walks only the proofs not
  yet walked plus the earlier `the walk raised` ones.
- **Failure:** a few proofs that raise every time (a REPL crash on a particular statement, a Python exception in
  `plan_block` on odd text) make every small resume fail. Take a first session killed near its end, or one that ended
  above 1% for a transient reason. The resume on, say, 700 proofs fails on 8 persistent raisers. The next start walks
  those 8 again: 100% raise, and the third failure leaves the chain STOPPED ("step walk failed 3 times").
- **Asymmetry:** in the other direction, a first session with up to 1% raised walks (up to 655 proofs) exits 0. Those
  proofs are never walked again, because `done_walk` exists. They are only counted in `build.json`.
- **Fix:** compare with the number of proofs (`len(proofs)`) and with the latest walks over the whole file:
  `sum(walk.status == ERROR for walk in latest_walks(...)) > MAX_ERROR_SHARE * len(proofs)`. That bounds the total
  loss, and a resume is not judged on a few hard cases.

## Nits

- **N1. A missing `chain_helpers.sh` restarts the driver in a tight loop.** `deployment/offline_chain.sh:28`, the same
  in `deployment/study_chain.sh:33`. "no chain_helpers.sh beside the driver" exits 1 before the 60 s start sleep. With
  `startsecs=0` and `autorestart=unexpected`, supervisord restarts on every exit 1 without limit or backoff, so it
  respawns at full speed. Fix: write `$state/STOPPED` inline and exit 0, or sleep before exiting.
- **N2. One `chain_helpers.sh` serves two installed drivers.** `/workspace/step1_chain_tools/chain_helpers.sh` is
  shared by `study_chain.sh` and `offline_chain.sh`. Installing one driver from a later master replaces the other
  driver's helpers at its next restart (a container restart mid-chain). A helper that needs a new variable then fails
  under `set -u` inside a counted step. Fix: install the helpers as `<driver>_helpers.sh`, or note that a helpers
  change waits until both drivers are at HOLD or STOPPED.
- **N3. Driver constants duplicate the config, and no test pins them.** `deployment/offline_chain.sh:43-47`. `arm`,
  `rates`, `v0_adapter` and `gate_run` repeat `offline_arm.toml`'s `name`, `learning_rates` and
  `initial_policy_adapter`, and `GATE_RUN`. If they drift, `train` refuses 3 times and the chain is STOPPED, and if
  `v0_adapter` drifts the arm is compared with a v0 run of another adapter. Add a test that reads the config and the
  driver's assignments.
- **N4. The rejected-probe stop gives advice the driver cannot follow.** `deployment/offline_chain.sh:122`. The
  message says to repeat the run at a doubled cap under a new name. But the name (`probe_run_name`,
  `experiments/offline_arm.py:723`) and the cap (`offline/probe_evaluation.toml`) are fixed. `runs_<subset>.toml` is
  only rewritten before `done_rank_<subset>`. And `report` reads `probe_offline_arm_<subset>`, which is then the
  rejected run (`read_arm_run` refuses it). Finishing the subset after a rejection needs a code change. The risk is
  low: no reasoning at 16 expansions under 14,400 s. Fix: give the manual procedure in the ops note, or add a
  `--probe-name` option to `probe-list` and `report`.
- **N5. Stray output lands in the gate report and the ranking file.** `deployment/offline_chain.sh:149,162`. `2>&1`
  writes library warnings into `report_<subset>.md` and `rank_<subset>.txt`. `chosen_label` is unaffected, but the
  gate report gets noise. Send stderr to a `.log` beside them.
- **N6. Stale comments in the step-2 files.** `deployment/study_chain.sh:4-5` and `deployment/study_chain.conf:2`
  still describe the install as the driver's copy alone. The ops note's install commands do copy the helpers;
  `offline_chain.conf` already mentions them.
- **N7. Test gaps.** `tests/rl/test_offline_chain_script.py` and the fakes:
  - The fakes ignore `LOOP_CONFIG` and `--loop-config`, so a wrong held-out loop config would pass.
  - No test starts from the data steps' state: `done_download`, `done_prepare` and `done_walk` present, no
    `attempts_*`, `timings.tsv` with two lines. That is exactly the first start on the node.
  - No test that a failed dry run, ranking, probe list or report ends in STOPPED.
  - The fake `probe-list` writes a bare `[[runs]]`, so the chosen adapter path never reaches a check.

  None of this hides a defect today.
- **N8. Theoretical endless loop in the replay.** `src/lean_search/rl/expert_iteration_data.py:609-621`. With
  `repeat`, items whose completion tokens are all 0 and a positive budget never return. This cannot happen with real
  data. An assert after a pass that added no tokens would close it.
- **N9. Nobody resumes the detached walk after a container restart.** Until the driver is installed, nothing restarts
  `offline_data_steps.sh` (it is not under supervisord). The watchdog should check that `data_steps.pid` is alive and
  that `walk.log` advances. The installed driver resumes the walk correctly (`read_walks` drops a cut line; ERROR
  walks run again).

## Checked and fine

**Command lines**
- `held_out_evaluate.py`: `--name/--arm/--phase/--policy-adapter/--loop-config`; exit 4 for servers that keep dying.
- `learning_rate_step.py check-held-out --name`.
- `rank_learning_rates.py`: `--v0 <name> --variant <label> <rate> <held-out name>`. Its `Chosen: <label> (` line
  parses with `chosen_label`, and the labels equal `run_label(subset, rate)`.
- `offline_arm.py`: `train --subset --learning-rate [--dry-run]`, `held-out-config --output`, `probe-list --subset
  --rank --output`, `report --subset`. Rates stay strings (`5e-5`, `1e-4`) end to end, so `output_of` equals
  `run_name` (`offline_arm_<subset>_<rate>`).
- `probe-list` writes `PlannedRun` fields only (name, arm, phase, policy_adapter, value `v0`, config, search_config,
  purpose).
- `probe_runs.sh --foreground` with `PROBE_CONCURRENCY=112`: exit 3 means rejected, exit 4 servers dying, and its
  own refusals (`node_checks.py`, `probe_runs.py check`) exit 1 or 2 and are retried.
- `probe_compare.py pair --x/--y/--x-label/--y-label --descriptive-across-settings`: across settings only the probe
  set must match, so run 8's other search mode is accepted.
- The report's `grep 'the owner.s gate'` matches `gate_report`'s sentence.
- `download` passes `token=False` and unsets `HF_HUB_OFFLINE` for that step only.

**Markers, attempts, resume**
- A step is either marked, or retried under a counted attempt. Every exit-1 path after the start sleep sits behind
  `attempt()`, so nothing loops forever, and the fourth attempt is STOPPED.
- A training that finished before its teardown failed is kept: it needs `attempts_*` and the adapter and
  `training_summary.json`, and that file is written last and atomically.
- A killed training is moved aside and retrained into a fresh output. `run_training` also refuses an existing
  adapter.
- Held-out runs come only after `done_train_*`. A resumed held-out run continues under its name, and a different
  adapter would be refused.
- The ranking and probe list are deterministic, so a kill between them and the marker repeats them identically.
- Probe runs resume through `probe_runs.sh`.
- A start after HOLD or STOPPED does nothing, and a rerun with all steps done goes straight to the final stop and
  HOLD.

**Servers and GPUs**
- `stop_model.sh --all` runs before any training of each subset, on a resume too. `gpus_free` runs before each
  training.
- Held-out runs start the servers on `grpo_followup_base` version 0 (the held-out loop config keeps base's `name`, and
  it exists on the node). Each held-out run puts its adapter on the policy servers itself.
- The probe run starts any server that does not answer and puts the chosen adapter on, with value v0.
- HOLD stops the servers. Step 1's servers, up now, are stopped before the matched training.
- Nothing else on the node holds a CUDA context (`reasoning_sampler` only calls `nvidia-smi`).

**Node rules**
- No kill other than through `stop_model.sh`, no reboot, no token, no git.
- The CPU layout comes from the node environment and is checked. Training runs on `TRAINING_CPU_LIST` through
  taskset. Prepare, walk and held-out runs go through `background.sh`, and probe runs are pinned by `probe_runs.sh`.
- Installation is a copy and an `mv` of `.new` files. The helpers are sourced whole at start, so replacing them never
  affects a running driver.

**Data steps on the node**
- Code `0d663a4` equals the head in `src/`, `experiments/` and `deployment/`.
- `offline_data_steps.sh` writes the driver's marker names, `started_*` and `timings.tsv`. It uses the same commands
  and arguments, with `PYTHONPATH` on the copy's `src` ahead of the checkout's venv.
- The driver skips its steps and continues at `build`.

**The `chain_helpers.sh` extraction**
- `say`, `stop_chain`, `attempt`, `done_step`, `mark_start`, `finish`, `aside`, `held_out`, `gpus_free` and `complete`
  are identical to the old bodies, apart from the renamed loop-config variable, which `study_chain.sh:49` sets to the
  old value.
- The helpers are sourced before first use and before `cd`, with an absolute `BASH_SOURCE` under supervisord.
- `local arm` in `held_out` shadows the offline driver's global `arm` only inside the function, which does not use it.
- The ops note's step-2 install section now copies the helpers.

**`search.py`**
- The extraction (`named_state`, `identifier_check`, `policy_plan`) behaves the same for the search. No leftover
  `identifier_checker` or `name_scope` references remain.

**Tests**
- The driver test runs the real `deployment/offline_chain.sh` with the real `chain_helpers.sh` beside it, under a
  supervisord-like restart loop.
- The kill points are reached (`-9`) and resumed to HOLD.
- Each training runs to its end exactly once, no missing adapter is evaluated, no output is overwritten, and
  teardown failures are kept.
- Busy GPUs, a refused stop, probe exits 1, 3 and 4, and 3 failed walks each take the documented path.

## Smoke-check at first run

1. **Before installing:**
   - `done_walk` exists, `chain.log` says "CPU steps done", and the pid in `data_steps.pid` is gone (S1).
   - `walk.log` has its final status counts, including the count of walks that raised.
   - `wc -l walks.jsonl` is at least 65,585.
   - Master holding the offline arm is deployed to the checkout.
   - Both `.sh` copies are in `/workspace/step1_chain_tools/`.
   - No fix since `0d663a4` touched prepare or the walk (S2).
2. **`build.log` and `build.json`:**
   - walk statuses, and complete walks per candidate;
   - `over_prompt_cap` and duplicates;
   - matched completion tokens close to 2M;
   - pool and validation sizes.
3. **`held_out_loop.toml`:** `name = "grpo_followup_base"` and the no-reasoning `search_config`.
4. **`dry_run_matched.log`, last line:** offline, Lean and math replay examples, shares close to 60/30/10%, steps on
   4 GPUs.
5. **`servers.log`:** eight servers stopped. `nvidia-smi` shows about 1 MiB per GPU before `train matched 5e-5`.
6. **`training/matched_5e-5.log`:** the first steps' tokens per second.
7. **`held_out/offline_v0_no_reasoning.log`:**
   - servers started on version 0;
   - the swap to v0's adapter;
   - `pinning.jsonl` on the 96 Lean CPUs.
8. **`rank_matched.txt` and `runs_matched.toml`:** the chosen label and adapter path.
9. **`probe_matched.log`:**
   - `servers-free` passes;
   - concurrency 112;
   - longest-expected-first order;
   - the servers swapped to the chosen adapter, value v0.
10. **`report_matched.md`:** the gate line, and the descriptive rows against run 4 and the anchors.
11. **Pool dry run:** peak RSS of the single process. The four ranks each tokenize the whole pool set (about 565M
    tokens as Python int tuples, roughly 20 GB per rank). Four times that must fit the free RAM once the servers are
    stopped (252 GiB total).
12. **HOLD:** written, with `stop_model.sh` having stopped every server.
