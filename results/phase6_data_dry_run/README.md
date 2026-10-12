# Expert-iteration round 0: training data

Built 2026-10-12T04:38:01+00:00 (git 2013af3182, 124 s; statistics only, no data written). Statements held out by hash (2%, seed `expert-iteration-round-0`) feed only validation sets.

| Run | Trees | Solved | Held-out trees | Held-out solved |
|---|---|---|---|---|
| phase3_astar_v0 | 244 | 155 | 4 | 3 |
| phase2_sft_v1_search | 244 | 148 | 4 | 2 |

| Source | Trees | Solved |
|---|---|---|
| other | 488 | 303 |

## Policy SFT

298 found proofs, one shortest per statement: 157 statements (3 more held out). 0 proofs have a shorter path through duplicate edges (not used: only the verified path's steps are certain to compose). 315 proof steps, 143 by automation (left out: the sweep tries them anyway); 172 examples, 0 duplicates, 0 over the length caps: **172 new examples, 31,800 tokens**. Replay of traced human steps: 50% of the mixture, 31,800 tokens budgeted, **166 examples, 32,681 tokens**. Validation: 2,000 traced validation steps; 3 held-out proof steps in `validation_expert_iteration.jsonl`.

| Proof steps | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8+ |
|---|---|---|---|---|---|---|---|---|
| proofs | 87 | 36 | 20 | 5 | 3 | 2 | 0 | 4 |

| New examples | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|
| prompt tokens | 146 | 131 | 208 | 355 | 405 |
| completion tokens | 39 | 25 | 77 | 223 | 235 |

| Replay source | Examples | Tokens | Over length |
|---|---|---|---|
| goedel_lean_workbook_proofs | 25 | 4,622 | 0 |
| stp_lean_workbook | 17 | 4,627 | 0 |
| deepseek_prover_v1 | 25 | 4,630 | 0 |
| lean_workbook | 29 | 4,610 | 0 |
| goedel_sft_v2 | 18 | 4,721 | 4 |
| numinamath_lean_kimina | 22 | 4,770 | 1 |
| leanabell_sft | 30 | 4,701 | 1 |

## DPO pairs

At each policy step of a found proof (chosen = the executed on-path step), rejected = sibling policy candidates that failed in Lean (error or timeout, never an infrastructure failure) or led into a dead subtree, the policy's most likely first, at most 4 per node. 357 nodes, 229 with pairs; 1,079 rejectable siblings before the cap; 662 pairs, 0 over the length caps: **658 training pairs**, 8 held-out validation pairs. In 285 kept pairs the policy gave the rejected step the higher log-probability.

| Rejection | Pairs |
|---|---|
| error | 635 |
| timeout | 19 |
| dead | 4 |

| Pairs per node | 0 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|---|
| nodes | 128 | 54 | 36 | 20 | 119 |

Completion tokens: chosen mean 38 (p90 77), rejected mean 42 (p90 90).

## Value v1

Tree labels (`value.labels`): exact remaining steps for states that reach the proof, at least 1 + the distance to the frontier for censored states, dead for fully expanded states without either. 27,394 open-frontier labels (at least 1) carry no loss and are dropped. Pre-filter proofs: 193 exact labels from 152 automation-only trees, 193 sampled. Replay of `v0`: 10,351 of 134,652 states.

| Labels | Examples | Exact | At least | Dead |
|---|---|---|---|---|
| all tree labels | 38,345 | 697 | 37,110 | 538 |
| kept tree labels | 10,951 | 697 | 9,716 | 538 |
| train (merged with replay) | 20,702 | 11,077 | 9,124 | 501 |
| validation | 2,858 | 2,633 | 170 | 55 |

| Kept tree labels | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8+ |
|---|---|---|---|---|---|---|---|---|
| exact | 298 | 137 | 83 | 66 | 30 | 20 | 11 | 52 |
| at least | 0 | 8,066 | 1,390 | 188 | 48 | 15 | 5 | 4 |

| Depth | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 | 16+ |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| exact | 298 | 155 | 93 | 46 | 27 | 16 | 12 | 12 | 8 | 8 | 5 | 5 | 5 | 3 | 3 | 1 | 0 |
| at least | 178 | 639 | 1,615 | 2,199 | 1,038 | 477 | 325 | 238 | 247 | 248 | 267 | 312 | 333 | 382 | 502 | 716 | 0 |
| dead | 4 | 28 | 63 | 83 | 82 | 60 | 54 | 44 | 24 | 20 | 20 | 16 | 13 | 9 | 13 | 5 | 0 |

Validation: 242 held-out tree states and 2,616 replay validation states, none also in train.
