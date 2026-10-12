# Phase 5 pilot: how the policy thinks before reasoning training

512 traced train-split states (7 sources × ~73, at most 2 per proof; 463 of them are SFT v2 prompts), k=8 samples
each at temperature 0.8, zero-shot, on one RTX 3090 (vLLM, `Qwen/Qwen3.5-2B` with the SFT v2 adapter or none).
Thinking arms are capped at 1024 generated tokens (reasoning and block; truncation is a failure), the non-thinking arm
at 256. Every distinct block ran on its rebuilt state in Lean; a success applies whole and closes the goals or reaches
a state of the reference proof. Per-arm details (outcomes, success against reasoning length, by source, by SFT
exposure): `phase5_pilot_<arm>/README.md`, produced by `experiments/phase5_reasoning_data.py`.

| Arm | Success / sample | Any success @8 | Truncated | Format failures | Mean generated tokens | Tokens / success |
|---|---|---|---|---|---|---|
| (d) SFT v2, no thinking | 48.2% | 74.8% | 1.4% | 0.0% | 32 | 67 |
| (a) SFT v2, thinking | 12.5% | 41.7% | 51.5% | 27.9% | 693 | 5,543 |
| (b) SFT v2, thinking + brevity instruction | 10.0% | 41.3% | 49.8% | 32.1% | 677 | 6,749 |
| (c) base, thinking | 3.7% | 13.9% | 72.9% | 0.1% | 929 | 25,047 |
| (c') base, thinking + brevity instruction | 4.1% | 16.6% | 78.9% | 0.0% | 941 | 22,886 |

Format failures are samples without a usable block other than truncation (`empty` + `no_block`). For SFT v2 they are
SFT-format leakage: 17% close `</think>` and then write the tactic and a closing fence without the opening
```` ```lean ```` (the SFT prompt prefilled that fence), 11% never close `</think>` and write a bare SFT-style
tactic.

Reasoning length of the samples that closed `</think>` (tokens, p25 / p50 / p75 / p90): SFT v2 143 / 296 / 515 / 714,
with brevity 115 / 278 / 507 / 728; base 450 / 556 / 676 / 791, with brevity 432 / 532 / 693 / 820. The brevity
instruction does not shorten the thoughts of either model.

Success of SFT v2 thinking (a) against reasoning length, among samples that did not truncate: 34.6% (32–63 tokens),
34.1% (64–127), 23.6% (128–191), 33.3% (192–255), 29.4% (256–383), 26.3% (384–511), 17.7% (512–767), 24.8%
(768–1023); 1–31 tokens: 13.7% (mostly format failures). Longer thinking does not succeed more often.

Effect of the cap, simulated on arm (a) by cutting every sample at the cap:

| Cap | Success / sample | Any success @8 | Tokens / sample | Tokens / success |
|---|---|---|---|---|
| 256 | 6.3% | 20.4% | 222 | 3,507 |
| 384 | 8.4% | 27.0% | 316 | 3,768 |
| 512 | 10.0% | 32.5% | 402 | 4,041 |
| 768 | 11.5% | 38.0% | 555 | 4,819 |
| 1024 | 12.5% | 41.7% | 693 | 5,543 |

By SFT exposure: on the 48 states whose goals are not SFT v2 prompts (mostly STP), thinking succeeds in 0.8% of
samples and non-thinking in 22.4%; on the 463 seen states 13.7% and 50.9%. By source, thinking is weakest on
STP (5.1%) and Numina Kimina (4.3%), strongest on DeepSeek-Prover (19.6%) and Goedel SFT v2 (19.1%).

Rejection selection (at most 2 successes per state, at least 16 reasoning tokens, shortest first): arm (a) yields
317 examples from 207 states (median reasoning 252 tokens), (b) 312 from 205, (c) 105 from 71, (c') 125 from 84.

Cost: sampling at 5,600 (SFT v2) to 6,500 (base) generated tokens/s on one GPU, 8 thinking samples/s; Lean 1.5 s per
thinking state and 7.7 s per non-thinking state (more distinct blocks, heavy `nlinarith` attempts), 16 processes.
Pilot run 2026-10-12 08:08–09:00 UTC, git 01c60a8.

## Choice for round 1

SFT v2 adapter, plain thinking prompt (no brevity instruction), cap 512, k=8, temperature 0.8: 80% of the successes
of the 1024 cap at 58% of the tokens, and the shorter selected reasoning is what the search will pay for. The base
model is three times worse per sample and almost never finishes within 512 tokens.
