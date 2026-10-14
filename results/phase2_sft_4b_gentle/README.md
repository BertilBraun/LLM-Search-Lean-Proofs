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
