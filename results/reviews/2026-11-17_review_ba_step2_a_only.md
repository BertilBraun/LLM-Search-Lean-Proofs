# Review BA: step 2 shrunk to arm A's learning rate, node operations

Branch `step2-a-only`, head `4a0b192` (3 commits on `fdf6161`). Same focus as review AU: will
`deployment/study_chain.sh` run the shrunk step unattended and correctly on the node, and did anything shared with
`deployment/offline_chain.sh` (`deployment/chain_helpers.sh`, `learning_rate_step` functions, the shared test fakes)
break. Read against the real tools (`slice_trees.py`, `tree_slices.py`, `grpo_phase.py`, `held_out_evaluate.py`,
`rank_learning_rates.py`, `arm_loop.sh`, `followup_arm.py`/`study_configs.py`, `loop_config.py`). No node access this
time. WSL: `test_study_chain_script.py`, `test_learning_rate_step.py`, `test_study_commands.py`,
`test_learning_rate_report.py`, `test_offline_chain_script.py`, `test_followup_arms.py`, `test_rate_ranking.py`: 329
passed.

**Verdict: merge.** Nothing blocking. One should-fix concerns the two chain drivers sharing the GPUs with no guard
between them; it predates this branch in part, but this branch makes both drivers installable at once.

## Blocking

None.

## Should fix

**S1. Nothing stops `study_chain` and `offline_chain` from using the GPUs and servers at the same time.**
`deployment/study_chain.sh:92, 176, 205` (`stop_model.sh --all`), `deployment/offline_chain.sh:218-219` (the O1
switch), both confs `autostart=true`; ops doc lines 312 and 381-384.
Both drivers stop all servers, train on all four GPUs and run held-out evaluations, and neither looks at the other's
state. The install text says to start step 2 only "at a HOLD of the node's other drivers", but the O1 switch
(`touch run_pool`, move HOLD aside, `supervisorctl start offline_chain`) says nothing about step 2, and both programs
autostart after a container restart. If they overlap, one driver's `stop_model.sh --all` takes down the servers under
the other's held-out run, and a round meets GPUs the other holds. The existing checks turn this into STOPPED or
repeated retries rather than wrong results: `gpus_free`, the serving lock in `held_out_evaluate.py`, and exit 4 when
servers keep dying. The cost is hours of node time and a confusing chain.log, not silent corruption.
Fix: a few lines in `chain_helpers.sh`. Each driver names the other's state directory and stops with STOPPED ("the
other chain is running") before its first server or GPU action, unless that state holds HOLD or STOPPED or does not
exist. Add a line to the O1 switch in the ops doc: only while `study_chain` is at HOLD or not installed.

## Nits

**N1.** `study_chain.sh:198`; `src/lean_search/rl/learning_rate_step.py:327-336`: the report only names
`/workspace/runs/offline_chain/rank_matched.txt` for C's and D's rate. When that file exists, the report could read
its `Chosen:` line with `chosen_label` (already imported by `offline_arm.py`) and print the rate itself. That removes
one manual lookup and one chance of a typo when filling the placeholders.

**N2.** `tests/rl/test_tree_slices.py`: no test of `slice_by_tokens(entries, 1)` and `write_slices` with a single
slice. The code handles it (no cut in `range(1, 1)`, so one slice of all trees in finish order). The driver test checks
only that the fake receives `--slices 1`. One parametrized case (count 1: every tree in `slice_1`, manifest total equal
to the index's) pins the path the driver now depends on.

**N3.** `src/lean_search/rl/tree_slices.py:155`: links are named by the tree file's basename. Two trees with the same
basename in different phase directories would collide (`os.symlink` raises). A sampling-only run has one phase, so this
cannot happen here; a one-line note or an assert would keep a later multi-phase use from tripping on it.

**N4.** Ops doc lines 339-342: `mode.err` (the mode check's stderr, which the STOPPED text quotes) is not listed
among the logs.

## Checked and fine

- Command lines against the real CLIs:
  - `slice_trees.py --trees … --slices 1 --output …/slices` writes `slices/slice_1`, which is the plan's `TREES_SLICE`.
    The flattening is needed because `grpo_phase.py` globs `*.json.gz` only at the top of `--trees`, while the run
    stores trees under phase directories.
  - `grpo_phase.py --config A_<rate>.toml --trees …/slice_1 --run-name step2_A_<rate> --part policy --lean-replay
    --math-replay`; `rounds.tsv` has 8 fields and `train_round` reads 8.
  - `rank-arguments` takes no `--signal` now, and the driver passes none.
  - `rank_learning_rates.py --v0 step2_v0` with the three A variants.
  - `check-round --label` choices are the three A labels.
  - `report --o2-ranking` takes a path string and does not read it, so a missing O2 file cannot fail the report.
- The shared sampling config: 12M total below the 1e9 phase budget makes it sampling-only (`loop_config.py:160`,
  `budget_refusals`); the unchanged `max_phases = 0` and the arms' `sampling.json` comparison still hold.
- Restart semantics:
  - Markers, attempts, and the `s1_loop_exit` attempt (AU N9).
  - stderr kept out of `mode.txt` (AU N8).
  - A finished round is kept only if `phase.json` reads back through `check-round` (AU N10).
  - `rounds/<label>.exit` is cleared before each attempt.
  - Kill points cover sampling, slices, both v0 runs, a round, a variant's held-out run, the ranking and the report.
- Servers and GPUs: stopped through `stop_model.sh` only, before S1's first start, before S2 and before HOLD (HOLD
  says the servers are stopped). `gpus_free` judges free by memory. Held-out runs put their own adapter on the servers.
- `chain_helpers.sh` contract: `study_chain.sh` sets `state`, `python`, `poll_seconds`, `gpus`, `gpu_free_mib` and
  `held_out_loop_config` before using the helpers. A missing helpers file writes STOPPED and exits 0 instead of
  looping. `source` reads the whole file at once, so replacing it does not disturb a running driver.
- Offline chain unaffected:
  - It uses `check-held-out` (kept) and `chosen_label` (kept), and its held-out names (`offline_*`) cannot clash with
    `step2_*`.
  - The shared fake `python` lost only the expert-iteration and dry-run stand-ins, which `offline_chain.sh` never calls.
  - `test_offline_chain_script.py` passes.
- Arms: C and D carry the owner's window 4, and the placeholders left are exactly C's O2 rate and D's two rates
  (pinned by `test_followup_arms.py`).
- Node rules: PID-only stops, CPU lists from the node environment, `HF_HUB_OFFLINE=1`, rounds on
  `TRAINING_CPU_LIST`, installation as copies with `chain_helpers.sh` beside the driver.

## Must be smoke-checked on the node at first run

1. `slice_trees.py --slices 1` on the finished sampling-only run: `manifest.json` total equals the index's trees and
   tokens, and `slice_1` holds absolute links.
2. The first round: `grpo_phase.py` reads every link in `slice_1`; trees, groups and steps in `phase.json` are about
   one arm phase's worth.
3. `nvidia-smi --query-gpu=index,memory.used` reads under 100 MiB per GPU after `stop_model.sh --all` (carried over
   from AU).
4. `offline_chain` at HOLD, or not installed, for the whole of step 2 (S1).

## Re-review (2026-11-17)

Fixes `4a0b192..6182609`. WSL: `test_study_chain_script.py`, `test_offline_chain_script.py`, `test_tree_slices.py`,
`test_learning_rate_step.py`, `test_learning_rate_report.py`, `test_study_commands.py`, `test_followup_arms.py`: 355
passed.

**Verdict: merge after one small fix** (S2 below: two lines in the driver plus a sentence in the doc). The guard is
otherwise right.

| Finding | Status | Note |
|---|---|---|
| S1 the two drivers share GPUs unguarded | Fixed in the code, with one gap on the node (S2) | `chain_helpers.sh:26-34` `other_chain_idle`; `study_chain.sh:86` and `offline_chain.sh:91` call it before their first server or GPU action. |
| N1 report only names O2's file | Fixed | `o2_choice` reads the `Chosen:` line via `o2_rate` (labels from `offline_arm.run_label(MATCHED, rate)` and the offline config's rates). A missing or unreadable file prints "O2 not ranked yet" and does not fail the report. |
| N2 no one-slice test | Fixed | `test_tree_slices.py`: one slice holds every tree in finish order; it links and records them all. |
| N3 link name clash | Fixed | `tree_slices.py:148-150` refuses duplicate basenames before anything is written (see N5). |
| N4 `mode.err` not listed | Fixed | Ops doc line 356. |

The guard, checked:
- **Placement.**
  - Study chain: after the mode check and `write-configs` (no server or GPU action), before S1's first `stop_model.sh`.
    It runs on every start, so a resume in S2 or S3 is guarded too.
  - Offline chain: after its CPU data steps and `held_out_config`, before `stop_servers`. Its data steps may run while
    step 2 runs, but step 2 refuses to start while the offline chain has a `chain.log` and no HOLD or STOPPED, so the
    two never meet on the Lean CPUs either.
- **What counts as started.** "Started" means the other directory holds a `chain.log`; an empty or prepared state
  (`mode.toml` only) does not count. Both directions are tested, along with HOLD, STOPPED, a prepared state and the
  O1 switch while step 2 runs.
- **No restart loop.** `stop_chain` exits 0, so supervisord does not retry.
- **Both started at once** (e.g. a container restart with neither at HOLD): each writes STOPPED, or the later one finds
  the other's STOPPED and goes on. Either way they never overlap.
- **Old offline chain on the node.** The node's installed offline chain sources the shared `chain_helpers.sh` at each
  start. The only change to that file since its first version (`0d663a4`) is the added function, so the old driver
  keeps working with the new copy and simply never calls it.

### Should fix

**S2. Until the offline chain is reinstalled, the guard works in one direction only, and an older helpers copy turns
the study side off without a word.**
`deployment/study_chain.sh:86`; ops doc lines 325-328 and 397-398.
- The installed `offline_chain.sh` predates the guard. Until it is reinstalled from this master, nothing stops O1's
  switch (`touch run_pool`, move HOLD aside, start) while step 2 runs. Yet the doc says "otherwise the offline driver
  stops itself" (397-398) and "each driver stops itself" (325-328), both untrue on the node today.
- The study driver calls `other_chain_idle` without checking that the sourced helpers define it. Under `set -uo
  pipefail` without `-e`, an undefined function prints "command not found", returns 127 and the driver goes on (checked
  in bash). If `study_chain.sh` were installed beside the older `chain_helpers.sh` (step 3's copy skipped, or the copy
  deferred because the doc says to replace it only while both drivers are at HOLD), the guard would be off silently.
- Fix:
  - In `study_chain.sh` (and `offline_chain.sh`), right after sourcing:
    `declare -F other_chain_idle > /dev/null || stop_chain "chain_helpers.sh beside the driver is older than the driver: install the current one"`.
  - In the ops doc, make reinstalling `offline_chain.sh` (at its HOLD, with the new helpers) part of installing step 2,
    or say plainly that until then O1's switch is unguarded and must wait for step 2's HOLD by hand.

### Nits

**N5.** `src/lean_search/rl/tree_slices.py:148-150`: the clash check spans all slices. A clash only matters within one
slice directory, so a future multi-phase, multi-slice cut would be refused needlessly when two phases reuse a basename
in different slices. Checking per slice would be exact. It is also an `assert` on input data: under the user's
convention a `ValueError` fits better, and `slice_trees.py` would then print a message rather than a traceback. The
driver's STOPPED text quotes only the last line either way.

**N6.** `src/lean_search/rl/learning_rate_step.py:78-87` (phase-1 seeds, BB's fix): fine for the rounds. Note in the
report that only the seeds and the trees match arm A's phase 1; the trainer (`grpo_phase.py` against the persistent
one) still differs, as the docstring says.
