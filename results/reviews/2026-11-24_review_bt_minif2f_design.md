# Review BT: miniF2F-valid evaluation of final checkpoints (design and operations)

Reviewer: independent agent, 2026-11-24 (node clock 2026-11-23 23:4x UTC at review time). Scope: the uncommitted
`experiments/configs/grpo/followup/minif2f/`, `experiments/minif2f_valid_set.py`, `minif2f_valid_set` in
`src/lean_search/rl/fixed_sets.py`, its tests, and the launch script `minif2f_after_d.sh` (scratchpad), against
DESIGN.md "Evaluation", `deployment/probe_runs.sh`, `experiments/probe_runs.py`, `experiments/probe_evaluate.py`,
`experiments/probe_compare.py`, `src/lean_search/rl/arm_comparison.py` and the node (read-only ssh: cat, ls, grep, ps,
sha256sum).

## Verified correct

- **Set.** `minif2f_valid_set` refuses any non-valid problem (`fixed_sets.py:296-299`). `data/minif2f/minif2f.jsonl`
  has 244 valid and 244 test rows, no shared name, no shared statement body. The PC and node copies are identical
  (sha256 `d6654c88…7dd5` on both). Rebuilt in WSL: 244 statements, strata amc12 45 / mathd_algebra 70 / aime 15 /
  mathd_numbertheory 60 / induction 8 / imo 20 / numbertheory 8 / algebra 18, file sha256 `bee5a77d…029c`, the
  script's `SET_SHA256`. The names are the same 244 that `minif2f_v0000` and `minif2f_v0035` searched. Start order is
  the file order, as the old loop's `load_minif2f(Split.VALID)` gave. Headers and statements are the miniF2F rows, and
  the search reads only name, header and statement (`pool.py:85-87`). The `minif2f.` name prefix only seeds
  exploration, which is off.
- **Search config.** I rendered the run config with `probe_run_config` (WSL) and diffed it against
  `node_backup/2026-11-01/hf_dataset/evaluations/minif2f_v0035/config.toml`. It is identical except for one new field,
  `[policy] step_log_probability = "completion"`, the default, unused with a value model. That includes harvest and
  exploration off, A* with value_weight 1 and depth_weight 0.25, n = 8, T 0.8, 64 expansions, 3,600 s, 112 REPLs and 4
  policy plus 4 value servers. Against the probe config, only `probe_set`, `output`, `max_expansions` and
  `max_wall_seconds` differ. `max_wall_clock_stop_share` (0.01) is inherited.
- **Checkpoints (node `ls`).** All exist: `followup_C_phase_0016/{expert_iteration,value}/adapter`,
  `followup_screen_F_2e-5_phase_0016/{policy,value}/adapter`, `data_rewrite_sft_numbered/adapter`,
  `phase3_value_v0/adapter`, `hf_policy_latest_v35/adapter` and `hf_value_latest/adapter`. C16 uses the same paths and
  `value_version = 16` as the arms driver's `arm_C_phase16_run1` (`/workspace/runs/arms_chain/probe/runs_C.toml`). v35
  uses the same paths as the node-local `step1/runs_v35_value_final.toml` (value_version 35). For D, the phase
  directories hold both `policy/` (the GRPO step) and `expert_iteration/` (the round after it). The published policy is
  the round's, which `arms_chain.py:563-568` gates on (`adapter.endswith("expert_iteration/adapter")`) and `d_after.sh`
  uses for D8, so `expert_iteration/adapter` for D16 is right. D's value adapter exists only at even phases (D6 has
  `value/`, D7 does not), so `followup_D_phase_0016/value/adapter` will exist if D reaches phase 16. v0 with `value =
  "v0"` resolves to base.toml's `phase3_value_v0`, as the old `minif2f_v0000` did (value version 0).
- **Tests.** `pytest tests/rl/test_followup_minif2f.py tests/rl/test_fixed_sets.py`: 55 passed (WSL). Every list passes
  `run_refusals` at concurrency 112, and the v0 anchor satisfies `probe_run_list.py:137`.
- **Compare calls.** `compare` passes full run directories. `probe_compare.run_directory` takes a path that exists as is
  (`probe_compare.py:91-93`). `probe_strata` reads the set from each run's `checkpoint.json`. The output path
  `${M}/probe_<name>` matches `probe_evaluate.run_directory` (`probe_evaluation.py:394-396`) under
  `$LEAN_SEARCH_RUNS/minif2f_evaluations`. All runs share one identity setting (budget, cap, concurrency, search
  config), so `pair` without `--primary` gives a descriptive verdict, as intended.
- **Wait and deploy mechanics.** `d_after.sh` ends with `say "D after done"` (line 58), so the grep target is right.
  The pgrep pattern `screens/d_after.sh` cannot match the launcher's own command line
  (`…/screens/minif2f_after_d.sh <commit>`), and `pgrep` excludes itself. `${E}` (`/workspace/runs/step1_chain/edits`)
  exists, so the before/after diffs get written. The node is at `04333f0`, and `04333f0..c6480c2` changes only
  HANDOFF.md and `results/followup_progress.md`. Nothing touches the node's locally edited step1 configs, search configs
  or uv.lock, and the new files do not collide with the node's untracked files. The node has tracked local edits and an
  empty stash list, so push and pop are paired. `servers-free` checks only the lock and loops
  (`node_checks.py:121-128`), so leaving servers up between lists is fine. The launcher is restart-safe: a rerun skips
  accepted runs, resumes interrupted ones, and gets exit 3 again at once for rejected ones.

## Findings

### 1. Blocker: under the 1% rule the runs will most likely be rejected, so no comparison gets written

`run_record` accepts a run only if `wall_clock_stops / problems < 0.01` (`probe_evaluation.py:1051-1055`). With 244
statements, 3 stops (1.23%) already reject a run. The two reference runs would themselves fail this rule:

| run | wall-clock stops | share | accepted under the rule? |
|---|---|---|---|
| minif2f_v0000 (concurrency 40) | 5 | 2.05% | no |
| minif2f_v0035 (concurrency 112) | 3 | 1.23% | no |

(`summary.json` and results.jsonl in `node_backup/2026-11-01/hf_dataset/evaluations/`.) The stops are Lean-bound
(Lean seconds about equal to wall seconds). `imo_2006_p3` (49 and 41 expansions) and `mathd_numbertheory_543` (39 and
20 expansions) stopped in both runs. `imo_1977_p5`, `aime_1996_p5` (3,535 s in v35) and `amc12a_2008_p15` (2,856 s)
come close or stop in one run. New runs at 112 REPLs on 96 Lean CPUs will very likely have 3 or more stops each.

Consequences:

- `probe_evaluate.py` returns 3, and the launcher logs a rejection and goes on (fine).
- `arm_comparison.read_arm_run` raises unless `run.json` says accepted (`arm_comparison.py:116-117`), so every
  `compare` returns "compare … failed" and `${M}/compare/*.txt` stays empty. The stated intent ("comparisons written
  after each run") does not happen.
- The node's precedent applies the rule strictly. `followup_node_operations.md:844`: the pilot was rejected at
  exactly 1.00% and rerun at a higher cap. The rule's own remedy (double the cap to 7,200 s and repeat every compared
  run at that cap) cannot fit before 20:20.

This needs a decision from the owner before launch. Option (a): declare the 3,600 s cap a budget for miniF2F, as it
was in grpo_loop_v1, where a wall-clock stop counts as unsolved. Set `max_wall_clock_stop_share` in
`minif2f_evaluation.toml`, for example to 0.03 with the old runs' 5/244 and 3/244 as the justification, then adjust
`test_the_minif2f_evaluation_differs_from_the_probe_only_in_set_output_expansions_and_wall_cap` and say so in DESIGN
"Evaluation", which says "every probe and miniF2F run is accepted only with under 1%". Option (b): keep the rule and
accept that the night yields rejected runs, compared later by hand. `probe_compare.py load` still works on rejected
runs, but `pair` does not. Option (a) keeps the references meaningful. Under (b), the references are rejected runs by
the study's own rule.

### 2. Should-fix: the order puts v0 last, but the design pairs miniF2F against v0, and the deadline will cut v0

Time per run: v35's old run at 112 REPLs took 3,712 s wall (`summary.json`). At 112 REPLs all 244 searches start
within minutes, so each run lasts about the cap plus the startup tail. Add merging both adapters and restarting the 8
servers (about 200 s, base.toml:41-44) and compare_all, and a run takes about 70-75 min. From about 15:30 UTC: C16
about 16:45, F16 about 18:00, D16 about 19:15. v35 would end about 20:30, after the 20:20 maintenance, and v0 never
starts. If D's loop and probes finish later than 15:30 (D was at phase 7 at 23:30 UTC with 9 phases plus two 2.3-2.9 h
probes still to go; ledger durations 2.26-2.90 h), only C16 and F16 finish.

DESIGN.md:1285-1286 says miniF2F is "paired (McNemar) against v0 only". DESIGN.md:1143 says 244 statements cannot
resolve arm differences under about 7 points. The comparisons that would complete (C16 against F16, D16 against C16,
D16 against F16) are the least informative ones. All four planned "against v0" comparisons need the run that never
starts. The old v0 reference (160) was searched at 40 REPLs, not 112 (`progress.json`: concurrency 40), so it is a
weaker like-for-like reference than v35's (170, at 112). Recommendation: order v0 second, after C16 (or first), and
v35 last. v35 has the more comparable old reference, so it is the most dispensable run. Optional: the owner could
also run miniF2F before d_after.sh's D8 probe. D8 is a descriptive intermediate checkpoint of about 2.5 h, and moving
it after miniF2F would let all five miniF2F runs fit before 20:20.

### 3. Should-fix: a single transient `pgrep` match stops the whole plan

At `minif2f_after_d.sh:35-36`, one `pgrep -f "grpo_loop.py|probe_runs.sh|probe_evaluate.py|f_chain.sh"` hit calls
`stop`, with no retry. `pgrep -f` also matches any shell whose command line contains these strings. Examples are an
orchestrator or watchdog ssh such as `ps … | grep -E "grpo_loop.py|probe_runs.sh|…"` (this review ran exactly such a
command) or `tail …/probe_runs.sh`. A watchdog poll that coincides with the check leaves the GPUs idle until someone
notices. Fix: retry for a few minutes before stopping, for example the same 360 × 10 s loop as `gpus_free`. Or match
only real processes, for example `pgrep -f '^python experiments/(grpo_loop|probe_evaluate)\.py|^bash .*deployment/probe_runs\.sh|^bash .*/f_chain\.sh'`.
`probe_runs.sh` already refuses on a held serving lock or a running loop (`node_checks.py servers-free`), and
`gpus_free` covers the rest. The wait loop's `pgrep -f "screens/d_after.sh"` (line 29) only delays on a transient match,
so it is fine.

### 4. Should-fix: the rejection message names the wrong cap

At `minif2f_after_d.sh:88`, the message says "repeat later at a 14,400 s cap". The rule is the cap doubled
(`probe_runs.sh:105-106`, DESIGN.md:1267-1268), which here is 7,200 s, and every run compared with it repeats at that
cap. 14,400 s was the step-1 pilots' doubling from 7,200 s. Whoever acts on the log would quadruple the cap.

### 5. Note: the base.toml miniF2F target disagrees with the run's cap

base.toml:259-265 `[evaluation.minif2f]` sets `max_wall_seconds = 7200.0` and `concurrency = 56` ("runs standalone
at an arm's end"). `test_the_minif2f_evaluation_matches_the_loops_minif2f_budget` checks only the expansions. The
3,600 s choice is deliberate (the old runs' cap, plus the deadline). The config comment says why, but base.toml still
reads as if miniF2F ran at 7,200 s. Worth one line in base.toml or in the progress file.

### 6. Note: compare_all runs between runs while the GPUs idle

`compare_all` (8 `probe_compare.py` processes, each importing the package and bootstrapping) runs synchronously after
each run and before the next `probe_runs.sh`. Expect a minute or more of idle GPUs per gap, and the servers stay
loaded meanwhile. With finding 1 unresolved, each call only fails. Consider `compare_all &`, which is CPU-only, writes
its own files and does not touch the next run.

### 7. Note: stash fragility (no current risk)

`git stash push -q` with no tracked edits saves nothing and exits 0. `git stash pop` would then pop an older,
unrelated entry, or fail on an empty list and stop the plan. On the node today the stash list is empty and tracked
edits exist, so the pair is safe. A guard such as comparing `git stash list | wc -l` before and after the push would
make it robust. Also, `<commit>` must be a hash, not `master`: `git rev-parse master` would equal HEAD before the
fetch, and the deploy would be skipped silently, followed by `minif2f_valid_set.py` not found.

### 8. Note: when d_after.sh stops, miniF2F stops too

At `minif2f_after_d.sh:30`, any `D_AFTER_STOPPED` stops the launcher. That includes a D8 probe exit 3 or 4 and an arms
driver STOPPED like the one at 22:31 UTC after the host outage. Given the owner's look-first rule, that is defensible.
It does mean one unrelated D8 problem idles the GPUs for the evening unless the watchdog acts. The handover note should
say to start the launcher by hand in that case.

### 9. Note: maintenance cut-off

The launcher does not check the clock before starting a run. A run cut at 20:20 leaves partial results that resume
under the same name (run directories, sessions). Rerun the launcher with the same commit after the maintenance; the
deploy is skipped because HEAD equals the commit. That is the right behaviour (no idle GPUs before the cut), but the
runs then span two sessions and possibly two CPU layouts. `probe_runs.sh` refuses a different layout unless given
`--allow-other-pinning`, so the restart needs that flag if the layout changes.

### 10. Note: config comment

`minif2f_evaluation.toml:3` says "no measured search times exist for these statements". The old runs' results.jsonl
hold per-statement `wall_seconds` for all 244. Longest-first order would shorten the tail only marginally, because
every search starts within minutes at 112 REPLs, so file order is fine. The comment is just inaccurate.

## Summary

| # | severity | item |
|---|---|---|
| 1 | blocker | 1% rule against a 3,600 s cap: references would fail it, new runs most likely rejected, no comparisons written |
| 2 | should-fix | v0 last although miniF2F is paired against v0; deadline fits 3 runs (maybe 2): move v0 to 1st/2nd, v35 last |
| 3 | should-fix | one-shot `pgrep -f` check stops everything on a transient match (watchdog ssh commands) |
| 4 | should-fix | rejection message says 14,400 s; the doubled cap is 7,200 s |
| 5-10 | note | base.toml cap mismatch; compare_all idles GPUs; stash fragility; d_after stops cascade; maintenance resume needs `--allow-other-pinning` if layout changes; comment inaccuracy |

## Re-review (2026-11-24)

1. **Blocker 1: resolved.** `minif2f_evaluation.toml:9` sets the top-level `max_wall_clock_stop_share = 0.05`.
   `probe_evaluate.load_config` merges the file over its base with `resolved_toml`, and I rendered the result in WSL:
   `ProbeEvaluationConfig(... max_wall_clock_stop_share=0.05 ...)`. `run_record` takes the share from the config
   (`probe_evaluate.py:408`, `probe_evaluation.py:1055`). Every reader of acceptance reads `run.json["accepted"]`:
   `arm_comparison.py:116`, `probe_run_list.py:236`, `probe_rating.py:119`. None of them recomputes against 0.01, and
   the share is not part of the run identity (`ProbeRunStart`). A run is now accepted with up to 12 stops of 244
   (12/244 = 4.9% < 5%). The references, at 5 and 3 stops, would pass. The tests pass (56, including the new
   stop-share test). The `newline="\n"` added to `write_fixed_set` changes nothing on Linux, so the set's sha256 still
   matches.
2. **Order: accepted as the owner's call.** The order is C16, F16, D16, v0, v35. With about 70-75 min per run from
   about 15:30 UTC, v0 starts around 19:15 and will probably be cut by the 20:20 maintenance. It resumes under the same
   name if the launcher is rerun afterwards, with `--allow-other-pinning` if the CPU layout changes (note 9). Until
   then the "against v0" files say a run is missing. This is not a blocker.
3. **pgrep: resolved.** Lines 34-41 retry 6 times, 30 s apart, before stopping. That is long enough to outlast any
   watchdog ssh command. The `[g]` brackets do not change what matches, so the retry is what does the work. The script
   passes `bash -n`.
4. **Rejection message: resolved.** Line 93 now names the 5% rule and the 3,600 s cap.

Notes 5-10 stand as notes. The comment at `minif2f_evaluation.toml:3` still says no measured search times exist.

**Nothing is blocking.**
