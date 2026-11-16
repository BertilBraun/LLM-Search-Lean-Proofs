# Review AQ: start order by expected search seconds, code

Branch `worktree-agent-a8257711895071364` (68e70fe). WSL: `test_submission_order.py` and the `test_probe_*` files,
**191 passed**. I checked the TSV directly: 2,000 statements, each the mean of 5 runs, 7 header lines, the probe v2
digest in its header, values 6.5 to 6,587.5 s, 287 ties at 0.1 s. Not run: a node.

## Unchanged from yesterday's checks (still hold)

The pilot is taken in file order before the ordering (`evaluate` l. 307-316), and `started` is passed only to
`run_problem_set_evaluation`. `stops_by_stratum`, `dropped_statements` and `lean_loads` still get the file-order
`problems`, and `stratum_outcomes` sorts. Nothing is seeded or assigned by position: exploration is seeded by name,
policy sampling is unseeded. Resume runs `pending_problems` in the current order, results are keyed by name, and the
identity (`ProbeRunStart`) is untouched.

## Must fix before merge (before this deploy)

- **M1. Turning the order on stops the chain at the finished pilot.** The pilot `step1_run4_pilot_no_reasoning_T_cap14400`
  and the full runs 3 and 4 share `step1/token_capped_evaluation.toml` (`runs_reasoning.toml`). `probe_runs.next_run`
  (l. 84-87) checks `start_mismatches` for every run *before* `run_state`, accepted ones included. The pilot's first
  session reads as `file` (no field, so the default). If the operator turns the order on in the shared config, the
  list "asks for" `longest_expected_search_first` for the pilot too, and `next` exits 1 ("Stopped before the next
  run"). So the plan "pilot in file order, runs 3 and 4 in the new order" fails as soon as the pilot finishes.
  - Fix in code: compare the start order only for a run that will be resumed (`RunState.PENDING`). An accepted run
    is only skipped, and the order is not part of the identity. Test this case: an accepted file-order run in a list
    whose config now orders.
  - Fix for the operator (also fine on its own): a new config `step1/token_capped_evaluation_ordered.toml` with
    `base = ".../token_capped_evaluation.toml"`, `submission_order = "longest_expected_search_first"` and
    `expected_search_seconds = ".../probe_v2_expected_search_seconds.tsv"`, and only runs 3 and 4 pointed at it in
    `runs_reasoning.toml`. That works with this commit unchanged: the chain re-reads the list at every `next`, and
    runs 3 and 4 have no record yet.

## Should fix

- **S1. Validate the file on the pilot before trusting the order (zero cost).** The TSV comes from 16-expansion,
  7,200 s-cap runs, value and value-free. Runs 3 and 4 are token-capped searches with a 14,400 s cap. Compute the
  Spearman correlation between the pilot's recorded `wall_seconds` (200 statements, no reasoning) and the TSV. If it is
  well below the 0.79 between runs, the gain is smaller than simulated. Outcomes are not at risk either way.
- **S2. The key is biased by contention.** In file order the last wave is the longest-proof band, and it ran with fewer
  co-runners, so its recorded seconds understate full-load time (up to about 1.4x for the last ~112 statements). The
  mean over 5 runs, including value-free runs whose searches have no value server to wait for, dampens this. It only
  costs packing (some long searches start a little later), never correctness. A file regenerated from ordered runs
  moves the bias to the new tail (short searches), where it is harmless.
- **S3. An ordered v0 run pools into the anchors in `probe_rating`.** The order is not in the identity, so a
  validation repeat of v0/value v0 joins the anchor pool automatically. That is wanted only once it has passed: give
  it a non-anchor arm label until then, or have `probe_rating` print each pooled run's order.
- **S4. Stale or other file between the paired runs.** The digest is fixed per run, but not across runs. A `git pull`
  that changes the TSV between run 3 and run 4 gives them different digests, and only `probe_compare`'s "orders
  differ" line shows it. `check` also tests only that the file exists. Fix: have `check` read the file
  (`read_expected_search_seconds` against the probe set's digest), and refuse a list whose runs would differ in order.

## Minor

- `expected_search_seconds_text`: the header lists the runs in argument order, so regenerating with the same runs in
  another order gives another digest. Sort the runs by name.
- `planned_start_order` raises a ValueError traceback in `next` for a config that sets a file with
  `submission_order = "file"`. `probe_evaluate` turns it into a clean message; do the same here.
- A server restart's session inherits the run's order (`ProbeServers`), which is right. A spoiled first session still
  fixes the run's order, which is also right.
- Old directories read everywhere: `ProbeSession.start_order` and `ProbeRunRecord.start_orders` have defaults, and
  `probe_compare` and `probe_rating` pass on the old records. A finished run in a file-order config still matches in
  the launcher, because a missing order reads as `file`.
- Resuming in another order or with another file is refused before pinning or serving, `--allow-other-order` is
  recorded per session, and `probe_runs.sh` never passes it. So mixing inside a run can only be deliberate, and that
  resolves yesterday's M1.

## Operator checks

- **Before trusting runs 3 and 4 as a pair:** in each run directory,
  `jq -c '.start_orders' run.json` must print the same one-element list, `longest_expected_search_first` with the same
  `expected_search_seconds_sha256`. `jq -c '[.start_order, .other_order_allowed]' sessions.jsonl | sort -u` must
  print exactly one line, ending in `false`. That sha must equal `sha256sum` of the TSV at the deployed commit. Then
  `probe_compare.py pair` must print no "orders differ" line, and the two Lean-load rows should be similar.
- **Single validation run:** v0 with value v0 at the standard settings (16 expansions, 7,200 s cap,
  `probe_evaluation.toml` plus the order and the TSV, not `--anchor`), paired against `step1_run1` and `step1_run2`.
  It passes if its difference to each anchor is within their A/A difference and its Lean-load table matches theirs.

**Verdict: merge after M1** (the code fix or the separate config; deploy only with one of them in place).

## Re-review (2026-11-16)

193ce6e and eb422ce. WSL: `test_submission_order.py`, `test_followup_step1.py` and `test_probe_runs_script.py`,
**116 passed**. **Verdict: merge.**
- **M1 resolved.** `recorded_mismatches` compares the order only when `run_state` is PENDING. Covered by the tests
  `test_a_finished_run_in_another_order_does_not_stop_the_list` and
  `test_an_unfinished_run_in_another_order_still_refuses_to_resume`. The identity is still compared for every run.
- **The config is right.** `token_capped_evaluation_ordered.toml` is based on `token_capped_evaluation.toml` and
  adds only the order and the TSV. Only runs 3 and 4 use it; the pilot keeps file order (both pinned by
  `test_followup_step1`). Runs 3 and 4 have no record yet, so a deploy mid-chain picks them up at the next `next`.
- **S4 partly resolved.** `missing_files` (`check`) now reads the TSV against the probe set's digest, and more than
  1% uncovered is refused at start. Two runs of one list with different digests are still only flagged by
  `probe_compare`, so the operator check stays.
- **S1 still open**, an operator step: rank-correlate the pilot's `wall_seconds` with the TSV before trusting the
  gain. **S2** is accepted as documented. **S3 still open**: an ordered v0 repeat would pool into the anchors.
- **Minors resolved:** the header is sorted by name, so the committed TSV's moved header line is that sort and the
  file is reproducible; the ValueError in `next` is now caught. The TSV's new digest does not matter, since no run used
  the old one.
- **New finding, should:** the README's out-of-sample figures show Lean demand of 102-110 cores on 96 CPUs in the first
  30 minutes, with the longest searches run together. Runs 3 and 4 share that pattern, so the pair stays fair. But
  their acceptance (under 1% wall-clock stops; the cap-7,200 pilot was rejected at exactly 1.00%) is now tested under
  more pressure on the long searches. Watch the wall-clock-stop share and the Lean-load table of run 3 early. The
  14,400 s cap gives about 2x headroom over the longest mean (6,587 s).
