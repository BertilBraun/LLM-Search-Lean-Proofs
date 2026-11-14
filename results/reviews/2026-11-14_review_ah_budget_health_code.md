# Review AH: follow-up WP1 and WP5 (token-budget phases, run end, seed offset, health across arms), code by simulation

Branch `worktree-agent-a1f7eaa0dbb612621` (e40c958, 3925d19) against DESIGN.md "Follow-up study: controlled arms". In WSL:
`tests/rl` and `tests/graph/test_grpo_trainer.py` 1,372 passed, 5 skipped. Scenarios drive the real `GrpoLoop` with
the `loop_fakes` world, made deterministic: searches end only when released, and the watch checks only on a tick
(`asyncio.sleep(check_seconds)` patched in the scenario process only). Real-data numbers come from the branch's
`tree_summary`, `measurements` and `phase_health` on `node_backup/2026-11-01/hf_dataset`, with the Qwen3.5-2B
tokenizer (0 of 2,500 recorded completions decode differently). Scripts:
`C:\Users\berti\AppData\Local\Temp\claude\30f4a3a6c2eb0ef2\cac68663-9500-4596-8dc6-7bcaea394a3b\scratchpad\review_ah\`.
Not run: anything on a GPU, the resident trainer, `LeanTreeSearcher` against servers.

## Scenarios (B = 250 tokens, 100-token searches unless stated, concurrency 2, held-out states at each pause)

| Scenario | Expected | Observed |
|---|---|---|
| Reference, 4 phases | trees 3,2,3,2; one version, held-out run and health record per phase | as expected; run tokens 300, 500, 800, 1,000 |
| One search of 1,000 tokens (4·B) among 10-100 | phase 1 ends at ≥ 250; overshoot paid back | phase 1 1,100 tokens, then phases 2-5 train and publish on one tree each (50, 30, 40, 80 tokens) |
| Six searches end in each tick | overshoot carried | 6 trees and 600 tokens a phase; run tokens 600, 1,200, ... ≥ k·B; no phase skipped |
| Stop mid-sampling of phase 2 | lost searches logged, not counted; same boundaries | trees 3,2,3,2; `lost_generated_tokens` 100 in phase 2 |
| Crash after the phase was due, before the `training` stage | phase trains once after the restart | trains once; trees 3,3,2,2, run tokens 300, 600, 800, 1,000: a tree that ended before the first check after the restart joins the due phase (carried) |
| Crash mid-training of phase 2 | the phase trains again, one version | trained 1,2,2,3,4; versions 1-4 once each; paused searches booked as lost in phase 3 |
| Crash after publishing, before the held-out states | held-out runs once after the restart | held-out runs 0,1,2,3,4; no second version |
| Crash in the health check (after the record was written) | same health | record written twice; `read_health_history` keeps the last: no effect |
| Crash in the last phase's training or health (`max_phases = 2`) | the restart finishes the phase and stops | finishes, stops, starts no search |
| Server failure, search without a tree, summary failure | failed one lost (its partial tokens), the other two counted | phase 1 = 1 tree + 100 `no_tree` + 100 `summary_failed`; 50 lost; boundaries unchanged |
| `max_phases = 2` | trains 2, publishes v2, searches stay paused; a restart trains nothing | as expected |
| Sampling only, B = 10^6, `max_generated_tokens = 550` | stops at the first check ≥ 550, never trains | stops at 600 tokens, no training, no phase record |
| Both: B = 250, `max_phases = 3`, `max_generated_tokens = 600` | one rule ends the run | ends at 600 in phase 3's sampling: its 100 tokens are sampled and never trained |
| `max_generated_tokens = 500 = 2·B` | ends after phase 2 | as expected; searches stay paused |
| `seed_offset` 0 against master | identical | `phase_config_text` byte-identical for phases 1, 2, 7; exploration 0 and curriculum seed equal |
| `seed_offset` 1 against 2 | all moved seeds differ | policy/value seeds of phase 1 1,000,001 vs 2,000,001, replay `…/offset-1` vs `-2`, exploration 10^6 vs 2·10^6, curriculum differs |
| Phase without trainable groups (real `train_grpo`, 0 sequences) | defined empty update | 0 steps, the unchanged adapter saved, `loss_shares` None; the loop publishes a new version with the same weights; the next budget holds |
| No GRPO statistics (`policy = None`), held-out 0.78/0.76/0.75 vs v0 0.80 | no stop, KL and clip unmeasured | KL, clip None, no alerts, three versions |
| Same, held-out 0.50 (and 0.55 vs line 0.56) in phase 2 | hard stop at the collapse | `health_stop.json`, loop stops after phase 2 in both |

## Measurements

**Token accounting, phases 1-8 of the old run** (4,835 trees, 142.9M tokens; per-tree tokens from the index or
`result.accounting`): largest tree 103k tokens (p99 79k, median 30k), so no single search approaches B = 12M and the
empty-phase cascade above cannot happen at that B. Sampling rate 3.4k tokens/s, 103k per 30 s check. Re-cut at
B = 12M in finish order with the pauses removed: 11 phases, 329-598 trees (median ~410), each 11.9-12.2M; overshoot at
the check median 67-117k, max 228k (≤ 2% of B) over three check alignments, and it is carried. The 30 s granularity
costs nothing measurable. The real spread comes from the pauses: with 112 searches, every pause from phase 8 on held
~100 searches whose whole trees (4.4-4.9M tokens, 30-37% of the next phase's tokens) finished in the next phase;
about 38% of those tokens (~1.8M, phase 8) were generated before the pause by the previous version. At concurrency 56
expect about half: ~2.4M whole-tree, ~0.9M (7% of B) pre-pause tokens per phase. 12M is sensible: ~400 trees a
phase, ~1 h of sampling at the old rate, far above the old 300-group gate.

**Health from the trees, 250 random trees per phase** (reference = phase 1, `reference_phases = 1`):

| Phase | expl. tokens | bare `have` | failing after PG | unproved claim after PG | alerts (new checks) |
|---|---|---|---|---|---|
| 1 | 97.1 | 19.0% | 1.48% | 0.084% | reference |
| 4 | 101.3 | 30.1% | 2.36% | 0.25% | bare, failing (> 2.22%), unproved (> 0.13%) |
| 6 | 103.7 | 43.6% | 1.44% | 0.16% | bare, unproved |
| 9 | 90.5 | 53.2% | 1.82% | 0.27% | bare, unproved |
| 26 | 96.9 | 52.4% (below band 52.7%) | 3.04% (below band 3.26%) | 0.29% (0.24%) | bare, failing, unproved |

The explanation tokens stay at 90-104 in every phase: the new tree-based measure would not have seen the old reward
hacking (nor would the characters: 353-365). The story's signal is the bare `have` share (existing check, fires from
phase 4). The failing-tail share does not follow the hacking (peak phases 6 and 9 below phase 4) and fires at 2.4%
against 2.2%. The unproved-claim tail has a 0.08% reference: its threshold of 0.13% fires in every later phase, the
healthy phase 26 included. Cost: the tokenizer adds 22-48 ms to a 320-650 ms tree summary (+5-10%, ~20 s of a worker
thread per 500-tree phase); loading it adds 170 MiB RSS (811 -> 981 MiB). 16 threads sharing one tokenizer gave
identical counts on 3,976 completions, and the bisection equals a linear scan on 400 (prefix lengths monotonic).

## Findings

### Must fix before merge

None found: no divergence in phase boundaries, token totals, versions, trainings or evaluations except those below.

### Should

1. **The unproved-claim tail check fires every phase** (`health_checks.health_thresholds` l. 268, `health_alerts`
   l. 414). A 0.08% reference times 1.5 is noise; it fired in phases 4, 6, 9 and 26 above, so every arm will carry a
   permanent warning. Fix: a floor as for the cut-off share (`max(factor × ref, ref + rise)`, e.g. + 0.5 points) on
   both tail checks, or require a minimum count of samples; add a test with a 0.1% reference.
2. **`loss_shares` reads as "the anchors dominate"** (`policy_trainer.loss_shares` l. 163, `kl_penalty` l. 768).
   It compares |policy loss| with the KL and replay terms, but GRPO's policy loss is a mean-zero-advantage sum: its
   value was 0.001-0.03 per step in the old run (`grpo.jsonl` `policy_loss`) whatever its gradient, while 0.1 × replay
   NLL is ~0.03-0.1. The replay share will read 50-95% in every arm. Fix: log the three raw per-step means beside the
   steps, or per-term gradient norms (one extra backward each on a sampled step); at least rename and document it
   as a share of loss values, not of the update.
3. **A failure in the health-only measures drops the tree from training** (`loop.keep_tree` l. 1073 wraps all of
   `tree_summary`, which now also runs the tokenizer and the tail habits; `tree_summary.block_habits` l. 324). It did
   not happen on 3,976 completions under 16 threads, but the consequence (the tree leaves training in one arm only)
   is out of proportion. Fix: compute `explanation_token_habits` and the habits in their own try, `BlockHabits()` on
   failure with a logged count.

### Minor

4. **One overshoot ≥ B makes several empty or one-tree phases** (scenario 2; `loop.phase_due` l. 864). Unreachable at
   12M with 103k trees, but reachable when `phase_generated_tokens` is switched on in a run that already has phases
   (k·B is counted from phase 1) or at a tiny smoke B. Fix: require ≥ 1 tree in the phase, or refuse a store whose
   phase 1..k tokens already exceed k·B at the first start with the budget.
5. **`max_generated_tokens` beside B ends inside a phase** (`run_ended` l. 885): its sampled tokens are never
   trained, and `ends_with` (l. 878) can disagree with `run_ended` when the overshoot ≥ B. Fix: refuse both set unless
   `max_generated_tokens` < B (sampling-only), or end only at phase boundaries when B is set.
6. **Lost-token booking**: searches held at phase k's pause and cut off by a stop are booked in phase k + 1
   (`lose_search` uses `collecting`); a search cancelled during its `keep_tree` summary is neither counted nor lost.
   Log-only; say so in the README.
7. **The dashboard's "Explanation length" chart** (`static/pages.js` l. 591, `compare: true`) still plots the
   trainer's `grpo.mean_explanation_tokens`, which under sequence credit is the whole completion. Point it at
   `health.measured.mean_explanation_tokens`.
8. **Flaky test**: `test_a_restart_ends_the_token_phases_at_the_same_trees[4]` (`test_loop_budget.py` l. 80) failed
   once in ~32 runs (real 0.001 s checks against 0.01 s searches: a fourth tree can land before the check). Use a
   ticked watch as in the scenario harness, or assert the run tokens rather than tree counts.
9. **Arm equality**: nothing in the sampling path depends on `credit` before training (rewards in the three phase
   templates are identical; habits read `reward.off_graph_min_expanded_nodes` only; token phases ignore groups). The
   first phases are still not identical runs: vLLM sampling is unseeded and the curriculum band moves with outcomes,
   so arms match in distribution, not draw for draw. The only credit-dependent outputs are `trainable_groups` (logs,
   budget record), the GRPO family and item 7.

Verdict: **merge**; fix 1-3 before the arms launch (small), the minors when convenient.

## Re-review (979e83f)

`tests/rl` and `tests/graph/test_grpo_trainer.py`: 1,420 passed; `test_loop_budget.py` 20 runs in a row, 0 failures.
The same harness, rerun on the new head:
- **Limits**: refused are `max_generated_tokens` without B; a total that is neither below B nor a multiple of it (550
  and 600 at B = 250). Accepted are 500 (ends after phase 2), 250 (phase 1), and `max_phases = 3` with 1,000 (phase 3).
  Sampling-only B = 10^6 with total 550 finishes at 600 with trees complete (the 2 in flight are logged as stopped). Still
  accepted: `max_phases` beside a sampling-only total (harmless) and a negative `max_lost_token_share` (alerts every phase).
- **Run end**: state `finished`, `finished.json` (last phase 2, 500 tokens), `loop.pid` removed when it names the
  process (kept for another pid; `grpo_loop.sh` records python's own pid, `taskset`/`nice` exec), a restart finishes
  again with no search or training. A changed budget is refused, and so is switching it on after a minutes phase.
  `finished.json`'s `lost_tokens` is written before the stop cancels the paused searches, so it misses them (minor).
- **Restarts** in training and in evaluating: one version, held-out run and health record per phase; boundaries 3,2,3,2
  and run tokens 300/500/800/1,000 as before. A crash during training issues a second request for that phase, which is
  expected: the first never finished.
- **Race**: the window between "phase due" and `collect(phase + 1)` remains in production. It covers `await
  finish_benchmark_scoring()` (the value benchmark's scoring, still running beside the searches) and the pause lock. Two
  trees released into that window per phase gave 5,5,5,5 trees, each phase 500 tokens and the run 500/1,000/1,500/2,000.
  The totals are right, and an overshoot carries over and is paid back the next phase. It matters only if a scoring
  outlasts a phase. Minor: call `collect(phase + 1)` before waiting for the scoring.
- **Tails, 200 trees a phase** (new denominator: samples reaching the proof graph). Failing tail: phase 1 14.4%,
  threshold 24.4%; phase 1 against itself 20.0%, quiet. Fires in phases 4 (38.0%), 6 (30.0%) and 9 (36.2%), and phase 26
  sits at the same level (37.5%; below the band 37.7%). Phase 26 stays quiet only because its below-band 584 samples fall
  short of the 1,000 minimum. At ~500 trees a phase (~1,460 below the band) it would fire, so the check marks a level
  that rose after phase 1 and stayed, not the hacking (should: document it, or compare with the previous phases).
  Unproved tail: 0.9% (threshold 3.9%); fires in phase 9 only (5.3%), quiet in phases 4 (3.6%), 6, 26 and phase 1 again.
- **Habit failure**: the tree trains (the trainer saw 3 of 3 files), `trees_without_habits` is 1, both log lines appear
  and the alert fires (1 of 3 > 1%).
- **Step size**: a GRPO phase logs the parameter change 0.90 (0.99% of the start), gradient norm 0.030, |policy loss|
  0.0023, KL 0.00027, replay 0. With 0 sequences: 0 steps, `update` None, "its size not measured", no crash.

Verdict: **merge**. No must-fix; the failing-tail level is a "should", the rest minor.
