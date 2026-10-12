# Applicability check cost (frequent)

500 states (0 failed to start): miniF2F-valid roots and traced validation-split competition states. Candidates: 32 per state, the premises most often named in traced competition steps (the same list for every state, a stand-in until the premise embeddings exist). Tactics `exact {name}`, `apply {name}`, `rw [{name}]` in order until one closes the goal, 10,000 heartbeats, 5 s wall-clock backstop; 8 REPL processes, 182 s wall.

| Quantity | Value |
|---|---|
| Lean seconds per state, mean | 1.59 |
| p50 / p90 / max | 1.02 / 1.90 / 67.47 |
| Tactic calls per state | 95.8 |
| Candidates closing the goal, per state | 0.10 |
| Candidates leaving goals, per state | 2.38 |
| Candidates without a match, per state | 29.52 |
| States with a closing candidate | 6.2% |
| Process restarts | 15 |

## Per tactic call (milliseconds)

| Tactic | Outcome | Calls | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|
| apply | applied | 19 | 77 | 32 | 380 | 386 | 386 |
| apply | error | 15,950 | 21 | 8 | 52 | 168 | 1314 |
| exact | applied | 31 | 24 | 2 | 46 | 380 | 380 |
| exact | error | 15,969 | 14 | 3 | 12 | 52 | 17966 |
| rw | applied | 1,188 | 27 | 15 | 60 | 87 | 260 |
| rw | error | 14,768 | 13 | 5 | 44 | 64 | 1299 |
