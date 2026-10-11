# Phase 0: Lean environment

`leanprover/lean4:v4.9.0-rc1`, Mathlib `d1d1e4b72c6e009edd97cabe1d661b021fe8eeae`, REPL `7df77c0a1c9188ab58c76d4138a06ae5e0c32282`. Other workloads shared the node; its state when each set of parts started:

- concurrency,memory_growth,process_costs,statements,sweep: load average 23.0, cgroup memory 66.9 GiB (19.7 GiB anonymous)
- concurrency,sweep: load average 40.0, cgroup memory 107.2 GiB (63.8 GiB anonymous)
- sweep: load average 8.5, cgroup memory 67.6 GiB (32.9 GiB anonymous)

## Statements

488/488 statements yield a proof state ({'valid': 244, 'test': 244}). Initial goal equal to DeepSeek's `goal` field (normalized): 488/488. Statements that only elaborate with `autoImplicit` (the REPL default): 5 (induction_pord1p1on2powklt5on2, induction_prod1p1onk3le3m1onn, amc12a_2021_p9, mathd_algebra_342, mathd_algebra_158). Median start time 0.025 s.


## Process costs

REPL start plus header import (`import Mathlib`), sequential runs:

| start_and_import_seconds | resident_gibibytes | anonymous_gibibytes |
|---|---|---|
| 3.68 | 3.5 | 0.24 |
| 3.55 | 3.5 | 0.24 |
| 3.77 | 3.5 | 0.24 |

## Memory growth

One process, 2000 applications of intros, norm_num, simp, ring_nf, omega, linarith (50k heartbeats) to initial states of miniF2F-valid, 1447 proof states created: anonymous RSS 246 → 603 MiB, **17.8 MiB per 100 tactic applications** (0.25 MiB per proof state).

## Concurrency

Each process repeatedly starts a miniF2F-valid problem and applies norm_num, simp, linarith, nlinarith, omega, aesop (default limits) for 60 s, sampled every 0.25 s. Pool anonymous = sum of the REPL processes' private memory; the Mathlib .olean files are shared file mappings (about 3.3 GiB once per node). Cgroup figures include other workloads on the node (baseline before the pool starts), limit 120.8 GiB.

| processes | load_average_before | ready_seconds | applications_per_second | median_latency_seconds | p90_latency_seconds | wall_clock_timeouts | peak_pool_anonymous_gibibytes | max_process_anonymous_gibibytes | baseline_cgroup_anonymous_gibibytes | peak_cgroup_anonymous_gibibytes | peak_cgroup_gibibytes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 8 | 40 | 4.81 | 81.7 | 0.036 | 0.182 | 0 | 2.08 | 0.362 | 63.8 | 69.2 | 113 |
| 16 | 22.5 | 6.04 | 154 | 0.0374 | 0.187 | 0 | 4.02 | 0.36 | 70.8 | 75 | 116 |
| 32 | 29.4 | 7.7 | 291 | 0.0412 | 0.198 | 0 | 7.86 | 0.365 | 71.7 | 79.8 | 121 |
| 48 | 38.8 | 10.1 | 384 | 0.0468 | 0.235 | 0 | 12.2 | 0.354 | 70.3 | 83.2 | 121 |

## Automation sweep

Initial states of 244 miniF2F-valid problems, 200000 heartbeats per tactic, 60 s wall-clock backstop, pool of 32 processes. Progress = valid and goals changed (closing included). Sorted by median latency. Closed by at least one tactic: 59/244; every closing tactic re-verified as a full proof: 259/259 pass.

| tactic | closing_rate | progress_rate | median_seconds | p90_seconds | max_seconds | errors | heartbeat_timeouts | wall_clock_timeouts |
|---|---|---|---|---|---|---|---|---|
| decide | 0.0984 | 0.0984 | 0.00166 | 0.00635 | 0.66 | 220 | 0 | 0 |
| omega | 0.0943 | 0.0943 | 0.00212 | 0.00781 | 0.145 | 221 | 0 | 0 |
| positivity | 0 | 0 | 0.00238 | 0.00328 | 0.0133 | 244 | 0 | 0 |
| intros | 0 | 0.0164 | 0.00322 | 0.00564 | 0.0219 | 0 | 0 | 0 |
| constructor | 0.0984 | 0.258 | 0.00368 | 0.0076 | 0.648 | 181 | 0 | 0 |
| rfl | 0.107 | 0.107 | 0.00497 | 0.0109 | 63.8 | 217 | 0 | 1 |
| tauto | 0.107 | 0.107 | 0.0176 | 0.0456 | 63.7 | 217 | 0 | 1 |
| simp | 0.0574 | 0.189 | 0.0184 | 0.0819 | 0.641 | 198 | 0 | 0 |
| field_simp | 0.0246 | 0.225 | 0.0217 | 0.142 | 1.04 | 189 | 0 | 0 |
| norm_num | 0.082 | 0.221 | 0.0287 | 0.117 | 0.672 | 0 | 0 | 0 |
| linarith | 0.0492 | 0.0492 | 0.0505 | 0.114 | 0.29 | 232 | 0 | 0 |
| ring_nf | 0.102 | 0.43 | 0.0517 | 0.137 | 0.366 | 0 | 0 | 0 |
| simp_all | 0.0656 | 0.504 | 0.0897 | 0.436 | 3.96 | 121 | 0 | 0 |
| nlinarith | 0.0615 | 0.0615 | 0.094 | 0.283 | 2.04 | 229 | 0 | 0 |
| aesop | 0.115 | 0.615 | 0.132 | 0.643 | 3.97 | 94 | 0 | 0 |
