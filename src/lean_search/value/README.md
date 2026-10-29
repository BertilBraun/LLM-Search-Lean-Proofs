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
top-k gets the smallest returned logprob, an upper bound on its own) and returns `ValueEstimates`:
`remaining_steps` (h) and `prompt_tokens` as A* expects, plus the per-node `distributions`. A prompt that does not
fit the server's context reads out as dead. A* passes the distributions on (`Scores.value_distributions`), and every
scored node keeps its bins next to its h (`Node.value_distribution`, `NodeRecord.value_distribution`; None in records
written before, and for priorities without a binned value model). Serve the adapter with `--lora-modules <name>=<directory>` and enable it
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

For the next phase (DESIGN.md, "Value model"), on graphs labelled by `search.graph_labels.label_graph`, every
expanded state gets `y = (1 − μ) · z + μ · q` (`value_share` = μ; 0 until a value model passed the gate, then 0.15):

| Node | z (concrete label) | q (value part) | Weight |
|---|---|---|---|
| proof graph | 1, exact steps (fewest top-level tactics over new-state, sibling or transposition edges to a verified proof; an edge whose intermediate tactic state, `Edge.tactic_goals`, is another node's state also routes through that node) | as below | `proof_graph_weight` |
| expanded off the graph, solved or unsolved tree (dead ends included) | 0 ("no proof within this budget") | mean over the expanded descendants (each once, at its fewest tactics): proof probability, and distance + h; the state's own estimate without any | `off_graph_weight · n / (n + half_weight_expanded_nodes)`, n the state and its expanded descendants |
| never expanded | — | — | no target |

Estimates are `ValueEstimate(proof_probability, remaining_steps)`: from the bins as `1 − p_dead` and the steps given
alive (`bin_estimate`; `recorded_estimates` reads a node's recorded bins so), or, for records written before the bins
were kept, from the scalar h as `(dead_steps − h) / (dead_steps − 1)`, clipped (`RemainingStepsReadout`). `bin_target` is the mixture `(1 − μ) · bins(z) + μ · bins(q)`: bins(z) is the smoothed exact
step on the proof graph and all-dead off it, bins(q) spreads q's proof probability over the step bins around its
steps and puts the rest on dead, so `1 − p_dead` of the target is y. A target without any estimate is z alone.
`temperature` slides q toward the best descendant (softmax weights on the proof probability; `None` is the plain
mean). Dead ends are only a statistic (`GraphStatistics.dead_ends`, the benchmark's separation metrics).

Sibling pairs (`sibling_pairs`) are taken among the distinct states one expanded node reached over new-state, sibling
and transposition edges: each proof-graph child over each expanded off-graph sibling (`proof_over_expanded_weight`
times the sibling's `n / (n + half_weight_expanded_nodes)`) and over each never-expanded sibling
(`proof_over_never_expanded_weight`, 0 by default). Unsolved trees give no pairs, nor do two off-graph siblings.

`graph_trainer.py` trains the value LoRA on these targets (`experiments/grpo_phase.py`): per target the cross-entropy
against `bin_target` (plus the bin-mass term), weighted and rebalanced per step across sources (`SourceShares`), plus
`ranking_weight` times the weighted logistic loss `softplus(-(s_preferred - s_other) / temperature)` on sibling pairs,
with s the log-odds of the proof probability `log(1 - p_dead) - log p_dead` (or the probability itself). A parent's
pair members train in the same micro-batch; exact and dead v0 examples (v0's own training data, `value/v0/train.jsonl`)
are replayed as `replay_share` of the pointwise items, drawn anew by each phase's optimization seed.

## The gate (`gate_statistics.py`)

`run_value_gate` scores the benchmark fresh with the candidate and the published adapter (`benchmark_scores`, the same
`BenchmarkScores` as the served path) and `value_gate` decides on the quantity A* orders its frontier by: for every
labelled sibling pair of the benchmark (`labelled_pairs`: a proof-graph child against a dead-end sibling, or against
an off-graph sibling the search explored, `min_expanded_nodes`), whether the proof-graph child gets the lower
`h = Σ p_k · steps_k` (ties count half). The statistic is the candidate's share of such pairs minus the published
model's, and its interval a percentile interval from a paired cluster bootstrap: problems are drawn with replacement
with all their pairs (`bootstrap_resamples` 5000, fixed `seed`, `confidence` 0.95). The candidate passes when the lower
bound lies above `min_lower_bound` (0) and the benchmark holds no value-model-guided tree (`guided_trees = "refuse"`;
`"warn"` only reports them in `warnings`). `GateStatistic` reports the problems and pairs behind it, the pairs the two
models order differently, and the effective pairs: the independent pairs that would give the bootstrap's spread
(fewer than the pairs when the pairs of one problem move together). The benchmark metrics of both models (AUC, Brier,
pair accuracy by p_dead, Spearman) are kept in `GateResult` as diagnostics, never as pass criteria; v0 has no
meaningful p_dead (≈ 1e-7 everywhere), so any metric of p_dead favours every new model.

What it can detect, measured on the value-free row-2 trees (miniF2F-valid, log-probability search of SFT v2, 244
trees): 52 labelled pairs (50 proof over expanded, 2 proof over dead end) over only 13 problems (16, 8, 6, 5, 5, 3, 2,
2 and five with one); `min_expanded_nodes = 1` would give 95 pairs over 24 problems. A model against itself gives the
interval [0, 0]. In simulations on that pair structure (a candidate changing 10-40% of the pairs, independently per
pair), the 95% half-width is 0.08-0.17, a candidate without a real gain passes in 2-4% of retrains, and a gain of
+0.10 in pairs ordered by h passes 22-61% of the time (60% only when the candidate changes few pairs); when the pairs
of a problem change together, power is lower still. The gate set's 402 problems give about 1.6 times the pairs.

`diagnostics.py` records per retrain (`ValueDiagnostics`, the dashboard's value page): the label distribution of the
window's targets per bin (proof graph, off graph in solved and in unsolved trees, v0 replay; weight-averaged, with
counts and weights), the predicted distributions (mean per bin, p_dead per tenth, expected steps given alive per step)
of the candidate and the published model on the benchmark and of the serving model on the phase's expanded and
frontier states (the recorded bins), and the calibration of the predicted proof probability against z on expanded
states (the candidate on the benchmark, the serving model on the phase).

## Value benchmark (`benchmark.py`, `benchmark_scoring.py`, `experiments/value_benchmark.py`)

Best-first search expands what its priority rates best, so the labels of an A* search on a value model are chosen
by that model: in the visible student's v0-guided trees every labelled sibling pair is ordered as v0 ordered the
expansions. The benchmark therefore records each run's provenance (`TreeProvenance`, from the run's `config.toml`):
`value_free` (cumulative log-probability or depth plus goals), `heuristic_value` (A* on the goal count),
`value_model` (A* on a named served adapter or merged value model) or `unknown_value` (trees with recorded estimates
and no config). `guidance_conflicts` lists the runs guided by a compared model (by served name; `None` compares every
value model, and an unknown guide always conflicts); `build` refuses them unless `--guided-trees warn`, and so does
the gate (`GateConfig.guided_trees`). Benchmark trees come from a value-free search of the starting policy on
miniF2F-valid (`experiments/configs/value_benchmark_search.toml`, the commands are in its header).

`build_benchmark` keeps one tree per statement (the first run listing it), every sibling group with a proof-graph
state, and fills up to `max_states_per_tree` with groups holding a dead end, then the rest; never-expanded children
stay in. Metrics (`benchmark_metrics`):

| Metric | States and pairs |
|---|---|
| ranking | pairs of a preferred over an other sibling, both with a known label: proof graph over dead end, proof graph over an expanded off-graph sibling whose subtree the search explored (`min_expanded_nodes`, default the state plus one expanded descendant: the estimate-free counterpart of an averaged target, since value-free trees record no estimates to average), and that expanded sibling over a dead end; each type separately, the first two together as `pairwise_accuracy`; top-1 per group. Never-expanded and unexplored expanded siblings are unknown, not negatives: counted, never paired |
| steps | MAE and Spearman of the steps (given alive, or the recorded h) on proof-graph states |
| calibration, separation | fresh scores only: the anchors' ECE and Brier score and the proof-graph/dead-end AUCs of `1 − p_dead` |

Estimates come in two kinds. **Fresh**: `score_benchmark(estimator, benchmark)` scores every state through the
search's vLLM path (`ValueModelEstimator.score_states`: top-k logprobs renormalized over the nine bin tokens; a
prompt longer than the server's context gets no score) and stores the distributions with the served model's name and
the benchmark's fingerprint (`BenchmarkScores`, `write_scores`); `fresh_estimates` reads them back for the same
benchmark only, so every model is compared on identical states. **Recorded**: the h a search stored per node
(`recorded_benchmark_estimates`, or `looked_up_estimates` for the h a model recorded for identical goals of the same
statement in another search it guided). An h has no probability, so recorded metrics are ranking and steps only, are
labelled "recorded (biased if the trees were guided by this model)", and `circular_runs` names the runs whose labels
the estimating model chose. The `(dead_steps − h) / (dead_steps − 1)` mapping is used only for training targets.

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
