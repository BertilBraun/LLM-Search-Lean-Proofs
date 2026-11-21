# Follow-up study: progress

Kept current by the orchestrator. Details live in the linked files.

**Last update:** 2026-11-16, 21:45 UTC.

## Where we are

Step 1 (evaluations only) is done except for the reasoning comparison, which is running. Every merged package had
two independent reviews and a re-review (`results/reviews/`). A new agent takes over from `HANDOFF.md` in the
repository's root; the node's setup and operation are in `results/followup_node_operations.md`.

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
| Step 1: reasoning at equal tokens (no-reasoning pilot, visible run, no-reasoning run) | first pilot rejected at exactly 1% wall-clock stops; wall cap doubled to 14,400 s; the repeated pilot **accepted** (2026-11-16 20:2x UTC): 70 of 200, 0 wall-clock stops, 2.47 h. 9834972 deployed by the chain; run 3 (visible, token cap T, depth weight 0, new start order) **accepted**: 672 of 2,000 (33.6%), 0 wall-clock stops, 3.49 h (anchors at their tuned settings: 713 and 716). Run 4 (no reasoning) started 2026-11-17 00:00 UTC; its first minutes are Lean-bound (112 REPLs, about 96 cores, GPUs idle), as the start order predicts | |
| Step 1: the full value-free run (whole-completion order) | done: 642 of 2,000 against 713 and 716 with the value model | |
| Step 1: v0's policy with the old run's final value model | done: 875 of 2,000, +8.0 points over value v0; the restart-based serving path worked on real servers | |
| Step 1: the full value-free run in the block-sum order | done: 633 of 2,000 (the whole-completion order: 642) | |
| Step 1, added: the old final policy (v35) with value v0, then with the final value model (the 2x2 of policy by value) | done: 1,083 of 2,000 with value v0 (+18.4 points) and 1,236 of 2,000 with the final value model (61.8%); the two gains add up | |
| Code: GPU power limits and Lean load (tactic timeouts, REPL failures) in every run record; quota reserve enforced on every start path | merged (reviews AO and AP, re-reviewed) and deployed, master 3309652 | |
| Step 1, last: old final value model with v0's policy; the full value-free run | after a check-in on the pilots | |
| Before any arm: time server stops and starts, one short phase on the restart-based serving path | during step 1 | |
| Learning rates for the arms (shared v0 sampling, one round per signal, held-out states) | after the reasoning comparison and the decision on the arms' mode | |
| Code: step 2's node automation (`deployment/study_chain.sh`: shared sampling, 4 slices, 10 rounds, held-out for v0 twice and each variant, ranking, report, HOLD with servers stopped); sampling mode as an explicit input (`followup/modes/visible.toml`, `no_reasoning.toml`), arms refused if their sampling differs from the shared run's | merged (reviews AU and AV, re-reviewed), master d500f85; tested against stand-ins only, never run on the node; about 8-11 h with visible reasoning | `results/reviews/2026-11-16_review_au_*`, `_av_*`; install in `results/followup_node_operations.md` section 3 |
| Arms A, B, C, D with one probe run each | after the learning rates; see the plan below | |
| Code: expert iteration inside the loop (for arms C and D) | merged (reviews AS and AT, re-reviewed), master 467d97c; 80 crash-and-restart cases simulated; needs a one-phase smoke run on the node before arm C | `results/reviews/2026-11-16_review_as_*`, `_at_*` |
| Code: probe runs start the longest expected searches first (by the mean search time of v0's five runs) | merged (reviews AQ and AR, re-reviewed), master 9834972; used for the two full reasoning runs; a check run against the anchors follows them | `results/reviews/2026-11-16_review_aq_*`, `_ar_*` |
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
  showed it makes runs longer (4.24 against 3.35 hours), and any reordering changes the load the anchors ran under.
- **Replaced by (2026-11-16, the owner's proposal):** starting the searches with the longest MEASURED search time
  first. Out-of-sample simulation on the recorded runs: 2.41-2.88 hours against 2.32-3.57 in file order, about 15
  minutes saved per v0 run on average and more where single searches run for hours. It moves the Lean pressure and
  the idle GPU time to the start of a run. Off by default; before a run in this order is compared with the
  file-order anchors, one v0 run in the new order is paired against them.

## Results so far

**Reasoning at equal tokens: runs 3 and 4** (v0 with value v0, 2,000 statements, T = 26,804 generated tokens per
statement, depth weight 0, 14,400 s wall cap, both started longest expected search first; both accepted
2026-11-17):

| | Run 3, visible reasoning | Run 4, no reasoning |
|---|---|---|
| Solved of 2,000 | 672 (33.6%) | **769 (38.5%)** |
| Paired difference | | **+4.9 points** (95% +2.9 to +6.7; 139 against 236 solved by one run only, McNemar p = 6e-7) |
| Solved within 1/2/4/8/16 expansions | 9.8/16.1/22.5/27.8/32.5% | 12.0/18.9/25.2/30.3/34.4% |
| Generated tokens per statement | 20,561 | 18,126 |
| Expansions per statement (mean / max) | 12.8 / 41 | 25.1 / 237 |
| Wall-clock hours | **3.49** | **6.36** |
| Bulk (≥ 100 searches running): GPU use | 85-88% | **70-72%** |
| Bulk: generated tokens per second per GPU | about 870 | about 425 |
| Bulk: Lean cores in use (of 96) / cgroup cores | 68.7 / 74.4 | 84.0 / 90.2 |
| Tactic wall-clock timeouts (statements) | 3,845 (371) | 8,705 (426) |
| Wall-clock stops | 0 | 4 (0.2%) |

- **Per token, no reasoning wins in every band** (by 1 to 7.7 points; the interval excludes 0 in three of seven
  bands, 1,000-1,499, 2,000-2,999 and 3,000-4,499). **Per node hour, visible reasoning wins**: 193 solved per hour against 121. Without reasoning the search is
  Lean-bound: the GPUs idle about 30% in the bulk and generate half the tokens per second, so a run takes 1.8 times
  as long for the same tokens. The proposed rule (switch if within noise or better AND bulk GPU use above about 90%)
  is met on its first half and missed on its second; visible reasoning also misses 90% here (85-88%), because the
  start order front-loads Lean.
- What it means for the arms (matched on generated tokens): without reasoning each arm's sampling would take about
  1.8 times as long (an arm about 30-36 h instead of about 20 h, about $10-13 more per arm), unless the Lean side is
  made cheaper.
- Run 3 against the anchors (descriptive; the token cap and depth weight 0 differ): -2.1 points (95% -0.6 to -3.7),
  most of it under 500 characters (-10 points).
- **At equal expansions** (solved within N expansions, paired; analysis on the PC 2026-11-17): no reasoning at 16
  expansions against the anchors (visible, tuned depth weight, 16 expansions): -1.2 and -1.4 points (95% -3.0 to
  +0.6 and -3.2 to +0.5); against run 3 at 16: +2.0 (+0.1 to +3.9); at 8 against run 3: +2.5 (+0.7 to +4.4). So
  visible reasoning buys at most about 1 point per expansion for 2.2 times the tokens per expansion (1,606-1,678
  against 721), and no reasoning has not had its depth weight tuned.
- **Where Lean time goes** (run 4, 575 Lean hours): 88% verifying the policy's blocks, 12% the automatic tactics
  (`nlinarith` 4.6%, `simp_all` 2.5%, `field_simp` 2.1%, `omega` 1.2%, `ring_nf` 1.0%, `rfl` and `constructor` 0.3%).
  The automatic tactics take part in 44% of proofs and close 10% of them alone. Policy blocks stopped at the
  60-second tactic limit cost about 25% of all Lean time in every run (8,632 timeouts in run 4).
- The node's `reasoning_readings.txt` failed for runs 3 and 4 (its log pattern does not match the ordered runs'
  start line); the readings above come from a fixed copy run on the PC against the pulled files.

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

**How the old run's gain splits between policy and value model** (probe v2, 2,000 statements, 16 expansions; all four
cells accepted, the last on 2026-11-16 17:48 UTC):

| | Value v0 | The old run's final value model |
|---|---|---|
| **Policy v0** | 714.5 (35.7%), mean of the two anchors | 875 (43.75%) |
| **Policy v35**, the old run's final policy | **1,083 (54.15%)** | **1,236 (61.8%)** |

- **The two gains add up.** Value training: +8.0 points with v0's policy, +7.6 with v35's (95% interval +5.9 to
  +9.6). Policy training: +18.4 points with value v0, +18.1 with the final value model (+16.1 to +20.0). Adding both
  to the baseline predicts 62.1%; measured 61.8%. The interaction (-0.3 points) is inside the noise.
- **The old run's whole in-pool gain is +26.1 points** on statements it never saw (95% interval +24.2 to +28.1):
  about 70% from the policy and 30% from the value model.
- By band (solved of 150/250/350/350/400/300/200): v35 with the final value model 140/195/236/235/229/148/53. The
  policy's gain is largest between 1,000 and 4,499 characters (+19 to +24 points); the value model's is spread more
  evenly (+5 to +11 from 1,000 characters up).
- The last run: 3.31 hours, 32.5M generated tokens, 1 wall-clock stop, no throttling, no server restart.

- **The old loop's policy training is worth +18.4 points** on statements it never saw (95% interval +16.6 to +20.2;
  62 statements lost and 432 gained against anchor run 1). Every band gains: +6 points under 500 characters, +14 to
  +24 between 500 and 4,499, +12 at 4,500 and more.
- The policy's gain is there at the first expansion: solved within 1/2/4/8/16 expansions 18.0/28.3/38.8/47.8/54.1%
  for v35 against 10.1/16.5/22.9/29.5/35.7% for v0. It reaches v0's 16-expansion result with under 4 expansions.
- v35 works Lean harder (5.5 Lean seconds per policy attempt against 3.8-4.1; 1,882 tokens per expansion against
  1,672) and still used fewer tokens in total (35.2M against 39.7M), because more searches end early.
- 3 wall-clock stops (0.15%), accepted.

**Did the old loop's value training help? Full run** (v0's policy with the old run's final value model, 2,000
statements, 16 expansions; accepted 2026-11-16 08:20 UTC):

| Value model (policy v0 in all) | 0-499 | 500-999 | 1,000-1,499 | 1,500-1,999 | 2,000-2,999 | 3,000-4,499 | 4,500+ | All |
|---|---|---|---|---|---|---|---|---|
| None | 115/150 | 133/250 | 142/350 | 109/350 | 86/400 | 46/300 | 11/200 | 642 (32.1%) |
| v0 (anchors, mean of two runs) | 125/150 | 156/250 | 145/350 | 129.5/350 | 93.5/400 | 51/300 | 14.5/200 | 714.5 (35.7%) |
| The old run's final value model | 132/150 | 171/250 | 175/350 | 157/350 | 133/400 | 76/300 | 31/200 | **875 (43.75%)** |

- **+8.0 points over value v0** (95% interval +6.4 to +9.7; against each anchor alone p below 1e-15), with the policy
  unchanged. The gain is in every band and largest in the hard ones (+8 to +10 points from 1,000 characters up).
- Solved within 1/2/4/8/16 expansions: 8.7/16.7/25.1/34.2/43.8% against 10.1/16.5/22.9/29.5/35.7%: no gain at the
  first two expansions, growing from the fourth on.
- Fewer tokens for more proofs: 36.5M generated tokens against 39.7M.
- **What this changes.** The old run's in-pool gain (+17 to +20 points on its probe) was credited to the policy; a
  large part may have come from the value model. The old value benchmark, which stayed flat, missed it. Next: the old
  final policy (v35) with value v0 and with the final value model, to split the gain between policy and value.
- Not contamination by construction: probe v2 excludes every statement the old run searched. One value model, one run.

**Does the value model matter? Full run** (v0's policy, no value model, whole-completion order, 2,000 statements, 16
expansions; accepted 2026-11-16 05:24 UTC):

| Proof characters | 0-499 | 500-999 | 1,000-1,499 | 1,500-1,999 | 2,000-2,999 | 3,000-4,499 | 4,500+ | All |
|---|---|---|---|---|---|---|---|---|
| Without a value model | 115/150 | 133/250 | 142/350 | 109/350 | 86/400 | 46/300 | 11/200 | **642 (32.1%)** |
| With value v0 (anchors, mean of two runs) | 125/150 | 156/250 | 145/350 | 129.5/350 | 93.5/400 | 51/300 | 14.5/200 | **714.5 (35.7%)** |

- **The value model helps: +3.6 points** (95% interval +2.0 to +5.3; against each anchor alone p = 0.0002 and 0.00008).
  The gain is largest on short and medium proofs (+6.7 points under 500 characters, +9.2 at 500-999, +5.9 at
  1,500-1,999) and within noise elsewhere.
- Solved within 1/2/4/8/16 expansions: 9.7/14.1/20.8/27.0/32.1% without, 10.1/16.5/22.9/29.5/35.7% with: the gap opens
  from the second expansion on, as expected for a model that only orders states.
- Same compute: 39.7M generated tokens against 39.6M and 39.8M; no wall-clock stops; no throttling.
- The result does not hinge on how the value-free search orders states: the block-sum order solves 633 of 2,000
  (31.65%), +4.1 points for the value model (95% interval +2.6 to +5.7); the two orders differ by 0.4 points
  (-1.3 to +2.2).
- The 200-statement pilots had not shown it (71, 68, 65 against 70 and 75): the effect is real but smaller than a
  pilot's noise.

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

## Plan (revised 2026-11-16 with the owner)

| Order | What | Rough cost |
|---|---|---|
| 1 | Step 1's last cell: v35 with the final value model | done: 1,236 of 2,000 |
| 1b | Reasoning at equal tokens, first (owner, 2026-11-16): the no-reasoning pilot, the visible run and the no-reasoning run on 2,000 statements each, with GPU use and Lean load recorded. It decides whether the arms sample with or without reasoning | about $14 |
| 2 | Learning rates: v0 samples 48M tokens once; one training round per signal from the same trees (per-tactic GRPO, pure proof success, expert iteration with window 1 and 4, two or three rates each); the 512 held-out states pick each signal's rate. No probe runs, no gate | about $7 |
| 3 | Arm A (per-tactic GRPO), then one probe run of its final checkpoint | about $19 |
| 4 | Arm B (pure proof success), then one probe run | about $19 |
| 5 | Arms C (expert iteration) and D (GRPO plus an expert-iteration round every 4 phases), one probe run each | about $38 |
| 6 | Second pass, arm by arm: the final checkpoint a second time, phase 8, v0's policy with the arm's final value model | about $36 |
| Later | Second seeds | $19 per seed |

- Every arm: from v0 and value v0, 16 phases of 12M generated tokens, value model trained every 2 phases, stops at its
  first valid-Lean collapse (then assessed and reported).
- Expert iteration inside the loop (needed for C and D) is merged; it needs a one-phase smoke run on the node before
  arm C. Arms A and B do not need it.
- While the owner decides on the arms' mode after the reasoning comparison, the node runs the start order's check
  (v0 with value v0 in the new order, about 2.5 hours).
- Credit loaded: $190 on 2026-11-16; not a cap.

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

## Owner, 2026-11-21: a verified-progress screen before D

The owner: GRPO should not underperform on Lean; the likely cause is our credit design. Our per-tactic and
proof-success credits label a step by whether it lies on the proof the search finished (hindsight), pay a block that
progresses and then fails, and put the sequence score on the reasoning. The textbook reward (r = 1 only for a block
closing its goal) was rejected by the owner: it would reward only finishing moves, too hard for long statements.
Chosen instead: **verified progress** (`src/lean_search/rl/README.md`, "Verified progress"), r = 1 for a complete
block ending on the proof graph closer to a proof (closing included), 0 for a failing, wasted or dead-end block,
untrained when the block ends in an unknown state. Screened like the others: `screens/V_2e-5.toml`, 2e-5, 8 phases,
the same pre-registered rule (means over phases 4-8: success ≥ 34.9%, valid Lean ≥ 62.2%; guards over 7-8). D waits
for its result; the question of D's round interval (every phase or every 4th) stays open.

After reviews BN and BO the rule is the "clean block" one: r = 1 only with no failing, no-op, redundant or open-claim
tactic anywhere and not ending on a claim the block adds; samples without an r are left out of the policy data (no
optimizer steps); `mean_verified_progress`, `unscored_progress_share`, `unscored_sequences` reach `metrics/grpo.jsonl`.
Master dd2d2cc deployed (edits identical, search configs and uv.lock unchanged); `run_screens.sh` (installed copy)
started the V screen at 10:19 UTC 2026-11-21 (the A and B2 screens skipped as ended). Watch at phases 1-2: bare `have`
and failing-after-graph shares, tactics per complete block (below about 2.0?), `unscored_progress_share`, groups
trained, parameter change per phase against the A and B2 screens.

**V screen (verified progress, 2e-5), per phase** (v0 895 solved samples):

| Phase | Valid | Success | Solved | Failing after graph | Tactics | Bare `have` | Change | Mean r | Unscored | Groups trained |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | **64.5%** | 35.2% | **1,046** | 18.6% | 2.62 | 19.2% | 3.6% | 0.376 | 5.8% (755 seq.) | 1,533 |
| 2 | **63.4%** | 35.2% | 1,039 | **16.6%** | 2.35 | 19.3% | 3.3% | 0.382 | 7.1% | 1,375 |
| 3 | **66.8%** | **38.4%** | **1,132** | 22.2% | 2.49 | 18.2% | 3.0% | 0.325 | 12.1% | 1,136 |

| 4 | **67.1%** | **36.8%** | 1,025 | 20.6% | 2.22 | 20.6% | 2.6% | 0.314 | 14.5% | 927 |
| 5 | **70.3%** | **38.7%** | **1,138** | 14.9% | **1.94** | 20.2% | 2.5% | 0.381 | 15.6% | 913 |
| 6 | **71.9%** | 38.5% | 1,102 | 14.5% | 1.90 | 21.6% | 2.5% | 0.373 | 18.1% | 817 |
| 7 | **73.2%** | 38.6% | **1,161** | 11.3% | 1.92 | **23.4%** | 2.5% | 0.394 | 19.0% | 891 |

| 8 | **76.3%** | **39.3%** | **1,200** | 13.9% | 1.92 | 22.7% | 2.5% | 0.369 | 20.3% | 961 |
| 9 (extended) | **78.1%** | 38.4% | 1,121 | 9.5% | 1.87 | **25.3%** | 2.7% | 0.463 | 22.0% | 1,089 |

**V screen against the rule** (finished 18:24 UTC 2026-11-21, 96.1M tokens, none lost, no alert in 8 phases but the
phase-5 `claims_proved` warning):

- Success, mean of phases 4-8: **38.4%** (line 34.9%; C 35.9%, A screen 36.1%): passes by 3.5 points.
- Valid Lean, mean of phases 4-8: **71.8%** (line 62.2%; C 64.2%): passes by 9.6 points.
- Guards, mean of phases 7-8: tactics 1.92 (≤ 3.0) and failing after the graph 12.6% (≤ 30%) pass; bare `have`
  **23.1% (≤ 22%) fails by 1.1 points** (19.2% at phase 1; v0's runs measured 19.7-20.5% at phase 1).
- Phase 8 is the best held-out result of any run at any phase (C's best: 71.1% valid at 16, 39.6% success at 10).

By the letter of the pre-registered rule V does not pass (the bare-`have` guard). Under V's credit a bare `have`
scores 1 only in a clean block that ends on the found proof closer to it (a block ending on the claim it adds scores
0), so the guard, set against A's exploit, measures something milder here. Reported to the owner, who decides; the
node idles at HOLD since 18:25 UTC.

**Owner, 2026-11-21 ~20:00 UTC: extend V in place to 16 phases** (not fresh from v0). Done by hand with
`/workspace/runs/screens/extend_V.sh` (node-local, logged to `extend_V.log`): under the run's lock, `max_phases = 8`
→ 16 in `followup_configs/followup_screen_V_2e-5/loop.toml` (the 8-phase copy kept beside it), `finished.json` moved
aside (`finished.json.phase8_*`), servers started on version 8, `grpo_loop.sh loop`; the loop (pid 2809547) resumed
at phase 9, 20:09 UTC. `arm_loop.sh` and `followup_arm.py` are bypassed on purpose (both refuse a finished run or a
changed config). Difference from a continuous run: the 112 searches paused at phase 8's end were cut off at the
finish (2.3M tokens lost), so phase 9 starts its searches fresh. No 16-phase rule was pre-registered for V; the
screens' stop rule (mean success of 10-12 at least 1 point below 6-8) is read, and the probe of phase 16 paired
against C (1,049) and v0 decides. About 8.5 h, then the probe run (about 2.5 h).

Phase 5 had a `claims_proved` warning (6.3% of open claims proved below the band). Tactics per complete block fell
below 2.0 (the shortening the reviews expected under a 0/1 reward); held-out keeps rising, so it reads as cheaper
blocks, not a collapse.

Phase 3 is the highest held-out result of any run at phase 3 (C: 59.1% / 33.0%; A screen 60.3% / 35.9%). Phase 4 has
no dip (every earlier GRPO run fell to 54-57% valid at phase 4; C 61.4% / 35.4%). Watch: the unscored share rises
(5.8 → 14.5%) and the groups trained fall (1,533 → 927).

Phase 1 is the best first phase of any run (A screen 61.2% / 33.6%, B2 59.2% / 34.4%, C 59.6% / 34.3%).

## Owner, 2026-11-21: run D with its GRPO at 2e-5

D's GRPO learning rate 5e-5 → 2e-5 (the A screen's setting: credit, cap, claim switches, rate); its rounds keep C's
rate (5e-5) and window (reviews BL, BM; earlier entries saying D uses 5e-5 are superseded). Review BM: with a round
every 4th phase, D trains each block in one round where C trains it in four, so D against C measures "GRPO minus 12
rounds"; only "D clearly ahead of C" would say something about GRPO. Rounds every phase (D = C's schedule plus the
A screen's GRPO step) would make D against C a two-sided test. The owner decides before D starts.

## Arm A (capped) probe and the screens' start, 2026-11-20

- **Arm A's capped rerun, probe `probe_arm_A_phase16_run1`: 822 of 2,000 (41.1%)**, accepted, no wall-clock stop.
  Against the v0 anchors +5.4 points [+3.7, +7.1] (ahead in every band, significantly in five); against arm C −11.3
  [−13.3, −9.3] (behind in every band, most at 2,000-4,499 characters, −14.5 and −15.3); against v35 with the final
  value model −20.7. Solved within 1 expansion 9.7% (v0 10.1%, C 13.1%): A's gain comes only from deeper searches.
  The phase-8 adapter (A's held-out peak) is staged in `arms_chain/adapters/A` but not probed.
- HOLD "waiting for: D" at 14:55 UTC. Master eb75e61 deployed (edits identical, search configs and uv.lock unchanged),
  merged weights of `followup_A` and `followup_C` removed (both probed; regenerable from their adapters; 128 GB free),
  `run_screens.sh` started 15:13 UTC: the A screen at 2e-5 first, then B2 at 2e-5.

**A screen (2e-5), per phase** (held-out valid / success / solved samples; failing after the graph; tactics per complete
block; bare `have`; parameter change):

| Phase | Valid | Success | Solved | Failing after graph | Tactics | Bare `have` | Change |
|---|---|---|---|---|---|---|---|
| 0 (v0) | - | - | 898 | - | - | - | - |
| 1 | 61.2% | 33.6% | 977 | 19.4% | 2.68 | 20.7% | 4.5% |
| 2 | 57.2% | 34.9% | 979 | 23.5% | 2.60 | 21.3% | 3.6% |
| 3 | 60.3% | 35.9% | 1,004 | 31.3% | 2.65 | 19.8% | 3.4% |
| 4 | 56.8% | 34.2% | 922 | **37.4%** | 2.70 | 21.1% | 3.0% |
| 5 | 61.8% | 36.0% | 1,003 | 36.7% | 2.62 | 19.3% | 3.1% |
| 6 | 62.6% | 34.8% | 961 | 33.8% | 2.46 | 18.2% | 3.2% |
| 7 | 63.2% | **37.9%** | **1,101** | 30.8% | 2.79 | 20.6% | 3.0% |
| 8 | 64.6% | 37.8% | 1,102 | 28.2% | 2.77 | 21.7% | 3.1% |

**A screen against the rule** (finished 00:11 UTC 2026-11-21, 96.1M tokens, none lost, no alert):

- Success, mean of phases 4-8: **36.1%** (line 34.9%; C 35.9%): passes.
- Valid Lean, mean of phases 4-8: **61.8%** (line 62.2%; C 64.2%): **misses by 0.4 points**.
- Guards, mean of phases 7-8: tactics 2.78 (≤ 3.0), failing after the graph 29.5% (≤ 30%), bare `have` 21.2% (≤ 22%):
  all pass, the last two narrowly.
- Against its own v0 baseline (898 solved samples) and A capped's phases 4-8 (33.6%, 60.5%): far better than any
  5e-5 A run; level with C on success, about 2.4 points behind on valid Lean.

By the pre-registered rule the A screen does not pass (valid Lean). Reported to the owner; the B2 screen started
00:13 UTC.

**B2 screen (proof-success credit, 2e-5), per phase** (same columns; v0 938 solved samples):

| Phase | Valid | Success | Solved | Failing after graph | Tactics | Bare `have` | Change |
|---|---|---|---|---|---|---|---|
| 1 | 59.2% | 34.4% | 981 | 19.9% | 2.61 | 20.1% | 4.0% |
| 2 | 57.8% | 35.0% | 1,010 | 19.5% | 2.50 | 20.0% | 3.5% |
| 3 | 58.1% | 35.9% | 1,030 | 33.0% | 2.70 | 20.3% | 3.4% |
| 4 | **54.1%** | **32.4%** | 892 | 30.2% | 2.68 | 22.5% | 2.7% |
| 5 | 53.6% | 33.9% | 955 | 36.0% | 2.93 | 23.4% | - |
| 6 | 53.3% | 33.6% | 925 | **40.7%** | **3.17** | 23.1% | - |
| 7 | 55.1% | 36.1% | 1,021 | 41.3% | 2.78 | 22.0% | - |
| 8 | 58.3% | 37.4% | 1,049 | 35.0% | 2.83 | **27.2%** | - |

**B2 screen against the rule** (finished 08:48 UTC 2026-11-21, 96.1M tokens, none lost): success mean of phases 4-8
**34.7%** (line 34.9%), valid Lean **54.9%** (line 62.2%), guards over phases 7-8: tactics 2.81 (passes), failing
after the graph 38.2% and bare `have` 24.6% (both fail). Does not pass.

**Screens' outcome: neither passes the pre-registered rule.** The A screen (2e-5) comes closest: level with C on
held-out success (36.1% against 35.9%, phases 4-8), 2.4 points behind on valid Lean, 0.4 below the line. B2's
outcome-only credit, at the same rate, is clearly worse: lower valid Lean in every phase from 4 on, and the failing-
after-graph habit (35-41%) and bare `have` (27% at phase 8) it was expected to avoid grow faster than under A's
capped per-tactic credit. So the shaping was not the main problem; the step size was. Per the rule D stays held and
the node is idle since 08:50 UTC (servers stopped), awaiting the owner.

After phase 5 B2 cannot reach the valid-Lean line: phases 6-8 would need 67.8% each (its best so far 59.2%).

Phase 3 had a `valid_blocks` warning, phase 4 a `claims_proved` one. The phase-4 dip of every A run shows here too,
deeper than the A screen's (56.8%, 34.2%).

Phase 5 had a `valid_blocks` warning (21.2% of sampled blocks complete), as phase 2.

## Owner, 2026-11-20 ~10:50 UTC: hold D, screen two GRPO fixes

A's capped rerun peaked at phase 8 and slid back to v0's held-out level, its blocks lengthening to 4.0 tactics.
Diagnosis: (1) GRPO's step is about 3x C's (6-10% parameter change a phase against 2-3%; KL penalty about 0.0006);
(2) the per-tactic shaped reward is exploited route after route (bare `have`, failing tails, now long blocks);
(3) about half the samples never reach the graph and push down at about −0.35 each. D shares A's signal, so it is held
(`hold_D`, 10:59 UTC): after A's probe the driver writes HOLD "waiting for: D".

Two screens of 8 phases each at the same rate, so they differ only in their credit (reviews BJ, BK):

- `followup/screens/A_2e-5.toml`: arm A unchanged (claim switches, explanation cap) at 2e-5. A at 2e-5 moved the
  LoRA 4.3% in phase 1 against 10.4% at 5e-5; C moves 2.0-3.4% a phase. Tests problem 1.
- `followup/screens/B2_2e-5.toml`: arm B2, proof-success credit (every token r − mean r, r = 1 on reaching the found
  proof's graph), at 2e-5. No per-tactic progress steps; a block failing after the graph still counts r = 1, and the
  claim switches and the cap do not act on this credit (review BK). Tests problem 2 against the A screen.

**Decision rule, fixed before the screens publish phase 4 (review BK).** Held-out success and valid Lean, means over
phases 4-8 (C: 35.4 / 35.5 / 35.2 / 36.4 / 37.1% success, mean 35.9%; valid mean 64.2%; A capped: 33.6% and 60.5%):

- A screen passes when its means reach at least 34.9% success and 62.2% valid Lean (C's minus 1 and 2 points) and at
  phases 7-8 it shows no exploit (means of the two): tactics per complete block at most 3.0 (v0 measured 2.55-2.70),
  failing after the graph at most 30%, bare `have` at most 22%. Both pass: the higher success mean; within 0.5 points, the higher valid mean. Neither passes:
  that is the result (no GRPO variant matched C through phase 8, one seed), reported to the owner; D stays held.
- The passing screen then runs from v0 to 16 phases with a probe run, under a new arm-kind overlay and run name
  (for example `arms/A_2e-5.toml`, `followup_A_2e-5`; written and reviewed when the screens are in); it is stopped and reported
  if the mean success of phases 10-12 falls 1 point or more below that of phases 6-8 (A capped: 33.1 against
  34.6, which trips it; 1.5 would not). The probe, paired against C's, decides.
- Reported alongside: each mean against the run's own v0 baseline (C's sits about a point above A's), solved
  held-out samples per phase, of 4,096 draws (the rate's denominator moves), parameter change per phase,
  and phase 1 against A capped's (same seed and curriculum: a sanity check). One seed, the same 512 states every
  phase: a selection rule, not a significance test.

Run: master deployed at the driver's HOLD "waiting for: D" (after A's probe; never while the script runs), then
`mkdir -p /workspace/runs/screens && cp deployment/run_screens.sh /workspace/runs/screens/run_screens.sh` and
`(cd /workspace/LLM-Search-Lean-Proofs && setsid nohup bash /workspace/runs/screens/run_screens.sh >
/workspace/runs/screens/run.log 2>&1 < /dev/null &)`. Each screen: skipped once ended (finished.json or
health_stop.json), adopted while its loop runs, else every server stopped, the GPUs waited on (up to 1 h) and the
screen started through `arm_loop.sh --kind smoke`, resumed at most 3 times; its servers stopped before the next.
STOPPED in `/workspace/runs/screens/` on a failure. About 8.5 h each.

## Arm C finished; arm A's rerun started 2026-11-19 12:45 UTC

- **Arm C** (expert iteration, 5e-5, window 4): 16 phases, 192.1M generated tokens (0.2% lost), 14.9 loop hours, no
  health alert, no traceback, no wall-clock stop. Probe run `probe_arm_C_phase16_run1` (C's phase-16 policy with its
  own phase-16 value model): **1,049 of 2,000 (52.45%)**, accepted.
  - Against the v0 anchors (714.5): **+16.7 points** [+15.0, +18.5], every band ahead (+9 to +22).
  - Against v35 with the old run's final value model (run 7, 1,236): **−9.3 points** [−11.5, −7.4]; level under
    1,000 characters, −7 to −15 points above. Against v35 with value v0 (run 8, 1,083): −1.7 points (not paired-tested).
  - Compute: 192M training-search tokens against the old run's 495M (39%).
  - Held-out states: valid Lean 59.6% → about 69% from phase 9 on (71.1% at 16); success 34.3% → 39.6% at phase 10,
    then flat at 38-39%. Training-search solve rate fell from 0.66-0.73 (phases 1-8) to 0.59-0.62 (13-15).
  - Expert-iteration loss 0.34 → 0.19, distinct samples per expansion 7.47 → 7.06; verified proofs per phase 4,111
    (phase 1) → about 900 (from phase 9); bare-`have` share 19.9% → 14% (phases 2-4) → about 20% (9-16), no drift.
  - Degree-bounded nlinarith: 1-4% of verified proofs per phase fail plain Mathlib (almost all on its wall clock);
    up to 20 solved trees per phase have no plain-passing proof.
  - Sampling was 54% of the wall clock (7.5 of 14.0 h over phases 1-15); each pause 21-35 min (policy training ~4,
    value training 6-9 every second phase, server wake ~6, held-out check ~6.5).
  - Provisional: one probe run, one seed; the comparisons used different start orders (run 9 showed the order does
    not change v0's result).
- **Arm A's rerun**: master b5f6425 deployed at the HOLD (node-local edits identical, `experiments/configs/grpo/search/`
  and `uv.lock` unchanged); old run moved aside as `*.bug_20261119T124352Z`; `hold_A` removed; the driver started A
  from v0 at 12:45 UTC with `claims_earn_progress = false`, `unproved_claim_cost = 0.3`, 5e-5. Then D.
- **A's claim watch, phase 2** (`runs/arms_chain/claim_watch/A_phase2.md`, 15:48 UTC): bare `have` 19.7 → 23.6%
  (+3.9 points; the first run went 20.5 → 23.3%, +2.8); proved in their block off the graph 7.2 → 9.5% of samples
  (1.32x); left open with a failing attempt after 5.8 → 7.1% (1.23x); open claims proved 14.0 → 11.0%; `have … :=`
  8.6 → 9.7%. The bare class is now net negative on the proof graph (−0.097 per sample), the decomposition premium
  1.84x → 1.67x. Held-out after phase 2: valid 56.5%, success 34.1% (v0 58.7%, 33.2%). Under every stop line so far;
  the rule reassesses at phase 4.
- **A's claim watch, phase 4** (`A_phase4.md`, 17:30 UTC): **no stop line crossed**; the habit went back. Bare `have`
  19.6% (−0.2 points against phase 1; the first run was at 28.4%); proved off the graph 1.01x; open with a failing
  attempt after 1.07x; open claims proved 9.3% (14.0%); `have … :=` 10.3% (8.6%); decomposition premium 2.66x (1.84x);
  bare class −0.019 per sample; explanation tokens 112 (97). A goes on under the rule.
  - But held-out does not improve: valid 60.4 / 56.5 / 58.4 / 55.7%, success 33.1 / 34.1 / 34.9 / 31.2% after phases
    1-4 (v0 58.7%, 33.2%; held-out states solved 970 at v0, 918 / 956 / 1,004 / 871). The first run at phase 4: 53.1%,
    30.1%; arm C at phase 4: 61.4%, 35.4%. Phase 3 had a `valid_blocks` warning (21.0% < 22.1%).
- After phase 5: held-out valid 58.4%, success 33.8% (960 states): back at v0's level; bare `have` 20.8%.
- **Credit on blocks that fail after progress** (owner's question, 2026-11-19 18:05 UTC; replay of A's phases 1-5 on
  the node, `experiments/analysis/continuation_credit.py`, not yet reviewed; output
  `runs/arms_chain/claim_watch/continuation_A.md`). Of the trained samples reaching the proof graph, 22% (phase 1) →
  34% (phase 5) then run a failing tactic. Their mean sequence advantage is +0.35 to +0.41 (72-77% positive) against
  +0.43 to +0.51 for complete blocks on the graph: a block that fails after progress earns about 85% of a clean one,
  because the failing tactic costs only c = 0.1 (`wasted_tactic_cost`; continuing pays from P(correct) > 1/3) and the
  prefix keeps its progress. The continuation tactics net about 0 (+8 to +56 per phase).
  - Replayed (trained groups unchanged in all): c = 0.3 → +0.21 to +0.29 (63-67% positive); c = 0.5 → +0.07 to
    +0.18 (55-61%), but never-on-graph samples then turn positive in 15-20% (the baseline falls); "a block failing
    after progress gets no positive advantage" → −0.04 to −0.06 (0% positive), other classes unchanged.
  - The owner's alternative, a cost per never-run tactic after the first failure (`continuation_A_masked.md`, phases
    1-5; failing blocks after progress have 1.15-1.74 never-run tactics, falling): at 0.1 each, fails after the graph
    +0.29 to +0.38 (70-73% positive), at 0.3 +0.17 to +0.32 (64-70%); it barely closes the gap, and never-on-graph
    samples turn positive in 7-8% (0.1) or 18-21% (0.3) because the baseline falls. Combined with "never positive":
    −0.07 to −0.11 (0%), never-on-graph 7-8% positive. "Never positive" alone: −0.04 to −0.06, every other class as
    under the phase's reward.
  - Caveat: the search keeps the prefix as a child, so such blocks still advance a 16-expansion search; the held-out
    check (one expansion) penalises them fully. Arm C (positives only) shortened its blocks (2.7 → 2.1 tactics,
    continue rate 0.86 → 0.80); A kept them (2.5-2.7, 0.86 → 0.89).
- **Owner, 2026-11-19 ~18:50 UTC: cap the reasoning, keep the tactics, rerun A now.** Built as
  `[policy.data] cap_wasted_block_explanation` (reviews BH, BI; widened after BI from failing blocks to blocks with
  any wasted tactic: replayed, "charged on graph" blocks, a no-op/redundant/open-claim/off-graph ending after
  progress, 435-745 samples a phase, earned +0.33 to +0.46 like clean ones). It removes 30-40% of the positive
  explanation credit, no tactic credit. On in A and D (D's phase config is A's by design). The uncapped rerun
  (`followup_A`, phases 1-6) is stopped and moved aside; A restarts from v0 with the cap, so A and D both train capped
  from phase 1. The uncapped rerun's last phase (6): held-out valid 60.2%, success 34.1% (956 states; v0 58.7%,
  33.2%), bare `have` 24.9% (+5.2 points over phase 1), failing after the graph 33.8%; stopped 19:10 UTC after its
  phase-6 pause. What should move against the uncapped rerun: on-graph samples failing after the graph (22-34%),
  held-out valid Lean and success, perhaps tactics per block and the continue rate; the probe run decides.
- **Capped rerun, early signs** (started 19:27 UTC from v0; v0 held-out 945 states). The cap fired on 1,934 samples
  (−1,085 positive explanation credit) in phase 1 and 1,595 (−864) in phase 2. Capped against uncapped rerun:

  | After phase | Bare `have` | Failing after graph | Tactics per block | Continue rate | Explanation tokens | Held-out valid | Held-out success |
  |---|---|---|---|---|---|---|---|
  | 1 (v0's samples) | 20.5% / 19.7% | 19.4% / 19.0% | 2.60 / 2.57 | 0.87 / 0.86 | 97 / 97 | 60.7% / 60.4% | 33.2% / 33.1% |
  | 2 | **16.0% / 23.6%** | **18.8% / 22.3%** | 2.65 / 2.69 | 0.87 / 0.89 | **98 / 103** | 57.0% / 56.5% | 33.4% / 34.1% |
  | 3 | 17.3% / 20.9% | 28.8% / 34.8% | 2.39 / 2.64 | 0.89 / 0.89 | 104 / 106 | 61.4% / 58.4% | 34.8% / 34.9% |

  | 4 | 21.5% / 19.6% | 24.8% / 33.4% | 2.26 / 2.49 | 0.87 / 0.89 | 106 / 112 | **54.6% / 55.7%** | **31.1% / 31.2%** |
  | 5 | 14.4% / 20.8% | 33.9% / 31.7% | 2.10 / 2.46 | 0.87 / 0.87 | 104 / 115 | 58.6% / 58.4% | 33.1% / 33.8% |
  | 6 | 15.9% / 24.9% | 33.3% / 33.8% | 2.21 / 2.60 | 0.86 / 0.90 | 103 / 121 | 61.5% / 60.2% | 33.0% / 34.1% |
  | 7 (capped only) | 15.4% | 27.6% | 2.28 | 0.84 | 107 | 62.7% | 34.6% (1,034 states; C at 7: 64.6%, 36.4%) |
  | 8 (capped only) | 17.8% | 28.6% | 2.35 | 0.85 | 111 | 65.0% | 36.1% (1,058 states; C at 8: 67.2%, 37.1%, 1,016) |
  | 9 (capped only) | 18.1% | 26.0% | 2.43 | 0.85 | 112 | 62.0% | 35.6% (1,014 states; C at 9: 69.4%, 37.9%, 1,045) |
  | 10 (capped only) | 21.3% | 30.7% | 2.62 | 0.85 | 112 | 60.0% | 33.9% (987 states; C at 10: 67.9%, 39.6%, 1,127) |
  | 11 (capped only) | 21.7% | **36.9%** | 2.52 | 0.87 | 109 | 59.2% | **31.3%** (899 states; C at 11: 69.0%, 38.8%, 1,077) |
  | 12 (capped only) | 19.6% | 37.7% | 2.66 | 0.89 | 109 | 58.2% | 34.2% (1,010 states; C at 12: 69.8%, 38.5%, 1,076) |
  | 13 (capped only) | 20.2% | 35.0% | **2.99** | 0.89 | 108 | 61.7% | 32.9% (944 states; C at 13: 68.9%, 38.2%, 1,074) |
  | 14 (capped only) | 19.0% | 30.1% | **3.13** | 0.88 | 109 | 62.8% | 31.4% (940 states; C at 14: 69.7%, 38.7%, 1,058) |
  | 15 (capped only) | 20.4% | 26.1% | **4.00** | 0.86 | 102 | 63.2% | 32.0% (913 states; C at 15: 68.4%, 38.3%, 1,063) |
  | 16 (capped only) | 18.5% | 28.1% | 3.10 | - | - | 62.1% | 33.8% (C at 16: 71.1%, 38.8%) |

  The capped rerun finished 11:48 UTC 2026-11-20 (192.1M tokens, 0.2% lost, no alert in 16 phases); its probe run
  (phase 16 with its own value model) started 11:50 UTC.

  Blocks lengthen from phase 12 on (2.66 → 4.00 tactics per complete block) while failing after progress falls
  (37.7 → 26.1%): the model writes longer blocks that complete; phase 15's sampling took 39 min (others 26-31).

  Phase 12's training searches solved 225 of 441 trees (51%, the run's lowest; 793 trainable groups against
  1,000-2,000 before). The share failing after progress is back above the uncapped rerun's (33-35%) from phase 11 on.

  After its phase-8 peak the capped rerun slides back: held-out success 36.1 → 35.6 → 33.9%, and blocks lengthen
  again (2.35 → 2.62 tactics, bare `have` 17.8 → 21.3%).

  Phase 3 had the same `valid_blocks` warning in both runs (21.0% of sampled blocks complete). At phase 4 all three A
  runs dip to the same held-out level (success 30.1% first run, 31.2% uncapped, 31.1% capped; held-out states 836
  capped against 871) although the capped run fails after progress far less and writes shorter blocks: the dip does
  not follow the credit fixed so far. Arm C at phase 4: 61.4%, 35.4%.

- **Disk**: 90% full at the HOLD (33 GB free; an arm needs about 38 GB). Removed the merged `weights/` folders of
  `followup_A.bug_20261119T124352Z`, `followup_smoke_C`, `followup_smoke_D` and
  `followup_shared_sampling.failed_value_benchmark_20261118` (rebuilt from the adapters kept beside them): 113 GB free.

## Why arm A drifted into bare `have` claims (measured 2026-11-18 on all of A's trees)

- Bare claims left open and never proved are already net negative every phase (−0.36 to −0.46 per sample; the −0.25
  penalty is applied).
- But the bare-`have` opening as a class is net positive in every phase (+4k to +26k of summed token advantage per
  phase, v0's phase included), almost all on the explanation tokens. It is paid by bare `have` blocks that prove their
  own claim in the same block (9 → 14% of samples): progress is counted per flattened tactic, so every claim tactic
  earns its own δ = 0.2 step, and a decomposition is paid per claim it states (+0.9 to +1.3 on the proof graph against
  +0.3 for a direct tactic). Open never-proved claims grow alongside (5.9 → 10.4% of samples).
- **Fix** (branch `bare-have-claim-switches`, under reviews BF and BG): `claims_earn_progress = false` (a claim tactic
  earns no δ of its own) and `unproved_claim_cost = 0.3` (from 0.1), both off by default and on for arms A and D.
  Replayed on the same groups (v0, A1-A7, the 2e-5 run's 2 phases): the bare class becomes net negative in all ten
  (e.g. A1 +19.6k → −9.3k), self-proving decompositions stay positive (+0.16 to +0.23 per sample), trainable groups
  unchanged, positive proof-graph mass −2 to −5.5%. Weaker variants (either switch alone, cost 0.2) stay positive in
  2-8 of 10 phases.

## Arm A's rerun: the fix and its stop rule (owner, 2026-11-18)

- The claim reward switches (master `2a1caf4`, reviews BF and BG) are merged and deployed (b5f6425, 2026-11-19 12:44
  UTC, at the HOLD after arm C); A rerun from v0 since 12:45 UTC.
- **Stop rule (owner):** after phases 2 and 4 the orchestrator runs `experiments/claim_watch.py --run
  /workspace/runs/followup_A --phase <k>` on the node; reassess at phase 4 (report to the owner, who decides) if the
  bare-`have` share rose more than 5 points over phase 1, or either growing subclass (bare claims proved in their block
  off the proof graph; open claims followed by a failing attempt) grew more than 1.5x. Also watched: `suffices`/
  `obtain`/`have … :=` as substitutes, claims proved, the on-graph decomposition premium, explanation tokens,
  held-out against v0.

## Smoke test passed (by hand), arm C started 2026-11-18 18:49 UTC

Smoke C and D (6M tokens, one phase each; D with GRPO, value training and a round in one pause, killed by SIGKILL 30 s
into publishing and restarted) passed every gate but one: "GPU memory before the wake" read the LAST such line, which
for D comes from the restart after the kill, with the servers already up on version 0 (1.9 GiB free). D's line before
the kill showed 23.0 of 24.0 GiB free against the servers' 21.6: a pass. The orchestrator accepted the test by hand
(`done_smoke`; note appended to `smoke_report.md`); the gate is to be fixed. Readings: rounds of 774 and 794 examples
from about 148 solved trees, 7-8 optimizer steps, 70-77 s of training; D's whole training stage 20 min; /dev/shm peak
33.7 of 71 GiB; replay validation loss +3.3% after C's round (alert, recorded). The node idled 17:35-18:48 (the PC
slept, so the stop was seen late).

## Smoke test and arm C first (owner, 2026-11-18)

While A's reward is fixed, the arms driver runs in the order `smoke C A D` with A held (`order`, `hold_A`; review BE,
master `d03ff06`). The smoke test started 15:13 UTC (smoke C, then smoke D with the kill during publishing), then arm
C (about 21-23 h with its probe run), then HOLD "waiting for: A". There: deploy the reward fix, the rerun path for A,
remove `hold_A`, start; A from v0, then D.

## Arm A stopped 2026-11-18 14:39 UTC (owner): bare-`have` drift

After 6 trained phases at 5e-5 (phase 7 sampled), bare-`have` openings rose every phase, 20.5 → 32.4% (below the band
16.8 → 26.6%); `have` as first tactic 28 → 42%; the share of those claims the tree later proves stayed at ~11%;
`have … :=` (proved inline) flat at 8-10%. Held-out valid Lean 0.624 → 0.537 (v0 ~0.572), success 0.342 → 0.317 (v0
~0.321): no collapse, but no gain and a drift with the habit. The old run's reward fix (−0.25 on an unproved claim) is
active and does not hold it. The owner decided to fix the reward and rerun A from v0 (D shares the GRPO signal; C's
data excludes open claims). Stopped with `pause_A` and `grpo_loop.sh stop`; the arms driver halts on the pause. Being
done: the credit bare-`have` samples get in A's trees, a fix, an offline replay, two reviews. The habit alert did not
fire because `health_checks.py` compares the below-band share against 1.5× the reference's all-statements share; fixed
with the reward change.

## Arms driver installed 2026-11-18 10:53 UTC

`deployment/arms_chain.sh` (reviews BC and BD with re-reviews; master `6f3ce10`) adopted the running arm A without
touching it. It then runs: A's adapters (phase 8 and final) and one probe run, the C/D smoke test (6M tokens, one
phase each, GRPO + value + a round in one pause, a kill during publishing), arm C, arm D, each with its probe run and
comparisons, then HOLD with the servers stopped. A health stop: the owner chose `continue` (2026-11-18): the driver writes
the stopped arm's report, goes on with the next arm, and asks for the owner's word on the stopped one at the end. The PC pull now includes `runs/arms_chain` and every `runs/followup_*`, and
fetches each arm's adapters into `node_backup/2026-11-15/adapters/<arm>/` with a checksum check.

## Arm A restarted 2026-11-18 07:15 UTC at 5e-5

The owner chose 5e-5 for A (step 2 tied 2e-5 and 5e-5; C and D use 5e-5), so D's GRPO rate is 5e-5 too (master
`0e04599`). The first start at 2e-5 (04:58-07:10, one phase published, no health alerts) was stopped cleanly with
`grpo_loop.sh stop` and kept as `followup_A.lr2e-5_stopped_20261118`. Arm-chaining automation and the expert-iteration
smoke test before arm C are being written.

Earlier start, superseded: per-tactic GRPO at 2e-5, from v0 and value v0, 16 phases of 12M generated tokens, value trained every 2 phases, visible
reasoning with the search-efficiency switches (master `0f12c1d`). Started by hand with `deployment/arm_loop.sh`; the
automation that runs the arms one after another (with each arm's probe run and adapter pull) is not written yet.

## Step 2 results (2026-11-18, `node_backup/2026-11-15/live/runs/study_chain/learning_rates_report.md`)

One per-tactic GRPO round from v0 on the shared phase (385 trees, 2,085 groups, 245 steps, 2.2M trained tokens), each
rate against v0 on the 512 held-out states (points, 95%):

| Rate | Valid Lean | Success |
|---|---|---|
| 2e-5 | +3.4 [+1.1, +5.8] | +0.4 [-2.7, +3.0] |
| 5e-5 | +4.9 [+2.6, +7.1] | +0.5 [-2.0, +2.7] |
| 1e-4 | +3.8 [+1.9, +6.5] | -2.6 [-4.7, -0.2] |

- **Chosen for A: 2e-5** (tied with 5e-5 on the held-out states; the lower rate by the rule). D: 2e-5 and 5e-5;
  C: 5e-5 (O2). 1e-4 already lowers success after one round.
- v0's A/A check (start against end of the step): valid Lean +0.5 [-1.5, +3.0], success -0.4 [-2.8, +1.9].
- The step took 3.5 h in all: sampling 0.85 h (12.3M tokens), three rounds 1.4 h, held-out runs 0.9 h.

## Step 2 (A's learning rate), started 2026-11-18 00:38 UTC

Master `c15afc5` deployed (node-local edits unchanged; the node's Lean tests at it: 548 passed). The step-2 driver runs
in the visible mode (`followup/modes/visible.toml` → `search/visible_student_v2_sampling.toml`: result cache, timeout
skip at 2, degree-bounded `nlinarith`, 8 warm spares). The shared sampling loop started 00:47 UTC (112 searches plus
8 spare REPLs). Then: A's three GRPO rounds, held-out runs, ranking, HOLD; about 3-4 h.

- First start failed at once (00:52): the loop reads a value benchmark (`grpo_gate/benchmark.json.gz`) that was never
  built on this node. Turned off in `followup/base.toml` (master `2c74e67`; a trend nothing acts on), failed state
  moved aside (`*.failed_value_benchmark_20261118`), restarted 01:19.
- **Shared sampling done: 12.3M generated tokens in 37 min** (01:34-02:11 UTC, after the loop's 6-minute v0 held-out
  baseline), 385 trees, 4,356 verified proofs; 102 searches cut off at the stop (2.4M tokens
  not counted, as designed).
- **Plain-Mathlib check:** 3 of 4,356 verified proofs (0.07%) fail it, all at its 60 s limit; no solved tree lacks a
  plain-verified proof. The bounded `nlinarith` does not change what the arms train on in any material way.

## Offline run O2 (token-matched), 2026-11-17

- Data: 2,091 pool proofs (about 299 per proof-length band), 30,632 blocks of 1-5 tactics, 2.0M completion and 17.3M
  prompt tokens; 4 epochs from v0 without reasoning, 60/30/10% offline/Lean/math replay. Training at 12.1k tokens/s
  sustained on 4 GPUs (2.2 h per rate).
- Held-out states without reasoning, against v0 in the same mode (points, 95%): valid Lean +10.5 [+8.3, +13.1] at 5e-5
  and +11.8 [+9.4, +14.5] at 1e-4; success (reaching the reference's next state) -2.9 [-5.7, -0.5] and -2.7
  [-5.7, -0.4] on the flattened measure, -5.0 and -5.6 on the standard one. More valid steps, fewer that land exactly
  on the reference proof's next state; the probe run decides what that means for search.
- Chosen: 5e-5 (the two rates tie; the lower rate). C and D take 5e-5.
- **Probe run `offline_arm_matched`** (no reasoning, value v0, 16 expansions, depth weight 0.1, longest expected
  search first; 2.0 h, 0 wall-clock stops): **545 of 2,000 (27.3%)**.
  - **Gate: not passed.** Against run 8 (v35, value v0): -26.9 points (95% -29.1 to -24.7), behind in every band.
  - Descriptive (settings differ): against v0 without reasoning (run 4, within 16 expansions) -7.2 points (-9.0 to
    -5.2); against the v0 anchors -8.5 (-10.2 to -6.9); behind in every band. The anchors' noise floor is -0.1 (-1.8
    to +1.6).
  - So SFT on 2M tokens of known pool proofs, cut into 1-5-tactic blocks, made v0 WORSE at search, although its
    held-out valid Lean rose by 10 points. Its searches spread over more distinct valid children (4.7 per expansion
    against 2.5 for v0) and make less progress per expansion. The depth weight (0.1 against run 4's 0) is not
    controlled; a v0 run at 0.1 would separate it (about 6 h).
  - **Consequence (owner's rule of 2026-11-17): the arms sample WITH visible reasoning.** Report:
    `node_backup/2026-11-15/live/runs/offline_chain/report_matched.md`.

## Lean overhead (measured 2026-11-17 at HOLD; files in `node_backup/2026-11-15/live/runs/lean_overhead/`)

Run 4 (no reasoning): 575 Lean-hours, 41.2 s of Lean per expansion.

- **`nlinarith` written by the policy is 68% of all Lean time** (393 h): 105k calls, 2,221 successes. Its cost grows
  with the number of comparisons (hint terms + comparison hypotheses + negated goal): calls with 13 or more take 332 h
  (58% of all Lean time) at 2-3% success, and hold 229 uses on proof paths.
- **Kills:** 8,797 restarts (8,705 at the 60 s wall clock), about 8.3 s each: 24 h (4.2%); replays after them 21 h
  (3.7%); the timed-out steps themselves 145 h (25%).
- **Heartbeats do not separate slow failures from slow successes.** Replaying 200 timed-out and 200 slow successful
  steps alone: at 20k heartbeats only 81 of the timed-out ones stop within 20 s, while 159 of the 200 slow successes
  would be stopped; at 50k only 6 timed-out ones stop within 20 s. About a quarter of the timed-out steps run past
  120 s even at 200k heartbeats, and about 18% crash the REPL.
- **Work done twice:** duplicate children found after Lean 51 h (8.8%); a (state, tactic) result cache inside a search
  would save about 39 h (6.8%); skipping a text after its second wall-clock timeout in the same search 12 h (2.0%)
  with no proof lost.
- Run 3 (visible) shows the same pattern at half the scale (restarts 4.2%, replays 3.6%, duplicates 8.2%).

**Search efficiency package** (branch `worktree-agent-a884d29b93192b24f`, switches off by default, under reviews AY
and AZ; measurements in `node_backup/2026-11-15/search_efficiency/`):
- Result cache within a search, keyed by the tactic path: 6.1% of run 4's Lean time (5.7% net of re-run wall-clock
  stops).
- Skip a tactic text after its 2nd wall-clock stop in a search: 2.0%, no proof lost; labelled as a wall-clock timeout.
- Warm spare processes: a kill costs 0.2 s instead of 6.2 s (median) when a spare is ready; 0.24 GiB private memory per
  spare; 8-12 per pool recommended. Removes most of the 4.2% restart cost.
- Bounded `nlinarith` (300 of run 4's calls rerun alone, five product rules): only the degree-bounded variant keeps
  most successes (93%) while cutting nlinarith time by about 29% (about 20% of all Lean time); the cheaper ones lose
  27-45% of successes. No default change; a search A/B would be needed.
- The node's Lean tests at the package's head: 489 passed.

## Start-order check (run 9, 2026-11-17)

`step1_run9_v0_value_v0_ordered` (v0 with value v0, the anchors' settings, longest expected search first): **708 of
2,000** (35.4%), 0 wall-clock stops, 3.06 h (anchors 3.17 and 3.58 h). Against the anchors: -0.2 and -0.4 points
(95% -2.0 to +1.5 and -2.1 to +1.4), inside their A/A difference; Lean load 3,498 timeouts in 368 statements against
2,856-3,209 in 367-375. The check passes: the arms' probe runs may start longest expected search first. The node
reached HOLD at 09:30 UTC.

## Decisions and open points (owner, 2026-11-17)

- **Offline arm: agreed in principle.** From v0, SFT on known proofs of the pool statements a loop arm would see, cut
  into blocks of 1-5 steps, with at least the loop's training tokens. Step-level GRPO along known trajectories is
  doubtful (it may push down nearly every sample, since samples rarely land on the known path); the arm's exact design
  is still to be discussed.
- **Offline runs, revised:** two, both from the pool's known proofs only (no extra corpus): O1 on all usable pool
  proofs, and O2 token-matched to an expert-iteration arm (about 2M completion tokens), sampled with an equal number of
  proofs per proof-length band (so slightly towards longer proofs), trained 4 epochs (as a 4-phase expert-iteration
  window sees each block about 4 times; O1 one epoch). Each: SFT from v0 without reasoning, two rates
  picked on the held-out states, then one 2,000-statement probe run (no reasoning, value v0, 16 expansions, depth
  weight 0.1). **Gate:** if the offline policy beats v35 with value v0 (run 8, 1,083 of 2,000) with the paired 95%
  interval above 0, the arms run without reasoning; otherwise with reasoning. Offline runs go before the other arms.
- **O1 runs last**, after the arms (owner, 2026-11-17).
- **Learning-rate step shrunk** (owner, 2026-11-17): arm C takes O2's chosen rate (the same expert-iteration recipe
  and trainer) and a 4-phase window; D takes C's rate and window and A's rate. Step 2 only picks A's GRPO rate: one
  shared phase of 12M sampled tokens from v0, three rounds (2e-5, 5e-5, 1e-4), held-out states; about 3-4 node hours
  instead of 8-16.
- **O2 first; O1 decided after O2's result** (O1 is about 565M training tokens, about 20 h per rate at the measured
  7.8k tokens/s; if it runs, at O2's chosen rate only, after checking training throughput).
- **Search efficiency for the arms** (owner, 2026-11-17): result cache, timeout skip, warm spares and the
  degree-bounded `nlinarith` are used in the arms' training sampling (no separate search A/B for `nlinarith`). Probe
  runs and held-out evaluations keep today's settings, so they stay comparable with the anchors and the offline runs.
- **Arm B (pure proof success) dropped**: it differs from A only in reward shaping (92-94% sign agreement on the old
  trees), which one seed cannot resolve.
- **Leaning towards no reasoning** for the arms, but first the Lean overhead must come down without process kills
  (measurement of replays, restarts, duplicates and heartbeats per second of slow tactics, at step 1's HOLD).

## Decisions (owner, 2026-11-16)

- **Arms.** A, B (pure proof success), C and D all run. Dropped: an arm that learns from unsolved trees (no positive
  signal there except the value model's estimate, which is how the old reward hacking arose) and a value-only arm.
- **Defaults.** 12M generated tokens per phase, 16 phases. An arm that collapses is stopped, assessed, and reported.
- **Evaluation, breadth first.** After each arm one probe run of its final checkpoint. Only when all four arms have
  one: the second final run, phase 8, and v0's policy with the arm's final value model, arm by arm.
- **Learning rates.** Chosen on the held-out states from one training round per signal; no probe runs at that step.
- **Reasoning first.** The reasoning comparison runs before the arms; if the search without reasoning is at least as
  good at equal tokens and keeps the GPUs busy, the arms sample without reasoning.
