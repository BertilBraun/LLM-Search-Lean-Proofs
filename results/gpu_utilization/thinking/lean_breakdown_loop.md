# Lean time of `perf_thinking_loop_trees`: 76 trees, 3,991 expansions, 28.65 s/expansion

| Part | s / expansion | Share |
|---|---|---|
| automation sweep | 8.23 | 28.7% |
| policy candidates | 20.27 | 70.8% |
| root statement | 0.02 | 0.1% |
| proof verification | 0.13 | 0.4% |

## Sweep tactics

| Tactic | Attempts | s / expansion | Share | s / attempt | Children | Timeouts | Proof steps |
|---|---|---|---|---|---|---|---|
| `omega` | 3,991 | 2.33 | 8.1% | 2.33 | 3 | 0 | 1 |
| `nlinarith` | 3,889 | 1.50 | 5.2% | 1.54 | 2 | 3 | 2 |
| `simp_all` | 3,924 | 1.39 | 4.9% | 1.42 | 991 | 1 | 21 |
| `field_simp` | 3,788 | 1.02 | 3.6% | 1.07 | 587 | 4 | 17 |
| `ring_nf` | 3,932 | 0.96 | 3.4% | 0.97 | 1,919 | 1 | 15 |
| `constructor` | 3,990 | 0.52 | 1.8% | 0.52 | 441 | 0 | 5 |
| `rfl` | 3,990 | 0.50 | 1.7% | 0.50 | 4 | 0 | 2 |

## Policy candidates by outcome

| Outcome | Attempts | s / expansion | Share | s / attempt | Children | Timeouts | Proof steps |
|---|---|---|---|---|---|---|---|
| `timeout` | 1,664 | 11.05 | 38.6% | 26.50 | 0 | 1,664 | 0 |
| `error` | 8,433 | 5.39 | 18.8% | 2.55 | 0 | 0 | 0 |
| `valid` | 7,354 | 2.92 | 10.2% | 1.58 | 7,354 | 0 | 81 |
| `valid, duplicate` | 2,160 | 0.92 | 3.2% | 1.69 | 0 | 0 | 0 |
| `valid prefix, then error` | 3 | 0.00 | 0.0% | 2.98 | 3 | 0 | 1 |
| `not run` | 600 | 0.00 | 0.0% | 0.00 | 0 | 0 | 0 |

## Policy candidates by first tactic

| Tactic | Attempts | s / expansion | Share | s / attempt | Children | Timeouts | Proof steps |
|---|---|---|---|---|---|---|---|
| `nlinarith` | 3,070 | 9.46 | 33.0% | 12.30 | 7 | 1,157 | 7 |
| `have` | 10,989 | 7.27 | 25.4% | 2.64 | 5,618 | 323 | 50 |
| `rw` | 1,075 | 0.75 | 2.6% | 2.78 | 705 | 66 | 4 |
| `norm_num` | 1,166 | 0.72 | 2.5% | 2.47 | 191 | 29 | 2 |
| `constructor` | 413 | 0.53 | 1.9% | 5.12 | 4 | 47 | 0 |
| `case` | 489 | 0.30 | 1.1% | 2.49 | 5 | 6 | 2 |
| `simp_all` | 273 | 0.16 | 0.6% | 2.31 | 74 | 9 | 1 |
| `field_simp` | 435 | 0.14 | 0.5% | 1.27 | 59 | 0 | 2 |
| `linarith` | 363 | 0.13 | 0.5% | 1.43 | 0 | 0 | 0 |
| `?` | 219 | 0.13 | 0.4% | 2.32 | 3 | 2 | 2 |
| `exact` | 123 | 0.08 | 0.3% | 2.62 | 2 | 4 | 2 |
| `simp` | 255 | 0.08 | 0.3% | 1.23 | 69 | 1 | 0 |
| `all_goals` | 124 | 0.07 | 0.2% | 2.15 | 12 | 2 | 0 |
| `aesop` | 25 | 0.07 | 0.2% | 10.57 | 15 | 7 | 0 |
| `apply` | 161 | 0.06 | 0.2% | 1.46 | 111 | 0 | 1 |

Sweep ['constructor', 'field_simp', 'nlinarith', 'omega', 'rfl', 'ring_nf', 'simp_all']: saves 0.00 s/expansion (0.0%); the dropped tactics were 0 proof steps.

## Per-call limits

| Limit s | Saved s / expansion | Share | Proofs with a slower step |
|---|---|---|---|
| 1 | 20.04 | 70.0% | 21 |
| 2 | 16.16 | 56.4% | 17 |
| 5 | 11.68 | 40.8% | 8 |
