# Phase 5: short-reasoning bootstrap, round 1

On-policy, teacher-free: the SFT v2 policy thinks on traced train states it never saw in SFT, Lean keeps the
successful steps, the base model compresses long successful thoughts, a compression is kept only if the policy,
given it as its thoughts, still writes a successful step, and the SFT v2 adapter is trained further on 50% short
reasoning and 50% non-thinking replay. Two RTX 3090s, 2026-10-12 21:59 – 2026-10-13 00:34 UTC.
Per-step details: `phase5_bootstrap_r1/` (sampling statistics, `shortening_2b.md` with example rewrites),
`phase5_bootstrap_r1_nothinking/`, `phase5_data_bootstrap_r1/`, `phase5_sft_bootstrap_r1/`, `phase5_eval_bootstrap_*/`.

## States

Traced train states whose goals are not SFT v2 prompts: 174,696 (57,988 proofs), almost all in two sources:
Goedel SFT v2 (101,222 states, traced after the snapshot SFT v2 was built from) and STP (72,532, left out by the SFT
data budget). The other sources' ~940 unseen states are mostly those whose reference step SFT dropped as too long
and are not used. Round 1: 8,000 states, 4,000 per source, at most 2 per proof. Evaluation: 512 traced
*validation* states of the same two sources (statements held out from all training), 256 per source.

## Sampling and yield

8k states × 8 thinking samples (SFT v2 adapter, cap 1024, temperature 0.8): 16.2% of the samples succeed, 34.6% of
the states have a success; 56.7% of the samples run past 1024 tokens, 10.5% never close `</think>`, and 12.5%
(7,975 samples) wrote the block without its opening fence (recovered; 31.8% of those succeed). By source: Goedel
SFT v2 26.0% / 44.1% of states, STP 6.5% / 25.0%. Success falls with reasoning length: 57–59% for 32–191
tokens, 39% for 256–383, 21% for 512–767, 18% for 768–1023. The SFT v2 policy without thinking (4k of the states,
k=4) succeeds in 42.3% of its samples and on 55.1% of the states.

## Compression

Successes with more than 256 reasoning tokens (among the first three of a state): 1,816 targets, two rewrites each
by Qwen3.5-2B without thinking ("at most 150 tokens; the key insight and why this step; never restate the goal; no
code"). 3,632 rewrites: 363 truncated, 414 with a code block, 297 over 200 tokens, 14 copying the step, 65
restating the goal; 2,479 checked, 2,233 sufficient (the policy, given the rewrite as its thoughts, writes a
successful step in at least one of 4 samples; 68.7% of all check samples succeed). **Pass rate 78.8% of the
targets**; the shortest sufficient rewrite has 95 tokens on average against 518 originally (**median ratio 0.19**).
The 2B rewrites were good enough, so the 4B rewriter was not tried. Rewrites that failed the check typically argue
the mathematics without pointing at the step (a counterexample for `norm_num [Set.Icc] at h`, the units of ℤ/8ℤ for
`decide`).

Data: 4,272 short-reasoning examples from 2,456 states (3,152 sampled with at most 256 reasoning tokens, 1,120
compressed), above the 2k threshold, so rationalization was not run. Train: 4,165 reasoning + 4,165 non-thinking
replay examples (2.2M tokens); 107 reasoning examples of held-out proofs and 500 replay examples for validation.

## Training

The SFT v2 adapter continued for 2 epochs (68 steps, learning rate 1e-4, packing and compiled layers, both GPUs):
validation loss 0.367 → 0.332; greedy exact match of the non-thinking replay validation 26.6% → 26.2% (the
non-thinking mode is kept).

## Evaluation on unseen states

512 traced validation states, k=8, temperature 0.8. Cap 256 is simulated by cutting the cap-512 samples.

| Policy | Mode | Success / sample | Any success @8 | Tokens / sample | Tokens / success | Truncated | No `</think>` |
|---|---|---|---|---|---|---|---|
| SFT v2 | no thinking | 45.6% | 64.8% | 40 | 89 | 2.8% | – |
| SFT v2 | thinking, cap 256 | 12.7% | 26.0% | 219 | 1,728 | – | – |
| SFT v2 | thinking, cap 512 | 16.3% | 32.6% | 400 | 2,450 | 65.8% | 7.8% |
| bootstrap | no thinking | 46.0% | 64.6% | 41 | 90 | 2.9% | – |
| bootstrap | thinking, cap 256 | 36.9% | 59.2% | 178 | 482 | – | – |
| bootstrap | thinking, cap 512 | 42.1% | 62.9% | 234 | 557 | 14.9% | 0.2% |

By source, bootstrap thinking at cap 512: Goedel SFT v2 46.9% per sample / 58.6% of states, STP 37.3% / 67.2%
(SFT v2 thinking: 27.4% / 46.9% and 5.3% / 18.4%). The bootstrap adapter's thoughts are short (median reasoning
under 128 tokens among the samples that finish; success 88% for 1–31 tokens, 81% for 32–63, 49% for 64–127, 33–39% above).

One round of training on its own short successful thoughts makes thinking 2.6 times as accurate per sample (42.1%
against 16.3%) at 59% of the tokens, and cuts its tokens per success 4.4-fold (2,450 → 557). The non-thinking mode is
unchanged. Thinking now costs 5.4 (cap 256) to 6.2 (cap 512) times the tokens per success of non-thinking, under the
10× stopping rule, though per sample it is still slightly less accurate than not thinking (42% against 46%) and finds
a success on as many states (63% against 65%).
