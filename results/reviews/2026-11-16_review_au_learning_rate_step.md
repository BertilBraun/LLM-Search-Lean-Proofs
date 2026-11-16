# Review AU: step 2's study driver (learning rates), node operations

Branch `worktree-agent-a576d0540c85ea253` (4 commits on master `4263d98`, head `8c631b0`). Focus: whether
`deployment/study_chain.sh` under supervisord runs the whole step unattended and correctly on the node. Read against the
real tools (`arm_loop.sh`, `grpo_loop.sh`, `stop_model.sh`, `background.sh`, `environment.sh`, `server_pid.sh`,
`slice_trees.py`, `grpo_phase.py`, `grpo_expert_iteration.py`, `held_out_evaluate.py`, `rank_learning_rates.py`,
`node_checks.py`, `rl/loop.py`'s finish path), the step-1 driver of 2026-11-15, and the node itself (read-only: state
directory empty, no `loop.pid` under `runs/`, `held_out_v0` complete with 512 trees and `"dropped": []`, its
`checkpoint.json` in today's `HeldOutRunStart` form, node environment sets the two lists and no `BACKGROUND_CPUS`, PID 1
is `bash /.launch` and no zombies exist). The branch's three suites pass in WSL: 137 passed.

**Verdict: merge after fixes** (B1 and S1-S3 before installing; the rest can follow).

## Blocking

**B1. The HOLD leaves the policy servers on the last variant's weights, and the next step's launcher keeps them.**
`deployment/study_chain.sh:266-288`; `deployment/arm_loop.sh:101`; ops doc line 275 ("the servers stay up").
After S3b every policy server runs the merge of the last held-out run in `held_out.tsv` (`step2_C_w4_1e-4`):
`held_out_evaluate.py` restarts them onto each variant and keeps a merge "a server runs from". The step ends in HOLD
with them up. Step 3 starts an arm with `deployment/arm_loop.sh --mode … arms/A.toml`, which runs `grpo_loop.sh servers`
— and that keeps every server that answers, whatever it holds (the driver's own comment at lines 92-93 says so; the
loop's restart path does no weight check at start, `VllmServers.check` returns at once for `swap = "restart"`). So arm
A's phase 1 would sample with C's trained policy while its trainer and KL reference are v0: silently wrong trees and
ratios for the first phase of the first arm, the very thing S1's `stop_model.sh --all` guards against.
Fix: `deployment/stop_model.sh --all` before writing HOLD (the GPUs are idle in HOLD either way; refusal → STOPPED as in
S2), and say in the HOLD text and the ops doc that the servers are stopped. If they must stay up, the HOLD text and the
doc must at least say "stop_model.sh --all before any arm_loop.sh".

## Should fix

**S1. A held-out run that dropped states is marked done, and the step then stops at the very end.**
`deployment/study_chain.sh:140-147`; `experiments/held_out_evaluate.py:201-202`; `src/lean_search/rl/fixed_targets.py:146-147`;
`experiments/rank_learning_rates.py:89-92`.
When the servers fail repeatedly but within the restart allowance, `held_out_evaluate.py` writes `summary.json` with a
non-empty `dropped`, logs "rerun under the name" and exits 0. The driver marks `done_held_out_<name>`. Hours later
S4's `rank_learning_rates.py` refuses ("lacks N of the 512 states' trees") → STOPPED "rank_learning_rates.py failed".
Recovery needs `done_held_out_<name>` deleted, which the ops doc does not say (it says "a held-out run resumes its
states", true only for a non-zero exit). Server crashes are not hypothetical (four segfaults on the first node).
Fix: after exit 0, check `held_out_evaluations/held_out_<name>/summary.json` has `"dropped": []` (a one-line
`python -c` or a `learning_rate_step.py check-held-out` subcommand); otherwise `exit 1` so the next start resumes the
missing states under the same name (attempts still bound it). Add a fake scenario for it.

**S2. The slicing can race the finishing loop and STOP the chain.**
`deployment/study_chain.sh:100-113, 126-127`; `src/lean_search/rl/loop.py:1002-1013, 1064-1096`; `experiments/slice_trees.py:41-42`.
The loop writes `finished.json` first (`finish_run`), then cancels the searches and background tasks, saves progress,
writes the status and only then removes `loop.pid` and exits. The driver leaves its poll as soon as `finished.json`
exists and runs `slice_trees.py`, which refuses while that run's `loop.pid` names a live process — and the driver
turns that refusal into STOPPED at once (no retry for slicing). With a 60 s poll and a shutdown of seconds, a few
percent of runs stop here for nothing, idling the node until someone looks.
Fix: after the poll loop, `while loop_alive; do sleep 10; done` (bounded, e.g. 10 minutes, then exit 1), before
`finish s1_sampling`.

**S3. The GPU-free check may be blind in this container, and its advice may name PIDs that do not exist here.**
`deployment/study_chain.sh:162-172`; ops doc "Failures".
Inside Docker without the host PID namespace, `nvidia-smi --query-compute-apps` commonly lists nothing (or host PIDs)
even while GPUs are in use. Nobody has run it on this node (the doc lists only "empty output when no process holds a
GPU" as unseen; the opposite case matters more). If it is blind, `gpus_free` always passes: orphaned torchrun workers
of a SIGKILLed round (the case it exists for; `loop_services.py:341` confirms they outlive torchrun) hold ~20 GiB per
GPU, the next round OOMs three times and the chain STOPs as "round … failed 3 times", or S3b's server start fails —
both with a misleading cause. Fix: decide free by memory, which works in containers:
`nvidia-smi --query-gpu=index,memory.used --format=csv,noheader,nounits` with every GPU below ~1 GiB, and keep the
compute-apps list only as the message. Smoke-check both commands once while the servers are up (below). Also drop
`2>&1` from the capture: any warning line on stderr currently counts as a holder.

**S4. The report subcommand's file reading is untested, and it runs last.**
`experiments/learning_rate_step.py:171-240`; `tests/rl/study_chain_fakes/python` (`report` is a stand-in).
`round_record`, `signal_ranking`, `v0_baseline`, `read_durations` on a real `timings.tsv`, `RunFinished` from
`finished.json`, `PhaseOutcome` from `phase.json` and `TrainingSummary` from `training_summary.json` are never run
together: unit tests build `StepReport` directly, the driver test fakes the command. A failure here STOPs the step
after 8-11 node hours (recoverable by hand, but the HOLD then never comes by itself). Fix: one CLI test of `report`
over a fixture state directory (timings, dry-run logs, rank_*.txt, phase.json/training_summary.json written by the
real dataclasses' `to_json`, held-out runs of a few states).

**S5. The driver tests never exercise the paths most likely on the node.**
`tests/rl/test_study_chain_script.py`, fakes. Untested:
- a live loop (`loop_alive` true) and the finished-but-alive window of S2: the fake `arm_loop.sh` either finishes at
  once or leaves a dead pid;
- `arm_loop.sh` failing (`fail_sampling` exists in the fake, no test uses it): three failed starts → STOPPED;
- a background build still running when the driver exits 1 and restarts (`builds_running` true across instances), and a
  background build failing then built in the foreground (`fail_build_*` unused); every kill test kills the whole group,
  which is the one case where the build dies with the driver;
- `fail_servers` (`grpo_loop.sh servers` failing before a held-out run);
- a held-out exit 0 with dropped states (S1).
Each is a few lines with the existing fakes; add at least the first three.

## Nits

**N1.** `deployment/study_chain.sh:185-190, 205`: `builds_running` trusts a pid file across reboots; after a container
restart the old builds pid could be any new process whose cmdline holds `study_chain` — including the new driver itself,
and then `ensure_builds` waits on itself forever. Also `while builds_running` has no bound for a hung build. Record and
compare the process start time (as `server_pid.sh` does), exclude `$$`, and bound the wait. Same idea for `loop_alive`
(line 89; low risk here since PIDs are in the 270,000s and restart near 1).

**N2.** `deployment/study_chain.sh:226-250`: a round whose trainer exited 0 but whose driver died before `finish`
(between the completion check and `touch`) is moved aside and trained again (~0.5 h). Harmless but avoidable: on an
attempt after the first, an output with every completion file could be accepted (phase.json / training_summary.json are
written last by the main rank).

**N3.** `deployment/study_chain.sh:75-80`: `mode.recorded` is written on the first start that passes `check-mode`, even
if a later check STOPs before anything sampled. Changing the mode then needs `mode.recorded` deleted; the doc does not
say so.

**N4.** Ops doc, "Stopping safely" (line 340): `supervisorctl stop` signals only the current driver's group. A
background build started by an earlier instance (before an exit 1) or a shared loop started by an earlier instance
survives it. Say so, with how to find them (`builds.pid`, `followup_shared_sampling/loop.pid`).

**N5.** Ops doc line 318: "A later driver change is installed the same way" — add that it takes effect only at the
next start, and that `supervisorctl restart` mid-step kills the running loop, round or held-out run (and, in S1, uses
up one of the three `s1_sampling_start` attempts).

**N6.** Ops doc line 273 says S3b runs `grpo_loop.sh servers` once; the driver runs it before every held-out run
(harmless: answering servers are kept). The first call also starts the four value servers, which no held-out run uses
(a minute or two of start-up, no harm to the policy servers' memory).

**N7.** `deployment/study_chain.sh:126-127`: slicing has `attempt` but any failure STOPs at once, so the attempt count
is never used; either retry (exit 1) or drop the `attempt`.

## Checked and fine

- Every command line against the real CLI: `arm_loop.sh --kind … --mode … <overlay>` (parse order matches),
  `slice_trees.py`, `held_out_evaluate.py` (absolute `--loop-config` survives `REPOSITORY_DIRECTORY /`),
  `grpo_phase.py --part policy` with the loop's replay files resolved under `$LEAN_SEARCH_DATA`,
  `grpo_expert_iteration.py --config … build|train [--dry-run]`, `rank_learning_rates.py --v0 --variant …`,
  `stop_model.sh --all`, `LOOP_CONFIG=… grpo_loop.sh servers`. Completion files match what the trainers write last
  (`phase.json` + `policy/adapter`; `training_summary.json` + `adapter`); the dry-run regex and the refusal prefix match
  `run_training`'s prints; the shared loop config path matches `followup_arm.py`'s output; slice links are absolute
  `*.json.gz` symlinks that both trainers' globs read.
- Restart semantics: markers, `started_`/`timings.tsv`, attempts per step with STOPPED on the 4th, half-trained outputs
  moved aside, slices moved aside, `write-configs` idempotent, mode pinned by `mode.recorded`, HOLD/STOPPED exit 0 at
  once. fd 3 redirections nest correctly; `exit` inside the `while … done 3<` loops and the process substitution exits
  the driver; the background subshell never calls `stop_chain`.
- supervisord: `startsecs=0` is right (with step 1's `startsecs=10` an immediate exit 0 counts as a failed start and is
  retried); `autorestart=unexpected` + `exitcodes=0` retry only non-zero exits, paced by the 60 s start sleep;
  servers are in their own sessions (`setsid`) and survive `stopasgroup`.
- Node rules: no name-pattern kills, no reboot, no tokens, no git writes (`rev-parse` only), CPU lists from the node
  environment with `BACKGROUND_CPUS` refused, Lean work through `background.sh`, rounds on `TRAINING_CPU_LIST`,
  `HF_HUB_OFFLINE=1`; installed as a copy and replaced by `mv`.
- Servers: stopped only through `stop_model.sh` (S1's first start, S2), its refusal → STOPPED; held-out runs put their
  own adapter on the policy servers, so the weights at each run's start are right; S3a runs on the loop's v0 servers.
- The earlier v0 run on the node (`held_out_v0`) has the same states file and digest the report will check.

## Must be smoke-checked on the node at first run

1. `nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader` while the servers are up: does it list the
   vLLM processes, with container PIDs? And empty output with nothing on the GPUs (S3).
2. S1: `arm_loop.sh` with `--mode` starts a sampling-only loop; `finished.json` at 48M; `loop.pid` gone and the process
   exited before slicing (S2); `finished.json`'s lost tokens.
3. Slices: `manifest.json` token counts per slice; trees in slice 4 all of version 0.
4. S3a: whether the policy servers are skipped or restarted onto the v0 merge; run time; `summary.json` `dropped` empty.
5. First GRPO round: wall time, peak GPU memory, `phase.json` trees/groups/steps, compile time; `nr_throttled` while the
   background builds run beside it on the Lean CPUs (16 processes) and host memory of both together.
6. Dry runs: no "train would refuse" line for a finished sampling-only run (`stopped_loop_refusal` reads its progress
   stage), steps > 0 for window 1 (DESIGN expected only ~8), time on unpinned CPUs.
7. First C round under torchrun: training time, `training_summary.json`, replay-loss change.
8. First S3b run: 8 servers started on v0, then the policy servers restarted onto the variant's merge; merges deleted
   after; ~12 min per run.
9. The report renders, and `supervisorctl status study_chain` shows EXITED (not BACKOFF/FATAL) after HOLD; servers'
   state at HOLD per B1.

## Re-review (2026-11-16)

Fixes `8c631b0..e91d7fa` (head `e91d7fa`), read against the same tools. WSL: `test_study_chain_script.py`,
`test_learning_rate_step.py`, `test_study_commands.py`, `test_learning_rate_report.py` 196 passed;
`test_followup_arms.py`, `test_rate_ranking.py` 72 passed.

**Verdict: merge.** Every blocking and should-fix finding is fixed; what remains is nits and the node smoke checks.

| Finding | Status | Where / note |
|---|---|---|
| B1 servers left on the last variant at HOLD | Fixed | `study_chain.sh:331-335`: `stop_model.sh --all` after S4 on every start that reaches it, refusal → STOPPED (a later start retries it, S4 being done); HOLD text, header and ops doc say the servers are stopped and why. Test checks it is the last step. |
| S1 dropped held-out states marked done | Fixed | `study_chain.sh:158-164` + `learning_rate_step.py check-held-out` (reads `summary.json` through `EvaluationSummary`); exit 1, next start resumes under the name, bounded by the run's attempts. Two tests; ops doc updated. |
| S2 slicing racing the finishing loop | Fixed | `study_chain.sh:120-127`: waits for `loop_alive` to end, 600 s, then exit 1. The fake loop now lives across its `finished.json` and the fake `slice_trees.py` refuses beside it. See N9 below. |
| S3 GPU check blind in a container | Fixed (needs the smoke check) | `study_chain.sh:181-195`: free = every GPU under 100 MiB by `--query-gpu=index,memory.used`, four GPUs required, process list only shown, stderr no longer captured. The "idle reads 1 MiB" premise is listed as not yet seen on the node; keep smoke check 1 (run it once with the servers stopped). |
| S4 report untested end to end | Fixed | `tests/rl/test_learning_rate_report.py`: the CLI over files written through the production dataclasses, including a disagreeing rank file and an unreadable earlier run. |
| S5 untested driver paths | Fixed | Live loop, `arm_loop.sh` failing 2 and 3 times, a build alive across a restart, a failing build rebuilt before C, `grpo_loop.sh servers` failing, dropped states, all added. |
| N1 pid files across reboots, unbounded build wait | Partly | `builds.pid` now holds pid and start time, excludes `$$`, wait bounded at 3 h → STOPPED. `loop_alive` still trusts `loop.pid` alone (low risk; PIDs on the node are ~275,000). |
| N2 finished round retrained | Fixed | `study_chain.sh:265-271`: with an attempt recorded and every completion file present the output is kept. See N10. |
| N3 changing the mode before sampling | Fixed (doc) | Install step 2 names `mode.recorded` and `mode.recorded.txt`. |
| N4 groups an earlier instance started | Fixed (doc) | "Stopping safely" names `loop.pid`, `builds.pid` and how to stop each. |
| N5 driver changes take effect at the next start | Fixed (doc) | Install step 3. |
| N6 servers before every held-out run | Fixed (doc) | S3b row describes it, value servers included. |
| N7 slicing's unused attempt | Fixed | `attempt s1_slices` removed. |

The new code, checked: `check-held-out`; the memory check (`awk -F', *'` on `nounits` output, count of lines); the
bounded waits; `process_start` (field 22 of `/proc/<pid>/stat`, as `server_pid.sh` reads it); `sampling.json` written
beside every loop.toml by `followup_arm.py` and an arm refused unless its record equals the shared run's (search config
path, expansions, sha256), with a fallback for configs written before the record existed; `training_search_refusal`
(no per-search token cap) in both `check-mode` and `followup_arm.py`; the mode's search config sha256 in `mode.txt`,
compared on every start with `mode.recorded.txt`; `modes/no_reasoning.toml` and
`search/no_reasoning_student_v2.toml` (differs from `visible_student_v2.toml` only in `max_depth` 64, `depth_weight`
0 and `visible_reasoning` false; no token cap, so `check-mode` accepts it); the second v0 run `step2_v0_end` as the
last line of `held_out.tsv` (its own name, so its `checkpoint.json` cannot clash with `step2_v0`; ranking still pairs
with `step2_v0`); `git_revision` no longer failing the report. Nothing broke; new nits only:

**N8.** `study_chain.sh:79-84`: `mode.txt` captures stderr too (`2>&1`) and is now compared byte for byte with
`mode.recorded.txt` on every start. Any non-deterministic line `check-mode` writes to stderr (a library warning with a
path or time in it) would STOP the chain as "the mode differs". Compare stdout only (write stderr elsewhere).

**N9.** `study_chain.sh:121-124`: the exit 1 after 600 s counts no attempt, so a loop process that never exits (hung
shutdown, or a reused pid in `loop.pid`) makes supervisord restart the driver every ~11 minutes forever, with no
STOPPED to tell anyone. Count an attempt (`attempt s1_loop_exit`) or stop the chain.

**N10.** `study_chain.sh:265-271`: the kept output is judged by the completion files existing, not by the trainer's
exit. That is sound because both trainers write them last, but `phase.json` is written with `write_text`, not
atomically: a kill during that write leaves a truncated file that is accepted and only fails the report at S4. Writing
it atomically in `training_phase.py`, or parsing it here, closes that.

**N11.** `experiments/followup_arm.py:126-136` (pre-existing, slightly wider now with a third file): a directory left
with only some files (killed between `mkdir` and the last write) is refused as "holds other" on every later start, so
a shared-sampling restart would use up its three attempts and STOP. Write to a temporary directory and rename it.
