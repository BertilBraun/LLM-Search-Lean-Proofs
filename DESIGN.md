# Design: LLM-guided best-first proof search in Lean 4

## Goal

Measure how far a small (~2B parameter) language model can be pushed on formal theorem proving when it is
combined with search, a learned value function and cheap training loops, on a budget of a few hundred dollars.
Success is a significant improvement over the base model **at fixed compute**, reported as solve-rate-vs-compute
curves and an ablation ladder on miniF2F. Reaching the published reference provers (70–95% on miniF2F) is not
the goal.

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
  one GPU serves while the other trains.

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

- [ ] **Phase 0** — Environment, REPL wrapper, miniF2F loading and statement check, Lean cost measurements,
  automation-only best-first baseline (ladder row 0).
  - [x] Lean v4.9.0-rc1 + Mathlib `d1d1e4b7` + REPL pinned; all 488 statements load; costs measured
    (`results/phase0_environment/`). Lean is cheap: ~3.7 s per process start, ~0.24 GiB private memory,
    ~290 tactic calls/s with 32 processes.
  - [ ] Search core and automation-only baseline.
- [ ] **Phase 1** — Model probe (throughput, valid-Lean rate, progress rate; few-shot and after short SFT);
  base-model few-shot search (ladder row 1).
- [ ] **Phase 2** — Proof-corpus tracing, decontamination, LoRA SFT, policy search on miniF2F-valid (row 2).
- [ ] **Phase 3** — Value v0/v1, A* search, λ/D sweep (row 4).
- [ ] **Phase 4** — Retriever, applicability annotation, list-length ablation (row 3).
- [ ] **Phase 5** — Single-step on-policy reasoning (row 5).
- [ ] **Phase 6** — Expert iteration rounds (row 6).
- [ ] **Phase 7** — Final ladder on miniF2F-test, write-up in `results/README.md`.

Results of each phase are committed under `results/` as small JSON summaries plus a markdown table; large
per-theorem logs, datasets and checkpoints stay on the node.
