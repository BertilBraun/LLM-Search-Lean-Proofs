# Training signal of four schemes on the recorded trees of grpo_loop_v1

Script: `experiments/analysis/training_signal.py` (production labels, rewards, groups, token credit; today's `[reward]`
of `experiments/configs/grpo/phase.toml`, μ = 0 as in the whole run). Seeded samples: 160 trees per phase of 1-4 (640 of
2,252), 100 per phase of 16-26 (1,100 of 4,916), scaled to whole phases (noise roughly ±10%). Check: (a)'s groups per
phase in 16-26 (942) match the logged `groups_trained` (954); recorded token ids decoded to the texts in every tree.

## The disputed fact: unsolved trees never trained the policy

- Path: `loop.py` -> `training_phase.label_phase_data` -> `grpo_groups.policy_groups` -> `policy_data.build_policy_data`
  -> `policy_trainer.train_grpo`. `policy_groups` forms groups only at expanded nodes of class `NodeClass.PROOF_GRAPH`
  (`graph_labels.label_graph`); an unsolved tree has none, so it gives zero groups before any reward is computed. Not a
  side effect of dropping all-zero-advantage groups (`GroupAdvantages.has_signal`) or of the global reward.
- Deliberate: DESIGN.md "Policy update: GRPO over sibling groups" (2026-10-28) and rl/README.md say unsolved trees and
  off-graph nodes give no policy groups, only value targets. On the data: `summary.trainable_groups` is 0 for all 6,550
  unsolved trees of phases 1-31 (41%), and this replay finds 0 contributing unsolved trees.
- So the write-up's "an unsolved statement still teaches which steps were valid and which failed" holds for the value
  model only. Graph credit differed from outcome only inside proof-graph-node groups of solved trees, in the size of the
  advantages (progress δ, label values, per-tactic splits), not in the data. 82-85% of all policy expansions never
  trained (11-16% off the proof graph in solved trees, 65-74% in unsolved ones), though 59-85% of them mix valid and
  failing first tactics.

## Accounting per phase (whole-phase estimates)

(a) loop credit "per_tactic"; (b) loop credit "sequence" (`CreditMode.SEQUENCE`, still in the code); (c) loop credit
"proof_success" (`CreditMode.PROOF_SUCCESS`, WP3): in the same expansion groups a sample scores r = 1 if its edge is a
forward one and a tactic of its kept prefix reaches the proof graph (`GroupSample.reaches_proof_graph`), else 0, minus
the group's mean r, on every sampled token (no division by a standard deviation, as in the loop). Since 2026-11-14 the
script scores (c) with that production mode, so (c) is the B2 arm's definition; the rerun on the same samples moved only
(c), by under 0.2% (the forward-edge condition: unverified proofs and blocks ending at their node or an ancestor now 0). Samples are recorded
completions; "+ / -": samples with any positive / negative token. Shares are of the summed |advantage| over tokens.

| scheme, phases | trees (solved / unsolved) | groups | samples (+ / -) | tokens + / - | from unsolved / off-graph / on-graph | on explanation | same sign as (c) / opposite / (c) zero | mean abs adv per token | sum abs adv |
|---|---|---|---|---|---|---|---|---|---|
| (a) per-tactic, 1-4 | 335 / 0 | 1,438 | 11,508 (5,272 / 8,618) | 644k / 985k | 0 / 46% / 54% | 83% | 94% / 2% / 4% | 0.40 | 0.65M |
| (a) per-tactic, 16-26 | 278 / 0 | 942 | 7,538 (3,219 / 6,173) | 413k / 712k | 0 / 44% / 56% | 79% | 92% / 2% / 6% | 0.41 | 0.46M |
| (b) sequence, 1-4 | 335 / 0 | 1,425 | 11,384 (4,743 / 6,641) | 743k / 1,163k | 0 / 46% / 54% | - | 95% / 1% / 4% | 0.46 | 0.88M |
| (b) sequence, 16-26 | 278 / 0 | 922 | 7,370 (2,671 / 4,700) | 530k / 1,069k | 0 / 44% / 56% | - | 94% / 1% / 5% | 0.60 | 0.95M |
| (c) outcome, 1-4 | 308 / 0 | 1,233 | 9,864 (4,043 / 5,821) | 660k / 1,028k | 0 / 49% / 51% | - | 100% | 0.35 | 0.58M |
| (c) outcome, 16-26 | 258 / 0 | 781 | 6,249 (2,235 / 4,014) | 474k / 938k | 0 / 49% / 51% | - | 100% | 0.32 | 0.45M |

A phase has 2,252/4 = 563 trees (1-4) and ~447 (16-26) of 12-20M sampled tokens; all three schemes touch the same
~60% solved trees and put a non-zero advantage on 9-12% of the sampled tokens. (c) loses the 14-17% of groups in which
every sample reaches the proof graph; there (a) still ranks by progress and label. 92-94% of (a)'s summed |advantage|
has the sign outcome gives the same sample, and ~80% of it sits on explanation tokens, which (a) credits like (b).
Advantages are negative on 60-67% of trained tokens in all three schemes.

## Expert iteration (d): examples per phase under the round's selection rules

| phase | 1 | 2 | 3 | 4 | 16 | 17 | 18 | 19 | 20 | 21 | 22 | 23 | 24 | 25 | 26 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| trees with an example | 166 | 217 | 480 | 414 | 183 | 223 | 273 | 232 | 285 | 258 | 305 | 231 | 303 | 273 | 357 |
| kept blocks before caps | 2,627 | 4,940 | 2,929 | 1,866 | 1,604 | 781 | 1,126 | 1,922 | 2,116 | 894 | 990 | 1,321 | 1,459 | 1,368 | 2,067 |
| selected examples | 918 | 1,283 | 1,423 | 1,096 | 562 | 537 | 749 | 764 | 805 | 619 | 695 | 679 | 722 | 770 | 943 |
| completion tokens | 0.12M | 0.19M | 0.20M | 0.17M | 0.09M | 0.10M | 0.13M | 0.14M | 0.13M | 0.11M | 0.12M | 0.12M | 0.16M | 0.14M | 0.17M |

`proof_graph_completions` + `CompletionSelector` with `expert_iteration_1_b.toml` [data], per phase, all versions but
rejected ones. Phases 16-25 sum to ~6,900, close to the published round's 7,118 (15-25 pooled). No statement was solved
twice within 1-4 or 16-26, so the caps do not bind across phases: a 4-phase window is ~4x one phase (2,600-3,100
examples, ~0.5M tokens in 16-26). (d) uses the same ~270 solved trees as (a) with ~1/10 of its sequences and tokens.

## What the old run logged per update (grpo.jsonl; KL to v0 from health.jsonl)

| phase | from v | lr, passes | groups | trained tokens | local share | clip | KL to data policy | KL to v0 | ratio + (clip +) | ratio - |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 0 | 3e-5, 2 | 1,368 | 2.49M | 0.18 | 0.076 | 0.032 | (1.06e3) | 1.043 (0.060) | 0.975 |
| 3 | 2 | 3e-5, 1 | 1,825 | 1.60M | 0.22 | 0.046 | 0.022 | - | 1.000 (0.030) | 0.999 |
| 4 | 3 | 3e-5, 1 | 1,376 | 1.21M | 0.22 | 0.044 | 0.313 | - | 1.000 (0.028) | 1.63 |
| 9 | 8 | 3e-5, 1 | 865 | 0.65M | 0.22 | 0.041 | 2.2e5 | 0.046 | 1.020 (0.026) | 5.0e5 |
| 11 | 11 | 2e-5, 1 | 1,215 | 0.96M | 0.21 | 0.031 | 0.013 | 0.076 | 1.001 (0.023) | 1.000 |
| 16 | 16 | 2e-5, 1 | 888 | 1.26M | 0.21 | 0.022 | 0.006 | 0.055 | 1.001 (0.019) | 1.000 |
| 26 | 26 | 2e-5, 1 | 1,231 | 1.96M | 0.20 | 0.018 | 0.006 | 0.060 | 1.001 (0.015) | 1.002 |

Last-pass means; KL to v0 (k1) is unreliable before phase 8 (not scored, or 1.06e3). Phases 1-10 had no KL penalty:
the positive tokens' ratio stayed at 1.00-1.04 while the negative ones' ran away (1.6 to 5e5), the drift that was rolled
back. From phase 11 (lr 2e-5, k3 KL 0.01 to v0) the positive ratio moved 0.0004-0.0015 per phase (0.010 once), clip
1.5-2.5%, KL to v0 flat near 0.055: tiny steps. Trained tokens doubled at the reward fix (phase 15), largely because
unknown tactics became trained. All phases: `training_signal.py --logged`.

## What this predicts for the arms

- (a) and (c) train on nearly the same data: the same solved trees, ~85% of the groups, a similar token count (c even
  ~25% more non-zero tokens in 16-26: tokens (a) leaves at 0, unknown tactics and closing), and the same sign on 92-94% of
  (a)'s advantage mass. An (a)-vs-(c) arm measures reward shaping (progress, label values, tactic-level splits), not
  "graph data vs outcome data"; expect a small difference, likely below what one seed per arm resolves.
- (b) is (a) with the ~20% of the mass on tactic tokens replaced by the sample's score: same groups and signs, but
  ~1.4-2x the summed |advantage| per phase. At one learning rate (b) takes about twice (a)'s step and (c) about (a)'s.
- (d) sees the same solved trees but ~10x fewer tokens, all positive; a 1-phase window is ~550-950 examples
  (0.1-0.17M tokens), a 4-phase window 2,600-3,100. At the round's lr of 1e-4 (5x GRPO's) its steps are far larger
  than the old GRPO's; the arms then differ more in step size than in data.
- None of the four learns from unsolved statements; the signal per phase scales with the solve rate. Match step size,
  not lr: e.g. the same KL to v0 or positive-token ratio per phase (old run: +0.001 per phase at 2e-5 with KL 0.01).

## Code that would make an arm unfair or broken

- (c) is in the code since WP3 (`phase_proof_success.toml`, the definition above); (b) works via
  `phase_sequence_credit.toml`.
- No advantage normalization in any scheme: the summed |advantage| per phase differs ~2x between (b) and (a)/(c).
- (d) is a one-off script, not a loop stage, and `train` refuses unless the loop is stopped in sampling. Since WP4a
  it takes a sliding phase window (`[data] window_phases`, no `reward_fix.json` needed) or explicit tree directories
  (`[data] tree_directories`, step 2's slices); inside the loop it is WP4b.
- Not determined: whether the shaping in (a) helps (offline counts cannot say); the evaluations' held-out goal keys
  were not applied to (d) (file not local; few states); counts are sample estimates, and phases 16-26 trees are
  off-policy for v0 (KL ~0.055 per token), phases 1-4 nearly on-policy.
