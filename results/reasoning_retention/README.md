# Reasoning retention: did Lean training damage general mathematical reasoning?

**Short answer: no broad damage.** With thinking on, every Lean-trained model scores at least as well as its base.
The reasoning-trained ones (the 2B bootstrap and the 4B student) score much better, mostly because they stop
thinking before the 4,096-token cap. With thinking off there is a small but consistent loss of 2.5–8 points pass@1,
concentrated on levels 4–5. Read by hand, the reasoning quality of the traces is about the same as base. The 4B
student is cleaner on hard problems; the 2B models make somewhat more substantive slips on level 4–5 problems.

## Setup

- **Problems:** 200 MATH-500 problems (`HuggingFaceH4/MATH-500` via hf-mirror), stratified by level and subject with
  a fixed seed (levels 1–5: 18 / 36 / 42 / 51 / 53).
- **Prompt and sampling:** the problem followed by "Please reason step by step, and put your final answer within
  \boxed{}.", k = 4 samples at temperature 0.6 / top-p 0.95, at most 4,096 generated tokens.
- **Modes:** thinking on, and thinking off (the chat template's empty think block).
- **Scoring:** the answer is the last `\boxed{}` after the thinking block, compared by value
  (`src/lean_search/evaluation/math_answers.py`). Every reference solution matches its own answer, and no shuffled
  pair of answers matches.
- **Forced answers (budget forcing):** a sample cut off at the cap gets its thinking closed and
  `The final answer is $\boxed{`, then 64 tokens to finish the box. This separates reasoning from stopping.
- **Models:** all served as LoRA adapters on their base.
  - 2B: Qwen3.5-2B base; SFT v2 (Lean tactic SFT); bootstrap r1 (SFT v2 plus training on its own Lean reasoning).
  - 4B: Qwen3.5-4B base; 4B SFT (Lean tactic SFT); 4B student (4B SFT continued on a 9B teacher's Lean reasoning).
- **Code:** `experiments/reasoning_retention.py`; configs `experiments/configs/evaluation/reasoning_retention*.toml`.
- **Discarded first run:** it used a broken instruction. In a basic TOML string `\boxed` is the escape `\b`, so the
  prompt asked for "<backspace>oxed{}", and the bootstrap model copied it verbatim. The fixed config uses a literal
  string, and the runner rejects an instruction without `\boxed{}`.

## Accuracy

| Model | Thinking pass@1 | Thinking pass@1 forced | Thinking any@4 | Thinking mean tokens | No-thinking pass@1 | No-thinking pass@1 forced | No-thinking any@4 | No-thinking mean tokens |
|---|---|---|---|---|---|---|---|---|
| Qwen3.5-2B | 9.0% | 66.6% | 22.5% | 3,934 | **64.0%** | **71.0%** | 76.5% | 1,812 |
| 2B SFT v2 | 17.0% | 67.8% | 33.0% | 3,733 | 60.6% | 64.8% | 76.5% | 1,616 |
| 2B bootstrap r1 | **47.0%** | **69.2%** | **60.0%** | 2,899 | 61.4% | 63.1% | 76.0% | 1,180 |
| Qwen3.5-4B | 22.1% | 80.9% | 38.0% | 3,683 | **83.0%** | **87.2%** | **91.5%** | 1,435 |
| 4B SFT | 25.2% | 80.1% | 42.0% | 3,553 | 80.5% | 84.4% | 88.0% | 1,219 |
| 4B student | **40.8%** | **83.4%** | **56.0%** | 3,170 | 80.4% | 83.2% | 91.0% | 1,091 |

Truncation with thinking on: 91% / 82% / 51% of samples for the three 2B models and 77% / 74% / 58% for the 4B
models. Truncation with thinking off: 28% / 25% / 13% and 15% / 13% / 10%.

Paired per-problem differences against the base model (95% bootstrap intervals over 200 problems;
`paired_differences.txt`):

| Trained − base | Thinking pass@1 | Thinking forced | No-thinking pass@1 | No-thinking forced |
|---|---|---|---|---|
| 2B SFT v2 | +8.0 [+5.0, +11.0] | +1.1 [−2.0, +4.3] | −3.4 [−6.2, −0.5] | −6.2 [−9.4, −3.1] |
| 2B bootstrap r1 | +38.0 [+32.9, +43.2] | +2.6 [−0.6, +6.0] | −2.6 [−6.2, +1.0] | −7.9 [−11.4, −4.4] |
| 4B SFT | +3.1 [+0.1, +6.4] | −0.7 [−2.9, +1.4] | −2.5 [−5.1, 0.0] | −2.9 [−5.5, −0.4] |
| 4B student | +18.6 [+14.7, +22.5] | +2.5 [+0.1, +4.8] | −2.6 [−5.4, −0.1] | −4.0 [−6.8, −1.5] |
| 4B student − 4B SFT | +15.5 [+11.9, +19.1] | +3.3 [+1.1, +5.5] | −0.1 [−2.5, +2.4] | −1.1 [−3.6, +1.3] |

By level (pass@1 with forced answers):

| Model | Thinking L1 | L2 | L3 | L4 | L5 | No-thinking L1 | L2 | L3 | L4 | L5 |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen3.5-2B | 90.3% | 84.7% | 85.1% | 46.1% | 51.4% | 91.7% | 88.9% | 89.9% | 56.4% | 50.9% |
| 2B SFT v2 | 90.3% | 86.8% | 80.4% | 48.5% | 55.7% | 95.8% | 86.8% | 81.5% | 47.5% | 42.5% |
| 2B bootstrap r1 | 95.8% | 87.5% | 86.3% | 54.9% | 48.1% | 90.3% | 80.6% | 81.0% | 49.5% | 41.0% |
| Qwen3.5-4B | 90.3% | 93.1% | 91.1% | 70.1% | 71.7% | 91.7% | 95.1% | 92.9% | 82.8% | 80.2% |
| 4B SFT | 93.1% | 93.8% | 89.9% | 67.6% | 70.8% | 94.4% | 94.4% | 91.7% | 78.9% | 73.6% |
| 4B student | 95.8% | 95.1% | 91.7% | 71.1% | 76.4% | 94.4% | 94.4% | 92.9% | 76.5% | 70.8% |

Per-level pass@1 without forcing, reasoning-length quantiles and the "no boxed answer" rates are in
`thinking/summary.md` and `nothinking/summary.md`.

Readings:

- **Thinking on, the base models mostly fail to stop.** They usually reach the answer early and then re-verify
  until the cap (91% truncated for the 2B base). With the answer forced at the cap, every model reaches 67–69% (2B)
  or 80–83% (4B).
- **Reasoning training removes much of the over-thinking.** The bootstrap and the student finish far more often
  (+38 and +19 points pass@1). With answers forced at the cap they are slightly ahead of base: +2.6 (not
  significant) and +2.5 points.
- **The Lean tactic SFT alone neither hurts nor helps with thinking on:** +1.1 for 2B and −0.7 for 4B once answers
  are forced.
- **Thinking off, all four trained models lose 2.5–8 points**, mostly at levels 4–5. The 4B student is no worse
  than the 4B SFT (−0.1, −1.1). The cost therefore comes from the Lean SFT stage, not from the reasoning training.
- **Which mode is better at this cap depends on the model.** Thinking off beats forced thinking for both base
  models and the 4B SFT. Forced thinking is higher for the 2B SFT v2 (67.8% vs 64.8%) and the 2B bootstrap (69.2% vs
  63.1%). The 4B student is level (83.4% vs 83.2%).

## Hand-judged reasoning quality (thinking on)

For 20 fixed problems (4 per level), the first sample of each model was read in full and judged as sound,
minor slip, wrong or incoherent. The judgment was on the reasoning itself, not on whether it finished. Traces are in
`thinking/judged/`.

| Model | Correct | Minor slip | Wrong | Incoherent | Finished | Truncated after the answer | Truncated before it |
|---|---|---|---|---|---|---|---|
| Qwen3.5-2B | 11 | 4 | 1 | 4 | 2 | 14 | 4 |
| 2B SFT v2 | 9 | 5 | 5 | 1 | 4 | 12 | 4 |
| 2B bootstrap r1 | 12 | 3 | 5 | 0 | 12 | 3 | 5 |
| Qwen3.5-4B | 16 | 3 | 0 | 1 | 4 | 14 | 2 |
| 4B SFT | 16 | 2 | 2 | 0 | 7 | 11 | 2 |
| 4B student | 15 | 2 | 0 | 3 | 11 | 7 | 2 |

- **2B:**
  - Correct or minor slip on 15 / 14 / 15 of 20 traces for base, SFT v2 and bootstrap.
  - SFT v2 keeps base's verbose "Here's a thinking process" template. It adds two cases where a "double check"
    invented a false contradiction and talked itself out of a correct answer.
  - The bootstrap is short and decisive, finishing 12 traces against base's 2. All five of its wrong traces are
    level 3–5 problems, mostly ones where base was on a sound track.
- **4B:**
  - Base and SFT are both sound on 16 of 20. The SFT's only two substantive errors are on level-5 inequalities.
  - The student is the cleanest on hard problems (731, 183 and 966 all correct) and finishes 11 traces.
  - The student's new failure mode is verbatim repetition after it has the answer, on 2 traces.
- **No model shows Lean syntax, tactics or code in its natural-language solutions.**

Clearest base-vs-trained pairs:

1. **2B, precalculus/441, base vs SFT v2.** Both found 30°. Base confirms it: "$196 - (\mathbf{a}\cdot\mathbf{b})^2
   = 49$. $(\mathbf{a}\cdot\mathbf{b})^2 = 147$." SFT v2's "verification" breaks it: "We need $\mathbf{a}\cdot
   \mathbf{b} = 0$ … This is a contradiction. Therefore, $\theta = 30^\circ$ is impossible." It confuses orthogonality
   with $\mathbf{a}\cdot\mathbf{b}=0$ and rejects its own correct answer.
2. **2B, intermediate algebra/966, base vs bootstrap.** Base recovers to the right equality case: "$x^4 = 4 \implies
   x = \sqrt{2}$ … Value is 16." The bootstrap's Lagrange route goes wrong: "$2 = \frac{\lambda^3}{128} \implies
   \lambda^3 = 256 \implies \lambda = 4\sqrt{2}$". The algebra errors lead it to "minimum" values near 10.65, below
   the true 16.
3. **4B, intermediate algebra/966, base vs SFT.** Base: "apply AM-GM to these 4 terms: $x^4, 2y^2, 2y^2, 4z^4$ …
   So $S \ge 16$." SFT: "the product $a^2 \cdot b \cdot c^2 = (abc)^2$ … So the lower bound is $12\sqrt[3]{4}$."
   That is a false identity, giving a bound that is not the minimum.
4. **4B, algebra/2046, base vs student.** Both derive $x^3 + 3x - 6$. Base boxes it and stops. The student repeats
   "I'll ensure the box is at the end. I'll ensure the box contains the final answer. …" verbatim until the cap.

These are one sample per problem on 20 problems: they show patterns, not rates.

## Control: the 4B SFT alone on the reasoning agent's 512 Lean states

This answers whether the 4B SFT was already weaker, or whether reasoning training hurt the Lean policy. Setup:
zero-shot, thinking off, k = 8 at temperature 0.8, 256 tokens; the same 512 held-out traced states and success
definition as `phase5_eval_student_4b_nothinking` (`control_sft_4b_nothinking/README.md`).

| Policy (thinking off) | Success | Any success / state | Fully valid | Closed |
|---|---|---|---|---|
| 4B SFT alone (control) | 45.1% | 64.1% | 78.5% | 28.4% |
| 4B student | 43.9% | 63.5% | 78.9% | 28.9% |
| 2B SFT v2 (`phase5_eval_bootstrap_sft_v2_nothinking`) | 45.6% | 64.8% | 76.8% | 28.8% |
| 2B bootstrap r1 (`phase5_eval_bootstrap_r1_nothinking`) | 46.0% | 64.6% | 79.4% | 28.9% |

The 4B SFT is not weaker than the 2B SFT on these states, and the student's non-thinking Lean policy is within
about a point of the 4B SFT it started from. The student's lower success with thinking on (37.8% in
`phase5_eval_student_4b_thinking`) therefore comes from the thinking mode, not from a weaker starting point or from
damage to the non-thinking policy.
