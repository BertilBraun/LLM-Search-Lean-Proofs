# Review AR: starting probe searches longest expected first (by measured search time), by experiment

Branch `worktree-agent-a8257711895071364`, commit 68e70fe (the worktree also holds uncommitted edits, not reviewed:
`recorded_mismatches`, `token_capped_evaluation_ordered.toml` for runs 3-4). WSL: order, probe, tolerated-search,
probe-runs and lean-load tests 139 passed. Scripts and outputs:
`C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_ar\`.
Simulation: 112-slot list scheduling of each run's recorded `wall_seconds`, orders from the production functions
(`longest_expected_search_first`, `read_expected_search_seconds`; leave-one-out files written by
`expected_search_seconds_text` from `recorded_run`), durations independent of load.

## Simulation (makespan h; minutes with < 112 / < 56 / < 20 running; idle GPU = idle slots / 112, minutes)

| Run | File | Committed file (in-sample) | Leave-one-out | Mixed (LOO, longest/shortest alternate) | Oracle |
|---|---|---|---|---|---|
| run1 v0 value v0 | 3.15; 53/43/32; 41 | 2.52; 3/3/3; 3 | 2.88; 26/26/24; 25 | 2.80; 22/20/18; 20 | 2.47 |
| run2 v0 value v0 | 3.57; 68/62/50; 58 | 2.63; 3/3/2; 2 | 2.78; 12/12/11; 11 | 2.99; 26/24/22; 24 | 2.60 |
| run6 v0 no value | 3.06; 57/50/40; 47 | 2.30; 2/2/1; 2 | 2.74; 30/29/27; 28 | 2.56; 20/18/16; 17 | 2.27 |
| run6 v0 block sum | **2.32**; 25/20/10; 18 | 2.06; 3/3/2; 2 | **2.85**; 51/51/50; 50 | 2.41; 26/24/23; 23 | 2.02 |
| run5 v0 value final | 2.80; 42/35/24; 32 | 2.31; 3/3/3; 3 | 2.41; 9/9/8; 9 | 2.45; 14/12/10; 11 | 2.27 |
| run8 v35 value v0 (v0's file) | 3.55; 74/64/45; 59 | 2.88; 20/20/19; 19 | (out of sample) | 3.02; 30/28/26; 27 | 2.57 |
| run7 v35 value final (1,998) | 2.68; 55/46/27; 41 | 2.41; 25/25/25; 25 | (out of sample) | 2.09; 8/5/4; 5 | 2.02 |

Correction to the brief's 3.1-3.6 h vs 2.4-2.9 h: file order is 2.32-3.57 h (v0 mean 2.98), out of sample the new
order 2.41-2.88 h (v0 mean 2.73, v35 2.88 and 2.41); the in-sample 2.06-2.63 h flatters it by ~22 min. Gain per run
-32 to +47 min, mean ~15 min for v0, 40 and 16 min for v35; block-sum gets 32 min longer (its file-order run had a short
tail; the order still leaves 50 min under 20 running). Rank correlation of a run with the file: 0.81-0.84 out of sample,
0.73-0.74 for v35. The mixed order: mean 2.62 h over the seven vs 2.71 (new) vs 3.02 (file): a robustness option (it
fixes block-sum, loses on run2 and run8), not a Lean fix (first-30-min Lean demand 106-108 vs 108-110 cores).

## Lean load at the start (Lean share = lean_seconds / wall_seconds per search)

- First 30 min, summed shares of running searches: file 42-55 cores (peak 75-85), new order 102-110 (peak 105-110);
  all 112 running searches have share >= 0.5 (file: 79-95 at peak). Over the run, demand above 96 for 63-98 min (new)
  vs 37-95 min (file, mid-run). The 200 Lean-heaviest searches see 98-106 cores of Lean demand (time-weighted) in the
  new order against 85-92 in file order: above the 96 Lean CPUs (48 physical cores) instead of below.
- GPUs idle at the start: searches waiting on the model in the first hour average 2.5-9 (new) vs 39-49 (file). Fluid
  check (Lean parts slowed by demand / C above C): at C = 96 the new order still wins on 6 of 7 runs (block-sum 2.98 vs
  2.36 h); at C = 72 likewise. So the idle moves from the end to the start, and the run is still shorter because Lean
  is the binding resource; but these shares were recorded under file-order mixes and will grow under the new one.
- Outcome risk: the heavy searches are exactly those with repeated 60 s tactic timeouts, now all together on an
  oversubscribed Lean set. The README's replay (0 of 300 timeouts succeed alone) shows timeouts are not load-made; it
  does not show that steps succeeding at 40-60 s stay under 60 s at +15% Lean demand.

## No-reasoning (200-statement pilot, 1,024 expansions, 7,200 s cap)

Spearman of the pilot's wall seconds with the file: 0.74 (with run1's visible: 0.68). Its 20 longest searches sit in the
file's first 20 / 50 / 100 of the 200: 15 / 19 / 20; its two wall-clock stops (7,236 s, 7,223 s) rank 93 and 12 of
2,000. Pilot median 500 s vs 257 s visible; long ones Lean share 0.98-1.00. At 14,400 s the longest searches can take
4 h, so starting them first matters more there; the visible file predicts them well enough.

## Must fix before merge

- **M1. An accepted file-order run stops `probe_runs.sh` once its list's config turns the order on** (68e70fe
  `probe_runs.next_run` -> `start_mismatches(..., recorded_start_order)` before the state check: exit 1 "its record
  has start order 'file'"). Setting the order in a shared base (`probe_evaluation.toml`) would halt every list with a
  finished run. The uncommitted `recorded_mismatches` (order compared only for a run to be resumed) is the fix; commit
  it with a test that an accepted run in another order is skipped.

## Should

- **S1.** Validate before relying on the order for a comparison with file-order runs, as the README says: the heavy
  searches' Lean demand changes by +15% (above). Cheap check: the first new-order run's `probe_compare.py load` per
  stratum (tactic wall-clock timeouts per policy attempt, Lean s per attempt) against the five file-order v0 runs' range.
  Runs 3 and 4 (both ordered) pair cleanly; run 3 against run 1 now also crosses orders (the note prints; put it in the
  descriptive verdict text, not only below the table).
- **S2.** README numbers (rl/README.md, "Simulated on six recorded runs"): replace "file 3.1-3.6 h, 2.4-2.9 h" and
  "< 56 from 58-71 to 9-51 min" with the out-of-sample figures above, including the block-sum regression.
- **S3.** Statements missing from the file start first and are only logged (`probe_evaluate.py`, "N of M statements
  have no expected seconds"); a file of the same probe set but other names would silently give file order. Refuse when
  more than a handful are missing.

## Minor / by test

- Real Lean (`search_problem_set`, 7 probe statements, automation): file order and the new order give identical
  per-statement results (proof, expansions, nodes, edges, errors, timeouts, tokens, step statistics); cut off after 3
  results and resumed in the same order: 7 lines, identical. `ToleratedSearches` is unchanged, so the fakes give the
  same per statement as before (review AP); the order only permutes the input.
- Refusals: a file-order run resumed in the new order, the same order with another file digest, and back to file order
  are each named by `other_start_order` (probe_evaluate refuses without `--allow-other-order`); the same order and file
  is not. A file of another probe set: ValueError naming both digests (SystemExit in probe_evaluate). A statement
  missing from the file starts first. 0 of 2,000 probe statements are missing from the committed file.
Verdict: merge after M1 (commit the in-progress fix); use the order for runs 3 and 4 together, with S1's check.

## Re-review (2026-11-16)

193ce6e and eb422ce on 68e70fe; WSL: `test_submission_order.py`, `test_followup_step1.py` 113 passed. Verdict: merge.

- M1 resolved. `probe_runs.py next` on the real `runs_reasoning.toml` (a copy with T = 26,804 in place of its
  placeholder; fake run directories): pilot accepted in file order -> exit 0, next `step1_run3_visible_T` with
  `token_capped_evaluation_ordered.toml`; run 3 accepted in file order -> next run 4; run 3 interrupted in file order
  -> exit 1 "its record has start order 'file'"; interrupted in the order with another file digest -> exit 1; in the
  order with this file -> resumed; pilot interrupted in file order -> resumed on its file-order config.
- S3 resolved. `uncovered_statements` with the committed file: pilot subset 200 with 2 missing logged, 3 refused; full
  2,000 with 20 logged, 21 refused ("lacks 21 of the run's 2000 statements (more than 1%)").
- S2 resolved. README: file 2.32-3.57 h, new 2.41-2.88 h, ~15 min mean, block-sum +32 min, v35 3.55 -> 2.88 and
  2.68 -> 2.41 h, first-30-min Lean 102-110 vs 42-55 cores, and the 40-60 s caveat: as measured.
- TSV: only the `# run` header lines changed (sorted by name; run5 moved up); 2,000 data lines unchanged, each over 5
  runs, none of the probe's 2,000 statements missing; regenerated from the five runs with the production writer it is
  byte-identical.
- Config path (in place of a Lean run, which needs the servers): run 3's arguments name the ordered config; it resolves
  to `longest_expected_search_first (expected seconds 02f7eda36482)`, digest = the TSV's sha256, and a session started
  with it gives `run.json` `start_orders` that one entry.
- S1 (validate against file-order runs) stays an operator step; runs 3 and 4 share the order.
- New, minor: once a run of the list has a record, `next` refuses (exit 1) while the token-capped search configs hold T's placeholder, as `check`
  does; fill T before starting the list.
