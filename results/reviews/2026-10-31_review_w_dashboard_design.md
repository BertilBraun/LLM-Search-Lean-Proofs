# Review W: dashboard headline and probe rating (design), `dashboard-headline` at 814d2f9

Scope: `git diff master..dashboard-headline`. I read in full `rl/probe_rating.py`, the `families.py` additions, the
`static/app.js` and `static/pages.js` diffs, both README changes, `deployment/grpo_loop.sh`, and the relevant parts of
`rl/evaluation.py`, `rl/loop.py` (evaluation directories, value model served), `rl/health_checks.py`, `loop.toml`,
`dashboard.toml`, DESIGN.md (the owner decisions of 2026-10-31) and review T's watch list.

Simulation (the fit copied verbatim from `fit_abilities`). The design matches the node: 501 problems in 3 thirds of 167.
Version 0 runs each third twice; 8 later versions run one third each, rotating thirds, with the node's ratings as true
abilities. Difficulties are N(0, σ_d), and an optional per-run shock is N(0, τ) logits. 150 replications with 100
bootstraps each. Scripts and outputs:
`C:\Users\berti\AppData\Local\Temp\claude\C--Projects-Lean-Proofs\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_w\`
(`simulate.py <τ> <sims> raw|scaled [σ_d]`, `marginal.py`, `out_*.txt`). With σ_d = 2 the simulated run-to-run
difference of version 0 has an SD of 7.1 problems per third. The node's 9, 6 and 1 fit that, so σ_d ≈ 2 is a
reasonable calibration. The simulated interval width (0.97 logits) also matches the node's (~1.0–1.1).

| Scenario | Mean coverage of the 95% interval (worst version) | Point / truth | Interval asymmetry (upper − point vs point − lower) |
|---|---|---|---|
| Bernoulli noise only, σ_d = 2 | 0.91 (0.85) | 0.98–1.13 | 0.55 vs 0.44 (away from 0) |
| + run shock τ = 0.2 logits | 0.81 (0.74) | same | same |
| σ_d = 1 | 0.87 (0.77) | 1.03–1.26 | 0.51 vs 0.42 |
| bootstrap with the prior scaled by the weight (fix of 2) | 0.93 (0.89) | same | 0.47 vs 0.45 (symmetric) |
| marginal fit (random difficulty), σ_d = 1 | n/a | slope 1.00 (joint 1.16), SD 0.18 (joint 0.22) | n/a |

## Findings

**1. Run-level effects are confounded with version, and the interval cannot see them (should-fix).**
- The problem bootstrap is a valid cluster bootstrap for outcome noise that is independent across problems. Each
  resampled problem carries its own Bernoulli outcome, so search stochasticity of that kind *is* included.
- What the bootstrap misses is anything shared by all problems of a run. Every version after 0 has exactly one run,
  so a run effect cannot be told apart from the version's ability.
- With τ = 0.2 logits (about 4 problems of 167, which three v0 repeat pairs cannot detect), coverage falls to 0.81, and
  to 0.79 for a version pair.
- Version 0's repeats cannot calibrate τ. All six of its runs ran together before sampling (`loop.toml:198-205`), so
  they share every condition that later runs do not.
- The systematic run effects are concrete:
  - (a) `value_model` changed from `"initial"` to `"published"` on 2026-10-30 (c34e2d0). Runs before that searched with
    value v0, runs after with the version's own value model. The curve therefore mixes two estimands, and v0's own
    runs are of the first kind.
  - (b) Since the same commit, probe runs run beside sampling: 56 REPLs, with GPUs shared with the searches. Version 0
    ran before sampling. Under the 1800 s cap (`loop.toml:212`), a slower GPU turns into more `wall_clock_stops`, which
    count as unproved and also as "not within 16".
- Evidence: `probe_rating.py:52-63` reads neither `value_model` nor `summary.wall_clock_stops`.
- Fix:
  - Carry `wall_clock_stops` and the value regime per version into `VersionRating`, show them in the table, and mark
    the regime switch on the chart.
  - Either drop wall-clock-stopped unproved outcomes from the fit (treat them as censored) or warn when a run's
    stop share exceeds v0's by more than a few points.
  - To calibrate τ under the real conditions, repeat one later version's slot once, beside sampling. The repeat
    machinery exists (`EvaluationRun.repeat`).

**2. The bootstrap's prior is not scaled with the multinomial weight. This makes the interval asymmetric, skewed away
from 0 (should-fix, one line).**
- `fit_abilities` multiplies the likelihood by `weights[problems]`, but adds `DIFFICULTY_PRIOR` once per problem
  (`probe_rating.py:83-84`). A problem drawn k times gets k × likelihood with 1 × prior. Problems that are always or
  never solved therefore get more extreme difficulties in the replicates than in the point fit, and the replicates
  shrink less than the point estimate.
- That is exactly the node's pattern. Every positive version's point lies near the lower end: v2 0.82 [0.50, 1.62],
  v13 1.18 [0.81, 2.03], v15 0.65 [0.35, 1.30]. v10's point lies near the upper end: −1.99 [−2.83, −1.54].
- Simulated, the bootstrap median exceeds the point by 0.05–0.10 logits (0.16 for v10), with upper − point 0.55
  against point − lower 0.44.
- With the prior multiplied by the weight (`DIFFICULTY_PRIOR * weights`), the interval becomes symmetric
  (0.47 / 0.45), the median-to-point shift goes to 0, and coverage rises from 0.91 to 0.93.
- Under the current status rule (green iff lower > 0), the bias is toward a green that comes slightly too late; the
  upper bounds overstate the gain.
- Fix: scale the prior by the weight in the bootstrap fits. Also consider a BCa or basic interval, and report the
  bootstrap SD, which is ~0.25 logits (≈ 43 Elo) per version.

**3. The point estimate is a joint (fixed-difficulty) fit, so its bias depends on how spread out the difficulties are
(minor; check before trusting the scale).**
- Each difficulty has only ~4–5 observations: v0's two plus the 2–3 versions on that third. That is the
  incidental-parameter regime of joint-ML Rasch fits.
- The prior N(0, 3.16²) is centred on v0's 50% point, not on the probe's actual mean difficulty.
- Simulated:
  - σ_d = 2: ratios to the truth of 0.98–1.13 (slope 1.04), essentially fine.
  - σ_d = 1: slope 1.16 and up to 1.26, so the ratings come out up to a quarter too large.
- A marginal fit removes this: difficulty ~ N(μ, σ²) with μ and σ estimated, integrated by 30-point Gauss–Hermite
  quadrature, L-BFGS over 10 parameters. It gives slope 1.00, and a smaller SD (0.18 vs 0.22) at σ_d = 1.
  `marginal.py` does this in ~25 lines and runs in well under a second per fit.
- The ability prior (precision 0.01) and the v0 anchor are fine. v0's six runs make it the natural anchor, and
  shrinkage of abilities is negligible.
- Fix: switch to the marginal fit, or at least log the fitted difficulty SD. Below ~1.5, the current numbers are
  inflated.

**4. The headline is the newest version's single third, so it is too noisy to colour each slot, and "best" is a
winner's curse (should-fix).**
- The tile shows the newest rated version (`app.js:415-424`). That is one run of ~167 problems with an SD of
  ≈ 0.25 logits (43 Elo). Its status turns green or yellow from one slot to the next.
- "Best v13 +206" is the maximum of 9 noisy estimates, so it is biased up.
- Version pairs are fragile:
  - The SD of a difference is ≈ 0.35 logits (61 Elo), so two versions need a gap above ~120 Elo to separate.
    v13 vs v17 (+206 vs +137) is noise.
  - Versions on different thirds are connected only through v0's (and same-third versions') difficulty estimates.
  - The 95% interval of a pair difference covers 0.89 in simulation (0.79 with run shocks).
- Nothing in `ProbeRatings` gives a pairwise interval. Yet the tile's "why" says to read "rising over versions" and the
  sub names the best version.
- Fix:
  - Headline a pooled "recent" rating: the last three probed versions sharing one ability, i.e. one full pass over
    the 501 problems, the same idea as `probe_rolling_*`. Its SD is ~0.15.
  - Keep per-version points in the chart.
  - From the bootstrap matrix that is already computed, store intervals of the difference to the previous rated
    version and to the reference of the reward-fix revert rule (finding 9).
  - Drop "best", or show it with its interval.

**5. "Elo" is mathematically correct here, but it invites the wrong intuition. Give the projected solve count beside
it (minor).**
- 400/ln 10 per logit is the Elo scale, and "+100 is a 64% chance on a problem v0 proves half the time" is correct:
  σ(100 · ln 10 / 400) = 0.640.
- It is not head-to-head strength, though. It is a log-odds shift per problem, and its relation to the solve rate
  depends on the difficulty distribution.
- On a spread-out set, Rasch differences are about √(1 + 0.35 σ_d²) ≈ 1.5× the raw logit difference of solve rates.
  v4's +108 is roughly 92 vs ~79 of 168 problems (DESIGN.md:1067), about +8 points.
- A chess player reads +108 Elo as a clearly stronger engine. Here the same number is +8 points on a third, with an
  SD of ±43 Elo.
- Fix: in the tile, show beside the Elo number the projected solves on the whole probe set,
  Σ_p σ(a_v − d_p) over all 501 problems against v0's. It is cheap, it is the user's real target, and it puts every
  third on the same 501 problems. Label the scale "probe Elo (log-odds vs v0)".

**6. Tile 2 ("solved within 16 vs v0") duplicates the rating and an existing chart, and a gain > 0 is not evidence
(should-fix).**
- It uses the same 167 problems as the newest version's rating, and it equals `probe_baseline_difference`, which is
  already charted in the same section (`pages.js:544`, `FIXED.probeDifference`).
- Its SD is a single run against the mean of v0's two runs: √(var + var/2) ≈ 5.5 problems ≈ 3.3 points. So
  "green iff gain > 0" (`app.js:430`) is a coin flip at no effect.
- "Within 1 expansion is the policy's first answer without search" (`app.js:434`) is really the root's n samples
  (pass@n), not a first answer.
- Fix: replace it with the rolling last three slots against v0 on the whole set (`probe_rolling_baseline_difference`,
  501 problems, SD ≈ 2 points), with a paired interval. Colour it only when the interval excludes 0; otherwise use a
  neutral colour. Reword "within 1".

**7. The status colours mix "no evidence yet" with "something is wrong" (minor).**
- Rating yellow, i.e. warning, when the interval contains 0 (`app.js:420`) is the expected state early on and on any
  plateau. A permanently yellow headline trains the reader to ignore yellow.
- The value benchmark tile has the right idea: a status only when the interval lies below 0 (`app.js:458`).
- Fix:
  - green: the lower bound is above 0, or above the reference of finding 9;
  - red: the upper bound is below the reference;
  - neutral otherwise.
  - Status the regression against the previous pooled rating, not only against v0. After a recovery from a collapse,
    "above v0" is green while the policy is still below the version it rolled back to.

**8. The "Claims proved" tile judges one number and displays another (should-fix).**
- The status uses `below_band_claim_proved_rate ?? claim_proved_rate` (`app.js:516`), but the value is
  `claim_proved_rate` (`app.js:520`), and the sub does not say which slice is judged.
- The tile can show a value above the limit in red, or below it in green.
- The rate is also a tiny ratio: 0.2–2% of open claims, and the below-band slice is 35% of statements. So it moves a
  lot from phase to phase.
- Fix: show the judged value, as the Bare-claims tile does (`app.js:507`, with "below the band" in the sub), and
  print the counts (proved / open).
- Bare claims compares the below-band share with 1.5× the reference phases' share over all statements. That matches
  `health_checks.compared`, so the tile agrees with the loop's alert. That is defensible, and the README says so.

**9. The headline does not support the decision rules the owner already set (should-fix).**
- The reward-fix revert rule (rl/README.md "Revert rule", review T) asks: by the third phase with the fix, are the
  probe solves above the pre-fix level? Review T's watch list names v0 76–82, v4 92 and v10 43 on 168 problems.
- The headline compares only against v0.
- Fix: add a reference version from `reward_fix.json` (the last pre-fix version, or the pooled pre-fix versions after
  the rollback). Draw it as a reference line in the rating chart, and give the tile the interval of the difference to
  it (from the bootstrap matrix). This is the one comparison the next days actually depend on.

**10. The documented collapse signature is not on the dashboard (should-fix).**
- DESIGN.md:1061-1063 describes the drift of phases 1–10: the probe fell, the replay NLL on the SFT data doubled, and
  the entropy fell from 0.36 to 0.23.
- `policy_trainer.py` computes `final_entropy` and `replay_nll`, but `GrpoPhase` (`families.py`) carries neither, so
  no page shows them and no alert reads them.
- These two per-phase, free signals would have flagged the drift sooner than the probe (every 2 h on a third) or the
  held-out valid-Lean rollback trigger.
- Fix: write both into `grpo`, and give Health an "Entropy / replay NLL vs the first phases" tile with a
  relative threshold, like the habits.

**11. The rollback trigger has no status on any tile (should-fix).**
- The held-out valid-Lean rate is the signal that publishes a rollback below 0.7× v0's (README "Rollback and hard
  stop"). It appears only in the sub of the Policy-alone tile, whose status is set by `min_held_out_success` alone
  (`app.js:446`).
- Fix: give it a health tile with warning below 0.9× and critical below 0.7× v0's.
- Show "rolled back to vN at phase k" and any pending `health_stop.json` on the Loop tile. That is the state an
  operator most needs to see at a glance, and today it is only in the alert list.

**12. The curriculum tile measures the wrong population and frames the failure mode as healthy (should-fix).**
- The rate sums `by_difficulty` (`app.js:545`). Since `below_band_share = 0.35`, that pools the easier below-band
  statements with the band's cohort. The band controller acts on the cohort only (raise at 0.5 and fast at 0.8, lower
  at 0.3, `loop.toml:174-177`).
- The rate is also largely a controlled variable: the controller keeps it in 0.3–0.7. Being in band says little.
- The "why" text says the rate "should stay within 0.3–0.7 while the band climbs". But a band that climbed (2.5 → 6.9)
  while the fixed targets fell *was* the drift of phases 1–10.
- Fix: compute the rate from `by_origin` for the band cohort. Make the health signal the band's climb next to the
  fixed-target trend, with a warning when the band rises for several phases while the pooled probe rating does not.
  Reword the explanation.

**13. The KL tile's sparkline and explanation are not supported by the history (minor).**
- Phases before 2026-10-31 report another estimator: a k3 median that reads 0 or 10^1–10^7 (README health table). So
  the sparkline mixes two scales.
- The claim that "a steady climb past the limit is drift like the collapse before the rollback to v4"
  (`app.js:531`) cannot have been observed with that estimator.
- The loss now carries a k3 penalty of 0.01 toward the starting policy, so the KL is partly controlled.
- Fix: plot from the first phase with the new estimator, and reword the explanation to "a fast climb or a climb past
  the limit", without the historical claim.

**14. The probe rating covers policy and value together, which is right for "is the prover stronger", but the
decomposition is only implicit (minor).**
- Since `value_model = "published"`, the rating answers the prover question. The held-out tile (policy alone) and the
  value benchmark (value alone, 97 pairs, intervals ~±5 points) are the decomposition.
- With the value arm off, nothing separates a policy gain from a value gain on the probe. Given the benchmark's power,
  the only value-model failure the dashboard can show is a large one.
- Fix: say this in the headline note. Show the value version per point in the rating chart's tooltip (it is in
  `VersionRating`).
- Combined with finding 1(a), the rating's history before the switch should be shown as "policy with value v0".

**15. The recorder is a separate, unsupervised process that dies silently and leaves a stale headline (should-fix).**
- `record_ratings` (`probe_rating.py:178-188`) has no exception handling. Any of these kills it for the rest of the
  run:
  - a `ValueError` from `from_json_object` on a summary or result with an older or newer schema;
  - a truncated `results.jsonl` line after a crash and resume;
  - a directory pruned mid-glob;
  - a `numpy` failure.
- `nohup` keeps nothing alive, and the dashboard shows the last `rating` line with no age and no "runs rated vs runs
  finished". The headline would quietly freeze.
- A restart writes a duplicate line (`rated = ()`), which is harmless. Starting `grpo_loop.sh dashboard` twice runs two
  recorders, which is also harmless but noisy. The script's echo omits the new log.
- Cost is not a concern: ~4 s per refit for 14 runs, linear in runs (≈ 25 s after a week of slots), every ~2 h.
- Fix, one of:
  - (a) Rate from the loop after each probe summary (`asyncio.to_thread`, wrapped so that a failure logs an alert and
    never stops the loop). The loop already owns the evaluation lifecycle and writes `fixed_targets` at the same
    moment.
  - (b) Keep the recorder, but catch and log per iteration, skip unreadable runs with a count, and write the count of
    finished vs rated runs into `ProbeRatings`.
- Either way, the tile should show the rating's age and turn grey when a finished probe summary is newer than the
  latest `rating` line by more than two intervals. My preference is (a) plus a one-shot `rate` CLI for backfill.

**16. What the overview dropped (minor).**
- Distinct samples, cut-off samples and repetition loops (collapse signals), MATH-500 (forgetting) and miniF2F left
  the overview or moved into the collapsed Operations section.
- Their alerts still render under Health, so nothing is lost operationally.
- MATH-500 visible has a critical threshold and is the forgetting check the user would expect near the headline.
- Fix: keep MATH-500 as a small tile in Health, coloured only by its existing thresholds.

The collapsible sections are sound. Remembering the choice per browser, collapsing two by default, and fetching nothing
for collapsed sections are all fine. The per-tile "why" lines with a global toggle answer the request well.

## Verdict

The design does what was asked:
- a small top row of fixed-target headline numbers and health numbers, each with a stated reason;
- the habits on the overview;
- collapsible sections.

The Rasch rating is a reasonable way to put one-third probe slots on one scale. Its point estimates are close to
unbiased at the probe's apparent spread (σ_d ≈ 2), and "+100 = 64%" is correct.

The statistics need three changes before the headline's colours can be trusted:
- scale the prior with the bootstrap weight, which removes the visible away-from-0 skew of every interval;
- account for run-level effects, which the problem bootstrap cannot see: the value-model regime switch and wall-clock
  stops beside sampling are confounded with version, and one run per version gives ~0.81 coverage at a modest 0.2-logit
  run effect;
- headline a pooled recent rating against a decision-relevant reference (the pre-fix version), not the newest single
  third against v0.

On the health side:
- the Claims-proved tile must show the value it judges;
- the curriculum tile should use the band cohort and stop calling a climbing band healthy;
- the collapse signature named in DESIGN.md (entropy, replay NLL) and the rollback trigger (held-out valid Lean) need
  tiles.

Operationally, make the rating fail loudly, either inside the loop or with per-iteration error handling and a staleness
marker. None of these is a blocker for merging a read-only dashboard. Findings 1, 2, 4, 8 and 15 should land before
anyone reads the headline's green as "the RL is working".
