# Review AJ: follow-up WP6 study tooling (launcher, step-1 configs, arms, held-out runner, slices), code

Branch `worktree-agent-acedfb3c2cd157ac3` (master..970a3db, 7 commits) against DESIGN.md "Follow-up study: controlled
arms" (Arms, Evaluation, Step 1, Step 2, WP6), with the sibling `worktree-agent-a1f7eaa0dbb612621` (WP1, WP5) read for
interfaces. Focus: does it run correctly on the node the first time, and can it silently run the wrong thing.
In WSL: the branch's suites plus `test_shipped_grpo_configs.py`, 231 passed. The three arms generated with a filled rate
(`followup_arm.py`) and compared after parsing against `followup/base.toml` and `grpo/phase.toml`. shellcheck is not
installed, so the shell script was read by hand. Not run: anything on a GPU, the launcher end to end.

## Traces

- **Arms**: A, B1 and B2 differ from each other only in `name`, `training.phase_config` and `policy.data.credit`. They
  differ from base/phase only in `name`, `phase_config` and `learning_rate`. `[[serving.*_servers]]` round-trips through
  the new inline form. The `toml_text` change only adds a case that used to raise, so every earlier caller (loop phase
  configs, `run_config_text`, which means every run digest and identity) writes the same bytes as before.
- **Runs 3/4**: the token-capped files are `visible_student_v2.toml` with `max_expansions` 1024, `max_depth` 64,
  `depth_weight` 0 and T. Run 4 differs from run 3 only in `visible_reasoning` (CRLF aside), and the tests pin both facts.
  `probe_run_config` takes the template's 1024 (`--search-config`) and the probe's 7,200 s cap and concurrency, turns
  harvest and ε off, and keeps `max_generated_tokens`. `Search._search` checks the cap before each expansion, so an
  expansion is never cut mid-way and the last one overshoots by one expansion. Prompt, stop strings and forced answers
  follow `visible_reasoning` and nothing else. Sample count, temperature and `max_tokens` (1024) are shared.
- **Value-free runs**: `step_log_probability`, `kind`, `length_exponent` and the constant come only from
  `[value_free_priority]`, and `value.model = ""`. Calibration runs search 1 expansion (`[probe] max_expansions = 1`, no
  `--search-config`), so the dummy `calibrated = true` constant only ever scores children that are never chosen. The
  recorded step values follow the setting, not the constant.
- **Placeholders**: every one stops both the launcher and a direct `probe_evaluate.py` call. T is a string in an int
  field, so `from_json_object` fails. A placeholder path has no adapter directory. A placeholder `config` file is not
  found. `calibrated = false` is refused. The probe concurrency `56` is the exception: it is not a placeholder (finding 2).
- **Crash vs rejected**: a server death raises after 3 transport attempts, the run exits 1 and the launcher stops with
  "rerun to resume". Exit 3 comes only from `run.json` saying rejected. Nothing in the diff kills anything. The only kill
  the launcher reaches is the existing `stop_model.sh <name>` (by pid-file process group) for servers that are down.

## Must fix before merge

1. **`seed_offset` is in the wrong place against WP1.** `study_configs.ARM_SETTINGS` (`study_configs.py:18`) allows
   `loop.training.seed_offset`, but the sibling's `GrpoLoopConfig.seed_offset` is top level. After both merge, a
   second-seed arm written the documented way fails in `load_loop_config` with "unknown keys". Written the right way
   (`[loop] seed_offset`), `arm_configs` refuses it. That is loud, but second seeds become impossible. Fix: allow
   `loop.seed_offset`, and fix the comment and the test name with it.

## Must fix before the first node run

2. **The concurrency guard is empty as documented.** `probe_runs.sh:5` and `runs_anchor.toml:4` give a copy-paste
   command with `BACKGROUND_CPUS=40 PROBE_CONCURRENCY=56`. Every evaluation config holds a literal `concurrency = 56`
   marked "THROUGHPUT TEST: a placeholder". Run that command before the throughput test, and `check` compares 56 with
   56, so runs 1–2, the anchor of everything, go at an unmeasured load. The example also breaks `background.sh`'s own
   rule: no more Lean processes than `BACKGROUND_CPUS`, so 56 REPLs on 40 pinned CPUs hit wall-clock tactic timeouts,
   which become `FAILING` labels. Fix: use `<the throughput test's>` in every copy-paste command, as `followup_arm.py`
   does. Have `check` print both values and refuse `PROBE_CONCURRENCY > BACKGROUND_CPUS`, unless the throughput test
   explicitly cleared that ratio.
3. **The launcher cannot survive a disconnect and leaves no log.** `probe_runs.sh` runs in the foreground, with no
   `nohup` or `setsid` and no log file, for 10–25 h lists. An SSH drop sends SIGHUP, which kills the list and the probe.
   The data is safe: results resume, flock is released, and stale merges are removed at the next start. But the list
   just stops, and the 10-minute watchdog has nothing to read. Fix: run like `grpo_loop.sh loop` (detached, a
   `probe_runs.pid`, output appended to `$LEAN_SEARCH_RUNS/<output>/probe_runs.log`), or require running it under
   tmux and say so in the header.
4. **Check the CPU layout before trusting `background.sh` on this node.** It pins to the last N of `nproc --all`
   (`background.sh:19-23`). That count ignores both the cgroup quota and any cpuset. On a 128-thread host with only a
   61-core `cpu.max`, CPUs 88–127 are valid but are probably SMT siblings of 24–63. With a restricted cpuset, `taskset`
   fails on every run, which is loud but stops the list. Also, `BACKGROUND_CPUS` ≥ the quota is accepted. That lets the
   pinned job take the whole quota and throttle the unpinned vLLM processes. Fix: during node-check, compare
   `taskset -cp $$` and `cpuset.cpus.effective` with `nproc --all`. In `background.sh`, take the last N CPUs of the
   allowed list, and refuse N ≥ quota/period − a few cores. Record `len(os.sched_getaffinity(0))` in `run.json` so an
   unpinned run can be seen.

## Must fix before the first arm run (step 3) or step 2's ranking

5. **After both merges, the arms would run on minutes and groups, not tokens, and nothing errors.** The sibling only
   *comments* `phase_generated_tokens` and `max_phases` into `base.toml`, and `ARM_SETTINGS` does not allow them. So
   `followup_arm.py` writes arms that end phases by `GrpoLoop.phase_due`'s 75 min / 300 groups and never stop. This
   breaks the design's compute matching. Fix: set B and 16 phases in `base.toml`, since they are identical for every
   arm. Assert `phase_generated_tokens > 0 and max_phases > 0` in `arm_configs`, plus a test. Also make
   `grpo_loop.sh loop` refuse an arm without `BACKGROUND_CPUS`: WP6 asks for "a launcher that requires the arm config
   and pinning", and today pinning there is optional.
6. **The learning-rate ranking uses partial held-out runs without saying so.** `rank_learning_rates.read_held_out`
   (`:61-72`) keeps only states whose tree exists, and `paired_states` pairs on the intersection. A run that crashed
   halfway is ranked on fewer states, and nothing says so. Fix: require `summary.json`, which is written only at the
   end, and all 512 states. Also check that `checkpoint.json`'s arm/phase matches the variant label.

## Should

7. **`next_run` treats a run as done by name alone** (`probe_runs.py:67-84`). A `run.json` under the name means
   "accepted", even if the list now asks for another adapter, search config or problem count. This happens when T is
   corrected after run 3 finished, or when a later list reuses a name. The run is then silently skipped and the old
   result goes into the ledger under the new purpose. Fix: compare the planned run with `checkpoint.json` (policy path,
   value, search config, problems) and stop on a mismatch, as `refuse_another_start` does for pending runs.
8. **Run 4's pilot is not ordered before runs 3 and 4.** Once T is filled, `runs_reasoning.toml` can run before
   `runs_reasoning_pilot.toml`. Passing both lists interleaves them, giving run 3, then the pilot, then run 4. Fix: put
   the pilot first in `runs_reasoning.toml`. A rejected pilot then stops the list (exit 3) before ~25 h of full runs.
9. **`run_refusals` misses states that surface hours into a list** (`probe_run_list.py:83`): a missing adapter
   directory (run 5's path, typos), a value path without `value_version`, `anchor` with `search_config` or `problems`,
   a missing probe set or `calibration_200.jsonl`, a missing `[probe]` table (KeyError). `probe_evaluate.py` refuses
   each only when that run starts. Check them all in `check`.
10. **`--across-search-modes` drops every config check** (`arm_comparison.py:146`). The runs 3/4 comparison then does
    not verify equal T (`max_generated_tokens` is not in `RunSettings`) or equal concurrency. T is typed twice by hand.
    Fix: add T and concurrency to `RunSettings` and compare them always. Better still, keep T in one file.
11. **`held_out_evaluate.py` is comparable with the loop only in procedure.** It uses the same function, target
    (1 expansion, 120 s, concurrency 56), states file, sampling search config, no value model and options off. That is
    what `grpo_evaluate.py --target held_out_states` runs at a pause. It differs in four ways: it is not pinned (the
    loop's evaluation subprocess inherits the loop's affinity), it merges with `merge_adapter` on the CPU rather than the
    loop's publisher, its resume check covers the adapter only, and nothing hashes the unpublished states file. The old
    node's v0 32.2% / 57.2% are not comparable at all: another node, quota and pinning. Step 2 must use this
    tool's own v0 run on the new node, which `rank_learning_rates --v0` already requires. Fix: document or enforce
    `background.sh`, record affinity and the states file's sha256 in `checkpoint.json`, and compare both on resume.
12. **Slicing does not refuse a running loop** (`slice_trees.py:29`). A sampling run that is still writing gives slices
    of a snapshot. Since output is "cut once", a rerun is refused. Fix: refuse while `running_loops` lists the run, and
    record the index line count in the manifest. The links are absolute (`tree_slices.py:85`). `grpo_phase.py --trees`
    and `expert_iteration_trees.directory_trees` glob `*.json.gz` and follow them, and the unresolved `tree.path.parent`
    check matches. Moving the run directory breaks the links, but loudly. Relative links would survive a move. The
    slice `index.jsonl` is read by neither consumer, which is harmless.
13. **The servers can be another config's** (`probe_runs.sh:28`). `start-servers` restarts only servers that do not
    answer. A server already listening on the same port with another `max_model_len` or memory share is used as it is,
    and the run identity records nothing about it. Fix: compare `/v1/models`' `max_model_len` and served name with the
    loop config in `serve_checkpoint`.
14. **`stop_model.sh` trusts a pid file** that may predate a container restart. `start_server` calls it for every down
    server before starting, so a reused PID group could be TERM/KILLed. This is existing code, now reached on every
    launcher start. Fix: before killing, check that `/proc/<pid>/cmdline` contains `vllm`. This is still a kill by PID.

## Minor

15. The ledger skips a name already in it, so a rerun under the same name after deleting `run.json` keeps the stale row.
16. Overshoot at T: one visible expansion averages ~1.7k tokens (~6% of T ≈ 27k) and can reach 8 × (1024 + 256).
    DESIGN's "up to ~3%" understates this. The tokens actually used per mode are reported (`search_ends`).
17. In calibration, when automation proves at the root, the policy samples may be cancelled, so the easiest statements
    give fewer samples. It is a small bias of the median.
18. Not provided: the shared-sampling run's config (`max_generated_tokens` = 4B, no phase due) and the miniF2F T64 runs
    (`token-budget` only prints T64).
19. A test asserting that every run whose config is `value_free_*` or `calibration_*` has `value = "none"`.
    `--value v0` silently ignores `[value_free_priority]`.

## Tests

None cover `probe_runs.sh` itself, `probe_runs.py check` with the lock held or a loop running, `held_out_evaluate.py`,
or `rank_learning_rates` on partial runs. Add first a pytest that runs `probe_runs.sh` on a temp `LEAN_SEARCH_RUNS`,
with the probe command replaced by a stub that writes `run.json` and exits 0, 1 or 3. It should assert that exit 3 stops
two interleaved lists with one ledger line, that exit 1 resumes on rerun, and that an accepted run is skipped. Then: a
held lock refusing `check`, and `read_held_out` refusing a run without `summary.json`.

## Step-1 runs: ready on merge

- **Ready** once fixes 2–4 are in: runs 1–2 (`runs_anchor.toml`). They also need the throughput test's concurrency in
  the configs, `LOOP_CONFIG=base.toml grpo_loop.sh init`, `probe_v2.jsonl` and both v0 adapters on the node.
- **Ready apart from data**: `runs_calibration.toml`, after `calibration_statements.toml` draws `calibration_200.jsonl`.
  That draw needs the held-out states file, the old run's tree index and the training data on the node.
- **Blocked only on a path**: run 5, once the final value adapter is downloaded and its path filled in.
- **Blocked on a measurement**: run 4's pilot and runs 3–4 (T from accepted runs 1–2), the value-free pilots (the
  calibrated constants), run 6 (the pilots' winner), runs 7–9 (v35 paths, and whether they are needed at all).

**Verdict: merge after fixes.** Fix 1 at merge. Fixes 2–4 before the first node run. Fixes 5–6 before step 3 and
step 2's ranking.
