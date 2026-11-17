# Review AX: the offline arm (branch worktree-agent-af3691747bca0ee5a, 58454ab on dca9a1f)

**Verdict: no blocking defect; mergeable after the should-fix items, of which S1 and S2 change how the results read.**
The data path does what the owner decided. The recovered proofs are the pool's verified ones (65,585 of 65,585
recovered, 11 ambiguous). Every held-out set entry is dropped by name (2,936 = 501 + 402 + 2,000 + 33). Examples are
rendered and executed by the search's own functions, the matched subsample is equal per band by construction, and the
gate statistic is the stratified paired interval used in the rest of the study. What follows changes what the numbers
mean more than whether the code runs. Tests: 169 passed and 5 skipped (Lean, on the PC) across the offline,
expert-iteration-data and chain tests; `tests/search` 167 passed; `ruff check` and `ruff format --check` clean.

Node evidence (read-only, 2026-11-17 ~11:10 UTC): `preparation.json`, `walk.log` (5,500 of 65,585 walked, 5.2/s), the
first 2,000-3,000 lines of `walks.jsonl` joined to `proofs.jsonl` by name.

## Blocking

None.

## Should fix

**S1. The rate choice's held-out "success" counts against blocks that stop inside a nested proof, which is what this
training teaches.** `experiments/rank_learning_rates.py` → `rl/single_step.sample_success` (single_step.py:231) counts a
sample as successful only when its block ends proved or on a state in `ReasoningState.reference_goal_keys`
(reasoning/states.py:34). Those are the states after the traced proof's *top-level* steps. The 512 states' `previous_steps`
on the node hold whole `have … := by …` blocks as single steps. The offline examples cut the *flattened* proof at random
k (offline_walk.py:101, 119). Often the cut falls inside a nested `have` proof: the walk's own sample
`have h_main : …\nrw [Nat.fib_gcd]\n<;> simp …` ends there. Such a block is valid but ends on a state with the `have`
goal still open, which is never a reference state.
- *Failure scenario:* the better-trained rate (more of the random-cut format) scores lower on held-out success. The
  rule then picks it less often, and on a tie it picks the lower rate anyway (rate_ranking.tie_break). The ranking is
  biased toward 5e-5 for a reason unrelated to search quality.
- *Fix (owner's call):* show held-out valid Lean beside success in the chain log line (already computed). Do one of two
  things: rank on a block-agnostic success (the block's end state lies on the flattened reference path, or is the
  reference state reached by a flattened prefix), or state the bias in `rank_<subset>.txt` and the progress note. The
  probe run stays the decisive measure. At least say so wherever the choice is reported.

**S2. Walk survival falls steeply with proof length, and nothing in the build output shows it.** Joining the first 3,000
walks to their pool characters gives these failure rates by probe band (0-499 … 4,500+): 1.9%, 6.8%, 8.1%, 11.4%,
14.5%, 16.4%, 26.5%. About 80% of the failures are 50k-heartbeat timeouts (`whnf`/`isDefEq`/`elaborator`), the rest
`simp` failures, 60 s wall stops (9/2,000, load-dependent at 90 REPLs), revisits and a few cut constructs.
- *Effects:*
  - O1's band mix shifts toward short proofs relative to the pool.
  - Within the long bands, both subsets lose exactly the heavy-tactic proofs (big `nlinarith` hint lists, kernel
    reductions). Those are plausibly the hard probe statements' neighbours.
  - A failed walk also discards its valid prefix. These are real search transitions: the steps before the heavy
    tactic run fine at the search's limits.
- Dropping these proofs is consistent with the search: the policy could not use the heavy tactic at 50k either. It is
  still a selection the write-up must state.
- *Fix:* add per-band walk statuses to `BuildSummary`/README (offline_arm.py build, around line 526). Decide with the
  owner whether failed walks keep their prefix examples (see Questions).

**S3. The central claim ("each example is exactly what the search's no-reasoning policy sees and would emit") is true
today by inspection but no test pins it.**
- Today `tokenize_example` (sft_data.py:192) renders `render_prompt(tokenizer, goals)` with no lemmas, no few-shot, no
  thinking, not visible and no failed automation. The probe search config matches: `few_shot = false`,
  `thinking = false`, `visible_reasoning = false`, and `failed_automation_in_prompt` defaults to false.
- The walk's tactic limits come from `no_reasoning_student_v2.toml`, the probe's from `search_no_reasoning_16.toml`.
  They agree today on heartbeats 50k, timeout 60 s, flatten, naming, identifier check, forbidden steps and
  `policy.max_tokens` 1024. `test_offline_configs.py` ties the walk config to the mode and the probe config to run 4,
  but nothing ties the two to each other.
- *Failure scenario:* someone edits one file (raises heartbeats in the mode, turns on `failed_automation_in_prompt` or
  lemmas for the probe), and the training prompts or the walked limits silently stop matching the evaluation.
- *Fix:* three tests.
  1. The `walk_settings` fields derived from the walk config equal those derived from `PROBE_SEARCH`.
  2. `tokenize_example`'s prompt equals the expander's `render_prompt` call under `PROBE_SEARCH`'s policy config.
  3. `parse_sample` of `block + "\n```"` (finish reason stop) returns the block.

**S4. `build` holds the leakage- and size-relevant logic and has no test** (experiments/offline_arm.py:483-543). This
covers the validation split (`is_held_out` per statement), cross-proof deduplication (shared between train and
validation), the prompt cap, drawing the matched subset from train only, and the tokens counted for the 2M target.
- *Failure scenario:* a later edit moves the split after the matched draw, or dedups per subset, and validation
  statements leak into training. No test would fail.
- *Fix:* move the pure part (walks → `ProofExamples`, split) into `rl/offline_arm.py`. Test four things: no validation
  statement in either subset, matched ⊆ pool, duplicates counted once, an over-cap prompt dropped while its proof's
  other examples stay.

**S5. The gate pairs on the intersection of statements without checking that the runs are comparable at all.**
`offline_report.paired_difference` (offline_report.py:52-66) uses `common_problems`. It does not call
`check_comparable(..., across_settings=True)`, which would check the probe set and one identity per arm, and it does not
require the full 2,000.
- *Failure scenario:* a resumed or mislabelled run on another probe set, or a run missing statements, yields a gate
  verdict on a subset. Only the statement count in the first line hints at it.
- *Fix:* call `check_comparable([x, y], across_search_modes=True, across_settings=True)`. Make the gate refuse (or say
  "not evaluable") unless all 2,000 probe v2 statements are common.

**S6. O1's training holds every token on every rank as Python ints; the size has not been checked.**
`run_training` (offline_arm.py:629-635) tokenizes all offline examples and the replay on each of the 4 ranks into
`tuple[int, ...]`.
- *Estimate:* the operations note's ~565M tokens per O1 run, at about 36 bytes per token id (a 28-byte int object plus
  an 8-byte tuple slot), is ~20 GB per rank, so ~80 GB for 4 ranks. Add ~2 GB per rank of goal strings and the CUDA
  host side. The node has 251 GB; the 90 REPLs and the servers are stopped by then, so it probably fits, but no run this
  large has used this path.
- *Fix:* print the dry run's peak RSS (`resource.getrusage`) in its last line. The dry run is the same tokenization in
  one process. Have the chain stop if 4 × RSS approaches the free memory. Storing ids as `array('l')` would cut this
  roughly fourfold if needed.

## Nits

- **N1.** `experiments/offline_arm.py:520`: "Training blocks by tactics" counts every block of a train proof, including
  ones dropped as duplicates or over the prompt cap. Count the kept examples. `min(block.tactics, max_block_tactics)` is
  redundant (count ≤ max by construction).
- **N2.** `experiments/offline_arm.py:491-512`: deduplication runs over all proofs in walk-hash order before the matched
  draw. A matched proof can lose an example to an earlier proof that is not in the matched subset (near-duplicate
  statements from the two corpora share states). This is small, but the matched subset then has slightly fewer distinct
  transitions than its proofs hold. Dedup again within matched, or draw before dedup.
- **N3.** `rl/offline_arm.py:324` `hash_order(seed, name)` duplicates `rl/fixed_sets.hash_order(name, seed)` with the
  arguments swapped (same hash). That is a trap for the next caller: reuse the existing one.
  `rl/offline_walk.first_line`/`MAX_FAILURE_CHARACTERS` duplicate `expert_iteration/known_proofs`.
  `experiments/offline_arm.py:409` hard-codes `[:300]`.
- **N4.** `rl/offline_arm.recovered_candidates` reimplements phase 2's cap order (`short_hash(key + proof_key)`) instead
  of calling `corpora/pipeline._deterministic_order`/`cap_proofs_per_statement`. It is correct today (100% recovered),
  but the two can drift.
- **N5.** `offline_report.within_budget` (line 30) sets `proved=False` but leaves `end=SearchEnd.PROVED`. The report
  does not read `end`, but anything that later does will be misled. Set it to `EXPANSIONS`.
- **N6.** The walk does not run the search's final `verify_state` on the walked proof. Forbidden tokens cover the usual
  unsound closers, so the effect is likely nil, but the docstring's "exactly as the search" does not hold for the
  proving block.
- **N7.** Proofs walked to more than 64 blocks (the probe's `max_depth`) give examples at depths the search never
  expands. These are rare; count them in the build summary.
- **N8.** Style (CLAUDE.md, HANDOFF section 3):
  - Several multi-line comments and docstrings where one short line is the rule: `rl/offline_arm.py` module docstring,
    `recovered_candidates`, `matched_sample`, `ReplayConfig.repeat`, `WalkConfig` fields, the `offline_walk.py` module
    docstring.
  - `PoolSelection.dropped`/`Preparation.dropped` pass `dict[str, int]` keyed by enum values between functions where
    `Counter[Exclusion]` or a dataclass would be typed.
  - `by_key = {}` (experiments/offline_arm.py:277) is untyped.
- **N9.** `test_offline_walk.py` drives `walk_proof` through a scripted REPL. That is acceptable (the REPL process is the
  external boundary and the file says so), but the real-Lean file is skipped on the PC. Record in the operations note
  that `tests/rl/test_offline_walk_lean.py` was run on the node before the walk.

## Checked and fine

- **Proof recovery.**
  - Phase 2's normalization, within-shard dedup, cross-shard "first by identifier as a string" (pipeline.py sorts by
    `record.identifier`, a string, as `recovered_candidates` does) and the per-source cap in `short_hash(key +
    proof_key)` order are all mirrored.
  - The pool's verification order across sources (`add_proof`: length key, then file order) matches the identifier
    order used for ties.
  - Matching on `(split_top_level_tactics count, len(tactic_proof))` is exactly how `known_proof` recorded them. On the
    node: 65,585/65,585 recovered, 11 with several candidates, 0 missing.
- **Exclusions.**
  - Names via `problem_name`: 2,936 dropped, equal to the four sets' total.
  - States vs statements: the held-out states' `step.formal_statement` is canonicalized like the pool's. Zero dropped
    is expected, because those statements come from traced proofs (goedel validation split), which pool v3 excluded as
    selected for tracing.
  - Near-duplicates use anonymized-token MinHash, exhaustive, with the queries/references order right for both
    `exhaustive_matches` and `exhaustive_duplicates`. The threshold is the probe's 0.7. The held-out states' formal
    statements are included. 30 + 17 dropped.
- **Prompt and completion.**
  - `tokenize_example` gives the system prompt, the user message of the named goals, `enable_thinking=False` and the
    fence prefill, then block + `\n```` + `<|im_end|>`. That is what the expander renders and what
    `parse_sample_block` returns for a no-reasoning sample (stop at the fence, normalized).
  - Prompt and completion are tokenized separately, as at inference.
  - The prompt cap of 7,168 = 8,192 − 1,024. `completion_fits` counts block plus closing fence.
- **Execution.**
  - The walk uses the search's own `named_state`, `identifier_check`, `policy_plan`, `ForbiddenSteps`, the expander's
    forbidden tokens and `apply_block` at the search's per-tactic heartbeats and timeout. The next prompt state is the
    named `result.state`, as `_apply` makes a child. The revisit check mirrors the tree's duplicate check.
  - Early-closing blocks are trimmed to the steps that ran. The 1-5 draw is seeded per statement and identical across
    candidates.
  - Sampled complete walks on the node look right: named root goals; flattened `have h : X` headers followed by their
    tactics; `<;>` continuations at column 0 executed by Lean.
- **Matched subset.** It is round-robin over the seven probe bands in seeded hash order, stops at the first proof
  reaching 2M completion tokens (bands differ by at most one proof), draws from train after the validation split, and
  counts tokens after dedup and the prompt cap.
- **Replay.**
  - `examples_within_completion_tokens` without `repeat` produces the same permutation as before (shuffling indices
    with the same seed). This is pinned by a test, so the expert-iteration arms are unchanged.
  - `repeat` takes every example once before any twice.
  - Shares are by completion tokens of offline + replay, as in the recipe. `plan_steps` shuffles all examples per
    epoch, so the repeats are interleaved.
  - O2 applies 4 epochs to offline and replay alike, keeping the shares.
- **Training config.** `[sft]` equals the expert-iteration recipe (test). It continues v0's adapter, O1 trains 1 epoch
  and O2 4. Validation is 2% of statements, at most 2,000 examples, evaluated at the start, the middle and the end.
- **Rate choice.** `choose_rate` with no gate runs means the held-out states decide, lower rate on a tie. The
  held-out loop config is base.toml in the no-reasoning mode with the same 512-state file (sha checked by
  `rank_learning_rates.read_held_out`). The v0 held-out run is shared, in the same mode.
- **The cut at N.**
  - `expansions_to_proof` is `solved_at.expansions`, incremented before the expansion runs, so a proof in the 16th
    expansion reads 16 and is kept at budget 16. Unproved outcomes are None.
  - Run 8 on the node: 16 expansions, 7,200 s cap, value v0, accepted, so the cut is a no-op for it and for O.
  - Run 4 (token cap) cut at 16 is a fair "first 16 expansions" view: A* order does not depend on the budget. Token-cap
    stops before 16 make it slightly pessimistic, which is fine for a descriptive view.
- **The statistic.** It pairs per statement, pools runs per statement, uses the stratified bootstrap by probe band
  (`arm_comparison.difference`) and passes when the two-sided 95% lower bound is above 0. The report says the settings
  differ and that the verdict is the owner's rule, not `arm_comparison`'s.
- **Refactor.** The search.py extractions (`named_state`, `identifier_check`, `policy_plan`) behave as before.
  `IdentifierChecker.names` exists. `tests/search` passes.

## Questions for the owner

1. **S1:** should the learning rate be chosen on held-out success as defined (which penalizes blocks ending inside a
   nested proof, the offline format), on valid Lean, or on a block-agnostic success?
2. **S2:** a failed walk now drops the whole proof, including its valid prefix (failure rate 2% in the shortest band,
   26% in 4,500+). Should the prefix examples be kept? They are real search transitions, but they lead toward a step
   the search cannot run at 50k heartbeats.
3. **Matched on tokens, not on transitions:** O2's 2M completion tokens of bare Lean blocks are ~67 tokens per example,
   so ~30k transitions from ~2,100 proofs. If the expert-iteration arms' 2M completion tokens include visible
   reasoning, O2 sees several times more states than an arm does. Is "2M completion tokens" the intended match?
4. **No v0 baseline in O's exact search settings** (no reasoning, depth weight 0.1, 16 expansions). Run 4 differs in
   depth weight (0) and budget (token cap), so "what SFT bought over v0" mixes in the depth-weight change. Do you want a
   v0 probe run with `offline/search_no_reasoning_16.toml` (~4-5 node hours)?
5. **Run-to-run noise:** the gate's interval covers statement sampling only, and O and run 8 are single runs at
   temperature 0.8. Should the report also show the anchors' A/A difference (runs 1 vs 2) as the noise floor beside
   the gate?
6. **State-level leakage:** the exclusions are statement-level as decided. Should the build also drop (or at least
   count) training examples whose state nearly repeats one of the 512 held-out states (exhaustive MinHash at 0.7, a few
   minutes)?

## Re-review (2026-11-17)

**Verdict: no blocking defect. Every should-fix is fixed or fixed within a stated limit, and Q5 and Q6 are done.**
Mergeable; the new points below are nits or caveats to state in the write-up. Wave 58454ab..de38cab.

- Tests in WSL: 233 passed and 7 skipped (Lean, on the PC) across the offline, build, report, configs, chain-script and
  expert-iteration-data tests. `ruff check` and `ruff format --check` are clean.
- `git diff 0d663a4..de38cab` over the walk's sources (`offline_walk.py`, `search/`, `lean/`, `policy/`) is empty. The
  walk running on the node (code 0d663a4, 21,500 of 65,585 at 11:59 UTC, 5.3/s) is therefore the walk this code would
  make, and the `walk_record` step's stamping of `walk.json` onto it is truthful.

### Per finding

- **S1: fixed within a stated limit.**
  - What changed: `rl/offline_held_out.flat_reference` runs the reference next step flattened in Lean from
    `state_before` and adds the open states after each flattened tactic to the reference keys. `rank` reports both
    measures, chooses on the flattened one, lower rate on a tie.
  - This is what S1 asked, and it is sound. The extra keys are states on the reference's own flattened path. A
    failed flattening falls back to the standard keys. v0 and both rates are judged by the same keys.
  - Limits (all stated in DESIGN and in `rank`'s output):
    - Only the *next* step is flattened, because the later steps' texts are not in the states file. A block that runs
      past the next step and stops inside the following step's nested proof still counts as a failure.
    - The measure is somewhat more lenient: a sample writing just the reference's `have h : X` header now succeeds.
  - New, pre-existing and minor: 29 of the 512 states have inaccessible names in their goals. The held-out run names
    them at the root, while both the standard and the flattened keys come from unnamed traced or replayed states, so
    samples from those 29 states can rarely match a key. This affects every variant alike, so it does not bias the
    choice.
- **S2: fixed.**
  - `band_walks` gives walk statuses per band in `build.json` and the README. DESIGN states the 2% to 26% gradient.
  - Walks that fail at a block or at a forbidden step keep their prefix (`usable_blocks`, `PREFIX_STATUSES`);
    revisits and goals left at the end still give nothing.
  - Caveat for the write-up: the matched subset still draws equal *proofs* per band, and in the long bands about a
    quarter of them are now prefixes, which contribute fewer transitions. The last kept transition of a prefix leads
    toward a step the search cannot run at 50k heartbeats.
- **S3: fixed.** New tests in `tests/rl/test_offline_build.py` pin three things:
  - The walk config and the probe search agree on heartbeats, timeout, flatten, naming, identifier check, forbidden
    steps, `max_tokens` and tokenizer.
  - The probe search's prompt is bare: no few-shot, thinking, visible reasoning, failed automation or lemmas.
  - An example's prompt tokens equal `render_prompt` under the probe policy's flags, and `parse_sample` of a stopped
    completion returns the block.

  The prompt test re-states the expander's `render_prompt` call rather than calling the expander. That is acceptable
  now that the flags are pinned.
- **S4: fixed.** `split_examples` is pure and tested: no validation statement in training, matched drawn from train
  only, duplicates counted once, an over-cap prompt dropped while its proof stays, near-held-out states dropped,
  prefix counts, kept-only block tactics, the depth count.
- **S5: fixed.** `paired_difference` calls `check_comparable(..., across_settings=True)`, which checks the probe set and
  one identity per arm, and refuses unless all 2,000 statements (`len(strata)`) are common. `report` turns that into
  "Not evaluable". Tests cover another probe set and missing statements.
- **S6: fixed.**
  - The dry run prints its peak RSS times the number of ranks against the cgroup or physical limit and exits 3 above
    80%; the chain stops on 3.
  - Nit: the check compares against total memory, not what is free at the time. The servers and REPLs are stopped
    before training, so this is fine as driven.
- **N1: fixed.**
- **N2: not changed.** Accepted; small.
- **N3: partly fixed.**
  - `hash_order` now reuses `fixed_sets.hash_order`. The argument order is right at both call sites.
  - `MAX_FAILURE_CHARACTERS = 300` now exists three times (`offline_walk`, `offline_held_out`,
    `experiments/offline_arm.py`).
  - `first_line` still duplicates `known_proofs.first_line`.
- **N4: not changed.** It is correct, as 100% recovered shows.
- **N5: fixed**, with a test.
- **N6: documented** in DESIGN.
- **N7: fixed.** Nit: the depth count uses the index among recorded blocks. Blocks skipped for the completion cap still
  add depth, so the count can slightly understate.
- **N8: mostly fixed.** The docstrings are short now. `dropped: dict[str, int]` keyed by enum values and
  `BandWalks.statuses: dict[str, int]` remain; minor.
- **N9: fixed.** The operations note says to run the Lean test files on the node. `test_offline_held_out_lean.py` was
  added for `flat_reference`.
- **Q5: done.** The anchors' run 1 against run 2 is shown beside the gate as the noise floor. Both are visible-reasoning
  runs, so it is the noise floor at the anchors' setting, not at O's. The report labels it as two runs of one checkpoint
  at one setting.
- **Q6: done.**
  - Training states whose fingerprint reaches 0.7 with one of the 512 held-out states are dropped and counted. The
    comparison is exhaustive, uses the probe's `exhaustive_duplicates`/`fingerprints`, and is tested through
    `split_examples`.
  - Cost: MinHash over the roughly 0.9M distinct walk states, single-process in `build`. Expect minutes to a few tens of
    minutes and about 1 GB of signatures. That is acceptable, but add it to the build's time estimate.
- **Q4 (v0 in O's settings):** declined by the owner and recorded in DESIGN. Fine.

### New findings (nits only)

- **N10.** `experiments/offline_arm.py flat_references` gathers all 512 `flat_reference` calls and catches nothing. A
  replay mismatch or a dead REPL on one state (`apply_block` from `state_before` can raise) fails the whole step, and
  the chain retries it and then stops. This is unlikely, because the held-out runs already replay these states, but
  catching per state and recording the state as failed would match how `FlatReference.failure` already works.
- **N11.** The `FlatReference.goal_keys` comment says "before its end", but the keys include the state after the whole
  step. This is harmless, since that state equals the first standard key up to naming. Fix the comment.
- **N12.** A prefix proof counts as a whole proof of its band in `matched_sample` while contributing only part of the
  proof. Show prefix proofs per band in the README's matched table.

No new should-fix or blocking items.
