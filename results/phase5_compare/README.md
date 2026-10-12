# Phase 5: did SFT destroy the model's reasoning?

The pilot's 512 traced train-split states (463 of them are SFT v2 prompts, 48 are not), k=8 samples at temperature
0.8, zero-shot unless noted, with the pilot's success metric: the whole block applies and closes the goals or reaches
a state of the reference proof. Thinking arms can generate 4096 tokens; samples that close `</think>` and then write
the tactic without the opening fence count with their tactic (the reasoning pipeline's recovery; the search's parser
rejects them). Arm (d) is the pilot's (`results/phase5_pilot/`). Per-arm details: `phase5_compare_<arm>/README.md`.
Two RTX 3090s, 2026-10-12 13:04–13:55 UTC.

| Arm | Success / sample | Any success @8 | Truncated | Format failures | Tokens / sample | Tokens / success | Unseen states: success / any |
|---|---|---|---|---|---|---|---|
| (d) SFT v2, no thinking | 48.2% | 74.8% | 1.4% | 0.0% | 32 | 67 | 22.4% / 31.2% |
| (f) base, no thinking, zero-shot | 7.2% | 30.1% | 2.9% | 0.1% | 109 | 1,519 | 1.0% / 6.2% |
| (g) base, no thinking, few-shot | 11.4% | 35.8% | 5.5% | 0.1% | 109 | 962 | 1.3% / 6.2% |
| (e) base, thinking | 4.5% | 18.0% | 52.3% | 0.0% | 2,700 | 60,636 | 0.8% / 2.1% |
| (h) SFT v2, thinking | 20.7% | 55.0% | 34.0% | 13.4% | 1,935 | 9,352 | 3.6% / 14.6% |

Format failures: samples without a usable block other than truncation. (h) also has 889 samples (21.7%) in the
recovered format, which succeed in 24.6% of cases; without the recovery they would be failures too. Suggestion tactics
the search forbids (`exact?`, ...) are not format failures: 3.7% of (e), 10.2% of (f), 3.5% of (g).

Simulated caps (the same samples cut at the cap: success / any success @8 / tokens per success):

| Cap | (e) base, thinking | (h) SFT v2, thinking |
|---|---|---|
| 512 | 1.9% / 9.0% / 26,465 | 13.2% / 35.2% / 3,063 |
| 1024 | 3.2% / 13.5% / 28,648 | 17.1% / 45.8% / 4,089 |
| 2048 | 4.0% / 16.8% / 39,015 | 19.3% / 51.5% / 6,042 |
| 4096 | 4.5% / 18.0% / 60,636 | 20.7% / 55.0% / 9,352 |

Raising (h)'s cap from 1024 to 4096 finishes 726 more samples (17.8%), which succeed in 20.4% of cases; 34% still run
past 4096 tokens, mostly in loops (enumerations, repeated expansions).

Success against reasoning length, samples that finished (per-arm READMEs have every bucket):

| Reasoning tokens | 32–255 | 256–511 | 512–1023 | 1024–2047 | 2048–4095 |
|---|---|---|---|---|---|
| (e) base | 31% (42) | 16% (405) | 6% (915) | 9% (366) | 8% (219) |
| (h) SFT v2 | 46% (736) | 32% (514) | 28% (507) | 24% (373) | 18% (314) |

(sample counts in parentheses; the base model rarely finishes in under 384 tokens.)

## Answers

1. **Does the base model reason usefully when given enough tokens?** No. With 4096 tokens it succeeds in 4.5% of
   samples, below its own non-thinking zero-shot (7.2%) and few-shot (11.4%) prompts, at 40–60 times their tokens per
   success; half its samples are still thinking at 4096 tokens, and 36% of its samples are Lean errors (SFT v2
   thinking: 14%).
2. **Did SFT hurt thinking?** No, it helped: SFT v2 thinking beats base thinking on every measure (20.7% against 4.5%
   per sample, 55% against 18% of states, 9.4k against 61k tokens per success), also on the 48 SFT-unseen states
   (3.6% against 0.8% per sample, 14.6% against 2.1% of states; few states, so only the direction is reliable). What
   SFT did damage is the answer format in thinking mode: 13% of the samples never close `</think>` and 22% drop the
   opening fence. The recovery handles the second, and training on correctly rendered targets should fix both.

Thinking, from either model, is far behind SFT v2 without thinking: 67 tokens per success against 3,063 (SFT v2
thinking at cap 512) and 6,042 (cap 2048).

## Round 1

Because neither condition holds, round 1 keeps its plan: rejection sampling from the SFT v2 adapter with thinking,
plain prompt, cap 2048, k=8, temperature 0.8, 6k states (pilot states held out), the format recovery on, then training
that continues the SFT v2 adapter with a one-to-one non-thinking replay. At cap 2048, (h) gives 0.8–0.9 selected
examples per state; 6k states should give about 5k examples and cost about 56M generated tokens (~1.5 h on both
GPUs at the measured 10–11k tokens/s).
