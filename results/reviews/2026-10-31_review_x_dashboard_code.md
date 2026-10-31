# Review X: dashboard headline and probe rating, code (branch `dashboard-headline`, 814d2f9)

Scope: `git diff master..dashboard-headline` (13 files). Tests run in WSL: `tests/rl/test_probe_rating.py tests/monitoring`,
141 passed. Probed with scratch scripts against the branch's code (synthetic Rasch data, edge cases, timing,
import cost), and the demo (`dashboard.py demo`) rendered in a browser: overview and both runs render, no console
errors. Each finding says whether it was verified.

## Findings

1. **should-fix — `experiments/dashboard.py:33`: every dashboard command now imports torch and transformers.**
   The top-level `from lean_search.rl.probe_rating import record_ratings` pulls in `rl.evaluation`, then
   `expert_iteration.pool_search`, then `policy.expander`, which has a hard `from transformers import AutoTokenizer`.
   So `serve`, `record-system` and `demo` load torch and transformers too, not only `record-ratings`.
   Verified in the node's venv:
   - Max RSS of a process that imports the monitoring modules goes from 49 MB to 703 MB once `probe_rating` is imported.
   - The import takes 13 s warm and 25 s cold.
   - `grpo_loop.sh dashboard` starts three such processes, so about 2 GB more host memory on a node whose memory is
     budgeted (rl/README "Host memory").
   - Without the `ml` extras (transformers is not a core dependency), `dashboard.py serve` now fails with
     `ModuleNotFoundError`.

   Fix: import `record_ratings` inside the `case "record-ratings":` branch. Better still, keep `probe_rating.py` free of
   `rl.evaluation`: read `summary.json` through a small local dataclass, or move `EvaluationPaths`, `read_summary` and
   `EvaluationKind` to a light module. Then the recorder itself also stays near 50 MB.

2. **should-fix — `src/lean_search/rl/probe_rating.py:178-188`: any exception kills the recorder for good, and nothing
   notices.** The loop has no `try`. Some failures are certain. Verified:
   - `probe_ratings` on runs that are all empty (a `summary.json` beside an empty `results.jsonl`) raises `IndexError`
     at `ability_step[0]` (line 82).
   - A `summary.json` without `results.jsonl` raises `FileNotFoundError`.
   - `from_json_object` rejects unknown keys. The recorder is a long-lived process started once with
     `grpo_loop.sh dashboard`. Suppose the loop is restarted on newer code that adds a field to `SearchResult` or
     `EvaluationSummary`. The recorder's old code then raises `ValueError` on the next finished run.

   Any of these makes the process exit. The dashboard keeps showing the last `rating` line forever, with no staleness
   hint or alert. A restart also appends a duplicate line, because `rated` starts empty.

   Fix:
   - Catch and log per iteration, and per run in `finished_probe_runs`: skip an unreadable run with a log line instead
     of failing all of them.
   - Skip runs without outcomes. Return early when there are no outcomes.
   - Optionally, show the rating line's age in the tile's `sub`.

3. **should-fix — `src/lean_search/monitoring/static/app.js:764-767`: collapsing "Health" hides the alerts.** The alerts
   used to render at the top of the overview for every reader. Now they render only inside the health section
   (`if (section.alerts) renderAlerts(main)`), after `if (closed) continue;`. A reader who collapsed Health once has
   that choice remembered in localStorage. From then on they never see "loop silent", a hard stop or a value-model
   alert on the overview. Verified by reading. Nothing else calls `renderAlerts`.

   Fix: render alerts even when the section is collapsed, for example the alert list or at least a count and the
   worst severity in the heading. Or keep warning and critical alerts above the sections as before.

4. **should-fix — `probe_rating.py:136-163`: version 0 is assumed but not checked, and versions that share no problem
   with version 0 get ratings the priors make up.** Verified with scratch data:
   - With no version 0 runs (baseline `at_start = false`, as in `loop_overfit.toml`, or a missing baseline part), the
     anchor is silently the lowest version, for example v3 at 0. The UI still says "version 0 = 0" and "v0 on the
     same problems".
   - Say v1 searched only problems v0 never searched. `baseline_solved_within` is then `0.0` (line 161), not
     "unknown". The headline tile reports "v0 on the same problems 0.0%" and marks the gain "good".
   - Its Rasch rating is not identified, but it comes out as a confident number. v0 solved 40% of part A. A v1 that
     solves 20% of part B rates -1.87 logits (95% from -2.86 to -1.36). One that solves 80% rates +1.87 (from +1.38 to
     +2.68). These are the difficulty prior's centre, not a comparison with v0.

   In the normal loop, v0's baselines cover every part twice, so this needs a missing or failed baseline part. The
   result is then wrong and looks significant.

   Fix:
   - Anchor on version 0 explicitly and refuse, or emit nothing, without it.
   - Emit `baseline_solved_within` as `None` when there is no overlap, and let the frontend show "–".
   - Rate only versions connected to the anchor through shared problems (a BFS over the version and problem
     bipartite graph). Give the others no rating.
   - Add tests for the no-v0 and no-overlap cases.

5. **minor — `probe_rating.py:75` (`NEWTON_STEPS = 100`, no convergence check): the fit does not converge for many
   versions.** Both blocks are updated at once from the same probabilities (a Jacobi scheme). On the anchor/gauge mode
   its contraction factor approaches 1 as the share of rows from version 0 shrinks. Compared with an exact joint
   Newton fit on synthetic data (501 problems in 3 parts, one part per version), verified:
   - With v0 in 2 runs, the maximum ability error after 100 steps is 2e-9 at 15 versions, 7e-4 at 50 versions and 0.02
     at 100 versions (bootstrap fits 0.03).
   - With a single v0 run and 150 versions it is 0.17 logits, about 38 Elo. With no v0 covering all parts and 200
     versions it is 0.6 logits.
   - At 1000 steps the error is below 1e-4 everywhere.

   A long run with one rated version per slot (every 2 h) reaches 100 versions in about 8 days.

   Fix: iterate until `max(|step|) < 1e-8`, with a cap. Or solve the joint Newton system: it has V + P ≤ about 700
   unknowns, a dense solve per step that costs milliseconds.

6. **minor — `app.js:459`: the value benchmark tile shows "+0.0 points" for a missing difference.**
   `PairStatistic` is built with `difference/lower/upper = None` when no pair is scored by both models
   (`value/pair_statistics.py:148`). `null * 100` is `0` in JS, so `signed()` prints `+0.0 points, 95% +0.0 to +0.0`
   instead of "–". Verified by reading.

   Fix: pass `versus.difference === null ? null : versus.difference * 100`, and the same for lower and upper.

   Related: the sub shows `benchmark.pairs.pairs`, the model's own scored pairs, while the interval is over
   `versus.pairs`, the pairs both models scored. Show `versus.pairs`.

7. **minor — `app.js:503-522`: the health tiles are inconsistent for older or partial records.**
   - "Bare claims" tests `belowBand === null`. A health line written before the `below_band_*` fields existed (an older
     run, or a `--compare` run) has `undefined`. The tile then says "below the band" while showing the all-statements
     value, and the spark reads a column that does not exist. Use `== null`.
   - "Claims proved" takes its status from `below_band_claim_proved_rate` (as the alert does) but displays the overall
     `claim_proved_rate` (line 520). The warning icon can sit next to a number above the limit. Display `proved`, and
     say which population it covers, as "Bare claims" does.

8. **minor — `probe_rating.py:150` (`value_version = max(...)`): versions that searched with several value models.**
   With `evaluation.value_model = "published"`, one policy version's runs can span a value publish. The rating pools
   them, but the table and the docstring ("the value model it searched with") name only the highest. Either rate per
   (policy, value) pair, or label the column "value (latest)".

9. **minor — `pages.js:116-120`, `app.js:424`: "16" is hardcoded where the data carries the budget.** The chart labels
   "within 16" and the tile's "at 16 expansions" are hardcoded. `budget: "last"` is `max(run.expansion_budget)` over
   all `probe_*` runs. A whole-set `probe_vNNNN` run at another budget would also enter the Rasch fit unnoticed, since
   `finished_probe_runs` does not filter on `expansion_budget`. That would shift its version's rating.

   Fix: build the labels from `fields.budgets`. Rate only runs at the probe's configured budget, or the most common
   one, and log the ones skipped.

10. **minor — section toggle, `app.js:74-80` and `760`.** The open/closed state lives only in localStorage. When
    `setItem` throws (some private modes), `store` swallows the error and `collapsed()` keeps returning the default,
    so clicking a heading does nothing. The comment in `store` promises "lasts for this page only". Keep an in-memory
    map as the fallback.

11. **minor — `deployment/grpo_loop.sh:76`.** The echo still lists `{system_sampler,dashboard}.log` and omits
    `rating_recorder.log`. Rerunning `dashboard` starts a second recorder that appends duplicate lines (the sampler
    has the same problem); a `pgrep -f "record-ratings --run-directory ${run_directory}"` guard would prevent it.

12. **minor — tests, `tests/rl/test_probe_rating.py`.**
    - The existing tests construct their data correctly. In the "harder problems" test, version 2 keeps only problems
      30-59 and proves 30-44, against 1/30 each for v0 and v1 there.
    - The tests miss every failure mode above:
      - a version with no problem shared with v0 (rating and baseline)
      - no version-0 run
      - an empty or missing `results.jsonl` beside a summary
      - convergence against an exact fit with many versions
      - the recorder surviving a bad run
    - `pytest.importorskip("numpy")` is unnecessary: numpy is a core dependency.

Checked and fine:
- The Newton signs and the prior terms.
- The anchor at index 0 (its step is zeroed and it starts at 0).
- Bootstrap problems with weight 0: they relax to difficulty 0. A version whose problems all get weight 0 relaxes to
  ability 0; with ~167 problems per version this has probability about e^-167.
- `solved_at` None: `proved` guards it, and a renamed proof that fails the original check has `proved = False`.
- `solved_at.expansions` counts the expansion that found the proof (the increment comes before the batch), so
  "within 1" is right.
- Renamed statements keep the original `problem_name`.
- `summary.json` is written atomically after all results, so the recorder cannot read a partly written run.
- The value-arm exclusion catches `_value_arm` and `_value_arm_repeatN`. Repeat runs and whole-set `probe_vNNNN` runs
  are included as extra observations.
- `runs` counting.
- `overview.latest` is the raw last line, so `latest.rating.fields.versions` is the list of objects. `flattened` skips
  it for the columns.
- `versionSeries` and `budgetValue`.
- The toggle's closure: each render rebinds `closed`. Closing re-renders from cached data; opening refreshes.
- `wantedSeries` skipping collapsed sections: tiles read only their own section's families or the overview's latest.
- The removed tiles are referenced nowhere else.
- `json_safe` turns NaN into null.
- Timing: the full rating takes 1.9 s for 30 runs, 4.2 s for 75 and 8.4 s for 155.

## Verdict

The rating's model and its maths are sound, and the frontend changes work on the demo data. Fix three things before
relying on it on the node:
- the dashboard importing torch and transformers (1)
- the recorder dying silently (2)
- alerts hidden by a collapsed section (3)

Version-0 anchoring and overlap (4) should be guarded so that a missing baseline part cannot produce a confident wrong
rating. The rest is minor: convergence at very many versions, the null displays, labels and tests.
