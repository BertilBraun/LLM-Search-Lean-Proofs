# Review BD: the arms driver (A, smoke test, C, D)

Branch `worktree-agent-ab9fe6ed21f69d9fd`, head b5199ee, one commit on master 0e04599. The focus is study design: are
the probe runs comparable, are the adapters kept, is the smoke test sound, does the health-stop path match the rules,
and can the arms differ by accident. Read against:
- DESIGN.md "Follow-up study: controlled arms" (Evaluation, Step 3, Automatic rules);
- `results/followup_progress.md` (master 4fbe627: A restarted at 5e-5);
- the smoke lists at the end of reviews AS and AT;
- the ops note "The arms driver".

Checks run:
- In WSL, against the worktree's `src`: `test_arms_chain`, `test_arms_chain_script`, `test_followup_arms`,
  `test_study_chain_script`, `test_offline_chain_script` and `test_study_commands`. 339 passed.
- `ruff check` and `ruff format --check` over `src`, `experiments` and `tests/rl`: clean.
- No node access, as asked.

**Verdict: merge after fixes.** The probe runs, the adapter copies, the health-stop path and the separation of the
smoke runs from the real arms are right. Nothing blocks. Fix before the smoke test runs:
- **S1:** the smoke's 2M-token phase will probably fall under the loop's 100-example floor for a round. The round
  would then be skipped and the smoke test would fail on its own gate, with the node idle until someone looks.
- **S2:** the smoke does not exercise the heaviest trainer state (GRPO, value training and a round in one phase),
  which arm D meets at phase 4 and C at every even phase. One setting covers it.
- **S3:** the 95% nvidia-smi gate during training is uncalibrated and may fail a healthy run.

## Blocking

None.

## Should fix

**S1. At 2M tokens the smoke round will probably be skipped, which fails the smoke test by its own gate.**
`src/lean_search/rl/arms_chain.py:34` (`SMOKE_PHASE_GENERATED_TOKENS = 2_000_000`), `:513-536` ("round trained");
loop default `expert_iteration_min_examples = 100` (`loop_config.py:158`), which `SMOKE_SETTINGS` cannot change.
- A round with fewer than 100 training examples is skipped (`too_few_examples`). A skipped round fails "round trained"
  in C and D, and "GRPO then the round" in D, so the driver writes STOPPED before arm C.
- Estimate (DESIGN "Step 2": "at round 1's density one slice gives C only ~8 optimizer steps" for 12M tokens):
  - 8 steps × 4 GPUs × 16,384 packed tokens ≈ 520k tokens per 12M, of which about 60% are the round's own examples,
    so roughly 300-400 examples per 12M.
  - 2M tokens is about 1/6 of that: roughly 50-70 examples, under the floor.
  - The first trees to finish are the fast, often easy searches, so more of them are solved. But the 20% cap on easy
    states (at least 7 of 8 first-round samples on the proof graph) cuts exactly those.
- I cannot measure this without the node, so treat the estimate as an order of magnitude. Even so, the planned smoke
  is more likely to test the skip path than the round.
- Fix, either:
  - raise the smoke budget to about 6M tokens: the sampling costs ~15 minutes more and the round becomes near-real; or
  - add `loop.training.expert_iteration_min_examples` to `SMOKE_SETTINGS` and set it to e.g. 20 in `smoke_overlay`,
    with a reading that names the examples count.

  Either way, print the round's example count next to the gate.

**S2. The heaviest trainer state is not smoke-tested, and it comes early in C and D.**
- `base.toml` has `value_every_phases = 2`. Arm D's phase 4 (and every 4th phase after) runs GRPO, value training
  and a round in one persistent trainer, with the value merge beside the policy merge in /dev/shm. Arm C runs value
  training and a round at every even phase.
- These are AT's smoke items 2 and 3 ("GPU memory in D's phase 4", "/dev/shm ... plus, in value phases, the value
  merge"). The smoke report lists "a value phase beside a round" as not covered.
- The smoke's only phase is phase 1, which trains no value model. So C's first value-and-round phase (phase 2, ~1.5 h
  in) and D's first triple phase (phase 4, ~6 h in) are where an OOM or a full /dev/shm would show first, inside a
  real arm.
- Fix: add `loop.training.value_every_phases` to `SMOKE_SETTINGS`, and set it to 1 in `smoke_overlay`. The one smoke
  phase then trains value too, the gates (OOM, nvidia-smi peaks, /dev/shm, wake memory) judge the worst case, and the
  value window (4 phases) has phase 1's trees.

**S3. The 95% nvidia-smi gate is uncalibrated and may stop a healthy smoke.** `arms_chain.py:45`, `:585-596`.
- nvidia-smi's "used" includes the caching allocator's reserve (expandable segments) and the sleeping vLLM servers'
  CUDA contexts (two per GPU).
- A trainer that runs fine can sit at 23.3 GiB or more of 24 GiB, which is the 95% line, without ever failing. No
  reading of arm A's training stage exists to compare with: the driver samples only the smoke loops.
- The gates that catch real trouble are already there: no out-of-memory in `trainer.log`, wake memory at least the
  servers' shares, phase finished.
- Fix: make "GPU memory while training" a reading. Or sample arm A's phases too, which is free while the driver polls
  A's loop, and gate on "at most A's training peak plus a margin" or "no GPU at 100%".

**S4. When an arm stops on its health rule, the GPUs sit idle until the owner answers.**
`deployment/arms_chain.sh:148-161`.
- The path matches the decided rules: the arm is never restarted, a report is written, and the last good version (the
  newest whose held-out run raised no held-out alert, `health_checks.healthy`) is probed on `evaluate`.
- But a stop of arm C at, say, phase 6 leaves the node idle until the owner writes `skip` or `evaluate`. He checks in
  about twice a day, so that is up to ~12 h at $0.83/h. The owner's standing rule says "never leave GPUs idle without a
  reason".
- The next arm does not depend on the stopped arm's evaluation, except when the cause is a shared bug, which the
  health report shows.
- Fix, or put it to the owner (question 1): let the driver go on with the next arm and leave the stopped arm's probe
  for the owner's word at the end, before HOLD.
- Also add the third outcome the rules provide, "fix and rerun the arm", to the ops note's word list. That one means
  moving the run aside by hand; say how.

**S5. The smoke report understates what it does not cover.** `arms_chain.py:722-726`. Not covered and not listed:
- AS 5: a kill during the build, and a kill of one trainer rank during the round;
- AS 2: the in-loop round against the hand-run `train`;
- AT 1: "exactly one policy merge in /dev/shm handoff, the round's, and in D not GRPO's too". This is only implied by
  the published adapter's path.
- AT 6: a stop during a build.

Several are fine to leave to the real arms. List them in the report's "Not covered" line, so that passing the smoke
test is not read as clearing AS and AT's whole list.

## Nits

**N1. "GRPO then the round" uses a norm inequality as a proxy.** `arms_chain.py:551-559`. The gate takes the phase's
LoRA change norm being at least the round's as evidence that GRPO's update is included. That is true for orthogonal
or aligned updates but not guaranteed when they are anti-correlated. It is almost certainly fine in practice. A
direct check is cleaner, e.g. the round's `initial_adapter` in its `round.toml` being the GRPO update's adapter.

**N2. The report does not state the decision rule.** `arms_chain.py:381-420`.
- Arm against arm and arm against anchors are compared with ONE probe run per arm at this stage. DESIGN's rule
  (Evaluation) wants two runs pooled, a difference of at least 3 points and the 95% interval excluding 0, and with one
  seed it is provisional.
- Add one line to each report saying that these comparisons are provisional until the second pass.

**N3. The report does not name each arm's code revision.** The arms run over ~60 h, and a deploy between arms (allowed
at boundaries) would make them differ in code. Print the revision each loop ran from its run record, so an accidental
difference is visible.

**N4. The kill lands in the server restart, not in `record_durably`.** The 30 s kill delay lands during
`servers.serve` (swap "restart", ~200 s): after the handoff, before the version is recorded. That is a good crash
point ("a restart after the servers loaded the merges but before the record"), but it is not AS's M1 case (during
`record_durably`). Say which one the smoke hits.

**N5. The driver stops the servers before restarting the killed loop.** `arms_chain.sh:181-185`. The restart after
the kill goes through `start_loop`, which first runs `stop_model.sh --all`. A real crash leaves the servers running,
so the test exercises the resume with the servers down. That is the harder case for the record, but not the common
one. A note in the report is enough.

**N6. A health stop with version 0 as the last good one cannot be evaluated, and the health report does not say so.**
`evaluate` then stops again (documented in the ops note). Have the health report say "evaluate is not possible: no
healthy version" when `last_good_version` is 0.

## Checked and fine

- **Probe comparability.**
  - `step1/probe_evaluation_ordered.toml` is `probe_evaluation.toml` (the anchors' settings: plain
    `visible_student_v2.toml`, probe v2, 16 expansions, 7,200 s cap, concurrency 112, the 1% acceptance) plus the
    start order. The order check (run 9) passed, so the arms' runs may use it.
  - Every arm uses the same file, so A, C and D compare cleanly with each other. Anchors and run 7 are in file order,
    which `probe_compare.py` notes.
  - Each run uses the arm's final (or last good) policy with that version's own value adapter, with `value_version` =
    the version that first published it.
  - On the efficiency branch, `evaluation_run_config` keeps probe runs on the plain search. Exit 3 (wall-clock stops)
    stops the chain with the doubled-cap instruction.
- **Comparisons.** Anchors pooled (runs 1 and 2), run 7 descriptive, and each earlier arm with a probe run done.
- **Adapters.** Phase 8 and the final (or last good) phase, policy and value. That is exactly what the second pass
  needs: the final checkpoint again, phase 8, and v0's policy with the final value adapter. They are copied with a
  sha256 manifest and renamed into place, and an existing copy whose manifest does not hold is refused. The PC pull
  verifies them with `sha256sum -c` and fetches only adapters. Retention keeps everything on the node.
- **Health stop.** Never restarted. The report shows the last four phases, their alerts and the updates. `skip` copies
  the adapters and writes a report; `evaluate` probes the last good version as DESIGN's Evaluation requires ("labelled
  stopped at phase k").
- **Smoke runs kept apart.**
  - Each has its own run name, config directory, checkpoints and curriculum state.
  - The overlay is derived by code, and a test pins that it changes only the name, the budget, the phase count and
    D's round interval.
  - It is checked against the shared run's sampling like any arm, and refused as an arm.
  - Nothing the real arms read (pool snapshot, held-out files) is written by them.
- **Seeds and mode.** All arms run at seed offset 0 (identical by design) and are bound to step 2's sampling record.
  A's adoption touches nothing while its loop lives.
- **Kill gates.** The stage-based kill is guarded by the PID's command line. The gates use the loop's real log lines
  (pinned by `test_the_log_lines_the_checks_read_are_still_the_loops`). Phase and stage come from `loop_state.json`;
  the phase stays 1 through training and publishing, which I checked in `loop.py`.

## Questions for the owner

1. **After an arm's health stop, should the driver go on with the next arm while you decide** (`skip` or `evaluate`
   for the stopped one at the end)? Or should everything wait for your word, as now (up to ~12 h idle)?
2. **The smoke test's budget.** About 6M tokens, so the round trains on a realistic amount of data (+~15 min), or 2M
   with a lowered example floor for the smoke only?
3. **Arm A's earlier start at 2e-5** (`followup_A.lr2e-5_stopped_20261118`). Its phase-1 checkpoints were written as
   `checkpoints/followup_A_phase_0001`. Were they moved aside with the run directory? Otherwise the 5e-5 run's phase 1
   may have found them (the orchestrator can check on the node: `continued_from` and the dates of
   `followup_A_phase_0001/phase.json`).
