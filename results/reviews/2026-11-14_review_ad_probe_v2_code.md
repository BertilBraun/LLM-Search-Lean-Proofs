# Review AD: follow-up WP0 (probe v2, guard, character curriculum, probe_evaluate.py), code

Branch `worktree-agent-afca96780ff18295f` (6 commits, b39b405..5f08131), read against master's DESIGN.md "Follow-up
study". Changed tests: 276 passed (WSL venv). Measurements on the published pool and trees (`node_backup/2026-11-01`) and
the 2026-10-15 SFT, reasoning and value data. v0's final `visible_student_v3_numbered` is not on this PC, so the guard
numbers are indicative. Scripts are in `C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\`.

## Traces

- (a) Selection works, but a missing `--training-data` directory is silent (finding 10). The loop holds probe v2 out
  by name and starts the band at 10 (1,000-1,200 characters). A part (~167 statements) runs every 2 h of loop time
  beside sampling. A pass takes ~24 h and `against_previous` ~48 h, so a 16-phase arm rarely gets one (findings 1, 7).
- (b) Each run serves the right weights, and `--value none` leaves the value servers alone. A resume skips finished
  statements and refuses a changed checkpoint, search config or cap. The risks are the missing guards, the path-keyed
  merge cache and the rating's grouping (findings 4, 5, 7).
- (c) A step is 50 characters (fast: 150); an empty band jumps to the nearest statement; lowering stops at the easiest.
  No tactic-scale constant is left on the RL path (root scoring is only in the old `search_service`); only labels
  remain (finding 14).

## Must fix before merge

1. **`base.toml` runs evaluations beside every arm and repeats v0's baselines at every start, all sized for 123 cores.**
   Affected lines: `followup/base.toml:96,101` (sampling 112, beside 56), `:196` (`beside_sampling`), `:220-227` (probe
   every 2 h, `at_start`, 1,800 s), `:251` (miniF2F `at_start`), `:261-264` (held-out states 112, baseline 6).
   - Why it matters: the design says nothing else runs beside an arm, because tactic timeouts are wall-clock and load
     changes the labels. Here 56 sampling plus 56 probe REPLs run on a 61-core quota. Before phase 1 of every arm,
     12x6 + 34 + 6 = 112 REPLs run a whole 2,000-statement probe plus miniF2F at 64 expansions: hours per arm, at a cap
     (1,800 s) and concurrency that differ from step 1's. That gives a second v0 number that cannot be compared with
     step 1's.
   - Fix: probe `every_hours = 0`, `at_start = false`; miniF2F `at_start = false`; `beside_sampling = false`. Held-out
     states: `every_hours` small enough to be due at every pause (with 2.0 a 1.5 h phase skips one), and
     `baseline_concurrency` equal to `concurrency` ("v0's held-out baseline at the pause's"). Set the concurrencies to
     at most ~56 until the throughput test sets them, and mark them as placeholders. Update
     `test_version_zeros_followup_baselines_share_the_sampling_concurrency`, which pins 112.
2. **Retention deletes the adapters the study must evaluate later; rollback is still on.** At `base.toml:271`,
   `adapter_versions = 5` deletes phases 4 and 8 by about phase 10 and 14. The design requires all of them
   (`adapter_versions = 0`), and probe_evaluate cannot run beside a loop. At `:295`, `rollback_window_phases = 4` is
   an automatic recipe change; the design proposes 0. Set both, and leave a note if the owner reverses the rollback.
3. **Probe v2 does not exclude the 16,006 statements grpo_loop_v1 searched.** Scratch `old_run_overlap.py` finds that
   23.5% of the usable pool was searched (21-27% per band) and about half of those were proved.
   - Why it matters: expect ~470 of the 2,000 probe statements to be ones whose trees trained the old final value model,
     and whose solved trees trained v35 (GRPO, expert-iteration round 1). That contaminates step 1 run 5 (Q4's "final")
     and runs 7-9, and the probe is fixed once drawn.
   - Fix: add a fourth reason to `fixed_sets.Exclusions` (`fixed_sets.py:222`), "searched in grpo_loop_v1", read from
     `search_trees/index.jsonl` and counted per band. Supply is ample: the 500-999 band has ~4,800 unsearched
     statements against the 250 it needs.
4. **`probe_evaluate.py` swaps weights into whatever servers listen, with no guard.** See `serve` (`:97-126`).
   - Why it matters: a second invocation, or a running arm (any `RUNS/<arm>/loop.pid`; `loop_config` names `base.toml`,
     not the arm), swaps the policy mid-run. The rest of the first run is then searched by another checkpoint and
     recorded under its label, and nothing detects it. A stopped loop's parked trainer or sleeping servers (mid-pause)
     can make the wake fail. After a probe run, `grpo_evaluate.py` (miniF2F at an arm's end) assumes the servers hold
     the loop's current version.
   - Fix: hold an exclusive `fcntl.flock` on `CHECKPOINTS/<output>/serving.lock` for the whole run. Refuse while any
     `RUNS/*/loop.pid` is live, as `loop_services.stopped_loop_refusal` does. Write a node-wide `served.json` (adapter
     paths and content hashes) and have `grpo_evaluate.py` refuse on a mismatch.
5. **The merge cache is keyed by the adapter's path string and never deleted.** See `probe_evaluation.py:109` and
   `MergedPublisher.merged_weights` (`serving.py:232`: the marker exists, so the merge is reused).
   - Why it matters: an adapter rewritten at the same path is served from its stale merge without a word. That happens
     when an arm is rerun under its name after a bug fix (the design's "fixed and every affected arm rerun"), or when a
     step-2 round is rerun into one directory. WP0 also requires deleting the merge after use (~13.5 GB per checkpoint;
     the study evaluates 20+).
   - Fix: key the directory by a hash of `adapter_model.safetensors` and `adapter_config.json`, store that hash in the
     marker and compare it. Delete the merges after the run (or keep the last one).
6. **The wall-stop rule is 5%; the design requires under 1%, reported by stratum.** See `probe_evaluation.toml:12`,
   the 0.05 default and `accepted = share <= max_share` (`probe_evaluation.py:126`). Fix: 0.01 and a strict `<`, with
   stops per stratum in `run.json`. Correct the README line that says 5%.
7. **The ratings would pool different checkpoints.** `probe_rating.probe_ratings` groups runs by `policy_version`
   alone. probe_evaluate writes every run to one `probe_evaluations/`, and its docstring says `finished_probe_runs`
   "rates them all".
   - Why it matters: v0 with value v0, final (run 5) and none (run 6), and the frozen-policy reference (v0 with the
     arm's value), all become the anchor "version 0". Arm A phase 8 and arm B phase 8 merge into one version.
   - Fix: give each (arm, value mode) its own output (a `--output`, or derive it from the name). Also refuse a run
     whose (policy_version, value_version) already belongs to another checkpoint in the same output. Fix the docstring.

## Should

8. **`--value none` changes only the priority kind** (`probe_run_config`). It keeps the A* template's
   `automation_log_probability = -1.0` (`visible_student_v2.toml:61`), while the decided configuration is row 2's
   (-2.8, `gate_search.toml`) until WP2 recalibrates it. Instead of rewriting the kind, refuse `none` unless the search
   config is already value-free.
9. **`[probe] max_expansions = 16` overrides any `--search-config`** (`evaluation_run_config`). Runs 3 and 4 (up to
   1,024 expansions with a token cap) would quietly run at 16. Take the budget from the given search config, or refuse
   when the two disagree.
10. **The guard as a measurement.** On the old data, against brute force on 2,000 sampled candidates, LSH caught 57 of
   the 60 with estimated Jaccard >= 0.7 (95%) and all 73 exact root matches. 4.3% of candidates sit at 0.6-0.7. 18% of
   training proofs (20.6k of 118k) have no step-0 record, and their earliest state adds 59 drops (+2.8%) to the 2,127
   (3.1% of the pool). The theorem-form rewrite is sound (pool roots and training goals share the printer and
   numbering). Cheap nets:
   - compare signatures by brute force for the drawn set plus a reserve (~30 s) instead of LSH alone;
   - use each proof's earliest record, not only `step_index == 0` (`training_overlap.py:43`);
   - list the pairs at 0.6-0.7 in `selection.json` for a look;
   - refuse a `--training-data` directory that is missing or yields no roots (`rglob` on a missing path is silently
     empty), and record roots per directory and the dropped names.
11. **Twins inside the pool.** 2.1% of pool statements have another pool root at estimated Jaccard >= 0.7 (0.3% with
   an identical root), because the pool's dedup was by statement with LSH. So ~40 probe statements have a twin that
   every arm's curriculum can feed. Write those names to a held-out file and list it in `statements.held_out`.
12. `[health] reference_phases = 2` (`base.toml:278`); the design wants 1 (each arm's own phase 1).
13. `run.json` lacks the node, Lean and vLLM identity the design requires. `--value PATH` is stored as typed, so a
   relative path changes the merge key and the resume check with the working directory; make it absolute
   (`probe_evaluate.checkpoint`).

## Minor

14. Small items: the comment at `base.toml:207` is stale ("6 x 11 probe runs, 40 miniF2F"). The curriculum bins read
   "0-5" ... "45+" in hundreds of characters while the band chart says "number"; label the unit.
   `strataRank("unknown")` is NaN in `app.js`. `initial_band_low` is not validated. `CharacterSelectionRecord` lacks
   the pool's hash and the commit. The off-target alert pools the below-band feed (pre-existing).

**Regressions: none found.** Old sets read back as strings. `stratum_order` keeps the old order of the named strata and
of the default bins, and the dashboard still shows easy, medium, hard. The default-edge labels are unchanged, and the
golden tests pin the old selection.

## Tests

No test imports `experiments/probe_evaluate.py`, and no test covers the 12-part schedule or the config load guards.
Add first a fake-server test of `serve` across three runs (policy and value, then `--value none`, then the first
again). It should assert which weight directory each server received, that a rewritten adapter at the same path forces
a new merge, and that a second checkpoint under one name is refused. Then a `select_characters` test on real record
shapes (sft `step_index`, value `depth`) with one directory missing.

Verdict: **merge after fixes 1-7**. Fix 3 must land before `select-by-characters` runs on the node.

## Re-review (27eef46, d897212, 1f7f3f7)

Tests: 759 passed (`tests/rl` loop, rating, probe, fixed sets, overlap, configs; `tests/expert_iteration`). The pool
digest in the configs equals the published `verified.jsonl`'s sha256.

**Earlier findings:**
- 1 resolved: nothing runs beside sampling, there are no probe or miniF2F baselines at start, the held-out states are
  due every 0.01 h (so at every pause) with v0's baseline at the pause's 56, and the placeholders are marked.
- 2 resolved: `adapter_versions = 0`, `rollback_window_phases = 0`.
- 3 resolved: `--old-run-index` is required and is the second exclusion, counted per band.
- 4 partly: the lock and the loop check run before and after the search, but no loop honours `serving.lock` (finding B).
- 5 resolved: merges are keyed by base and content digest and deleted after the run.
- 6 resolved: strictly under 1%, stops per stratum, and rejected runs are never rated.
- 7 partly: runs are pooled by identity now, but see findings A and C.
- Should items resolved: row 2's value-free constants, `--search-config` brings its own budget, earliest state per
  proof, missing training directories refused, brute-force check of the drawn set, pool twins held out,
  `reference_phases = 1`, node, toolchain and version identity in `run.json`.

**New problems:**
- **A, should (before step 1's runs 3 and 4).** `ProbeCheckpoint.identity` leaves out the search config. Runs 3 and 4
  (same adapter, same value v0, both capped at 1,024 expansions; visible vs no reasoning) pool as repeats of one
  checkpoint, and so would any other search variant at 16 expansions. Add `run_config_sha256[:12]` or the search
  config's name to the identity.
- **B, should (before step 1).** `grpo_loop.py run` and `grpo_loop.sh` ignore `serving.lock`. A loop started during a
  probe evaluation makes the after-check exit without writing `run.json`. Rerunning the same command then resumes, keeps
  the statements searched under the loop's weights, and records the run as accepted. Fix: the loop refuses while the
  lock is held, and the after-check marks the directory spoiled.
- **C, should.** The rating's anchor is the lowest (phase, identity) as a string. Within phase 0, "no value model" sorts
  before "value ...", and any arm name below "v0" (uppercase, or "step2_...") sorts first too, so v0 without a value
  model or a step-2 variant becomes the anchor. Name the anchor explicitly (arm v0 with value v0).
- **Minor.** `--search-config` naming the default file switches the budget to that file's 64 (recorded, then dropped by
  the rating's budget filter). The held-out states also run at every restart (`due_now`), which costs only time.
- **(c) Phase end.** With 56 searches, the groups still pass 300 long before 75 min, so the minutes end each phase as
  before. A phase then holds about half grpo_loop_v1's tokens, unequal across arms until WP1. A pause now waits for the
  held-out states' whole Lean tail at 56 REPLs.
- **No early resume.** `early_resume_valid_fraction = 2.0` holds only while v0's held-out valid rate stays above 0.5
  (the floor is 2 × v0's; it was 0.57 on the old node). The first arm needs no code: set it to 100 (nothing validates
  an upper bound). A boolean switch can come later.

Verdict: **merge**. Fix A and B before step 1's probe runs and C before the first rating of step 1.
