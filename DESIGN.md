# Design: LLM-guided best-first proof search in Lean 4

## Goal

Measure how far a small (~2B parameter) language model can be pushed on formal theorem proving when it is
combined with search, a learned value function and cheap training loops, on a budget of a few hundred dollars.
Success is a significant improvement over the base model **at fixed compute**, reported as solve-rate-vs-compute
curves and an ablation ladder on miniF2F. Reaching the published reference provers (70–95% on miniF2F) is not
the goal.

**Reframed 2026-10-25** (`results/literature/state_of_the_art_2026-10.md`, section "Next phase" below): the
project is a learning project on the reinforcement-learning stage of the LLM lifecycle, with Lean as a verifiable
target, written up on the owner's homepage. It is not aimed at a publication: miniF2F is saturated at the top
(95–100% with agentic systems) and whole-proof models of our size are far ahead (Pythagoras-Prover-4B 86.1% on
miniF2F-test at pass@32). The next phase is search-tree GRPO with a combined local and global reward.

## Benchmark and data

| Use | Data |
|---|---|
| Development | miniF2F-valid (244 problems) |
| Final numbers | miniF2F-test (244 problems), only for the final ladder |
| Policy SFT, value warm start, single-step reasoning prompts | Public competition-style Lean 4 proof corpora, re-run and traced in our pinned environment |
| Retrieval training and offline recall | Mathlib state/tactic/premise data (LeanDojo-style) |
| Expert iteration | Statement-only pools (Lean Workbook, Goedel-Pset, NuminaMath-Lean), decontaminated against miniF2F |

Nothing derived from miniF2F-test is ever used for training or for generating reasoning traces.

## Environment

- **Lean**: one pinned toolchain and Mathlib commit. Default is the de-facto miniF2F evaluation environment
  (Lean v4.9.0 with the Mathlib commit used by DeepSeek-Prover-V1.5), because the miniF2F statements and the
  largest public proof corpora are verified against it. The exact pin lives in `lean/lean-toolchain` and
  `lean/lake-manifest.json`.
- **Interaction**: the community Lean REPL (`leanprover-community/repl`) driven from Python. Proof states are
  immutable ids, so branching is free. Per-tactic heartbeat limits plus a wall-clock backstop; REPL processes
  are restarted when their memory grows past a threshold.
- **Models**: served by vLLM (OpenAI-compatible API). Policy and value are LoRA adapters on one base model.
- **Hardware**: one Vast.ai node (see `deployment/README.md`): 2× RTX 3090 24 GB, 46 effective CPU cores,
  ~120 GB RAM cgroup limit, 300 GB non-persistent disk. During search both GPUs serve; during expert iteration
  one GPU serves while the other trains. The node was returned after 2026-10-15 and is rented to others; the next
  phase needs a new node ("Next phase" below).
- **Throughput** (`results/gpu_utilization/`): training is GPU-bound (98–100%) with packed sequences and compiled
  element-wise layers (10.9k tokens/s on both GPUs, 1.5× the padded setup). Search at row-4 settings is bound by
  Lean CPU (~4.3 core-seconds per expansion with the 7-tactic sweep): 120 searches pinned to 40 CPUs reach
  ~150 samples/s, ~85% of what both GPUs serve (merged policy and value instances); CPU-heavy jobs run pinned
  (`deployment/background.sh`), because `nice` cannot prevent the cgroup quota from throttling GPU feeders.

## Search

A best-first search (A* with a learned heuristic) over proof states:

```
state
 → automation sweep, cheapest first, tight timeouts (results become children; a closing tactic ends the search)
 → retrieve ~100 lemmas → Lean applicability check → annotated, capped list         (Phase 4)
 → policy: one request, n = k samples (8–32), optional short thought, multi-line tactic block
 → run each block one top-level tactic at a time, keep the longest valid prefix as the child
 → value: prefill-only distribution over remaining-step bins                          (Phase 3)
 → priority queue on f = g + λ·h, de-duplicated by normalized goal text
```

- **Node** = the full proof state (all open goals). Goal-level AND/OR search is a possible later extension.
- **g** = depth (number of applied steps). Before a value model exists, the priority is the summed,
  length-normalized negative log-probability of the steps (GPT-f / BFS-Prover style).
- **h** = `Σ p_k · k + p_dead · D` over bins `1..7, 8+, dead`, where `D` is a fixed dead-end cost.
- **Budget** is compute-denominated: generated + prompt tokens on the GPU and Lean CPU-seconds, plus a cap on
  node expansions and wall-clock per theorem. Every comparison is made at equal compute and reported as
  solve-rate-vs-budget curves.

## Policy

- Base model chosen by a probe (Phase 1) among Qwen3.5-2B, Qwen3-1.7B and Qwen2.5-Math-1.5B: vLLM
  throughput at our prompt shape, valid-Lean rate and progress rate, measured few-shot and after an identical
  short LoRA SFT. The post-SFT numbers decide.
- LoRA on all linear layers (attention and MLP) with ~10× the full fine-tuning learning rate; one A/B against
  full fine-tuning on a small model confirms the gap is small. Adapters are merged for evaluation if merged
  inference is measurably faster than serving the adapter.
- Thinking is a toggle. SFT data without reasoning uses an empty thinking block, so the model keeps both modes.

## Value

- Classification over bins `1..7, 8+, dead`, read out as the weighted mean above (classification losses train
  value functions more stably than regression).
- Gaussian label smoothing across neighboring step bins; the dead class is never smoothed.
- Censored labels ("at least n more steps") use `−log P(remaining ≥ n)`.
- Served prefill-only: one forward pass, `max_tokens = 1`, probabilities read from the bin tokens.
- Warm start (v0) from traced human proofs: every state on a proof has a known remaining-step count (an upper
  bound). The dead class is learned from search trees.

## Training ladder

1. **SFT without reasoning** on traced state→step pairs (empty thinking block). Value v0 from the same proofs.
2. **Single-step on-policy reasoning** (thinking on): sample reasoning + step on traced states, reward = the step
   is valid and Lean reaches the reference next state or closes the goal. One Lean call per sample, no search.
   Trained by rejection sampling (fine-tune on successes) or GRPO.
3. **Search-based expert iteration** on the statement pool: label every search tree (table below); steps on found
   proofs, including their reasoning, become SFT data; sibling pairs with different outcomes become DPO pairs;
   groups of siblings feed GRPO once the pipeline is stable; the value model retrains on all labelled nodes.
4. Repeat 3.

| Node | Policy reward | Value target |
|---|---|---|
| On the found proof path | positive, larger for shorter remaining proofs | exact remaining steps |
| Lean error or timeout | negative | — (no state) |
| Subtree fully expanded, nothing proved | mildly negative | dead (lower weight) |
| Alive, off the proof path, or on the frontier when the budget ran out | 0 | censored: at least n |

Local shaping for RL is potential-based: `h(before) − h(after)` plus a small penalty for invalid steps, so creating
and closing a subgoal nets to zero. The global proof outcome dominates.

Reasoning is bootstrapped from the model's own thinking mode (stages 2–3). A same-family larger teacher
(Qwen3.5-9B, self-hosted) is the fallback if self-bootstrapping stalls; a paid API teacher only after a pilot and
the owner's approval.

## Ablation ladder (all at equal compute)

| # | System | Question |
|---|---|---|
| 0 | Best-first search over the automation sweep only, no model | How much is free? |
| 1 | Base model, few-shot, log-probability best-first | Does a generic model help? |
| 2 | SFT policy | Value of domain fine-tuning |
| 3 | + lemma retrieval (list length 0/4/8/16/32) | Does retrieval help, and at what length? |
| 4 | + remaining-steps value (A*, sweep λ and D) | Does the heuristic beat log-probability? |
| 5 | + single-step on-policy reasoning | Does short reasoning pay for its tokens? |
| 6 | + expert iteration rounds | How much does self-generated data add? |

Cross-cutting: thinking on vs off at each stage; model size (0.8B / 2B / 4B) against search budget if the budget
allows.

## Phases and status

- [x] **Phase 0** — Environment, REPL wrapper, miniF2F loading and statement check, Lean cost measurements,
  automation-only best-first baseline (ladder row 0).
  - [x] Lean v4.9.0-rc1 + Mathlib `d1d1e4b7` + REPL pinned; all 488 statements load; costs measured
    (`results/phase0_environment/`). Lean is cheap: ~3.7 s per process start, ~0.24 GiB private memory,
    ~290 tactic calls/s with 32 processes.
  - [x] Wrapper review: cancellation desync, `admitGoal` closers, axiom spoofing and replay drift fixed.
  - [x] Search core and automation-only baseline: **79/244 (32.4%) of miniF2F-valid**, all proofs verified,
    5 minutes for the split (`results/phase0_automation_baseline/`).
- [x] **Phase 1** — Model probe (throughput, valid-Lean rate, progress rate; few-shot and after short SFT);
  base-model few-shot search (ladder row 1).
  - [x] Serving and throughput (`results/phase1_throughput/`): Qwen3.5-2B gives ~40–47 short samples/s per 3090
    (~11–12/s with 512-token thinking), so the GPU, not Lean (~290 tactic calls/s on 32 processes), is the
    bottleneck. Runtime adapter swaps take 0.26 s; adapters cost 9–24% throughput. Because budgets count
    expansions and tokens, not seconds, policy and value are served as two LoRA adapters on the raw base model.
  - [x] Few-shot probe (`results/phase1_probe/`): Qwen3.5-2B > Qwen3.5-2B-Base >> Qwen3-1.7B, Qwen2.5-Math;
    temperature 0.8 beats 1.0.
  - [x] Row 1, few-shot policy + automation, 16 samples × 64 expansions: **Qwen3.5-2B 115/244 (47.1%),
    Qwen3.5-2B-Base 117/244 (48.0%)**, no row-0 proof lost (`results/phase1_fewshot_search_*`).
  - [x] Short identical SFT (7.5M tokens each) and post-SFT probe (`results/phase2_sft_model_choice/`):
    Qwen3.5-2B and -Base tie (~63% valid, ~32% any-close@8 vs 18% / 20% few-shot), ahead of Qwen3-1.7B and
    Qwen2.5-Math. **Chosen: Qwen3.5-2B** (keeps thinking mode). LoRA rank 64 matches full fine-tuning within
    noise on Qwen3.5-0.8B (`results/phase2_sft_lora_vs_full/`).
- [ ] **Phase 2** — Proof-corpus tracing, decontamination, LoRA SFT, policy search on miniF2F-valid (row 2).
  - [ ] Proof tracing (`results/phase2_tracing/`): the selection minus `stp_conjectures` is replayed step by step
    (200k heartbeats, 60 s wall-clock backstop per step; 2% of canonical statements held out). Pilot, 15,516
    proofs: 83.9% replay completely, from 99.2% (DeepSeek-Prover-V1) to 52.2% (Numina human proofs: Mathlib 4.15
    names, `native_decide`); 49,807 training steps; 238/238 sampled complete proofs re-verify. Narrowed full run
    (Goedel workbook, STP workbook, DeepSeek-Prover-V1, Lean Workbook, Leanabell) finished: ~402k train steps.
    Goedel SFT v2 and Numina are being traced separately for later training rounds.
  - [x] SFT v1 (development policy, `results/phase2_sft_v1/`): 16.8M tokens × 2 epochs on the first snapshot;
    probe valid 71.4%, any-close@8 37.6% (few-shot: 18.0% / 19.8%).
  - [x] SFT v2 (final policy, `results/phase2_sft_v2/`): 60M tokens, equal source shares, one epoch on both
    GPUs (143 min). Probe equal to v1 within noise (valid 71.9%, any-close@8 36.3%), slightly lower validation
    loss: more traced data of the same kind has stopped paying off. Deferred tracing (Goedel SFT v2, Numina)
    stopped after ~33k proofs.
  - [x] Row 2 with SFT v2 on miniF2F-valid: **148/244 (60.7%)**, same set size as SFT v1 (5 new, 5 lost)
    (`results/phase2_sft_v2_search/`).
- [x] **Throughput** (`results/gpu_utilization/`): packed + compiled LoRA training 10.8k tokens/s on both GPUs
  (+48%, 98–100% utilization); search 120 concurrent, pinned to 40 CPUs, merged policy + merged value instance per
  GPU, 7-tactic sweep: ~1,240 miniF2F-valid theorems/hour (was 603) at equal solve rate; in-place weight publish
  ~20 s. Search remains Lean/CPU-bound (~48 Lean cores would saturate both GPUs).
- [ ] **Phase 3** — Value v0/v1, A* search, λ/D sweep (row 4).
  - [x] Value v0 on traced human proofs (`results/phase3_value_v0/`): validation bin accuracy 53%, MAE 1.26
    steps, Spearman 0.80 (zero-shot: 27%, 2.35, −0.03).
  - [x] Development pair on miniF2F-valid with SFT v1: **row 2 148/244 (60.7%)**, **A* with v0 (λ = 0.5)
    155/244 (63.5%)**, ahead at every expansion and token budget (12 new, 5 lost; not yet significant)
    (`results/phase2_sft_v1_search/`, `results/phase3_astar_v0/`). v0 cannot see dead ends (no dead labels).
  - [x] A* with v0 on the SFT v2 policy: **157/244 (64.3%)** vs 148 for row 2 (12 new, 3 lost, sign test
    p ≈ 0.035), ahead at every expansion and wall-clock budget, 21% less Lean time
    (`results/phase3_astar_v0_sft_v2/`).
  - [x] Search shape at ~1,024 generations (`results/phase3_search_shape/`): 16×64 156, 8×128 154, 4×256 153;
    policy prior w_p 0.2 154, 0.4 153 (all within noise). Loop uses n = 8, w_p = 0.2.
  - [ ] Value v1 from statement-pool search trees (dead and censored labels).
- [ ] **Phase 4** — Retriever, applicability annotation, list-length ablation (row 3).
  - [x] ReProver retriever over 199,810 premises (LeanDojo corpus plus 25,556 `to_additive`/alias theorems it
    misses). Recall@8 0.54 on LeanDojo novel_premises (upper bound) but **0.16 on held-out competition steps
    (Hit@8 22%)**; only 39% of competition steps use a library theorem (`results/phase4_recall/`).
  - [ ] Reduced ablation: lemma-aware SFT (~15M tokens), lists of 0/8/32 on 64 hard miniF2F-valid problems.
- [ ] **Phase 5** — Single-step on-policy reasoning (row 5).
  - [x] Pilot (`results/phase5_pilot/`): SFT v2 with thinking succeeds on 12.5% of samples vs 48.2% without,
    at ~80× the tokens per success; a brevity instruction does not shorten thoughts; the base model is worse.
  - [x] Base vs SFT thinking (`results/phase5_compare/`): SFT improved thinking (20.7% vs 4.5% per sample); the base
    model reasons poorly even at 4,096 tokens; short thoughts succeed most.
  - [x] Short-reasoning bootstrap (`results/phase5_bootstrap/`): 8k SFT-unseen states, Lean-verified thinking
    samples, long traces compressed to ~95 tokens by Qwen3.5-2B with a sufficiency check (78.8% pass), 50/50 with
    non-thinking replay. On unseen states thinking goes from 16.3% to **42.1% per sample at 234 tokens** (512 cap);
    tokens per success 557 vs 89 non-thinking (6.2×, passes the 10× rule); non-thinking unchanged (46%).
  - [x] Equal-token search comparison (`results/phase5_search/`, 96k generated tokens per theorem, bootstrap
    policy): thinking n = 8 **152**, non-thinking n = 8 **156**, n = 16 **159**. Per expansion thinking is as good,
    but each expansion costs ~11× the tokens, so at equal compute short reasoning does not pay yet. The loop runs
    non-thinking from the bootstrap policy.
- [ ] **Phase 6** — Expert iteration rounds (row 6).
  - [x] Continuous actor–learner loop launched 2026-10-13 ~01:40 UTC: non-thinking, n = 8, stages 64/192/512,
    curriculum over 720k known-proof statements (unverified allowed), pause–train–publish phases (~5–8 min),
    lazy re-scoring, evaluation at 32 expansions inside training pauses. By 06:00 UTC: versions 0–4, 3,098
    statements processed, 2,696 proofs; miniF2F-valid (32 expansions) v0 147 → v3 152; band ~8.5–9.5 at ~44%
    solve rate.
  - [x] Outcome of the 2B loop (9 phases): miniF2F-valid at 32 expansions v0 147, v3 152, v6 148, v9 149, no
    gain beyond noise. 4B thinking loop (2026-10-14 12:16–17:47 UTC, round-2 student): 305 statements, 130
    proofs (~25–35 proofs/hour), v1 143; held for the visible-reasoning experiments, then the node was returned.
  - [x] The loop's value gate was measured on far too few held-out states (0–63 exact, 0–53 dead per phase;
    Spearman jumped between −0.87 and 1.0), so it never opened and v0 stayed in use. Whether loop value training
    helped or hurt was never established; its labels were mostly censored, with few exact or dead ones.
- [ ] **Phase 7** — Final ladder on miniF2F-test, write-up in `results/README.md`. Report the test split as
  commonly used (Kimina's five fixed statements) and the corrected miniF2F-v2c (2511.03108), on which scores drop
  8–10 points.

Results of each phase are committed under `results/` as small JSON summaries plus a markdown table; large
per-theorem logs, datasets and checkpoints stay on the node. A copy of the irreplaceable parts of the first node
(all run logs and results, generated datasets, 12 adapters) is in the gitignored `node_backup/2026-10-15/`.

### Findings 2026-10-13

- **Model-size reasoning probe** (`results/phase5_model_size_probe/`, 128 unseen states, k = 8): 2B bootstrap 47.0%
  per sample / 960 tokens per success; Qwen3.5-4B 24.2% / 12,819 (65% still thinking at 4,096); Qwen3.5-9B 27.8% /
  5,629, bounded to 1,024 tokens 28.7% / 2,077. Hand-judged reasoning on non-trivial successful steps: 2B correct
  6/17 (pattern matching), 4B 9/10, 9B 10/10. Larger models reason soundly; their steps fail on Lean syntax and long
  blocks, not on mathematics.
- **Lean waste in the loop** (`results/gpu_utilization/thinking/`): 120 REPLs on 40 CPUs turned 10 s wall-clock
  limits into ~3 CPU-seconds, so heavy candidates were killed and replayed. Policy candidates at 25k heartbeats:
  Lean per expansion −32%, run time −48%, solve rate unchanged. Serving: policy 0.62 memory / 512 sequences /
  8,192 batched tokens (+5%); FP8 weight-only no faster on a 2B model.

- **9B teacher → 4B student** (`results/phase5_teacher_student/`): 4B Lean SFT (20M tokens) matches SFT v2 2B on
  the probe. The 9B (bounded thinking) yields 2,134 Lean-verified reasoning examples from 3,072 unseen states;
  compression to ~60 tokens passes 95% but produces generic rewrites. Student reasoning is much sounder (12/17
  correct on non-trivial successful steps vs 6/17 for the 2B) but solves less: 37.8% per sample thinking, 43.9%
  non-thinking (2B bootstrap 42.1% / 46.0%). Equal-token search on miniF2F-valid: 2B non-thinking n=16 159,
  4B student non-thinking 156, 2B thinking 152, 4B thinking 147 (the 4B's thinking arm hit the 900 s wall clock,
  ~1.9k tokens/s on a 3090).

- **Round 2 student, light compression** (9B rewrites to ~50% length, ≥ 100 tokens): equal-token search on
  miniF2F-valid without a binding wall clock: 4B student non-thinking n=16 **162** (best so far; 2B 159),
  thinking n=8 150 (2B 152). The expert-iteration loop continues with this student in thinking mode.
- **Reasoning retention on MATH-500** (`results/reasoning_retention/`, 200 problems, thinking, 4,096 cap, forced
  answers at the cap): our training did not damage general reasoning. Forced-answer pass@1: 2B base 66.6%, SFT v2
  67.8%, bootstrap 69.2%; 4B base 80.9%, 4B SFT 80.1%, student 83.4%. Unforced pass@1 rises most (2B 9.0% → 47.0%,
  4B 22.1% → 40.8%) because trained models finish their thinking.

- **MATH-500 without thinking** (`results/reasoning_retention/`): base models do better with visible
  chain-of-thought than with a 4,096-capped think block (2B 71.0% vs 66.6% forced; 4B 87.2% vs 80.9%); our
  reasoning training closes that gap (4B student 83.4% thinking vs 83.2%). Lean SFT costs 2.5–3.4 points of
  non-thinking accuracy, mostly at levels 4–5; reasoning training adds no further loss.
- **Equal expansions** (round-2 4B student, n = 16, 64 expansions, no token cap, forced answers on truncated
  thoughts): **thinking 160 vs non-thinking 154** on miniF2F-valid. Per expansion thinking is the stronger policy;
  per token non-thinking remains cheaper. The loop runs the 4B student in thinking mode with forced answers.

- **Visible-reasoning series** (2026-10-14/15): the policy writes a short visible explanation, then the Lean block
  (no think block). Probe: round-2 student 37.5% per sample / 64.5% any@8 / 408 tokens per success in visible mode
  vs 36.0% / 59.8% / 925 thinking; plain Lean SFT destroys the visible mode (6.9%). 9B teacher in visible mode:
  26.1% / 43.4% on 6,143 unseen states, median explanation 95 tokens, 4,677 examples. Gentle 4B SFT (Lean +
  18% general math worked solutions) keeps Lean validation loss (0.221 vs 0.218) and the visible mode (self-
  generation 22.6% / 43.7% on 10,240 states). Student: 11,727 visible-reasoning examples, 70 / 15 Lean replay /
  15 math. **Equal-expansion search on miniF2F-valid (n = 16, 64 expansions): 171/244 (70.1%)** vs 160 thinking,
  154 non-thinking; 124 solved after one expansion; 94k tokens per theorem (thinking 114k).

- **MATH collapse after the gentle SFT** (`results/phase2_sft_4b_gentle/README.md`): visible-mode MATH-500
  (forced) fell to 47.0% (gentle SFT) and 52.0% (visible student) from 84–87%, with answers ~4× shorter. Cause:
  MATH-train reference solutions are terse (median 162 tokens vs the base model's own 860), and they were trained
  under the exact evaluation prompt. The student's think block now just answers. Fix in progress: gentle SFT v2
  with the base model's own full-length, answer-checked solutions plus some thinking-mode examples, then a
  student v2, and a control search of the visible student without explanations.

- **MATH collapse fixed; small Lean cost** (`results/phase2_sft_4b_gentle_v2`, `results/phase5_visible_v2`).
  Gentle SFT v2 (5,354 self-solutions, median 673 tokens, plus 306 thinking-mode ones): MATH-500 visible forced
  87.5% (base 87.3%), thinking mode alive again. Student v2 from it (visible examples with short ones capped,
  10% thinking traces, full-length math replay): MATH-500 visible 87.6%, thinking forced 84.5% (base 80.9%), but
  miniF2F-valid equal-expansion search 166/244 vs 171 for student v1 (2 new, 7 lost; one run each) and 42.1% vs
  44.6% per sample on the 512 states. Control without explanations (v1): 157/244.

## Next phase: search-tree GRPO (agreed 2026-10-26)

### Where the project stands (2026-10-25)

- **Fair comparisons** on miniF2F-valid (single runs; differences under ~5–7 theorems are noise):

  | Comparison | Same model and budget | Result |
  |---|---|---|
  | 2B base few-shot vs Lean SFT | yes (16 × 64) | 115 → 148 |
  | 2B SFT, + value v0 in A* | yes | 148 → 157 (p ≈ 0.035) |
  | 4B student, with vs without visible explanations | same expansions, ~10× tokens (94k vs 10k) | 157 → 171 |
  | Expert-iteration loop v0 vs v3 (2B) | yes (32 expansions) | 147 → 152 (noise) |
  | 4B base model in search | never run | — |

  Most of the gain is SFT on public proof corpora produced by large-compute provers (distillation of a fixed
  dataset). Our own contributions are the value model (+9), visible per-step reasoning (+14 per expansion) and
  the loop (unproven).
- **Visible student v1 vs v2** (`results/phase5_visible_v2`): v1 171/244, 44.6% per sample on the 512 held-out
  states, MATH-500 52.0% visible (collapsed); v2 (gentle SFT v2 base, self-solution math replay, 10% thinking
  traces) 166/244, 42.1%, MATH-500 87.6% visible and 84.5% thinking (base 4B 87.3% / 80.9%).
- **Literature** (`results/literature/state_of_the_art_2026-10.md`): our ~64–70% test-equivalent at ~1k
  generations matches late-2024 step provers (InternLM2.5-StepProver, HunyuanProver, BFS-Prover V1) with 20–5,000×
  fewer samples, but small whole-proof models are far ahead at matched tokens (DeepSeek-Prover-V2-7B non-CoT
  68.0% test at ~14k tokens; Pythagoras-4B 86.1% at pass@32). Covered by prior work: step-level best-first search
  with a critic, remaining-steps values, expert iteration and its plateau, per-tactic thoughts (Lean-STaR), teacher
  distillation. Possibly new but small: short visible reasoning inside value-guided best-first search (Lean-STaR
  found thoughts break log-probability BFS); a value model helping at a one-attempt budget (InternLM2.5's critic
  hurt there); keeping general reasoning while LoRA-tuning a prover.
- **Compute so far**: ~480 RTX-3090-hours (~100–150 H100-hours). Published RL stages: Kimina-RL 384 H100-hours
  from a strong whole-proof model; one Goedel-Prover round 64 H100 × 6 h plus 8,000 CPUs; InternLM2.5 21k
  CPU-days. Large-scale expert iteration is out of budget; the target is a measurable improvement over the
  starting policy at a fixed evaluation budget, with detailed intermediate feedback.

### Goal

Learn and measure the RL stage on a verifiable task: an RL loop with a concrete optimization target, dense but
globally anchored rewards, and per-phase curves rather than a single final score. Success: the loop improves its
starting policy on the fixed targets beyond noise. There is no full control run (decided 2026-10-28: too
expensive); per-tactic against sequence-level credit is compared only in the cheap single-step test below.

### Budget and infrastructure

- **Budget: about $200**, spent over one to two weeks rather than in a few days: no time pressure, so cheaper,
  slower hardware is preferred; setup, data transfer and implementation overhead then weigh less. Roughly $0.6–1.4
  per hour of node time; concrete offers are checked live before renting, the owner picks, nothing is rented
  without approval.
- **New node**: a region with direct access to Hugging Face and GitHub (the first node needed mirrors and had a
  slow, dropping link); as many CPU cores as the budget allows (Lean was the bottleneck at 46 cores); 2–4 RTX
  3090/4090-class GPUs or equivalent. Candidate class: 4× RTX 3090 with a 96-thread EPYC and ~128 GB RAM at about
  $0.80/hour, which matches 2× RTX 5090 in aggregate memory bandwidth (3.8 vs 3.6 TB/s) at a lower price and with
  more CPU; check that the threads are all ours, the location, the network speed and the reliability.
- **Work that needs no GPU happens before renting**: implementation and unit tests locally; tests that need Lean
  either on a local Linux environment (e.g. WSL) or on a cheap CPU-only instance. The GPU node is rented when the
  code is ready.
- **Rebuild on the new node** (about half a day): setup scripts, raw downloads, normalization, curriculum pools;
  evaluation states, generated datasets and adapters from `node_backup/`. Copying from the old node is not
  possible. The flattened SFT data needs a re-trace of the selected proofs (CPU work, see below).

### Starting policy and the SFT stage before GRPO

- **Starting point: visible student v2** (decided): RL tends to erode general reasoning, and v2 keeps it
  measurable. Value: v0. Both adapters are in `node_backup/`.
- Reasoning stays visible and short (~120 tokens mean now): a short explanation, then the Lean block
  (`enable_thinking = false`). No length penalty; only a hard token limit against runaway outputs.
- **One more fine-tune before GRPO** (gentle, from v2, with the same math replay so MATH-500 retention holds),
  on rewritten data:
  - **No nested `have` blocks**: Lean data and visible-reasoning examples rewritten into flat steps (below) and
    re-verified by replay, so the model stops writing them.
  - **Mixed step lengths**: chunks of k consecutive top-level tactics with their exact start and end states,
    k ∈ {1, 3, 5, 7, rest of the proof}, so the model learns to choose its own step size. Today's data teaches one
    tactic per step (the non-reasoning policies emit exactly one).
  - **Visible chunk examples** (decided 2026-10-29): the loop samples in visible mode, so chunks taught only as
    non-visible examples might not transfer. A teacher (the namer, Qwen3.5-9B) writes the explanation a prover would
    state before the known block for two chunks per reasoning example, in the naming run (~18,500 explanations,
    ~30–40 min on 4 GPUs with prefix caching; `data_rewrite/README.md`). Replies are validated (length, markup, code,
    copied block, stale names, …), retried once, and a chunk without an accepted explanation stays a non-visible
    example. The explanation is written on the named chunk and renamed back for the numbered arm.
  - **Mode mix** (decided 2026-10-29): a third of the train examples are non-visible chunks, two thirds visible
    (per reasoning example: itself, two visible chunks, 1.5 non-visible; ~40k train examples). Check MATH-500 and
    the held-out states right after the SFT, since more steps move further from v2.
- **The SFT stage's adapter is the GRPO policy** (decided 2026-10-29): it continues visible student v2's adapter on
  raw Qwen3.5-4B, is merged for version 0 and keeps training phase by phase on raw Qwen3.5-4B ("Precision" below).
- **Descriptive hypothesis names: a cheap A/B before GRPO, leaning towards adopting them** (decided 2026-10-28).
  miniF2F and the corpora of other provers (Lean Workbook, DeepSeek-Prover, Goedel) number hypotheses (`h₀, h₁, …`);
  Mathlib mostly uses short meaningful names (`hx`, `hab`, `hpos`). The main argument is the reasoning: facts
  referenced by what they say rather than by a number, which matters most in longer proofs with many `have`s (e.g.
  `amgm_sqrtxymulxmyeqxpy_xpygeq4` with h₃ … h₁₂); the 3.0% of samples referencing non-existent hypotheses is only
  the measurable symptom. The distribution shift is expected to be small (the names stand in the goal state in the
  prompt and are copied from context; the fine-tune adapts). Practical risks: misleading names (names are proposed
  once offline by a larger model and checked to be unique, valid identifiers, and the renamed proofs replay) and
  statements (binder names do not change the proposition; every proof is also checked against the original
  statement; the search renames each statement's hypotheses the same way). Two short fine-tunes on the same
  rewritten data, numbered vs named, compared on the probe set below, the unknown-name error rate and MATH-500;
  the winner is the GRPO starting policy. In the A/B the named arm's searches score each state with the original
  names restored (decided 2026-10-29: value v0 was trained on numbered names); the loop leaves this off, since its
  value model trains on its own renamed trees.

### The loop

1. Search a batch of curriculum statements with best-first / A* search, **n = 8 samples per expansion** (not 16),
   **32 expansions per search** (decided 2026-10-29, review F M4: expansions 17-64 added 8 of 171 solves in the visible
   run; the probe stays at 16, miniF2F at 64; `[sampling] max_expansions`, raised mid-run by a restart when the budget
   signals below show harder proofs cut off),
   without raising the sampling temperature (0.8). Exploration over which state is expanded next: with probability
   **ε = 0.1** the search picks uniformly among the **top 8 frontier states** by priority instead of the best one
   (never fully random; off in evaluations). Reason: only expanded states get value labels and the value model
   decides what is expanded, so a state it under-rates is never labelled and the error never corrected (in the v0
   trees all 253 never-expanded siblings were rated below the expanded ones); the near misses are where ranking
   errors matter.
2. **Harvesting after the first proof**: the rest of the proving expansion's samples are still executed, then the
   search keeps expanding frontier states the value model puts at most **2 tactics** from done, for up to **16
   more expansions** (the old loop's `HarvestConfig`: 1.5 steps, 8 expansions). Goal: several proof paths per
   problem and more proof-graph nodes, i.e. more policy groups. Tuned by the harvest yield on the dashboard.
3. After each search finishes, label the whole search graph (below). No training after individual steps.
4. Build GRPO groups and value targets from the labelled graphs; train the policy every phase and the value model
   every 4 phases ("Value model") in a pause–train–publish phase, **two passes over the phase's data** if training
   time allows (PPO clipping exists for this reuse; decided 2026-10-28, depending on the measured ratio of training
   to sampling time; 1 or 2 is a setting, there is no control run to compare them).
5. Publish after every training phase. A phase's sampling ends once it has **300 trainable groups** (groups at
   proof-graph nodes of solved trees with a policy proof and a non-zero advantage, counted per finished tree), after
   at least 45 and at most 90 minutes (decided 2026-10-29, review F M4: the pause's fixed costs are paid per phase;
   before: 15–30 min and 100 solved trees). Watch the clip fraction and the KL to the data-collecting and to the
   starting policy (health checks below); if they rise, lower the learning rate or train on smaller batches.
6. The curriculum keeps the solve rate around 30–70%, so groups carry signal and trees are balanced between
   solved and unsolved. Hard problems absorbing most of the budget is expected; the curriculum and escalation
   stages bound it.
7. **Health checks per phase** (decided 2026-10-29; `src/lean_search/rl/README.md`, "Health checks and budget
   signals"): KL to the starting policy, clip fraction, distinct samples per expansion, held-out valid-Lean rate and
   per-sample success (whenever the held-out states run), explanation length and the share of samples cut off at the
   token cap, each with a configurable alert threshold (absolute, or relative to version 0's held-out evaluation or the
   first two phases; first guesses, calibrated on the first phases), in `loop.log` and on the dashboard. **Hard stop**:
   a held-out valid-Lean rate below 0.7 × version 0's stops the loop after the phase, records the last good version
   (its adapter is kept) and refuses to restart until it is rolled back to (`grpo_loop.py rollback`) or the stop is
   cleared. **Budget signals**: share of solves in the last quarter of the budget (expansions 25–32), expansions to
   the first proof, proof lengths and the curriculum difficulty of solved statements per phase; a note suggests a
   larger budget when the last-quarter share exceeds 10% over the last 3 phases.

**GPU layout** (decided 2026-10-29; reviews C and D estimated ~35–55% GPU use for the earlier layout, GPU 0 only
training and GPUs 1–3 serving but idle while it trained): while sampling, all four GPUs serve the merged policy (62%
of memory) and the merged value model (28%). At the training stage every search pauses at the pause gate (requests
wait, trees and REPL states stay), all servers sleep (level 2, weights and KV cache freed), all four GPUs train
data-parallel (`torchrun`, one rank per GPU; policy, then the value model), the new adapters are merged
on the GPUs, and the servers wake with the new weights. A data-parallel step equals the one-GPU step (same global
loss normalization, LoRA gradients summed before clipping). One-GPU training (`training.gpus = [0]`: GPU 0's servers
sleep, the others stay loaded, idle and swap in place) is the configurable fallback. Every pause segment is timed
(drain, server sleep, trainer start, preparation, loads, compile, scoring, policy and value training, merge,
write, publish, wake, resume; `rl/README.md`, "Timing"). Estimate before the node: ~10–15 min per pause on one GPU,
of which training compute 4–8 min; on four GPUs the compute shrinks about fourfold while start, loads, compile,
merges and wake do not (an estimated 5–8 min of fixed part); GPU utilization ~80–87%.

**Persistent trainer** (decided 2026-10-29, built): one training job for the whole loop, a rank per GPU, keeps its
processes, NCCL group, tokenizers, models and compiled graphs across phases. Between phases each rank parks its models
in host memory (one shared tmpfs copy of the 4B and 2B bases for all ranks, ~14 GB) and frees its GPU but for its CUDA
context; the trees are read and labelled while sampling (main rank, one background CPU), so the pause starts with GPU
work; the new adapters are merged on the GPUs into host memory and the servers load them from there, the disk copy and
the version's record following in the background after the searches resumed (never recorded before its files exist).
Estimated fixed part ~1 min per phase (start and first compilation once per job); the per-phase job stays the fallback
(`training.persistent = false`). Details: `rl/README.md`, "Persistent trainer". Lever if the pause still costs too
much: longer sampling phases (the fixed part is paid per phase).

**Loop systems** (decided 2026-10-29, after reviews C and D): training and evaluation jobs run in their own process
groups with PID records and a marker in every job process's environment (torchrun's workers leave the group);
stopping the loop stops the job and every marked process, and a restarted loop refuses to start, before waking any
server, while a recorded job still runs. A search that ends on a policy or value server failure says nothing about
its statement, which is fed again (up to 3 retries) and counted; when half of the last 20 searches failed on a server,
the searches pause, dead servers are restarted, and the loop stops if one stays down. Host memory has a budget (loop
concurrency × p90 REPL memory + evaluation concurrency × p90 + vLLM + merge + training ranks + the persistent
trainer's parked bases and handed-off merges ≤ 0.85 × RAM, checked in `loop.log` at each stage of a pause;
`rl/README.md`, "Host memory"): the paused searches' REPL processes stop before training and before evaluations
(they replay their states on resume), and evaluations run at concurrency 64. The
policy's NLL replay is the rewritten, flattened SFT data of the starting arm. Groups and texts are matched per tree
(two searches of one statement in a phase used to swap texts and advantages).

### Search graph and labels

The search is a graph: a tactic that reaches an existing state records a duplicate edge to it. In the visible
student's 244 trees: 66.2% of attempts fail (Lean error or timeout), 15.5% create a new state, 14.4% reach an
existing state, 3.8% repeat an earlier tactic text. Duplicates: 49% back to the same state (no progress), 4% back
to an ancestor, 21% the same state as a sibling, 26% transpositions into another branch; 56 transposition edges
lead from 14 off-path nodes into a proof (the proof graph has 458 nodes vs 444 on the found proof paths).

- **A step is one top-level tactic after flattening** (decided 2026-10-28), for remaining steps, A* depth, the
  value bins and harvesting; a block of 7 tactics is 7 steps. This is independent of how the model splits its
  output into blocks and matches v0's training data (human proofs, one tactic per step), so the bins (1–7, 8+)
  stay. Measured on the visible student's 171 solved trees: a block that reaches a new state applies a median 1
  tactic (mean 1.8, 90th percentile 3); proofs take a median 2 tactics (90th percentile 8); of the 124 problems
  solved by the first expansion, 71 are a single tactic (e.g. `nlinarith [...]`), the rest a median 3.
- **Proof graph**: every node with a route to a proof via new-state or transposition edges is on a proof. Its
  exact remaining steps are the shortest such route. Transpositions are never failures (A then B and B then A both
  prove). **Per tactic**: the harness records the state after every tactic of a block, so the intermediate states
  of proof blocks are proof-graph states too, and a tactic of another sample that reaches one of them (e.g. the same
  first `have` followed by a failing line) is on the proof graph.
- **No progress** (per tactic): a tactic that leaves the state unchanged, returns to an ancestor, or adds a
  **redundant hypothesis** (a `have` whose type is already in the context, e.g. `have h₉ : y ≤ x := h₁`, or a
  reflexive `a = a`). Found inside successful proofs too, so it is penalized wherever it occurs.
- **Same state as a sibling**: both tactics are equally good and get the reward of the state they reach.
- **Dead end**: an expanded node whose 8 samples and automation sweep produced no new state and no transposition
  to a live state (only errors, timeouts, repeats or no-progress). Checked by Lean, but only for 8 samples, so a
  weaker 0 than a single tactic error.
- **Subtrees are never fully explored** (the branching factor is too large), so "fully explored dead subtree" is not
  a label; off-path nodes are judged by the evidence beneath them (value targets below).
- Possible later fix: when a transposition finds a shorter route to an existing state, A* would reopen it with the
  shorter depth; the search currently does not.

### Lean execution and harness

Findings (`results/search_error_analysis/`):
- The 66% failed edges overstate the policy's failure rate: 38% of failed edges come from the automation sweep
  (70.8% of sweep tactics fail, cheaply: 6.9% of Lean time), and identical policy samples are merged before
  execution. Per policy sample about 53.6% fail; 90.6% of policy expansions are spent in the 73 problems never
  proved. At the first expansion of later-solved problems the failure rate is 23.6%, matching the per-step
  evaluation.
- Per policy sample: 5.0% malformed Lean (1.8% syntax, 3.2% library names missing in the pinned Mathlib), 8.8%
  invalid in the state (3.0% unknown hypothesis names, 5.8% ill-typed terms), 33.7% well-formed tactics that do
  not work there (linarith/nlinarith, simp without progress, rw pattern missing, unsolved goals, omega), 2.6%
  timeouts. About 95% of samples are syntactically valid Lean with real names; the non-existent names are the
  model's own inventions (the traced training data only contains tactics that replayed in the pinned environment).
  Visible explanations roughly double the malformed and invalid rates (2.6% / 3.4% without) through longer, more
  ambitious blocks, yet solve more problems.
- Wall-clock timeouts are 2.3% of edges but **41.9% of Lean seconds** (mostly `nlinarith`, `norm_num`,
  `simp_all`, `omega`, `interval_cases`), ~16 s each (limit, kill, REPL restart, replay); steps on found proofs
  take a median 0.21 s (95th percentile 2.4 s).
- "Back to the same state" comes from tactics that succeed without changing anything: the sweep's `ring_nf` (49%;
  it returns to the same state on 69% of its runs) and the policy's `norm_num` variants (32%), plus `all_goals` /
  `try` wrappers, `exfalso` on `False`, `norm_cast`; 2.1% of Lean time. The state key contains every hypothesis
  (with case tags, `let` values and inaccessible names) and the target, so an added `have` always changes the
  state; Lean does not prune unused hypotheses. False merges would need differences hidden by printing (numeral
  types); none were found and the residual risk is ignored.

Decisions:
- **Heartbeats are the limit** (deterministic; the wall clock depends on load). Policy tactics at about 25–50k
  heartbeats (the first loop's 25k cut Lean time per expansion by 32% at equal solve rate). A heartbeat timeout is
  an ordinary Lean error without killing the REPL. A wall clock stays only as a generous emergency stop (e.g.
  60 s) for hangs that heartbeats do not count, such as kernel reduction. First test on the new node: replay all
  steps on found proofs plus a sample of the former timeouts at 25k, 50k and 100k heartbeats and check which
  formerly successful steps still complete.
- **Flatten nested `have`**: the unit of execution is the top-level tactic, so `have h : A := by …` with its nested
  proof is atomic and one error inside kills it (32% of the visible model's blocks start with `have`; 72.6% of
  those fail; `have`-headed blocks use 26% of Lean time). The harness rewrites `have h : A := by t₁ … tₙ` into
  `have h : A` (Mathlib: A becomes the first goal) followed by `t₁ … tₙ` as top-level steps, so the valid prefix
  inside nested proofs is kept. Only rewrites that are equivalent are used: the training data is re-verified by
  replay and rewrites that change behaviour (e.g. `all_goals` or `simp_all` now seeing both goals) are dropped.
- **Names**: rename inaccessible hypotheses (`x✝`; 0.6% of samples copy them and can never be valid) before
  prompting; check identifiers against the pinned environment's constants and the local context before running
  Lean, reject or repair.
- **Sweep and policy**: the policy's `exact`, `linarith` and `nlinarith […]` almost never work because the sweep
  already closes those states, and 3.4% of samples repeat a failed sweep tactic. Not treated specially: a wasted
  sample, which the GRPO reward already scores as the failure it is.
- **Repetition loops**: 139 blocks were answers forced at the 1,280-token cap, mostly repeating explanations. The
  GRPO reward should dampen them (they fail); logged on the dashboard in case RL amplifies them instead.
- Keep the goal-key de-duplication and `ring_nf` in the sweep (it produced 1,049 children and 9 proof steps).
- Compare per-sample rates, not per-edge shares, with the per-step evaluation.
- Later option: resample with the Lean error message attached (error-conditioned repair).

Implemented (2026-10-26; details in `src/lean_search/lean/README.md`, "Harness for policy blocks"): heartbeat limits
(policy 50k, sweep 200k, 60 s emergency wall clock, `experiments/configs/grpo/search/visible_student_v2.toml`; a sweep
tactic is disabled after one timeout of either kind), flattening with guards that keep it equivalent wherever the
original succeeds (`flatten_proof` for the data rewrite), `rename_i` on every new state with inaccessible names, and
the identifier check (1 false rejection in 18,227 accepted blocks and prefixes, 71% of unknown-name failures caught
on the visible student's trees). Edges keep the original block and the executed tactics with their offsets; tree
records keep each policy request's prompt and every sample's full text with the executed tactics' spans
(`TreeRecord.expansions`, the trainer's `ExpansionTexts`). Samples without a usable block (no block, cut off at the
token cap, empty, forbidden) are failed edges (`FailureKind.UNPARSED`, empty text) and score like a Lean error in
their group. `experiments/heartbeat_replay.py` is the replay test for the new node; a local run (WSL, 2 REPLs,
indicative only) on the visible student's trees: of 52 proof-path steps from 60 solved trees, 50 complete at 25k
heartbeats (two heavy `nlinarith`/nested-`have` steps run out) and all 52 at 50k and 100k (median 0.7 s); of 10
sampled former wall-clock timeouts, at 25k all 10 stop on heartbeats (median 3.6 s, 37 s in total vs 153 s recorded),
at 50k 9 stop on heartbeats and 1 fails fast (median 8.6 s, 133 s), at 100k 5 heartbeats, 3 errors, 2 still hit the
60 s emergency stop (340 s); none finished.

### Policy update: GRPO over sibling groups

- **Group** = the 8 samples of one expanded node **on the proof graph** (decided 2026-10-28): only those groups
  are trained; nodes off the proof graph and unsolved trees give no policy groups (they still give value targets).
  This removes the local reward earned off the proof graph (72.6% of it before) and makes the trained data small
  (about 4 groups per solved tree with harvesting). A group also needs at least one **policy** sample with a
  proof-graph tactic (decided 2026-10-29): where only the automation sweep's children reach the proof graph, the
  group is left out and counted (`groups_without_policy_proof`); in such groups every policy sample failed or made no
  progress, and 11 of the 166 groups with a signal on the old trees were of this kind. A policy sample repeating the
  sweep's tactic counts as the policy's. Identical tactic texts are merged. Best-first selection skews which states
  are trained, not the groups themselves. Later option, off at first: Lean-checked malformed samples (syntax errors,
  unknown constants) from any tree as a small separate negative signal ("not valid Lean", never "does not work
  here").
- **Reward** = `(1 − λ) · G + λ · L`, both on a common scale, mixed AlphaZero-style with **λ = 0.15** (the local
  influence stays at about 15–20%; the proof graph decides):
  - `G` (global) = `(1 − μ) · z + μ · q` with **μ = 0.15** (decided 2026-10-27): `z` is the concrete label, 1 if
    the state reached lies on the proof graph and 0 otherwise; `q` is the value part (the averaged estimate below, or
    the child's own estimate if it has no expanded subtree). μ is a manual switch (decided 2026-10-29, "Benchmark and
    value trends"): 0 until the owner turns it on, so G is the concrete label alone; at 0.15 the value model
    contributes at most 0.85 · 0.15 ≈ 13% of the reward. Dead ends are not a separate case (z = 0).
  - **Progress on the proof graph** (decided 2026-10-29): a proof-graph state earns δ = 0.2 per remaining step it is
    closer to a proof than the group's node, `δ · (d(node) − d(s))` with d the exact remaining top-level tactics
    (negative for a proof-graph state farther away), added to the global part. Before, every proof-graph state was
    worth the same 0.85 and closing the proof added only 0.015, so nothing rewarded getting closer. The global part
    never falls below the best off-graph state's, (1 − λ) · μ: a valid detour 5 or more steps farther from the proof
    scores like leaving the graph, never below it (before, R = 0.85 − 0.2k fell below a Lean error at k ≥ 6).
  - `L` (local) ∈ [−1, 1]: −1 Lean error (heartbeat timeouts included), **−1 no progress or redundant
    hypothesis** (decided 2026-10-29, a failure: a no-op wastes the sample too; at the earlier −0.5 a no-op beat a
    failing attempt, and on the old trees 19 no-progress and 7 redundant-hypothesis tactics got a positive
    advantage), 0 for a new state, plus 0.1 per goal closed. There is no potential-based value shaping.
- Advantage = reward minus the group mean, **without dividing by the group's standard deviation**: with std
  normalization, groups where G is constant would have their small λ·L differences re-amplified to full-size
  advantages and defeat the 15% cap. Only relative differences within a group matter; absolute sums over samples
  (e.g. the placeholder weights' local −45,918 vs global +1,112 on the visible student's trees, dominated by the many
  −1 errors) carry no meaning. Groups whose advantages are all zero are dropped, as in the mainstream recipes. The
  dashboard shows the effective local share of the summed |advantage|.
- Measured on the visible student's trees: 93.1% of groups have mixed rewards with the dense reward, 3.1% with the
  outcome-only reward; 72.6% of the positive local reward (placeholder weights) was earned
  off the proof graph, which is why L is capped at λ.
- **Per-tactic credit within a sample** (decided 2026-10-28, revised 2026-10-29; the GRPO loss is a sum over tokens,
  so each tactic's tokens get their own advantage). Each evaluated tactic gets a reward `R = (1 − λ) · G + λ · L`
  from the state it reaches:

  | Tactic | G | L | R (λ = 0.15) |
  |---|---|---|---|
  | Reaches a proof-graph state (closing the goal included) | 1, + δ per step gained | 0.1 per goal closed | 0.85 + 0.2 per step + 0.015 per goal |
  | Reaches a dead end, or an expanded off-graph state with ≥ 4 expanded nodes in its subtree (itself included) | 0 (+ μ · q once on) | 0 | ≈ 0 |
  | Reaches a state never expanded, an expanded off-graph state with live children and < 4 expanded nodes in its subtree, or a state no node has | unknown | — | **neutral**: untrained, outside the baseline |
  | No progress (unchanged, ancestor, redundant hypothesis) | 0 | −1 | −0.15 |
  | First failing tactic (the line Lean's error points to, after flattening) | 0 | −1 | −0.15 |
  | Everything after the failing tactic | — | — | masked (Lean never evaluated it) |

  **Thin off-graph evidence is unknown** (decided 2026-10-29): a sibling expanded once by harvesting or ε and not
  proved was pushed down, while its never-expanded twin stayed neutral. The threshold of 4 is the n of the value
  targets' weight n / (n + 4). Dead ends stay off graph: their expansion produced nothing usable, which is real
  evidence however small.

  **Later tactics in a block** (decided 2026-10-29): the search keeps a block's longest valid prefix, so a tactic
  after the first decides only whether the block gets further than the state before it. The block's anchor (its first
  tactic reaching a state with a reward, else its first tactic when that failed or made no progress) gets R − b₁.
  A later tactic reaching a state with a reward gets `R(s_i) − R(s_j)`, s_j the most recent earlier state of the
  block with a reward: δ per step gained on the proof graph (plus its goal bonus), the whole drop when it leaves the
  proof graph. Any other failing, no-progress or redundant tactic (a no-op before the anchor included) gets
  **−c = −0.1** (local part): the prefix is kept, only its tokens are wasted. A sample's score is its final state's R
  minus c per wasted tactic; a sample whose first tactic fails or makes no progress, with no state with a reward
  after it, scores that tactic's R; one with neither has no score. The baseline b is the multiplicity-weighted mean
  score of the group's samples with a score, the **first-tactic baseline b₁** (decided 2026-10-29, second round) the
  same mean of their anchors' R. The explanation gets score − b, and a block's tactic advantages add up to
  score − b₁: b − b₁ is the group's mean progress after the anchor, which the later tactics' gains carry. Against b
  (before), the anchor was charged that progress: at a node 4 steps from the proof with 6 of 8 samples proving in
  one 4-tactic block, the correct first tactic every proof shares got −0.16 (now +0.30), and the expected anchor
  advantage was negative whenever blocks ran more than one step. Progress is not normalized per group: the anchor's
  advantage and the later gains do not grow with d(node); only the explanation's spread grows, with the progress
  samples make within one block (`rl/README.md`).

  Tokens: a tactic's span and the gap before it get the tactic's advantage (untrained when unknown or masked), the
  explanation and the opening fence score − b, the **closing fence and end of turn 0** after a complete block
  (untrained after a failure). The closing tokens are trained at 0 rather than masked: the loss divides by a fixed
  token count, so they add no gradient but stay in the KL term and the per-token metrics. Before, they got the last
  tactic's advantage.

  **Stop vs continue**: stopping after t_i keeps s_i, the reference point of t_{i+1}, so stopping is worth 0;
  continuing earns δ per step gained when t_{i+1} is correct and −c when it fails, so the policy should continue when
  P(next correct) > c / (c + δ) = 1/3, as long as the alternative to a correct tactic is a Lean error. A valid
  tactic that leaves the proof graph for an off-graph state with evidence costs the whole drop (≈ 0.85 + progress,
  about 10× a later error; kept, since the search then keeps the off-graph child), so with 5% such steps the
  threshold is about 0.49. Example: a next tactic correct with probability 0.8 (one step gained), else
  unknown: continuing +0.16, stopping 0. Before, stopping won whenever the next tactic carried risk: in review D's
  example (b = 0.07, next tactic on the proof graph 0.4, failing 0.4, unknown 0.2) closing got +0.78 and continuing
  +0.22 in expectation; now 0 and 0.4 · 0.2 − 0.4 · 0.1 = +0.04. The dashboard charts block length and the continue
  rate after a valid tactic next to the later tactics' failure rate; a steady fall in block length means the credit
  pushes blocks short.

  Samples without a usable block (none, cut off at the token cap, empty, forbidden) score like a first failing
  tactic over the whole completion, which is how RL dampens repetition loops. Magnitudes are settings.
  Sequence-level credit (every token gets the sample's score − b, which still sees progress and wasted-tactic costs)
  stays as an option for the single-step comparison.
- **Example** (root of `algebra_2varlineareq_xpeeq7_2xpeeq3_eeq11_xeqn4`): A writes the proof (`have h₂ : x = -4
  := by linear_combination h₁ - h₀`, `have h₃ …`, `exact ⟨h₃, h₂⟩`): every tactic positive (the first against b₁,
  the later ones by the steps they gain). B writes the same first `have`, then a failing `have h₃ : e = 11 := by
  linarith`: the first tactic reaches A's state after one tactic (positive), the failing one gets −c, the rest is
  masked. C proves `e = 11` first, then fails: a new state never expanded (neutral), then −c. D writes
  `have h₄ : x + e = 7 := h₀`: redundant, −0.15 − b₁, negative.
- **Exact sampling data**: the search records every sample's sampled token ids and vLLM log-probabilities; the
  trainer trains on those tokens (no re-tokenization) and computes log-probabilities with the logits divided by the
  sampling temperature (0.8), so the PPO ratio compares like with like; the recorded log-probabilities are logged
  against the trainer's for the mismatch. **Forced answers are kept**: there is no length filter in the trainer
  (the old 1,088-token limit was the old trainer's explanation cap plus a 64-token margin and silently dropped all
  1,605 forced samples, 2.7%); the text the harness inserts (the fence after the cap) is masked, the rest trained.
  The sampling cap of 1,024 explanation tokens stays (90% of samples are below 760 tokens).
- **Policy version per expansion** (decided 2026-10-29): every expansion records the published policy version that
  sampled it; the trainer reports the sampler agreement per sampling version and the dashboard by sampling age (the
  version trained from minus the version that sampled). No importance correction: searches pause during training,
  so samples older than the current version come only from trees that spanned a pause.
- **Precision** (decided 2026-10-29): the policy does not train a fresh GRPO adapter on merged SFT weights. Merged
  bf16 weights lie on the bf16 grid, so small updates round away (at a per-element update of std 1e-5, 88% of
  elements stay unchanged and ~28% of the update survives; review D). It continues the SFT adapter on raw
  Qwen3.5-4B, so the merged weights lie between grid points and the rounding is unbiased; the same adapter is the KL
  reference. FP16 serving (8× finer grid) is a node test against an fp32 reference (log-probabilities on a few
  hundred samples, plus throughput), alongside bf16-merged and unmerged LoRA serving; fp32 serving is not viable
  (memory, ~2× slower, no fast attention kernels). The trainer computes the output layer (lm_head) in fp32 per chunk
  of 512 positions, in scoring and training alike (bf16 logits step by 0.125 at |logit| 16–32, a ratio change of
  ×1.17 at T = 0.8).
- **Optimization** (implemented defaults): PPO-style clipped objective per token, clip range [1 − 0.2, 1 + 0.28];
  old log-probabilities from the trainer's own weights before the phase's first update, logged against the recorded
  vLLM log-probabilities; KL (k3 estimator) measured to the data-collecting policy and to the starting weights (the
  latter on 256 sampled sequences per phase while it is only reported), penalty coefficient 0; the mean probability
  ratio and clip fraction of the positive- and of the negative-advantage tokens logged per pass; loss normalized as Σ token loss / (sequences in the step × 256), so there is no
  per-sequence mean and no length bias; the starting adapter's rank (64), learning rate 1e-5, 64 sequences per
  step, `passes_per_phase` 2 (1 allowed); NLL replay (the rewritten Lean SFT data and math) at weight 0.1;
  data-parallel on four GPUs (one as the fallback).
- **No control run** (decided 2026-10-28): a second full loop is out of budget. The credit comparison happens in
  the single-step test.
- **Implemented** (2026-10-29; `src/lean_search/rl/README.md`, `search/tactic_labels.py`): per-tactic labels from
  `Edge.tactic_goals` matched to nodes by goal key (proof graph, off graph, unknown, no progress, redundant
  hypothesis, failing, masked), with the proof graph at tactic granularity (an edge whose intermediate state is
  another node's routes through it); groups only at expanded proof-graph nodes with a policy proof; the credit rules
  above (`progress_per_step` 0.2, `wasted_tactic_cost` 0.1, `no_progress_local` −1, `off_graph_min_expanded_nodes`
  4, closing bonus 0.1 per goal, μ = `value_share` 0); unknown tactics untrained and samples without a known score
  outside the baseline; tactics mapped to tokens by decoding the recorded token ids (tokens before the first
  tactic's span are the explanation, the gap before a tactic is that tactic's, tokens after the last tactic the
  closing part); groups and texts matched per tree; `credit = "sequence"` (`phase_sequence_credit.toml`) for the
  single-step comparison; the trainer on the recorded tokens at the recorded temperature, inserted text masked, no
  length filter (only an assert at the servers' context). Old trees without token ids are tokenized again (offline
  only, counted). On the visible student's 244 old-format trees (no tactic states, n = 16, no harvesting), under the
  credit rules before 2026-10-29: 216 groups (1.26 per solved tree), 166 with a non-zero advantage; group tactics
  12.8% proof graph, 2.5% off graph, 20.1% unknown, 1.5% no progress, 0.4% redundant, 32.0% failing, 30.6% masked
  (unflattened blocks); 11.8% of group samples have no known score; the local term carries 17.6% of the summed
  |advantage|.

### Value model

Diagnosis: v0 never saw a dead end (trained on human-proof states only, all provable and on-path) and cannot
separate dead from live states in search trees (AUC 0.35–0.55); it ranks remaining steps with Spearman 0.80 on
held-out human proofs but 0.55–0.73 on our own search trees (0.39 on few-shot trees). The loop's value gate was
measured on far too few states to tell whether loop training helped or hurt. A representative value model is the
foundation of everything above, so it comes first.

- **Target** (AlphaZero-style): the probability that the current policy finds a proof from this state within the
  budget, plus a remaining-steps head trained only on proof-graph nodes, where steps are exact. The value model's
  ninth bin ("dead") is read as "no proof within the budget", the complement of the proof probability. The A*
  priority combines both (high proof probability and few remaining steps first; exact formula open).
- **Targets and weights per node** (decided 2026-10-27, replacing purely averaged targets, which made ~90% of all
  targets the model's own estimates): every expanded node gets `y = (1 − μ) · z + μ · q` with **μ = 0.15**, the same
  mix as the policy's global term:

  | Node | z (concrete label) | q (value part) | Weight |
  |---|---|---|---|
  | On the proof graph | 1, exact remaining steps | average below (or own estimate) | high |
  | Expanded, off the proof graph, in solved and unsolved trees ("no proof within this budget", censored) | 0 | **average** over the expanded descendants reachable via new-state and transposition edges (each once, no back-edges): proof probability = mean of their values; steps = mean of (distance + h); own estimate if there are none | grows with the number of expanded descendants (a node expanded once in a tree the search then abandoned is weak evidence for "no proof") |
  | Never expanded | — | — | no target |

  Unsolved trees are kept on purpose (confirmed 2026-10-28): without them the model never sees hopeless problems
  and stays like v0, which never predicts dead.

  Concrete labels thus make up at least 85% of every target; nothing is trained purely on estimates. Dead ends
  (expanded nodes whose 8 samples and sweep produced nothing usable, ~6% of expanded nodes) are no longer a
  separate category: they are off-graph nodes with z = 0 and appear only as a dashboard statistic. Lean-error edges
  have no state; they enter only the policy reward. The average was chosen over max/min for a stable q: best-first
  search expands mostly promising nodes, so the average is dominated by good branches; a temperature parameter can
  slide it toward the maximum later.
- **Sibling ranking loss**, only among children of the same expanded node (identical states merged first; children
  reached by transpositions count as siblings), logistic on the difference of the log-odds of the proof
  probability, added to the pointwise loss with a mixing factor: the proof-graph child against each expanded
  off-graph sibling (weight growing with the sibling's subtree) and against never-expanded siblings (weight 0 at
  first: they may be provable too). Unsolved trees give no pairs (no concrete label differs); pairs of two off-graph
  siblings ranked by their estimates are not used (noise against noise).
- **q from recorded bins** (decided 2026-10-29): every scored node stores its bin distribution in the tree record,
  and q's proof probability is `1 − p_dead` of the recorded bins (steps: the expected steps given alive). Trees
  written before the bins were kept fall back to the linear readout `(D − h) / (D − 1)` of the scalar h, which is
  not a probability.
- **The value model in the loop** (decided 2026-10-29; before, it retrained every phase from the published adapter on
  that phase's trees alone, so a rejected model's data was lost): it retrains **every 4 phases on the trees of the
  last 8 phases**, continuing the last adapter trained (accepted or not), with **10% replay of v0's training data**
  (exact remaining steps of traced proofs). Every retrained value model is published with the next version and
  searched with (decided 2026-10-29: no gate, "Benchmark and value trends").
- **Guards against a self-reinforcing loop**: the concrete label carries 85% of every target and is never
  overwritten; leaf values come from the value version that ran the search (a frozen target network); best-first
  search replaces optimistic estimates of expanded nodes by their children's values; per-batch source shares and a
  cap on targets per tree, so large unsolved trees do not dominate; the 10% v0 replay; retraining from the base
  checkpoint is a setting (`retrain_from_base`, off); μ stays 0 unless turned on by hand, and the benchmark and
  value-arm trends below show a value model going wrong.
- **Not done**: extra searches only to label states (AlphaZero does not need them either).
- **Implemented** (`src/lean_search/value/graph_targets.py`, `ranking.py`, `graph_trainer.py`): weighted soft
  cross-entropy on the bins plus the ranking loss (0.5 × softplus of the negative score difference), pair members
  in the same micro-batch, learning rate 5e-5, at most 64 targets and 64 pairs per tree. The μ-mix and pairs of this
  section are implemented (2026-10-28): the bin target is `(1 − μ) · bins(z) + μ · bins(q)` (z: smoothed exact steps
  on the proof graph, all-dead off it; q: its proof probability over the step bins at its steps, the rest dead), so
  `1 − p_dead` is y; `value_share` (μ) is 0 in the GRPO phase configs, and the loop sets it per phase; off-graph
  weight `0.5 · n / (n + 4)` for n expanded nodes in the subtree; per-step source shares proof graph 0.4, off graph
  0.6. Remaining steps and q's distance count top-level tactics (`applied_tactics` per edge). On the visible student's
  244 trees: 287 proof-graph and 4,535 off-graph targets (4,303 from unsolved trees), q from descendants for 2,949,
  the own estimate for 1,873; proof-graph steps median 2 tactics (mean 3.8) vs 1 block (mean 2.0).

### Benchmark and value trends

- A fixed value benchmark of a few thousand states from search graphs of the current policy, including
  never-expanded children. Metrics: ranking among siblings (proof-graph child above its siblings), calibration of
  the proof probability, dead/live separation, remaining-step error on proof-graph nodes.
- **No circularity**: labels from a search guided by a value model are selected by that model. In the visible
  student's v0-guided trees every labelled sibling pair is ordered exactly as v0 ordered the expansions (sibling
  expanded first: v0 rated it higher in 52 of 52 pairs; proof child expanded first: 23 of 23; never-expanded
  siblings: 253 of 253 rated lower), so v0 looked "worse than chance" on proof-vs-dead pairs by construction. The
  benchmark is therefore built from searches **without a value model** (log-probability best-first of the starting
  policy on held-out statements), pairs are counted only when both sides carry a known label (never-expanded
  siblings are unknown, not negatives), every model is scored fresh on the same states, and calibration is reported
  only for models with a probability output.
- v0 measured without circularity (row-2 trees, a log-probability search, `results/phase3_astar_v0_sft_v2/`):
  Spearman 0.65 for remaining steps, but p_dead ≈ 1e-7 on every state and dead AUC 0.47: it never predicts dead.
- Implemented (`src/lean_search/value/README.md`, "Value benchmark"): each benchmark records its runs' provenance
  and refuses value-model-guided trees (configurable to a warning), models are scored fresh through vLLM into stored
  per-state bin distributions, and recorded h is ranking/steps only and flagged when circular. Benchmark trees:
  `experiments/configs/value_benchmark_search.toml`; the loop's benchmark is the gate set's (`grpo/gate_search.toml`,
  unchanged). Proof-graph children rarely have a dead-end sibling (2 such pairs among 4,228 states of the row-2 v2
  trees; ~50 proof-over-expanded and ~160 expanded-over-dead-end pairs), so the AUC over proof-graph and dead-end
  states carries more weight than the proof-over-dead-end pair accuracy.
- **No value gate** (decided 2026-10-29 by the owner, replacing the two gates of the same day: a bootstrap gate (a) on
  publishing and an A/B search (b) that switched μ on or reverted to v0; from AlphaZero experience gating did not
  help): every retrained value model (every 4 phases, window of 8) is published with the next version and used by
  the searches. The statistics stay, as trends on the dashboard, and nothing acts on them automatically.
  - **Benchmark trend**: once a new value model is served, the loop scores the benchmark through the value servers
    while the searches run (the search's own scoring path; ~30–60 s of value-server load per retrain instead of a
    segment of the training pause), keeps the scores per value version (`value_benchmark/scores_v<k>.json.gz`) and
    writes, per value version: the share of labelled sibling pairs whose proof-graph child gets the lower h (the
    quantity A* orders its frontier by; ties count half), its difference to v0's and to the previous value model's
    with a **paired cluster bootstrap over problems** (5,000 resamples, fixed seed, 95% percentile interval), and the
    diagnostics (AUC, Brier and ECE on expanded states, pair accuracy by kind, Spearman and MAE of the steps, the
    predicted distributions). A scoring the servers fail is retried after the next phase; the phase's pause waits for
    a scoring in flight.
  - **Value arm** (replacing the 250-problem A/B every 12 h): every other probe slot ("Fixed targets") searches its
    third again with the published value model and the same policy version, paired per problem with the slot's run
    with v0. Per slot and pooled (over the slots of the same published value model, and of every value model): the
    paired solve-rate difference with McNemar's exact interval (Clopper–Pearson on the problems one arm solved,
    conditional on their number) and one-sided exact McNemar p-values. An **alert** (dashboard and `loop.log`) only
    when the published value model is worse than v0 at p < 0.05, pooled over its own value arms; nothing changes on
    its own.
  - **μ is a manual switch, starting at 0**: `deployment/grpo_loop.sh value-share 0.15` (`grpo_loop.py
    set-value-share`) writes `value_share.json` in the run directory; the loop reads it each time a phase starts
    training, so it takes effect from the next phase to train (0 turns it off). The μ in effect is on the
    `value_phase` line of every phase and in `phases.jsonl`.
- **Free per-phase value metrics** (no extra search): from each phase's labelled training trees and the bins the
  serving value model recorded, the `value_phase` line holds the label distribution per bin (targets by source and
  tree outcome, exact steps unsmoothed) next to the predicted distribution of the same states (and of the
  never-expanded frontier: mean per bin, p_dead per tenth, expected steps given alive), the calibration of the proof
  probability against z on expanded states (reliability bins, ECE, Brier), and the remaining-steps MAE and Spearman on
  proof-graph states, whose exact steps (the shortest route to a proof) do not depend on the order the search found
  them in. Each retrain also records the label distribution of its window (smoothed as trained) and the v0 replay.
- **Evaluations with a fixed value model** (decided 2026-10-29): the probe and miniF2F always search with v0 as the
  value model (the value servers swap to v0's kept merged weights and back), so they measure the policy alone; the
  held-out states use no value model. The value arm is the one exception, by design.
- **Measured weakness of the pair statistic**: on the value-free row-2 trees (miniF2F-valid, 244 trees) the
  benchmark gives only ~52 labelled pairs over 13 problems; in simulations on that structure the 95% half-width is
  0.08–0.17, and a gain of +0.10 lies above zero in only 22–61% of retrains. The gate set's 402 problems give about 1.6
  times the pairs. A trend over retrains is read more reliably than one interval; the gate search stays as it is
  (decided 2026-10-29: no wider search for now).

### Fixed targets

- **Probe set** (decided 2026-10-28): about 500 held-out pool problems, stratified easy / medium / hard by the
  curriculum's difficulty estimate (not mostly easy; 501 problems), searched at a small budget (16 expansions) with v0
  as the value model. Small budgets because RL improves efficiency first (126 of 166 miniF2F solves came at the first
  expansion). **Rhythm** (decided 2026-10-29, for a smoother trend at the same cost): the set is split into three
  stratified parts (every third problem of each stratum, ~167 problems each), and every ~2 hours of loop time a
  **slot** searches the next part, attached to the phase pause as before; the whole set is covered every ~6 hours,
  ~1,670 expansions per slot, estimated 13–20 min on 4× 3090 at n = 8 (the whole set: about 5,000 expansions, 40–60
  min, from the old 2× 3090 node's 4,577 expansions at n = 16 in 124 min; GPUs were the bottleneck), ~10–15% of
  compute as before. The dashboard draws each slot's point and a rolling curve over the last three slots (the whole
  set, each problem once, across their policy versions), per stratum too. **Validity** (decided 2026-10-29): the
  per-problem wall cap is 3,600 s, an emergency stop only, so the expansions are the budget and the probe does not
  measure load; wall-clock stops are counted and reported and should be zero. Evaluation concurrency is 64.
  **Version 0's probe runs twice** (independent runs) to measure the run-to-run noise later versions are judged
  against: before the first phase all three parts run twice (slots 0–2), the per-part differences and discordant
  problems are on the dashboard and their sums in `loop.log`. **Value arm**: every other slot also searches its part
  with the published value model ("Benchmark and value trends"), ~13–20 min every ~4 hours, about the cost of the
  A/B it replaces (2 × 250 problems every 12 h).
- **miniF2F-valid** at the full budget (64 expansions, n = 8; ~1–1.5 h) at the start, at milestones and at the end
  (the baseline before phase 1 automatically, the others on request; not on a clock), also with v0 as the value model.
- Per-sample success on the 512 held-out states with every probe (no value model). MATH-500 retention (visible and
  thinking) at milestones, run separately (`reasoning_retention.py`; not in the loop). Curves over training, not
  just a final score. Baselines are re-measured on the new node with the new settings (n = 8, heartbeat limits,
  flattening), since the old numbers used n = 16 and wall-clock limits.
- The value benchmark comes from a separate held-out problem set (the gate set, searched once without a value model,
  ~1–2 h), so value models are not judged on the evaluation set and the pair statistic gets enough pairs.
- Timings are measured in the first hour on the node.

### Order of work

1. **Implementation before renting** (local, WSL; Lean-dependent tests run there). Done and merged (2026-10-27):
   WSL development environment with direct downloads; graph labelling (proof graph, edge kinds, statistics); value
   targets, sibling pairs, value benchmark without circularity and fresh scoring; GRPO trainer with per-token credit
   and the outcome-only control; value trainer and gate; the dashboard (self-built, open by default); the harness
   (heartbeats, flattening, `rename_i`, identifier check, full sample texts, unparsed samples). Done since
   (2026-10-29): per-tactic states, per-tactic labels and credit, groups only at proof-graph nodes, the μ-mix,
   harvesting and ε-exploration, recorded tokens and log-probabilities with the temperature in the trainer, no
   length filter, two passes as a setting, the dashboard metrics of proofs, harvesting and credit labels; then the
   data rewrite (flattening, chunks, descriptive renaming; `data_rewrite/`); the loop integration (`rl/loop.py`,
   `experiments/grpo_loop.py`, `grpo/loop.toml`: search → label → pause–train–publish, all dashboard families,
   restart from the last stage and the tree store); the probe, value-gate and overfit statement sets
   (`grpo_fixed_sets.py`), the probe / miniF2F / held-out-states evaluations (`grpo_evaluate.py`, inside the loop's
   pauses), the gate's value-free benchmark search; optional search-time renaming with every proof checked against
   the original statement; the cheap tests as runnable experiments (`grpo_single_step.py`, `grpo/loop_overfit.toml`,
   `grpo_naming_ab.py`); the node bring-up (`deployment/grpo_loop.sh`, `deployment/README.md` "GRPO loop"). Done
   later on 2026-10-29, after reviews C and D (`results/reviews/2026-10-29_review_{c,d}.md`): the credit rules (no-op
   as failure, a policy proof per group, thin off-graph evidence unknown, progress δ, later tactics within the block,
   closing at 0); the trainer fixes (per-tree text matching, fp32 lm_head, the continued SFT adapter on raw
   Qwen3.5-4B, policy version per expansion, replay from the rewritten data); visible chunk explanations by the
   teacher; the loop systems (process groups, server-failure re-queue, host memory budget, probe wall cap and
   repeated baseline, original names for value in the naming A/B); all four GPUs serving and training data-parallel
   with timed pause segments; the value model in the loop (recorded bins, windowed retraining, v0 for evaluations,
   value diagnostics). After reviews E and F: the curriculum judged on the statements fed first, the server check and
   restart, torchrun's workers stopped with their job, the REPLs stopped before training, adapter retention and a disk
   metric, and the node check and smoke cycle (`grpo/loop_smoke.toml`). Owner decisions of 2026-10-29: no value gate
   (every retrained value model published, the benchmark scored through the value servers as a trend), μ a manual
   switch, the probe in rotating thirds every ~2 h with a paired value arm every other slot, per-phase value metrics
   from the training searches. Details: `src/lean_search/rl/README.md`. Nothing ran on a GPU or a vLLM server yet:
   the first-hour checks of `deployment/README.md` come first.
2. **New node**: the node check (disk, `/dev/shm`, a 4-rank NCCL all-reduce), rebuild, smoke tests, the heartbeat
   replay test, the loop's smoke cycle (one hour, every stage and evaluation at a tiny size), baselines with the new
   settings (student v2, value v0). First-hour checks (`deployment/README.md`, "GRPO loop"): `grpo_loop.sh check` (recorded tokens and
   log-probabilities, usable blocks); **serving precision**: fp16-merged, bf16-merged and unmerged LoRA serving
   against an fp32 reference (log-probabilities on a few hundred samples, plus throughput); the probe's wall time,
   its wall-clock stops (should be zero) and the two version-0 runs for the noise; host memory while sampling, while
   training and during a probe, against the budget; the first phase's pause segment by segment (four GPUs vs
   `gpus = [0]` if the fixed segments dominate), training vs sampling time (one or two passes) and the ranks' peak
   memory; phase 1's first step at `mean_ratio` 1 and `clip_fraction` 0; the sampler-vs-trainer difference, overall
   and by sampling age; after phase 1, that the merged policy weights differ from version 0's in a large share of
   the adapted layers' elements; server failures at 0.
3. **Cheap tests before the loop**: the naming A/B (two short fine-tunes); single-step GRPO on the 512 states with
   per-tactic and sequence-level credit (does the policy improve on states it trained on, which credit is better,
   about a GPU-hour); an overfit test on ~300 statements (the loop must drive their solve rate up).
4. **SFT stage**: rewritten data (re-trace the selected proofs flat), the teacher's chunk explanations in the
   naming run (~9,500, ~15–20 min on 4 GPUs), the naming the A/B picked, a gentle fine-tune continuing v2's adapter
   on raw Qwen3.5-4B; the starting policy.
5. **Value benchmark**: the gate set searched once by the starting policy without a value model (~1–2 h).
6. **GRPO loop** with μ = 0 (proof graph only); the value model retrains in the loop every 4 phases and is always
   published; μ is turned on by hand when the owner decides (`grpo_loop.sh value-share`).
7. Write-up on the homepage: the ladder, the RL curves, what the dense signal adds.

### Dashboard

A self-built dashboard (no dashboard framework): a small web server in the project serving our own pages and
charts from the metrics files, with an overview page of the most important values and detail pages per area
(policy/GRPO, value, search/Lean, curriculum, evaluations, system); it grows as gaps appear. It runs on the node
and is exposed on an open port (read-only, so open by default; a password is optional; HTTPS through a tunnel
where possible), laid out for phones too, so a multi-day run can be checked from anywhere; TensorBoard has no login
of its own and stays behind SSH or the tunnel. Overview page: status (loop
running, phase, versions, time since the last publish, proofs per hour, GPU and Lean CPU utilization, money spent),
headline curves (the fixed targets against the baseline), RL health, value health, search
behaviour, warnings (rising no-progress share, KL too high, repetition loops, MATH dropping). Logged per phase
from day one:
- value targets by source (proof graph, dead end, averaged), the subtree sizes behind averaged targets, the number
  of never-expanded children;
- edges by kind (error, timeout, new state, no progress, back to an ancestor, sibling duplicate, transposition,
  repeat); a rising no-progress share is an early warning of reward hacking;
- failures by tier (malformed, invalid in the state, valid but failing, timeout) per policy sample, block lengths,
  repeats of failed sweep tactics, forced answers and repetition loops;
- value (decided 2026-10-29): μ in effect per phase; per phase from the training searches the label and the
  predicted distribution per bin and source, p_dead and expected-steps histograms, calibration on expanded states and
  the remaining-steps error and Spearman on the proof graph; per served value model the benchmark trend (pairs ordered
  by h, against v0 and the previous model with bootstrap intervals, AUC, Brier, calibration, Spearman); per value-arm
  slot the paired difference to v0 and its pooled values with exact intervals, and the alert when worse; per retrain
  the window's label distribution and the training loss;
- GRPO: share of groups with mixed rewards, groups left out without a policy proof, reward split into local and
  global, tactics by credit label (proof graph, off graph, unknown, no progress, redundant hypothesis, failing,
  masked), KL and clip fraction, the sampler-vs-trainer log-probability mismatch overall and by sampling age,
  explanation length, forced answers kept;
- blocks (decided 2026-10-29): tactics and valid tactics per sample, the continue rate after a valid tactic and the
  later tactics' failure rate; a steady fall in block length means the stop credit pushes blocks short;
- proofs (decided 2026-10-28): proof length in tactics and in blocks, proofs per solved problem, the share of
  proof-graph nodes, harvest yield (proofs and proof-graph nodes per harvest expansion), the share of ε-picks;
- time: training vs sampling per phase (decides one or two passes) and every pause segment;
- health and budget (decided 2026-10-29, the Training page): each health check's signal with its threshold, the
  latest phase's alerts in the alert list; solves in the budget's last quarter, expansions to the first proof, proof
  lengths and the difficulty of solved statements per phase, trainable groups per phase;
- system: host memory (limit, available, Lean REPL private memory total and p90, vLLM private memory), server
  failures and statements given up;
- fixed targets (above): the probe per slot and over the last three slots, per stratum, with wall-clock stops and
  the version-0 repeat's difference and discordant problems per part.

### Relation to other recipes

| Recipe | Credit per step | Users |
|---|---|---|
| Outcome-only GRPO on whole proofs | none; sequence-level pass/fail, curriculum filter | DeepSeek-Prover-V1.5-RL, Kimina-RL, Goedel-V2 |
| Expert iteration / rejection sampling | successes only | Polu 2022, Goedel, STP, BFS-Prover |
| DPO on search-tree sibling pairs | local pairs labelled by the global outcome | BFS-Prover V1, our first loop |
| Search distillation | policy toward the search's choices, value toward outcomes | AlphaZero, AlphaProof, HTPS |
| Process rewards from subtree outcomes | step value from continuations | Math-Shepherd, VinePPO, tree-based GRPO variants |
| Backed-up value targets for every searched node | value trained on the subtree's backed-up value | TreeStrap (Veness et al. 2009) |
| **This plan** | sibling groups, local reward + proof-graph / backed-up global term | closest to HTPS and tree-based GRPO |

Paper names in the last three rows are from memory and still need checking before the write-up.

### Open

- Hardware offers within the budget.
- Owner decisions (2026-10-29): implemented: no value gate (every retrained value model is published; the
  benchmark, scored through the value servers during sampling, and the paired value arms are dashboard trends only,
  with an alert when the value model is worse than v0), μ a manual switch starting at 0 (`grpo_loop.sh value-share`),
  the probe in rotating thirds every ~2 h, per-phase value metrics from the training searches; phases ending at 300
  trainable groups within 45–90 min; 32 expansions per loop search with budget signals; per-phase health checks
  (alerts, a hard stop on a valid-Lean collapse with rollback), their thresholds calibrated in the first phases; a
  persistent trainer with in-memory weight handoff (built, not yet run on a GPU). Open: learning rate 1e-5 vs 3e-5
  decided by the single-step test on the node.
- Serving precision: fp16-merged vs bf16-merged vs unmerged LoRA, decided by the node test against fp32.
- Whether the four-GPU pause with the persistent trainer meets its ~1 min fixed part on the node (smoke cycle: pause
  segments, `compiled_graphs` 0 after the first phase, the wake's memory next to the parked ranks' CUDA contexts, the
  sampling condition of the host memory budget during the handoff); else `gpus = [0]` or `persistent = false`.
- Reward magnitudes (δ, c, the closing bonus, the off-graph evidence threshold), the A* priority formula combining
  proof probability and steps, the value-average temperature, the exact weights by subtree size, the expansion
  budget of the fixed miniF2F evaluation.
- Whether flattening plus mixed step lengths bring the failure rate of long blocks (9+ lines: ~80%) down.
- Not implemented: the "not valid Lean" negative from any tree (Policy update, first bullet). It needs a classifier
  of failure messages into the tiers of the error analysis (syntax errors and unknown constants vs the rest), which
  the code does not have yet; the identifier check's `UNKNOWN_IDENTIFIER` alone mixes unknown constants with
  unknown hypothesis names. Then: those samples as separate single-sample terms with a small negative advantage.

## Known issues (backlog)
- Resolved: search generation cost is charged per batch (`CandidateBatch`), when the expander yields it. Runs before
  the fix did not charge requests whose samples all failed to parse (in `PolicyStatistics.unattributed_generated_tokens`
  instead) nor candidates left unexecuted after a proof, so their token totals are low, most for thinking mode.
- Resolved: a run whose search raised could hang forever in `asyncio.run`'s shutdown (another search restarted a REPL
  after the pool closed); failing runs now exit with the original exception (`src/lean_search/lean/README.md`).

- Statement pools: some Lean Workbook statements lack the colon before the goal; `π` is ambiguous under
  `open … Nat Real` in the pinned Mathlib.
- Resolved in the Lean layer (`src/lean_search/lean/README.md`); data traced before the fix still has the old
  behavior: pattern-matching steps (`intro ⟨a, b⟩`, `fun ⟨…⟩`, `match`) and statements with their own matchers
  (`{(x, y) | …}`) now replay step by step; a second header in a process no longer re-imports Mathlib (3.9 GiB);
  a header without Lean is a `LeanError`; the "closed a goal with sorry" error keeps Lean's message; deterministic
  runtime panics (`Nat.pow exponent is too big`) are `LeanError(panic=True)`, a negative label. Re-tracing the
  455 traced proofs that failed with "closed a goal with sorry" or "unknown constant": 142 now replay completely
  and verify, 124 show the heartbeat timeout the old message hid, 189 keep a genuine error. 500 sampled complete
  proofs replay with identical goals (1,669 steps); 4 heavy `nlinarith` steps (17–59 s before) now exceed the 60 s
  backstop, because their runtime is chaotic in Lean's fresh-name counters, which shift whenever the base
  definitions change.
