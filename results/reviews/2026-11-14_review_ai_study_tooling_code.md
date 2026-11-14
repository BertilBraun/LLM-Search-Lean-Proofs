# Review AI: follow-up WP6 (study tooling: arm comparison, slices, rate ranking, step-1 settings, arm configs), code

Branch `worktree-agent-acedfb3c2cd157ac3` (master..970a3db, 7 commits) against DESIGN.md "Follow-up study: controlled
arms" ("Evaluation", "Step 1", "Step 2", WP6) and `results/followup_step0/noise_floor.md`. The branch's six new test
files: 120 passed in WSL. Every number below comes from the branch's own functions (`compare_arms`,
`confirm_with_seeds`, `pooled`, `mcnemar_p_value`, `token_budget`'s rule, `progressing_step_values`,
`automation_constant`) on synthetic probes drawn from noise_floor.md's model (fitted again from v0's two recorded runs:
logit spread 3.40, bin means 3.70 / 0.98 / -0.38 / -0.94 / -3.02 / -3.64 / -5.24; 2,000 statements at 150 ... 200 per
stratum) or on the old run's recorded v0 probe runs. Scripts: `C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_ai\`.

## Simulation

**The rule (`compare_arms`, 1,500 probes per row; "differ" = the verdict naming the arm truly ahead).**

| true difference | arms | runs per arm | "differ" | "differ", wrong arm | interval excludes 0 |
|---|---|---|---|---|---|
| 0 | identical per statement | 1 / 2 | 0.0% / 0.0% | 0.0% / 0.0% | 5.1% / 5.4% |
| 0 | divergence 0.65 (median trained pair) | 1 / 2 | 0.1% / 0.0% | 0.0% / 0.0% | 4.4% / 4.3% |
| 3 | identical + shift | 1 / 2 | 53.3% / 50.7% | 0 | 89.6% / 99.8% |
| 3 | divergence 0.65 + shift | 1 / 2 | 49.5% / 50.5% | 0 | 88.8% / 99.4% |
| 5 | identical + shift | 1 / 2 | 98.9% / 99.6% | 0 | 99.9% / 100% |
| 5 | divergence 0.65 + shift | 1 / 2 | 98.1% / 99.9% | 0 | 99.9% / 100% |

- **No false positives; pooling is sound.** The stratified bootstrap over pooled per-statement means is calibrated (4.3-5.4%
  exclusions under the null), so pooling two runs does not understate search noise; the floor takes the rule to <= 0.1%.
  Power is set by the floor on the point estimate: a true 3 points is called ~50% at any run count, 5 points ~99%.
  Write "reliably calls about 4 points and more", not "detects 1.9".
- **Pooled sign test** (one cross pair, 1,000 probes): p < 0.05 in 4.9% under the null (single-run McNemar 4.7%): valid,
  slightly conservative, not anti-conservative; at 3 points 99.1% vs McNemar's 89.7%.
- **Second-seed rule**, two runs pooled; seeds as a shift of each checkpoint's logit worth N(0, s) points (500 probes;
  s = 0: 1,000, one-run figures in brackets):

  | seed SD (points) | true 0 | true 3 | true 5 | true 8 |
  |---|---|---|---|---|
  | 0 | 0.0% | 73.6% (one run: 49.5%) | 96.7% (84.3%) | 100% (99.3%) |
  | 1 | 1.6% | 24.0% | 51.6% | 82.8% |
  | 2 | 2.6% | 10.6% | 16.8% | 39.6% |
  | 3 | 2.8% | 7.2% | 13.6% | 20.4% |

  False confirmations stay under 5% at every s (the gap criterion), but "under ~5 points cannot be confirmed" is about
  seed variance, not the rule: 3 points confirm 74% at s = 0; at s = 2, 5 points 17%. Report power at the observed gaps.

**T (old v0 probe runs, 501 statements each).** Tokens per expansion: 1,685 by the tool's ratio of sums, 1,583 as a mean
of per-statement ratios, 1,710 on the unsolved 16-expansion searches (where the cap binds), 1,496 on solved ones (3.7
expansions); the repeat run 1,671 / 1,587 / 1,704. The tool is within 1.5% of the binding quantity (per statement would
set T 6% low); pooling runs 1 and 2 moves it under 1%: harmless.

**Automation constant (old v0 probe trees, completion setting).** `automation_constant` on the root's progressing samples:
-47.2 (1,589 samples, each merged edge's maximum repeated per sample); median over the 1,423 edges the search ranks:
-49.4. Over all policy children the median step value is -59 at depth 1, -65 at depth 2, -70 below. The dummy
`calibrated = true` constant in `calibration_*.toml` is inert, verified: `_search` (`search/search.py:447`) stops at
`max_expansions` before `_next_node` pops the frontier, the constant enters only frontier priorities
(`CumulativeLogProbability.step_log_probability`), candidates are ordered by their own value (`policy/prompts.py:534`),
harvesting is off in evaluations.

## Must fix before merge

1. **`confirm_with_seeds` (`rl/arm_comparison.py:349-386`) confirms differences below the 3-point floor.** It checks
   direction, sign tests and seed gaps, never the floor or an interval. Tool fixtures, A's two seeds 8 of 400
   statements (2 points) ahead of B's in all four pairs: p = 0.008 each, gaps 0, **confirmed**. On 2,000 statements a
   consistent 2-2.5 point difference passes routinely. Fix: require `round(abs(claimed), 9) >= MIN_DIFFERENCE` and the
   interval of `difference` (x's two seeds' per-statement mean against y's) excluding 0; add the reason otherwise.
   Delete the unused `CONFIRMABLE_DIFFERENCE` (the seed table shows 5 points is not a property of the rule).
2. **The across-modes comparison drops the one setting Q3 is about.** `RunSettings` (`arm_comparison.py:66`) has probe,
   expansion budget, wall cap and config digest; `--across-search-modes` skips the digest, so runs 3 and 4 with
   different `max_generated_tokens` (a stale T in one file) compare silently. Fix: add `max_generated_tokens` and
   `max_depth` (`load_run_config(paths.config).search`) to `RunSettings`, checked in every mode. Also refuse two seeds
   of one arm with one identity in `confirm_with_seeds` (a duplicated run list gives gap 0).

## Should

3. **One-run comparisons print the primary endpoint's verdict.** DESIGN.md: one-run intermediate checkpoints are
   descriptive; `print_comparison` (`probe_compare.py:112`) prints "differ (provisional, one seed)" for any pair. Show
   runs per side and label a one-run side "descriptive".
4. **Run-level effects are invisible to the bootstrap** (statements are resampled; a shift shared by one run's
   statements, from node, load, builds or wall stops, is not). For a two-run arm, `pair` should print run 1 against run
   2 (difference, interval, McNemar) and flag the pooled verdict when that A/A interval excludes 0; read step 1's runs
   1-2 this way first.
5. **Multiple comparisons (`against_reference`, `rank_learning_rates`).** Rows share v0's runs (one low v0 run lifts
   every row) and each interval excludes 0 in 5% under the null: `rank_learning_rates` prints 13 x 3 intervals, ~2
   spurious exclusions expected; the floor protects `against`'s verdict (<= 0.1% per row), not the intervals. One line
   under both tables: "N variants against one shared v0: rows are correlated and about 1 in 20 intervals excludes 0 by
   chance; an effect needs the rule's verdict or a 99.6% (0.05 / 13) interval", ideally with that interval as a column.
6. **`choose_rate`'s gate tie is exact equality (`rate_ranking.py:114-117`): the "lower rate" clause is dead (~5% of
   pairs tie exactly) and gate noise picks the rate.** With the held-out states resolving ~3 points and one round moving
   little, the rates will usually tie there; the gate's paired difference on 402 statements has an SD of ~2 points, so
   the arms' rate becomes the argmax of noisy gate estimates, the riskier higher rate winning whenever its noise favours
   it. The held-out tie is an interval; the consistent reading of "the lower rate only if that ties too" is the gate's
   interval. Ask the owner; either way print tied rates' gate differences with intervals ("within noise" when they
   include 0). Held-out success as the measure is right (valid Lean beside it), but cannot separate rates under ~3 points.
7. **The probe-run flag fires without a contradiction (`rate_ranking.py:126-133`).** In a tie the chosen rate won the
   gate; a held-out point estimate leaning the other way inside its interval flags both rates. Flag only when the
   held-out interval also excludes 0.
8. **`rank_learning_rates.read_held_out` (`:61`) reads whatever trees exist**: an interrupted run, or one
   `held_out_evaluate.py` told to delete, is ranked on fewer states silently, and n is not printed. Require the finished
   summary and all 512 states; print n.
9. **The automation constant: per edge, and a root constant.** The search compares the constant with edges (each the
   maximum over merged samples): take the median over edges (`step1_settings.py:87`; -49.4 vs -47.2). More material: one
   expansion sees root steps only, 6-11 nats above deeper steps, which favours automation below the root. Document it, or
   calibrate from 16-expansion value-v0 runs with the setting on (A* with `policy_prior_weight = 0` never reads the
   constant, so all depths are recorded uncontaminated).
10. **Slices differ in curriculum position; the manifest cannot show it (`tree_slices.SliceRecord`).** With v0 fixed,
    slices differ by composition: the band rises, and the stop drops slow in-flight searches from slice 4 only. C's
    "W = 4 vs W = 1" is 4x the data *and* the easier early band, not window size. Record per slice: `difficulty`
    quartiles or counts per character stratum, distinct statements and those seen in an earlier slice, trainable groups
    and proof-graph blocks, mean expansions and wall seconds, statements fed but unfinished at the stop; the write-up
    then says "W = 4: k x the blocks, j% from bands below slice 4's".

## Minor

11. "Favour the same arm" uses the mean's sign, the p-value the sign count (`arm_comparison.py:362, 377`); with pooled
    values they can disagree. Require `x_ahead > y_ahead` to match the mean's sign.
12. Tests miss the edges: exactly 3.00 points with the interval excluding 0 (passes today via the rounding), an interval
    touching 0 ("no difference", correct), seeds agreeing on under 3 points (fails today, item 1), mean and sign count
    disagreeing, a variant 3+ points below v0.
13. The value-free pilot picks the most-solved of three settings on 200 statements (pairwise SD ~3 points): near-random
    unless one is far ahead; say so where reported. `confirm_with_seeds` names the winner "A1"; print the arm's name.

Verdict: **merge after fixes** (items 1-2; 3-10 before the runs they affect).

## Re-review (fix round 970a3db..a2a7750)

The six touched test files: 181 passed in WSL. Simulations and fixtures rerun on a2a7750 with the same scripts.
1. **Resolved.** `confirm_with_seeds` requires `passes_rule` on the seeds-pooled difference. Fixture: 2 points comes back not
   confirmed ("under 3 points or its interval includes 0"), 3.00 points confirmed. Seed rule, two runs pooled, 500
   probes (false confirmation / 3 / 5 / 8 points): s = 0: 0.0 / 43% / 97% / 100%; s = 1: 0.2 / 16 / 51 / 83%; s = 2:
   1.8 / 9 / 16 / 40%; s = 3: 2.6 / 7 / 13 / 20%. The floor cut 3-point power at s = 0 from 74% to 43%, as it should.
2. **Resolved.** `RunSettings` holds the token cap, depth cap and concurrency, checked in every mode. Two seeds with one
   identity are refused. `favours_x` requires the mean and the count to agree (old minor 11).
3. **Resolved.** The verdict is "primary" only with `--primary` (refused unless both sides have two runs), otherwise
   "descriptive". Each two-run side shows run 1 against run 2, flagged when that interval excludes 0. `against` and
   `rank_learning_rates` print the multiple-comparisons line.
4. **Resolved.** Gate ties use the paired interval to the gate leader, then the lower rate; the tied rates' gate
   intervals are printed. The probe flag needs both intervals to exclude 0. Partial or other-states held-out runs are
   refused, and n is printed.
5. **Resolved; it is the quantity the search compares.** The constant is computed per edge (first run of a block, max
   over merged samples, an unaligned sample keeping its completion value, as `parse_samples` does), at every depth, from
   a value-v0 run where the constant is inert. Under each setting this is the step value the per-block-mean path score
   averages. On the old v0 probe trees (1,002 trees with texts, 15,780 progressing edges, none dropped, Qwen3.5-2B
   tokenizer of the same family), the production functions give: **completion -56.1, block_sum -4.96, block_mean
   -0.135** (the placeholder is -0.12; review AF had -5.65). Medians by depth, 1 / 2 / 3 / 4+: block_sum -3.8 / -4.4 /
   -5.6 / -5.4, block_mean flat at -0.13 to -0.14, completion -49 / -54 / -58 / -59. Minor: children kept from a block's
   prefix after a failing tactic are ranked by the search but left out here, and the value-guided depth mix is not the
   value-free search's; say both in the configs' comment.
6. **Resolved, nearly.** Records hold the difficulty range, counts and solves per character band, below-band share,
   distinct statements and those seen before, trainable groups and mean expansions. Still missing: proof-graph blocks
   (C's training unit; trainable groups are GRPO's) and the statements still in flight at the stop.
7. **New.**
   - Should: run 3 against run 1, the pre-set depth_weight caveat named in `runs_reasoning.toml` and
     `token_capped_visible.toml`, cannot be run, because `pair` refuses different expansion and token budgets. Add a
     descriptive `--across-budgets` mode or name another tool.
   - Minor: the A/A flag fires on about 5% of two-run arms by chance; say so beside it. `multiple_comparisons_note(1)`
     reads "1 95% intervals ... 0.1 of them".

Verdict: **merge.** Item 7's should-fix is due before step 1's run 3 is compared.
