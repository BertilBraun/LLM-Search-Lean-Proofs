# Review BU: miniF2F-valid fixed set and its five evaluation runs (code)

Under review: the uncommitted working tree of 2026-11-24, i.e. `minif2f_valid_set` in
`src/lean_search/rl/fixed_sets.py`, `experiments/minif2f_valid_set.py`,
`experiments/configs/grpo/followup/minif2f/*.toml`, `tests/rl/test_followup_minif2f.py` and the additions to
`tests/rl/test_fixed_sets.py`.

Verified by running:
- the builder twice into a scratch `$LEAN_SEARCH_DATA` (WSL), at the default output and at another path, then a
  third time over the existing file. All three gave sha256
  `bee5a77dc1a7c19f603a8d202f52bcd67f5e3b26010eb8c619902835af2b029c`, the pinned value. The rerun kept the file.
  Counts: 244 statements, amc12 45, mathd_algebra 70, aime 15, mathd_numbertheory 60, induction 8, imo 20,
  numbertheory 8, algebra 18.
- the data: 244 valid names, all unique. None contains `/` or `.`, so `problem_name` keeps them as they are. No name is
  shared with the test split, and no statement body (theorem name dropped) is either. One header for all 488 problems.
- `pytest tests/rl/test_followup_minif2f.py tests/rl/test_fixed_sets.py`: 55 passed. `ruff format --check` and
  `ruff check` on the four Python files: clean.

## Blockers

None.

## Correctness checks that hold

- **No test statement can be included.** `fixed_sets.py:298-300` refuses any problem whose split is not `VALID`. The
  builder loads `Split.VALID` only. `test_fixed_sets.py:241` passes all 488 problems and expects the refusal.
- **The header matches what the REPL and grpo_loop_v1 used.** Each record keeps miniF2F's own header (`import Mathlib`,
  `Aesop`, `maxHeartbeats 0`, `open BigOperators Real Nat Topology Rat`). `HeldOutStatement.problem`, through
  `pool_problem`, passes that header and the formal statement unchanged to the search. The REPL builds one environment
  per header (`lean/repl.py:918-928`), which is how the old loop searched `load_minif2f` problems
  (`rl/fixed_targets.py:177`).
- **Fields that differ from the old loop do not matter.** The search reads only `informal_prefix` and `goal` from
  `Problem`, and it never uses either, so dropping them in `pool_problem` changes nothing. Statement renaming is off in
  both the old and the new loop config.
- **Names.** Problems are named `minif2f.<name>` (`problem_name`). The theorem name inside `formal_statement` is
  unchanged. `problem_source` now returns `minif2f` instead of `other`. Nothing on the evaluation path reads it, and the
  separate output directory (`minif2f_evaluations`) keeps these trees away from the probe readers that list
  `probe_evaluations`.
- **Strata.** `category` puts `mathd_algebra` before `algebra` and `mathd_numbertheory` before `numbertheory`, so the
  prefixes do not overlap wrongly. `stratum_order` sorts these unnumbered labels by name, as it does `easy` and
  `medium`.
- **Run lists.**
  - All five pass `run_refusals`: no placeholders, `value_version` given for value paths, concurrency 112 as the study
    uses.
  - The v0 run's `anchor = true` satisfies `anchor_problem`: base.toml's `[initial]` policy, value v0, phase 0, no
    pilot.
  - Arms C and D publish `expert_iteration/adapter` after the GRPO step (`arms_chain.py:567` and its "GRPO then the
    round" check). F's policy is `policy/adapter`.
  - With `value_every_phases = 2`, phase 16 has a value adapter.
- **Evaluation config.** `test_followup_minif2f.py:34` pins the config to the probe's except for the set, the output,
  64 expansions and 3,600 s. That is the right guard against drift. The 64 expansions and 3,600 s cap match
  grpo_loop_v1's `[evaluation.minif2f]` (`experiments/configs/grpo/loop.toml:242-245`), so the comment's claim holds.

## Should-fix

### S1. The inherited 1% wall-clock rule will probably reject runs at a binding 3,600 s cap, and the remedy conflicts with the maintenance window
`experiments/configs/grpo/followup/minif2f/minif2f_evaluation.toml:1-11`, inheriting `max_wall_clock_stop_share =
0.01` from `probe_evaluation.toml`.

A run is rejected (exit 3) once 3 of the 244 searches stop on the wall clock (2.44 is 1%). The documented remedy is
"repeated with the cap doubled", which the owner's one-hour maintenance constraint rules out.

The cap is likely to bind:
- The old runs used 3,600 s at 56 REPLs, and v0's baseline at 40.
- These runs use 112 REPLs (forced by `run_refusals`). The study's throughput test gives about 14.6k expansions/h at
  112, which is about 130 expansions/h per search. A search that uses all 64 expansions then averages about 30 min.
- About 30% of the set goes unsolved (v0 160/244), and those searches run all 64 expansions. Lean-heavy hard
  statements and later checkpoints have tails well past the average.
- At 16 expansions the probe keeps 7,200 s as an emergency stop. At 64 expansions, 3,600 s is a real budget.

Fix: decide explicitly. Either set `max_wall_clock_stop_share` in this config, with the reason (for example, report
cap stops as unsolved and compare runs at the same cap), or say in the comment what happens when a run is rejected.
Without that, a rejection mid-sequence leaves the remaining runs of `probe_runs.sh` waiting on a decision.

### S2. The comment says the cap bounds each run to about an hour; it bounds each search
`minif2f_evaluation.toml:4`.

`max_wall_seconds` applies per statement. With 244 statements on 112 slots, one run can last up to about three caps
back to back (about 3 h), plus serving and merges. The five runs together take several hours. The comment as written
misleads anyone scheduling around the node's maintenance. Reword it to "bounds each search" and give the expected
run length.

### S3. Nothing in the repository guards the pinned sha256
The pinned digest appears in no committed file (a grep of the repository finds none). If `to_json`, a
`StatementRecord` field, `category`, `HeldOutStatement` or `data/minif2f/minif2f.jsonl` changes, the node's rebuilt
file stops matching the launch script, and no test catches it first.

Fix: add a test that writes `minif2f_valid_set(load_minif2f(Split.VALID))` to `tmp_path` and asserts `file_sha256` ==
`bee5a77d…029c`, or record the digest next to the config. One portability catch for such a test:
`Path.write_text` turns `\n` into `\r\n` on Windows (`fixed_sets.py:316`). The digest therefore reproduces only on
Linux/WSL, where the builder and the test suite run. Passing `newline="\n"` would make it platform-independent and
changes nothing on Linux.

## Notes

- **N1. The stale `stratum` comment** (`fixed_sets.py:45`). It says the stratum is "A `Stratum`, or a character band".
  It can now also be a miniF2F competition (`amc12`, ...). Update it.
- **N2. Placeholder fields** (`fixed_sets.py:302-308`). `difficulty = 0.0` and `lean_version_hint = ""` are
  placeholders. Harmless, since nothing on the probe path reads difficulty, but `0.0` looks measured.
- **N3. Return type** (`fixed_sets.py:296`). `minif2f_valid_set` returns a `list`, while the other selectors return
  tuples. Minor inconsistency; `write_fixed_set` takes any `Sequence`.
- **N4. `ValueError` versus `assert`** (`fixed_sets.py:299-300`). The caller is internal, so CLAUDE.md's rule could
  argue for `assert`. Keeping `ValueError` is defensible: a public selector refusing contaminating input is a guard at
  the data boundary, and the test depends on it. No change needed.
- **N5. Comparing with the references** (`minif2f_evaluation.toml:2`). The old references (v0 160, v35 170) were
  searched beside sampling at 40/56 REPLs and under bare names (`amc12a_2019_p21`). The new runs are standalone at 112
  under `minif2f.amc12a_2019_p21`. A paired comparison (McNemar, as in `results/grpo_loop_v1/README.md:77`) needs the
  prefix stripped, and wall-clock-dependent outcomes are not like for like. Worth one line in the comment or the
  write-up.
- **N6. Checkpoint identity cannot be checked from the repository.**
  - `runs_v35_value_final.toml`: is `hf_value_latest` the value model v1's v35 miniF2F run searched with? v1 used the
    published value, retrained every second phase, so at v35 it would be v34's unless one was published later.
  - `runs_F_phase16.toml`: the path depends on the F screen having been extended to 16 phases.
    `screens/F_2e-5.toml:11` still says `max_phases = 8`, while `arms/D.toml:4` says F ran 16.
  - `missing_files` catches a missing directory at launch, but not a wrong phase.

  Confirm both on the node before the runs.
- **N7. The tests' `toml` helper** (`test_followup_minif2f.py:16`). It duplicates `probe_run_list.read_toml` and
  `test_followup_step1.toml`, and returns a bare `dict`. Reusing `read_toml` would drop it.
- **N8. A possible extra test** (`test_followup_minif2f.py`). One test could assert that the union of the five lists
  passes `interleaved`, so names are unique across lists. Today only the launch catches a duplicate.
- **N9. The cap differs from base.toml** (`test_followup_minif2f.py:46`). base.toml's own `[evaluation.minif2f]` keeps
  `max_wall_seconds = 7200.0`, while this config uses 3,600, and the test compares only expansions. The difference is
  deliberate per the comment; noted so nobody "fixes" one to match the other.
- **N10. Style is otherwise clean.**
  - Names are spelled out, type hints are present, and the docstring is one line.
  - The tests call production code directly with one assertion each, and the config tests are parametrized.
  - Ruff is clean.
  - The builder never replaces an existing different file (`minif2f_valid_set.py:30-32`), as the other fixed-set
    builders do.

## Re-review (2026-11-24)

Checked the fixes in the working tree. In WSL, `test_followup_minif2f.py` and `test_fixed_sets.py` give 56 passed,
and `ruff format --check` and `ruff check` are clean on the four Python files. **Nothing blocks.**

- **S1, resolved.**
  - `minif2f_evaluation.toml` sets `max_wall_clock_stop_share = 0.05`. Its comment says a stopped search counts as
    unsolved and that the stops are reported. It also gives the reference runs' stops: 5 and 3 of 244 (2.0% and 1.2%;
    the arithmetic checks out, the counts I could not verify locally).
  - The renamed config test pins the value.
  - The 5% threshold allows 12 stops. That covers the references and leaves room for the doubled load at 112 REPLs.
- **S2, resolved.** The comment now says "3,600 s per search", and the claim of about an hour per run is gone.
- **S3, resolved.**
  - `write_fixed_set` writes with `newline="\n"`.
  - `test_the_written_minif2f_valid_set_has_the_hash_the_node_checks` writes the set to `tmp_path` and asserts the
    pinned sha256. It passes.
  - Every existing fixed set's hash is unchanged on Linux. With the default `newline=None`, Python translates `"\n"`
    to `os.linesep`, which is `"\n"` on Linux, so the bytes are identical. I confirmed it empirically in WSL: the old
    `write_text` call and the new `write_fixed_set` give the same digest (`bee5a77dc1a7c19f…`).
  - On Windows the digest now also reproduces, where before it would not have.
- **N1, resolved.** `fixed_sets.py:45` now names miniF2F competitions.
- **New notes, not blocking.**
  - `fixed_sets.py`, `test_fixed_sets.py` and `test_followup_minif2f.py` have CRLF line endings in the working copy;
    the untouched files are LF. With `core.autocrlf = input`, `git add` converts them to LF, and the diff is clean
    (+72/-4), so this is harmless. Check the committed blobs are LF.
  - The new test comment cites this review file, and the config comment cites "review BT". CLAUDE.md asks for no
    task or review references in comments. The repository already does this elsewhere (`probe_evaluation.toml`'s
    "review AF"), so it is a style note only.
  - N2-N9 stand as written. N6 (the v35 value model's identity and F's 16 phases) still needs a check on the node
    before launch.
