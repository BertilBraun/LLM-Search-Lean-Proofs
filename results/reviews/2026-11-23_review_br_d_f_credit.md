# Review BR: arm D as C plus F's GRPO step (design: does D − C measure what the GRPO step adds?)

Scope: the uncommitted `arms/D.toml` (`grpo_and_expert_iteration`, a round every phase, `verified_fraction` at 2e-5,
rounds at 5e-5), read against the loop, the resident trainer, the credit code, the arms driver and the node's written
configs and logs (`node_backup/2026-11-15/live/runs/`, pulled 2026-11-23 12:25 UTC). Tests not run (Linux-only env).

Config check (question 1), done by rebuilding D's configs the way `overlay_configs` does (`study_configs.py:237-271`,
a plain `merged`) from the repo's base, phase template and recipe with C's node sampling mode, and diffing them against
the node's written files:
- D's phase.toml == `followup_configs/followup_screen_F_2e-5/phase.toml` (no difference: credit, 2e-5, reward, data,
  budgets, value section, `kl_coefficient = 0.01`, `reference = "starting_weights"`, replay all equal).
- D's loop.toml == `followup_C/loop.toml` except `name`, `policy_update` and the two config paths.
- D's expert_iteration.toml == `followup_C/expert_iteration.toml`.
- ARM vs SMOKE kind: they differ only in the allowed key set (`study_configs.py:44-62, 76-78`); F's three SMOKE-only
  keys (12M tokens, `value_every_phases = 2`, `max_phases` 16 after the extension) equal base.toml's. Nothing in the
  ARM path changes D's GRPO half relative to F's.

## Findings

1. **should-fix — the KL penalty to v0 is part of D's "GRPO step", and it acts on a policy the rounds moved.**
   D's GRPO keeps `kl_coefficient = 0.01`, k3 against `reference_adapter` = v0 (`experiments/configs/grpo/phase.toml:81-82`,
   `rl/loop.py:663`, `rl/policy_trainer.py:64-68, 470`). In F the penalty was 2.5e-4 against |policy loss| ~0.025
   (~1%) with KL to v0 at 0.023 nats by phase 16 (F loop.log "Policy update" lines). In D each GRPO step starts from a
   policy that 1-16 SFT rounds moved; C's KL to v0 was never measured (C has no GRPO pass). So D − C = GRPO reward signal
   + a pull back toward v0 that C does not have, of unknown size. Fix: no config change (owner: reference stays v0),
   but before reading D − C put D's per-phase `KL penalty` and `KL to the start` beside F's; if D's penalty exceeds ~10%
   of its |policy loss| (F: 1%), report the anchor as a confound. Optionally score C's phase-8/16 adapters against v0
   on the same reference sequences offline, so both arms have the number.

2. **should-fix — one run per arm and no D-vs-F comparison in the driver.** F − C was +0.5 [−1.4, +2.4]; that
   interval covers the probe's statements, not loop-to-loop variance, which no arm has measured (each ran once). D − C
   will be read from one run each as well. The driver compares D only with A and C (`experiments/arms_chain.py:109-115`,
   `rl/arms_chain.py:30` ARMS = A, C, D); F's probe runs are outside it. Fix: write down before D starts how D − C is
   read (e.g. "the GRPO step adds something" only if D beats C with the paired interval excluding 0 and also beats F;
   a tie means "no effect larger than the interval", not "no effect"). After D's probe, run `probe_compare.py pair` for
   D vs F (phase 16) by hand, and probe D's retained phase-8 adapter too: C and F both have phase-8 points (F 1,007).

3. **should-fix — the node checkout decides which D runs, and a wrong first write sticks.** `run_arm` reads
   `${followup}/arms/D.toml` from the node's repository checkout (`deployment/arms_chain.sh:68`, `run_arm`), and
   `followup_arm.py` writes `followup_configs/followup_D/` once and refuses a later different write. Releasing `hold_D`
   before this commit is deployed would start D on the old overlay (per-tactic, claim switches, round every 4) with no
   error. Fix: deploy, then after `arm_loop.sh` writes the configs check `followup_D/phase.toml` has
   `credit = "verified_fraction"` and `learning_rate = 2e-05`, and `loop.toml` has `expert_iteration_every_phases = 1`,
   before phase 1's pause (`loops/D.revisions` records the commit).

4. **note — order and coupling inside one pause.** Per phase: the round's data is built from phases k−3..k
   (`rl/loop.py:1823-1827, 1842-1871`); the trainer runs GRPO on phase k's trees from the published adapter
   (`rl/loop.py:662`), then the round continuing the GRPO adapter (`rl/resident_trainer.py:400-410`), then value, and
   merges only the last policy adapter (`:416-419`); one version is published. The sampler for phase k+1 is that
   version, and the next GRPO starts from it, so behaviour policy and GRPO start agree as in F. Consequences for reading
   D − C: (a) the round (5e-5, ~50 steps at steady state, cosine) runs last and can wash out much of GRPO's ~70 steps at
   2e-5 before anything is published; (b) the round's SFT targets are the same phase-k proof-graph blocks GRPO just
   rewarded, and from phase 2 on all of D's data comes from GRPO-shaped policies, so D − C is the closed-loop effect
   (direct step + changed data), not the step alone. Fix: report per phase the GRPO change, the round change and "the
   phase's whole update" (already in loop.log, `expert_iteration_rounds.py:115-117`); if D ties C and the whole change
   is ≈ the round's, say the GRPO step was largely overwritten rather than "adds nothing". Minor provenance trap:
   `round.toml` records `initial_adapter` = the published adapter (`expert_iteration_rounds.py:53`) while D's round
   actually starts from the GRPO adapter (`resident_trainer.py:409`); anyone re-running a D round from round.toml gets
   the wrong start.

5. **note — stale-policy samples weigh more in D.** About 2.2-2.5M of each 12M-token phase comes from searches paused
   at the previous pause (C loop.log "112 searches paused with ..."), partly sampled by v(k−2). GRPO's ratio is to the
   phase-start log-probabilities recomputed in the scoring pass (`rl/policy_trainer.py:694-700`), not the sampler's, so
   that lag is uncorrected in F and D alike; in D the policy moves GRPO + round per phase (steady state roughly F's
   ~2.2% plus C's ~3.4% relative LoRA change, against F's 2.2% alone), so the lagged samples are further off-policy. Fix: none required; compare D's sampler agreement by
   version (`sampler_agreement_by_version`, GRPO records) with F's when reading D.

6. **note — dropping the claim switches and the cap does not change F's credit.** `claims_earn_progress` and
   `unproved_claim_cost` are read only in `judged_in_block` (`rl/grpo_groups.py:290-330`), which changes `parts` and
   `gain`; `verified_fraction` reads only `kind`, `label`, `adds_claim`, `steps_gained` and `node_steps`
   (`grpo_groups.py:150-176`), and `advantages.py:53-54, 82-83, 119, 145` use only it in this mode. The cap would be
   refused with this credit (`rl/policy_data.py:52-53`), so removing it is required, not optional. Only logged metrics
   (`mean_global_reward`, `local_advantage_share`) would differ. Related watch item: F raised the `bare_haves` warning
   at phases 15 and 16 (27.7% and 28.5% below the band, limit 26.0%; F loop.log); D has no claim-specific GRPO guard,
   only the round's "no claim left open" selection. Fix: read D's health `bare_haves` lines at phases 8 and 16 against
   F's (or run `experiments/claim_watch.py` there); no stop rule is implied.

7. **note — nothing in the driver assumed D's old settings or applies A's stop rule.** `smoke_overlay` only lowers an
   interval above 1 (`rl/arms_chain.py:77-79`), so it leaves D's 1 alone; the D-specific smoke gate
   (`rl/arms_chain.py:578-589`) checks GRPO-then-round generically; A's stop rule is a manual orchestrator step
   (`results/followup_progress.md:783`), not wired into `arms_chain.sh`; the only automatic stop is the held-out
   valid-Lean collapse (`followup/base.toml:310-312`), with `on_health_stop = continue`. KL/clip/bare-have checks are
   warnings (`rl/health_checks.py:380-389`). The training timeout keys on (value, round) (`rl/loop_services.py:529-537,
   603-605`): every D phase has a round, so phase 1 (with compile) and phase 2 (first value+round) get the first-phase
   timeout and later ones 2x the median, ≥ 15 min, which D's steady ~10-15 min training clears. `done_smoke` was earned
   by the old D (per-tactic, round brought to phase 1), which exercised the same GRPO + round + value pause; F ran
   `verified_fraction` 16 phases. No re-smoke needed.

8. **note — time and memory.** From the node's "Phase k pause:" lines: C's mean pause 16.2 min (4.33 h over 16;
   round ~230-250 s from phase 4); F's 20.1 min (5.36 h; scoring ~140 s + GRPO ~260-330 s from phase 4, 470-706 s in
   phases 1-3). D ≈ C + F's scoring + GRPO: ~+7.5 min per steady phase, +12-17 min in phases 1-3, so ≈ +2.0-2.3 h over
   16 phases: C's loop took 15.3 h (18:49 → 10:08), D about 17.5 h plus the ~3 h probe, ~$2 more than C at $0.83/h.
   Memory is C's and F's: one resident policy shared by GRPO and the round (`resident_trainer.py:304-321`), one policy
   merge; smoke D peaked at 16.2 GiB GPU and 33.7 of 71 GiB /dev/shm with GRPO, round and value in one pause. D keeps
   the GRPO and the round adapter per phase (retention 0): a few GB more disk than C, within the 113 GB free.

## Re-review (2026-11-23)

Checked the uncommitted `results/followup_progress.md` section "Owner, 2026-11-23: run D (C's rounds plus F's GRPO
step)" and the draft `d_after.sh` (session scratchpad, to be installed as `/workspace/runs/screens/d_after.sh`).

1. **Resolved.** KL penalty against |policy loss| and KL to v0 next to F's, with the 10% confound line, are among the
   per-phase checks. The optional offline KL of C's adapters to v0 was not taken up; that is acceptable, since D's own
   number against F's 1% is enough to flag the confound.
2. **Resolved.** The reading rule is written down before D starts (lower bound above 0 / interval containing 0 / upper
   bound below 0; phase-8 and D-vs-F secondary; C8 937 and F8 1,007 match the node's summaries). `d_after.sh` is right
   on the points that matter: it uses the bare run names, which `probe_compare.py:93` resolves to
   `probe_evaluations/probe_<name>`, and `arm_C_phase8_run1`, `screen_F_phase8_run1`, `screen_F_phase16_run1`,
   `arm_C_phase16_run1` all exist on the node. The driver names D's run `arm_D_phase16_run1` (`rl/arms_chain.py`
   `probe_run_name`). D8 uses the phase-8 round adapter and phase-8 value with `value_version = 8`, as C8 did
   (C8's `run.json`: `followup_C_phase_0008/expert_iteration/adapter`, value 8). It uses the same
   `probe_evaluation_ordered.toml` as C8, C16, F8 and F16 (their `config.toml` are identical) and concurrency 112, and
   it gates on all 4 GPUs being below 100 MiB. Remaining caveats, none blocking:
   - **Stale STOPPED file.** The script exits at once if `arms_chain/STOPPED` exists. The PC backup still holds a
     STOPPED file from 2026-11-19 (probably a stale copy, since the chain ran after it and pulls do not delete). Check
     `ls /workspace/runs/arms_chain/STOPPED` on the node before launching.
   - **D ending before phase 16.** If D health-stops and the owner answers `evaluate`, the driver probes the last good
     phase under another name. The three D16 comparisons then fail with "compare … failed" (logged, not fatal) and
     need redoing by hand.
   - **Duplicate comparison.** `D16_against_C16` duplicates the driver's `D_against_C.txt`; this is harmless.
3. **Open until done (deployment step).** The order given (deploy, check the written `followup_D/phase.toml` and
   `loop.toml`, verify before phase 1's pause) covers it. Two more steps are needed to start the driver: removing
   `hold_D` alone does not start it, because HOLD must be moved aside too (`arms_chain.sh` header: HOLD and STOPPED
   make a start exit at once), and STOPPED must be absent. Do both before `supervisorctl start arms_chain`.
4. **Resolved.** The per-phase GRPO, round and whole-change check and the `round.toml` start-adapter trap are written
   into the progress section.
5. **Resolved.** Sampler agreement per version against F's is a listed check.
6. **Resolved.** Bare `have` at phases 8 and 16 against F's 27.7% and 28.5% is a listed check. The progress section
   records that the switches are not read and the cap is refused.
7. **No action needed (note).**
8. **No action needed (note).** The progress section's ~17.5 h estimate matches.
