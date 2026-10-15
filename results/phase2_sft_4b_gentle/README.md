# Phase 2: gentle Qwen3.5-4B SFT (Lean steps plus general math)

The phase2_sft_4b recipe (LoRA rank 64 on all language-model linear layers, learning rate 2e-4, one epoch, packed with
compiled layers, DDP on both RTX 3090s) on the same 20.0M tokens of Lean steps (`4b`) plus 4.5M tokens (18%) of
general math worked solutions in the visible non-thinking format (`math_v1`: MATH train and NuminaMath-CoT
school-level sources, decontaminated against MATH-500 and miniF2F; `results/phase2_sft_data/math_v1.md`). The goal
is to keep the visible reasoning that the plain Lean SFT costs (MATH-500 forced pass@1 87.2% base, 84.4% old SFT).
Config `experiments/configs/training/phase2_sft_4b_gentle.toml`; training report in `training.md`.

**Adapter: `/workspace/checkpoints/phase2_sft_4b_gentle/adapter`** (serve on the raw `Qwen/Qwen3.5-4B`; not merged).

377 steps, 24.5M tokens in 103 minutes (3,964 tokens/s), peak 17.8 GiB per GPU. On the first 1,000 Lean validation
steps of `4b`, compared with the plain 4B SFT on the same steps:

| Adapter | Validation loss | Teacher-forced exact match | Greedy exact match (128) |
|---|---|---|---|
| 4B SFT (`phase2_sft_4b`, Lean only) | 0.2184 | 27.2% | 28.9% |
| Gentle 4B SFT (Lean + 18% math) | 0.2208 | 26.3% | 28.9% |

The math mix costs the Lean step prediction almost nothing (+0.002 loss, −0.9 points teacher-forced exact match).
The MATH-500 retention check of this adapter (visible mode, forced answers) runs from
`experiments/phase2_sft_4b_gentle_retention.sh` after the reasoning agent's visible-reasoning series finishes.

## MATH-500 retention: collapse, and its cause

Visible non-thinking mode, forced answers (`results/reasoning_retention/nothinking/summary.md`):

| Model | Forced pass@1 | Mean tokens | Median tokens |
|---|---|---|---|
| Qwen3.5-4B base | 87.2% | 1,435 | 860 |
| 4B SFT (Lean only) | 84.4% | 1,219 | 657 |
| Round-2 student | 83.2% | 1,091 | – |
| **Gentle 4B SFT** (Lean + 18% math) | **47.0%** | **358** | **166** |
| Visible student (from the gentle SFT) | 52.0% | 277 | 157 |

The cause is the math data itself, not the template and not the Lean steps:

- **The targets are terse reference solutions.** `math_v1`'s MATH-train solutions have a median of 162 tokens; 27% are
  under 100 tokens, many of them one-liners ("Multiply them together to get $\boxed{1155}$"). NuminaMath-CoT has a
  median of 294. The base model's own solutions to the same kind of problem have a median of 860 tokens (758 when
  correct).
- **The model copied that length exactly.** The gentle SFT's median output is 166 tokens, the same as the MATH-train
  targets. It now writes reference-solution-style answers without the step-by-step working and checks that made the
  base accurate. All of the loss is on harder problems: level 1 holds, levels 4–5 drop from 77–83% to about 30%.
- **It learned this on exactly the evaluation's own prompt.** The math examples used the same chat template,
  instruction, empty think block and end of turn as the evaluation. There is no system prompt in either. Every target
  had a boxed answer, and the closing `<|im_end|>` was placed correctly. Nothing was truncated: solutions over 1,024
  tokens were dropped, not cut.
- **The Lean steps are not the cause.** The Lean-only 4B SFT trains on the same 20M tokens of 25–35-token
  completions and keeps 84.4% with 1,219-token answers. Its Lean prompts (a system message and a proof state) are
  far enough from a math word problem that their shortness does not carry over.

Example (intermediate_algebra/1014, reference 50). The gentle SFT writes 232 tokens with a wrong AM-GM split:
"$a^4 + b^8 = \frac{a^4}{2} + \frac{a^4}{2} + b^8 \ge 3\sqrt[3]{\cdots} = 3 \cdot 4 = 12$ … the minimum value is
$\boxed{12}$". The base writes 960 tokens, solves for the equality case, and checks it: "Check the sum:
$a^4 + b^8 = (\sqrt{5})^4 + 25 = 25 + 25 = 50$".

**The visible student's thinking mode (0%) is the same collapse plus a scoring artifact.** With the prompt opening
`<think>`, the student never writes `</think>` (0 of 800 samples). It writes its short visible solution inside the
think block and ends the turn (`We can write $99^2+99+1=(99+1)^2-99=100^2-99=\boxed{9901}$.`). The evaluation only
reads answers after `</think>`, hence 0%. Scored by the last box anywhere, it is 53%, the same as its visible mode.
Its thinking mode no longer reasons; it answers directly. Whether that comes from the gentle SFT or from the
student's visible-only training is untested: a thinking-mode run of the gentle adapter would separate the two (about
10 minutes).

**Proposed fix: math targets from the model's own reasoning (self-distillation), not reference solutions.**
- Sample the base Qwen3.5-4B in visible non-thinking mode on the same decontaminated problems.
- Keep answer-checked correct solutions (about 80%), so the targets keep the base's length and step-by-step style.
- Cost: about 8,000 problems × one sample × about 1,000 tokens ≈ 8M generated tokens. That is about 45 minutes on
  both GPUs and yields about 6M tokens of math (about 23% of a 26M mix).
- Retraining is about 1.8 h with DDP; the retention check is about 15 minutes.
- In total about 3 h of GPU time, plus retraining the visible student on top.
- The student's data should also keep some thinking-mode examples so that mode survives.
- Cheaper fallback: drop the math mix and build the visible student on the Lean-only 4B SFT (84.4%). This costs no
  extra GPU time.
