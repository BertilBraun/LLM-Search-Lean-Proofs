# Applicability check cost (retrieved)

500 states (0 failed to start): miniF2F-valid roots and traced validation-split competition states. Candidates: 32 per state, the retriever's top candidates. Tactics `exact {name}`, `apply {name}`, `rw [{name}]` in order until one closes the goal, 10,000 heartbeats, 5 s wall-clock backstop; 8 REPL processes, 107 s wall.

| Quantity | Value |
|---|---|
| Lean seconds per state, mean | 0.98 |
| p50 / p90 / max | 0.60 / 1.29 / 37.97 |
| Tactic calls per state | 95.9 |
| Candidates closing the goal, per state | 0.07 |
| Candidates leaving goals, per state | 1.80 |
| Candidates without a match, per state | 30.13 |
| States with a closing candidate | 3.6% |
| Process restarts | 15 |

## Per tactic call (milliseconds)

| Tactic | Outcome | Calls | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|
| apply | applied | 339 | 16 | 11 | 33 | 54 | 100 |
| apply | error | 15,634 | 13 | 7 | 17 | 160 | 1239 |
| apply | heartbeat_timeout | 24 | 775 | 779 | 805 | 827 | 827 |
| exact | applied | 3 | 13 | 19 | 20 | 20 | 20 |
| exact | error | 15,995 | 9 | 3 | 10 | 37 | 7897 |
| exact | heartbeat_timeout | 2 | 832 | 833 | 833 | 833 | 833 |
| rw | applied | 604 | 10 | 9 | 18 | 31 | 79 |
| rw | error | 15,364 | 7 | 5 | 10 | 24 | 1084 |
