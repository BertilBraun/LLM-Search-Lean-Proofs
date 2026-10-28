# Search-tree GRPO

The policy update of DESIGN.md, "Policy update: GRPO over sibling groups": labelled search graphs become groups of
sibling samples, every tactic of a sample earns its own reward, and the trainer trains on the tokens the model sampled.
`training_phase.py` runs one phase (`experiments/grpo_phase.py`, configs in `experiments/configs/grpo/`).

## Per-tactic labels (`search/tactic_labels.py`)

`policy_tactics(record, labels)` labels every executed tactic of every policy sample (keyed by the executed edge;
repeats share it, infrastructure failures are left out). A tactic's state is `Edge.tactic_goals[i]`, Lean's printing
before the search's `rename_i`; it matches a node through the node's own goal key or the last tactic state of any
edge reaching it (`graph_labels.nodes_by_goal_key`). The checks, in order:

| Label | When |
|---|---|
| `failing` | the first tactic Lean rejected (`executed_tactics[applied_tactics]`; errors, heartbeat and wall-clock timeouts, unknown identifiers), the closing tactic of an unverified proof, and the single tactic of a sample without a usable block (no block, cut off, empty, forbidden) |
| `masked` | every tactic after the failing one |
| `proof_graph` (closing) | no goals left and the proof verified |
| `no_progress` | the state equals one before it on its path: the node, its ancestors, or an earlier state of the same block (the trailing no-ops skipped after a nested proof closed repeat their state, so they count too) |
| `redundant_hypothesis` | the state adds only hypotheses whose types the context already had, or reflexive `a = a` / `a ↔ a` (`lean/hypotheses.py`, `adds_only_redundant_hypotheses`, against every earlier state of the path); a flattened `have h : A` also puts `⊢ A` first, which counts as redundant when `A` is |
| `proof_graph` | a proof-graph node's state, or an intermediate state of a forward edge on a route to a proof |
| `off_graph` | an expanded node off the proof graph (dead ends included) |
| `unknown` | anything else: a node never expanded, or a state no node has |

The proof graph is defined at tactic granularity: `label_graph` splits a forward edge at every intermediate tactic
state that is another node's state, so that node routes to the proof too (and gets exact remaining steps). Records
written before `tactic_goals` was kept know only the final state of each edge: its earlier tactics are `proof_graph` on
a route to a proof and `unknown` otherwise; the last one is judged as above against the parent (redundancy included).

## Groups and rewards (`grpo_groups.py`)

One group per expanded proof-graph node with policy samples; no groups off the proof graph or in unsolved trees.
Identical texts are merged (multiplicity = the samples behind them). Each tactic gets `R = (1 − λ) · G + λ · L`
(`RewardConfig`, λ = `local_share` = 0.15, L clipped to [−1, 1]):

| Label | G | L | R |
|---|---|---|---|
| proof graph | 1 | `goal_closed_bonus` (0.1) per goal closed | 0.85 + 0.015 per goal |
| off graph | μ · q (`value_share`, 0 until a value model passed the gate; q averages the state's expanded descendants, else its own estimate) | 0 | 0 before the gate |
| no progress, redundant hypothesis | 0 | `no_progress_local` (−0.5) | −0.075 |
| failing | 0 | `failure_local` (−1) | −0.15 |
| unknown, masked | — | — | no reward |

## Advantages (`advantages.py`) and tokens (`token_credit.py`, `policy_data.py`)

A sample's score is the mean R of its tactics with a reward; the baseline b is the multiplicity-weighted mean score of
the group's samples with a score (all-unknown samples stay out). No division by a standard deviation. Groups whose
advantages are all zero are dropped (`GroupAdvantages.has_signal`).

| Tokens | `per_tactic` credit (default) | `sequence` credit |
|---|---|---|
| explanation and opening fence (before the first tactic's span) | score − b | score − b |
| a tactic's span, and the gap before it (newlines, comments) | R − b; untrained when unknown or masked | score − b |
| after the last tactic (closing fence, end of turn) | the last tactic's R − b after a complete block; untrained after a failure | score − b |
| inserted by the harness (`SampledTokens.inserted`) | untrained | untrained |

Unknown scores train nothing. A sample without a span per executed tactic (no usable block, spans not recorded) gets
score − b on every sampled token, so an unparsed sample scores like a failing tactic over its whole completion.

Tokens are the recorded ones (`SampledCompletion.tokens.token_ids`, no re-tokenization; the prompt is the recorded
prompt encoded without special tokens, as vLLM does). Their characters come from decoding them one by one with the
policy tokenizer (`decoded_offsets`; tokens sharing a multi-byte character share its range), so the executed tactics'
character spans (`SampledCompletion.tactic_spans`, after flattening) map to tokens. The decoded text is the sample's
text without token-less inserted spans (the closing fence appended after the cap), followed by the end of turn or a
stop string; positions after such a span shift past it. Tokens that do not decode to the text are trained with
sequence credit and counted (`token_mismatch_sequences`). Records written before tokens were kept are tokenized again
from the text (`retokenized_sequences`, no sampler log-probabilities): only for old trees and offline tests.

## Trainer (`policy_trainer.py`)

PPO-clipped objective per token, clip [1 − 0.2, 1 + 0.28], loss Σ token loss / (sequences in the step × 256), KL (k3)
to the data-collecting policy and to the starting weights reported, NLL replay. Log-probabilities divide the logits by
each sample's recorded temperature (`ExpansionTexts.temperature`; `PolicyDataConfig.default_temperature` for old
records). Old log-probabilities are the trainer's own before the phase's first update; the recorded vLLM
log-probabilities are compared with them (`GrpoTrainingResult.sampler_agreement`: mean and mean absolute difference,
k3 KL), which compares like with like only when the policy servers run with `--logprobs-mode processed_logprobs`
(vLLM's default reports the raw distribution before temperature; `deployment/README.md`). No length filter: length
only sizes micro-batches, and a sequence beyond `max_sequence_tokens` (the servers' context) is an assertion.
`passes_per_phase` (default 2) passes over the phase's sequences.

## Metrics

`tree_statistics.graph_statistics` adds per tree: tactics by label over every policy sample and over the groups,
groups with a signal, the global and local reward parts, proofs with their tactics and blocks, harvest expansions with
the proofs and proof-graph nodes they created, and ε-picks. `training_phase.grpo_phase_record` turns a policy outcome
into the dashboard's `grpo` line (trained groups, tactics by label, local share of the advantages, sampler mismatch,
forced answers kept, training and sampling time).
