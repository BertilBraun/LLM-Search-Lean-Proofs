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
