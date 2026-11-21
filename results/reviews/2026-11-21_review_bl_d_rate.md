# Review BL: arm D's GRPO rate 5e-5 → 2e-5 (2026-11-21)

Scope: the uncommitted change to `experiments/configs/grpo/followup/arms/D.toml` (`[phase.policy.optimization]
learning_rate` 2e-5; the round's rate stays 5e-5) and `tests/rl/test_followup_arms.py` (`CHOSEN_RATES`).
`tests/rl/test_followup_arms.py`: 72 passed.

## Blocking

None.

## Should fix

1. **Stale wording that still says D's GRPO rate is A's.**
   - `D.toml` header, line 3: "D takes A's and C's step-2 settings." No longer true for the GRPO rate; the new inline
     comment says so, the header contradicts it.
   - `DESIGN.md` 1168-1169 ("Arms"): "A's (and D's GRPO rate) from step 2". Needs the 2026-11-21 exception and its
     reason (the A screen at 2e-5).
   - Not stale but worth a line in the same place: D against A is now no longer "A plus the rounds". The probe
     comparison `D_against_A.txt` (`arms_chain.py comparisons`) differs in two things, rate and rounds; the 2e-5
     GRPO-only reference (`followup_screen_A_2e-5`) ran 8 phases without a probe. Say this where D's report is read
     (DESIGN.md or the progress file), so nobody reads D − A as the rounds' effect.

2. **Deploy before releasing the hold, and check the node's chain state first.** `arm_loop.sh` runs
   `experiments/followup_arm.py` from the checkout, which writes `followup_configs/followup_D/` once and refuses any
   later start whose configs differ ("an arm's configs are written once"). If D starts before the checkout has this
   commit, it trains at 5e-5, and a later deploy turns every resume into a refusal (→ STOPPED after 4 attempts).
   Order: deploy master, confirm `grep learning_rate $LEAN_SEARCH_RUNS/followup_configs/followup_D/phase.toml` after
   the start reads 2e-5, not before. The installed `arms_chain.sh` copy needs no reinstall (unchanged).
   The PC mirror (`node_backup/.../runs/arms_chain/`) still holds `hold_A`, `pause_A` and a 2026-11-19 `STOPPED`; the
   chain log shows the driver ran past all three, so the mirror keeps deleted files. On the node, `ls` the state
   directory anyway: either `hold_A` or `pause_A` present would stop the chain at A, before D.

## Minor

3. `src/lean_search/rl/learning_rate_step.py` `values_section` (line 362) labels D's GRPO rate as "A's". It is step 2's
   historical report generator, not on D's path; leave it, or note in `followup_node_operations.md` near line 296 that
   D's GRPO rate was later set apart.
4. The progress file has no entry yet for the owner's choice (D at 2e-5, 16 phases, probe). Record it with the start,
   including whether the screens' slide rule (mean success of phases 10-12 at least 1 point below 6-8 → stop and
   report) applies to D: the driver does not implement it, so the watchdog would have to.
5. The smoke test (`done_smoke`) exercised D's combined pause at 5e-5. The rate does not change memory, the kill or
   the restart path, so no rerun is needed; `smoke_report.md` simply records the old rate.

## Checked, no issue

- **Nothing in code ties D's GRPO rate to A's.** `study_configs.ARM_SETTINGS` lets each rate vary independently;
  `followup_arm.py` and `arms_chain.py` (`comparisons`, report, `smoke_overlay`) never read a learning rate. Tests that
  compare D with A (`test_arm_ds_phase_config_is_arm_as_at_the_same_rate`, `..._loop_config_is_arm_as_plus_the_rounds`,
  `test_arms_c_and_d_share_one_recipe`) normalise the rate through `filled` first, so they still hold; `CHOSEN_RATES`
  is the only check of the values.
- **Combined update.** The round starts a fresh optimizer and schedule after GRPO (`rl/README.md`, "Expert iteration
  inside the loop"; `expert_iteration_training.py` 117-124). `minimum_learning_rate_ratio` is a ratio of each update's
  own rate. No coupling between the two rates, no minimum-rate floor. The KL and clip-fraction checks are measured
  on the GRPO update only, and a smaller step only makes them easier to pass.
- **Smoke state.** The smoke run is `followup_smoke_D` with step keys `loop_smoke_D`; the arm is `followup_D` with
  `loop_D`. No glob or prefix match crosses them (`no_other_loop` lists both explicitly). The mirror shows no
  `followup_D` run or config directory and no `done_loop_D` or `attempts_loop_D_start`, so D starts fresh.
  `done_smoke_overlays` is set, so the smoke overlays are not regenerated from the new D.toml.
- **The screen matches D's GRPO half.** `screens/A_2e-5.toml` has the same credit, cap, claim switches and rate as
  D's `[phase]`.
- **Style.** The comments give the reason and stay under the 120-column limit; dated owner decisions follow the
  repository's convention for config comments.

## Verdict

Correct as a config change: no code path assumes D's GRPO rate equals A's, and the combined update is not affected.
Before starting D: fix the D.toml header and DESIGN.md wording (1), and deploy before removing `hold_D` (2).
