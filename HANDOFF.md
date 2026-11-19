# Handoff: the follow-up study of the Lean prover project

Written 2026-11-16 by the orchestrating agent for the agent that takes over on a new Claude account. Same PC, same
repository, same rented node; no conversation history and no running subagents carry over. Everything needed is in this
file and the files it points to. Keep this file current while you work, or replace it with your own.

**State at a glance (2026-11-19, about 13:00 UTC; updated by the second orchestrator)**

- Done: step 1 (incl. the reasoning comparison: no reasoning +4.9 points at equal tokens but Lean-bound, 1.8x the
  time), the offline run O2 (545 of 2,000: FAILED the owner's gate against v35, so the arms sample WITH visible
  reasoning), step 2 (A's learning rate: 2e-5 and 5e-5 tied; the owner chose 5e-5), the C/D smoke test (accepted by
  hand: its wake-memory gate read the line after the deliberate kill), arm C (probe 1,049 of 2,000: +16.7 points over
  v0, −9.3 behind v35 with the final value model). Details: `results/followup_progress.md`.
- Arm A's first run (stopped by the owner for a bare-`have` drift) is kept as `runs/followup_A.bug_20261119T124352Z`.
  The reward fix (master `2a1caf4`) is deployed (b5f6425, 2026-11-19 12:44 UTC).
- Running unattended: the arms driver `deployment/arms_chain.sh` (supervisord `arms_chain`, state
  `/workspace/runs/arms_chain/`, order file `smoke C A D`) runs arm A's rerun from v0 (started 12:45 UTC 2026-11-19,
  about 15 h plus a 2.5-h probe run), then arm D. The owner's stop rule for A: `experiments/claim_watch.py` after
  phases 2 and 4 (`results/followup_progress.md`, "Arm A's rerun"). Disk: 113 GB free after removing regenerable
  merged weights of finished runs (an arm needs about 38 GB).
- `on_health_stop = continue`. Search-efficiency switches only in the arms' sampling. Arm B dropped; O1 last, on the
  owner's word. Review letters used up to `bg` (next: `bh`). Spend about $75 of $190 at $0.83/h. The PC sleeps at
  times: the watchdog and the pull pause, the node does not.

## 1. First hour: what to do

1. Read, in this order: this file; `results/followup_progress.md` (the study's state, results and the owner's
   decisions, kept current); `results/followup_node_operations.md` (how the node is set up and operated; written by the
   agent that ran it — if it is missing or thin, section 6 below is the fallback); `DESIGN.md`, section
   "Follow-up study: controlled arms (agreed 2026-11-14)".
2. Check the node (section 6 has the command). Compare with what section 6 says it should be doing.
3. Set up the 30-minute watchdog (section 6) and confirm the results pull on the PC is alive (section 7).
4. Check the arms driver: `tail /workspace/runs/arms_chain/chain.log`, the running arm's `loop.log` (phases, health
   alerts), STOPPED/HOLD markers; its section in `results/followup_node_operations.md` ("The arms driver") has every
   marker, the pause files, the owner's word files and the rerun path. Report each arm's probe-run result to the owner.
5. Tell the owner in a few lines where things stand. He checks in about twice a day and wants short, concrete updates.

## 2. The project in brief

- **What it is.** LLM-guided proof search in Lean 4: a policy (Qwen3.5-4B with a LoRA) writes a short explanation and
  a block of tactics for a proof state; a value model (Qwen3.5-2B with a LoRA) ranks states; best-first search with 8
  samples per expansion; Lean checks every tactic. An RL loop ("search-tree GRPO") trains the policy and value model on
  its own search trees. Repository: `C:\Projects\Lean-Proofs` (GitHub `BertilBraun/LLM-Search-Lean-Proofs`, public,
  branch `master`).
- **The first RL run** (`grpo_loop_v1`, 2026-10-29 to 11-01, about $75) is written up in
  `results/grpo_loop_v1/README.md` and summarised in `results/project_report_2026-11-14.md`. Its data and adapters are
  public on Hugging Face (dataset `BertilBraun/lean4-search-grpo-qwen3.5-4b`, model repo
  `BertilBraun/lean4-prover-qwen3.5-4b-grpo-lora`).
- **The follow-up study** (this work, since 2026-11-14) asks what matters in that loop, measured on held-out
  statements from the loop's own pool ("in-pool"), with controls. The owner wants something worth writing up without
  paying for ambiguous results. Whether it becomes a homepage post or a report is decided after the results; for now it
  is internal documentation.
- **The owner** (Bertil) is an ML engineer with search, training and scaling experience (he built an AlphaZero-style
  chess engine on rented nodes). He rents the hardware himself, is cost-conscious, dislikes idle GPUs, and reads short
  updates, not long ones.

## 3. Standing rules (the owner's, all still in force)

- **Subagents:** implementation, analysis and review run in subagents on Opus 5.5 at high effort. Two independent
  reviews after every implementation wave, then fixes, then a re-review by the same reviewers, then merge. Reviews are
  files in `results/reviews/` named `<date>_review_<letters>_<topic>.md`; the last used letters are `bg` (next: `bh`).
- **Usage:** running 5-8 Opus subagents at once exhausted the 5-hour usage limit on 2026-11-14 and left the node idle
  for hours. Keep few agents running, have node agents report on events rather than on a timer, and make node work
  self-sustaining so it does not depend on an agent being awake.
- **Node:** never kill processes by name pattern (`pkill`, `killall`, `pgrep -f`-driven kills) — PIDs only. Never
  reboot the instance. Never leave GPUs idle without a reason; never leave node jobs unwatched (watchdog). Nothing runs
  beside an evaluation or a sampling loop except light samplers. Only logs, results and LoRA adapters are copied to
  the PC, never base models or raw data.
- **Secrets and privacy:** never print, store or generate tokens or passwords; no access token goes on the node
  (everything needed is public). The owner's email address is private.
- **Money:** the node bills by the hour; ask before any new kind of spend (renting, API costs). The owner has said to
  run the planned experiments without asking each time; pivots and changes of plan go to him. Credit loaded on
  2026-11-16: $190, not a cap.
- **Publishing:** pushing `master` to the public GitHub repository is the normal deployment path. Anything else public
  (Hugging Face uploads, write-ups) needs the owner's explicit word.
- **Code style** (`CLAUDE.md` in the user's global settings): no abbreviations in names; type hints on all functions;
  dataclasses or named tuples rather than bare dicts between functions; `match`/`case` for dispatch; no comments unless
  the why is non-obvious (one short line); no defensive checks for impossible cases; `assert` for invariants,
  `raise ValueError` for bad user input; tests call production code directly, one logical assertion per descriptively
  named test, `pytest.mark.parametrize` for similar cases; `ruff format` and `ruff check` clean before committing.
- **Commits:** on `master` after review; messages end with the attribution line the harness gives the session
  (`Co-Authored-By: Claude <model> <noreply@anthropic.com>`; subagents use their own model's line). Never commit or
  push from the node.
- **WSL:** local tests run in WSL (`~/lean-proofs`); keep its memory under 12 GB.
- **Talking to the owner:** lead with the result or the decision needed; short sections; numbers with their units;
  say plainly what failed and what a thing cost. Keep `results/followup_progress.md` current — he reads it.

## 4. File map

| What | Where |
|---|---|
| The study's state, results, decisions, plan, spend | `results/followup_progress.md` |
| Node setup and operations | `results/followup_node_operations.md` |
| Experiment design (arms, matching, evaluation rule, automatic rules, work packages) | `DESIGN.md`, section "Follow-up study: controlled arms (agreed 2026-11-14)" |
| Step-0 analyses of the old run (compute, pool, noise floor, training signal) | `results/followup_step0/*.md`, scripts in `experiments/analysis/` |
| All reviews of the study (design AA, AB; code AC to AT) | `results/reviews/2026-11-14_*`, `2026-11-15_*`, `2026-11-16_*` |
| Deployment and tools (launcher, serving scripts, node settings file, known limits) | `deployment/README.md`, `src/lean_search/rl/README.md`, `src/lean_search/policy/README.md` |
| Study configs | `experiments/configs/grpo/followup/` (`base.toml`, `probe_evaluation.toml`, `step1/`, `arms/`, `shared_sampling.toml`) |
| Study commands | `experiments/probe_evaluate.py`, `probe_runs.py`, `probe_compare.py`, `held_out_evaluate.py`, `followup_step1.py`, `followup_arm.py`, `slice_trees.py`, `rank_learning_rates.py`, `node_checks.py`; `deployment/probe_runs.sh`, `arm_loop.sh`, `grpo_loop.sh`, `serve_model.sh`, `stop_model.sh`, `background.sh` |
| Results copied from the node (not in git) | `node_backup/2026-11-15/live/` (pulled every 10 minutes), `node_backup/2026-11-14/` (first node: probe draw, one anchor run, crash logs) |
| The old run's published data, local copy | `node_backup/2026-11-01/hf_dataset/` |
| Project memory of the previous account (may not be visible to you) | `C:\Users\berti\.claude\projects\C--Projects-Lean-Proofs\memory\` |

## 5. Results so far

Probe v2: 2,000 held-out pool statements in seven bands by proof length, 16 expansions, 112 searches at a time. It
excludes every statement the old run searched and near-duplicates of training data. Two identical runs differ by 0.1
points and one paired comparison resolves about 2.6 points.

| Policy | Value model | Solved of 2,000 | Run name on the node |
|---|---|---|---|
| v0 (the SFT policy, the arms' start) | none, whole-completion order | 642 (32.1%) | `step1_run6_v0_no_value` |
| v0 | none, block-sum order | 633 (31.65%) | `step1_run6_v0_no_value_block_sum` |
| v0 | v0 — the baseline ("anchors"), twice | 713 and 716 (35.7%) | `step1_run1_v0_value_v0`, `step1_run2_v0_value_v0` |
| v0 | the old run's final value model | 875 (43.75%) | `step1_run5_v0_value_final` |
| v35 (the old run's final policy) | v0 | 1,083 (54.15%) | `step1_run8_v35_value_v0` |
| v35 | the old run's final value model | 1,236 (61.8%) | `step1_run7_v35_value_final` |

- The starting value model is worth about 4 points over a policy-only search (+3.6 and +4.1, intervals exclude 0).
- The old loop's value training: +8.0 points with the policy unchanged (95% +6.4 to +9.7).
- The old loop's policy training: +18.4 points with the value model unchanged (95% +16.6 to +20.2).
- With v35's policy the value model's gain is +7.6 points, and with the final value model the policy's gain is +18.1:
  the two gains add up (predicted 62.1%, measured 61.8%).
- So the old run's in-pool gain is real and large (+26.1 points, 95% +24.2 to +28.1), about 70% from the policy and
  30% from the value model. Which ingredient of the loop produced the policy's gain is what the arms test.
- Reasoning at equal tokens: only a hint so far. A 200-statement pilot without reasoning solved 76 against 70 and 75
  with it; that pilot was rejected by the acceptance rule (2 of 200 searches hit the wall cap) and is being repeated
  at a doubled cap.
- Other settled points: the 60-second tactic limit fires about 3,000 times per run but does not change where searches
  go (a replay of 300 timed-out steps: none succeeds alone), so the protocol stays; the old run never trained the
  policy on unsolved trees; per-tactic graph credit and pure outcome credit agree in sign on 97% of samples.

Full tables, per band, with intervals: `results/followup_progress.md`, "Results so far".

## 6. The node

- **Access:** `ssh -i ~/.ssh/vast-ssh -p 21232 root@50.173.30.254` (Vast.ai container; $0.83/h since 2026-11-15 about
  08:30 UTC). SSH sometimes hangs: wrap checks in `timeout 40` and use `-o BatchMode=yes -o ConnectTimeout=12`.
- **Hardware:** 4x RTX 3090; 2x EPYC 7642 (192 threads); a cgroup v1 CPU quota of 105.3 cores; 183 GiB memory limit;
  300 GB disk. `/workspace` is NOT a volume: everything on the node is lost if the instance is destroyed.
- **CPU layout** (in `/workspace/node_environment.sh`, sourced by `deployment/environment.sh`): Lean on socket 1
  (`BACKGROUND_CPU_LIST=48-95,144-191`), the 8 model servers and training on socket 0
  (`SERVER_CPU_LIST=TRAINING_CPU_LIST=0-47,96-143`). Lean REPLs lower their own priority; nothing needs to raise one
  (the container cannot).
- **Fixed study settings:** 112 concurrent searches for probe runs and sampling, 56 for held-out states; per-statement
  wall cap 7,200 s (14,400 s for the token-capped reasoning runs); servers changed by restart
  (`[serving] swap = "restart"`), never by in-place swap.
- **The first node** (2026-11-14, destroyed) had three host reboots and four server segfaults in thirteen hours; this
  one has run since 2026-11-15 without a crash or reboot.

**What runs on the node now and what it will do by itself**

- A chain driver under the node's supervisord (`step1_chain`; files in `/workspace/step1_chain_tools/`, state and logs
  in `/workspace/runs/step1_chain/`, the log is `chain.log`). It marks finished steps on disk and continues at the
  first unfinished step after a restart; a failed check or a rejected run stops it with a `STOPPED` marker.
- At 17:50 UTC on 2026-11-16 it had finished run 7, deployed master by itself (node-local edits kept) and was
  putting the 8 servers back on v0's weights. From there it runs the reasoning comparison from
  `experiments/configs/grpo/followup/step1/runs_reasoning.toml`: step e1, the pilot
  `step1_run4_pilot_no_reasoning_T_cap14400` (200 statements, file order); then, after deploying master again
  (9834972 or later, which has the start order), step e2: `step1_run3_visible_T` and `step1_run4_no_reasoning_T`
  (2,000 statements each, T = 26,804 generated tokens per statement, depth weight 0, wall cap 14,400 s, both started
  longest expected search first). Expected: pilot 1-2.5 hours, each full run 3-5 hours.
- After run 4 it writes the comparison files (run 3 against run 4 across search modes, the solved-within-N-expansions
  view, run 3 against the anchors, the sampler's bulk and tail readings) under `/workspace/runs/step1_chain/`, then
  runs step f, the start order's check run (`step1/runs_order_check.toml`: `step1_run9_v0_value_v0_ordered`, about 2.5
  hours), then stops with a `HOLD` marker: waiting for the owner's decision on the arms' mode.
- If the pilot is rejected again, e2 does not run; step f runs instead and a marker says why.
- This sequence was requested from the node agent at 17:52 UTC; `results/followup_node_operations.md` says what was
  actually set up. If `chain.log` shows something else, the operations document and the log are right, not this file.
- A second driver, `study_chain.sh`, is prepared for the learning rates and the arms and is on hold until the owner's
  decision after the reasoning comparison.
- Node-local edits to the checkout (recorded with copies and diffs in `/workspace/runs/step1_chain/edits/`): the token
  budget T = 26,804 in the two token-capped search configs; the three calibrated automation constants (-56.4 for the
  whole completion, -5.35 for the block sum, -0.142 for the block mean) in the value-free configs; filled run lists.
- The details, exact commands and marker meanings are in `results/followup_node_operations.md`.

**Status check** (read-only; run from Git Bash on the PC):

```bash
timeout 40 ssh -i ~/.ssh/vast-ssh -p 21232 -o ConnectTimeout=12 -o BatchMode=yes root@50.173.30.254 'date -u +%H:%M; uptime | cut -c1-34; nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader | tr "\n" " "; echo; grep nr_throttled /sys/fs/cgroup/cpu/cpu.stat; tail -2 /workspace/runs/step1_chain/chain.log | cut -c1-170; ps -eo pid,etimes,args | grep -E "probe_evaluate|grpo_loop.py|step1_chain.sh|study_chain.sh" | grep -v grep | cut -c1-160; tail -5 /workspace/runs/probe_evaluations/ledger.tsv | cut -f1,3,4,5,6,7; supervisorctl status | grep -v -E "caddy|portal|jupyter|syncthing|tensorboard|tunnel|cron"'
```

- **Normal:** all GPUs near 100% during the bulk of a run; a run's result count (in `chain.log`, `[n/2000]`) growing.
- **Also normal:** every run ends with a tail in which the last few long searches work in Lean and the GPUs read 0%
  (25-35 minutes on a 2,000-statement run, over an hour on a no-reasoning pilot). It is a tail, not a stall, as long
  as results still arrive every few minutes and a Lean REPL process is at full CPU.
- **Not normal:** GPUs idle with no probe or loop process and no `HOLD` or `STOPPED` marker explaining it; a changed
  boot time (`who -b`); `nr_throttled` climbing during a run.

**Watchdog.** A session-only recurring prompt every 30 minutes (CronCreate, e.g. `11,41 * * * *`): run the status check;
answer in one line if work progresses; act only if GPUs are idle without a reason, results stopped moving, the host
rebooted, or the PC's results pull is more than 25 minutes old. It dies with the session, so recreate it.

## 7. The PC side

- **Results pull:** a detached loop copies the node's small result files (no trees, no weights) every 10 minutes into
  `node_backup/2026-11-15/live/`. Script: `node_backup/2026-11-15/pull_results.sh`; its Git Bash pid is in
  `node_backup/2026-11-15/pull_results.pid`; `node_backup/2026-11-15/live/last_pull.txt` holds the time of the last
  successful pull. If it is stale, start the script again detached
  (`nohup bash node_backup/2026-11-15/pull_results.sh > node_backup/2026-11-15/pull_results.out 2>&1 &`) and update the
  pid file. Stop it by PID only.
- **When arms exist:** also copy each arm's retained LoRA adapters of phases 8 and 16 (policy and value) to
  `node_backup/2026-11-15/adapters/<arm>/`; later probe runs depend on them.
- **Tests:** in WSL, as `deployment/README.md` ("Local development (WSL)") describes. From Git Bash:
  `MSYS_NO_PATHCONV=1 wsl -e bash -lc "source ~/lean-proofs/deployment/environment.sh; cd /mnt/c/Projects/Lean-Proofs && export PYTHONPATH=\$PWD/src && pytest -q -p no:cacheprovider tests/rl -W ignore | tail -3"`.
  The whole suite (`tests` instead of `tests/rl`) takes 7-15 minutes (about 4,700 tests); run one at a time, two at
  once have made the WSL service drop a run. One Lean panic test is flaky under load and passes alone. A worktree is
  tested by pointing `PYTHONPATH` at its `src`.
- **Worktrees:** subagents work in git worktrees under `.claude/worktrees/`; many old ones exist and can be ignored.
- **Shell quirk:** long heredocs with quotes can fail in the Bash tool on this PC; write files with the file tool or
  a small Python script instead.

## 8. Code: two features merged on 2026-11-16, nothing in flight

Master is `467d97c` or later and pushed. The node runs `9a594b1` and deploys `9834972` by itself after the pilot; the
expert-iteration merge is not on the node yet and is not needed there before arm C. The full suite on the merged master (`467d97c`): 4,482 passed, 0 failed, 305
skipped. The two branches' own runs skipped only 43 (4,590 and 4,701 passed); the difference was not investigated and
is probably the Lean-dependent tests skipping under the plain command of section 7. Every merged package had two reviews and a re-review.

**A. Start order by measured search time** — MERGED 2026-11-16 (master `f29df21`; reviews AQ and AR with re-reviews
in `results/reviews/2026-11-16_review_aq_*` and `_ar_*`; full suite 4,590 passed).

- **What:** a probe run can start the statements with the longest expected search first
  (`submission_order = "longest_expected_search_first"`, `expected_search_seconds = <file>` at the top level of an
  evaluation config; default file order). The file `experiments/configs/grpo/followup/probe_v2_expected_search_seconds.tsv`
  holds each statement's mean search seconds over the five v0 runs. A run keeps its first session's order; a resume in
  another order or with another file is refused; a file lacking more than 1% of the run's statements is refused.
- **Where it is on:** only in configs named `*_ordered.toml`: `step1/token_capped_evaluation_ordered.toml` (the two
  full reasoning runs) and `step1/probe_evaluation_ordered.toml` (the check run in `step1/runs_order_check.toml`).
  `probe_evaluation.toml` itself stays in file order.
- **Why:** the owner proposed it to cut the idle tail of a run. Review AR's out-of-sample simulation on the recorded
  runs: file order takes 2.32-3.57 hours, the new order 2.41-2.88 hours; about 15 minutes saved per v0 run on average,
  40 and 16 minutes on the two v35 runs, and one run (block sum) gets 32 minutes longer. The gain should be largest
  where single searches can run for hours (the token-capped runs at the 14,400 s cap). An earlier version ordered by
  proof length and was dropped (reviews AO, AP): proof length does not predict search time.
- **What it costs:** it moves the Lean pressure and the GPU idle time to the START of a run: Lean demand of 102-110
  cores in the first 30 minutes against 42-55 in file order, on 96 Lean CPUs, and only 3-9 searches waiting on the
  model in the first hour. Low GPU use in a run's first hour is therefore expected in this order. The 200 Lean-heaviest
  searches see slightly more contention, so outcomes could shift a little; that is what the checks below are for.
- **The two full reasoning runs** both use it, so they pair cleanly with each other: both `run.json` files must show
  the same `start_orders` and file digest, and `probe_compare.py pair` must print no "orders differ" line. Run 3
  against the file-order anchors crosses orders and is descriptive only.
- **Checks before trusting a comparison ACROSS orders** (an arm's probe run in the new order would be compared with
  the file-order anchors): (1) after the first ordered run, `probe_compare.py load` per band against the range of the
  file-order runs, and its share of wall-clock stops; (2) the check run `step1_run9_v0_value_v0_ordered` (not an
  anchor, never pooled into the anchors) paired against each anchor: it passes if its difference to each is within
  their A/A difference (-0.1 points, interval -1.8 to +1.6) and its Lean-load figures match. If either fails, the
  arms' probe runs stay in file order (`probe_evaluation.toml`); if both pass, switch the arms' probe runs to
  `step1/probe_evaluation_ordered.toml` (or an arms copy of it) and say so in the progress document.

**B. Expert iteration inside the loop** — MERGED 2026-11-16 (master `467d97c`; branch head `041389e`, 11 commits;
reviews AS and AT with re-reviews in `results/reviews/2026-11-16_review_as_*` and `_at_*`; full suite on the branch
4,701 passed, 0 failed).

- **What:** a phase's policy update can be an expert-iteration round (supervised fine-tuning continuing the published
  adapter on the verified proof-graph blocks of the last W phases, 30% Lean and 10% math replay by completion tokens,
  one epoch, no KL penalty) instead of the GRPO update, or after it. The persistent trainer runs the round on the same
  resident policy; a phase publishes exactly one policy version. Description:
  `src/lean_search/rl/README.md`, "Expert iteration inside the loop".
- **Arm C** (`experiments/configs/grpo/followup/arms/C.toml`): `policy_update = "expert_iteration"`,
  `expert_iteration_every_phases = 1`. **Arm D** (`arms/D.toml`): `policy_update = "grpo_and_expert_iteration"`,
  `expert_iteration_every_phases = 4`, `credit = "per_tactic"`, KL reference stays v0. Both share the recipe
  `followup/expert_iteration.toml`. Both still carry PLACEHOLDER values: C's and D's expert-iteration rate (O2's choice,
  5e-5 or 1e-4) and D's GRPO rate (A's, from step 2); the window is set to 4 (owner, 2026-11-17). Contradictory keys
  (GRPO-only keys in C, round keys in A or B) fail at load.
- **Skipped rounds:** a round with too few examples, or whose data fills no optimizer step, is skipped and recorded
  with its reason (`no_optimizer_step`); C then keeps its policy for that phase, D publishes the GRPO update alone.
- **Restarts:** tested by simulation at every crash point (during the data build, the training, between D's two
  updates, while publishing; 80 crash-and-restart cases for arms A, C and D): one version and one record per phase and
  kind, nothing trained twice, a record line cut off by a crash is tolerated, a damaged complete line stops the loop.
- **Changed for arms A and B too:** a phase's GRPO and value-training records are now written once across a crash
  while publishing (master used to write them twice). Uninterrupted runs are byte-identical to before (pinned by
  `tests/rl/golden/grpo_only_loop.json`, captured on the old master).
- **Not testable locally, so smoke-test on the node before arm C or D runs** (one phase of each with a small token
  budget; the lists are at the end of both review files): real training of a round by the persistent trainer on 4
  GPUs and how long it takes; GPU memory after GRPO plus a round in one trainer process (the round's record holds peak
  ALLOCATED memory only — watch `nvidia-smi` for reserved); recompiles of the compiled layers; `/dev/shm` use of the
  weight handoff; the in-loop data build for a 4-phase window on real trees; one kill by PID during publishing
  followed by a restart.
- **Known small gaps, none blocking:** the round's selection and replay seeds change per phase, so replay-loss levels
  are not comparable across rounds; expert-iteration records have no dashboard page (`ExpertIterationPhase` is not in
  `monitoring/families.py`); the error for a damaged record line names no file or line, and cutting a torn line is not
  logged (review AT, N7).

## 9. Next steps, in order

1. **Reasoning comparison** (running by itself): the pilot, then `step1_run3_visible_T` and
   `step1_run4_no_reasoning_T`, then the start order's check run. The node writes these report files into
   `/workspace/runs/step1_chain/` (pulled to `node_backup/2026-11-15/live/runs/step1_chain/` on the PC):
   `run3_against_run4.txt` (the pair across search modes at equal tokens AND as "solved within 1/2/4/8/16
   expansions" — the owner asked for both views), `anchors_against_run3.txt` (descriptive: what the token cap and
   depth weight 0 cost the tuned visible search), `run3_load_against_file_order.txt`, `reasoning_readings.txt` (bulk
   and tail GPU use, tokens per second, Lean CPUs — the owner's worry is that without reasoning the search becomes
   CPU-bound and the GPUs idle), and for the check run `run9_against_step1_run1_v0_value_v0.txt`,
   `run9_against_step1_run2_v0_value_v0.txt`, `run9_load_against_anchors.txt`. Put the results into
   `results/followup_progress.md` and report to the owner. If the chain shows `STOPPED`, read the marker and
   `chain.log` first; the operations document lists every marker.
2. **Decision with the owner: do the arms sample with or without reasoning?** Proposed rule: switch to no reasoning if
   it is within noise of, or better than, visible reasoning at equal tokens and its bulk GPU use stays above about 90%.
   If no reasoning: also decide whether a search keeps 32 expansions (more statements per phase; recommended, because
   only solved trees train the policy) or gets about 2.3 times more.
3. **Learning rates, arm A only** (owner, 2026-11-17; about 3-4 node hours): v0 samples one phase of 12M tokens without
   training in the arms' mode; A's three per-tactic GRPO rounds from v0 on its trees (2e-5, 5e-5, 1e-4); held-out states
   for v0 (before and after) and each variant; `rank_learning_rates.py` for A. Arm B is dropped; C takes O2's rate and
   a 4-phase window, D takes C's rate and window and A's rate. Automated by `deployment/study_chain.sh` (with
   `chain_helpers.sh`, `study_chain.conf`, `experiments/learning_rate_step.py`): start it only after O2's gate has
   chosen the mode and the search-efficiency branch is merged and deployed, with the offline chain at HOLD; put the
   chosen mode file at `/workspace/runs/study_chain/mode.toml`, install as a copy (operations note, "The study driver:
   step 2"). It ends in HOLD with `learning_rates_report.md` (A's rate, and C's and D's rate read from O2's ranking)
   and the servers stopped. Superseded: the earlier plan of 48M tokens, four slices and ten rounds (A, B2, C with two
   windows). The rates then go into the arms' PLACEHOLDER values (as node-local edits, recorded like the others, or
   committed on the PC and deployed).
4. **Arms**, one after another, each from v0 and value v0, 16 phases of 12M generated tokens, value model trained
   every 2 phases: A (per-tactic GRPO), B (pure proof success), C (expert iteration), D (GRPO plus a round every 4
   phases). After each arm ONE probe run of its final checkpoint with its own value model. An arm that collapses is
   stopped by the automatic rule: capture what happened, leave it stopped, assess, report to the owner. Watch arm A's
   first pause closely: it is the first real training pause on this code (trainer on the training CPUs, restart of
   all servers onto the new version, held-out states, the phase record). Arms A and B can start as soon as their
   rates are known. Before arm C: deploy master `467d97c` or later to the node at a boundary and do the smoke run of
   section 8 B. Whether the arms' probe runs use the new start order depends on the check run (section 8 A).
5. **Second pass**, arm by arm, only after all four have one probe run: the final checkpoint a second time, the
   phase-8 checkpoint, and v0's policy with the arm's final value model.
6. **Later, on the owner's word:** second seeds of the interesting arms (`seed_offset`), miniF2F-valid for final
   checkpoints (the test split stays untouched), the write-up.

Rough costs on this node: a 2,000-statement probe run 3-3.5 hours ($3); an arm's loop about 20 hours ($16).

## 10. The owner's decisions so far

- **2026-11-14:** measure in-pool on a 2,000-statement held-out probe, miniF2F-valid only at the end; all arms from
  v0; arms matched on generated tokens of the training searches; each arm with its own best learning rate; value model
  trained in every arm; expert iteration with a fixed sliding window; when an arm goes wrong, automatic rules detect
  it, then we look at the cause together (a bug is fixed and affected arms rerun; otherwise the degradation is a
  result); the write-up's form is decided after the results.
- **2026-11-16:** arms A, B (pure proof success), C, D all run; no arm that learns from unsolved trees and no
  value-only arm; defaults 12M tokens per phase and 16 phases; evaluations breadth first (one final-phase probe run
  per arm, the rest later); learning rates chosen on held-out states without probe runs; the reasoning comparison
  runs BEFORE the arms and decides their mode; probe statements may be started in order of measured search time.

## 11. Things that were learned the hard way

- A run's last searches idle the GPUs; ordering by proof length makes it worse, ordering by measured search time helps.
- One timed-out or crashed step must not end a run: evaluations retry and restart servers themselves now; a run that
  used up its restarts exits with status 4, a run rejected for wall-clock stops with status 3 (repeat it at a doubled
  cap under a new name, with everything it is compared to at the same cap).
- Model servers are brought to new weights by restart, about 3 minutes; the in-place swap was followed by segfaults on
  the first node and is not used.
- Stopping servers is safe only through `deployment/stop_model.sh` (it verifies each process). After a host reboot,
  stale pid files are removed, never signalled.
- The container cannot raise process priority; only Lean REPLs lower theirs.
- 200-statement pilots cannot see a 4-point effect (their noise is about 3 points); full runs are needed for claims.
- A node agent that starts code work before queueing node work leaves the GPUs idle; queue node work first.
- Config edits made on the node (measured values filled into placeholders) are recorded there and must survive each
  deploy; nothing is committed or pushed from the node.
- Session restarts and usage limits kill subagents and session-only watchdogs but not the node's chain or the PC's
  pull loop; after any restart, check both and recreate the watchdog.

## 12. Spend

- First node (2026-11-14, destroyed): at most about $11, partly refunded by the provider.
- Second node: $0.83/h since 2026-11-15 about 08:30 UTC; about $28 by 2026-11-16 18:00 UTC.
- Estimate for the rest: reasoning comparison $14; learning rates $7; four arms with one probe run each $76; second
  pass $36.
