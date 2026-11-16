# Review AV: the learning-rate step (step 2) automation

Branch `worktree-agent-a576d0540c85ea253`, 4 commits on master `4263d98` (fbea663, fa878fb, 6abf63e, 8c631b0).
Focus: does the step measure what it is meant to measure. Read against DESIGN.md "Follow-up study: controlled arms"
with the owner's decisions of 2026-11-16 (no probe or gate-set runs, held-out states only, B1 dropped).

Checks run: the three suites `tests/rl/test_learning_rate_step.py`, `test_study_commands.py`,
`test_study_chain_script.py` in WSL against the worktree's `src`: 137 passed. `ruff check` and `ruff format --check`
on the 7 changed Python files: clean. Node (read only): `held_out_evaluations/held_out_v0/checkpoint.json` and
`summary.json` parse in today's `HeldOutRunStart` format (512 states, nothing dropped, 48 Lean CPUs in
`pinning.jsonl`).

**Verdict: merge after fixes.** Nothing blocks. The ten rounds are built from the arms' own overlays through the same
`overlay_configs` code the arms use, so A's, B2's and C's training recipes at step 2 match what the arms will run
(credit, KL, clipping, batch, replay mixes, epochs, schedule). The should-fix items are about what the report tells
the person filling the PLACEHOLDERs, and about keeping the arms on the step's sampling mode.

## Blocking

None.

## Should fix

**S1. The report does not flag a chosen variant that is significantly worse than v0.**
`src/lean_search/rl/learning_rate_step.py:450` and `:462-467`. The column "Success apart from v0" prints "yes"
whenever the interval excludes 0, whatever its sign. The only warning is the "within noise" note. `choose_rate`
(`rate_ranking.py:130`) picks the best variant among the variants and never compares it with v0.
Scenario: every A rate lowers held-out success, and the least bad one is -4 [-6, -2]. The report prints "chosen
A_2e-5" and "Success apart from v0: yes", the values table puts 2e-5 in arms/A.toml, and nothing says the signal
hurt. The same applies to valid Lean, which is the measure behind the hard stop: a chosen variant could lose 10
points of valid Lean and nothing would mark it.
Fix: make the column signed (e.g. "above v0", "below v0", "within noise"). When the chosen variant's success
interval lies entirely below 0, or its valid-Lean interval lies entirely below 0, add a line to the ranking section
and put a "look first" caveat on the values table. Add one test per case.

**S2. The arms are not bound to the step's sampling mode.**
`deployment/arm_loop.sh:39-46`, `experiments/followup_arm.py:59-63`. `--mode` is required, but any mode file is
accepted. The driver pins its own copy (`mode.recorded`), but the arms are started later, by hand, from
`arm_loop.sh`. If someone passes `followup/modes/visible.toml` after a no-reasoning step 2, or later edits that file's
expansions, the arms sample differently from the trees their rates came from, and nothing refuses it. The
docstring's claim that "the arms sample as the trees they took their learning rates from"
(`study_configs.py:14-16`) is then false.
Fix: `followup_arm.py` (kind arm) compares the merged `[sampling]` table with the one in
`$LEAN_SEARCH_RUNS/followup_configs/followup_shared_sampling/loop.toml`, when that exists, and refuses a difference.
Compare the referenced search config's bytes or sha256 as well, not only its path.

**S3. The mode mechanism is ready only for "visible". The no-reasoning outcome has no config, and nothing guards
the one that will be written.**
`study_configs.py:63-82`, `experiments/learning_rate_step.py:117-125`, `study_chain.sh:72-80`.
- No training search config without visible reasoning exists. The operations document says so, which is right, but
  it means the step cannot start on a "no reasoning" decision until a new config is written and reviewed. That config
  is not a one-line switch: `visible_student_v2.toml` has `max_depth = 16` and `depth_weight = 0.25`. DESIGN, "Step
  1", says 0.25 pushes a no-reasoning search breadth-first, and a no-reasoning block is about one tactic, so depth
  16 cuts proofs about three times shorter.
- `check-mode` accepts any search config that loads. On the node, the step-1 evaluation config
  `step1/token_capped_no_reasoning.toml` now loads, because the node-local edit filled T. It is the obvious file to
  point a no-reasoning mode at, and the mode would accept it silently: a per-search token cap, 1,024 expansions
  overridden to the mode's count, and settings tuned for evaluation, not training.
- `mode.recorded` pins the mode file's bytes, not the search config it names. An edit or a deploy that changes that
  search config between S1 and S3b would go unnoticed. The held-out runs re-read the search config at evaluation
  time (`held_out_evaluate.py:133`), so the variants would then be evaluated under another search than v0.
- The mode reaches the shared sampling run, the held-out runs (through the shared run's loop.toml) and the arms'
  loops. It does not reach the arms' probe runs (`followup/probe_evaluation.toml`, visible reasoning at 16
  expansions). See the owner question below.
Fix: record the search config's sha256 in `mode.recorded` (or `mode.txt`) and compare it at every start. Make
`check-mode` refuse a search config with `max_generated_tokens` set (the training searches are budgeted by
expansions). Write the no-reasoning training search config now, in this branch or the next, so the owner's
decision does not wait on code.

**S4. Nothing checks v0's baseline for drift or noise under the step's conditions.**
`study_chain.sh:150-152`, `:266-269`. v0 runs once, in S3a. The ten variants run 4-6 hours later, after the servers
were stopped and restarted. The only other v0 reading in the report is the 2026-11-15 run, which differs in code,
pinning (48 against 96 Lean CPUs) and possibly mode. The report itself labels that comparison as not an A/A check.
So if the variants' runs shift for a reason unrelated to the adapter (server state, node load, a Lean or vLLM
difference after a restart), every "variant minus v0" moves with it, and nothing in the report would show it.
Fix: run v0 a second time as the last held-out run (`step2_v0_end`, about 7 minutes). Report it paired against S3a's
run as the step's A/A and drift check, and keep pairing the variants with the S3a run. The ranking is unaffected:
`choose_rate` compares variants with each other.

**S5. When C's window is decided by the tie-break, the report does not say so.**
`rate_ranking.py:166-167`, `learning_rate_step.py:88-101`, `:457-459`. On a tie, C's window is decided by listing
order (`min` returns the first of equal rates, and window 1 is listed first). The reason printed is "tied on the
held-out states, no gate runs; the lower rate", even when the tied variants have the same rate and differ only in
window. Window 1 is a defensible tie-break: it is the smaller update per round and the DESIGN-conservative choice,
and step 2 cannot test window 4's repetition anyway ("the data amount, not the repetition"). But the report should
say the window was chosen by the tie-break and not by the measurement, because the window shapes arm C, and arm D
through it, more than the rate does.
Fix: in `ranking_section` for signal C, add a line when the tied set holds both windows: "window chosen by the
tie-break (window 1 preferred), not measured apart".

## Nits

**N1. The module docstring overclaims.** `learning_rate_step.py:7-8` says "the arm later trains exactly as its chosen
variant did". The recipe matches; the seeds, the data and the trainer do not:
- Seeds: a GRPO round keeps the template's `policy.optimization.seed = 0` and `policy_replay.seed = "grpo-replay"`,
  where the loop's phase 1 uses 1 and `"grpo-replay/1"` (`loop.py:660-661`). A C round keeps the recipe's selection,
  replay and training seeds, where the loop uses `/phase-1` and 1 (`expert_iteration_rounds.py:43-50`).
- Data: slice 4 against the arm's phase-1 trees.
- Trainer: `grpo_phase.py` and the hand-run `train` against the persistent trainer.
The seed differences bias nothing: the rates within a signal share their seeds, which is good for pairing. Either set
the phase-1 seeds or reword the docstring to "with the arm's recipe".

**N2. Gaps in the step's in-loop parity that the report could show.**
- An in-loop C round with fewer than 100 examples is skipped (`expert_iteration_min_examples`). Step 2 trains any
  round with at least one optimizer step (`dry_run_steps`).
- A dry run planning 1-3 steps passes. DESIGN expected about 8 for one slice.
Print the examples and steps of both builds in the report's header, and warn under 100 examples or under ~5 steps.

**N3. A failure in the descriptive comparison can fail the whole report.** `experiments/learning_rate_step.py:200-211`.
`read_held_out` raises SystemExit if the earlier run's states hash differs or a tree is missing. That stops the
chain at its last step, after about 10 node hours. Catch it and print "not comparable: <reason>" instead. The two
files checked on the node look fine today.

**N4. The `report` command never runs end to end in a test.** No test reads real `phase.json`, `training_summary.json`,
`finished.json` and `timings.tsv` through `round_record`, `signal_ranking`, `v0_baseline` and `report`. I checked the
field names by hand (`GrpoTrainingResult`, `TrainerTimings.total_seconds`, `RunFinished`) and they match. Still, one
fixture-based test of `report()` would catch a format drift before it surfaces at the end of a node run.

**N5. The rate column is printed in two formats.** `learning_rate_step.py:447`: `f"{report.learning_rate:g}"` prints
`2e-05`, while the labels and the values table use `2e-5`. Print `report.label`'s rate string instead.

**N6. A leakage check is missing.** The C builds count trees of held-out statements and states equal to a held-out
state (`BuildSummary.held_out_statements`, `held_out_states`; both should be 0). The report does not show them. GRPO
rounds do not filter held-out goal keys at all. If the 512 states' goals appear in slice 4's trees, GRPO variants
would train on them, and the higher rates would profit most. Show the two build counts in the report. Optionally,
count slice 4's expanded nodes whose goal key is a held-out state's.

**N7. Step sizes are reported for GRPO only.** The rounds table gives KL to v0 for GRPO. A C round gets only its
replay-loss change; the hand-run `train` records no parameter change, while the in-loop round records it. The
progress document's own finding is that arms should be matched on step size, not only on rate. A relative LoRA change
for both kinds would make "A at 5e-5 against C at 1e-4" readable.

**N8. Docstrings.** The new modules follow the repository's habit of multi-line docstrings. The global style rule asks
for one short line. Not worth changing alone.

## Checked and fine

- **The ten variants.** A and B2 at 2e-5, 5e-5 and 1e-4 on slice 4. C at 5e-5 and 1e-4 on slice 4 (window 1) and on
  slices 1-4 (window 4). No B1. Run names and held-out names are distinct and consistent across `rounds.tsv`,
  `held_out.tsv`, `rank-arguments` and the report.
- **The GRPO round config.** It is `overlay_configs(ARM, arm overlay with the rate)`, so it is phase.toml or
  `phase_proof_success.toml` as the arm would use it (test-pinned). v0 is the start and the KL reference (the same
  path as `[initial] policy_adapter`), `--part policy`, and the loop's own Lean and math replay files. The value-share
  is 0 in both.
- **The C round config.** It is arm C's recipe at the rate, with `tree_directories` set to its slices, `loop` set to the
  shared run (so `train` continues v0 from its `current.json`), and one build per window shared by both rates. Window
  4's `states_per_statement` cap spans all four slices, as an in-loop window does. The in-loop round trains as the
  hand-run `train` does (rl/README, tested equivalent).
- **Compute.** The shared run stops at 48M = 4 x B. The slices are cut by finish order into equal tokens of about
  12M = B. Window 4 covers 4 x B, as an arm's W = 4 round does from phase 4 on.
- **The held-out baseline.** Rerunning v0 is right: the 2026-11-15 run used 48 Lean CPUs and older code. Every
  variant runs `held_out_evaluate.py` with the shared run's loop.toml, so the same mode, states file, concurrency 56,
  pinning and swap by restart. A server is skipped only when it provably holds byte-identical weights, so v0 on the
  loop's servers and the variants on fresh merges differ only in the adapter.
- **The ranking.** It is DESIGN's rule as the owner changed it: paired per state, best by point estimate, ties by the
  95% interval to the best, then the lower rate; no gate set. The report reruns `choose_rate` with the same seed and
  refuses a disagreement with `rank_<signal>.txt`. The multiple-comparisons note counts 20 intervals.
- **The values table.** It covers every PLACEHOLDER of A, B2, C and D: D takes C's window and rate and A's GRPO rate.
  Rate strings are valid TOML floats.
- **The driver.** A round counts as done only after exit 0 and its last-written files exist; an interrupted output
  is moved aside. The builds run beside the GRPO rounds on the Lean CPUs and are waited for before C. A step gets at
  most 3 attempts. Servers are stopped only through `stop_model.sh`. HOLD and STOPPED are final under supervisord with
  `startsecs=0`. Killing the driver at every step point resumes correctly (test-pinned).
- **Tests.** Names are descriptive, each test has one logical assertion, production code is called directly, and the
  chain tests use the real `plan_files` output.

## Questions for the owner

1. **Tie means the lowest rate, so the step may pick 2e-5 by default.** One GRPO pass from v0 moved the old run very
   little, and 512 states resolve about 3 points. All three GRPO rates may well tie, and the rule then picks 2e-5:
   the old run's rate, the one DESIGN wanted to move up from. That is the rule as decided (the gate set and probe
   runs are dropped). Is "lowest rate when nothing separates" still what you want? The alternative is the middle rate,
   or KL to v0 per phase as the tie-break.
2. **Slice 4 against slice 1.** The GRPO rounds and C window 1 train on slice 4: the last 12M tokens, at a higher
   curriculum band, without the slowest searches. An arm's phase 1 samples exactly what slice 1 holds. Slice 4 fits
   a "typical later phase" better; slice 1 fits the arm's actual first update. DESIGN says slice 4: confirm.
3. **The probe runs under "no reasoning".** If the arms sample without reasoning, should their probe runs (the primary
   endpoint) also search without reasoning, against a v0 anchor in that mode? Today `probe_evaluation.toml` is
   visible at 16 expansions, and the mode does not reach it.
4. **Arm D with window 1.** If C's window comes out at 1, D's round every 4 phases trains on the last phase only, and
   3 of every 4 phases' solved trees never reach D's rounds. Should D's window be max(C's window, 4)?
5. **The replay data under "no reasoning".** GRPO's NLL replay and C's 30% Lean replay stay
   `visible_student_v3_numbered` (with its explanations) whatever the mode. Fine if that set also holds v0's
   no-explanation examples. Otherwise the replay would pull a no-reasoning policy back toward explanations.

## Re-review (2026-11-16)

Fixes reviewed: 8c631b0..e91d7fa (head e91d7fa), five commits.

Checks run:
- In WSL, against the worktree's `src`: `test_learning_rate_step`, `test_learning_rate_report` (new),
  `test_study_commands`, `test_study_chain_script` and `test_rate_ranking`. 207 passed.
- `ruff check` and `ruff format --check` over `src`, `experiments` and the test files: clean.
- On the node (read only): no `followup_configs` and no `study_chain` state exist yet, so the step starts clean.
  The replay set `reasoning/visible_student_v3_numbered/train.jsonl` holds 15,114 `"visible": false` lines of
  42,678 (35%).

**Verdict: merge.** All five should-fix findings are fixed. N1-N5 are fixed; N6 and N7 are open and need not block. I
found no regression. The new nits below are small.

### Status per finding

| Finding | Status | Notes |
|---|---|---|
| S1 report hides a chosen variant below v0 | fixed | Each measure now has its own column: "above v0", "below v0" or "within noise" (`side_of_v0`; the sign comes from `interval.lower > 0` once 0 is excluded). A bold line under the ranking and a "Look first" line above the values table name the measures on which the chosen variant is below v0, success or valid Lean. Tested both ways. |
| S2 arms not bound to the step's mode | fixed | `followup_arm.py` writes `sampling.json` (search config path, expansions, the config's sha256) beside every loop.toml. It refuses an arm whose record differs from the shared run's. A differing path, expansions count or file content is refused (tested). Configs written without `sampling.json` fall back to path and expansions only; none exist on the node, so the fallback is unused. |
| S3 no-reasoning mode not ready, any search config accepted | fixed (the probe-run question stays the owner's) | Details below. |
| S4 no A/A or drift check for v0 | fixed | `step2_v0_end` is the last line of `held_out.tsv`, after the ten variants. The report pairs it with the first v0 run ("after minus before") and prints a bold drift line when either interval excludes 0. The variants stay paired with the first run, and the ranking does not use v0. |
| S5 C's window decided silently by the tie | fixed | The tie rule now lives in `rate_ranking.tie_break`. Signal C's section says the window came from the tie rule whenever the tied set holds both windows (tested both ways). |
| N1 docstring overclaim | fixed (reworded) | The seeds are still the template's, which is acceptable: the rates within a signal share them. |
| N2 rounds too small for the loop | fixed | The report notes a round under 100 examples or under 5 planned steps. It notes only and does not stop, which fits a report. |
| N3 earlier v0 run can fail the report | fixed | `earlier_run` catches SystemExit, OSError and ValueError and names the reason (tested). |
| N4 no end-to-end test of `report` | fixed | `tests/rl/test_learning_rate_report.py` runs `report` over real-format files written through the production dataclasses. It includes a rank file that disagrees and an earlier run on other states. |
| N5 rate printed two ways | fixed | The rate column uses the variant's rate string. |
| N6 leakage counts not shown | open | The C builds' `held_out_statements` and `held_out_states` counts are still not in the report. Small, can follow. |
| N7 no step size for C rounds | open | As before. Small, can follow. |
| N8 docstring length | open | Not worth changing. |

**S3 in detail:**
- `search/no_reasoning_student_v2.toml` differs from run 4's `step1/token_capped_no_reasoning.toml` in three things
  only: no `max_generated_tokens`, `max_expansions` 64 instead of 1,024 (the loop's mode value replaces it anyway),
  and comments. Against `visible_student_v2.toml` it differs only in `visible_reasoning = false`, `depth_weight = 0`
  and `max_depth = 64`, so harvesting, ε, n and the heartbeats are the visible training search's.
- `max_depth = 64` is run 4's value. That is right.
- The token-cap refusal (`training_search_refusal`: any `max_generated_tokens` set) is sound. A config still holding
  the PLACEHOLDER already fails to load. Both `check-mode` and `followup_arm.py` apply it.
- `mode.txt` now carries the search config's sha256. The driver compares it with `mode.recorded.txt` at every start,
  so an edit or a deploy that changes the search config stops the chain (tested).
- The mode still does not reach the arms' probe runs. That stays an owner question (question 3), not a code
  defect.

### Smaller points in the fixes

All are fine as they are:
- **GPU check by memory.** The GPUs count as free when each uses under 100 MiB; a check also stops the chain if
  `nvidia-smi` does not read exactly 4 GPUs. More robust in a container than the process list.
- **Builds pid with start time.** `builds.pid` now records the process start time (field 22 of `/proc/<pid>/stat`).
  The `cut -f20` after stripping `pid (comm) ` picks the right field. The driver's own pid is excluded, so a reused pid
  after a container restart no longer counts as the builds running.
- **Dropped held-out states.** A held-out run that exits 0 but left states without a tree is now not marked done;
  the next start resumes it under its attempt counter.
- **Servers at HOLD.** Stopping the servers before HOLD is right. `arm_loop.sh` keeps any server that answers, and
  these would hold the last variant's merge.
- **Finished round kept.** A round whose completion files exist when its driver died before marking it is now kept,
  not retrained. See R2.

### New findings (nits)

**R1. The wait for the loop to exit can retry forever.** `study_chain.sh`, S1, the wait after `finished.json`. It
exits 1 after 600 s without an attempt counter. If the shared loop hangs in its shutdown, supervisord restarts the
driver every ~11 minutes indefinitely. No STOPPED is ever written; only the watchdog would notice. Fix: count it
(`attempt s1_loop_exit`), so the 4th try writes STOPPED.

**R2. A finished output is kept even if its trainer exited non-zero.** `study_chain.sh`, `train_round`. The "kept"
check also accepts an output whose trainer wrote its completion files and then exited non-zero, e.g. at the
torchrun or NCCL teardown on an earlier attempt. That is probably the right call, since the files are written last.
But the log line says only "the earlier attempt left a finished output". Add that attempt's exit status if it is
known, or a pointer to `rounds/<label>.log`, so a teardown failure stays visible.

**R3. The depth comment goes stale if expansions rise.** `search/no_reasoning_student_v2.toml`, `max_depth` comment.
"Not binding at the loop's budget: 32 + 16 harvesting reaches depth 48" holds only while the mode's expansions are at
most 48. The mode file invites raising them about 2.3 times (about 74). The cap of 64 could then bind on a pure chain.
Fix: say "not binding up to 48 expansions". The value itself (run 4's) is fine.

**R4. The multiple-comparisons note leaves out the A/A intervals.** `learning_rate_step.py:694`. It counts the 20
variant intervals but not the two A/A intervals. The drift line can fire by chance about 5% of the time per measure.
Add the 2, or say "by chance" in the drift line.

### Owner question 5, answered on the node

The replay set already mixes both forms: 35% of its examples are no-explanation. Under the no-reasoning mode, the
GRPO and C replay would still be 65% examples with explanations. That is consistent with v0's own SFT mix, so I see no
change needed. The question stays the owner's only if he wants the replay to match the mode.
