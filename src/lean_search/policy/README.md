# Policy

The language-model policy: an async vLLM client (`client.py`), the chat format shared by every model, the search and
SFT data (`prompts.py`), and the search expander (`expander.py`, configured by `config.py`).

## Prompt format

One chat format for every model. A system message, optionally four fixed few-shot turns (steps of traced train-split
Lean Workbook proofs, never miniF2F), then the user turn with the pretty-printed goals (separated by blank lines) in
a ```lean block and an optional lemma list. Without thinking the assistant turn is prefilled with "```lean\n" and
generation stops at "```", so the generated text is the tactic block itself. Rendered for Qwen3.5-2B, zero-shot,
with the target completion appended:

````text
<|im_start|>system
You are a Lean 4 and Mathlib expert. Given the current proof state, write the next tactic or tactics that make progress on it. Reply with a single ```lean code block that contains only tactics.<|im_end|>
<|im_start|>user
Proof state:
```lean
x : ℝ
h₀ : 3 * x + 2 = 11
⊢ x = 3
```<|im_end|>
<|im_start|>assistant
<think>

</think>

```lean
linarith
```<|im_end|>
````

Everything up to and including the "```lean\n" after the empty think block is the prompt (`render_prompt`);
`linarith\n```<|im_end|>` is the completion (`render_completion`). Qwen2.5-Math has no think block, and our system
message replaces its default one. The few-shot prompt is 435 tokens on Qwen3.5-2B (97 zero-shot) and shares its
prefix across states, so vLLM's prefix cache serves all but the goals.

With lemmas (for retrieval, Phase 4) the user turn continues with `\n\nLemmas that may help:\n```lean\n<one per
line>\n```` after the proof state.

Thinking (`thinking=True`) renders the same messages with `enable_thinking=True` and no prefill: the model thinks,
closes `</think>` and writes the fenced block, which `parse_sample` reads from the first fence after `</think>`.
Generation then has no stop string (fences appear inside thoughts) and costs about ten times the tokens.

## API

| Call | Purpose |
|---|---|
| `render_prompt(tokenizer, goals, lemmas=(), *, few_shot=False, thinking=False) -> str` | the exact prompt text, ending with the prefill |
| `render_completion(tactic_block) -> str` | SFT target after the prompt: block, closing fence, `<|im_end|>` |
| `prompt_messages(goals, lemmas=(), *, few_shot=False) -> list[ChatMessage]`, `assistant_message(block)` | the same as chat messages, for chat-format SFT data |
| `parse_sample(sample, *, thinking, forbidden_tokens) -> str \| ParseFailure` | one sample's normalized block (dedented, trailing spaces and a leading bare `by` line removed), or `TRUNCATED`, `NO_BLOCK`, `EMPTY`, `FORBIDDEN` |
| `parse_samples(samples, *, thinking, forbidden_tokens) -> ParsedSamples` | distinct blocks, most likely first; duplicates merge, keep the best log-probability and sum their tokens |
| `PolicyExpander.expand(node, context)` | one request with n samples per expansion; yields the distinct candidates as one batch |
| `open_policy_expander(config, forbidden_steps)` | async context manager: loads the chat template, reads `max_model_len` from the server, opens one client per server URL |

`render_prompt(...) + render_completion(block) + "\n"` equals the tokenizer's chat template applied to the full
conversation for all five candidate models (`tests/policy/test_policy_live.py`), so SFT on these pairs trains exactly
the format the search samples.

## Expander accounting

Requests go round-robin over `policy.server_urls`. A prompt that leaves fewer than 32 tokens of context is skipped
(`prompts_too_long`). The first candidate of a request carries the prompt tokens and the tokens of failed samples, so
the search's per-theorem token accounting stays exact as long as one candidate survives; requests whose samples all
fail are counted in `PolicyStatistics.unattributed_generated_tokens`. `run_search.py` writes the statistics to
`policy.json`.
