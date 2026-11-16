# Handoff: the follow-up study of the Lean prover project

Written 2026-11-16 by the orchestrating agent for the agent that takes over on a new Claude account. Same PC, same
repository, same rented node; no conversation history and no running subagents carry over. Everything needed is in this
file and the files it points to. Keep this file current while you work, or replace it with your own.

**State at a glance (2026-11-16, about 18:00 UTC)**

- Step 1 of the study (evaluations) is almost done; five full runs have answered its value-model questions and
  measured the old run's gain on a clean probe.
- The node is running by itself: the last of those runs, then the reasoning comparison (a pilot, then two full runs).
- Two code features are in flight on branches: a faster start order for probe runs (in review) and expert iteration
  inside the loop (implemented, not yet reviewed). Section 8 has their exact state.
- After the reasoning comparison the owner decides whether the arms sample with or without reasoning; then learning
  rates are chosen and four closed-loop arms run.

## 1. First hour: what to do

1. Read, in this order: this file; `results/followup_progress.md` (the study's state, results and the owner's
   decisions, kept current); `results/followup_node_operations.md` (how the node is set up and operated; written by the
   agent that ran it — if it is missing or thin, section 6 below is the fallback); `DESIGN.md`, section
   "Follow-up study: controlled arms (agreed 2026-11-14)".
2. Check the node (section 6 has the command). Compare with what section 6 says it should be doing.
3. Set up the 30-minute watchdog (section 6) and confirm the results pull on the PC is alive (section 7).
4. Pick up the two branches in flight (section 8) and the next steps (section 9).
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
  files in `results/reviews/` named `<date>_review_<letters>_<topic>.md`; the last used letters are `at` (next: `au`).
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
| All reviews of the study (design AA, AB; code AC to AR) | `results/reviews/2026-11-14_*`, `2026-11-15_*`, `2026-11-16_*` |
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
| v35 | the old run's final value model | 1,236 of 1,998 when last seen; finishing | `step1_run7_v35_value_final` |

- The starting value model is worth about 4 points over a policy-only search (+3.6 and +4.1, intervals exclude 0).
- The old loop's value training: +8.0 points with the policy unchanged (95% +6.4 to +9.7).
- The old loop's policy training: +18.4 points with the value model unchanged (95% +16.6 to +20.2).
- So the old run's in-pool gain is real, large, and came from both models. Which ingredient of the loop produced the
  policy's gain is what the arms test.
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
- From here it will: finish `step1_run7_v35_value_final`; update the node's checkout to master while keeping its
  node-local edits; put all 8 servers back on v0's weights; run the reasoning comparison from
  `experiments/configs/grpo/followup/step1/runs_reasoning.toml` — the pilot
  `step1_run4_pilot_no_reasoning_T_cap14400` (200 statements), then `step1_run3_visible_T` and
  `step1_run4_no_reasoning_T` (2,000 statements each, at T = 26,804 generated tokens per statement, depth weight 0,
  wall cap 14,400 s). The node agent was asked to pause after the pilot so the new start order (section 8) can be
  deployed before the two full runs; if nobody acts within about 15 minutes it starts them in file order.
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
  The whole suite takes about 7 minutes (about 4,500 tests). A worktree is tested by pointing `PYTHONPATH` at its `src`.
- **Worktrees:** subagents work in git worktrees under `.claude/worktrees/`; many old ones exist and can be ignored.
- **Shell quirk:** long heredocs with quotes can fail in the Bash tool on this PC; write files with the file tool or
  a small Python script instead.

## 8. Code in flight (two branches, not merged)

Master is `0191a12` or later and pushed. Every merged package had two reviews and a re-review.

**A. Start order by measured search time** — branch `worktree-agent-a8257711895071364`, commit `68e70fe`
(worktree `.claude/worktrees/agent-a8257711895071364`).

- **What:** probe runs can start the statements with the longest expected search first
  (`submission_order = "longest_expected_search_first"`, `expected_search_seconds = <file>`; default file order; no
  shipped config turns it on). The file `experiments/configs/grpo/followup/probe_v2_expected_search_seconds.tsv` holds
  each statement's mean search seconds over the five v0 runs. A run keeps its first session's order.
- **Why:** the owner proposed it to cut the idle tail of a run. Review AR's out-of-sample simulation on the recorded
  runs: file order takes 2.32-3.57 hours, the new order 2.41-2.88 hours; about 15 minutes saved per v0 run on average,
  40 and 16 minutes on the two v35 runs, and one run (block sum) gets 32 minutes longer. The gain should be largest
  where single searches can run for hours (the token-capped runs at the 14,400 s cap). An earlier version ordered by
  proof length and was dropped (reviews AO, AP): proof length does not predict search time.
- **What it costs:** it moves the Lean pressure and the GPU idle time to the START of a run: Lean demand of 102-110
  cores in the first 30 minutes against 42-55 in file order, on 96 Lean CPUs, and only 3-9 searches waiting on the
  model in the first hour. Low GPU use in a run's first hour is therefore expected in this order. The 200 Lean-heaviest
  searches see slightly more contention, so outcomes could shift a little; that is what the checks below are for.
- **Review AQ** (`results/reviews/2026-11-16_review_aq_search_order_code.md`): merge after one fix. The launcher
  compares the start order of every run in a list, finished ones included; the reasoning pilot shares its evaluation
  config with runs 3 and 4 and ran in file order, so turning the order on in that config would stop the chain. Two
  fixes, either enough: (code) compare the order only for a run that will be resumed, never for a finished one; (no
  code) give runs 3 and 4 their own evaluation config (`step1/token_capped_evaluation_ordered.toml`, based on
  `token_capped_evaluation.toml`, with the order and the file) and point only those two runs at it in
  `runs_reasoning.toml`.
- **Review AR** (`..._ar_search_order_code.md`, by simulation with the production code): merge after the same fix.
  With real Lean both orders give identical per-statement results; a resume in another order is refused. The
  no-reasoning pilot's search times correlate 0.74 in rank with the file, so the file predicts that mode too. Should
  fixes: correct the README's numbers; refuse a file that misses many of the probe's statements.
- **State:** the implementer was sent both reviews' fixes on 2026-11-16 at about 17:45 UTC (the code fix, an own
  evaluation config `step1/token_capped_evaluation_ordered.toml` for runs 3 and 4 only, README numbers, the refusal).
  If the branch's head is still `68e70fe`, none of that happened; the fix is small (AR says an uncommitted
  `recorded_mismatches` edit in the worktree already does the code part).
- **Then:** re-review by AQ's and AR's angles, merge, push; on the node deploy at a boundary between runs (keeping
  the node-local edits). The two full reasoning runs must both use the same order and file: both `run.json` files show
  the same `start_orders` and file digest, `sessions.jsonl` shows a single order, and `probe_compare.py pair` prints no
  "orders differ" line.
- **Checks before trusting a comparison ACROSS orders** (every arm's probe run in the new order is compared with the
  file-order anchors): (1) after the first ordered run, `probe_compare.py load` per band against the range of the five
  file-order runs; (2) one v0 / value v0 run in the new order, not marked as anchor, paired against the two file-order
  anchors (about 2.5 hours); it passes if its difference to each is within their A/A difference and its Lean-load
  figures match. A good time for (2) is while the owner decides on the arms' mode. If either check fails, the arms'
  probe runs stay in file order.

**B. Expert iteration inside the loop** — branch `worktree-agent-af77525dfc814e9c3`, commits up to `2db23ca` or later
(worktree `.claude/worktrees/agent-af77525dfc814e9c3`).

- **What:** the loop's policy update can be an expert-iteration round (supervised fine-tuning on the verified
  proof-graph blocks of the last W phases) instead of, or in addition to, the GRPO update; arm overlays `arms/C.toml`
  (expert iteration every phase) and `arms/D.toml` (GRPO every phase plus a round every 4 phases). It is the last
  missing code for arms C and D; arms A and B need none of it.
- **State:** implemented in eight commits; the implementer confirmed on the old run's trees that the loop path builds
  byte-identical data to the hand-run builder and was running the full suite. Two reviews were started on
  2026-11-16 at about 17:40 UTC: AS (`results/reviews/2026-11-16_review_as_expert_iteration_loop_code.md`, by reading
  against the design) and AT (`..._at_expert_iteration_loop_code.md`, by simulation). If those files exist, they are
  the reviews; if they are missing or stop mid-way, the reviewers died with the session and must be redone. Read the
  branch's commit messages and `src/lean_search/rl/README.md` on the branch for what it does.
- **Then:** run the full suite on the branch; two independent reviews (suggested: one on correctness against the
  design and review AB's finding M6 — the round must be the phase's one version, the persistent trainer and /dev/shm,
  D's GRPO on A's code path, restart at every point; one by simulation with the loop's fakes, hostile restart
  schedules, and equivalence of arms A and B with master); fixes; re-review; merge. Before arm C runs on the node: a
  one-phase smoke run with a small token budget, with GPU memory logged.

## 9. Next steps, in order

1. **Reasoning comparison** (running or about to): the pilot, then `step1_run3_visible_T` and
   `step1_run4_no_reasoning_T`. For each, the node agent was asked for bulk and tail readings (GPU use, tokens per
   second, Lean CPUs in use) — the owner's worry is that without reasoning the search becomes CPU-bound and the GPUs
   idle. When both full runs are accepted: `probe_compare.py pair --across-search-modes` of run 3 against run 4, at
   equal tokens AND as "solved within 1/2/4/8/16 expansions" (the owner asked for both views; each search records the
   expansion at which it found its proof), and `--descriptive-across-settings` of run 3 against the anchors.
2. **Decision with the owner: do the arms sample with or without reasoning?** Proposed rule: switch to no reasoning if
   it is within noise of, or better than, visible reasoning at equal tokens and its bulk GPU use stays above about 90%.
   If no reasoning: also decide whether a search keeps 32 expansions (more statements per phase; recommended, because
   only solved trees train the policy) or gets about 2.3 times more.
3. **Learning rates** (about $7, 8 hours): v0 samples 48M tokens once without training
   (`deployment/arm_loop.sh --kind "shared sampling" experiments/configs/grpo/followup/shared_sampling.toml`); cut into
   4 slices (`experiments/slice_trees.py`); one training round per signal from v0 — per-tactic GRPO and pure proof
   success on slice 4 at 2e-5, 5e-5 and 1e-4 (`experiments/grpo_phase.py`), expert iteration at 5e-5 and 1e-4 with
   window 1 (slice 4) and window 4 (slices 1-4) (`experiments/grpo_expert_iteration.py` with `[data]
   tree_directories`); held-out states for v0 and each variant (`experiments/held_out_evaluate.py`), then
   `experiments/rank_learning_rates.py` without gate runs picks each signal's rate. No probe runs at this step. This is
   the first real run of the token-budget loop: watch its first minutes.
4. **Arms**, one after another, each from v0 and value v0, 16 phases of 12M generated tokens, value model trained
   every 2 phases: A (per-tactic GRPO), B (pure proof success), C (expert iteration), D (GRPO plus a round every 4
   phases). After each arm ONE probe run of its final checkpoint with its own value model. An arm that collapses is
   stopped by the automatic rule: capture what happened, leave it stopped, assess, report to the owner. Watch arm A's
   first pause closely: it is the first real training pause on this code (trainer on the training CPUs, restart of
   all servers onto the new version, held-out states, the phase record).
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
