# Follow-up study: progress

Kept current by the orchestrator. Details live in the linked files.

**Last update:** 2026-11-16, 02:30 UTC.

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
| Step 1, anchor runs 1 and 2 (v0 with value v0, 2,000 statements) | done: 713 and 716 of 2,000 | `node_backup/2026-11-15/live/runs/step1_chain/` |
| Step 1: token budget, calibration run | done: T = 26,804 generated tokens per statement; calibration run 65 of 200; constants -56.4 (completion), -5.35 (block sum), -0.142 (block mean) | |
| Step 1: three value-free pilots (200 statements each) | done: 71, 68 and 65 of 200, against 70 and 75 with the value model | |
| Step 1: reasoning at equal tokens (no-reasoning pilot, visible run, no-reasoning run) | pilot rejected at exactly 1% wall-clock stops; waits for a raised wall cap | |
| Step 1: the full value-free run (whole-completion order); then v0's policy with the old final value model; then the block-sum order | started about 02:30 UTC, through the night | |
| Code: GPU power limits and Lean load (tactic timeouts, REPL failures) in every run record; quota reserve enforced on every start path | merged (reviews AO and AP, re-reviewed) and deployed, master 3309652 | |
| Step 1, last: old final value model with v0's policy; the full value-free run | after a check-in on the pilots | |
| Before any arm: time server stops and starts, one short phase on the restart-based serving path | during step 1 | |
| Step 2: one training round per signal from shared v0 trees | after step 1 | |
| Not built: expert iteration inside the loop | only if that arm goes on after step 2 | |
| Results safety | small result files pulled to the PC every 10 minutes | `node_backup/2026-11-15/live/` |

## Settled: tactic timeouts and load (2026-11-15)

The 60-second wall-clock limit on a tactic step fires about 3,000 times per run, in about 370 of 2,000 statements. The
question was whether CPU contention causes this, which would make results depend on load.

- **Measurement.** 300 timed-out steps of anchor run 1 were replayed alone on the idle node with a 300-second cap and
  their own CPU time recorded, plus 200 control steps.
- **Result.** None of the 300 succeeds even alone. Of the 236 that finish, 235 reach exactly the prefix the anchor
  recorded. 31% needed under 60 seconds of CPU alone (contention pushed them over the limit); 64% are slow by
  themselves; 5% crash the Lean process. Steps ran about 1.5-1.7 times longer under the anchor's load than alone,
  because 112 searches share 96 logical CPUs that are hyperthread pairs.
- **Decision.** The limit stays wall-clock and the anchors stand: load changes the label and the seconds of these
  steps, not where a search goes.
- **Why steps pass 60 seconds at all.** `nlinarith`, `linarith` and `ring_nf` spend most of their time where Lean
  hardly counts heartbeats, so the heartbeat limit bounds only a minority of them.
- **Dropped.** Starting the longest proofs first to shorten a run's idle tail: a simulation on recorded durations
  showed it makes runs longer (4.24 against 3.35 hours), and any reordering changes the load the anchors ran under. The
  study keeps file order; the tail (25-35 minutes per run) stays.

## Results so far

**The baseline: v0 with value v0 on probe v2** (2,000 statements, 16 expansions; both anchors accepted):

| Proof characters | 0-499 | 500-999 | 1,000-1,499 | 1,500-1,999 | 2,000-2,999 | 3,000-4,499 | 4,500+ | All |
|---|---|---|---|---|---|---|---|---|
| Anchor run 1 | 129/150 | 155/250 | 143/350 | 129/350 | 89/400 | 51/300 | 17/200 | **713 (35.65%)** |
| Anchor run 2 | 121/150 | 157/250 | 147/350 | 130/350 | 98/400 | 51/300 | 12/200 | **716 (35.80%)** |
| First node, one run, cross-check only | 120/150 | 159/250 | 156/350 | 134/350 | 101/400 | 39/300 | 13/200 | 722 (36.1%) |

- **Noise floor on this node.** 303 statements (15.2%) are solved in only one of the two runs (150 and 153). The paired
  difference is -0.1 points (95% interval -1.8 to +1.6). Solved within 1/2/4/8/16 expansions: 10.3/16.7/23.2/29.3/35.6%
  and 9.9/16.3/22.4/29.8/35.8%.
- **Cost of a run.** 3.2 and 3.6 hours, 39.6M and 39.8M generated tokens (1,672 and 1,678 per expansion), no server
  restart, no CPU throttling (62-68 cores used on average), 1 and 0 wall-clock stops. Each run ends with a tail of
  25-35 minutes on a few long searches.
- **Tactic timeouts.** The 60-second limit fired 2,856 and 3,209 times per run, in 367 and 375 statements, with no
  throttling; the first node had 3,001 in 379. The same count on a node with twice the CPU points to steps that are
  slow by themselves, not to contention. The replay on the idle node confirms or refutes this.
- **Lean process crashes** (35 and 11 per run) come almost entirely from `ring_nf` on huge powers or long sums: memory
  exhaustion or stack overflow, which heartbeats do not stop, tried again on the same state because a crash, unlike a
  timeout, does not disable the tactic.

**Does the value model matter? Pilots** (v0's policy, no value model, 16 expansions, the first 200 probe statements;
finished 2026-11-16 00:02 UTC, all accepted):

| Search order without a value model | Solved of 200 | 0-499 | 500-999 | 1,000-1,499 | 1,500-1,999 | 2,000-2,999 | 3,000-4,499 | 4,500+ |
|---|---|---|---|---|---|---|---|---|
| Log-probability of the whole completion | 71 | 24/29 | 18/29 | 13/29 | 6/29 | 4/28 | 4/28 | 2/28 |
| Sum over the Lean block's tokens | 68 | 24/29 | 17/29 | 14/29 | 6/29 | 2/28 | 3/28 | 2/28 |
| Mean over the Lean block's tokens | 65 | 20/29 | 15/29 | 14/29 | 6/29 | 4/28 | 4/28 | 2/28 |
| For reference: with value v0 (the two anchors, same 200 statements) | 70 and 75 | | | | | | | |

- All three are within the noise of a 200-statement pilot (about 3 points), and so is the gap to the anchors. A first
  hint that the value model adds little at 16 expansions; the full 2,000-statement run decides.
- By the pre-set rule (most solved) the full run uses the whole-completion order. The owner asked for block-only
  tokens; the two are 3 statements apart, so the block-sum order may be run in full as well.

**Does visible reasoning pay at equal tokens? Pilot** (v0 without the explanation, the same generated-token budget
T = 26,804 per statement, the first 200 probe statements; finished 2026-11-16 02:13 UTC):

- 76 of 200 solved, against 70 and 75 for the anchors with visible reasoning on the same statements (the anchors use
  the tuned depth weight, so this is only a hint; the proper pair is runs 3 and 4).
- The pilot was **rejected** by the acceptance rule: 2 of 200 searches (exactly 1.00%) stopped on the 7,200-second wall
  cap; the rule accepts only below 1%. Both spent nearly all their time in Lean (about 260 seconds per expansion, 28
  expansions). Without reasoning the same tokens buy about 2.3 times the expansions (734 against 1,675 tokens each).
- Per the design, the cap is raised for the pilot, run 3 and run 4 together and the pilot is repeated. That config
  change is made in the morning; the reasoning runs wait until then.

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
