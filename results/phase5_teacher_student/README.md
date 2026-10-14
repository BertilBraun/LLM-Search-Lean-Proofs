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

# Round 2: lightly compressed teacher reasoning (2026-10-14, 23:57–04:01 UTC)

The same 9B teacher successes, re-compressed lightly; the student retrained from the 4B SFT adapter, evaluated on the
same 512 states and searched with the token budget as the only stop. Configs: `phase5_shortening_9b_light.toml`,
`phase5_data_teacher_9b_light.toml`, `phase5_sft_student_4b_light.toml`, `phase5_eval_student_4b_light_*.toml`,
`phase5_search_student_4b_light_*.toml`; the search report in `search_r2/`.

## Light compression (23:58–00:23 UTC)

Successes over 350 reasoning tokens (the first 3 per state in selection order) are condensed by the 9B without
thinking: asked for half the original's tokens, to remove restatements of the goal, dead ends and repetition, and to
keep every mathematical step, equation and the reason for the tactic. Rewrites under 100 tokens or outside 30–80% of
the original are rejected, plus the usual defects; the 9B checks sufficiency as in round 1. (The run summary's "asked
for at most 150 tokens" is the config's unused fixed target; each request asked for half its original.)

| | Round 1 (`9b`) | Round 2 (`9b_light`) |
|---|---|---|
| Targets | 1,733 (over 256 tokens) | 1,311 (over 350 tokens) |
| Targets with a sufficient rewrite | 1,646 (95.0%) | 822 (62.7%) |
| Original tokens of the targets, p10 / 25 / 50 / 75 / 90 | 292 / 354 / 422 / 474 / 554 | 381 / 410 / 442 / 495 / 576 |
| Shortest sufficient rewrite, p10 / 25 / 50 / 75 / 90 | 35 / 44 / 57 / 72 / 89 | 133 / 148 / 172 / 204 / 242 |
| Rewrite / original, p10 / 50 / 90 | 0.09 / 0.14 / 0.21 | 0.31 / 0.37 / 0.51 |
| Rejected rewrites (2 per target) | 63 defective, 357 insufficient | 1,227 defective (772 too short, 188 restating the goal, 172 code blocks), 175 insufficient |
| Train reasoning examples (sampled + compressed) | 2,134 (1,017 + 1,117) | 1,983 (1,327 + 656) |
| Reasoning tokens of the train examples, p10 / 25 / 50 / 75 / 90 | 43 / 56 / 83 / 149 / 211 | 96 / 135 / 175 / 234 / 292 |

The 9B overshoots the request: asked for half, it wrote a median 37% of the original, and 772 of its 2,622 rewrites
fell under the 30% / 100-token floor. The pass rate drops from 95% to 63% for that reason, not because rewrites became
insufficient (175 of 1,395 checked). Four examples (`runs/phase5_teacher_9b/shortening_9b_light.md` has more):

- **`constructor` for −1/2 ≤ x/(x²+1) ≤ 1/2** (original: paragraphs restating the hypotheses and doing the algebra
  twice). Rewrite: "the first subgoal −1/2 ≤ x/(x²+1) is equivalent to 0 ≤ (x+1)² after cross-multiplying by the
  positive denominator x²+1 …; similarly the second is equivalent to 0 ≤ (x−1)² …; `constructor` is chosen to handle
  the logical structure of the goal before applying algebraic simplifications."
- **(x + a).log < x.log + a** from h₁ (the log splits) and h₂ ((1 + a/x).log < a/x). Rewrite: "Given `h₁` … it
  suffices to show (1 + a/x).log < a. From `h₂`, (1 + a/x).log < a/x. Since x > 1 and a > 0, a/x < a. By
  transitivity … via `linarith`": every step of the original without its restatement of the four hypotheses.
- **`simp [Finset.sum_mul, Finset.mul_sum, mul_assoc]`** on (∑ a·(a·a))^(1/3) ≤ (∑ a·a)^(1/2). Rewrite: the
  simplification of the summands to a³ and a² and that it prepares a power-mean or Hölder argument; the original's
  exploration of both inequalities is gone.
- **Insufficient**: `have h₃ : (x − 3)(x² + 3x + 1) = 0` for the cubic x³ − 8x − 3 = 0. The rewrite kept the root
  check (3³ − 8·3 − 3 = 0), but the 9B, given it as its thoughts, wrote no working step in 4 samples.

## Training (00:26–00:46 UTC)

The 4B SFT adapter continued on `teacher_9b_light` (1,983 reasoning and 1,983 replay examples): 2 epochs, 38 steps,
2.5M tokens, 10.7 minutes. Validation loss 0.392 → 0.310; non-thinking greedy exact match on replay prompts 24.6% →
18.8% (round 1: 27.3% → 26.2%).

## Evaluation (00:50–01:08 UTC)

| Policy | Mode | Success / sample | Any success @8 | Truncated | Tokens / sample | Tokens / success | Median reasoning |
|---|---|---|---|---|---|---|---|
| Round-2 student | thinking, cap 1024 | 36.0% | 59.8% | 2.1% | 333 | 925 | 236 |
| Round-2 student | thinking, cap 512 (simulated) | 34.4% | 57.2% | | | 891 | |
| Round-2 student | no thinking | 43.4% | 61.7% | 1.7% | 34 | 78 | |
| Round-1 student | thinking, cap 1024 | 37.8% | 59.0% | 1.0% | 202 | 535 | 94 |
| Round-1 student | no thinking | 43.9% | 63.5% | 1.4% | 33 | 75 | |
| 2B bootstrap | thinking, cap 512 | 42.1% | 62.9% | 14.9% | 234 | 557 | 125 |
| 2B bootstrap | no thinking | **46.0%** | **64.6%** | 2.9% | 41 | 90 | |

The round-2 student reasons 2.5 times longer (median 236 against 94 reasoning tokens) and succeeds slightly less often
per sample (36.0% against 37.8%) at 1.7 times the tokens per success; per state it is level (59.8% against 59.0%).
Its thinking reaches 83% of its non-thinking success per sample.

## Reasoning quality (read by hand)

30 successful and 15 failed samples of the round-2 thinking run, fixed seed, the same rubric
(`trace_sample_student2.jsonl`, numbered 1–45).

| Model | Traces | Correct | Minor slip | Wrong | Irrelevant |
|---|---|---|---|---|---|
| Round-2 student, successful step | 30 | 25 (83%) | 2 (7%) | 3 (10%) | 0 |
| Round-2 student, failed step | 15 | 5 (33%) | 3 (20%) | 5 (33%) | 2 (13%) |
| Round-1 student, successful step | 30 | 25 (83%) | 3 (10%) | 2 (7%) | 0 |
| Round-1 student, failed step | 15 | 9 (60%) | 2 (13%) | 1 (7%) | 3 (20%) |

12 of the 30 successes close a goal that a hypothesis states. **On the 18 non-trivial successes the reasoning is
correct in 14, has a minor slip in 1 and is wrong in 3** (round 1: 12, 3 and 2 of 17; the 2B bootstrap: 6 correct and
8 wrong of 17). The longer traces carry more derivation, and more of it can be wrong: "(a³ + b³ + c³)/(abc) simplifies
to a² + b² + c² using abc = 1", an arithmetic check that declares "the equation is arithmetically false" for an
identity `norm_num` then proves, and an expansion that loses terms. Among the failures the wrong traces grow (5 against
1): the sum 111 + … + 999 given as 5550 (it is 4,995), `apply h` justified by a lemma `h` that does not exist,
affirming the consequent for a + b ≤ 2, and an `rpow_nat_cast` rewrite for the exponent 1/11.

Judgments: 1 C, 2 C, 3 W, 4 C, 5 C, 6 W, 7–12 C, 13 M, 14–21 C, 22 W, 23 C, 24 C, 25 M, 26–30 C | 31 M, 32 I, 33 C,
34 W, 35 C, 36 C, 37 W, 38 I, 39 C, 40 W, 41 W, 42 M, 43 W, 44 C, 45 M.

## Search: 96k tokens per theorem as the only stop (01:13–04:00 UTC)

The round-1 protocol except for the wall clock (a 2 h safety cap per theorem) and the thinking cap (1024). Report:
`search_r2/README.md`.

| Arm | Solved | Mean expansions | Mean generated tokens | Wall s / theorem | Lean s / theorem | Unsolved: token budget / wall clock / frontier | Arm wall time |
|---|---|---|---|---|---|---|---|
| 2B bootstrap, no thinking, n = 16 (900 s) | 159 | 41.6 | 12,363 | 334 | 214 | 0 / 79 / 6 | 17 min |
| Round-1 student, no thinking, n = 16 (900 s) | 156 | 22.0 | 7,792 | 363 | 147 | 0 / 86 / 2 | 23 min |
| **Round-2 student, no thinking, n = 16** | **162 (66.4%)** | 66.9 | 28,010 | 1,503 | 1,028 | 54 / 23 / 5 | 129 min |
| 2B bootstrap, thinking, n = 8, cap 512 (900 s) | 152 | 12.8 | 31,184 | 252 | 49 | 61 / 5 / 26 | 17 min |
| Round-1 student, thinking, n = 8, cap 512 (900 s) | 147 | 8.4 | 15,321 | 328 | 34 | 0 / 66 / 31 | 18 min |
| Round-2 student, thinking, n = 8, cap 1024 | 150 (61.5%) | 9.6 | 32,686 | 680 | 40 | 64 / 0 / 30 | 38 min |

- **Without the wall clock the round-2 student's non-thinking search proves 162**, 3 more than the 2B's 159 and 6
  more than its round-1 predecessor; but it takes 4.5 times the wall time and 5 times the Lean time per theorem, and
  at the 2B's budgets it is level (solved within 20k / 50k tokens: 156 / 158 against 158 / 159; within 600 s: 156
  against 156). The extra theorems come from running long, not from a better policy per token.
- **Thinking still loses at equal tokens**: 150 against 162 for the same student, 145 against 158 within 50k tokens.
  The longer round-2 reasoning makes a thinking expansion cost ~3,400 tokens (round 1: ~1,800), so it is behind round
  1 at small budgets (within 2k / 5k tokens: 50 / 106 against 96 / 128).
- Per expansion thinking is no better than not thinking (within 8 / 16 / 32 expansions: 139 / 145 / 149 against
  139 / 150 / 154).

## Answer (round 2)

Lighter compression kept more of the teacher's reasoning (median 175 against 83 tokens in the training data) and the
student's successful reasoning stays sound (14 of 18 non-trivial steps correct), but it does not make thinking pay: per
sample the student is slightly worse than in round 1, and in the search thinking stays behind not thinking at every
token budget. The round-2 student without thinking is the best policy so far when the search may run to its token
budget (162 against 159), at a much larger wall-clock and Lean cost.

# Equal-expansion test with budget forcing (2026-10-14, 08:12–11:59 UTC)

The round-2 student (merged) with value v0 on miniF2F-valid, n = 16 in both arms and 64 expansions per theorem as the
budget, with no token cap and a 2 h safety cap per theorem: (A) thinking, cap 1024, with budget forcing; (B) no
thinking. Otherwise the search protocol and serving of round 2. Configs
`experiments/configs/reasoning/phase5_expansions_student_4b_light_*.toml`; report, node-monitor windows and the policy
statistics in `expansions/`.

**Budget forcing** (`PolicyConfig.force_answer_on_truncation`, on by default in thinking mode): a sample that hits
max_tokens inside its thoughts gets them closed (`</think>`, the opened `lean` block) and one completion request per
expansion continues all such samples for up to 256 tokens, stopping at the closing fence; the result parses like any
other sample. The forcing request's tokens are charged to the expansion, and candidates and tree edges carry `forced`.

| Arm | Solved | Mean expansions | Mean generated tokens | Tokens / solve | Wall s / theorem | Lean s / theorem | Unsolved: 2 h cap / 64 expansions / frontier | Arm wall time |
|---|---|---|---|---|---|---|---|---|
| A: thinking, n = 16, cap 1024, forcing | **160 (65.6%)** | 16.3 | 113,546 | 173,158 | 2,480 | 125 | 69 / 2 / 13 | 128 min |
| B: no thinking, n = 16 | 154 (63.1%) | 24.8 | 12,201 | 19,332 | 509 | 234 | 0 / 86 / 4 | 99 min |
| Round 2, no thinking, n = 16, 96k tokens (reference) | 162 (66.4%) | 66.9 | 28,010 | 42,188 | 1,503 | 1,028 | 23 / 54 tokens / 5 | 129 min |

Solved within k expansions:

| Expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| A: thinking | **120** | **130** | **143** | **145** | **150** | **157** | **160** |
| B: no thinking | 86 | 114 | 129 | 139 | 147 | 152 | 154 |
| Reference (96k tokens) | 81 | 116 | 132 | 139 | 150 | 154 | 156 |

- **Per expansion, thinking is ahead at every budget**: 120 against 86 after one expansion, 160 against 154 after 64.
  A solves 12 theorems B does not (among them `imo_1964_p1_2`, `amc12a_2016_p3`, `amc12b_2002_p6`, five
  `mathd_algebra`) and loses 6 (`aime_1991_p1`, `imo_1984_p2`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`,
  `mathd_algebra_433`, `mathd_algebra_536`, `numbertheory_nckeqnm1ckpnm1ckm1`).
- **The comparison is not quite equal-expansion for A's unsolved theorems**: 69 of its 84 failures stopped at the 2 h
  safety cap after a mean of 16.3 expansions per theorem, not at 64. The 4B serves ~80 running sequences per GPU,
  and with 120 concurrent searches each requesting 16 thinking samples the queue stretches every expansion (2,100
  generated tokens/s on GPU 0, 98% GPU utilization, 5.5 CPU cores). A's 160 is therefore a lower bound on what 64
  thinking expansions reach.
- **Against the best non-thinking run (162 at 96k tokens, 67 expansions on average)**: A solves 5 it does not
  (`imo_1961_p1`, `mathd_algebra_149`, `_185`, `_323`, `_509`) and loses 7, with a quarter of its expansions but 4 times
  its generated tokens and 1.7 times its wall time per theorem.
- **Cost**: thinking spends 9.3 times B's generated tokens per theorem (~7,000 per expansion at n = 16) and 5 times its
  wall time, but half its Lean time (125 against 234 s), so per expansion it is GPU-bound where B is Lean-bound.

**Forcing statistics (arm A)**: of 63,472 policy samples, 2,085 (3.3%) were cut off inside their thoughts and forced;
1,811 of them (87%) yielded a usable block (the others ran past 256 tokens or wrote no block). The forcing requests
generated 140,737 tokens, 0.5% of the arm's 27.7M. 1,543 samples remained truncated after forcing, mostly samples cut
off after `</think>` inside their answer, which this forcing leaves alone. In the trees, 1,341 distinct forced steps
were tried: 21.5% gave a new node (unforced policy steps: 18.5%), 62% failed in Lean, the rest were duplicates; 2 of
the 160 proofs use a forced step. Forcing salvages a few percent of the samples at negligible cost and the salvaged
steps are as good as the others, but it changes little at a 1024-token cap where the student rarely runs out.

## Answer (equal-expansion test)

Measured per expansion, thinking helps the round-2 student: it solves more theorems at every expansion budget (160
against 154 at 64, and 120 against 86 at 1), even though most of its unsolved theorems ran out of wall-clock time
before using their 64 expansions. Measured per generated token or per wall-clock second it does not (the round-2
results above): each thinking expansion costs ~9 times the tokens of a non-thinking one on this node. Thinking is the
better policy where expansions (Lean calls and value scoring) are the scarce resource and generation is cheap, which
on two RTX 3090s with a 4B policy it is not.
