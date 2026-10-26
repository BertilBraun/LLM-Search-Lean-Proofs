# Value

The value model predicts how many proof steps remain from a Lean proof state, or that the state is a dead end, and
serves as A*'s heuristic `h`. It is a LoRA adapter on the policy's base model, read in one prefill-only vLLM request.

## Bins and readout (`bins.py`)

Nine classes: remaining steps `1..7`, `8+` and `dead`. The search reads them out as
`h = Σ p_k · steps_k`, with `steps_k = k` for `1..7`, `Readout.eight_or_more_steps` (default 12) for `8+` and
`Readout.dead_steps` (default 16) for `dead`. Both values are serving-time parameters (`[value.readout]`), so the
λ/D sweep of row 4 needs no retraining. Defaults: 12 is the mean remaining steps of the `8+` states of v0's train split (12.3);
16 is the search's `max_depth`, the most steps the search can still spend below any node, so a certain dead end
costs more than every alive estimate (at most 12) while a partial `p_dead` trades off smoothly against step
estimates.

## Prompt format (`prompts.py`)

A system message asking for the remaining steps, then the policy's own user turn (`policy.prompts.user_message`:
the goals in a ```lean block), rendered with the tokenizer's chat template, thinking off. The generation prompt ends
after the empty think block, so the assistant turn's first token is the answer: one of `1`..`8` or `dead`, each a
single token in the Qwen2.5, Qwen3 and Qwen3.5 tokenizers, also right after the generation prompt
(`tests/value/test_value_prompts.py`). No text is prefilled: a prefill ending in a space would split ` dead` from its
natural tokenization. Rendered for Qwen3.5-2B:

````text
<|im_start|>system
You are a Lean 4 and Mathlib expert. Given the current proof state, estimate how many more tactic steps are needed to finish the proof. Reply with a single token: a number from 1 to 7, 8 for eight or more steps, or dead if the proof cannot be finished from this state.<|im_end|>
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

1<|im_end|>
````

## Labels (`labels.py`)

| Source | Node | Label | Weight |
|---|---|---|---|
| Traced proofs | every state before a step | exact: the proof's remaining steps (an upper bound) | 1 |
| Search trees | reaches the verified proof | exact: fewest edges to it over child and duplicate edges | 1 |
| Search trees | reaches a frontier node | at least 1 + fewest edges to a frontier node | `at_least_weight` |
| Search trees | neither (everything below expanded) | dead | `dead_weight` (0.5) |

Frontier nodes are open nodes (never or only partly expanded, or at the depth cap) and nodes with an attempt lost to
an infrastructure failure (`Failure.is_negative_label` false), whose steps were therefore not all tried. An open
node is censored at "at least 1", which carries no loss; an expanded alive node whose subtree was explored `d` edges
deep without reaching the frontier is censored at `1 + d`. Proved states get no label. States with the same
normalized goals (goal order kept) merge to the fewest exact steps, else dead, else the largest lower bound.

## Loss (`loss.py`)

On the nine bin logits `z` at the prompt's last position, `log p = log_softmax(z)`:

- exact `n`: cross-entropy against the mass of `N(n, σ²)` on each step bin (bin `k` spans `[k − ½, k + ½)`, the
  first bin is open below and `8+` above; `σ = 0` gives one-hot targets); `dead` gets no mass;
- at least `n`: `−log(Σ_{k ≥ min(n, 8)} p_k + p_dead)`;
- dead: `−log p_dead`.

Each example's loss is multiplied by its weight; a step averages over its examples' weights. A second term,
`bin_mass_weight · −log Σ_bins softmax(full logits)`, puts the vocabulary's mass on the bins, so the bins that
matter are among the top-20 tokens vLLM returns (the nine-way softmax alone leaves the rest of the vocabulary
unconstrained; zero-shot only 68% of the mass is on the bins). A bin outside the top 20, such as `dead` when no dead
labels were trained, is then negligible. With one-hot targets and weight 1 the two
terms add up to the ordinary full-vocabulary cross-entropy of the bin token.

## Training (`training.py`, `experiments/phase3_value.py`)

LoRA on all language-model linear layers (`policy.adapters.LORA_TARGET_PATTERN`), bf16 autocast, gradient
checkpointing, length-grouped micro-batches and the cosine schedule of `training.sft`. `initial_adapter` (a path) continues
training a published value adapter, with its own rank and alpha, instead of starting a new one. Only the last position's
hidden state is projected onto the vocabulary. Validation: weighted loss, bin accuracy (exact and dead labels), MAE
of the expected steps given alive (exact labels; `8+` read out as in the readout), Spearman correlation of `h` with
the exact remaining steps, dead-vs-exact AUC of `p_dead`, mean probability of censored events, the bins' full-vocabulary
mass and the served h error: the mean change of `h` when it is read from vLLM's top-20 logprobs as the estimator
does.

## Serving (`estimator.py`)

`ValueModelEstimator.estimate(nodes)` scores the nodes 32 to a request (`score_next_tokens` with a list of prompts;
one request per node cost the client ~10 ms of CPU each), the requests concurrently and round-robin over servers
(`adapter` as the model, or a merged value model with no adapter), renormalizes the returned logprobs over the nine bin tokens (a bin outside the
top-k gets the smallest returned logprob, an upper bound on its own) and returns `BinnedValueEstimates`:
`remaining_steps` (h) and `prompt_tokens` as A* expects, plus the per-node `distributions`. A prompt that does not
fit the server's context reads out as dead. Serve the adapter with `--lora-modules <name>=<directory>` and enable it
in a run config:

```toml
[priority]
kind = "a_star"
value_weight = 1.0

[value]
model = "qwen3.5-2b"
tokenizer = "Qwen/Qwen3.5-2B"
server_urls = ["http://127.0.0.1:8000/v1"]
adapter = "value-v0"

[value.readout]
eight_or_more_steps = 12.0
dead_steps = 16.0
```

`run_search.py` then writes `ValueStatistics` (scored states as `requests`, `http_requests`, prompt tokens, missing
bin tokens, prompts too long) to
`value.json`.

## Search-graph targets (`graph_targets.py`, `ranking.py`, `benchmark.py`)

For the next phase (DESIGN.md, "Value model"), on graphs labelled by `search.graph_labels.label_graph`:

| Node | Proof probability | Steps | Weight |
|---|---|---|---|
| proof graph | 1 | exact (fewest new-state or transposition edges to a verified proof) | `proof_graph_weight` |
| dead end | 0 | none | `dead_end_weight` |
| expanded off the graph | mean over expanded descendants (dead-end descendants count 0) | mean of distance + h | `averaged_weight · n / (n + half_weight_descendants)` |
| never expanded | none | none | — |

Estimates are `ValueEstimate(proof_probability, remaining_steps)`: from the bins as `1 − p_dead` and the steps given
alive (`bin_estimate`), or from a tree's recorded scalar h as `(dead_steps − h) / (dead_steps − 1)`, clipped
(`RemainingStepsReadout`). `bin_target` maps a target back onto the nine bins (probability spread over the step bins,
the rest dead), so only these two adapters change with the value head. `temperature` slides the average toward the
best descendant (softmax weights on the proof probability; `None` is the plain mean).

Sibling pairs (`sibling_pairs`) are taken among the distinct states one expanded node reached over new-state, sibling
and transposition edges. The benchmark (`build_benchmark`, `experiments/value_benchmark.py`) keeps every sibling
group with a proof-graph state and fills up to `max_states_per_tree` with groups holding a dead end, then the rest;
`benchmark_metrics(benchmark, estimates)` scores any estimates aligned with its states.

`graph_trainer.py` trains the value LoRA on these targets (`experiments/grpo_phase.py`): per target the cross-entropy
against `bin_target` (plus the bin-mass term), weighted and rebalanced per step across sources (`SourceShares`), plus
`ranking_weight` times the weighted logistic loss `softplus(-(s_preferred - s_other) / temperature)` on sibling pairs,
with s the log-odds of the proof probability `log(1 - p_dead) - log p_dead` (or the probability itself). A parent's
pair members train in the same micro-batch; exact and dead v0 examples are replayed as `replay_share` of the pointwise
items. `run_value_gate` scores the benchmark with the new and the current adapter and passes when the sibling pairwise
accuracy improves by `min_ranking_gain` without the proof-graph/dead-end AUC or the anchors' Brier score regressing
beyond their tolerances.

## API

| Call | Purpose |
|---|---|
| `render_value_prompt(tokenizer, goals) -> str`, `render_value_target(bin) -> str`, `bin_token_ids(tokenizer)` | prompt text, SFT-style target, verified single-token bin ids |
| `traced_examples(steps) -> list[ValueExample]` | exact labels of traced states |
| `tree_examples(record, source, config) -> list[ValueExample]` | exact, censored and dead labels of a `TreeRecord` |
| `merge_duplicates(examples) -> list[ValueExample]` | one example per normalized goal list |
| `write_examples(path, examples)`, `read_examples(path)` | JSON lines |
| `value_losses(bin_logits, labels, sigma)`, `bin_mass_losses(full_logits, bin_ids)` | per-example losses |
| `value_metrics(distributions, examples, readout) -> ValueMetrics` | validation metrics |
| `train_value_model(config, tokenizer, train, validation, device, directory, on_step, on_evaluation)` | LoRA training |
| `open_value_estimator(config: ValueConfig)` | async context manager yielding the A* value estimator |
