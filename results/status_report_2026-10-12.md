# Status report — 2026-10-12

Everything below is measured on miniF2F-valid (244 problems) unless stated otherwise. Links point to the result
folders with full tables.

## 1. Ablation ladder so far

| Row | System | Solved | Source |
|---|---|---|---|
| 0 | Automation sweep only, no model | 79 (32.4%) | `phase0_automation_baseline/` |
| 1 | + few-shot Qwen3.5-2B (log-prob best-first) | 115 (47.1%); Base model 117 (48.0%) | `phase1_fewshot_search_*` |
| 2 | + SFT policy v1 / v2 | 148 (60.7%) / 148 (60.7%) | `phase2_sft_v1_search/`, `phase2_sft_v2_search/` |
| 4 | + value v0, A* (λ = 0.5) on SFT v1 / v2 | 155 (63.5%) / **157 (64.3%)** | `phase3_astar_v0/`, `phase3_astar_v0_sft_v2/` |
| 3 | + lemma retrieval | pending | — |
| 5 | + reasoning | pilot and comparison done, training pending a decision | `phase5_pilot/`, `phase5_compare/` |
| 6 | + expert iteration | loop built, launch pending | — |

- Budget: 16 samples per expansion, 64 expansions, 600 s. No row loses a theorem that row 0 solves.
- Row 4 beats row 2 with the SFT v2 policy by 12 new against 3 lost (sign test p ≈ 0.035).
- Expansions to solve (row 4, SFT v2): 89 / 123 / 138 / 144 / 153 / 157 solved within 1 / 2 / 8 / 16 / 32 / 64
  expansions.
- SFT v2 (60M tokens) equals SFT v1 (33M): more traced data of the same kind no longer helps.

## 2. Throughput and GPU utilization

### Training

On an idle node, padded SFT already ran at 98.5% GPU utilization. The low utilization seen during SFT v2 came from
the run sharing the node with ~60 unniced Lean processes (tracing and pool pre-filter) on the 46-core cgroup quota.

Separately, only ~51% of GPU time was matmuls; the rest was memory-bound element-wise work.

| Setup (SFT v2 data) | Tokens/s | GPU utilization |
|---|---|---|
| 1 GPU, padded (as SFT v2 ran) | 3,667 | 98.5% |
| 1 GPU, packed + compiled norms/MLP/mixer projections | 5,670 (+55%) | — |
| DDP, padded | 7,332 | 99% |
| DDP, packed + compiled | **10,724–10,911 (+48%)** | 98–99.9%, ~345 W |

Packing is leak-free: an example's losses are bitwise identical whatever its neighbours are.

### Search

| Setting (row 4, adapters, both GPUs) | Samples/s | GPU utilization | CPU cores used | cgroup throttled |
|---|---|---|---|---|
| 40 concurrent searches (as rows 2/4 ran) | 89 | 78–80% | 30 | 0% |
| + overlap policy request with the sweep, early value scoring | 94 | 70–73% | 32 | 0% |
| 120 concurrent searches | 138 (+56%) | 70–72% | 46 | 90% |
| 120, search pinned to 40 CPUs | 138 | 76–80% | 43 | 0% |

**At high concurrency the search is Lean/CPU-bound, not GPU-bound.**
- Row 4 costs ~5.6 Lean-seconds per expansion, so 46 cores cap the search at ~8.6 expansions/s.
- The two GPUs then use about a third of their generation capacity.
- Consequences:
  - Hardware scaling needs **CPU cores per GPU**, not just GPUs. InternLM2.5-StepProver reports a 1:11 GPU:CPU
    time ratio.
  - Cutting Lean cost per expansion is the cheapest lever. In the row-0 ablation, a 7-tactic sweep solved the same
    as 13 tactics at 3.5× less Lean time. A breakdown and reductions are being measured now.
  - With thinking enabled the balance flips back towards the GPU (more tokens per Lean call).

### Publishing and re-scoring

| Operation | Time |
|---|---|
| Merge LoRA into the base model (CPU) | 17 s |
| Warm vLLM restart with LoRA | 93–95 s |
| In-place weight reload / sleep-wake | being measured |
| Re-score open frontier (value model) | 118 states/s: ~60 s at 120 searches (~7k open states) |

Re-scoring is gated: it is skipped automatically when the measured rate predicts more than 60 s.

## 3. Reasoning (thinking before each step)

All arms run on the same 512 traced states, with k = 8 and temperature 0.8. Success = the block applies and closes the
goal or reaches a state of the reference proof.

| Arm | Success / sample | Any of 8 | Truncated | Tokens / sample | Tokens / success |
|---|---|---|---|---|---|
| SFT v2, no thinking | 48.2% | 74.8% | 1.4% | 32 | **67** |
| Base, no thinking, zero-shot | 7.2% | 30.1% | 2.9% | 109 | 1,519 |
| Base, no thinking, few-shot | 11.4% | 35.8% | 5.5% | 109 | 962 |
| Base, thinking, cap 4096 | 4.5% | 18.0% | 52.3% | 2,700 | 60,636 |
| SFT v2, thinking, cap 4096 | 20.7% | 55.0% | 34.0% | 1,935 | 9,352 |

Findings:

1. **SFT did not destroy reasoning; it improved it.** SFT v2 thinking beats base thinking 20.7% vs 4.5% per sample.
   On the 48 states SFT never saw: 3.6% vs 0.8% (small sample).
2. The base model reasons poorly even with 4,096 tokens: worse than its own non-thinking prompts, and over half its
   samples are still thinking at the cap.
3. **Short thoughts work best.** SFT v2 thinking succeeds 46% at 32–255 reasoning tokens, then 32% / 28% / 24% / 18%
   for 256–511 / 512–1,023 / 1,024–2,047 / 2,048–4,095 tokens. Long thoughts are mostly repetitive enumeration.
4. SFT broke the answer format in thinking mode: 13% never close `</think>`, 22% omit the opening fence. Recovery
   parsing and correctly formatted training targets address this.
5. **Cost:** thinking needs 60–140× the tokens per success of non-thinking, depending on the cap
   (3,063 / 4,089 / 6,042 / 9,352 at caps 512 / 1,024 / 2,048 / 4,096).

Literature:
- **Lean-STaR** (per-step thoughts) gained ~4 points over no-CoT at equal samples × steps.
- **DeepSeek-Prover-V2** whole-proof CoT wins at roughly matched tokens.
- Current step provers (BFS-Prover V1/V2, Hunyuan, MPS, InternLM2.5) use no per-step CoT.

Options for row 5:

- **A.** Round 1 as planned (cap 2,048, 6k states, ~2.3 h). Likely trips the 10× stopping rule.
- **B (recommended).** Round 1 aimed at *short* reasoning: cap 1,024, keep only the shortest successful thought per
  state.
  - If training reproduces the ~46% success of short thoughts at ~200 tokens, tokens per success fall to ~400 (≈6×
    non-thinking) and pass the rule.
  - Cost ~1.2 h.
- **C.** Report row 5 as negative at equal compute now.

## 4. Value model

| Value v0 | Bin accuracy | MAE (steps) | Spearman | Dead-vs-alive AUC |
|---|---|---|---|---|
| Zero-shot | 27.3% | 2.35 | −0.03 | — |
| Trained on traced human proofs | 53.2% | 1.26 | 0.80 | — |
| On search trees (row 2 / row 4) | — | — | 0.70 / 0.73 | 0.46 / 0.45 |

- Ranking states by remaining steps works. **Dead ends are invisible** because v0 never saw one: they score
  h ≈ 2.3, close to real near-proofs, so the search keeps visiting them. Value v1 from the loop's search trees learns
  dead labels; the readout then puts dead states at a large cost, so they sink in the queue.
- **Priority** for the loop: predicted remaining steps dominate (h + 0.25 · depth).
- **Literature:** value models help most when mixed with the policy prior.
  - InternLM2.5's critic-only search lost to log-prob search at pass@1.
  - LeanProgress's remaining-steps model alone collapsed, but mixed in at weight 0.2 it helped.
  - HunyuanProver's distance critic added 3.6 points.

  Worth testing: priority = h + w_d · depth − w_p · (normalized log-probability).

## 5. Lemma retrieval

| Retriever (ReProver, off the shelf) | R@8 | R@32 | Hit@8 | Hit@32 |
|---|---|---|---|---|
| LeanDojo novel_premises test (upper bound, likely in its training data) | 0.55 | 0.75 | 74% | 88% |
| **Held-out competition steps (honest number)** | **0.16** | **0.33** | **22%** | **43%** |

- The premise index has 199,810 entries: the LeanDojo corpus plus 25,556 `to_additive`/alias theorems it misses
  (`add_comm`, `mul_pos`, `sub_nonneg`, …), which are 25% of the theorem names competition proofs mention.
- Only 39% of competition steps use any library theorem, so retrieval can matter for at most those.
- **Prompt content per lemma:** name, compact signature, and Lean's applicability note (e.g. `-- rw: leaves 1 goal`),
  ~25 tokens. 64 lemmas ≈ 1.6k prompt tokens, prefilled once per expansion and shared by all 16 samples.
- **Annotation follow-up** ("apply, then automation closes it"): changes the note on only 1.3% of states the search
  would annotate, at +31% Lean time. Off by default.
- **Next:**
  1. Fine-tune the retriever contrastively on 138k competition queries (≤ 1 h GPU).
  2. Lemma-aware SFT (~15M tokens, lists of 0/16/32/64).
  3. End-to-end ablation with 0 / 16 / 64 lemmas on 64 hard miniF2F-valid problems at 32 expansions.

## 6. Expert-iteration loop (agreed design, implemented)

- **Search workers** process many statements concurrently (120 in flight). Each runs best-first search ordered by
  the value model. Expansions use 16 policy samples, the automation sweep and value scoring of children.
- **Budget escalation on the same tree:**
  - 32 expansions for every statement;
  - up to 128 if the best open state's prediction is ≤ 3 steps;
  - up to 512 if it is ≤ 2.
- **Harvest:** after a proof, expand open states predicted ≤ 1.5 steps from done (≤ 8 extra expansions) to collect
  more complete proofs.
- **Training phase** (every 400 proofs or 60 min):
  1. Workers pause in place, keeping their trees and Lean states.
  2. Policy (DPO + NLL on chosen) and value (bin cross-entropy with dead and censored labels) train from FIFO replay
     buffers prefilled with dataset samples, at reuse 1.0 and capacity ~3.5 phases.
  3. Publish the new models, re-score the frontier if that takes under 60 s, and resume.
- **Negative pairs, by priority:**
  1. Siblings that lead into dead subtrees.
  2. Lean errors (capped; they mostly teach syntax).
  3. Value-jump pairs (chosen child predicted ≤ 1.5 steps, sibling ≥ 3 steps worse). Gated on the value model being
     well-conditioned: Spearman ≥ 0.7 and dead AUC ≥ 0.75 on fresh held-out trees.
- **Pool:** 255,622 decontaminated statements; statements whose proofs were in SFT are excluded.
- **Throughput model:** statements/hour ≈ 3600 · S · d / (16 · E), with S samples/s, d ≈ 0.85 search duty and
  E ≈ 60 expansions per statement on average under escalation.
  - At S = 89–138: ~175–270 statements/hour, ~40–80 new proofs/hour.
  - That is Polu-2022 scale (~33k searches per iteration), not 2025 scale.

## 7. Literature summary

Full tables with sources: `results/literature/README.md`.

| Quantity | Ours | Literature |
|---|---|---|
| Samples per expansion | 16 | 2–3 (BFS-Prover), 6 (AlphaProof), 8 (Polu, Hunyuan, MPS), 32 (GPT-f, InternLM), 64 (ReProver) |
| Expansions per attempt (eval) | 64 | 100–5,000; 400–800 for current 7B step provers |
| Generations per theorem (eval) | ~1,024 | 3,200–4,096 cheapest pass@1; 1.6–4.9M for headline 7B results |
| Expert-iteration budget per statement | 32 → 128 → 512 expansions | Polu 4,096 generations; InternLM2.5 10 → 2,000 iterations; AlphaProof 250 → 16,000 simulations |
| Pool / rounds | 255k pool, ~4–8k statements/day | Polu 31k pool × 8 iterations; InternLM2.5 82k; BFS-Prover ~900k × 10; BFS-V2 ~3M |

Takeaways:

- We search **wide and shallow**; current step provers search **narrow and deep**. A budget-shape test at equal
  generations (16×64 vs 4×256 vs 2×512) is worth running.
- Solve rate scales log-linearly with search budget everywhere.
- Unsolved statements eat the compute (InternLM2.5: 98.5% of CPU on never-solved statements), and many are
  misformalized (Goedel-V2: >80% of sampled unsolved problems). Escalation plus **attempting the negation** is
  standard (DeepSeek V1, InternLM2.5, AlphaProof).
- Repeated cheap attempts with refreshed models beat one expensive attempt (Polu, HTPS). Periodic retraining from
  the base model avoids plateaus.

## 8. Decisions for the owner

1. **Reasoning:** option A, B (recommended) or C from section 3.
2. **Hardware:** the search is CPU-bound at high concurrency. Before adding GPUs, (a) cut Lean cost per expansion
   (being measured), then (b) prefer nodes with more CPU cores per GPU (~40–60 cores per GPU at current Lean cost).
3. **Literature-driven additions to the loop:** attempt the negation of unsolved statements; mix the value model
   with the policy prior; run a budget-shape test before launch.

## 9. Next on the GPUs

1. Performance work, ~1.5 h: merged serving, publish timing, Lean-cost breakdown and reductions, row-4
   re-validation.
2. Retrieval, ~2.5 h: retriever fine-tune, lemma-aware SFT, 0/16/64 ablation.
3. Reasoning round 1, if option A or B: 1.2–2.3 h.
4. Expert-iteration loop launch with the improved serving and Lean settings.
