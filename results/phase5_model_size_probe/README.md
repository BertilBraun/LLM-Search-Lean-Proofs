# Does a larger model reason better? Qwen3.5-4B and 9B vs the 2B bootstrap policy

Zero-shot thinking on the bootstrap evaluation's unseen states (traced validation steps of Goedel SFT v2 and STP,
statements held out from all training), k=8, temperature 0.8, cap 4096 generated tokens, the reasoning pipeline's
success metric (the whole block applies and closes the goals or reaches a state of the reference proof). One RTX 3090
per model and run, 2026-10-13. The 4B and 2B ran 10:49–11:29 UTC with wall time capped at 40 minutes per model: the
4B finished 128 of the 512 states (two 64-state chunks, ~15 minutes each), the 2B all 512. Qwen3.5-9B ran 12:52–13:12
UTC in two shards of 64 states (states 0–63 on GPU 0, 64–127 on GPU 1, ~18 minutes each) on exactly those 128 states.
**Everything below compares these 128 common states.** Per-run statistics: `runs/` (the 9B as `phase5_size_qwen3.5-9b`
and `_b`).

| Model | Success / sample | Any success @8 | Truncated | Format failures | Tokens / sample | Tokens / success |
|---|---|---|---|---|---|---|
| 2B bootstrap (SFT v2 + short-reasoning round) | **47.0%** | **66.4%** | 3.8% | 0.0% | 451 | **960** |
| Qwen3.5-4B (post-trained, no fine-tuning) | 24.2% | 35.2% | 65.5% | 0.0% | 3,105 | 12,819 |
| Qwen3.5-9B (post-trained, no fine-tuning) | 27.8% | 45.3% | 26.1% | 0.0% | 1,567 | 5,629 |
| 4B, bounded: cap 1024 + brevity instruction | 17.1% | 35.2% | 72.0% | 0.0% | 879 | 5,142 |
| 9B, bounded: cap 1024 + brevity instruction | 28.7% | 44.5% | 23.1% | 0.0% | 596 | 2,077 |

Simulated smaller caps (same samples, no instruction), per sample at 512 / 1024 / 2048 tokens: 4B 10.5% / 14.7% /
18.5% (any success 27.3% / 29.7% / 32.8%), 9B 21.3% / 25.1% / 25.9% (33.6% / 44.5% / 45.3%), 2B 44.4% / 45.9% / 46.7%.

**Reasoning length.** Reasoning tokens of the samples that finished (closed `</think>` and wrote a block), percentiles
10 / 25 / 50 / 75 / 90 / max: 2B 45 / 82 / 131 / 202 / 386 / 3,860 (96% finish); 4B 204 / 365 / 582 / 1,719 / 3,134 /
4,064 (34.5% finish); 9B 215 / 405 / 481 / 618 / 917 / 3,798 (74% finish). The untrained 4B reasons at arbitrary
length: it re-reads the proof state, re-derives the same conclusion several times ("Wait, …", "Let me double check …")
and on hard states never stops. The 9B mostly concludes after a few hundred tokens. **When the 4B finishes, its steps
are good**: 70% of its finished samples succeed (96% for 0–255 reasoning tokens, 61% for 256–511, 51% for 512–1,023,
76% for 1,024–2,047, 83% for 2,048–4,095), against 49% for the 2B (53% / 31% / 26% / 32% / 19%) and 38% for the 9B
(99% / 37% / 14% / 18% / 83%). The 4B's figure is selected: it finishes mostly the easy states, while the 9B also
answers on hard ones and fails there. Neither model leaks the answer format.

**Where the 9B's steps fail.** Of its 731 blocks, 38% close the goals, 33% are Lean errors, 14% make progress without
reaching a reference state (not a success under this metric; the 2B has 22% such steps), and 13.5% apply only in part.
It writes long blocks more often than the others (34% have more than three lines, against 23% for the 2B and 19% for
the 4B) and these rarely succeed (7%, 2B 29%); 2.7% of its blocks (4B 5.1%) are whole declarations with `import`,
`theorem` or `example` lines. Its failures are mostly about Lean, not the mathematics.

## Bounded thinking

The same 128 states at a 1024-token cap with the system prompt addition "Think briefly (a few sentences) about which
tactic to use; do not restate the goal." (`experiments/configs/reasoning/phase5_size_qwen3.5-{4b,9b}_bounded.toml`).
**The 9B keeps its success when its reasoning is cut short**: 28.7% per sample and 44.5% of states (unbounded at 4096:
27.8% / 45.3%), with 23% truncated, at 38% of the tokens per sample and 2.7 times fewer tokens per success (2,077
against 5,629). Its finished reasoning shrinks only a little (median 429 against 481 tokens): the instruction mostly
removes the long tail. **The 4B does not**: with the instruction 72% of its samples still run into the 1024 cap, and
its 17.1% per sample is barely above the 14.7% that the uninstructed run had within 1024 tokens. The 4B does not follow
a brevity instruction; the 9B does.

## Reasoning quality (read by hand)

Per model 30 random samples whose step succeeded and 15 whose step ran in Lean and failed (truncated samples have no
step), from the 128 common states, fixed seed; every trace was read in full and judged: **correct** (mathematically
correct and relevant to the step), **minor slip** (a small error that does not affect the step), **wrong** (a false
claim or derivation the step relies on, or a false conclusion), **irrelevant** (no mathematical content about the
step). The traces are in `trace_sample.jsonl` (2B and 4B) and `trace_sample_9b.jsonl` (the 9B's unbounded run, both
shards), in this order, numbered 1–45 per model; judgments below.

| Model | Traces | Correct | Minor slip | Wrong | Irrelevant |
|---|---|---|---|---|---|
| 2B, successful step | 30 | 18 (60%) | 3 (10%) | 8 (27%) | 1 (3%) |
| 2B, failed step | 15 | 2 (13%) | 2 (13%) | 10 (67%) | 1 (7%) |
| 4B, successful step | 30 | 29 (97%) | 1 (3%) | 0 | 0 |
| 4B, failed step | 15 | 9 (60%) | 0 | 3 (20%) | 3 (20%) |
| 9B, successful step | 30 | 30 (100%) | 0 | 0 | 0 |
| 9B, failed step | 15 | 6 (40%) | 3 (20%) | 2 (13%) | 4 (27%) |

The successful samples are dominated by easy states: 13 of the 2B's 30, 20 of the 4B's 30 and 20 of the 9B's 30 only
close a goal that a hypothesis already states. **On non-trivial successful steps the 2B's reasoning is correct in 6 of
17 and wrong in 8 of 17; the 4B's is correct in 9 of 10, the 9B's in 10 of 10.** The 2B's wrong traces are short,
confident "key insight" paragraphs (the style its compressed training targets taught it) whose algebra is false while
the step it writes — usually an `nlinarith`, `field_simp` or `positivity` step it has seen in SFT — works anyway: it
pattern-matches the step and confabulates a justification. The 4B reasons soundly but slowly; its failed steps mostly
carry correct mathematics (solving a quadratic for the witness, the arithmetic-progression shift, the case split for an
identity) and fail on Lean syntax, and its three wrong traces are residue arguments mod 9 and a set it first shows to
be infinite and then claims to be {1, 64}. The 9B is like the 4B, but shorter: its failed steps with correct reasoning
fail on Lean (`split` for a conjunction, an `import` and `example` header, a parity argument written as a 40-line
`cases` block), its four irrelevant traces list generic tactics ("field_simp, then ring_nf, then nlinarith") for hard
inequalities without any mathematics, and its two wrong traces are a derivative of `log` and a witness that
contradicts its own quadratic.

Judgments (trace number: label). 2B: 1 C, 2 C, 3 C, 4 W, 5 C, 6 W, 7 W, 8 W, 9 C, 10 I, 11 C, 12 C, 13 C, 14 W, 15 C,
16 W, 17 C, 18 C, 19 C, 20 W, 21 M, 22 C, 23 C, 24 M, 25 C, 26 C, 27 W, 28 M, 29 C, 30 C | 31 W, 32 C, 33 W, 34 W,
35 I, 36 M, 37 W, 38 W, 39 W, 40 W, 41 W, 42 M, 43 W, 44 C, 45 W. 4B: 1–12 C, 13 M, 14–30 C | 31 I, 32 C, 33 C, 34 C,
35 C, 36 C, 37 I, 38 W, 39 C, 40 C, 41 C, 42 W, 43 W, 44 I, 45 C. 9B: 1–30 C | 31 I, 32 C, 33 M, 34 C, 35 W, 36 C,
37 W, 38 C, 39 C, 40 I, 41 M, 42 M, 43 I, 44 I, 45 C.

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

**9B, failed step, wrong reasoning** (trace 37; the same state; step `use 66, 7`, which makes progress but leaves a
false goal):

> 17n² - 1187n + 966 = 0. Using the quadratic formula, I find two potential solutions for `n`. One solution is
> `n = 66` … The arithmetic checks out: (2211 - 7) / 65 = 33.707..., which matches the original equation's structure.

(the root is 69, and 33.7 is not 35 + 7/17; the 9B derives the same quadratic as the 4B but does not solve it.)

**9B, failed step, correct reasoning** (trace 36; goal 6 ^ 2003 ≡ 6 [ZMOD 49]; the block starts with an `import` and an
`example` header, so it does not apply):

> φ(49) = 42 … 6^42 ≡ 1 (mod 49). So 6^2003 = 6^(42·47+29) ≡ 6^29 … We need 6^29 ≡ 6 (mod 49), or equivalently
> 6^28 ≡ 1 (mod 49).

**4B, successful step, correct but unbounded reasoning** (trace 7, 2,473 tokens; the goal equals hypothesis `h_main`):

> So `exact h_main` closes the goal. … Wait, is it possible `h_main` is not defined but I should check if it's the
> goal? No, standard formatting puts the goal after `⊢`. Okay, I'm confident. Wait, looking at the provided proof
> state again. It lists `h_main` as a hypothesis. …

(it re-confirms the same one-line conclusion over and over.)

## Serving the 9B

bf16 on one RTX 3090 (24 GB) with `MAX_MODEL_LEN=5120 GPU_MEMORY_UTILIZATION=0.95` and `--max-num-seqs 64`: the
weights take 16.8 GiB, leaving 2.8 GiB of KV cache (56k tokens). vLLM's default of 256 sequences fails at start-up
because the hybrid layers' state cache has only 176 blocks. Throughput: 512 samples at cap 4096 in ~18 minutes per GPU
(4B: ~15 minutes), 1024 bounded samples in ~11 minutes.

## Answer

The larger models reason more soundly than the 2B: their non-trivial successful reasoning is correct in 9 of 10 (4B)
and 10 of 10 (9B) traces, while the 2B's is wrong about half the time and pattern-matches the step. Untrained, the 4B
does not stop thinking, even when told to be brief, so it is far behind. **The 9B stops**: three quarters of its
samples finish within 4,096 tokens, and with a 1024-token cap plus the brevity instruction it keeps its success
(28.7% per sample, 44.5% of states) at 2,077 tokens per success. It still trails the 2B bootstrap policy per sample
(47.0%), per state (66.4%) and per token (960 per success), mostly because its steps fail on Lean (long multi-tactic
blocks, declarations) rather than on the mathematics. That is the failure SFT on traced steps removed for the 2B. A bounded
9B is therefore the better source of correct reasoning, as the compression rewriter and teacher, or as a policy after
the same SFT and short-reasoning bootstrap, at about twice the 4B's serving cost and one model per 3090.
