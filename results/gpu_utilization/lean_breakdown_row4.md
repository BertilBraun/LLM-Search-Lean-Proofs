# Lean time of `phase3_astar_v0_sft_v2`: 244 trees, 5,261 expansions, 5.81 s/expansion

| Part | s / expansion | Share |
|---|---|---|
| automation sweep | 1.60 | 27.5% |
| policy candidates | 4.13 | 71.1% |
| root statement | 0.00 | 0.0% |
| proof verification | 0.08 | 1.4% |

## Sweep tactics

| Tactic | Attempts | s / expansion | Share | s / attempt | Children | Timeouts | Proof steps |
|---|---|---|---|---|---|---|---|
| `aesop` | 4,935 | 0.48 | 8.2% | 0.51 | 652 | 5 | 11 |
| `simp_all` | 5,146 | 0.33 | 5.6% | 0.33 | 1,232 | 1 | 12 |
| `nlinarith` | 5,155 | 0.19 | 3.2% | 0.19 | 8 | 1 | 5 |
| `field_simp` | 5,215 | 0.11 | 2.0% | 0.11 | 499 | 0 | 2 |
| `decide` | 5,261 | 0.10 | 1.7% | 0.10 | 47 | 0 | 27 |
| `ring_nf` | 5,162 | 0.10 | 1.7% | 0.10 | 1,143 | 3 | 9 |
| `norm_num` | 5,213 | 0.09 | 1.6% | 0.09 | 211 | 1 | 5 |
| `linarith` | 5,209 | 0.08 | 1.3% | 0.08 | 30 | 0 | 28 |
| `simp` | 5,215 | 0.07 | 1.3% | 0.07 | 813 | 0 | 0 |
| `rfl` | 5,213 | 0.02 | 0.3% | 0.02 | 5 | 1 | 4 |
| `constructor` | 5,219 | 0.01 | 0.2% | 0.01 | 623 | 0 | 5 |
| `intros` | 5,219 | 0.01 | 0.2% | 0.01 | 49 | 0 | 0 |
| `omega` | 5,237 | 0.01 | 0.2% | 0.01 | 40 | 0 | 19 |

## Policy candidates by outcome

| Outcome | Attempts | s / expansion | Share | s / attempt | Children | Timeouts | Proof steps |
|---|---|---|---|---|---|---|---|
| `error` | 23,190 | 1.91 | 32.9% | 0.43 | 0 | 0 | 0 |
| `timeout` | 451 | 1.33 | 23.0% | 15.56 | 0 | 451 | 0 |
| `valid, duplicate` | 9,287 | 0.45 | 7.8% | 0.26 | 0 | 0 | 0 |
| `valid` | 14,678 | 0.43 | 7.4% | 0.15 | 14,678 | 0 | 144 |
| `repl failure` | 1 | 0.00 | 0.0% | 5.43 | 0 | 0 | 0 |
| `not run` | 6,420 | 0.00 | 0.0% | 0.00 | 0 | 0 | 0 |

## Policy candidates by first tactic

| Tactic | Attempts | s / expansion | Share | s / attempt | Children | Timeouts | Proof steps |
|---|---|---|---|---|---|---|---|
| `all_goals` | 3,311 | 0.74 | 12.7% | 1.17 | 462 | 98 | 4 |
| `have` | 15,846 | 0.64 | 11.0% | 0.21 | 7,086 | 47 | 42 |
| `nlinarith` | 2,312 | 0.63 | 10.8% | 1.43 | 19 | 79 | 18 |
| `simp_all` | 5,106 | 0.56 | 9.7% | 0.58 | 635 | 48 | 6 |
| `norm_num` | 6,027 | 0.41 | 7.1% | 0.36 | 1,028 | 42 | 5 |
| `simp` | 4,777 | 0.22 | 3.8% | 0.24 | 1,259 | 15 | 10 |
| `rcases` | 521 | 0.12 | 2.0% | 1.19 | 217 | 23 | 4 |
| `?` | 934 | 0.10 | 1.8% | 0.59 | 10 | 11 | 3 |
| `ring_nf` | 2,130 | 0.09 | 1.6% | 0.22 | 605 | 6 | 5 |
| `field_simp` | 1,373 | 0.09 | 1.5% | 0.34 | 314 | 6 | 10 |
| `rfl` | 526 | 0.07 | 1.3% | 0.74 | 0 | 24 | 0 |
| `interval_cases` | 205 | 0.07 | 1.2% | 1.75 | 7 | 20 | 2 |
| `cases` | 366 | 0.07 | 1.2% | 0.96 | 100 | 2 | 1 |
| `constructor` | 414 | 0.06 | 1.1% | 0.80 | 36 | 8 | 2 |
| `induction` | 246 | 0.05 | 0.8% | 1.01 | 11 | 2 | 5 |

Sweep ['constructor', 'field_simp', 'nlinarith', 'omega', 'rfl', 'ring_nf', 'simp_all']: saves 0.83 s/expansion (14.4%); the dropped tactics were 71 proof steps.

## Per-call limits

| Limit s | Saved s / expansion | Share | Proofs with a slower step |
|---|---|---|---|
| 1 | 2.48 | 42.8% | 25 |
| 2 | 1.87 | 32.2% | 12 |
| 5 | 1.08 | 18.5% | 6 |

Sweep calls on a (goals, tactic) pair already run in this or another tree: 0 of 67,399, 0.000 s/expansion (0.0%) a cache could save.
