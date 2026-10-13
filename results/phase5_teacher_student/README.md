# 9B teacher, 4B student: does a larger model's reasoning make a better thinking policy?

Qwen3.5-9B (post-trained, no fine-tuning) writes bounded reasoning for traced train states, the 4B SFT policy
(`phase2_sft_4b`) is trained on it, and the student is compared with the 2B bootstrap policy
(`phase5_sft_bootstrap_r1`) per step and in the equal-token search. 2026-10-13, both RTX 3090s; Lean work pinned and
niced via `deployment/background.sh`, at most 16 REPLs. Configs: `experiments/configs/reasoning/phase5_teacher_9b.toml`,
`phase5_data_teacher_9b.toml`, `phase5_sft_student_4b.toml`, `phase5_eval_student_4b_*.toml`,
`phase5_search_student_4b_*.toml`; run summaries in `runs/`, the search report in `search/`.

## Step 1: teacher data (16:42–18:51 UTC)

- **States**: the first 3,072 of the 2B bootstrap's pool of SFT-unseen traced train states (Goedel SFT v2 and STP),
  after dropping the 697 of 8,000 that the 4B's own SFT data (`sft/4b`, a 20M-token sample of the v2 mix) contains;
  disjoint from the validation states of every evaluation.
- **Teacher**: Qwen3.5-9B, thinking with the brevity instruction, cap 1024, k = 8, temperature 0.8; one server per GPU
  (`--max-num-seqs 64`), 4.6 samples/s per GPU, 92 minutes.
- **Yield**: 23.5% of samples succeed, 40.6% of states have a success (validation probe: 28.7% / 44.5%); 24.9% are
  truncated. Success falls with reasoning length: 96% for 64–127 reasoning tokens, 74% for 192–255, 44% for
  256–383, 18% for 384–511 (the bulk), 14–16% beyond.
- **Compression** (the 9B rewrites without thinking, the 9B judges sufficiency with the rewrite as its thoughts, 4
  samples): 1,733 successes over 256 reasoning tokens, 95% get a sufficient rewrite, median 429 → 60 tokens (ratio
  0.14); 36 minutes. The rewrites are short and generic ("the inequality involves non-negative reals …, `nlinarith`
  is the appropriate tactic"), and the check passes easily: 73% of check samples succeed with the rewrite prefilled.
- **Data** (`reasoning/teacher_9b`): **2,134 teacher examples** in train from 1,194 states (1,017 sampled with at most
  256 reasoning tokens, 1,117 compressed; completion median 113 tokens), plus 2,134 non-thinking replay examples from
  the student's own SFT data; 67 + 500 validation examples. The examples use the plain thinking prompt (the teacher's
  brevity instruction is dropped).

## Step 2: student training (19:19–19:38 UTC)

The 4B SFT adapter continued on `teacher_9b`: 2 epochs, 36 steps, 2.3M tokens, 10 minutes, learning rate 1e-4.
Validation loss 0.459 → 0.329; non-thinking greedy exact match on replay prompts 27.3% → 26.2% (the non-thinking mode
is kept). A first attempt (18:54) finished training but ran out of memory in the final greedy-generation check before
saving the adapter; the rerun uses generation batches of 16.

## Step 3a: per-step evaluation (19:50–20:09 UTC)

The bootstrap evaluation's 512 traced validation states (statements held out from all training; none is in either
SFT data set), k = 8, temperature 0.8, the reasoning pipeline's success metric. The 2B rows are the bootstrap
evaluation's runs on the same states (`results/phase5_eval_bootstrap_*`); the 2B's thinking ran at cap 512.

| Policy | Mode | Cap | Success / sample | Any success @8 | Truncated | Tokens / sample | Tokens / success |
|---|---|---|---|---|---|---|---|
| 4B student | thinking | 1024 | 37.8% | 59.0% | 1.0% | 202 | 535 |
| 4B student | thinking | 512 (simulated) | 37.3% | 58.2% | | | 511 |
| 4B student | thinking | 256 (simulated) | 32.7% | 56.1% | | | 484 |
| 4B student | no thinking | 256 | 43.9% | 63.5% | 1.4% | 33 | 75 |
| 2B bootstrap | thinking | 512 | 42.1% | 62.9% | 14.9% | 234 | 557 |
| 2B bootstrap | no thinking | 256 | **46.0%** | **64.6%** | 2.9% | 41 | 90 |
| 2B SFT v2 | no thinking | 256 | 45.6% | 64.8% | 2.8% | 40 | 89 |

- The student's thinking reaches 86% of its non-thinking success per sample (the 2B bootstrap: 92%).
- **The student learned to be brief**: median 94 reasoning tokens (p90 314), 99% of samples finish within 1024 tokens;
  the untrained 4B left 66% unfinished at 4096 (`results/phase5_model_size_probe/`).
- **The student is below the 2B in both modes** on these states (thinking 37.8% vs 42.1%, non-thinking 43.9% vs
  46.0%). Its SFT base is weaker than the 2B's: 20M tokens against SFT v2's 60M. The 4B SFT adapter alone was not
  evaluated, so how much of the gap is the smaller SFT and how much the teacher data cannot be separated here; that
  evaluation (non-thinking, 10 minutes) is the missing control.
- Fewer of the student's thinking steps reach a reference state (150 of 4,096 samples, against 617 without
  thinking): thinking makes it close goals or take its own route more often, and "progress" steps (20%) do not count.

## Reasoning quality (read by hand)

30 random successful and 15 failed (ran in Lean) samples of the student's thinking run, fixed seed, judged with the
size probe's rubric: **correct**, **minor slip** (an error the step does not depend on), **wrong** (a false claim the
step relies on, or a false conclusion), **irrelevant** (no mathematical content about the step). Traces:
`trace_sample_student.jsonl`, numbered 1–45. The 2B and 9B rows are the size probe's (128 of the same 512 states, cap
4096 for those runs).

| Model | Traces | Correct | Minor slip | Wrong | Irrelevant |
|---|---|---|---|---|---|
| 4B student, successful step | 30 | 25 (83%) | 3 (10%) | 2 (7%) | 0 |
| 4B student, failed step | 15 | 9 (60%) | 2 (13%) | 1 (7%) | 3 (20%) |
| 2B bootstrap, successful step | 30 | 18 (60%) | 3 (10%) | 8 (27%) | 1 (3%) |
| 2B bootstrap, failed step | 15 | 2 (13%) | 2 (13%) | 10 (67%) | 1 (7%) |
| 9B teacher (unbounded), successful step | 30 | 30 (100%) | 0 | 0 | 0 |
| 9B teacher (unbounded), failed step | 15 | 6 (40%) | 3 (20%) | 2 (13%) | 4 (27%) |

13 of the student's 30 successes only close a goal a hypothesis states (or `False` is a hypothesis). **On the 17
non-trivial successful steps the student's reasoning is correct in 12, has a minor slip in 3 and is wrong in 2; the 2B
bootstrap's was correct in 6 of 17 and wrong in 8.** The student writes in the compressed rewrites' style: a few
sentences naming the structure and the tactic ("the goal is equivalent to the non-negativity of (x² − y²)², which
`nlinarith` can deduce"). Its two wrong successes confabulate in the 2B's manner — a counterexample (x = 3, y = −2)
that violates the hypothesis x² + y² = 7, and "2007 ≡ 2005 (mod 17)" for a product whose factor 2006 = 17 · 118 is the
reason — and its failed steps mostly carry correct mathematics (the parity contradiction, the arithmetic series, the
substitution x = 1, y = z = 0) and fail on Lean; three are generic "`field_simp` clears denominators" notes.

Judgments: 1 W, 2 C, 3 C, 4 C, 5 C, 6 M, 7 M, 8 W, 9–29 C, 30 M | 31 M, 32 C, 33 C, 34 C, 35 C, 36 M, 37 C, 38 C,
39 C, 40 I, 41 C, 42 C, 43 W, 44 I, 45 I.

## Step 3b: equal-token search on miniF2F-valid (20:13–20:54 UTC)

The thinking arm passed the gate (≥ 80% of the non-thinking success per sample), so both student arms ran with the
protocol of `results/phase5_search/`: 96k generated tokens per theorem, up to 1,000 expansions, 900 s, A* f = h +
0.25·depth without the policy prior, value v0 (merged), the 7-tactic sweep; per GPU the merged student (0.62 of the
memory) and a value v0 instance (0.30). Full report: `search/README.md`.

| Arm | Solved | Mean expansions | Mean generated tokens | Tokens / solve | Lean s / theorem | Unsolved: wall clock / tokens / frontier |
|---|---|---|---|---|---|---|
| 2B bootstrap, thinking, n = 8, cap 512 | 152 (62.3%) | 12.8 | 31,184 | 50,059 | 49 | 5 / 61 / 26 |
| 2B bootstrap, no thinking, n = 16 | **159 (65.2%)** | 41.6 | 12,363 | 18,973 | 214 | 79 / 0 / 6 |
| 4B student, thinking, n = 8, cap 512 | 147 (60.2%) | 8.4 | 15,321 | 25,430 | 34 | 66 / 0 / 31 |
| 4B student, no thinking, n = 16 | 156 (63.9%) | 22.0 | 7,792 | 12,188 | 147 | 86 / 0 / 2 |

- **The student's thinking costs a quarter fewer tokens per expansion than the 2B's** (~1,800 against ~2,400) and is
  better within few tokens (solved within 1k / 2k / 5k tokens: 33 / 96 / 128 against 7 / 58 / 109) and on the first
  expansion (101 against 80), but it ends lower (147 against 152). **Its budget is the wall clock, not tokens**: the
  4B generates 1,900 tokens/s on GPU 0 (the 2B thinking arm 5,000) with ~80 running sequences in its smaller KV
  cache, so 66 theorems stop at 900 s with 15k of their 96k tokens spent.
- Without thinking the student is within noise of the 2B (156 against 159; 5 new, 8 lost) at 64% of the 2B's tokens
  per theorem and 69% of its Lean time, again wall-clock-bound (86 of 88 unsolved stop at 900 s).
- Thinking still loses to not thinking at equal tokens, and by more for the student (147 against 156) than for the
  2B (152 against 159).

## Answer

The teacher pipeline works: the 9B's bounded reasoning, compressed by the 9B, gives 2,134 examples from 3,072 states,
and the 4B student trained on them reasons briefly (median 94 tokens) and much more soundly than the 2B bootstrap
policy (non-trivial successful steps correct 12 / 17 against 6 / 17). It is not a better policy: per step it is below
the 2B in both modes on the validation states, and in the search its thinking arm solves 147 against the 2B's best
159 (and the student's own 156 without thinking), limited by the 4B's slower generation on the 3090s before the token
budget binds. Better reasoning has not bought more solved theorems at this scale; the loop's recommendation (no
thinking, n = 16) stands. Open: the 4B SFT adapter without teacher data as a control, and whether a 2B student of the
same teacher data (same cost as the current policy) keeps the soundness gain.
