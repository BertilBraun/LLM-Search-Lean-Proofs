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
starting policy on the fixed targets beyond noise, and the dense signal beats an outcome-only control.

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
- **Required A/B: descriptive hypothesis names.** miniF2F and the training corpora number hypotheses (`h₀, h₁, …`);
  descriptive names might transfer general coding habits and reduce references to non-existent hypotheses (3.0% of
  samples), but they move the model away from its training distribution. Two variants of the fine-tune above:
  numbered names (as today) and descriptive names. For the second, a language model proposes names; they are
  renamed consistently in states, tactics, the model's own `have` names and the explanations, and verified by
  replay. Benchmark statements keep their meaning (binder names do not change the proposition; the final proof is
  checked against the original statement). The search renames hypotheses in each statement the same way.
  Compared on the 512 states (renamed accordingly), miniF2F-valid at the fixed budget and MATH-500; the winner is
  the GRPO starting policy.

### The loop

1. Search a batch of curriculum statements with best-first / A* search, **n = 8 samples per expansion** (not 16),
   without raising the sampling temperature.
2. After each search finishes, label the whole search graph (below). No training after individual steps.
3. Build GRPO groups and value targets from the labelled graphs; train policy and value in a pause–train–publish
   phase.
4. Publish after every training phase (~15–30 min); an in-place weight publish takes ~20 s, so training time, not
   publishing, sets the cadence. Watch the clip fraction and the KL between the data-collecting policy and the
   current one; if they rise, publish more often or train on smaller batches.
5. The curriculum keeps the solve rate around 30–70%, so groups carry signal and trees are balanced between
   solved and unsolved. Hard problems absorbing most of the budget is expected; the curriculum and escalation
   stages bound it.

### Search graph and labels

The search is a graph: a tactic that reaches an existing state records a duplicate edge to it. In the visible
student's 244 trees: 66.2% of attempts fail (Lean error or timeout), 15.5% create a new state, 14.4% reach an
existing state, 3.8% repeat an earlier tactic text. Duplicates: 49% back to the same state (no progress), 4% back
to an ancestor, 21% the same state as a sibling, 26% transpositions into another branch; 56 transposition edges
lead from 14 off-path nodes into a proof (the proof graph has 458 nodes vs 444 on the found proof paths).

- **Proof graph**: every node with a route to a proof via new-state or transposition edges is on a proof. Its
  exact remaining steps are the shortest such route. Transpositions are never failures (A then B and B then A both
  prove).
- **No progress**: a block whose net effect leaves the state unchanged or returns to an ancestor (a wasted step).
  A no-op tactic inside a block that otherwise makes progress is harmless.
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

### Policy update: GRPO over sibling groups

- **Group** = the 8 samples of one expanded node (independent draws from the policy at the same state), after
  merging identical tactic texts. Best-first selection skews which states are trained, not the groups themselves.
- **Reward** = `(1 − λ) · G + λ · L`, both on a common scale, mixed AlphaZero-style with **λ = 0.15** (the local
  influence stays at about 15–20%; the proof graph decides):
  - `G` (global) ∈ [0, 1]: 1 on the proof graph (optionally slightly more for shorter remaining proofs), 0 for dead
    ends; for expanded off-path children the backed-up value (below) once the value model passed the gate; **0
    (neutral) for never-expanded children** until then (the safe fallback: the loop still works, with less signal).
  - `L` (local) ∈ [−1, 1]: −1 Lean error (heartbeat timeouts included), **−0.5 no progress** (net-unchanged state or
    back to an ancestor, so a no-op never beats a genuine attempt), 0 for a new state plus potential-based value
    shaping `h(parent) − h(child)` (cannot change the optimal policy) and a small bonus for closing a goal, clipped.
- Advantage = reward minus the group mean, **without dividing by the group's standard deviation**: with std
  normalization, groups where G is constant (most groups in unsolved trees) would have their small λ·L differences
  re-amplified to full-size advantages and defeat the 15% cap. Only relative differences within a group matter;
  absolute sums over samples (e.g. the placeholder weights' local −45,918 vs global +1,112 on the visible student's
  trees, dominated by the many −1 errors) carry no meaning. Groups with identical rewards are dropped, as in the
  mainstream recipes. The dashboard shows the effective local share of the summed |advantage|.
- Measured on the visible student's trees: 93.1% of groups have mixed rewards with the dense reward, 3.1% with the
  outcome-only reward (the control's sparsity); 72.6% of the positive local reward (placeholder weights) was earned
  off the proof graph, which is why L is capped at λ.
- **Per-token credit within a sample** (the GRPO loss is a sum over tokens, so each token can get its own
  advantage): the explanation gets the sample's overall advantage; the tactics up to the last successful one get
  the advantage of the state they reach; the first failing tactic (after flattening, the line Lean's error points
  to) gets the error advantage; everything after it is masked, since Lean never evaluated it. The SFT counterpart
  is training on the valid prefix plus unlikelihood on the failing line.
- **Control run**: the same loop with only the outcome / proof-graph signal (expert iteration via GRPO), to
  measure whether the dense part helps.

### Value model

Diagnosis: v0 never saw a dead end (trained on human-proof states only, all provable and on-path) and cannot
separate dead from live states in search trees (AUC 0.35–0.55); it ranks remaining steps with Spearman 0.80 on
held-out human proofs but 0.55–0.73 on our own search trees (0.39 on few-shot trees). The loop's value gate was
measured on far too few states to tell whether loop training helped or hurt. A representative value model is the
foundation of everything above, so it comes first.

- **Target** (AlphaZero-style): the probability that the current policy finds a proof from this state within the
  budget, plus a remaining-steps head trained only on proof-graph nodes, where steps are exact. The A* priority
  combines both (high proof probability and few remaining steps first; exact formula open).
- **Targets and weights per node:**

  | Node | Target | Weight |
  |---|---|---|
  | On the proof graph | 1, exact remaining steps | high |
  | Dead end | 0 | moderate (only 8 samples tried) |
  | Expanded, off the proof graph | **average** over the expanded descendants reachable via new-state and transposition edges (each once, no back-edges): proof probability = mean of their values; steps = mean of (distance + h) | grows with the number of expanded descendants |
  | Never expanded | none (only a weak sibling-ranking partner) | ≈ 0 |

  Lean-error edges have no state; they enter only the policy reward. The average was chosen over max/min for a
  stable target: best-first search expands mostly promising nodes, so the average is dominated by good branches;
  its pessimistic bias is similar across nodes. A temperature parameter can slide it toward the maximum later.
- **Sibling ranking loss**, only among children of the same expanded node (identical states merged first),
  logistic on the score difference, added to the pointwise loss with a mixing factor:
  - solved trees: the proof-graph child against a dead-end sibling (high weight), an expanded off-path sibling
    (medium, growing with its subtree), a never-expanded sibling (low, 0 at first);
  - unsolved trees: expanded siblings with a large subtree against dead-end siblings;
  - not at first: pairs of two off-path siblings ranked by their averaged values (noise against noise).
- **Guards against a self-reinforcing loop**: Lean anchors (proof graph 1, dead ends 0) are never overwritten;
  leaf values come from the value version that ran the search (a frozen target network); best-first search
  replaces optimistic estimates of expanded nodes by their children's values; per-batch class balance and a cap on
  labels per tree, so large unsolved trees do not dominate; a small replay of v0 data; occasional retraining from
  the base checkpoint; the gate below.
- **Not done**: extra searches only to label states (AlphaZero does not need them either).

### Benchmark and gate

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
  per-state bin distributions, recorded h is ranking/steps only and flagged when circular, and the gate scores both
  adapters fresh. Benchmark trees: `experiments/configs/value_benchmark_search.toml`. Proof-graph children rarely
  have a dead-end sibling (2 such pairs among 4,228 states of the row-2 v2 trees; ~50 proof-over-expanded and ~160
  expanded-over-dead-end pairs), so the AUC over proof-graph and dead-end states carries more weight than the
  proof-over-dead-end pair accuracy.
- The decisive test: an A/B search with the policy fixed and only the value model swapped, solve rate at a fixed
  budget.
- A value model is published only if it beats the current one on the benchmark; value pseudo-labels for
  off-path children (and value-based rewards) are switched on only after a model passed.

### Fixed targets after every phase

- Per-sample success on the 512 held-out states; miniF2F-valid at a fixed search budget (n = 8; the expansion
  budget is set when the baselines are re-measured); MATH-500 retention (visible and thinking). Curves over
  training, not just a final score. Baselines are re-measured on the new node with the new settings (n = 8,
  heartbeat limits, flattening), since the old numbers used n = 16 and wall-clock limits.

### Order of work

1. **Implementation before renting** (local; Lean-dependent tests on a local Linux environment or a cheap CPU
   instance): flattening, name checks and renaming of inaccessible hypotheses in the harness; heartbeat-only limits;
   graph labelling (proof graph, dead ends, duplicate kinds); value targets (averaging, weights, sibling ranking)
   and the value benchmark; GRPO with per-token advantages and the outcome-only control; dashboard logging; the
   data rewrite (flattening, chunks, descriptive renaming). Each with tests.
2. **New node**: rebuild, smoke tests, the heartbeat replay test, baselines with the new settings (student v2,
   value v0).
3. **SFT stage**: rewritten data (re-trace the selected proofs flat), both naming variants, gentle fine-tunes from
   v2, compared on the fixed targets; pick the starting policy.
4. **Value**: benchmark, value v1 from search-graph targets, A/B search against v0.
5. **GRPO loop** with the neutral fallback (global term from the proof graph and dead ends only).
6. Value pseudo-labels once v1 passed the gate.
7. Control run with the outcome-only signal.
8. Write-up on the homepage: the ladder, the RL curves, what the dense signal adds.

### Dashboard

A self-built dashboard (no dashboard framework): a small web server in the project serving our own pages and
charts from the metrics files, with an overview page of the most important values and detail pages per area
(policy/GRPO, value, search/Lean, curriculum, evaluations, system); it grows as gaps appear. It runs on the node
and is exposed on an open port behind authentication (HTTPS where possible), laid out for phones too, so a
multi-day run can be checked from anywhere; TensorBoard is exposed the same way. Overview page: status (loop
running, phase, versions, time since the last publish, proofs per hour, GPU and Lean CPU utilization, money spent),
headline curves (the fixed targets against the baseline and the control run), RL health, value health, search
behaviour, warnings (rising no-progress share, KL too high, repetition loops, MATH dropping). Logged per phase
from day one:
- value targets by source (proof graph, dead end, averaged), the subtree sizes behind averaged targets, the number
  of never-expanded children;
- edges by kind (error, timeout, new state, no progress, back to an ancestor, sibling duplicate, transposition,
  repeat); a rising no-progress share is an early warning of reward hacking;
- failures by tier (malformed, invalid in the state, valid but failing, timeout) per policy sample, block lengths,
  repeats of failed sweep tactics, forced answers and repetition loops;
- value benchmark metrics;
- GRPO: share of groups with mixed rewards, reward split into local and global, the share of local reward earned on
  states that never lead to a proof, KL and clip fraction, explanation length;
- fixed targets (above).

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
- Local reward magnitudes, β, the A* priority formula combining proof probability and steps, the value-average
  temperature, weights by subtree size, the expansion budget of the fixed miniF2F evaluation.
- Whether flattening plus mixed step lengths bring the failure rate of long blocks (9+ lines: ~80%) down.

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
