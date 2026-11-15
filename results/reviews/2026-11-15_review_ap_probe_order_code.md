# Review AP: probe submission order, GPU power records, reserve refusal, thread affinity (by experiment)

Branch `worktree-agent-ab19668c33deedbef` (5 commits on master). WSL: the branch's order, GPU, CPU-layout, pinning,
probe-runs, loop, handoff, tolerated-search and probe tests 360 passed. Own runs (scripts in
`C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_ap\`):
a list-scheduling simulation of the complete file-order anchor of 2026-11-14 (2,000 recorded wall/Lean seconds), a
stratified bootstrap of it, a comparison with the live file-order anchor on this node (1,091 shared statements); both
orders through `ToleratedSearches` with the repo's fake vLLM servers and through `search_problem_set` with real Lean
REPLs (automation expander, 7 probe statements); fake nvidia-smi; the reserve check on the node's numbers; affinity.

## Tail simulation (112 slots, recorded per-statement wall seconds, durations independent of load)

| Order | Makespan | < 112 / < 56 / < 20 running | Idle GPU (full-pool equiv.) | Peak heavy | Lean cores: first 30 min / peak / min > 96 |
|---|---|---|---|---|---|
| file | 3.35 h | 52 / 45 / 31 min | 41 min | 53 | 47 / 104 / 63 |
| longest_proof_first | **4.24 h** | 101 / 98 / 93 min | **94 min** | 46 | 89 / 102 / 50 |
| oracle (longest search first) | 2.67 h | 0 / 0 / 0 min | 0 min | 100 | 110 / 110 / 95 |
| prior-run duration first (noise for Spearman 0.69) | 3.12 h [2.92, 3.35] | | | | |

Bootstrap (400 stratified resamples): file 3.36 h [p10 3.21, p90 3.48], longest_proof_first 4.16 h [3.22, 4.31]; the new
order is shorter in 54/400. Validation: file order at 84 slots on the real session-3 remainder gives 14,850 s against
14,924 s recorded (0.5%). "Heavy" = the 100 largest Lean-second searches (>= 2,271 s; 68 of them in 2000-4499, 10 in
4500+). Lean cores = sum of Lean s / wall s of running searches, in the old node's (contended, 52 CPUs) Lean seconds;
on this node the same statements use 0.62-0.65 of them (1000-1999), so peaks are ~65 cores of the 96-CPU set.

Why: proof length is a weak predictor of search length (Spearman 0.41 overall; 0.00-0.33 within strata on the live
run). 4500+ searches are not long (median 347 s, max 3,672 s: the 16-expansion budget caps them); the longest are
policy-step 60 s timeouts in middle and low strata (6,738 s and 5,309 s in 500-999, 89 and 70 wall-clock timeouts).
Longest-proof-first starts those two last (rank 1,780 of 2,000), which makes the tail. They recur: in the live file-order
anchor they are 2 of the 3 statements of 500-999 still unfinished at 1,201 results. Without them the new order would
win slightly (3.18 vs 3.30 h). If heavy searches slow each other, the new order's dense start (89 vs 47 cores in the
first 30 min) delays the late strata further: it gets worse, not better. The file-order tail measured on the real run:
48.5 min under 56 running, 35 min under 20 (the config comment says ~25 min).

Load each stratum sees (total Lean demand, weighted by its own Lean time): 4500+ 67 cores in file order, 88 in the
new; 500-999 57 vs 30; 0-499 30 vs 37; 1000-4499 within 8%.

## Must fix before merge

- **F1. The new order lengthens a probe run by ~50 min instead of removing the tail.**
  `experiments/configs/grpo/followup/probe_evaluation.toml:20` (inherited by gate, calibration and value-free configs);
  `evaluation.in_submission_order` (evaluation.py:80). Fix: set `submission_order = "file"` (keep the option and its
  tests). If the tail is worth fixing, add an order by a previous run's recorded `accounting.wall_seconds` (the
  anchor's results.jsonl, longest first, unseen statements by difficulty, ties in file order): 3.12 h at the measured
  cross-run correlation, vs 3.35 h; and only under F2's rule.
- **F2. Runs of different orders are rated and paired together, and a resume can change order silently.** The order
  is not in `ProbeRunStart.identity`, `probe_rating.finished_probe_runs` pools by (version, identity), and
  `probe_evaluate.evaluate` (around line 300) starts each session in the config's current order. The step-1 anchor
  `probe_step1_run1_v0_value_v0` is running now in file order; deploying this branch makes every later run (and that
  anchor, if interrupted) start 4500+ first. Measured: a file-order run resumed in the new order completes with
  identical per-statement results (fakes and Lean), and `sessions.jsonl` records each session's order, but run.json and
  the rating do not flag the mix. Fix: refuse a session whose `submission_order` differs from the run's first session
  (as `layout_differences` does for CPUs; old sessions read as file), and make `probe_rating` refuse to pair or pool
  runs whose orders differ (or put the order into the identity string).

## Should

- **S1. The per-tactic backstop is the load channel and is not counted per run.** It is recorded per statement
  (`results.jsonl` -> `step_statistics[].wall_clock_timeouts`, step `<policy>` or the automation tactic;
  `accounting.timeouts` = heartbeat + wall-clock). Complete anchor: 3,001 firings (2,957 policy steps, 1.6% of 180,964
  policy attempts; 44 automation), ~180,000 of 825,431 Lean-s; by stratum 13 / 204 / 108 / 500 / 1,035 / 826 / 315. Same
  statements, same checkpoint, old node (52 CPUs, 84) vs this node (96 CPUs, 112): 1500-1999 177 -> 43, 1000-1499 86 ->
  57. An automation tactic is dropped for the rest of a search after one wall-clock timeout
  (`max_wall_clock_timeouts_per_tactic = 1`), so the backstop changes outcomes, not only time. Fix: add per-stratum
  tactic wall-clock timeouts and policy attempts to `ProbeRunRecord` (probe_evaluate.py:371) and the run log line.
- **S2. GPU snapshots are taken when the GPUs idle.** Session start and run end (probe_evaluate.py:303, 371) are idle
  moments: the node's `power_limits.txt` shows SM clocks at 210 MHz then, and the enforced limit drifting 295 -> 326 W
  as an idle GPU cools; during load it sits at 261-350 W. The loop's `phase_start_gpus` is the previous phase's
  closing reading (loop.py:2321), before the pause, not when sampling began. Fix: a 60 s sampler line
  (power.draw, enforced limit, clocks.sm, clocks_throttle_reasons.active) into the run directory, or drop the clocks.
- **S3. `gpu_power_states` can still block.** A fake that hangs, ignores SIGTERM or holds the pipe in a child returns
  None in 2.0 s (timeout 2 s), but `subprocess.run` waits for the killed child; an nvidia-smi stuck in the driver
  (D state, the usual hang) never dies, and run.json is written after the query (probe_evaluate.py:371). Fix: Popen,
  kill on timeout, do not wait; or query in a daemon thread joined with a timeout.

## Minor

- `SERVER_RESERVE_CORES=abc`: traceback from `current_pinning` (node_checks exits 1); `-50` is accepted and passes any
  set. Validate in `node_pinning.server_reserve_cores` (non-negative float, ValueError with the setting's name).
- `probe_runs.sh:92` passes `--allow-other-pinning` to every run of the lists: one flag waives the layout check for
  all their interrupted runs (each session recorded). Unknown option, `--`: exit 2 (tested). Say so in the header.
- `thread_on_cpus`: verified it sets and restores the thread's CPUs, on an exception too, and that a pool or subprocess
  created inside stays on them (`taskset -cp`: 3; a child Python: [3]); other threads and a pool created before keep
  theirs. The copy is `shutil.copytree` in that thread: fine. Kernel writeback of the 13 GB runs in flusher threads
  outside it. No test for the exception path.

## By test (items 2-5)

- Equivalence: fakes (16 statements, 2 policy + 1 value fake): identical answers and token sums (2,640 each); a policy
  server dying after 10 completions: complete and as undisturbed in both orders, the failed statement started again
  next (start positions 6, 7), restart sessions record the order. Lean (`search_problem_set`, 2 REPLs, 2 expansions):
  identical proved, stop reason, proof, expansions, nodes, edges, errors, timeouts in both orders; cancelled after 3
  results in file order and resumed in the new: 7 lines, 7 unique, identical. `--problems 6`: same statements.
- Position: none found. Exploration draws are seeded by statement name (search.py:378) and off in the probe; policy
  sampling is unseeded (temperature 0.8) whatever the order; the server rotation is a global round-robin
  (rotation.py:68) over servers checked to hold the same weights; REPLs are handed out LIFO and restarted past half
  their limits between searches (timing only; 11 REPL failures in the whole anchor); headers preloaded from the
  pending set. Through load only: the 60 s tactic and 7,200 s search backstops, value batches' numerics.
- Backstops (complete anchor): no search stopped on the wall clock; closest 6,738 s (94% of 7,200) and 5,309 s, both
  500-999; >= 3,600 s: 2 / 0 / 4 / 7 / 3 / 1 in 500-999 .. 4500+. Per-tactic firings: S1.
- Reserve: 96 Lean CPUs, reserve 8, quota 105.326: passes; 104 CPUs: refused ("leave 1.3 cores"); with
  `SERVER_RESERVE_CORES=1` passes and `current_pinning().server_reserve_cores` = 1.0 (unset: null).
- nvidia-smi fakes: `[N/A]` / `[Not Supported]` null alone; exit 18, a warning line first or a header line: whole
  answer null; hangs: null after the timeout.

## Pairing across orders

No. The order moves load between strata (4500+ +31%, 500-999 -48% of experienced Lean demand) and the per-tactic
backstop fires 4x more often on the same statements under more Lean contention; a probe comparison per stratum against
an anchor in the other order would carry that. Above 48 busy Lean processes the 96 CPUs are hyperthread pairs, so
contention bites well below the set's size. Cheapest settling measurement: the next anchor replicate in the new order
(a run the study makes anyway), compared with run1 per stratum on tactic wall-clock timeouts per policy attempt and
Lean-s per policy attempt; equal within Poisson noise (e.g. 315 +- 2x18 in 4500+) means order is load-neutral there.

Verdict: rework the order (F1, keep file order for the study) and add F2's guard; the GPU, reserve, affinity and script
parts can merge as they are, S1-S3 soon after.

## Re-review (ae3ea5d; WSL: lean-load, GPU, pinning, probe, tolerated-search, loop, handoff, layout tests 358 passed)

1. No divergence. `evaluation.py`, `fixed_targets.py` and the configs equal master, so the fake-server runs cannot differ.
   Real Lean (`search_problem_set`, 7 statements): master and branch identical line for line (proof, expansions, nodes,
   edges, errors, timeouts, tokens, step statistics); cut off on master after 3 results, resumed on the branch: 7 lines,
   identical. Master-era `sessions.jsonl` / `run.json` read on the branch (`gpus` null, `lean_load` empty). F2 is moot.
2. GPU query: `[N/A]`, `[Not Supported]` null alone; NVML failure null; one GPU's error line: the other three kept; hang,
   SIGTERM ignored, pipe held by a child: null after the timeout, then null at once (latched, also after a one-off hang).
   Minor: the lost GPU is absent, not marked.
3. `probe_compare.py load` equals my counts (complete anchor 3,001; 13 / 204 / 108 / 500 / 1,035 / 826 / 315). Cells:
   tactic wall-clock timeouts (statements) / REPL failures / Lean s per policy attempt, on the 1,382 statements both have:

| Stratum (n) | Old node (52 CPUs, 84) | This node (96 CPUs, 112, in progress) |
|---|---|---|
| all (1,382) | 860 (142) / 11 / 2.29 | 554 (122) / 35 / 1.70 |
| 0-499 (150) | 13 (2) / 0 / 0.62 | 18 (6) / 0 / 0.66 |
| 500-999 (249) | 114 (8) / 1 / 1.34 | 94 (8) / 21 / 1.15 |
| 1000-1499 (350) | 108 (32) / 0 / 1.80 | 113 (25) / 6 / 1.38 |
| 1500-1999 (341) | 380 (54) / 0 / 3.22 | 222 (46) / 0 / 2.45 |
| 2000-2999 (292) | 245 (46) / 10 / 2.59 | 107 (37) / 8 / 1.70 |

   Whole old run: 3,001 (379) / 11 / 4.03. This node's finished hard statements are its quicker ones; rows will rise.
   New: REPL failures 11 -> 35 on the same statements, 28 in two searches (`sqrt_17_problem` 20, `lean_workbook_23568'` 8).
4. Reserve at `record_session_pinning` (quota 105.326): 96 CPUs pass; 104 refused, nothing recorded; 104 with reserve 1
   recorded (1.0); unpinned recorded; `abc`, `-50`, `nan`, `inf`, blank: one line each, `node_checks.py pinning` exit 1.
Verdict: merge.
