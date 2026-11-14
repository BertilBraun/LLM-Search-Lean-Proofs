# grpo_loop_v1: the statement pool, what the loop consumed, and a plan for the follow-up

By `experiments/analysis/statement_pool.py` from the published verified pool, fixed sets, tree index, loop log, metrics
and nine probe result files (v0: two runs per third; final pass: v31/v33/v35). "Usable" = verified and not closed by the
automation tactics alone. "Kept GPU-h" = 4 x (sampling + pause) of loop phases, rejected phases 5-10 left out.

## 1. The verified pool: stratified by proof length, not easiest first

| shortest proof (tactics) | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12+ |
|---|---|---|---|---|---|---|---|---|---|---|---|
| attempted | 8,357 | 8,357 | 8,357 | 8,357 | 8,356 | 8,356 | 8,356 | 8,356 | 8,129 (all) | 6,007 (all) | 8,356 |
| verified | 91% | 89% | 90% | 89% | 87% | 85% | 81% | 79% | 76% | 71% | 63% |
| automation-trivial of verified | 14% | 11% | 9% | 8% | 6% | 5% | 3% | 4% | 3% | 3% | 4% |
| usable | 6,505 | 6,620 | 6,871 | 6,833 | 6,854 | 6,757 | 6,576 | 6,361 | 5,974 | 4,113 | 5,104 |
| mean s per attempt | 18 | 18 | 17 | 18 | 21 | 24 | 29 | 32 | 36 | 39 | 43 |

68,568 usable of 89,344 attempted (58,002 goedel_sft_v2, 10,565 leanabell_sft); 26.5 s per attempt. Not easiest first:
since be2b66d it goes round-robin over proof-length buckets 2..11 and 12+, seeded-random within each
(`known_proofs.stratified_candidates`); it stopped only because the run did (~1,400 usable/h, ~14 Lean processes).

## 2. What the loop consumed (difficulty = the compiled proof's tactic count in all 16,006 trees; no root was scored)

| phase | kept GPU-h | band low | from band (solved) | from below (solved) | band median proof chars | unfed usable | unfed in band | unfed at/above band | unfed, 2,000+ chars | empty-band jumps |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 5 | 2 | 336 (51%) | 0 | 1,064 | 19,570 | 3,168 | 19,570 | 10,172 | 0 |
| 4 | 28 | 4 | 704 (60%) | 0 | 1,298 | 17,654 | 3,501 | 16,093 | 9,743 | 0 |
| 10 (rejected) | - | 6 | 543 (36%) | 0 | 2,286 | 14,036 | 1,404 | 10,091 | 8,027 | 0 |
| 11 | 34 | 4.5 | 550 (48%) | 220 (66%) | 1,668 | 13,266 | 604 | 10,529 | 7,738 | 0 |
| 16 | 69 | 9 | 263 (56%) | 144 (54%) | 2,793 | 17,924 | 4,076 | 8,414 | 10,097 | 0 |
| 21 | 102 | 11.5 | 291 (67%) | 154 (56%) | 2,958 | 26,926 | 731 | 2,756 | 14,386 | 0 |
| 26 | 138 | 15.5 | 337 (64%) | 181 (70%) | 3,573 | 36,100 | 143 | 792 | 18,672 | 0 |
| 29 | 159 | 15 | 417 (79%) | 226 (72%) | 1,702 | 45,558 | 157 | 199 | 23,405 | 33 |

The band rose ~0.1 tactics per kept GPU-h (4.5 to 19 over 34-152 GPU-h), in-band solve rates 48-79% on the kept line.
Supply ran short on the tactic axis, not in the pool: at/above the band <1,000 unfed by 15.5 tactics (phase 26), ~200 in
phase 29 (33 empty-band jumps up to 106 tactics and back) while 45k were unfed, 23k of them with 2,000+ characters. The
rise did not track ability (v5-v10 lost probe points as it rose); tactics barely measure difficulty (section 3).

## 3. Tactics are a weak difficulty measure; proof characters a strong one

| shortest compiled proof, characters | 0-499 | 500-999 | 1,000-1,499 | 1,500-1,999 | 2,000-2,999 | 3,000-4,499 | 4,500+ |
|---|---|---|---|---|---|---|---|
| usable (never fed by the old run) | 11,304 (8,400) | 6,489 (4,787) | 7,652 (5,814) | 8,233 (6,360) | 14,855 (11,502) | 12,741 (9,506) | 7,294 (5,290) |
| probe statements | 86 | 54 | 72 | 67 | 98 | 84 | 40 |
| probe solved, v0 / final pass (16 exp.) | 84% / 93% | 60% / 81% | 46% / 65% | 40% / 69% | 21% / 46% | 17% / 44% | 9% / 12% |
| loop trees solved (phases 11-31, 32 exp.) | 93% | 82% | 68% | 60% | 59% | 53% | 38% |

By tactics, v0 solves 53% of 2-tactic probe statements and 30-50% from 3 to 13+ (final 48-71% throughout); by
characters 84% down to 9%, also within goedel_sft_v2 alone (quartiles 62/38/22/12%). The short end is mostly leanabell
(9,437 of 11,304). The v0-to-final gain was +19 to +29 points at 500-4,499 characters (the middle); 4,500+ is the hard end.

## 4. What one arm needs, and re-feeding

| outcome of a tree (phases 11-31) | unsolved | solved at expansion 1 | at 2-4 | at 5+ |
|---|---|---|---|---|
| share of trees / trainable groups per tree | 38% / 0 | 17% / 1.6 | 20% / 2.9 | 25% / 4.9 |

~100 GPU-h = 15 phases of 6.8 GPU-h (old phases 1-4, 11-21): 7,836 distinct statements, ~5,100 from the band and ~2,700
below it at 35%. Arms do not compete (each arm's tree store decides what it searched); 43k usable at 1,000-4,499
characters are ~8x one arm's band demand. Re-feeding exists only below the band once no fresh statement is left there
(`Curriculum._below_band_name`, least recently searched first) and never happened. A re-fed solved statement likely
solves early (1.6-2.9 groups, on a proof it trained on); an unsolved one gives 0 unless now solved. How far an arm
moves: the probe's 50% point went from ~1,100 characters (v0) to ~2,000-3,000 (final, ~180 GPU-h with expert
iteration); a healthy 100 GPU-h arm might reach ~1,500-2,000 (a guess from one run).

## 5. Proposal

1. **Curriculum axis = proof characters** (config only): `proof_steps_weight = 0, root_value_weight = 0,
   characters_weight = 1` (difficulty = characters / 100), e.g. `band_width = 2` (~1,500 statements), `band_step = 0.5`;
   widen the dashboard bins (`statement_sources.DIFFICULTY_BAND_COUNT`). **Keep the 68.5k pool**: enough for supply.
2. **Optional, deepen the hard end**: verify 20,000 candidates with 2,500+ characters (10,000 at 2,500-4,499, 10,000 at
   4,500+, random within each): ~60-70% usable (~12-14k); at ~40 s per attempt on 56 Lean processes (61 cores) ~5,000
   attempts/h, about 4 h. Unknown: how many of the ~660k unattempted candidates have 2,500+ characters.
3. **Command today**: `phase6_pool_v3.py --config experiments/configs/expert_iteration/pool_v3.toml --step verify
   --concurrency 56 --limit 20000`, the published `verified.jsonl` in the pool directory (done names are skipped);
   without `--limit` or a large `--lead` it sleeps while 10,000 usable unstarted statements exist, and as is it
   continues the tactic round-robin (buckets 2-9, 12+). Character strata need, in `known_proofs.py`, a characters
   variant of `length_buckets` and per-bucket quotas in `stratified_candidates`, set from new `VerificationConfig`
   fields (`stratify_by`, `character_edges`, `bucket_quotas`) passed by `verify()` in `phase6_pool_v3.py`.
4. **Candidates are not published** (only the 89k attempted). Rebuild: `phase2_data_inventory.py --download` (pinned
   revisions, ~10 GB; normalization 20 min on the old node), then `phase6_pool_v3.py --step select` and `deduplicate`
   with the published `excluded_statement_keys.txt` in the pool directory (read as a cache: no tracing selection
   needed); their times were not recorded (guess under 1 h). Check that all 89,344 published names come back.
5. **The 2,000-statement probe**: from the usable pool by compiled-proof characters, seeded hash order per stratum,
   150 / 250 / 350 / 350 / 400 / 300 / 200 over the seven strata of section 3 (70% at 1,000-4,499, 200 at 4,500+).
   Expected v0 ~37%, the old final policy ~58%.

## 6. Hold-out today, and what to change

- The old 501 (and the 402 gate) came from `grpo_fixed_sets.py select` (`fixed_sets.select_fixed_sets`): tactic strata
  2-3 / 4-6 / 7+, 167 each in seeded hash order. The curriculum never feeds names in `[statements] held_out`.
- SFT: pool v3 drops statements whose canonical token key matches a proof in `selected_for_tracing.jsonl` (the source of
  all SFT and value data); MinHash removed near-duplicates within the pool only. Check the new probe against the
  `sft_data/` statements with `near_duplicates.py` (Jaccard >= 0.7) and drop hits.
- Code: `fixed_sets.py` has three fixed strata (`Stratum` enum, equal counts); seven strata with edges and counts need
  `FixedSetsConfig` and `select_fixed_sets` changed. Keep the old gate out of the new probe; list the probe in every
  arm's `held_out`. Not determined: the candidates' character distribution; whether the value model's root estimate
  predicts better (never scored here); the cost of a 2,000-statement probe pass (~4x the old one).
