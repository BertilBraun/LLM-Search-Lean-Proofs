# Follow-up study: progress

Kept current by the orchestrator. Details live in the linked files.

**Last update:** 2026-11-15, 12:45 UTC.

## Where we are

Step 1 (evaluations only) restarts on a new node. All code for steps 1 and 2 is merged and pushed; every package had
two independent reviews and a re-review (`results/reviews/2026-11-14_review_aa_*` to `_al_*`).

| Item | State | Result or file |
|---|---|---|
| Node: 4x RTX 3090, 105-core CPU quota, $0.83/h, rented 2026-11-15 about 08:30 UTC | set up in 45 minutes; 8 servers healthy | `ssh -p 21232 root@50.173.30.254` |
| v0 reproduction on the held-out states | done: 34.0% success, 58.7% valid Lean (published 32.2% / 57.2%; first node 33.6% / 59.3%) | |
| Throughput test (10 runs, two CPU layouts, four concurrencies, hard statements) | done: this node does 14.6k expansions/h at 112 searches, about 35-40% more than the first node; GPUs are the bottleneck, no CPU throttling | `node_backup/2026-11-15/live/runs/throughput/` |
| Fixed settings for this node | 112 concurrent searches for probe runs and sampling, 56 for held-out states; Lean on socket 1 (96 CPUs), servers and training on socket 0 | `experiments/configs/grpo/followup/`, `/workspace/node_environment.sh` on the node |
| Code: CPU quota on this node's cgroup layout, explicit CPU layout without raising priority, each run's layout recorded and checked | merged (reviews AM and AN, re-reviewed), master 40b2409 | `results/reviews/2026-11-15_review_am_*`, `_an_*` |
| Step 1, anchor runs 1 and 2 (v0 with value v0, 2,000 statements) | being deployed and started, about 12:45 UTC; about 2.5-3 hours each | |
| Step 1, rest: token budget, calibration run, three value-free pilots, reasoning at equal tokens | follows the anchors by itself (a chain on the node that survives a restart) | |
| Step 1, last: old final value model with v0's policy; the full value-free run | after a check-in on the pilots | |
| Before any arm: time server stops and starts, one short phase on the restart-based serving path | during step 1 | |
| Step 2: one training round per signal from shared v0 trees | after step 1 | |
| Not built: expert iteration inside the loop | only if that arm goes on after step 2 | |
| Results safety | small result files pulled to the PC every 10 minutes | `node_backup/2026-11-15/live/` |

## Results so far

**v0 on probe v2, first node** (2026-11-14, one run; kept as a cross-check between nodes): 722 of 2,000 solved
(36.1%), no wall-clock stops, 39.9M generated tokens, 1,677 tokens per expansion, about 4.5 hours.

| Proof characters | 0-499 | 500-999 | 1,000-1,499 | 1,500-1,999 | 2,000-2,999 | 3,000-4,499 | 4,500+ |
|---|---|---|---|---|---|---|---|
| Solved | 120/150 (80%) | 159/250 (64%) | 156/350 (45%) | 134/350 (38%) | 101/400 (25%) | 39/300 (13%) | 13/200 (6.5%) |

- Probe v2 is drawn and fixed: 2,000 statements, 33 near-identical pool statements held out of the curriculum
  (`node_backup/2026-11-14/probe_v2/`).
- A run's last few long searches leave the GPUs mostly idle (about 25 minutes on a 2,000-statement run). Planned fix,
  with review: submit the longest statements first, and let the next run with the same weights fill free slots.

- Measured on the new node: stopping a server takes about 1 second; a full start of the 8 servers 147 seconds with
  warm caches (8 minutes the very first time). The weight fingerprint differs by up to 0.25 nats between servers
  holding the same weights, so its warning tolerance goes from 0.05 to 0.3 nats; a gross mismatch (1 nat) still fails.

- The host caps three of the four GPUs below their nominal power (295 W, 350 W, about 262 W, about 330 W) and the
  caps drift a little; they are recorded every minute beside the runs.

## History in one paragraph

The first follow-up node (rented 2026-11-14, destroyed 2026-11-15) had three host reboots, four model-server
segfaults and a final outage within thirteen hours. It produced the probe draw and one complete anchor run. What it
left in the code: probe runs that survive a server failure, a restart-based way to serve new weights (the study's
default), safe server stops, results pulled to the PC as they are written.

## Findings so far

- **Compute.** Most of the old run's in-pool gain came early: +11.6 points on one probe third after 23 GPU-hours, +9.9
  pooled after 128, +17.2 at the end (228). Only 47% of node time was sampling.
- **Hardware.** The old run's later phases were Lean-bound and CPU-throttled at a 123-core quota. Probe searches of
  hard statements spend about 35 Lean-seconds per expansion, against 6-9 for easy ones.
- **Pool.** The pool did not run out of hard statements. The curriculum measured difficulty by the number of tactics
  in the shortest known proof, which hardly separates easy from hard. Proof length in characters does: v0 solves 84%
  of probe statements under 500 characters and 9% above 4,500. 45k usable statements were still unfed at the end. The
  fix is a configuration change; no new verification is needed for supply.
- **Noise floor.** v0 against itself: 16% of probe statements are solved in only one of two runs. On the 2,000-statement
  probe one paired comparison detects about 2.6 points, two runs per checkpoint about 1.9. With two seeds per arm, a
  5-point difference can be confirmed (seeds must agree within 1.6 points); 3 points cannot.
- **The old run never trained the policy on unsolved statements.** Groups are built only at proof-graph nodes, by a
  design decision of 2026-10-28. All 6,550 unsolved trees (41%) gave zero policy groups, and 82-85% of all policy
  expansions were never used for the policy. The write-up's sentence that unsolved statements teach valid and failing
  steps holds only for the value model.
- **Graph credit and pure outcome are nearly the same signal.** On the recorded trees they use the same solved trees
  and agree in sign on 92-94% of the advantage mass; they differ in the size of the advantages. A closed-loop pair of
  these two would measure reward shaping and will probably not separate with one seed.
- **Step sizes differ between signals at the same learning rate.** Sequence credit carries 1.4-2 times the advantage
  mass of per-tactic credit; expert iteration trains on a tenth of the tokens at five times the rate. Arms should be
  matched on step size (the same KL to v0 per phase), not only on learning rate.

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
| First node, 2026-11-14 11:20 UTC to its outage at about 23:35 UTC | about $11 at most; partly refunded by the provider (owner) |
| Second node, from 2026-11-15 about 08:30 UTC | $0.83 per hour |

## For the owner's next check-in

1. **Which arms to run.** Graph credit against pure outcome is expected to show little. Candidates with a larger
   expected contrast: graph credit against expert iteration, and a new arm E that learns from unsolved trees and
   off-graph expansions (the 82-85% never used). E brings back the conditions of the old reward hacking, so it would
   get its own step-2 round and a habit check first.
2. **Closed-loop outcome-only control.** Pure proof success instead of "whichever differs more" (a reviewer's point:
   that rule selects on noise).
3. **Proposed defaults.** 12M generated tokens per phase, 16 phases per arm; stop an arm at its first collapse; an
   expert-iteration round every 4 phases in the interleaved arm.
4. **Half probe.** 1,000 statements at intermediate checkpoints (phases 4 and 8), saving 4-6 hours per arm.
