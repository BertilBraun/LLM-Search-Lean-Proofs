# Follow-up study: progress

Kept current by the orchestrator. Details live in the linked files.

**Last update:** 2026-11-14, 12:15 UTC.

## Where we are

Step 0: analyses on existing data, node setup, design and the first work package. Nothing has trained or been evaluated
on the new node yet.

| Item | State | Result or file |
|---|---|---|
| Node: 4x RTX 3090, 61-core CPU quota, $0.89/h, billing since about 11:20 UTC | rented | `ssh -p 16657 root@104.233.209.157` |
| Node setup: environment, Lean, models, data, v0 reproduction, throughput test | running | |
| Analysis: compute and hardware of the old run | done | `results/followup_step0/throughput_and_hardware.md` |
| Analysis: pool difficulty | done | `results/followup_step0/pool.md` |
| Analysis: noise floor (v0 against itself, power of the new probe) | done | `results/followup_step0/noise_floor.md` |
| Analysis: training signal per scheme on the recorded trees | running | `results/followup_step0/training_signal.md` |
| Design section in `DESIGN.md` ("Follow-up study: controlled arms") | drafted, two reviews running | `results/reviews/2026-11-14_review_aa_*`, `_ab_*` |
| Work package 1: probe v2, near-duplicate guard, curriculum by characters, full-probe evaluation | being implemented, then two reviews | |
| Work package 2: log-probability of the Lean block only (search without the value model) | being implemented | |
| Work packages 3 and 4a: pure proof-success credit; expert-iteration phase window | being implemented | |
| Later packages: token-budget phases, expert iteration inside the loop, health checks per arm, study tooling | after the design reviews | |

## Findings so far

- **Compute.** Most of the old run's in-pool gain came early: +11.6 points on one probe third after 23 GPU-hours, +9.9
  pooled after 128, +17.2 at the end (228). Only 47% of node time was sampling.
- **Hardware.** The old run's later phases were Lean-bound and CPU-throttled. The new node has half the CPU quota, so
  expect lower throughput; the setup measures it.
- **Pool.** The pool did not run out of hard statements. The curriculum measured difficulty by the number of tactics
  in the shortest known proof, which hardly separates easy from hard. Proof length in characters does: v0 solves 84%
  of probe statements under 500 characters and 9% above 4,500. 45k usable statements were still unfed at the end. The
  fix is a configuration change; no new verification is needed for supply.
- **Noise floor.** v0 against itself: 16% of probe statements are solved in only one of two runs. On the 2,000-statement
  probe one paired comparison detects about 2.6 points, two runs per checkpoint about 1.9. With two seeds per arm, a
  5-point difference can be confirmed (seeds must agree within 1.6 points); 3 points cannot.
- **Unsolved statements taught the policy nothing.** The design draft found that training groups are built only at
  proof-graph nodes (`rl/grpo_groups.policy_groups`), so only solved trees train the policy; unsolved ones reach only
  the value model. Graph credit against outcome-only is therefore a question of how credit is spread inside solved
  trees. The training-signal analysis is confirming this on the recorded trees. An arm that really learns from
  unsolved trees is a possible addition; to discuss at the next check-in.
- **Evaluation cost.** A full probe run is expected to take several hours on this node, so the design's evaluation
  plan is being cut down (screen learning rates on the 512 held-out states, probe only the finalists).

## Plan

| Step | What | Rough cost | Decides |
|---|---|---|---|
| 0 | Analyses, node setup, design, work package 1 | node time | arm length, power, pool fix |
| 1 | Evaluations only: reasoning against none at equal tokens; value model final, v0, none | $15-25 | both questions |
| 2 | One training round per signal from shared v0 trees; 2-3 learning rates each; window 1 against 4 | $40-60 | whether signals separate; step sizes |
| 3 | Closed loop: two arms, one seed each; more arms and second seeds after a check-in | $30-45 per arm | which signal works best |

## Decisions (owner, 2026-11-14)

- **Scope.** Steps 0-2, then two arms with one seed. A third or fourth arm and second seeds are decided afterwards. No
  fixed budget cap yet.
- **Autonomy.** The orchestrator runs everything; the owner checks in about twice a day. If step 2 shows no separation,
  stop and decide together.
- **Write-up.** Internal documentation for now; homepage post or report is decided after the results.
- **Measure.** In-pool on a 2,000-statement held-out probe; miniF2F-valid only at the end, as a secondary check.
- **Arms.** All start from v0. Candidates: graph-credit GRPO, outcome-only GRPO, expert iteration, interleaved.
- **Matching.** Equal generated tokens in the training searches. For reasoning against none: generated tokens only.
- **Outcome-only.** Both definitions (pure proof success, sequence-level graph credit) at step 2; one goes on.
- **Step size.** Each arm uses its own best learning rate from step 2.
- **Value model.** Trained inside every arm, as in the old run. Search without it is best-first by the policy's
  log-probability of the Lean block tokens only.
- **Expert iteration.** Fixed sliding window, 1 against 4 phases, never all phases.
- **When an arm goes wrong.** Fixed automatic rules detect a collapse. Then we look at the cause together: an obvious
  bug is fixed and the affected arms rerun; otherwise the degradation is documented as a result.
- **Process.** Subagents on Opus 5.5 at high effort; two independent reviews per implementation wave.

## Spend

| Item | Amount |
|---|---|
| Node, 2026-11-14 11:20 UTC to 12:15 UTC | about $0.8 |
