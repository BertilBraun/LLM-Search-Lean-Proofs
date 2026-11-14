# grpo_loop_v1: evaluation noise floor, and sizing the follow-up's probe

By `experiments/analysis/noise_floor.py` from the published evaluations (all 21 probe runs, 8 held-out runs' trees),
the probe's fixed set and the pool's proof lengths. "Discordant" = solved in exactly one of two runs; points are
percentage points of the statements compared. Exact McNemar p throughout.

## 1. v0 twice (same model, same third, 16 expansions)

| group | statements | mean solved | both / one run / neither | SD of a solved count from search alone | coin-flip share |
|---|---|---|---|---|---|
| third 0 / 1 / 2 | 168 / 168 / 165 | 71-62, 82-76, 57-58 | discordant 23, 26, 31 (p 0.09, 0.33, 1.0) | ±3.4-3.9 statements (±2.2 points) | |
| 0-499 / 500-999 characters | 86 / 54 | 84% / 60% | 76/16/8% ; 48/24/28% | 3.1 / 4.7 points | 0.60 / 0.50 |
| 1,000-1,499 / 1,500-1,999 | 72 / 67 | 46% / 40% | 40/11/49% ; 31/18/51% | 2.8 / 3.7 | 0.22 / 0.37 |
| 2,000-2,999 / 3,000-4,499 | 98 / 84 | 21% / 17% | 13/16/70% ; 8/17/75% | 2.9 / 3.1 | 0.48 / 0.60 |
| 4,500+ | 40 | 9% | 5/8/88% | 3.1 | 0.47 |
| all 501 | 501 | 41% | 33/16/51% | ±6.3 statements (±1.3 points) | 0.33 |
| all, within 1 / 2 / 4 / 8 exp. | 501 | 13 / 22 / 29 / 36% | discordant 9 / 13 / 15 / 14% | ±0.9 / 1.1 / 1.2 / 1.2 points | 0.38 / 0.37 / 0.35 / 0.30 |

SD of a count = sqrt(discordant / 2), unbiased for sum p(1-p). Coin-flip share = observed discordance / the discordance
if every statement in the group had the group's mean rate (1 - intraclass correlation): two thirds of the outcome
variance is fixed per statement, one third is a coin flip. The flips sit at both ends (short proofs that v0 sometimes
misses, long ones it sometimes finds), least at 1,000-1,999 characters. Wall-clock stops explain 2 of the 80 flips.

## 2. Different versions on the same third (16 expansions; 23 pairs, a selection)

| pair (third) | solved | lost / gained | discordant | p |
|---|---|---|---|---|
| v0 -> v2 / v15 / v21 / v31 (0) | 71 -> 86 / 83 / 82 / 97 | 10/25, 8/20, 11/22, 3/29 | 21, 17, 20, 19% | 0.017, 0.036, 0.08, <0.001 |
| v0 -> v4 / v17 / v23 (1) | 82 -> 92 / 95 / 103 | 12/22, 10/23, 6/27 | 20, 20, 20% | 0.12, 0.035, <0.001 |
| v0 -> v13 / v19 / v25 (2) | 57 -> 87 / 94 / 97 | 5/35, 4/41, 4/44 | 24, 27, 29% | all <0.001 |
| neighbours v15->v21, v17->v23, v13->v19, v19->v25 | -1, +8, +7, +3 statements | 12/11, 10/18, 7/14, 11/14 | 14, 17, 13, 15% | 1.0, 0.19, 0.19, 0.69 |
| collapse v4 -> v10, recovery v10 -> v17 (1) | 92 -> 43 -> 95 | 50/1, 2/54 | 30, 33% | <0.001 |
| miniF2F-valid v0 -> v35 (64 exp.) | 160 -> 170 / 244 | 3/13 | 7% | 0.021 |

Discordant share = 13.4% + 0.61 x |points| (least squares, 23 pairs). Neighbouring kept versions disagree on 13-17% of
statements, no more than v0 disagrees with itself (14-19% per third): the per-statement shuffling between nearby
checkpoints is mostly search noise. Against v0 the trained versions disagree more (17-29%), growing with the gain.

## 3. Detectable difference on the new 2,000-statement probe (80% power, 5% two-sided, paired per statement)

| model of the two arms | arm A | discordant at no difference | 1,000 x1 / x2 | 2,000 x1 / x2 | 4,000 x1 / x2 |
|---|---|---|---|---|---|
| v0-like, same per-statement ordering | 37% | 17% | 3.6 / 2.6 | 2.5 / 1.8 | 1.9 / 1.3 |
| trained (+1.15 logit), divergence 0.65 (median pair) | 46% | 18% | 3.7 / 2.7 | 2.6 / 1.9 | 1.9 / 1.4 |
| trained, divergence 3.0 (largest pair) | 46% | 25% | 4.5 / 3.7 | 3.2 / 2.6 | 2.2 / 1.8 |
| trained, divergence 0.65, v0 spread at its 95% ends (2.6 / 4.4) | 46-47% | 20 / 15% | 4.0 / 3.5 | 2.8 / 2.5 | 2.1 / 1.7 |

Model: solve logit per statement ~ Normal(bin mean, 3.4^2) by proof-length bin, fitted to v0's two runs (spread 95%
2.65-4.4); arm B = A + shift + Normal(0, divergence^2), divergence fitted per pair of section 2 (0 to the cap 3.0, median
0.65); 1,500 simulated probes per point; "x2" = two runs per checkpoint, per-statement means compared. The shortcut
2.8 x sqrt(discordance / n) agrees (2.3-3.1 at 2,000 x1). Model choice moves the answer ~±0.5 points; statement count
and repeats matter far more, and two runs on 2,000 equal one run on 4,000.

## 4. Held-out states (512 states, one expansion of ~5.4 scored samples each)

| | success (summary) | valid Lean | SD of one run: binomial / resampling within states | paired per state: SE (80% detectable) |
|---|---|---|---|---|
| v27 / v28 / v29 / v30 | 36.4 / 36.8 / 37.0 / 36.8% | 59.2 / 63.1 / 64.2 / 64.0% | valid 0.94 / 0.72 points | v28-v29-v30 valid 1.0-1.1 (2.9-3.1 points) |
| v0 / v33 / v35 | 32.2 / 38.8 / 37.1% | 57.2 / 65.1 / 62.8% | success binomial 0.87-0.95 | v0->v35 1.25 (3.5), v33->v35 0.99 (2.8) |

No version ran the held-out set twice, so between-run noise is the resampling of each state's samples (unbiased
x(n-x)/(n-1) per state): ~0.7 points for valid Lean, below the binomial 0.9. Success per state cannot be rebuilt (the
reference states file is not published); valid Lean and proof-only success stand in. Paired per state the set resolves
~3 points; v28/v29/v30 differ by no more than resampling predicts (1.0-1.1 vs sqrt(2) x 0.72).

## 5. Training seeds: what the data cannot say

No arm was trained twice: seed variance is unmeasured. Weak proxies: kept neighbours on one third move -1 to +8 points
(z -0.2 to +1.5, eval noise, but one trajectory); the three expert-iteration variants agree within 0.2 points on
held-out success (1.1 on valid Lean), but that is SFT on fixed data; v29 and v31 are one adapter never evaluated on the
same target. The hard fact: v4 -> v10 lost 29 points in 6 phases, so one RL run can collapse. With 2 seeds per arm (t on
arm means, 2 df) a difference D holds only if each arm's seeds differ by at most D / 3: 1.0 point for D = 3 (below a seed
gap's own eval noise, ~0.95 at 2,000 x1: not confirmable), 1.6 for D = 5, 2.6 for D = 8.

## 6. Recommendation

| budget (exp.) | 1 | 2 | 4 | 8 | 16 |
|---|---|---|---|---|---|
| expansions per statement / McNemar z^2 per 167-statement pair / z^2 per expansion vs 16 | 1.0 / 5.5 / 3.6x | 1.8 / 7.5 / 2.7x | 3.3 / 10.7 / 2.1x | 5.8 / 14.2 / 1.6x | 10.2 / 15.6 / 1x |

- **Probe: 2,000 statements as planned, 16 expansions.** Small budgets carry more information per expansion (4
  expansions: 2.1x), but measure a different thing (first-try quality, not search) and need ~1.5-3x the held-out
  statements; a 16-expansion run records solved-within 1-8 for free, so report those as secondary.
- **Repeats:** one run per intermediate checkpoint (detects ~2.6 points); two runs for v0 and each arm's final
  checkpoint (~1.9 points, and the v0 pair re-measures this noise floor). Smaller than ~2 points is out of reach.
- **Pre-set rule, "arms differ":** on the final checkpoints, the paired per-statement difference (two runs pooled) has
  a 95% interval excluding 0 and is at least 3 points; with one seed it is reported as provisional. With the second seed:
  all four cross-seed comparisons favour the same arm (each McNemar p < 0.05) and each arm's seed gap is at most a third
  of the claimed difference.
- **Cannot be answered from this data:** training-seed variance; the held-out set's true between-run noise and its
  per-state success; whether the noise at 2,000-4,499 characters on the new probe matches the old probe's 40-98
  statements per bin.
