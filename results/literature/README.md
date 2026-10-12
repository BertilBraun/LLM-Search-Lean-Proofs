# Literature: search budgets and training scale of LLM provers

Compiled 2026-10-12 from primary sources (arXiv papers, Nature paper and supplement, official repositories).
miniF2F-test unless noted; GPT-f/PACT/Polu 2022/HTPS used Lean 3 or Metamath. `*` marks arithmetic from stated
values. "Accumulative" = union over runs/settings, not pass@k.

## Evaluation budget per theorem (step-level / tree search)

| System | Model | Samples per expansion | Expansions per attempt | Attempts | Result | Source |
|---|---|---|---|---|---|---|
| GPT-f (Metamath) | ~700M | 32 | 128–256 | 4–32 | 56.2% (Metamath test) | [2009.03393](https://arxiv.org/abs/2009.03393) |
| PACT | 837M | ≤16 queue width | ≤512 | 1 | 48.4% (mathlib test) | [2102.06203](https://arxiv.org/abs/2102.06203) |
| Polu et al. 2022 | 774M | 8 | 512 | 1 / 8 / 64 | 29.6 / 34.5 / 36.6% | [2202.01344](https://arxiv.org/abs/2202.01344) |
| HTPS | 600M | 8–48 | 5,000 | 64 | 41.0% | [2205.11491](https://arxiv.org/abs/2205.11491) |
| ReProver | 299M | 64 (beam) | 10-min timeout | 1 | 26.5% | [2306.15626](https://arxiv.org/abs/2306.15626) |
| Lean-STaR | 7B | 1 (thought + tactic, no tree) | ≤50 steps | 32 / 64 | 34.8 / 36.1% | [2407.10040](https://arxiv.org/abs/2407.10040) |
| InternLM2-StepProver | 7B | 32 | 100 | 1 / 64 | 48.8 / 54.5% | [2407.17227](https://arxiv.org/abs/2407.17227) |
| InternLM2.5-StepProver | 7B + critic | 32 | 600 | 1–256 | 65.9% | [2410.15700](https://arxiv.org/abs/2410.15700) |
| HunyuanProver | 7B | 8 | 400–800 | 600 | 68.4% | [2412.20735](https://arxiv.org/abs/2412.20735) |
| BFS-Prover | 7B | 2 | 600 | 2,048 | 70.8% (72.95% accumulative) | [2502.03438](https://arxiv.org/abs/2502.03438) |
| BFS-Prover-V2 | 7B / 32B (+ planner) | 3 | not stated | accumulative | 82.4% / 86.1% / 95.1% | [2509.06493](https://arxiv.org/abs/2509.06493) |
| MPS-Prover | 7B | 8 per node, 4 nodes/iteration | 800 | 1–64 | 72.5% | [2505.10962](https://arxiv.org/abs/2505.10962) |
| DeepSeek-Prover-V1.5 + RMaxTS | 7B | whole-proof completions from tree nodes | 6,400 generations/tree | 1–32 trees | 63.5% | [2408.08152](https://arxiv.org/abs/2408.08152) |
| AlphaProof | 3B | 6 + progressive sampling | ~4,000 simulations; RL 250 → 16,000 | multiple | 96–99.6% (own corrected miniF2F) | [Nature](https://www.nature.com/articles/s41586-025-09833-y) |

Scaling with budget is consistently log-linear: BFS-Prover 64 → 2,048 passes: 65.0 → 70.8%; InternLM2.5 critic search
1/4/16/64/256 passes: 43.0/56.1/61.7/64.3/65.6%; MPS-Prover 1/4/16/64: 67.6/68.4/70.1/72.5%; GPT-f +2.5–4.4 points per
doubling of attempts.

## Search budget during expert iteration

| System | Per-statement budget | Escalation / filtering | Total | Source |
|---|---|---|---|---|
| Polu 2022 | 1 search (8 × 512 = 4,096 generations) per statement per iteration | global dedup; retrain from base each iteration | ~33k searches/iteration; ~2,000 A100-days total | [2202.01344](https://arxiv.org/abs/2202.01344) |
| HTPS | 1k–10k expansions, 8–48 samples, online | uniform over pool | each curriculum statement ~250 tries on day 1 | [2205.11491](https://arxiv.org/abs/2205.11491) |
| InternLM2.5-StepProver | ≤10 iterations / 50 s first, raised each round to ≤2,000 iterations / 3,600 s | drop solved statements and their negations; critic picks top 50% of unsolved | 21,364 CPU-days; 98.5% of CPU went to never-solved statements | [2410.15700](https://arxiv.org/abs/2410.15700) |
| BFS-Prover | beam-32 filter, then width 2/4/8 | statements solved by beam search excluded from training | not stated | [2502.03438](https://arxiv.org/abs/2502.03438) |
| AlphaProof | 250 simulations, ×1.17 per recent failure, cap 16,000 | 50% prove / 50% disprove; drop after 8 failures or 12 consecutive proofs | 80,000 TPU-days RL | [Nature](https://www.nature.com/articles/s41586-025-09833-y) |

## Training scale

| System | Statement pool | Rounds | Proofs | Model | Source |
|---|---|---|---|---|---|
| Polu 2022 | 25k mathlib + 5.6k synthetic + 327 curriculum | 8 | mathlib 76.0% proved; 100/327 curriculum | 774M | [2202.01344](https://arxiv.org/abs/2202.01344) |
| HTPS | mathlib-train + curriculum | online, 1–7 days | 139/327 after 7 days | 600M | [2205.11491](https://arxiv.org/abs/2205.11491) |
| InternLM2.5-StepProver | 82,275 (Lean-Workbook-plus) | several | 14,075 proved or disproved (17%) | 7B + critic | [2410.15700](https://arxiv.org/abs/2410.15700) |
| BFS-Prover / V2 | ~900k / ~3M | 10 / dozens | not stated | 7B / 32B | [2502.03438](https://arxiv.org/abs/2502.03438), [2509.06493](https://arxiv.org/abs/2509.06493) |
| MPS-Prover | Workbook + Numina + AoPS | 26 | >30k theorems, ~6M step pairs | 7B | [2505.10962](https://arxiv.org/abs/2505.10962) |
| DeepSeek-Prover V1 (whole-proof) | 712k | 4 | 8.07M proofs | 7B | [2405.14333](https://arxiv.org/abs/2405.14333) |
| Goedel-Prover (whole-proof) | 1.78M | 8 | ~958k solved | 7B | [2502.07640](https://arxiv.org/abs/2502.07640) |
| STP (whole-proof) | 89k + 3.6M conjectures | 48 | 241M proofs | 7B | [2502.00212](https://arxiv.org/abs/2502.00212) |
| AlphaProof | ~80M autoformalized | ~1M learner steps | not stated | 3B | [Nature](https://www.nature.com/articles/s41586-025-09833-y) |

## Reasoning before each step

- **Lean-STaR** (per-step thought): 34.8% vs 30.7% (no-CoT best-first) at equal samples × steps; best-first search
  combined poorly with thoughts.
- **DeepSeek-Prover-V2 7B** (whole-proof CoT): 75.0% → 82.0% at 8,192 samples, ~10× tokens per sample; at roughly
  matched tokens, CoT 79.9% (1,024 samples) vs no-CoT 75.0% (8,192 samples).
- **DeepSeek-Prover-V1.5:** CoT comments +2.8–3.3 points at equal samples.
- Step provers BFS-Prover V1/V2, HunyuanProver, MPS-Prover, InternLM2.5 use **no per-step CoT**; BFS-V2 adds an
  external planner.

## Where this project sits

| Quantity | Ours (2026-10-12) | Literature |
|---|---|---|
| Samples per expansion | 16 | 2–3 (BFS), 6 (AlphaProof), 8 (Polu, Hunyuan, MPS), 32 (GPT-f, InternLM), 64 (ReProver) |
| Expansions per attempt (evaluation) | 64 | 100–5,000; 400–800 for current 7B step provers |
| Generations per theorem (evaluation) | ~1,024 | 3,200–4,096 for the cheapest pass@1 setups; 1.6–4.9M for headline 7B results |
| Expert-iteration budget per statement | 32 → 128 → 512 expansions (512–8,192 generations) | Polu 4,096 generations; InternLM2.5 10 → 2,000 iterations; AlphaProof 250 → 16,000 simulations |
| Model size | ~2B | 0.3–0.8B (2020–23), 3B (AlphaProof), 7B (2024–25) |

Takeaways:

1. We search **wide and shallow**; current step provers search **narrow and deep** (2–8 samples, 400–800
   expansions). Worth a budget-shape comparison at equal generations (16×64 vs 4×256 vs 2×512).
2. Value models help most **mixed with the policy prior** (log-probability), not replacing it (InternLM2.5 critic
   lost to log-prob search at pass@1; LeanProgress remaining-steps model alone collapsed, mixed at weight 0.2 it
   helped; HunyuanProver distance critic +3.6 points).
3. Throughput: ~4–8k statements/day puts us at **Polu-2022 scale**, not 2025 scale.
4. Unsolved statements dominate compute and many are misformalized (Goedel-V2: >80% of sampled unsolved problems);
   escalation on promising statements plus **trying the negation** is standard (DeepSeek V1, InternLM2.5,
   AlphaProof).
5. Cheap repeated attempts with a refreshed model beat one expensive attempt (Polu, HTPS); periodically retraining
   from the base model avoids plateaus (BFS, Hunyuan, Polu, BFS-V2, STP).
