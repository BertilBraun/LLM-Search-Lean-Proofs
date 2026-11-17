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
