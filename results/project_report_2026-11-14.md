# Project report: LLM-guided Lean 4 proof search (2026-10-11 to 2026-11-01)

**Bottom line.** We built a complete step-level prover on consumer GPUs: policy, value model, best-first search and an
RL loop. It solves about 70% of miniF2F-valid. Most of that comes from the supervised stages. RL added a clear gain on
its own distribution and a small, borderline one on miniF2F. Nothing here is a research contribution on its own.

## What we built

- **Harness and search.** Pinned Lean 4 and Mathlib, a REPL wrapper, best-first/A* search with every proof verified.
- **Policy.** Qwen3.5-2B, later 4B, as LoRA. Fine-tuned on about 400k traced proof steps from public prover corpora,
  later with a short visible explanation before each tactic block.
- **Value model.** Qwen3.5-2B LoRA that predicts the remaining steps and ranks states for the search.
- **Statement pool and curriculum.** 59k Lean-verified statements, fed by difficulty band.
- **RL loop.** Search-tree GRPO with a credit label per tactic from the search graph, 4-GPU training in pauses, fixed
  evaluation targets, a dashboard, a habit monitor and rollback. One expert-iteration round on top.
- **Published.** Code, 16k search trees, all evaluations and the adapters (GitHub and Hugging Face).

## The ladder on miniF2F-valid (244 problems)

| Stage | Solved | Comparison |
|---|---|---|
| Automation tactics only | 79 | |
| 2B few-shot + search | 115 | |
| 2B after SFT | 148 | same model and budget as the row above |
| + value model (A*) | 157 | paired: 12 new, 3 lost, p ≈ 0.035 |
| 4B with visible explanations | 171 (student v1), 166 (v2) | same expansions, about 10x the tokens |
| Loop start v0 (4B, rewritten data, 8 samples per expansion) | 160 | |
| After the RL loop (v35) | 170 | paired with v0: 13 new, 3 lost, p ≈ 0.02 |

Rows from different stages use different students and search settings. Only the paired rows are strict comparisons.

## What the RL stage did (3 days, about $75)

| Fixed target | v0 | Final |
|---|---|---|
| Probe, 501 held-out pool statements, 16 expansions | 203 (40%) | 304 (61%), +289 Elo (95% +248 to +340) |
| Held-out states, one sample, success | 32.2% | 37.1% |
| miniF2F-valid, 64 expansions | 160 (65.6%) | 170 (69.7%) |

- v35 reaches v0's 64-expansion result on miniF2F with 8 expansions.
- The gain came in three pieces: a fast gain in the first phases, a few points from small-step GRPO after the reward
  fix, and +74 Elo (95% +23 to +133) from the single expert-iteration round.
- In between, the policy learned to hack the reward (bare unproved claims, filler); we rejected six versions, rolled
  back and fixed the reward.
- The earlier 2B expert-iteration loop (Oct 13) showed nothing beyond noise: 147, 152, 148, 149.

## What holds and what does not

**Holds:**
- SFT on traced proofs: 115 to 148.
- The value model helps the search: +9, paired, p ≈ 0.035, one run.
- RL improves the policy on the training distribution: +101 probe statements, interval far from zero.
- The reward-hacking episode, with habit metrics before and after the fix.

**Gaps:**
1. **Transfer is borderline.** +10 on miniF2F is one run and one seed at p ≈ 0.02. And 170 is where the earlier
   student v1 already was (171) before any RL, so RL has not gone beyond what an SFT variant reached.
2. **No controls.** We cannot say whether per-tactic graph credit beats outcome-only reward, or GRPO beats expert
   iteration. The expert-iteration round came after GRPO, not beside it at equal compute.
3. **The probe shares the pool's distribution.** Part of the +20 points may be adaptation to the pool's style.
4. **The value model inside the loop is unmeasured.** Its benchmark stayed flat; whether loop training helped it is
   unknown.
5. **Never run on miniF2F-test.** All decisions were made on valid, so 70% is optimistic.
6. **Far from the state of the art.** Whole-proof models of the same size report 78-90% on miniF2F-test.
7. **The curriculum ran dry.** The loop consumed the pool's unfed easy statements within hours after the round.
8. **Dropped along the way.** Retrieval (recall@8 0.16 on competition steps) and hidden thinking (did not pay at equal
   tokens).

## Is there a research contribution?

Not as it stands. Search with a critic, remaining-steps values, expert iteration and its plateau, and per-step
reasoning are all covered by prior work. Three things are possibly new but small, and none is established:
- short visible reasoning inside value-guided search (+14 per expansion, at 10x the tokens, unpaired);
- per-tactic credit from the search graph (never tested against a baseline);
- the reward-hacking case (documented, a single instance).

Turning any of these into a contribution needs a controlled comparison with seeds, and that is the expensive, uncertain
part. As it stands, this is a reproducible, well-documented learning project with public data, which is what the
write-up for the homepage was meant to be (decided 2026-10-25).
