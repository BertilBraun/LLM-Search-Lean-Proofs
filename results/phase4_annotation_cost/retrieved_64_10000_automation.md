# Applicability check cost (retrieved)

500 states (0 failed to start): miniF2F-valid roots and traced validation-split competition states. Candidates: 64 per state, the retriever's top candidates. Tactics `exact {name}`, `apply {name}`, `rw [{name}]` in order until one closes the goal, 10,000 heartbeats, 5 s wall-clock backstop; 8 REPL processes, 202 s wall. After a tactic that leaves goals, `<tactic> <;> (first | assumption | norm_num | linarith | positivity | simp)` runs with 20,000 heartbeats.

| Quantity | Value |
|---|---|
| Lean seconds per state, mean | 2.41 |
| p50 / p90 / max | 1.57 / 4.11 / 77.01 |
| Tactic calls per state | 195.1 |
| Candidates closing the goal, per state | 0.10 |
| Candidates closing with automation, per state | 0.19 |
| Candidates leaving goals, per state | 2.95 |
| Candidates without a match, per state | 60.76 |
| States with a closing candidate | 4.8% |
| States with a candidate closing with automation | 6.4% |
| Automation follow-up Lean seconds per state | 0.57 |
| States the automation alone closes | 47 |
| Where it does not: candidates closing with automation, per state | 0.02 |
| Where it does not: states with a candidate closing with automation | 1.3% |
| Process restarts | 15 |

## Per tactic call (milliseconds)

| Tactic | Outcome | Calls | Mean | p50 | p90 | p99 | Max |
|---|---|---|---|---|---|---|---|
| apply | applied | 697 | 18 | 16 | 33 | 76 | 200 |
| apply | error | 31,260 | 13 | 7 | 17 | 159 | 1260 |
| apply | heartbeat_timeout | 40 | 768 | 781 | 813 | 837 | 837 |
| apply+automation | applied | 648 | 202 | 169 | 418 | 909 | 1395 |
| apply+automation | error | 5 | 91 | 16 | 400 | 400 | 400 |
| apply+automation | heartbeat_timeout | 3 | 1529 | 1529 | 1537 | 1537 | 1537 |
| exact | applied | 3 | 14 | 20 | 22 | 22 | 22 |
| exact | error | 31,993 | 7 | 3 | 10 | 35 | 8409 |
| exact | heartbeat_timeout | 4 | 829 | 838 | 845 | 845 | 845 |
| rw | applied | 937 | 11 | 9 | 18 | 35 | 75 |
| rw | error | 31,019 | 7 | 5 | 10 | 24 | 711 |
| rw+automation | applied | 910 | 150 | 105 | 295 | 675 | 1356 |
| rw+automation | error | 10 | 66 | 21 | 292 | 292 | 292 |
| rw+automation | heartbeat_timeout | 6 | 1622 | 1672 | 1735 | 1735 | 1735 |
