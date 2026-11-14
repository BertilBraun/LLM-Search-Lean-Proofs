# Follow-up study: progress

Kept current by the orchestrator. Details live in the linked files.

**Last update:** 2026-11-14, 22:50 UTC.

## Where we are

Step 1 is running: anchor run 1 (v0 with value v0 on the 2,000-statement probe) is close to done, run 2 follows by
itself. All code packages are merged and pushed (master 192b2ac); every one had two independent reviews and a
re-review.

| Item | State | Result or file |
|---|---|---|
| Node: 4x RTX 3090, 61-core CPU quota, $0.89/h, billing since about 11:20 UTC | running the anchors; unstable earlier today (see below) | `ssh -p 16657 root@104.233.209.157` |
| Step 1, anchor runs 1 and 2 | run 1 at 1,881 of 2,000 at 21:13 UTC; run 2 starts after it (about 3.5 h) | `node_backup/2026-11-14/` |
| Step 1, next: calibration run (200 statements), value-free pilots, reasoning at equal tokens, old final value model | after the anchors; needs master on the node | |
| Node measurements before any arm: stop and start timing, fingerprint noise, one short phase on the restart path | after the anchors | |
| Merged packages | probe v2 and evaluation tool; signal packages; token-budget phases and health; study tooling; serving resilience | reviews `_ac_` to `_al_` in `results/reviews/` |
| Not built: expert iteration inside the loop | only after step 2, if that arm goes on | |
| Watchdog | every 30 minutes while this session is open; a supervisor on the node restarts servers and resumes runs by itself | |

## Step 1 results so far

**Anchor run 1** (v0 with value v0, 2,000 statements, 16 expansions; finished 22:10 UTC, accepted): 722 solved (36.1%),
no wall-clock stops, 39.9M generated tokens, 23,814 expansions (1,677 tokens per expansion), about 4.5 hours in total.

| Proof characters | 0-499 | 500-999 | 1,000-1,499 | 1,500-1,999 | 2,000-2,999 | 3,000-4,499 | 4,500+ |
|---|---|---|---|---|---|---|---|
| Solved | 120/150 (80%) | 159/250 (64%) | 156/350 (45%) | 134/350 (38%) | 101/400 (25%) | 39/300 (13%) | 13/200 (6.5%) |

- Anchor run 2 started at 22:11 UTC on the same code and settings; about 4.2 hours.
- Results are pulled to the PC every 10 minutes (`node_backup/2026-11-14/live/`); finished runs are also copied to
  `node_backup/2026-11-14/anchor_v0_value_v0_run1/`.
- The run's last searches left the GPUs mostly idle for about 25 minutes. Planned fix (with review): submit the
  longest statements first, and let the next run with the same weights fill free slots.

## Plan for the night of 2026-11-14 (set 21:55 UTC)

Everything tonight uses v0's own weights, so no weights are swapped. The node works through a chain of reviewed
commands and does not need an agent; a watchdog checks every 30 minutes while the session is open.

| Order | What | Expected |
|---|---|---|
| 1 | Anchor run 1 finishes (1,994 of 2,000 at 21:49 UTC) | before about 23:00 UTC |
| 2 | Anchor run 2, same code and settings as run 1 | about 3.5-4 hours |
| 3 | Update the node to master; check the new server scripts; time stopping and starting servers; measure the fingerprint noise | about 20 minutes |
| 4 | Token budget T from the anchors; 200 calibration statements; calibration run; three constants | about 40 minutes |
| 5 | Three value-free pilots, 200 statements each (the winner is chosen in the morning) | about 1 hour |
| 6 | Reasoning at equal tokens: pilot of the no-reasoning run, then the visible run on 2,000 statements | into the morning |

Not tonight: any arm, step 2's shared sampling, any run with another policy or value model, the deliberate swap test.
Cost of the night: about $8-9 of node time.

For the owner in the morning: the anchors' numbers and their run-to-run agreement; the pilots; the node decision (keep
this one for the arms or move); the open points listed at the end of this document.

## Node stability (2026-11-14) — decision needed from the owner

| Time (UTC) | Event |
|---|---|
| 13:07 | value server on GPU 0 segfaults at a fresh start |
| 14:58 | value server on GPU 0 segfaults, 11 min after an in-place weight swap |
| 15:09 | policy server on GPU 3 segfaults, 83 s after a swap |
| 15:20 | the host machine reboots (uptime from 1 day 9 h to 1 min) |
| 15:29 | the host machine reboots again |
| 22:43 | the host machine reboots a third time, during anchor run 2 (422 of 2,000 done); the on-node supervisor restarts the servers and resumes the run |

- **Diagnosis** (crash logs, the server library's source, the old run's logs): the host is the leading suspect, the swap
  second. The old run did 31 swaps in 80 hours with the same versions and no server died. No file-lifetime defect.
- **Recommendation:** move the closed-loop arms to another node. An arm runs 30 hours or more; a host reboot kills its
  trainer mid-phase. A rebuild takes about an hour on a decent network. Step 1's evaluations can go on here meanwhile.
- **Now running (since 17:59 UTC):** anchor run 1, resumed from 271 statements, on fresh servers without any swap,
  under a supervisor on the node that restarts dead servers and resumes the run by itself, also after a reboot. These
  runs are the control: a server death without a swap points at the host.
- **Pause:** the session and its subagents were stopped by a usage limit from about 15:25 to 17:50 UTC; the node was
  idle in that time (about $2.2).
- **In progress:** probe runs that survive a server failure, a restart-based way to bring a checkpoint up, the
  re-reviews of the token-budget and health package; the study tooling's fixes are done and wait for re-review.

## Node results (2026-11-14)

- **v0 reproduced.** Held-out states: 33.6% success, 59.3% valid Lean on this node, against 32.2% / 57.2% published;
  paired per state the difference is within noise.
- **Throughput with v0 serving** (probe statements, 16 expansions): 56 searches 7.8k expansions/h; 84 searches 10.0k;
  112 searches 11.0k; 168 searches 10.4k. No CPU throttling in any of them, so v0 searches are GPU-bound here. The
  quota does bind on Lean-heavy bursts (the held-out evaluation at 112: throttled 46% of the time).
- **Fixed numbers for the study.** Probe concurrency 84 (set); Lean pinned to 52 CPUs; held-out states at 56. The
  sampling concurrency is set when the token-budget package merges.
- **A full probe run for v0 should take about 2-2.5 hours**, about $2.
- **Network.** The node's link kept dropping to 0.1-3 MB/s, which cost about 75 minutes of setup; SSH drops at times.
- **Persistence.** `/workspace` is not a volume: everything on the node is lost if the instance is destroyed, so
  results are copied to the PC as they finish.

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
| Node, 2026-11-14 11:20 UTC to 21:30 UTC | about $9.0, of which about $2.4 idle (crashes and the pause) |

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
