# Follow-up study: progress

Kept current by the orchestrator. Details live in the linked files.

**Last update:** 2026-11-14, 15:25 UTC.

## Where we are

Step 0 is done on the node; step 1 has started with the probe draw and the two anchor runs (v0 with value v0 on the
2,000-statement probe).

| Item | State | Result or file |
|---|---|---|
| Node: 4x RTX 3090, 61-core CPU quota, $0.89/h, billing since about 11:20 UTC | set up; v0 reproduced; throughput measured | `ssh -p 16657 root@104.233.209.157` |
| Step 1, probe v2 draw and anchor runs 1 and 2 | started about 14:40 UTC | results to `node_backup/2026-11-14/` |
| Step 1, value-free calibration and pilots, reasoning at equal tokens, old final value model | waits for the launcher (in review) and the anchor runs | |
| Four step-0 analyses, design with two reviews | done | `results/followup_step0/`, `results/reviews/2026-11-14_review_aa_*`, `_ab_*` |
| Package: probe v2, near-duplicate guard, curriculum by characters, base config, evaluation of any checkpoint | merged (reviews `_ac_`, `_ad_`, re-reviewed, final check) | master |
| Package: step log-probability setting, pure proof-success credit, expert-iteration data from tree folders | merged (reviews `_ae_`, `_af_`, re-reviewed) | master |
| Package: token-budget phases, a defined end, seeds; health checks that mean the same in every arm | implemented; two code reviews running | branch `worktree-agent-a1f7eaa0dbb612621` |
| Package: study tooling (arm comparison, slicing, learning-rate ranking, step-1 run lists, launcher, arm configs) | implemented; two code reviews running | branch `worktree-agent-acedfb3c2cd157ac3` |
| Package: expert iteration inside the loop | only after step 2, if that arm goes on | |
| Watchdog | every 15 minutes while this session is open | |

## Session paused (2026-11-14, 15:25 UTC): usage limit reached

The orchestrating session hit its usage limit. **The node keeps billing $0.89/h.** State at 15:23 UTC:

- **Node:** servers are being restarted fresh by the setup agent; anchor run 1 had NOT yet resumed (271 of 2,000
  statements done, GPUs at 4%). If the agent is cut off, nothing restarts it. Stop or destroy the instance if no
  session will continue soon; probe v2 and the partial run are copied to `node_backup/2026-11-14/`.
- **Merged on master (pushed up to a8a279d):** probe package, signal packages, value-free evaluation fix.
- **Not merged:**
  - token-budget and health package: fixes done (979e83f on `worktree-agent-a1f7eaa0dbb612621`), re-reviews requested;
  - study tooling: fix round in progress on `worktree-agent-acedfb3c2cd157ac3`;
  - server-crash diagnosis, restart-based serving and failure-tolerant probe runs: just started.
- **Next steps when resumed:** confirm the anchors run without a swap; merge the two packages after their re-reviews;
  then the value-free calibration and pilots, the reasoning comparison, and step 2's shared sampling.

## Open problem (2026-11-14, 15:20 UTC)

**Model servers segfault after an in-place weight swap.** Anchor run 1 crashed twice, each time minutes after the
probe tool swapped weights into the running servers (14:58 value server on GPU 0; 15:09 policy server on GPU 3). The
same servers ran 1.5 hours under load without a swap and without a crash. The loop publishes new versions through the
same swap, so the arms would be hit too.

- Now: the anchor runs restart on fresh servers without any swap (v0's weights are already what the servers load).
  271 of 2,000 statements of run 1 are kept.
- In parallel: diagnosis from the crash logs and the old run's logs; a restart-based way to bring a checkpoint up as a
  fallback; probe runs that survive a server failure (today one failed request ends a 2,000-statement run).
- Probe v2 is drawn: 2,000 statements, 33 twins held out; copies in `node_backup/2026-11-14/probe_v2/`.

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
| Node, 2026-11-14 11:20 UTC to 15:20 UTC | about $3.6 |

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
