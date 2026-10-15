# Visible reasoning: a short explanation before the Lean block, thinking off

The base Qwen3.5-4B is strongest at mathematics when it writes a visible worked solution without a think block
(MATH-500 87.2% forced against 80.9% with thinking; `results/reasoning_retention/`). This series makes the Lean policy
reason the same way: thinking off, a brief explanation of the key idea, then the `lean` block. 2026-10-14/15, both RTX
3090s, Lean work pinned and niced via `deployment/background.sh` with at most 16 REPLs. Run summaries in `runs/`, the
search report (`experiments/phase3_astar_report.py`) in `search/`.

## Visible mode

`policy.visible_reasoning = true` (`src/lean_search/policy/`): `enable_thinking = false`, no `lean` prefill, and the
system prompt "… Given the current proof state, briefly explain the key idea (a few sentences), then give the next
tactic or tactics that make progress on it in a single ```lean code block that contains only tactics." The step is the
first block after the explanation (a sample that closed its block and ran on is still parsed). A training example's
completion is the explanation, the block and the end of turn, with loss on all of it. Budget forcing: a sample cut off
before any block gets "\n\n```lean\n" appended and up to 256 more tokens, stopping at the fence; forced samples are
recorded but never selected for training. The mode runs through the reasoning pipeline (sampling, records, selection,
the sufficiency check, data, training) and the search expander.

## Step 1: probe (18:10–18:36 UTC)

The bootstrap evaluation's 512 traced validation states (none in any SFT data), k = 8, temperature 0.8, cap 1024,
the reasoning pipeline's success metric. The round-2 student's thinking and non-thinking rows are its earlier
evaluations on the same states.

| Model | Mode | Success / sample | Any success @8 | Tokens / success | Median explanation | Failures |
|---|---|---|---|---|---|---|
| Qwen3.5-4B (base) | visible | 25.7% | 47.3% | 1,096 | 119 | 41% Lean errors, 20% partial blocks |
| 4B Lean SFT adapter (phase2_sft_4b) | visible | 6.9% | 30.3% | 1,203 | 14 | 37% empty, 20% no block |
| Round-2 student (phase5_sft_student_4b_light) | visible | 37.5% | **64.5%** | **408** | 104 | |
| Round-2 student | thinking, cap 1024 | 36.0% | 59.8% | 925 | 237 | |
| Round-2 student | no thinking | **43.4%** | 61.7% | 78 | | |

- The plain Lean SFT loses the mode: it writes the block without its opening fence (its SFT format prefills the
  fence), so most samples do not parse. The base explains well but writes long multi-tactic blocks that fail.
- The round-2 student, trained on 9B thinking traces, does better visibly than with its think block (37.5% against
  36.0% per sample, 64.5% against 59.8% of states, at 44% of the tokens per success) and solves more states than
  without reasoning (64.5% against 61.7%), though fewer of its samples succeed (37.5% against 43.4%).
- Forcing barely triggers at cap 1024 (1.5% of the base's samples, under 1% otherwise).

## Step 2: the 9B teacher in visible mode (18:40–21:20 UTC)

6,143 SFT-unseen traced train states of Goedel SFT v2 and STP (none of rounds 1–2's or the 2B bootstrap's), k = 8,
cap 1024 (`phase5_visible_teacher_9b.toml`), 140 minutes on both GPUs (~2,300 generated tokens/s per GPU).

| Teacher | Success / sample | Any success @8 | Tokens / sample | Tokens / success |
|---|---|---|---|---|
| 9B, visible (this run) | 26.1% (25.8% unforced) | 43.4% (42.7% unforced) | 378 | 1,448 |
| 9B, thinking with the brevity instruction (round 1, other train states) | 23.5% | 40.6% | 621 | ~2,640 |

- The 9B succeeds as often visibly as in bounded thinking, at 60% of the tokens. Its failures are Lean failures of
  long multi-tactic blocks (31% errors, 24% partial). 6.8% of samples were forced; 4.9% of those succeeded.
- Successful explanations are short: p10 / 25 / 50 / 75 / 90 = 49 / 65 / 95 / 148 / 245 tokens; only 5.3% exceed 350.
- **Light condensation** (the round-2 rules: the 9B condenses to about half, rewrites under 100 tokens or outside
  30–80% of the original rejected, sufficiency judged by the 9B): 312 targets, 210 passing (67.3%); the shortest
  sufficient rewrites go from a median 491 to 186 tokens (p10–p90 134–289; ratio 0.37). 168 of the 624 rewrites
  fell under the floor and 83 were insufficient.
- Yield: 4,527 explanations as sampled and 150 condensed, from 2,585 states.
- Two of its explanations: "Since `n` is a natural number, `n + 3` is at least `3`, which is strictly greater than
  `0` … `linarith` is the most direct." (step `linarith`); for a goal that equals `h_main` it first sketches
  rationalizing the denominators, then "since the hypothesis `h_main` already asserts the equality … completed
  immediately by using that hypothesis" (step `exact h_main`). A condensed one: for 4c > (8/9)c² + 9/2 the original
  wandered ("Wait, let's just multiply by 18 …"); the rewrite keeps the derivation (multiply by 18,
  0 > 16c² − 72c + 81 = (4c − 9)², impossible) and the step `nlinarith [sq_nonneg (4 * c - 9)]`.

## Step 4: self-generated visible reasoning (23:20–00:58 UTC)

The gentle-SFT 4B (phase2_sft_4b_gentle: the 4B Lean SFT recipe plus 18% math worked solutions in the visible format)
in visible mode on 10,235 further unseen train states, k = 8, cap 1024 (`phase5_visible_self_4b.toml`), 95 minutes.

| Policy | Success / sample | Any success @8 | Tokens / sample | Tokens / success | Median explanation |
|---|---|---|---|---|---|
| Gentle-SFT 4B, visible | 22.6% | 43.7% | 129 | 570 | 39 |

Its explanations are short and often formulaic or missing: 16% of samples are empty and 12% have no block (the Lean
SFT's fence habit, weaker than the plain SFT adapter's 57%). Typical successful ones: "The goal has already been proven
by `h₁₀`. The proof is complete." (`exact h₁₀`), and a garbled one whose "explanation" is itself a tactic
(`Have h₃ : y ^ 2 = 19 / 8 := by nlinarith`) before the block `nlinarith`.

## Step 5: data and the student (00:59–02:10 UTC)

`reasoning/visible_student` (`phase5_data_visible_student.toml`): per state at most two successes with at most 350
explanation tokens (as sampled, or through a sufficient condensation), forced samples never; 70% visible reasoning,
15% Lean non-thinking replay (`4b`, the gentle SFT's Lean data) and 15% general math worked solutions (`math_v1`, its
math data).

| Part | Examples | Explanation or completion tokens, median / p90 |
|---|---|---|
| Visible reasoning from the 9B teacher | 4,542 (4,399 as sampled, 143 condensed) | explanation 93 / 198 |
| Visible reasoning from the gentle 4B itself | 7,185 | explanation 33 / 99 |
| Lean non-thinking replay | 2,513 | completion 15 / 59 |
| Math worked solutions | 2,513 | |
| Validation (reasoning + replay) | 365 + 500 | |

6,771 of 16,378 states contribute (204 held out). The gentle-SFT adapter continued on these 16,753 examples (5.1M
tokens): 2 epochs, 158 steps, 44 minutes, learning rate 1e-4 (`phase5_sft_visible_student.toml`). Validation loss
0.498 → 0.370; non-thinking greedy exact match on replay prompts 23.8% → 23.0% (the non-thinking mode is kept).

## Step 6a: per-step evaluation

The merged visible student on the same 512 validation states, k = 8, temperature 0.8 (visible at cap 1024 with
forcing, non-thinking at cap 256), 04:51–05:11 UTC (`experiments/phase5_visible_eval.sh`; the series chain's first
attempt failed because it never chose the evaluation runs' states).

| Policy | Mode | Success / sample | Any success @8 | Tokens / sample | Tokens / success | Median explanation |
|---|---|---|---|---|---|---|
| **Visible student** | visible, cap 1024 | 44.6% | 63.3% | 190 | 427 | 87 |
| **Visible student** | no thinking | **47.4%** | **64.8%** | 34 | 71 | |
| Round-2 student | visible | 37.5% | 64.5% | 153 | 408 | 104 |
| Round-2 student | thinking, cap 1024 | 36.0% | 59.8% | 333 | 925 | 237 |
| Round-2 student | no thinking | 43.4% | 61.7% | 34 | 78 | |
| 2B bootstrap | no thinking | 46.0% | 64.6% | 41 | 90 | |

- The visible student is the best 4B per step in both modes: +7.1 points visibly and +4.0 without thinking over
  the round-2 student; its non-thinking mode now matches the 2B bootstrap's (47.4% against 46.0% per sample).
- Visible reasoning still trails no reasoning per sample (44.6% against 47.4%) and per state (63.3% against 64.8%),
  at 6 times the tokens per success; the search below shows the opposite per expansion.
- Forcing triggered on 0.7% of the visible samples (10% of them succeeded).

## Step 6b: equal-expansion search on miniF2F-valid (02:23–04:28 UTC)

The merged visible student with value v0 (merged), n = 16, 64 expansions per theorem as the budget, no token cap, a
2 h safety cap per theorem, budget forcing on, the protocol of `results/phase5_teacher_student/` (A* without the
policy prior, the 7-tactic sweep; per GPU the student at 0.62 of the memory and a value v0 instance at 0.30). The
round-2 student's arms are from that report.

| Arm | Solved | Mean expansions | Mean generated tokens | Wall s / theorem | Lean s / theorem | Unsolved: 64 expansions / 2 h cap / frontier | Arm wall time |
|---|---|---|---|---|---|---|---|
| **Visible student, visible, n = 16** | **171 (70.1%)** | 19.8 | 93,685 | 1,820 | 343 | 61 / 7 / 5 | 124 min |
| Round-2 student, thinking, n = 16, forcing | 160 (65.6%) | 16.3 | 113,546 | 2,480 | 125 | 2 / 69 / 13 | 128 min |
| Round-2 student, no thinking, n = 16 | 154 (63.1%) | 24.8 | 12,201 | 509 | 234 | 86 / 0 / 4 | 99 min |
| Round-2 student, no thinking, n = 16, 96k tokens | 162 (66.4%) | 66.9 | 28,010 | 1,503 | 1,028 | 54 (tokens) / 23 / 5 | 129 min |

Solved within k expansions:

| Expansions ≤ | 1 | 2 | 4 | 8 | 16 | 32 | 64 |
|---|---|---|---|---|---|---|---|
| **Visible student** | **124** | **141** | **153** | **158** | **163** | **169** | **171** |
| Round-2 student, thinking | 120 | 130 | 143 | 145 | 150 | 157 | 160 |
| Round-2 student, no thinking | 86 | 114 | 129 | 139 | 147 | 152 | 154 |

- **The visible student is ahead at every expansion budget**: 171 against 160 (thinking) and 154 (no thinking) at
  64, and already 158 after 8 expansions. Unlike the thinking arm it reached its 64 expansions on most failures (61
  of 73; 7 hit the 2 h cap), so the comparison with the non-thinking arm is a true equal-expansion one.
- **It is also the best run per generated token beyond ~5k tokens** (solved within 5k / 10k / 20k / 50k tokens:
  122 / 142 / 153 / 165, against 79 / 120 / 133 / 145 for thinking and 146 / 153 / 156 / 158 for the 96k-token
  non-thinking run), but not below ~5k, where a non-thinking expansion is far cheaper.
- New and lost theorems: against thinking 13 new, 2 lost; against no thinking 19 new, 2 lost; against the 162-run 11
  new (`imo_1961_p1`, `amc12a_2003_p24`, `amc12a_2016_p2`, `algebra_amgm_sumasqdivbsqgeqsumbdiva`,
  `mathd_numbertheory_156`, `numbertheory_prmdvsneqnsqmodpeq0`, `mathd_algebra_149`, `_185`, `_323`, `_422`, `_509`)
  and 2 lost (`amc12a_2016_p3`, `induction_seq_mul2pnp1`).
- Cost: 93.7k generated tokens and 1,820 s of wall time per theorem (3.6 times the non-thinking arm's wall time, 0.73
  times the thinking arm's), and 343 Lean-seconds (it tries more distinct steps than the thinking arm).
- **Forcing**: 2,068 of 77,152 samples (2.7%) were cut off before their block; 2,055 forced blocks parsed (99%).
  1,610 distinct forced steps were tried, 15.9% gave a new node (unforced: 17.0%), and one proof uses a forced step.

### What the student explains at proof steps

The search does not keep the explanation behind a step, so the proof-path states of four theorems that only the
visible student proved were resampled (k = 8, visible, cap 1024; `search_step_traces.jsonl`). None of the 17 states' resamples reproduced the
exact proof step (the search's steps are single draws of n = 16), but they show what the student says there:

- **amc12a_2016_p2** (10^x · 100^(2x) = 1000^5, after rewriting 100 and 1000 as powers of 10): "simplify the
  left-hand side using exponent rules: (10²)^(2x) = 10^(4x), so the left-hand side becomes 10^x · 10^(4x) = 10^(5x).
  The right-hand side simplifies to 10^15. Thus … 5x = 15 and therefore x = 3", then a block rewriting both sides and
  closing with `linarith`. Correct, and the search's own steps follow the same plan.
- **mathd_numbertheory_156** (gcd(7 + n, 1 + 2n) ≤ 13), last state: "We are given hypothesis `h₂` which states that
  this GCD divides 13, and `h₃` which states it is less than or equal to 13. Since the goal is exactly `h₃` …",
  block `exact h₃` (the proof used `simp [mul_comm] at h₃ ⊢; exact h₃`). At the state before, it names the right idea
  (the gcd divides any linear combination, so a difference of the arguments bounds it) with a step that does not
  type-check.
- **amc12a_2016_p2**, a later state with exponentials: "h₀ gives (10^x)^5 = 10^14 … so 5x = 14 … x = 2.8. However,
  the goal is x = 3, which suggests the hypotheses might be inconsistent" — it misreads the literal 1000000000000000
  (10^15) as 10^14; long numerals remain a source of wrong arithmetic in the explanations.

## Answer

Visible reasoning is the first reasoning mode that pays off in the search. The visible student, trained on 70%
visible explanations (9B teacher and its own) with Lean and math replay from the gentle SFT, solves **171 of 244**
miniF2F-valid theorems at 64 expansions, against 160 for the round-2 student's thinking and 154 for its non-thinking
mode, and 162 for that non-thinking mode run to 96k tokens. It is ahead at every expansion budget and, beyond ~5k
generated tokens per theorem, at every token budget too. Per step it is the strongest 4B in both modes (44.6% visible,
47.4% without thinking), though per sample its non-thinking mode is still better than its visible one.

Open: (1) the visible student's own non-thinking search at 64 expansions is missing, and its non-thinking mode is 4
points stronger per step than the round-2 student's, so part of 171 against 154 may come from the better base rather
than from the explanations; that arm (~1.5 h) separates the two. (2) Its self-generated explanations are short and
partly formulaic (median 33 tokens; 61% of the reasoning examples); a 9B-only variant would show what they add.
(3) The search should log each step's explanation, as the loop's thinking expander does, for training and for reading.
