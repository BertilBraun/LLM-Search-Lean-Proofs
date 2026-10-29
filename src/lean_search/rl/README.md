# Search-tree GRPO

The policy update of DESIGN.md, "Policy update: GRPO over sibling groups": labelled search graphs become groups of
sibling samples, every tactic of a sample earns its own reward, and the trainer trains on the tokens the model sampled.
`training_phase.py` runs one phase (`experiments/grpo_phase.py`, configs in `experiments/configs/grpo/`).

## Per-tactic labels (`search/tactic_labels.py`)

`policy_tactics(record, labels, min_expanded_nodes)` labels every executed tactic of every policy sample (keyed by
the executed edge; repeats share it, infrastructure failures are left out). A tactic's state is `Edge.tactic_goals[i]`,
Lean's printing before the search's `rename_i`; it matches a node through the node's own goal key or the last tactic
state of any edge reaching it (`graph_labels.nodes_by_goal_key`). The checks, in order:

| Label | When |
|---|---|
| `failing` | the first tactic Lean rejected (`executed_tactics[applied_tactics]`; errors, heartbeat and wall-clock timeouts, unknown identifiers), the closing tactic of an unverified proof, and the single tactic of a sample without a usable block (no block, cut off, empty, forbidden) |
| `masked` | every tactic after the failing one |
| `proof_graph` (closing) | no goals left and the proof verified |
| `no_progress` | the state equals one before it on its path: the node, its ancestors, or an earlier state of the same block (the trailing no-ops skipped after a nested proof closed repeat their state, so they count too) |
| `redundant_hypothesis` | the state adds only hypotheses whose types the context already had, or reflexive `a = a` / `a ↔ a` (`lean/hypotheses.py`, `adds_only_redundant_hypotheses`, against every earlier state of the path); a flattened `have h : A` also puts `⊢ A` first, which counts as redundant when `A` is |
| `proof_graph` | a proof-graph node's state, or an intermediate state of a forward edge on a route to a proof |
| `off_graph` | a dead end (its expansion produced nothing usable: real evidence however small), or an expanded node off the proof graph with at least `off_graph_min_expanded_nodes` (4) expanded nodes in its subtree, itself included: the n of the value targets' weight n / (n + 4) |
| `unknown` | anything else: a node never expanded, an expanded off-graph node with live children and fewer expanded nodes (one harvesting or ε expansion is too little evidence to push a sibling down), or a state no node has |

The proof graph is defined at tactic granularity: `label_graph` splits a forward edge at every intermediate tactic
state that is another node's state, so that node routes to the proof too (and gets exact remaining steps). Records
written before `tactic_goals` was kept know only the final state of each edge: its earlier tactics are `proof_graph` on
a route to a proof and `unknown` otherwise; the last one is judged as above against the parent (redundancy included).

## Groups and rewards (`grpo_groups.py`)

One group per expanded proof-graph node with policy samples; no groups off the proof graph or in unsolved trees.
With `require_policy_proof` (default) a group also needs a policy sample with a `proof_graph` tactic: where only the
automation sweep's children reach the proof graph, the group is left out (`TreeGroups.without_policy_proof`, the
search metrics' `graph.groups_without_policy_proof`); a policy sample repeating the sweep's tactic counts as the
policy's. Identical texts are merged (multiplicity = the samples behind them). Each tactic gets
`R = (1 − λ) · G + λ · L` (`RewardConfig`, λ = `local_share` = 0.15, L clipped to [−1, 1]):

| Label | G | L | R |
|---|---|---|---|
| proof graph | 1 | `goal_closed_bonus` (0.1) per goal closed | 0.85 + 0.015 per goal |
| off graph | μ · q (`value_share`, 0 until a value model passed the gate; q averages the state's expanded descendants, else its own estimate) | 0 | 0 before the gate |
| no progress, redundant hypothesis | 0 | `no_progress_local` (−1, as a failure: a no-op wastes the sample too) | −0.15 |
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

Groups and texts are matched per tree (`PolicyTree`: a tree's groups with its `TreeRecord.expansions`), by node id and
edge id, which identify them only within their tree: the same statement is often searched twice in a phase (always
in the overfit test). Each expansion's texts record the published policy version that sampled them
(`ExpansionTexts.policy_version`, from the pause gate the loop sets when it serves a version; None outside the loop
and in older records), carried to every sequence (`PolicySequence.policy_version`).

## Trainer (`policy_trainer.py`)

PPO-clipped objective per token, clip [1 − 0.2, 1 + 0.28], loss Σ token loss / (sequences in the step × 256), KL (k3)
to the data-collecting policy and to the starting policy reported, NLL replay. Log-probabilities divide the logits by
each sample's recorded temperature (`ExpansionTexts.temperature`; `PolicyDataConfig.default_temperature` for old
records). The output layer runs in fp32 per chunk of 512 positions (hidden states and weight upcast, autocast off),
in the scoring and the training forward alike: bf16 logits step by 0.125 at |logit| 16–32, and one step moves a PPO
ratio by ×1.17 at T = 0.8. The upcast weight is transient: 4 bytes per vocabulary entry and hidden unit (~2.5 GB at
248k × 2,560). Old
log-probabilities are the trainer's own before the phase's first update; the recorded vLLM log-probabilities are
compared with them (`GrpoTrainingResult.sampler_agreement`: mean and mean absolute difference, k3 KL; and the same per
sampling version, `sampler_agreement_by_version`, since trees spanning phases hold samples of earlier versions; no
importance correction), which compares like with like only when the policy servers run with `--logprobs-mode
processed_logprobs` (vLLM's default reports the raw distribution before temperature; `deployment/README.md`). No
length filter: length only sizes micro-batches, and a sequence beyond `max_sequence_tokens` (the servers' context) is
an assertion. `passes_per_phase` (default 2) passes over the phase's sequences.

The adapter that trains is the starting policy's own (SFT) adapter, continued phase by phase on the weights it was
trained on (`model`, raw Qwen3.5-4B; `initial_adapter` the published one), as the value model's adapter continues on
raw Qwen3.5-2B. Publishing merges it into those weights, which then lie between bf16 grid points, so the rounding of
small updates is unbiased; a fresh adapter on already-merged bf16 weights would lose most of them (at a per-element
update of 1e-5, 88% of elements unchanged, 28% of the update kept). Its rank and alpha are the adapter's own
(`[policy.lora]` is unused). The KL reference (`reference = "starting_weights"`) is `model` with `reference_adapter`,
the starting policy's adapter: equal to the old log-probabilities while the phase continues that adapter (version 0),
else scored with it loaded next to the trained adapter, which alone trains again afterwards.

## Metrics

`tree_statistics.graph_statistics` adds per tree: tactics by label over every policy sample and over the groups,
groups with a signal, groups left out without a policy proof, the global and local reward parts, proofs with their
tactics and blocks, harvest expansions with the proofs and proof-graph nodes they created, and ε-picks.
`training_phase.grpo_phase_record` turns a policy outcome into the dashboard's `grpo` line (trained groups, tactics
by label, local share of the advantages, sampler mismatch overall and by sampling age, i.e. the version trained from
minus the version that sampled, forced answers kept, training and sampling time).

## The loop (`loop.py`, `loop_services.py`, `experiments/grpo_loop.py`, `experiments/configs/grpo/loop.toml`)

One long-running process. `sampling.concurrency` workers take statements from the statement source and search them
with the new search (`search_theorem`; n = 8, harvesting and ε on, `grpo/search/visible_student_v2.toml` on the
loop's servers), one Lean REPL each; every finished tree goes gzipped to `trees/phase_<k>/` of the phase collecting at
that moment, with a line in `trees/index.jsonl` (`tree_store.py`). A phase starts once `min_sampling_minutes` of
sampling produced `min_solved_trees` solved trees (or after `max_sampling_minutes` with one) and runs:

| Stage | What happens |
|---|---|
| pause | every policy and value request waits at the pause gate; searches keep their trees and REPL states in place, and trees finishing now belong to the next phase |
| training | servers on the training GPU sleep; `grpo_phase.py` runs on that GPU (`SubprocessTrainer`, log in `training/phase_<k>.log`): labels the phase's trees, trains the policy (two passes) and, every `value_every_phases` with a gate benchmark, the value model plus its gate; the loop labels the same trees meanwhile for the `search` and `curriculum` metrics |
| publishing | `training_phase.publish_phase`: version k + 1 with the new policy adapter and the new value adapter only if it passed the gate, merged on the CPU into `serving.policy_base_model` and `value_base_model` (`MergedPublisher`); every server swaps to it in place (`publish_weights`), sleeping ones wake with it (`restore_gpu`), and the searches' pause gate records the version for the samples to come; the first accepted value model turns μ on (`value_share_after_gate`) for later phases |
| evaluating | due fixed targets run as their own jobs (`grpo_evaluate.py`) while the searches stay paused: by loop hours (`every_hours`), once before the first phase (`at_start`), or when requested (`grpo_loop.py request-evaluation`) |
| resume | the searches continue with the new weights |

GPU assignment: `training.gpu` trains; servers on it are released for the phase (none in `loop.toml`: GPU 0 trains,
GPUs 1–3 each serve the merged policy and the merged value model). Policy servers run with `--logprobs-mode
processed_logprobs` (`grpo_loop.py serve-commands` prints every start command).

Restart: `loop_state.json` holds the phase, its stage, sampling and training time, whether a value model passed the
gate and the evaluation clock; `models/current.json` and `versions.jsonl` the published versions; the tree index the
searched statements and per-phase trees. `grpo_loop.py run` after a crash first swaps every server to the current
version, finishes the interrupted stage (training again, publishing only if `current.json` lacks the phase's
version, the remaining evaluations), then resumes sampling. Searches cut off by the crash are lost (the curriculum
feeds each statement once; the fixed list feeds it again). The node's disk is not persistent: back up the run's
`metrics/`, `phases.jsonl`, `evaluations*/summary.json` and `report.md`; trees and adapters stay on the node.

Metrics per phase (`MetricsWriter`, `<run>/metrics/`): `status` every `status_seconds`, `curriculum` and `search`
(`phase_metrics.search_phase_record`: graph statistics, failure tiers, forced answers and repetition loops, Lean time
per expansion, block length), `grpo` (from the trainer's `phase.json`), `value` when a value model met the gate,
`timing` (sampling, training, publishing and evaluation seconds), `fixed_targets` from the evaluations; `system`
from `dashboard.py record-system`. Failure tiers are a message-based approximation (`phase_metrics.py`).

The boundaries are protocols (`TreeSearcher`, `PhaseTrainer`, `ModelServers`, `Evaluations`); the tests run the loop
with fakes for them (`tests/rl/loop_fakes.py`) and real Lean for the start-state and renamed searches.

## Fixed targets (`fixed_sets.py`, `fixed_targets.py`, `evaluation.py`)

- `grpo_fixed_sets.py select` fixes the probe set (167 per stratum) and the value gate's set (134 per stratum):
  verified pool v3 statements the automation does not close, easy (difficulty < 2), medium (< 4) or hard by the
  curriculum's difficulty estimate (the known proof's tactic count until roots are scored), disjoint, in seeded hash
  orders. The loop's curriculum never feeds either (`statements.held_out`).
- `probe`: 16 expansions, 10-minute cap per problem, no harvesting, no ε, with the loop's value model; every 6 hours
  of loop time and before the first phase, inside the loop's pause (GPUs free, the evaluation's own pool of
  `concurrency` REPLs next to the paused searches' idle ones). `minif2f`: miniF2F-valid at 64 expansions, at
  milestones. `held_out_states`: per-sample success on the 512 per-step evaluation states (`single_step.py`), with the
  probe. Each writes `evaluations/<target>_v<version>/` (resumable), a `fixed_targets` line and `evaluations.jsonl`.
- `grpo_fixed_sets.py gate-benchmark` searches the gate set once with the starting policy and no value model
  (`grpo/gate_search.toml`, log-probability best-first) and builds the value benchmark from those trees
  (`value/benchmark.py`), the loop's `training.value_benchmark`.

## Statement renaming (`renaming.py`)

Off by default; `[renaming] enabled = true` when the starting policy is the naming A/B's named arm. Renamings are
computed once with the data rewrite's namer (`grpo_fixed_sets.py rename --sources probe gate pool minif2f`) and
looked up by problem name in the loop, the probe and miniF2F evaluations and the gate search. The search runs on the
renamed statement; a found proof is verified against the original statement with `rename'` first
(`data_rewrite.statement_renaming.verify_against_original`); a proof that fails counts as unsolved
(`SearchResult.original_verified = False`) and keeps no tree. Tree records hold the renamed statement. The held-out
states are traced states and are never renamed.

## Cheap tests

- **Single-step GRPO** (`single_step.py`, `experiments/grpo_single_step.py`, `grpo/single_step.toml`): one policy
  request per held-out state, executed from the state rebuilt by replay (`search_theorem(..., start_state=...)`).
  Proof graph: the state's traced proof proves it and every later state of it, so a tactic that closes the goals or
  reaches one of those states (by goal key) is on the proof graph; other new states are unknown (neutral). The root
  forms a group when a sample reaches the proof graph (states no sample solves train nothing). No extra search per
  state. Success per sample = the block runs completely and ends there (the per-step evaluation's criterion). Each arm (per-tactic, sequence credit) runs 3 rounds of sample, measure
  (training and 512 disjoint states), train (one phase, two passes), then a last measurement; `report` writes both
  curves. States whose goals had inaccessible names are renamed by the search, so their reference keys may not match.
- **Overfit on 300 statements** (`grpo/loop_overfit.toml`): the loop on a fixed list (`grpo_fixed_sets.py
  select-overfit`: 100 per stratum outside the probe and gate), policy only; `grpo_loop.py report` gives the solve
  rate per phase, which must rise.
- **Naming A/B** (`experiments/grpo_naming_ab.py`, `grpo/naming_ab.toml`): the data rewrite's two short fine-tunes on
  the probe (the named arm on renamed statements), the unknown-name error rate per policy sample of those searches
  (`phase_metrics.unknown_names`) and MATH-500 (`evaluation/reasoning_retention_naming_ab.toml`).
