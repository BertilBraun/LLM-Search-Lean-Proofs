# Review AF: follow-up WP2, WP3, WP4a (block log-probability, proof-success credit, expert-iteration window), code

Branch `followup-signals` (master..7e57041, 6 commits) against DESIGN.md "Follow-up study: controlled arms". Touched
suites (`tests/rl`, `tests/graph`, `tests/policy`, `tests/search/test_priority.py` files of the diff): 442 passed in WSL.
All numbers come from the branch's production functions (`label_phase_data`, `group_advantages`, `tree_policy_data`,
`block_log_probability`, `file_completions`, `CompletionSelector`, `phase_window`) on the old run's recorded trees
(`node_backup/2026-11-01/hf_dataset`) with the Qwen3.5-2B tokenizer (1 of 36,404 samples unaligned, 0 token
mismatches). Scripts: `C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_af\`.
Not run: anything on a GPU.

## Measurements

**Credit modes: 400 solved trees (100 random per phase 1-4), 2,370 groups, 18,960 policy samples.**

| | A per-tactic | B1 sequence | B2 proof success |
|---|---|---|---|
| groups kept; sequences (= steps × 64) | 2,240; 17,920 | 2,212; 17,696 | 2,060; 16,480 (A's extra 180: 158 all r = 1) |
| trained tokens; non-inserted untrained | 2.65M; 250k (8.6%) | 2.88M; 180 | 2.73M; 180 |
| mean \|A\| per trained token; policy-term scale Σ\|A\|/256 per sequence | 0.380; 0.220 | 0.465; 0.295 (1.34×) | 0.352; 0.227 (1.03×) |
| sample advantage p5 / p50 / p95; max \|A\| | −0.81 / −0.11 / 0.99; 5.67 | −0.81 / −0.12 / 1.00 | −0.63 / −0.13 / 0.75; < 0.88 |
| tokens trained by both, same sign / opposite (A vs B2; A vs B1; B1 vs B2) | 86.4 / 7.4% | 90.5 / 3.4% | 92.9 / 7.0% |

A's explanation tokens (71% of its trained tokens) get exactly B1's sample advantage: **83% of A's \|A\| mass is B1's**.
A vs B2 per sample: sign agreement 93.6%, within-group Spearman median 0.76 (2,047 groups); per-tree token correlation
0.83. B2's r (r = 1: 9,077): with a later failing tactic 1,727 (19%); last state not closer than the node 963 (679 equal,
284 farther); ending in a no-op or redundant tactic 63. r = 0 with a proof-graph tactic 998 (10% of r = 0); r = 0 into a
proof-graph child 43 (a lone redundant `have`); unverified-proof edges 4. So r = 1 is, to 60 of 18,960 exceptions, "the
child is on the proof graph". Sign disagreements (6.4%): on the graph, then a last tactic into an unknown, off-graph or
claim state 535; r = 1 detour or sideways 251; r = 1 with failing or wasted tactics 188; progress below A's baseline 71.

| Block (abridged) | Labels (remaining steps) | Node | A (token mean) | B2 |
|---|---|---|---|---|
| `constructor; intro a b c ha hb hc h` | PG14 PG21 | 15 | −1.17 | +0.38 |
| `constructor; exact h₃; intro y hy; have h₄ := h₃ 1; …` | PG5 PG4 PG17 … PG13 | 6 | −0.79 | +0.38 |
| `intro S; intro a b; constructor; simp [S]; ring_nf` | PG7 FAIL masked×3 | 8 | −0.41 | +0.50 |
| `constructor; intro …; field_simp …; rw […]; nlinarith […]` | PG14 PG21 unk unk PG10 PG9 unk | 15 | +0.99 | −0.62 |
| `intro h; have h₄ : m^4 = 2; nlinarith […]; have h₅ : m^2 = √2` | PG9 PG8 PG1 claim | 10 | +1.30 | −0.12 |
| `intro t; constructor; …; linarith; intro h; cases' h with h h` | PG7 … PG1 unk unk | 8 | +0.47 | −0.75 |
| `use 1, 1, 1; constructor; norm_num; …` (unverified proof) | PG9 … PG1 FAIL | 10 | +0.76 | −0.38 |

**Block log-probabilities (36,404 recorded samples with a block).**

| Tactics | n | block tokens | block log-p | per token | whole sample | forward edge |
|---|---|---|---|---|---|---|
| 1 | 14,743 | 7 | −0.84 | −0.078 | −42.6 | 49% |
| 2 | 6,106 | 22 | −4.36 | −0.163 | −48.3 | 63% |
| 3 | 4,146 | 38 | −6.91 | −0.161 | −51.4 | 77% |
| 6+ | 6,530 | 121 | −16.69 | −0.136 | −65.3 | 84% |

Spearman(block log-p, block tokens) −0.82. Partial blocks: 32% of usable samples, whole block −10.7 against the kept
prefix −2.9. Row 2's automation rule (median step of samples that made progress): −5.65 for block sums (whole −48.9; the
old −2.8 does not transfer). At 2,061 expansions with a proof-graph child and another candidate, the top candidate is
on the proof graph: block sum 39.4%, per-token mean 42.0%, whole sample 41.8%, chance 39.9% (pairwise AUC 0.516 / 0.546
/ 0.521). Block sum and per-token mean pick the same top candidate in 70% of expansions.

**Expert-iteration window on the old run (all 1,391 solved trees of phases 1-4, probe and gate held out).**

| | W = 1 (phase 4) | W = 4 (phases 1-4) |
|---|---|---|
| minimum version; samples it excluded | v3; 408 (3.2%: the 6 trees v2 left in flight) | v0; 0 |
| examples (train); completion tokens; by phase | 1,117 (1,044); 175k; 4: 1,117 | 5,163 (4,923); 762k; 1,081 / 1,389 / 1,535 / 1,158 |
| statements; examples per statement; states | 387; 2.9; 827 | 1,328; 3.9; 3,658 |
| easy examples (20% cap never binds); one-tactic blocks | 13.8%; 50% | 18.7%; 65% |

## Must fix before merge

1. **WP4a cannot serve step 2.** `loop_inputs` (`experiments/grpo_expert_iteration.py:185`) selects by
   `TreeEntry.phase`; the shared sampling never ends a phase, so W = 1 and W = 4 both select all four slices (and
   `last_phase = 0` resolves to phase 0 and raises). Smallest correct change: an optional `[data] tree_index = ""` (a
   file in the loop's trees directory, default `index.jsonl`) read by `index_entries` (`:162`); WP6's slicer writes
   `slices.jsonl`, the index lines with `phase` set to the slice number, and the configs set `last_phase = 4`,
   `window_phases = 1 | 4`. `phase_window` then gives `minimum_version = 0` (no "phase k" trigger in the run's
   `versions.jsonl`), right for one-version trees. Test: a slice index with phases 1-4 selects slice 4 alone at W = 1.
   The same slicer writes the slice directories `grpo_phase.py --trees` reads, so GRPO and C see the same slices.
2. **Before run 6 (the switch is off by default, so not a merge blocker): the value-free score is mostly block length
   and no better than chance at ordering siblings.** `block_log_probability` (`policy/prompts.py:413`) sums and
   `CumulativeLogProbability` averages per block, so a 6+-tactic block costs 20× a one-tactic one while per token they
   are alike; at proof-graph nodes the sum picks a proof-graph child at chance (39.4% vs 39.9%), the per-token mean a
   little better (42.0%). Partial children (32%) pay their failed tail: `Search` gives the child `candidate.log_probability`
   whatever prefix it kept (`search/search.py:727`). As implemented, Q4's "none" is one weak ordering, so "none < v0"
   may partly measure the rule: biased against the value-free side by an amount nothing here bounds. Fix: (a) a
   per-token option (the block's token count on `TacticCandidate`, step value = sum / tokens); (b) pilot sum and
   per-token on the 200 calibration statements and run Q4 with the better (the arms' "fair best effort" rule); (c) the
   automation constant per variant by the row-2 rule (here −5.65 for sums, about −0.12 per token) in a shipped run-6
   config, tested not to be `visible_student_v2.toml`'s −1.0; (d) prefix-only values for partial children, or report
   their share.

## Should

3. **A is mostly B1.** `token_credits` (`rl/token_credit.py:43`) gives A's explanation tokens `advantages.sequence`:
   A–B1 differ only on block tokens (17% of A's \|A\| mass), and A–B2 on the explanation only as score − b against
   r − b̄. Put this in DESIGN's outcome table before step 2 reads "A ≈ B1" as "placement does not matter".
4. **Equal treatment in the trainer.** Clip, normalizer (`policy_trainer.py:635`), KL coefficient and replay weight are
   the same, but (a) the policy term's scale differs (B1 1.34× A, B2 1.03×): AdamW plus a rate absorbs the overall
   scale, not the mix, so B1's KL (`:662`) and replay (`:815`) weigh 25% less against its policy term than A's;
   (b) B2 has 8% fewer sequences, steps and replay draws (a rate absorbs the steps, not the warmup's share or the
   replay count); (c) A keeps 8.6% of tokens (masked tactics, the closing after a failure) out of loss and KL, B1 and B2
   train them, the never-executed masked tail included; (d) a higher rate binds the fixed clip more. Only (a) and (c)
   are beyond a rate. Log per arm and phase the KL and replay share of the loss, or divide each phase's advantages by
   their mean \|A\| per trained token so the KL and replay weights mean the same in every arm.
5. **B2 is a clean outcome signal; "advances along the found proof" overstates it.** It is "the child is on the proof
   graph": 10.6% of r = 1 end no closer than the node (284 farther), 19% carry a failing tactic whose tokens and masked
   tail B2 pushes up where A charges −c, and 10% of r = 0 were on the graph for most tactics and lost it to one tactic
   into a never-expanded state. No wrong labels found (60 exceptions, all documented rules). Say so in the README and
   design; watch B2's cut-off, block-length and claim alerts first.
6. **A and B2 can separate**: token sign agreement 86.4%, below the design's ~95% gate. Record it in
   `results/followup_step0/` as the offline baseline; step 2's v0 trees may differ.
7. **W = 1 vs W = 4 is not only the amount**: W = 4 has 4.6× the examples but also more one-tactic blocks (65% vs 50%),
   more easy examples (18.7% vs 13.8%) and 3.9 examples per statement vs 2.9. On step 2's slices the version mix goes,
   the band's rise stays: report W = 4's tactic, easy and band shares beside W = 1's.

## Minor

8. An unaligned sample keeps its whole-completion log-probability (`prompts.py:490`), ~9× a block's, so it sorts last
   (1 in 36,404 here).
9. `phase_window` (`rl/expert_iteration_data.py:131`) ignores `reward_fix.json` when `window_phases > 0`, so on the old
   run a window can reach into the reward-hacking phases (rejected versions stay out). Say it in the docstring.
10. Unverified-proof edges: B2 0, A up to +0.95 (4 samples); in the README, not in the design's B2 row.
11. Until WP1, `phase_due` counts B2's trainable groups (8% fewer), so B2's timed phases would run longer.

No regressions found: A's and B1's token credits are unchanged (pinned example, same code path), `parse_samples` without
a decoder orders as before, the round-1 configs keep `window_phases = 0` and the reward-fix path still gives v16. Step
2's GRPO trees are v0's only, so the trainer's start policy is the sampler for the importance ratio.

## Re-review (fixes up to f14b28d)

604 tests on the fix commits' suites pass in WSL; reran on the same 400 trees through the production code (`rerun.py`).
1. **Resolved.** Slice directories (`expert_iteration_trees.round_trees`) read every `*.json.gz` as `grpo_phase.py
   --trees` does, so slice 4 against slices 1-4 builds what step 2 needs. Version rule (from 0, rejected aside, a mix
   refused) is right for a v0-only run. Minor: `below_band` is always False there, so the summary's share reads 0.
2. **Resolved; a new must-fix sits next to it.** All three settings match their definitions: max over each
   candidate's samples recomputed, 0 mismatches (1,799 merged `block_mean` candidates; 1 unaligned sample). Proof-graph
   top candidate at 2,060 expansions: completion 42.6%, block_sum 39.4%, block_mean 42.2%, chance 39.9%. Minor: an
   unaligned sample falls back to its completion sum (about −49), 400× off `block_mean`'s scale; use the completion's
   per-token mean. **Must fix before run 6:** `probe_evaluation.probe_run_config`'s value-free branch sets the kind and
   `automation_log_probability = −2.8` but leaves `policy.step_log_probability` at the template's `completion`. Run 6
   would order whole completions (about −49 a step) against automation at −2.8, so sweep children always go first. Put
   the setting in `ValueFreePriority` with a constant calibrated for it, and test it.
3. **Groups kept:** A 2,240, B1 2,212, B2 1,973 (−12%). r = 1 for 10,069: 23.5% with a failing tactic, 9.9% ending off
   graph, unknown or in a claim (303 claims), 10.5% no closer; only 6 r = 0 samples touch the graph. Sample sign
   agreement 97.3% (B1 97.5%); token sign agreement 89.0% (5.1% opposite; was 86.4 / 7.4%); within-group rank 0.76.
   For a 0/1 reward, sample sign agreement is the wrong yardstick: A and B2 now differ in magnitude (δ, local term,
   \|A\| up to 5.7) and in where credit lands, not sign. Not pointless: the tokens are below the ~95% gate and a step-2
   round is cheap; a closed-loop pair only if step 2 separates them. Still outcome-only. **Should:** the README's "neither
   charged nor credited, as in per-tactic credit's global part" is wrong at token level: B2 pushes tail tokens
   (failing tactics, trailing bare claims) up by r − b̄ > 0 where A charges −c or −2c. Correct it, and alert on claims
   and failing tails after the graph in B2 (only bare-`have` openings alert today).
4. **Not removed, partly documented:** A still keeps 8.6% of tokens (masked tactics, the closing after a failure) out
   of loss and KL; B1 and B2 train them. The README table lacks a proof_success column and the KL consequence.
5. Nothing else new. Verdict: **merge**; the run-6 config before run 6, the README sentence before step 2.
