# grpo_loop_v1: search-tree GRPO and expert iteration for Lean 4 proving (2026-10-29 to 2026-11-01)

A short write-up of the run: the concept, what we tried, what it measured, and what we learned. The run's data, search
trees and adapters are public:
- adapters: [BertilBraun/lean4-prover-qwen3.5-4b-grpo-lora](https://huggingface.co/BertilBraun/lean4-prover-qwen3.5-4b-grpo-lora)
- data: [BertilBraun/lean4-search-grpo-qwen3.5-4b](https://huggingface.co/datasets/BertilBraun/lean4-search-grpo-qwen3.5-4b)

Design detail lives in `DESIGN.md` and `src/lean_search/rl/README.md`; the reviews in `results/reviews/`.

## Concept

**Search.** A policy proposes proof steps and a value model ranks proof states; Lean 4 checks every step.
- The policy is a LoRA on Qwen3.5-4B. Given a proof state, it writes a short explanation, then a block of tactics.
- The search is best-first: it expands the state the value model (a Qwen3.5-2B LoRA) rates closest to a proof.
- Each expansion samples 8 blocks and runs them in a Lean REPL. Every new goal state becomes a node of the search graph.
- Training searches get 32 expansions per statement.

**Learning from the search graph instead of whole proofs.**
- Every tactic of every sampled block gets a credit label from the graph: on the proof graph, off it, unknown, failing,
  no progress, redundant hypothesis, unproved claim.
- GRPO groups are the 8 samples of one expansion. The advantage of a token mixes a local reward (its tactic's label)
  with a global one (the proof graph's distance to a proof).
- So an unsolved statement still teaches which steps were valid and which failed, and a solved one teaches more than
  "this whole proof worked".

**The loop.**
- Phases of 75-120 min of sampling on the 4 GPUs, then a pause: the 4 GPUs train data-parallel (policy GRPO, and every
  second phase the value model on the latest trees), the new version is published, and the servers swap weights.
- A curriculum feeds statements from a pool of Lean-verified statements (59k by the end, verified beside the loop). Its
  difficulty band moves with the solve rate, and 35% of the statements come from below the band.
- Fixed targets the loop never trains on measure progress:
  - a probe set of 501 held-out pool statements at 16 expansions, one third every ~2 h;
  - 512 held-out proof states, one sample each: the policy alone;
  - miniF2F-valid at 64 expansions.

## Timeline

1. **Setup and baselines (Oct 29-30).** v0 is the SFT policy (visible-reasoning student, numbered naming arm). It solved
   ~203 of the 501 probe statements (two runs per third), held-out states 32.2% success / 57.2% valid Lean, and
   miniF2F-valid 160/244 (65.6%).
2. **First phases (Oct 30).** A fast gain: v2 solved 86/168 on its third against v0's 66.5.
3. **Drift and reward hacking (phases 5-10).** The policy learned to open blocks with bare `have h : A` claims it left
   open and to pad blocks with filler. These were rewarded as progress. The curriculum band kept rising while the probe
   fell, down to v10's 43/168. We rejected v5-v10 and rolled back to v4.
4. **Recipe change (Oct 31).**
   - learning rate 2e-5, one pass per phase;
   - a KL penalty (0.01) to the SFT policy;
   - 35% of the statements from below the band.
5. **Reward fix (from phase 15).** It was reviewed four times and replayed on recorded trees first.
   - An unproved claim is penalised.
   - Filler counts as redundant.
   - Unknown states are scored.
   - The habits (bare claims, claims proved, openings) are monitored against the first phases'.
   Bare-`have` openings below the band fell from 47% to about 40%. The probe rose slowly: the pass after the fix beat the
   last pre-fix pass by +64 Elo (95% +15 to +112), about +3 points.
6. **Expert-iteration round 1 (Nov 1).** GRPO's steps were tiny: the probability of positive-advantage tokens moved by
   less than 0.1% per phase.
   - We fine-tuned v27 on the loop's own verified proof-graph blocks: 6,826 examples, the recorded prompts and tokens,
     40% replay.
   - Three step sizes: A 5e-5 × 1 epoch, B 1e-4 × 1 epoch, C 1e-4 × 2 epochs.
   - All three raised held-out valid Lean by 2.4-3.2 points over v27 (paired per state, intervals above 0); C began to
     forget in its second epoch.
   - B was kept (v31), and the KL reference moved to its adapter.
7. **GRPO on top of B (phases 27-30).**
   - The probe thirds reached their best yet: part 0 97/168 (before: 82-86), part 1 106/168 (before: 92-103), part 2
     101/165 (before: 87-97).
   - Bare-claim openings fell to 35%.
   - The curriculum ran through almost all unfed statements below difficulty ~30, a sign of the pool running out.

## Results

| Fixed target | v0 | Final |
|---|---|---|
| Probe set, 501 held-out pool statements, 16 expansions | ~203 (40%) | 304 (61%), the last full pass (v31, v33, v35) |
| Probe rating (Rasch, Elo scale, v0 = 0) | 0 | +289 (95% +248 to +340); +74 (+23 to +133) over the pass before expert iteration |
| Held-out proof states, success / valid Lean | 32.2% / 57.2% | 37.1% / 62.8% (v35; best v33: 38.8% / 65.1%) |
| miniF2F-valid, 64 expansions | 160 / 244 (65.6%) | 170 / 244 (69.7%): 13 newly solved, 3 lost against v0 (paired, exact McNemar p ≈ 0.02) |

- The probe shares the training pool's distribution, so it overstates the gain elsewhere; miniF2F is the
  out-of-distribution check.
- For scale: dedicated 4-8B provers report 78-90% on miniF2F-test at pass@32 and above, trained on far more statements
  and compute.

## Lessons

- **Measure on fixed targets.** The curriculum's solve rate, its band and the training searches' error rates all move
  with the target; only the fixed probe, the held-out states and miniF2F showed progress, regression and the drift.
- **Rate in passes, not single slots.** One version's probe third moves by about ±40 Elo from noise alone. The pooled
  Rasch rating of the last run of every third (a pass) made the trend readable.
- **Watch for reward hacking in the habits.** It showed in the blocks (bare claims, filler, shorter explanations) before
  the probe fell; the habit monitor now alerts on it.
- **Small-step GRPO plateaued; expert iteration stepped.** With a KL penalty and a learning rate of 2e-5, GRPO added
  only a few probe points over many phases. One SFT round on the loop's own verified steps moved held-out valid Lean by
  ~3 points and the probe thirds by up to +15 problems.
- **Exhausting the curriculum.** After the round, the curriculum ran through the pool's unfed statements within hours.
  More verified statements, or re-feeding solved ones, is the next constraint.

## Rebuilding the dashboard

The dashboard reads only a run's `metrics/*.jsonl`, which the dataset keeps under `run_logs/metrics/`:

```bash
python -c "from huggingface_hub import snapshot_download; snapshot_download('BertilBraun/lean4-search-grpo-qwen3.5-4b', repo_type='dataset', allow_patterns=['run_logs/metrics/*'], local_dir='grpo_loop_v1_data')"
PYTHONPATH=src python experiments/dashboard.py serve --run-directory grpo_loop_v1_data/run_logs --port 8600
```

Its alerts then say the loop is silent; everything else shows the run as it ended.

## Cost

One rented 4x RTX 3090 node from 2026-10-29 15:30 to 2026-11-01 ~23:00 UTC, about 80 hours at $0.965/h: about $75. The
earlier SFT and value-model stages ran before, on other nodes.
