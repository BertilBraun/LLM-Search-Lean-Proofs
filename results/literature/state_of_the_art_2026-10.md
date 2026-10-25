# Literature survey: LLM-guided Lean 4 theorem proving, with a focus on small models and low budgets (as of 2026-10-25)

Most numbers come from the arXiv HTML or abstract pages, read through a summarizing fetch tool. Anything marked **(2nd-hand)** comes from press, an aggregator or a citing paper and was not checked against the primary source. Budget notation:
- **K×W×N** = passes × tactics sampled per expansion × expansions.
- **pass@k** = k whole-proof samples.
- Your budget in this notation is about **1×16×64 ≈ 1k tactic generations**.

## 1. State of the art on miniF2F

| System (arXiv) | Date | Size | Approach | Budget | test | valid | Lean |
|---|---|---|---|---|---|---|---|
| DeepSeek-Prover-V1.5-RL (2408.08152) | 2024-08 | 7B | Whole proof, short NL comments | pass@32 / 3200 / 16×6400 | 50.0 / 54.9 / 60.2 | – | 4.9.0-rc1 |
| same + RMaxTS | | 7B | Tree search over whole proofs | 1×3200 / 32×6400 | 55.0 / 63.5 | – | |
| InternLM2.5-StepProver (2410.15700) | 2024-10 | 7B + 1.8B critic | Step-level BFS + critic | 256×32×600 | 65.9 | 69.6 | |
| HunyuanProver (2412.20735) | 2024-12 | 7B | Step-level BFS + distance critic | 600×8×400 | 68.4 | – | |
| STP (2502.00212) | 2025-02 | 7B | Whole proof, self-play | pass@128 / 3200 / 25600 | 61.2 / 65.0 / 67.6 | – | |
| Goedel-Prover-SFT V1 (2502.07640) | 2025-02 | 7B | Whole proof, expert iteration | pass@32 / 3200 | 57.6 / 62.7 | – | |
| BFS-Prover V1 (2502.03438) | 2025-02 | 7B | Step-level BFS, no critic | 2048×2×600 / accumulative | 70.83±0.89 / 72.95 | – | |
| Leanabell-Prover V1, GD-RL (2504.06122, numbers via 2507.08649) | 2025-04 | 7B | Whole proof | pass@32 / 128 | 59.8 / 61.1 | – | 4.9 |
| Kimina-Prover-Preview (2504.11354) | 2025-04 | 72B | Whole proof, long CoT | pass@1 / 32 / 8192 | 52.94 / 68.85 / 80.74 | – | DS-V1.5 env |
| Kimina-Preview-Distill | 2025-04 | 1.5B | Whole proof, long CoT | pass@1 / 32 / 1024 | 42.6 / 56.2 / 61.9 | – | |
| Kimina-Preview-Distill | 2025-04 | 7B | Whole proof, long CoT | pass@1 / 32 / 1024 | 52.5 / 63.1 / 70.8 | – | |
| DeepSeek-Prover-V2, non-CoT (2504.21801) | 2025-04 | 7B | Whole proof | pass@1 / 32 / 1024 / 8192 | 55.5 / 68.0 / 73.2 / 75.0 | – | 4.9.0 |
| DeepSeek-Prover-V2, CoT | 2025-04 | 7B | Whole proof, long CoT | pass@1 / 32 / 1024 / 8192 | 58.6 / 75.6 / 79.9 / 82.0 | – | |
| DeepSeek-Prover-V2, CoT | 2025-04 | 671B | Subgoal decomposition, CoT | pass@1 / 32 / 8192 | 61.9 / 82.4 / 88.9 | 91.0 (curriculum + 8192) | |
| MPS-Prover (2505.10962) | 2025-05 | 7B | Step-level, critic + heuristics | 1×4×800×8 / 64× / accumulative | 67.6 / 72.5 / 75.8 | – | |
| Kimina-Prover (HF blog, kimina-prover) | 2025-07 | 72B | Long CoT | pass@1 / 32 / 1024; TTRL | 63.9 / 84.0 / 87.7; 92.2 | – | |
| Kimina-Prover distills (same blog) | 2025-07 | 8B / 1.7B | Long CoT | pass@1 / 32 | 61.1 / 78.3 and 46.7 / 73.4 | – | |
| Kimina-Prover-RL (HF blog, kimina-prover-rl) | 2025-08 | 1.7B / 0.6B | Long CoT, RL | pass@32 | 76.6 (table says 76.23; 77.87 with error fix) / 71.3 | – | |
| Leanabell-Prover-V2-DS (2507.08649) | 2025-07 | 7B | Verifier-in-the-loop RL | pass@32 / 128 | 76.6 / 78.2 | – | 4.9 |
| StepFun-Prover Preview (2507.20199) | 2025-07 | 7B / 32B | Tool-integrated RL | pass@1 (20k tokens) | 66.0 / 70.0 | – | 4.20 |
| Delta-Prover (2507.15225) | 2025-07 | General LLM, no training | Agentic decomposition | accumulative | 95.9 | – | |
| Seed-Prover 1.0 (2507.23726) | 2025-07 | Closed | Lemma-style, iterative refinement | heavy | 99.6 (2nd-hand, from 2509.06493 table) | – | |
| Goedel-Prover-V2 (2508.03613, ICLR'26) | 2025-08 | 8B | Whole proof + self-correction | pass@32 / 1024 / 8192 | 84.6 / 87.9 / 90.2 (self-correction: 86.7 / 89.3) | – | 4.9.0-rc1 |
| Goedel-Prover-V2 | 2025-08 | 32B | same | pass@32 / 1024 / 8192 | 88.1 / 91.8 / 92.2 (self-correction: 90.4 / 92.6) | – | |
| BFS-Prover-V2 (2509.06493) | 2025-09 | 7B / 32B | Step-level BFS, multi-turn off-policy RL | accumulative | 82.4 / 86.1 | 32B: 85.5 | 4.10 |
| BFS-Prover-V2 32B + Gemini-2.5-Pro planner | 2025-09 | 32B + planner | Planner + parallel step provers | accumulative | 95.08 | 95.49 | |
| Hilbert (2509.22819, ICLR'26) | 2025-09 | Gemini-2.5-Pro + Goedel-V2-32B | Agentic, informal + formal | adaptive, up to ~22.8M tokens on hard problems | 99.2 (98.4 with DS-V2-7B prover) | – | |
| Aristotle (2510.01346) | 2025-10 | Closed | Agentic, IMO-gold system | – | Not reported in the paper; a 2024 blog claims 90% on Harmonic's own re-split | | |
| Pythagoras-Prover (2606.12594) | 2026-06 | **4B** / 32B | Whole proof, augmented formalization data | pass@32 / 1024 / 2048 | 4B: **86.1** / 88.1 / 89.8; 32B: 89.8 / 92.6 / 93.0 | – | 4.9.0-rc1 |
| NanoProof (2610.11605) | 2026-10 | ~1B | AND-OR MCTS, AlphaProof-like, critic = remaining depth | pass@16 at 512 sims | 50.8 | 51.3 (256 sims) | 4.27 |
| Leanstral 1.5 (Mistral blog) | 2026-07 | 119B MoE (6B active) | Agentic | not stated | 100 (vendor claim) | 100 (vendor claim) | |
| AlphaProof (Nature, 2025-11) | 2025-11 | – | AlphaZero-style RL + test-time RL | – | No miniF2F number found | | |

**Saturated (>95%):** Seed-Prover 1.0, Delta-Prover, Hilbert, BFS-Prover-V2 with planner, Leanstral 1.5 (claim). Every one of these uses a large or closed general reasoner or agentic loop. The best open single provers at pass@32 are Goedel-V2-32B (88–90%) and Pythagoras-4B (86.1%).

## 2. Small-model frontier on miniF2F-test

| Class | Best whole-proof result | Low-budget points | Step-level points |
|---|---|---|---|
| ≤1B | Kimina-RL-0.6B: 71.3 @32 | – | NanoProof-1B: 50.8 @16 |
| ≤2B | Kimina-RL-1.7B: 76.6 @32 | Kimina-Distill-1.7B: 46.7 @1, 73.4 @32 (the model card says 72.95 @32); Kimina-Preview-Distill-1.5B: 42.6 @1, 56.2 @32 | None found |
| ≤4B | **Pythagoras-4B: 86.1 @32** (pass@1 not reported) | – | None found |
| ≤8B | Goedel-V2-8B: 84.6 @32, 86.7 @32 with self-correction; curve 86.1 @64, 87.0 @256, 87.9 @1024, 90.2 @8192 | DS-V2-7B CoT: 58.6 @1, 75.6 @32; DS-V2-7B non-CoT: 55.5 @1, 68.0 @32; Kimina-8B: 61.1 @1, 78.3 @32; StepFun-7B: 66.0 @1 | BFS-V2-7B 82.4 (accumulative); MPS-7B 67.6 (single pass, ~25.6k generations); InternLM2.5 single pass (32×600 = 19.2k generations): **47.3 test / 55.4 valid** |

Budget-curve sources:
- **Full pass@k curves:** Goedel-V2 (Table 4 of 2508.03613), Kimina-Preview (2504.11354), DS-V2 (Table 1 of 2504.21801).
- **Step-level, critic vs. no critic by passes:** InternLM2.5. Test, BF/CG: 47.3/43.0 at 1 pass, 52.6/56.1 at 4, 57.3/61.7 at 16, 59.2/64.3 at 64, 59.4/65.6 at 256. Valid, BF/CG: 55.4/49.4, 61.3/55.9, 63.7/64.5, 64.6/67.7, 65.1/68.4.
- **BFS-V1, passes 64→2048 (each pass is ×2×600):** 64.98 → 70.83.

**Token costs are key for a matched comparison.** Average output tokens per proof (2504.21801, Table 3) are 442.6 for DS-V2-7B non-CoT and 4488.5 for CoT. So pass@32 costs about 14k tokens (68.0%) without CoT and about 144k tokens (75.6%) with CoT. Goedel-V2 allows up to 30k tokens per sample, and Pythagoras averages about 18.7k tokens per attempt, so their pass@32 runs are several hundred thousand tokens.

## 3. Is miniF2F still meaningful?

**Statement errors.** miniF2F-Lean Revisited (2511.03108, NeurIPS'25):
- More than 300 statements corrected; 16 are unprovable (13 test, 3 valid).
- Simplified: 40 test / 48 valid. Excessively simplified: 45 test / 36 valid.
- It releases miniF2F-v2s and v2c.
- Accuracy at pass@32 drops from v1 to v2c:

| Prover | test | valid |
|---|---|---|
| Goedel-V2 (size not confirmed) | 82.0 → 72.5 | 83.6 → 73.4 |
| DS-V2-7B | 73.4 → 64.4 | 79.4 → 70.5 |
| Kimina-Distill-7B | 65.2 → 57.0 | 73.0 → 67.6 |

**Other fixes:**
- DSP+ (2506.11487) found 8 incorrect test problems.
- Kimina fixed 5 unprovable statements. Most 2025–26 papers use this Kimina-revised set.
- Harmonic (2024) and a DeepMind fork also released corrected versions.

**Saturation.** Pythagoras (2606.12594) reports that 83.2% of problems are solved by all four models in its panel and only 9% by none. It proposes **miniF2F-ALF**, a mutated test set, on which the 32B scores 85.0, the 4B 83.2, and Goedel-V2-32B 83.6.

**Benchmarks in current use and their SOTA:**
- **PutnamBench (672 problems):**
  - Agentic, large models: Seed-Prover 1.5 about 88% (2512.17260); Leanstral 1.5 587/672 at pass@8 with 4M tokens per attempt, scaling 44 → 244 → 493 → 587 at 50k → 200k → 1M → 4M tokens; Hilbert 462/660; Aleph 668/672 (vendor, 2nd-hand); NEAR agent 672/672 (press, 2nd-hand).
  - Open single provers: Pythagoras 48 @32 and 93 @2048; Goedel-V2-32B 43 @32, 57 with self-correction, 86 @184; DS-V2-671B 22 @32, 47 @1024.
  - Small models are far behind: Kimina-7B-Distill 10 @192.
- **ProofNet-test:** BFS-V2-32B 41.4; DS-V2-671B 37.1; MPS-7B 32.97; InternLM2.5 about 27.
- **ProverBench (325):** DS-V2-671B CoT 59.1 @512; DS-V2-7B 51.7 @512.
- **FormalMATH (5,560, 2505.02735):** best 16.46% "under practical budgets".
- **FATE-H / FATE-X:** Seed-1.5 80/33; Leanstral 87/34.
- **Also in use:** MathOlympiadBench (Goedel-V2), miniF2F-v2, miniF2F-ALF. I did not verify CombiBench numbers.

## 4. Per-step natural-language reasoning

- **Lean-STaR (2407.10040, ICLR'25):** a thought before each tactic, trained with STaR and expert iteration.
  - InternLM2-7B at equal sampling budget: 29.5 → 34.8 @32 and 30.3 → 36.1 @64. InternLM2-plus-7B: 43.4 → 46.3 @64.
  - **Key finding: best-first search worked poorly with thoughts** because average log-probabilities become unreliable. So the authors used independent sampled trajectories (S=1, N=50) instead of tree search.
  - They did not compare thought lengths or a think-block against short thoughts.
- **DeepSeek-Prover-V1.5 and V2:** natural-language comments or long CoT inside whole proofs. V2-7B goes from 68.0 to 75.6 @32, but at about 10× the tokens.
- **StepFun-Prover (2507.20199):** interleaves reasoning with REPL calls. Accuracy grows with token budget, from 58.3 at 4k to 70.0 at 20k tokens.
- **Leanabell-V2 (2507.08649):** verifier feedback inside the reasoning.
- **No reasoning per step:** BFS-Prover V1/V2, MPS, InternLM2.5 and HunyuanProver generate tactics only. BFS-V2 puts natural language only in an external Gemini planner that produces subgoals. REAL-Prover (2505.20613) also emits tactics only.
- **Forgetting:** "Awakening the Sleeping Agent" (2604.08388) shows Goedel-Prover-V2 tool-calling collapsing from 89.4% to about 0% after specialization. About 100 agentic traces restored it to 83.8% on BFCL and raised ProofNet from 21.5 to 25.8 @32. NAACL'25 (2025.naacl-long.584) finds fine-tuning degrades CoT more in small models.

**Novelty assessment.** I found no paper that, inside step-level best-first or A* search, compares short visible per-step rationales against a think-block against no reasoning at matched expansions or tokens. Lean-STaR is the closest prior work: it established that per-tactic thoughts help under sampling and reported that they break log-probability BFS. Your result, a learned value heuristic that makes thought-augmented best-first search work plus a ranking of short over think-block over none at equal expansions, appears new. It is still incremental relative to Lean-STaR. To claim it you should report tokens as well as expansions, because the short-rationale arm used about 94k tokens per theorem.

## 5. Expert iteration and RL compute; value models

**Expert-iteration and RL compute:**

| System | Compute reported | Rounds / output |
|---|---|---|
| Goedel V1 | Per round: inference 6 h on 64 H100, training 12 h on 4 H100, verification 10 h on 8,000 CPUs | 8–9 rounds; Lean Workbook solved 20.6K → 30.3K (about 1K per round); formalized-set proofs 72K → 928K |
| InternLM2.5 | 21,364 CPU-days; final iteration 14 h on 32 A800; 2.19B tokens | 14,075 Lean-Workbook problems proved or disproved (vs 7,909 for the previous version) |
| MPS | Training 3 days on 8 H20 | 26 rounds, more than 30K theorems |
| BFS-V1 | 8 A100 machines (number of machines unclear) | 10 rounds; no per-round gains given |
| BFS-V2 | About 10⁷ tree searches per round | "Dozens" of rounds, about 3M statements |
| STP | TPU (amount not given) | 48 iterations, 241M proofs, 51.3B tokens |
| HunyuanProver | Not given | More than 10 rounds, 20M tactic examples; gains flatten after v8 |
| Kimina-RL | **48 h on 8 H100** | 1.7B reaches 76.6 @32 |
| NanoProof | **SFT 16 h on 4 A100, RL 45 h on 4 MI250**, about 3.8×10⁸ TFLOPs | 50.8 @16; claims about 90× less than HTPS and 7× less than ABEL |
| AlphaProof | About 2.4×10¹³ TFLOPs (NanoProof's estimate) | About 80M autoformalized statements (2nd-hand) |

STP reports that **plain expert iteration plateaus** because rewards are sparse: only 131 of 2.5M proofs for unproved statements were correct. Its self-play conjecturing doubled Lean Workbook coverage (13.2 → 28.5%).

**Your compute, as a rough estimate of mine:** 2×3090 for 10 days is about 480 GPU-hours, perhaps about 100–150 H100-hours equivalent. That is around one third to one half of Kimina-RL and roughly NanoProof scale. It is far below a single Goedel round.

**Value and critic models:**

| Work | Gain reported |
|---|---|
| InternLM2.5 critic (1.8B, 78% pairwise accuracy) | +6.2 test at 256 passes, but **−4.3 test and −6.0 valid at 1 pass** ("may overlook simple proofs") |
| HunyuanProver distance critic | +3.7 (64.75 → 68.44) |
| MPS critic | 177 vs 164 of 244 without it (+5.3) |
| LeanProgress remaining-steps (2502.17925) | 75.8% prediction accuracy; +3.8% on Mathlib (41.4 baseline) with ReProver |
| NanoProof critic | Predicts remaining depth; no ablation |

Your +9 problems (+3.7 pt) from the value model at a single pass contradicts InternLM2.5's low-budget degradation, which makes it a useful data point.

## 6. Compute-efficiency framing

- **Pythagoras:** "effective token complexity" (about 1.85–1.95×10¹¹ at matched points). It finds self-correction better at small budgets and independent restarts better at large ones.
- **Leanstral:** reports solved problems against tokens per attempt.
- **StepFun:** reports accuracy against maximum generation length.
- **DS-V2:** reports tokens per proof.
- **VERITAS (2606.19399):** solve rate against Lean calls; 40.6% at about 27 calls.
- **Cost-quality agent (2606.04883):** −28.9% cost at equal accuracy on PutnamBench.
- **ProofCompass (2507.14335):** 55.3 @128 vs 54.9 @3200 for DS-V1.5.
- **Prover Agent (2506.19923):** 88.1% at a "budget of 260" with small language models (budget figure 2nd-hand).
- **Tactic skeletons (2601.16172):** DS-V1.5-RL does not improve from k=32 to k=64 (42/244 under their setup).
- **Lean-side efficiency:** proof-state snapshotting (2605.25556) gives 9.7× median wall-time speedup; NanoProof.
- **Gap:** no paper compares step-level and whole-proof provers of matched size at matched total tokens plus Lean calls at about 1k generations.

## Where you stand (4B step prover, ~1k generations, 70.1% valid)

- **Era.** Valid usually runs 0–6 points above test (InternLM2.5 65.9/69.6; BFS-V2 86.1/85.5; DS-V2-7B 73.4/79.4 in 2511.03108). So 70.1% valid suggests roughly 64–70% test. That is the late-2024 to early-2025 step-prover SOTA (InternLM2.5, HunyuanProver, BFS-V1), reached with **about 20–5,000× fewer tactic samples per theorem**.
- **Same budget class (1 pass, ~1k–25k generations).** You clearly beat InternLM2.5 single pass (55.4 valid at 19.2k generations) and are around MPS single pass (67.6 test at ~25.6k generations).
- **Same size and tokens.** You are well behind 2025–26 whole-proof models:
  - Pythagoras-4B: 86.1 test @32, at about 600k tokens.
  - Kimina-1.7B: 73.4–76.6 @32.
  - DS-V2-7B non-CoT: **68.0 test @32 with only about 14k tokens**. That is about 7× fewer tokens than your 94k for a comparable or slightly lower test-equivalent score.
- **Bottom line.** You are competitive among step-level search methods at very low budget, but not at the frontier of models your size. Running miniF2F-test (Kimina-revised) and miniF2F-v2c is necessary before any external claim.

## Key papers

1. Goedel-Prover-V2, 2508.03613: best open 8B/32B pass@k curves.
2. Pythagoras-Prover, 2606.12594: 4B at 86.1 @32; miniF2F-ALF.
3. DeepSeek-Prover-V2, 2504.21801: CoT vs non-CoT tokens and scores; ProverBench.
4. Kimina-Prover Preview (2504.11354) and HF blogs: 0.6B–1.7B distill and RL; RL on 8 H100 for 48 h.
5. BFS-Prover V1 (2502.03438) and V2 (2509.06493): step-level BFS scaling; planner reaches 95%.
6. InternLM2.5-StepProver, 2410.15700: critic gains by pass count; critic hurts at 1 pass.
7. HunyuanProver, 2412.20735: distance critic +3.7.
8. MPS-Prover, 2505.10962: single-pass step search at 67.6; critic ablation.
9. Lean-STaR, 2407.10040: thought before each tactic; BFS breaks with thoughts.
10. STP, 2502.00212: expert iteration plateau; self-play.
11. miniF2F-Lean Revisited, 2511.03108: errors; v2; 8–10 point drops.
12. NanoProof, 2610.11605: ~1B, tiny compute, remaining-depth critic.
13. Hilbert, 2509.22819: agentic 99.2%; PutnamBench 70%.
14. Seed-Prover 1.0 (2507.23726) and 1.5 (2512.17260): saturation; PutnamBench about 88%.
15. Awakening the Sleeping Agent, 2604.08388: capability suppression in provers.

## Open gaps a small-budget project could address

- **Matched-cost comparison.** A careful study of step-level versus whole-proof generation at matched tokens and Lean calls in the about 1k-generation regime, for models ≤4B. Nobody has published this, and it plays to your strengths.
- **Reasoning length per step under value-guided best-first search.** Short visible rationale vs. think-block vs. none at matched expansions **and tokens**. This extends Lean-STaR, which never made thought-augmented BFS work. Appears novel.
- **Value models at very low budget.** Your positive result conflicts with InternLM2.5's negative 1-pass result. A remaining-steps critic is covered conceptually by LeanProgress, HunyuanProver and NanoProof, but not in this regime.
- **Evaluating on corrected benchmarks** (miniF2F-v2c, ALF) at low budget. Few small-model numbers exist.
- **Forgetting.** Keeping general reasoning when LoRA-tuning a reasoning model into a step prover. Only lightly studied (2604.08388).

**Already covered by prior work:**
- Step-level best-first search with a critic (InternLM2.5, Hunyuan, MPS).
- Expert iteration in general, and its plateau (STP).
- Remaining-steps value models (LeanProgress, NanoProof).
- Automation sweeps (standard practice).
- Per-tactic thoughts in general (Lean-STaR).
- Distilling a teacher's reasoning into a small prover (Kimina distills).

Expert iteration at your rate (25–35 proofs per hour) is unlikely to produce publishable gains. Small-compute RL successes, such as Kimina-RL at 384 H100-hours and NanoProof, used much stronger starting models or tiny models with dense RL.
