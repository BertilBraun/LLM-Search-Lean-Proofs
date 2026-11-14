# Review AC: follow-up WP0 (probe v2, near-duplicate guard, base config, probe_evaluate.py), code

Branch `worktree-agent-afca96780ff18295f` (b39b405..5f08131, 6 commits) against DESIGN.md "Follow-up study: controlled
arms (agreed 2026-11-14)" and `results/followup_step0/pool.md`. Tests: the touched suites (`tests/rl/test_fixed_sets.py`,
`test_training_overlap.py`, `test_probe_evaluation.py`, `test_shipped_grpo_configs.py`, `test_statement_sources.py`,
`test_loop_support.py`, `tests/expert_iteration`) 537 passed in WSL. Scratch check: `overlap_check.py` in the session
scratchpad. Not run: anything on a GPU or vLLM.

Verified correct: the draw is seeded (sha256 of seed and name, candidates sorted by name), the per-band counts are exact,
and a band that runs short raises before anything is written. The old three-strata selection matches the golden tests,
and `difficulty_band` with the default edges gives the old labels. `stratum_order` sorts easy/hard/medium alphabetically
as before. The dashboard's `strataRank` gives the old easy, medium, hard order. A held-out name never reaches the
curriculum: `CurriculumStatements.unavailable` → `Curriculum.add(started=...)` never makes it available, and
`_below_band_name` re-feeds only `self.searched`. `--value none` opens no value client (`open_search_models` checks
`config.value.model`). A loop that starts later serves its own current version again (`GrpoLoop.session`).

## Must fix before merge

1. **The acceptance rule is 5%; the design says under 1%.** `probe_evaluation.py:35` `max_wall_clock_stop_share = 0.05`,
   the same in `followup/probe_evaluation.toml`, and `run_record` (`:126`) accepts `share <= max_share`. The design says
   "accepted only with under 1% wall-clock stops, reported by stratum". As shipped, a run with 99 stops in 2,000 passes.
   No stops per stratum are recorded either. Fix: 0.01 with a strict `<`, and add wall stops per stratum to `run.json`
   (from the results and each problem's stratum). The parametrized test at `test_probe_evaluation.py` pins 0.05 and has
   to change too. `rl/README.md` says "rejected above 5%".
2. **Runs get rated when they should not, and different checkpoints get pooled.** `probe_evaluate` writes every run to
   one `$RUNS/probe_evaluations/probe_<name>/`, and its docstring says `probe_rating.finished_probe_runs(<output>)` rates
   them all. `finished_probe_runs` (`probe_rating.py:96`) takes every `probe_*` directory with a `summary.json`, and
   `probe_ratings` groups runs by `policy_version` alone (`:236`, `value_version=max(...)` at `:257`). Concretely:
   (a) step 1's v0 runs with value v0, the old final value and none are fitted as one ability "version 0";
   (b) arm A phase 8 and arm B phase 8 (both `--policy-version 8`) become one version;
   (c) a rejected run still has `summary.json` (written by `run_problem_set_evaluation` before the acceptance check),
   so it is rated next to its doubled-cap rerun.
   Fix: make `output` per series (arm and value model) or add `--output`. Write a rejected run's summary under another
   name, or have `finished_probe_runs` skip runs whose `run.json` says `accepted = false`. Add a test with two runs of
   one policy version but different value versions.
3. **The base config keeps the old run's in-loop evaluations, which break the design's load and checkpoint rules**
   (`followup/base.toml`; the diff test `test_the_followup_base_differs_from_the_loop_only_...` locks them in).
   - `[evaluation] beside_sampling = true` (`:196`). The probe runs every 2 h at 56 REPLs with a 1,800 s cap
     (`:220-223`), and miniF2F and a 12-part probe baseline run `at_start` in every arm (`:223,251`). The design says
     "Nothing else runs on the node beside an arm or an evaluation". Because tactic timeouts are wall-clock, that load
     changes the arm's labels, and each arm would repeat a ~2,000-statement v0 baseline that the acceptance rule rejects
     (1,800 s cap, a different concurrency). Fix: probe and miniF2F `every_hours = 0`, `at_start = false`; all probe
     runs go through `probe_evaluate`.
   - `[retention] adapter_versions = 5, healthy_versions = 3` (`:271`). The design says "all (`adapter_versions = 0`)".
     Phase 4's and phase 8's adapters, which are evaluated after the arm on retained adapters, are deleted by about
     phase 10. Fix: `adapter_versions = 0`.
   - `[evaluation.held_out_states]` uses `baseline_concurrency = 6` but runs at 112 at the pause (`:261,264`). The
     design (Load, decided) says "v0's held-out baseline at the pause's" concurrency. The hard stop compares the two.
     Fix: equal values, both from the throughput test.
4. **`probe_evaluate.py` swaps weights under a running loop without checking.** `serve` (`:97`) only checks health,
   then `release_gpu` (`/pause`) and `restore_gpu` on every policy server. If a loop is sampling (any arm: they all
   share base.toml's server URLs), its trees are labelled with its version but sampled by another policy. At its next
   pause the loop re-serves its own version, so the probe run continues on the wrong weights. Both failures are silent.
   Fix: refuse while any `$LEAN_SEARCH_RUNS/*/loop.pid` names a live process or any loop's `children/` has live jobs
   (the logic of `loop_services.stopped_loop_refusal`, applied to all loops). Check again before writing `run.json`.
5. **Probe v2 does not exclude what grpo_loop_v1 searched and trained on.** The design runs v0 with the old final value
   model (run 5) and v35 with final/v0/none (runs 7-9) on probe v2 to answer Q4. The old loop searched ~24% of the usable
   pool (pool.md §3: 52k of 68.5k never fed), and its value model trained on all those trees, solved and unsolved. Its
   policy (and expert-iteration round 1) trained on the solved ones. About a quarter of probe v2 would then be training
   data for the "final" side of the Q4 comparison. Fix: add an `Exclusions.searched_by_old_run` from the published
   `search_trees/index.jsonl`; every band keeps ≥ 4,787 candidates for ≤ 400 draws. Or get the owner's decision and
   write it into the design.

## Should

6. **Near-duplicate guard gaps** (`training_overlap.py`, `near_duplicates.matches_any`):
   - The same root with its hypotheses reordered scores Jaccard 0.676 (scratch check), so a 0.7 threshold misses an
     exact duplicate. Sort the binders (anonymized) before hashing, or also compare a key built from the conclusion and
     the multiset of hypothesis types.
   - LSH recall at J = 0.7 is 1 − (1 − 0.7⁶)¹⁰ ≈ 0.71, so about 29% of pairs at the threshold are never proposed. Pool v3
     has the same banding, but there it only merged pool members. Here a missed pair means test-set contamination. Fix:
     after the draw, compare the 2,000 chosen (plus a reserve) against all references by brute force on the signatures
     (2,000 × N × 60 compares, chunked), and redraw on hits.
   - Only root states are compared (`step_index`/`depth` 0). A training proof whose later state equals a candidate's
     root (the candidate a sub-lemma of a training statement) passes. At least add an exact check of the normalized goal
     tuple against every training state; that is a cheap set lookup.
   - A mistyped `--training-data` directory yields nothing without error (`rglob` on a missing path). Only when all are
     empty does `numpy.stack([])` raise an opaque `ValueError`. Require every directory to exist and hold ≥ 1 root
     state. Record the root states per directory and about 20 sampled hit pairs (as pool v3's `dedup.json` does) in
     `probe_v2.selection.json`: 0.7 was calibrated on statement text, here it is applied to pretty-printed goals.
7. **The merged weights are never deleted.** The design's WP0 says "merge on demand and delete the merge after
   (~13.5 GB)". `serve` keeps every merge under `$CHECKPOINTS/probe_evaluations/weights/<hash>/`, about 8 GB per policy
   and 4.5 GB per value adapter. Over step 1 to step 3 (~30 checkpoints) that is 250+ GB. Delete after an accepted
   run, or add `--keep-merge`.
8. **The value-free run uses the template's priority settings.** `probe_run_config` (`:99`) only switches `kind`, so
   `automation_log_probability = -1.0` and `length_exponent` come from `visible_student_v2.toml`. The design's
   value-free search (and `gate_search.toml`) uses -2.8 for whole-sample sums. Put a `[value_free_priority]` table in
   `probe_evaluation.toml` and use it, so run 6 cannot silently use another constant.
9. **`--search-config` cannot set the budget.** `evaluation_run_config` overwrites `max_expansions` with the probe's
   16, but runs 3/4 need ≤ 1,024 expansions under a token cap, and the docstring says the search config "may be
   replaced per run". Either take the budget from an overriding search config, or say that runs 3/4 need their own
   evaluation config. Add `--problems N` (`first_problems_by_stratum`) for run 4's 200-statement pilot.
10. **The base config has more inherited settings the design changes**: `rollback_window_phases = 4` (proposed: 0),
    `reference_phases = 2` (design: 1, existing switch), held-out states `every_hours = 2.0` (design: at every pause,
    and phases are expected to run 1-2.2 h plus the pause). Sampling `concurrency = 112` and the held-out 112 assume the
    old 123-core quota on a 61-core node. Set them, or mark them `# THROUGHPUT TEST` and make WP6's launcher refuse the
    old values.
11. **The pool is not frozen.** `verified = "expert_iteration/pool_v3/verified.jsonl"` (`base.toml:161`, `probe_v2.toml`)
    is the file WP7's `phase6_pool_v3.py verify` appends to, and `CurriculumStatements.refresh` re-reads it at every
    tick. The design says "frozen as published (a file copy)". Point both configs at a copy.
12. **Paths in the checkpoint key.** `checkpoint` makes the policy adapter absolute, but `resolve_value_adapter`
    (`probe_evaluate.py:91`) returns a relative `--value` path as given, so the merge hash and `checkpoint.json` depend on
    the cwd. The merge cache is keyed by path only, so an adapter rewritten at the same path reuses a stale merge. Key by
    absolute path plus the adapter file's mtime and size, or a hash of its contents.

## Minor

13. A rejection exits with status 1 (`:163`), the same as a crash. Use a distinct code (e.g. 3) so a driver script can
    tell "repeat with the cap doubled" from "fix and resume".
14. `summary.wall_seconds` of a resumed run covers only the last session (`run_problem_set_evaluation`).
    `probe_v2.selection.json` does not record the pool file's identity (line count or hash) or the git commit.
15. `base.toml:207` still says "6 x 11 probe runs, 40 miniF2F" (the old numbers). `rolling_probe` keeps strata in
    insertion order; only the dashboard sorts them. `strataRank("unknown")` is NaN.
16. Tests: mostly behavioural and well named. Gaps: nothing imports `experiments/probe_evaluate.py` (serve with
    `--value none`, refusal of another checkpoint on resume, exit status, a running loop). Nothing runs
    `select_characters` end to end on tiny files (that the fixed-set, held-out-state and training-root wiring actually
    lands in `Exclusions`). There is no test for reordered hypotheses or a missing training directory. The base-vs-loop
    diff test is a good guard but currently asserts the inherited retention, rollback and in-loop evaluations
    (findings 3, 10). `test_the_shipped_probe_evaluation_raises_the_wall_cap_to_two_hours` only restates the TOML.

## Re-review (27eef46, d897212, 1f7f3f7)

Touched suites (plus `test_probe_rating.py`, `test_loop.py`): 759 passed in WSL. Scratch check: `order_check.py`.

Must-fix items:
1. Acceptance threshold: **resolved**. The share is 0.01 and strict (`share < max_share`), with stops per stratum in `run.json`.
2. Rating identity: **resolved**. Runs are pooled by (version, identity) and only accepted standalone runs are rated; a loop's runs are pooled by version as before (tested). See new item a.
3. Base config: **resolved**. No probe or miniF2F inside an arm and no baselines at an arm's start; `adapter_versions = 0`; the held-out states run at every pause at 56 = the baseline's concurrency; first-collapse stop; reference phase 1.
4. Running loop / other evaluation: **mostly resolved**. A flock lock, a loop.pid and children check, and a second check before `run.json`. See item c.
5. Statements the old run searched: **resolved**. They are excluded, and the selection refuses to run without the index.

Should-fix items: all handled, with gaps noted.
- Handled: hypothesis reordering (Jaccard 1.0 now); every pair compared for the drawn set; missing or empty directories refused; merges deleted unless `--keep-merge`; value-free constant set to −2.8 in config; `--search-config` keeps its own budget; `--problems` for the pilot; frozen pool with its sha256 checked; placeholders marked THROUGHPUT TEST.
- Gap: states deeper than a training proof's earliest are still not compared.
- Gap: the frozen pool's sha256 (`1b216b06...`) could not be checked here (no local copy of the pool).

New problems:
a. **Should, fix before the selection runs (a regression).** `training_overlap.goal_statement` sorts hypotheses by their *raw* type text, before anonymization. A renamed duplicate whose variable names sort differently is then put in another order. Example: `x y z` / `h₀ : x = 1` … renamed to `c b a`. Its Jaccard falls from 1.0 to 0.684, below 0.7, so the guard and the twins miss the most common near-duplicate. The selection is run once and cannot be redone, so fix it first. Fix: anonymize the variables first, then sort the hypotheses by their anonymized types. Add the renamed-and-reordered case as a test.
b. **Should: the rating anchor is `version_names[0]`, the lowest (version, identity) in string order.** For v0, "…/no value model" sorts before "…/value …". Once run 6 exists, every curve "against version 0" is relative to v0 *without* a value model. Name the anchor explicitly (arm "v0", value v0, not a pilot). Also add the run config's sha256 to `identity`: otherwise reruns at a doubled cap, or a same-budget search config, pool as repeats. Token-capped runs are kept apart only because their budget differs.
c. **Should: the lock is per `output`** (`$CHECKPOINTS/<output>/serving.lock`), and only `probe_evaluate` takes it. A second evaluation config with another `output` swaps the same servers unguarded. So do `run_search.py` (miniF2F), `grpo_evaluate.py`, gate-benchmark, and a loop started by hand without `grpo_loop.sh` (no loop.pid). A loop that starts mid-run is only caught at the end. Fix: key the lock to the servers (one fixed path, e.g. `$CHECKPOINTS/serving.lock`), and have `grpo_loop.py run` and `run_search.py` take it too.
   - Stale state: flock is released when the holder dies, so a crash leaves no stale lock.
   - A loop.pid left by a crash whose PID is reused refuses (the safe direction; the message names the PID). An empty loop.pid refuses forever (`/proc/` exists).
d. **Should: `early_resume_valid_fraction = 2.0` is "never reached" only while v0's held-out valid rate is above 0.5.** On the new node at 56 REPLs, v0 could measure ≤ 0.5. Then the floor is ≤ 1 and a good version resumes beside the Lean tail. Use an explicit switch or a value such as 1e9, with a config test.
e. **Minor.**
   - `directory_digest` hashes every file in the adapter directory. A file added later (notes, a marker) changes the identity and blocks a resume. Hash `adapter_config.json` and `*.safetensors` only.
   - Merges leak if the value merge fails after the policy swap, or on SIGKILL.
   - The fake vLLM server replies `{}` to `/pause` and `/resume` and does not check call order. It pins which weights each server got, not the vLLM control API.

Verdict: **merge** once a is fixed (before `select-by-characters` is run). b–d can follow, but before step 1's first probe runs.
