# Does a larger model reason better? Qwen3.5-4B vs the 2B bootstrap policy

Zero-shot thinking on the bootstrap evaluation's unseen states (traced validation steps of Goedel SFT v2 and STP,
statements held out from all training), k=8, temperature 0.8, cap 4096 generated tokens, the reasoning pipeline's
success metric (the whole block applies and closes the goals or reaches a state of the reference proof). One RTX 3090
per model, 2026-10-13 10:49–11:29 UTC, wall time capped at 40 minutes per model: the 4B finished 128 of the 512 states
(two 64-state chunks, ~15 minutes each), the 2B all 512. Everything below compares the **128 states both ran**.
Per-run statistics: `runs/`. **Qwen3.5-9B was not run**: it is not in the node's Hugging Face cache, and downloading
~19 GB needs the owner's permission (config ready: `experiments/configs/reasoning/phase5_size_qwen3.5-9b.toml`).

| Model | Success / sample | Any success @8 | Truncated at 4096 | Format failures | Tokens / sample | Tokens / success |
|---|---|---|---|---|---|---|
| 2B bootstrap (SFT v2 + short-reasoning round) | **47.0%** | **66.4%** | 3.8% | 0.0% | 451 | **960** |
| Qwen3.5-4B (post-trained, no fine-tuning) | 24.2% | 35.2% | 65.5% | 0.0% | 3,105 | 12,819 |

Simulated smaller caps (same samples): 4B 10.5% / 14.7% / 18.5% per sample at 512 / 1024 / 2048 tokens (any success
27.3% / 29.7% / 32.8%), 2B 44.4% / 45.9% / 46.7%.

**Reasoning length.** Reasoning tokens of the samples that finished (closed `</think>` and wrote a block), percentiles
10 / 25 / 50 / 75 / 90 / max: 2B 45 / 82 / 131 / 202 / 386 / 3,860 (96% finish); 4B 204 / 365 / 582 / 1,719 / 3,134 /
4,064, and only 34.5% finish within 4,096 tokens. The untrained 4B reasons at arbitrary length: it re-reads the proof
state, re-derives the same conclusion several times ("Wait, …", "Let me double check …") and on hard states never
stops. **When it does finish, its steps are good**: 70% of its finished samples succeed (96% for 0–255 reasoning
tokens, 61% for 256–511, 51% for 512–1,023, 76% for 1,024–2,047, 83% for 2,048–4,095), against 49% for the 2B
(53% / 31% / 26% / 32% / 19%). Neither model leaks the answer format any more; the 4B's blocks fail in Lean mostly
on Lean itself (`import` lines, whole `theorem` declarations, Lean 3 `begin … end` inside the tactic block).

## Reasoning quality (read by hand)

Per model 30 random samples whose step succeeded and 15 whose step ran in Lean and failed (truncated samples have no
step), from the 128 common states, fixed seed; every trace was read in full and judged: **correct** (mathematically
correct and relevant to the step), **minor slip** (a small error that does not affect the step), **wrong** (a false
claim or derivation the step relies on, or a false conclusion), **irrelevant** (no mathematical content about the
step). The traces are in `trace_sample.jsonl` (in this order, numbered 1–45 per model); judgments below.

| Model | Traces | Correct | Minor slip | Wrong | Irrelevant |
|---|---|---|---|---|---|
| 2B, successful step | 30 | 18 (60%) | 3 (10%) | 8 (27%) | 1 (3%) |
| 2B, failed step | 15 | 2 (13%) | 2 (13%) | 10 (67%) | 1 (7%) |
| 4B, successful step | 30 | 29 (97%) | 1 (3%) | 0 | 0 |
| 4B, failed step | 15 | 9 (60%) | 0 | 3 (20%) | 3 (20%) |

The successful samples are dominated by easy states: 13 of the 2B's 30 and 20 of the 4B's 30 only close a goal that a
hypothesis already states. **On non-trivial successful steps the 2B's reasoning is correct in 6 of 17 and wrong in 8
of 17; the 4B's is correct in 9 of 10.** The 2B's wrong traces are short, confident "key insight" paragraphs (the
style its compressed training targets taught it) whose algebra is false while the step it writes — usually an
`nlinarith`, `field_simp` or `positivity` step it has seen in SFT — works anyway: it pattern-matches the step and
confabulates a justification. The 4B reasons soundly but slowly; its failed steps mostly carry correct mathematics
(solving a quadratic for the witness, the arithmetic-progression shift, the case split for an identity) and fail on
Lean syntax, and its three wrong traces are residue arguments mod 9 and a set it first shows to be infinite and then
claims to be {1, 64}.

Judgments (trace number: label). 2B: 1 C, 2 C, 3 C, 4 W, 5 C, 6 W, 7 W, 8 W, 9 C, 10 I, 11 C, 12 C, 13 C, 14 W, 15 C,
16 W, 17 C, 18 C, 19 C, 20 W, 21 M, 22 C, 23 C, 24 M, 25 C, 26 C, 27 W, 28 M, 29 C, 30 C | 31 W, 32 C, 33 W, 34 W,
35 I, 36 M, 37 W, 38 W, 39 W, 40 W, 41 W, 42 M, 43 W, 44 C, 45 W. 4B: 1–12 C, 13 M, 14–30 C | 31 I, 32 C, 33 C, 34 C,
35 C, 36 C, 37 I, 38 W, 39 C, 40 C, 41 C, 42 W, 43 W, 44 I, 45 C.

### Representative traces

**2B, successful step, wrong reasoning** (trace 14; step `nlinarith [sq_nonneg (a - b), …]`, goal
a² + b² + c² + ab + bc ≥ 1/2 given a + b + c = 1):

> Substituting the expanded form of the square, we get a²+b²+c² + ab + bc + (ab+bc) ≥ 1/2. Since ab+bc = 1 −
> (a²+b²+c²), the inequality reduces to … 1 ≥ 1/2, a trivial truth.

(ab + bc = 1 − (a² + b² + c²) is false; the inequality needs the square-sum argument the step's hints encode.)

**2B, successful step, correct reasoning** (trace 17; step `rcases h₀ with … <;> simp [h₀, Int.ModEq, …]`):

> Case 2: m ≡ 2 mod 5 → m^5 - m ≡ 2^5 - 2 = 32 - 2 = 30 ≡ 0 mod 5. Case 3: … 243 - 3 = 240 ≡ 0 mod 5. …
> Thus, in all cases, m^5 - m ≡ 0 mod 5.

**4B, failed step, correct reasoning** (trace 40; goal ∃ n k, … (n(n+1)/2 − k)/(n − 1) = 35 + 7/17 ∧ k = 7; step
`use 69 7`, which Lean rejected):

> 17n² - 1187n + 966 = 0 … √1343161 = 1159. So n = (1187 ± 1159) / 34 … n = 69! Let me verify:
> 69 * 70 / 2 - 7 = 2415 - 7 = 2408; (35 + 7/17) * 68 = 602/17 * 68 = 602 * 4 = 2408. Yes!

(after trying n = 17, 18, 20, 16, 21 by hand first.)

**4B, successful step, correct but unbounded reasoning** (trace 7, 2,473 tokens; the goal equals hypothesis `h_main`):

> So `exact h_main` closes the goal. … Wait, is it possible `h_main` is not defined but I should check if it's the
> goal? No, standard formatting puts the goal after `⊢`. Okay, I'm confident. Wait, looking at the provided proof
> state again. It lists `h_main` as a hypothesis. …

(it re-confirms the same one-line conclusion over and over.)

## Answer

The 4B reasons more soundly than the 2B (its non-trivial reasoning is almost always correct; the 2B's is wrong about
half the time and pattern-matches the step), but untrained it does not stop: two thirds of its samples are still
thinking at 4,096 tokens, so per sample it succeeds half as often as the 2B and costs 13 times the tokens per success.
For the search, the 4B as it is would be far behind; its finished steps (70% successful) suggest it is a better source
of correct reasoning traces than the 2B if its thoughts can be cut short — e.g. as the rewriter/teacher for the
compression step, or after the same short-reasoning bootstrap.
