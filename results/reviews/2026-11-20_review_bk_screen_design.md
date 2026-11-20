# Review BK: design of the two GRPO screens (A at 2e-5, B2 at 5e-5)

Scope: `experiments/configs/grpo/followup/screens/A_2e-5.toml`, `B2_5e-5.toml`, `tests/rl/test_followup_screens.py`,
and the section "Owner, 2026-11-20 ~10:50 UTC: hold D, screen two GRPO fixes" of `results/followup_progress.md`.
I read the configs, `study_configs.py`, `advantages.py`, `token_credit.py`, `grpo_groups.py` and `policy_data.py`, and
the pulled metrics of `followup_C`, `followup_A` (capped), `followup_A.uncapped_*` and `followup_A.lr2e-5_stopped_*`
(`node_backup/2026-11-15/live/runs/*/metrics/`, `evaluations.jsonl`). `tests/rl/test_followup_screens.py`: 9 passed.

## Numbers this review relies on (from the pulled metrics)

| | A capped, 5e-5 | A, 2e-5, old reward (1 phase) | C |
|---|---|---|---|
| Relative LoRA change per phase | 10.4% (ph 1), 7.6-8.3% (ph 4-8) | 4.3% (ph 1) | 2.0-3.4% |
| Optimizer steps per phase | 256 (ph 1), 145-157 (ph 4-8) | 248 | 13-52 |
| Positive share of the trained tokens with a nonzero advantage | 35% (ph 1-2), 23-29% (ph 3-8) | 38% | (SFT, positives only) |
| Held-out success, mean of ph 4-8 | 33.6% | | 35.9% |
| Held-out valid Lean, mean of ph 4-8 | 60.5% | | 64.2% |
| Curriculum band low at ph 8 / 15 | 14.0 / 16.5 | | 15.0 / 20.0 |

C at phase 5 (omitted in the doc): 35.5% success, 64.0% valid.

## Blocking

**B1. The decision rule is not defined, and the stated one would not catch A's failure.** "Compared with C's curve
at phases 4-8 ... the better one then run to 16 phases; neither beating C by phase 8 is itself the result" leaves
open what "beating" means, which metric wins, and what happens on a tie. Two concrete problems:
- A capped's own phases 4-8 look like a success by trend: success 31.1 → 33.1 → 33.0 → 34.6 → 36.1 (slope about
  +1.2 points a phase, against C's +0.4), 36.1 against C's 37.1 at phase 8. Its slide came at phases 9-15. A trend
  or last-phase reading of phases 4-8 would have passed it.
- At 2e-5 the policy moves about 0.4x as far per phase (below). If the slide is the same dynamics run slower, A at
  2e-5 reaches A capped's phase-8 distance from v0 near phase 20. Eight phases cannot show it.

"Beating C" is also too strict for a screen. C plateaus at 38-39% from phase 10, so the question for GRPO is whether
it keeps rising after that point. At phase 8 GRPO only has to stay level with C.

Fix: write the rule into the doc before the first screen phase is published. A proposal, calibrated so that C's
curve passes and A capped's curve fails:
1. M_s and M_v are the mean held-out success and valid Lean over phases 4-8 (five evaluations; phase 4 stays in:
   the dip is a real GRPO effect that C does not have). References: C 35.9 / 64.2, A capped 33.6 / 60.5.
2. A screen passes if M_s ≥ 34.9 (C − 1.0) and M_v ≥ 62.2 (C − 2.0), and no exploit guard fires at phase 8:
   tactics per complete block ≤ 1.25x its phase 1; on-graph samples failing after the graph ≤ phase 1 + 10 points;
   bare `have` ≤ phase 1 + 5 points (the claim-watch line).
3. If both pass, the higher M_s wins. Within 0.5 points, the higher M_v wins. If still tied, A at 2e-5 wins: one
   knob changed, and the claim watch and cap tooling apply.
4. If neither passes, that is the result. No 16-phase GRPO run unless the owner decides otherwise.
5. The 16-phase run gets its own stop line: at phase 12, if mean success over phases 10-12 is ≥ 1.5 points below the
   mean over 6-8, stop and report a slide. This line triggers on A capped (34.6 → 33.1). The final claim is the
   probe run paired against C's 1,049.
6. Report the paired per-state bootstrap interval of M_s − C's M_s beside the decision. It does not gate (see S3).

Also state whether the 16-phase run continues the winning screen from its phase-8 state or restarts from v0.
Continuing saves about 8.5 h and keeps the trajectory that was screened. A restart is a second seed for phases 1-8,
but the screen decision then does not bind it.

## Should fix

**S1. B2 at 5e-5 confounds problem 1 with problem 2.** The doc's own rule (Findings: match arms on step size, not
learning rate) and its diagnosis (5e-5 is about 3x C's step) both argue against 5e-5. Under Adam, the per-phase change
here tracks learning rate × steps: 2e-5 against 5e-5 on the same v0 phase gave 4.3% against 10.4% (ratio 0.41, the
learning-rate ratio), and A capped moved about 0.04-0.05% a step. B2 drops every group whose samples all have the
same r, so it trains fewer groups than A, but at 5e-5 it very likely still moves about 2x C. Scenario: B2 at 5e-5
peaks and slides like A. Then "shaping was not the problem" and "the step was still too big" cannot be told apart. The
variant most likely to work, B2 at a C-sized step, goes untested, and step 2 never chose a rate for B2.

Fix, in order of preference:
- (a) Run one offline B2 round at 2e-5 and 5e-5 on the shared step-2 phase or A's phase-1 trees (the step-2 round
  tooling, about 1 h of node time). Take the rate whose `relative_parameter_change` is closest to C's 3%.
- (b) Run B2 at 2e-5. The pair then compares credit at equal learning rate, and A capped is the 5e-5 corner.
- (c) Keep 5e-5 but pre-register: if B2's phase-1 `relative_parameter_change` is above 5%, a B2 failure is
  reported as "B2 at A's step", not "shaping does not matter".

**S2. B2 is not "no shaping to exploit"; it rewards the failing tails outright.** `reaches_proof_graph` is true for
a forward edge with any proof-graph tactic in the kept prefix, and `token_credits` gives every sampled token r − p̄.
So:
- In a block "t1 on the graph, then t2 fails", t2's tokens get +(1 − p̄), about +0.5. Per-tactic credit charged them
  −0.1. Under A's credit this class rose 22% → 36-40% of on-graph samples (`proof_success_failing_tail_share`). Under
  B2 it is reinforced directly, as are open claims and unknown or off-graph endings after the graph.
- A graph state no closer to the proof gets r = 1 (`proof_success_no_closer_share`: 14% at phase 1, 5-9% later),
  and block length is free once t1 lands. The config comment "r = 1 when the sample advances along the found proof"
  is inaccurate for these cases.
- The held-out metric scores a failing tail as invalid and unsuccessful, while the 16-expansion search keeps the
  prefix. B2 may therefore trade held-out valid Lean for search value, and the screen metric may judge it worse than
  the probe would.

The claim switches and the cap: the switches change only the score, which proof-success credit never reads (neither
`has_signal` nor the token credits), and the labels do not depend on them. The cap is refused without per-tactic
credit (`PolicyDataConfig`). Their absence is therefore not a confound, and adding them would be a no-op. This should
be written in the doc so nobody reads B2 as "A without the fixes".

Fix: reword the B2 claim to "outcome credit at the proof-graph level, no progress or waste terms". Pre-register the
expected exploit: watch `proof_success_failing_tail_share`, `failing_after_proof_graph_share` and
`valid_block_tactics`, which guard (2) of B1 covers. Add a prefix-success reading (see N2). If a clean
"no-exploit outcome" is wanted, r = `reaches_proof_graph and complete` matches the held-out criterion. That is a
code change outside the overlay settings, so it is for after these screens.

**S3. Noise: the comparison has one seed and is paired over the same 512 states.** The step-2 v0 A/A gives a paired
95% interval of about ±2.4 points on success for one phase. Averaging phases 4-8 reduces the trajectory noise. It
reduces the state-sampling part much less, because every phase uses the same 512 states. A's adjacent-phase moves
(34.8 → 31.1, 36.1 → 33.9 → 31.3 → 34.2) are larger than the four v0 baselines' spread (33.0-33.2), so most of the
movement is real policy change, i.e. trajectory noise, which one seed cannot average away. The thresholds in B1
therefore define a selection rule, not a significance test. Say so in the doc, and keep "significantly better than
C" out of any conclusion drawn from the screens.

**S4. The success rate's denominator moves.** Held-out success counts only samples that became root edges: 2,658 to
2,994 of the 4,096 draws (512 × 8). Draws with no edge, probably those with no usable block, leave both numerator and
denominator. A capped had more counted samples than C, and its absolute solved counts exceed C's at phases 7-8 (1,034
and 1,058 against 1,013 and 1,016), while its rates are 1.0-1.8 points lower. A screen that writes fewer usable blocks
gains rate for free. Fix: confirm what is excluded. Report solved per 4,096 draws (or per state) beside the rate, and
name in the rule which one decides. My suggestion is to decide on the rate, as all earlier numbers do, and to require
that the per-draw reading does not reverse the decision.

## Minor

- **M1.** The doc's C reference omits phase 5 (35.5% / 64.0%). List phases 4-8 in full, plus A capped's, so the
  rule's references are on the page.
- **M2.** Both screens use `seed_offset` 0 and the fixed curriculum seed, so phase 1 is v0 sampling the same
  curriculum as A capped. Phase-1 metrics (groups about 2,000, positive token share about 35-38%, failing tail about
  22%) should match A capped's within noise. Use this as a free sanity check before reading anything else.
- **M3.** A prior worth noting: the stopped A run at 2e-5 (old reward, one phase) reached held-out 35.1% / 62.5% after
  phase 1, the best phase-1 point of any run (C 34.3 / 59.6, A capped 33.2 / 60.7). It is one phase under the old
  reward, so it is only a hint.
- **M4.** Runbook: 2 × 8.5 h back to back with a manual stop between. Put the screen runs on the 10-minute watchdog,
  and pull their `metrics/` like the arms' (`runs/followup_*` already matches `followup_screen_*`, but check the pull
  pattern).

## Note

- **N1. Q1 alternatives.** The learning rate is the right knob, and in practice the only one. `SMOKE_SETTINGS`
  allows the name, `seed_offset`, `credit`, the cap, the policy learning rate, the two claim switches, the
  expert-iteration settings, `phase_generated_tokens`, `max_phases` and `value_every_phases`. It does not allow
  `kl_coefficient`, `passes_per_phase` (already 1) or `sequences_per_step`.
  - A KL change would be a different test. The penalty is about 0.0006 against a mean absolute policy loss of about
    0.044, so it is inert, and making it bite needs a 30-100x coefficient. That anchors cumulative distance to v0,
    not per-phase overshoot, and C has no KL term, so it would not match C either.
  - The 2e-5 choice is well grounded: the measured 0.41 ratio projects A's phases 4-8 to about 3.1-3.4% a phase,
    C's 3.1-3.4%. It changes one thing against A capped (the test pins every other line), and A capped is its proper
    one-change control. C is the bar. The doc should name both.
- **N2. Q4 logging.** Already logged per phase and enough for most of the diagnosis: `relative_parameter_change`,
  `optimizer_steps`, `mean_kl_penalty`, k1 KL to v0, positive and negative token counts with their ratios and clip
  fractions, `trained_mean_proof_success`, failing-tail and no-closer shares, capped credit, the health line (bare
  `have`, failing after the graph, tactics per block, continue rate) and the curriculum band. Missing, all computable
  after the fact from kept trees and adapters, so none blocks the start:
  - **Advantage mass by sign and by segment** (Σ A⁺, Σ |A⁻| over explanation, tactic and closing tokens). Token counts
    show 62-77% negative tokens, but problem 3 is about mass. Comparing B2 with A needs mass, because B2 puts its
    advantage on every token.
  - **Cumulative distance from v0**: ‖θ_k − θ_0‖ from the kept adapters (`expert_iteration_training`'s
    adapter-difference helper), plus a KL to v0 on fixed held-out prompts. C's `kl_to_starting_policy` is not
    measured (0 in its health line) and the GRPO k1 estimate is negative in phases 1-2, so "matched step" against C
    cannot be checked today. This also lets the screens be read against A capped at equal distance (B1).
  - **Held-out prefix success**: the kept prefix closes the goal or reaches a reference state, whatever the tail
    does. `root_samples` already records `reached`. This is the reading the search sees and separates "B2 learned
    failing tails" from "B2 is worse at progress".
  - **The phase-4 dip**: A's phase-3 update had the lowest positive share so far (28% against 35%) and the failing
    tail jumped to 32%, after the band rose. Log both screens' positive share and band per phase; if the dip shrinks
    at 2e-5, it is a step-size effect.
  - **Claim watch at phases 2, 4, 6 and 8 for both screens**, for comparability with A's runs.
- **N3.** The 2026-11-17 reason for dropping B (92-94% sign agreement with graph credit) still applies as a prior:
  B2 is likely to resemble A at the same step. The disagreement is concentrated in exactly the tails S2 describes,
  which is why guard (2) of B1 matters for B2.

## Verdict

**Run A at 2e-5 as written. Change B2 before it runs.** The A screen is a clean one-knob test, and the evidence
(0.41x step measured at phase 1) supports 2e-5. Before the first screen publishes phase 4, pre-register a decision
rule like B1's. The current "beating C at phases 4-8" would have passed A capped by its trend and cannot see a slide
after phase 8. For B2, calibrate the rate offline or run it at 2e-5 (S1). Reword its claim, since proof-success credit
positively rewards failing tails, no-closer graph states and open claims after the graph (S2), and watch those shares
as guards. The claim switches and cap are inert or refused under B2, so their absence is not a confound. The tests
pass and pin the configs correctly.

## Re-review (2026-11-20)

Checked: the progress doc's section "Owner, 2026-11-20 ~10:50 UTC", `screens/A_2e-5.toml`, `screens/B2_2e-5.toml`,
`tests/rl/test_followup_screens.py` (9 passed) and `deployment/run_screens.sh`. The arithmetic below is recomputed
from the pulled `evaluations.jsonl` and `metrics/health.jsonl` of `followup_C` and `followup_A`.

**Arithmetic: correct.**
- C's means over phases 4-8: success 35.9% (from counts 35.91), valid Lean 64.2%. The thresholds 34.9 and 62.2 follow
  (34.91 exactly; the rounding is immaterial). A capped: 33.6 / 60.5, so it fails on both, as intended.
- Stop line: A capped's success means are 34.6 over phases 6-8 and 33.1 over 10-12, a drop of 1.44 on the doc's
  rounded table (1.47 from the counts). **You are right and my B1 was wrong: 1.5 would not trip; 1.0 does.**
- C never trips the stop line: 36.2 over phases 6-8, 39.0 over 10-12.

**Guards at phase 8.** The table gives each run's value; the three lines are tactics per complete block (≤ 2.7),
failing after the graph (≤ 30%) and bare `have` (≤ 22%).

| Run | Tactics per block | Failing after graph | Bare `have` | Result |
|---|---|---|---|---|
| C | 2.12 | 16.7% | 17.0% | passes all three |
| A capped | 2.35 | 28.6% | 17.8% | passes all three (it fails on level) |

The guards are consistent with the data, with two weaknesses (should fix, cheap):
- **R1. The 2.7 tactics line sits at v0's own level.** Phase 1 sampled by v0 measured 2.55, 2.57, 2.60 and 2.70 across
  the four runs. GRPO and expert iteration shorten blocks early: C reaches 2.05-2.17 by phases 2-5 and A capped 2.10 by
  phase 5. B2's credit has no length term, so B2 can stay at v0's length and trip the line on sampling noise.
  - Fix: 3.0 (A capped crossed it only at phase 13), or 1.15x the screen's own phase 1.
- **R2. A single phase-8 reading is noisy for "failing after the graph".** A capped moved 24.8 → 33.9 → 33.3 → 27.6 →
  28.6 over phases 4-8, so one reading 1.4 points under the line is close to a coin flip.
  - Fix: judge the guards on the mean of phases 7-8.

**The other findings: resolved.**
- S1: both screens now run at 2e-5. They differ only in credit, which the test pins; B2's phase config is checked
  against the shipped `phase_proof_success.toml` at 2e-5.
- S2: the comment and the doc state that failing tails count r = 1 and that the claim switches and the cap do not act
  on this credit.
- S3 and the minor findings are addressed.

**Minor, remaining.**
- (a) "Solved held-out states" should read "solved held-out samples, of 4,096 draws": `solved` counts samples (950 > 512
  states).
- (b) "Neither passes: expert iteration beats GRPO in this setup" overstates a one-seed selection rule. Better: "no
  GRPO variant matched C through phase 8".
- (c) Since the winner reruns fresh from v0, compare its phases 4-8 with the screen's. That is a free replication of
  the selection.

**`run_screens.sh`: no defect found.**
- `arm_loop.sh` writes `loop.pid` before it returns and checks liveness after 30 s, so the liveness wait has no race.
- A restart resumes the run, a screen that already has `finished.json` is skipped, and a health stop moves on to the
  next screen.
- The CPU layout comes in through `environment.sh`, and `arm_loop.sh` enforces it.

**Verdict: approve.** Apply R1 and R2 (two numbers in the rule) before phase 4 is published; the minor items are
optional.
