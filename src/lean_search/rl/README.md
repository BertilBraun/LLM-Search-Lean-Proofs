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

A `proof_graph` tactic also carries its state's remaining steps (`TacticOutcome.remaining_steps`, top-level tactics
to a verified proof, 0 once proved): its node's `GraphLabels.remaining_steps`, or for an intermediate state the
target's plus the tactics left in the edge; a state with several (several nodes or routes with its goal key) takes the
shortest.

## Groups and rewards (`grpo_groups.py`)

One group per expanded proof-graph node with policy samples; no groups off the proof graph or in unsolved trees.
With `require_policy_proof` (default) a group also needs a policy sample with a `proof_graph` tactic: where only the
automation sweep's children reach the proof graph, the group is left out (`TreeGroups.without_policy_proof`, the
search metrics' `graph.groups_without_policy_proof`); a policy sample repeating the sweep's tactic counts as the
policy's. Identical texts are merged (multiplicity = the samples behind them). Each tactic gets
`R = (1 − λ) · G + λ · L` (`RewardConfig`, λ = `local_share` = 0.15, L clipped to [−1, 1]), and a proof-graph state
δ (`progress_per_step` = 0.2) per remaining step it is closer to a proof than the group's node, `δ · (d(node) − d(s))`
(part of the global part; negative for a proof-graph state farther away, but the global part never falls below the
best off-graph state's, (1 − λ) · μ, so a valid detour on the proof graph never scores below leaving it: from 5 steps
farther on it earns what an off-graph state does, and as a first tactic still more than a Lean error):

| Label | G | L | R |
|---|---|---|---|
| proof graph | 1 | `goal_closed_bonus` (0.1) per goal closed | 0.85 + 0.2 per step of progress + 0.015 per goal, global part ≥ (1 − λ) · μ |
| off graph | μ · q (`value_share`, 0 until a value model passed the gate; q averages the state's expanded descendants, else its own estimate) | 0 | 0 before the gate |
| no progress, redundant hypothesis | 0 | `no_progress_local` (−1, as a failure: a no-op wastes the sample too) | −0.15 |
| failing | 0 | `failure_local` (−1) | −0.15 |
| unknown, masked | — | — | no reward |

## Advantages (`advantages.py`) and tokens (`token_credit.py`, `policy_data.py`)

A block t1..tk is credited the way the search uses it: the longest valid prefix becomes the child, so a tactic after
the first decides only whether the block gets further than the state before it (`grpo_groups.judged_in_block`,
`TacticReward.gain`):

| Tactic | Advantage |
|---|---|
| the anchor: the first reaching a state with a reward (proof graph, off graph), else the first tactic when it failed or made no progress | R − b₁ |
| a later one reaching a state with a reward | R(s_i) − R(s_j), s_j the most recent earlier state of the block with a reward: δ per step gained on the proof graph (plus its goal bonus), the whole drop when it leaves the proof graph |
| any other failing, no-progress or redundant one (a no-op before the anchor included) | −c (`wasted_tactic_cost` = 0.1, a local part in the local share): the prefix is kept, only its tokens are wasted |
| unknown, masked | untrained |

A sample's score is its final state's R minus c per wasted tactic (`GroupSample.score_parts`: the anchor's R plus
every gain); a sample whose first tactic fails or makes no progress, with no state with a reward after it, scores
that tactic's R (minus c per later wasted one), one without a state with a reward or such a first tactic has no score.
The baseline b is the multiplicity-weighted mean score of the group's samples with a score, the first-tactic baseline
b₁ the same mean of their anchors' R (`GroupSample.anchor_parts`, `GroupAdvantages.first_tactic_baseline`). The
explanation gets score − b and a block's tactic advantages add up to score − b₁: b − b₁ is the group's mean progress
after the anchor (minus the wasted costs), which the later tactics' gains carry. Judged against b, the anchor was
charged that progress, so a correct first tactic shared by every proof got a negative advantage whenever most samples
proved in one multi-tactic block (6 of 8 in one 4-tactic block at d = 4: −0.16, now +0.30). No division by a standard
deviation. Groups whose advantages are all zero are dropped (`GroupAdvantages.has_signal`).

Scale with the node's distance d: the anchor's advantage spans one state's R and later tactics get ±δ per step,
whatever d; only the explanation's score − b grows, with the progress samples make within one block (bounded by
block length, not by d). Simulated groups of 8 with blocks of 1–6 tactics, each tactic correct with probability 85%
(50%): mean |anchor advantage| 0.10–0.11 (0.51) at every d; mean |explanation advantage| 0.11 at d = 1 and 0.27–0.28
at d ≥ 7 (0.51–0.54 at every d); the local share of the tactic advantages 0.14 at d = 1 and 0.06 at d ≥ 7
(0.14–0.15). Progress is not normalized per group: the wider spread at deep nodes comes from samples that differ by several
real steps, and dividing δ by d would raise the continue threshold below at deep nodes and push their blocks short.

Stopping after t_i keeps s_i, the reference point of t_{i+1}, so the closing tokens get 0. Continuing gets δ · steps
gained when t_{i+1} is correct, −c when it fails or makes no progress, nothing when its state is unknown, and the
whole drop R(s_i) − R(off) ≈ 0.85 + δ · progress when it is valid but leaves the proof graph for a well-explored
off-graph state or a dead end. So it pays when δ · P(correct) − c · P(error) − drop · P(valid off graph) > 0: the
threshold P(correct) > c / (c + δ) = 1/3 holds only when the alternative to a correct tactic is a Lean error. With 5%
valid off-graph steps it is about 0.49. A valid step off the graph thus costs about 10× a later error; this follows
what the search keeps (the error leaves the proof-graph prefix as the child) and stopping still beats deliberate
errors, but it pushes blocks shorter than 1/3 suggests: watch the block length and continue rate. The closing tokens are trained with advantage 0 rather than masked: the loss divides by a fixed sequences × 256 tokens,
so a zero-advantage token adds no gradient and changes no other token's weight; it only keeps the stop decision
under the KL term (`kl_coefficient`, 0 by default) and in the per-token metrics, as a decision with a known neutral
value. After a failure the closing follows masked tactics and stays untrained.

| Tokens | `per_tactic` credit (default) | `sequence` credit |
|---|---|---|
| explanation and opening fence (before the first tactic's span) | score − b | score − b |
| a tactic's span, and the gap before it (newlines, comments) | the tactic's advantage above; untrained when unknown or masked | score − b |
| after the last tactic (closing fence, end of turn) | 0 after a complete block; untrained after a failure | score − b |
| inserted by the harness (`SampledTokens.inserted`) | untrained | untrained |

Unknown scores train nothing. A sample without a span per executed tactic (no usable block, spans not recorded) gets
score − b on every sampled token, so an unparsed sample scores like a failing tactic over its whole completion.
Sequence credit sees the progress and the wasted-tactic costs through the score.

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
to the data-collecting policy and to the starting policy reported, NLL replay. The KL to the starting policy only feeds
a metric while `kl_coefficient` is 0, so its log-probabilities are scored on `reference_sequences` (256) sequences per
phase (a seeded draw; all of them with a KL penalty). Each step and pass also reports the mean probability ratio and
clip fraction of the positive- and of the negative-advantage tokens (`SignedRatios`, `GrpoTrainingResult.ratios_by_pass`,
the dashboard's `ratios_by_pass`): an update going the right way lifts the first above 1 and pushes the second below. Log-probabilities divide the logits by
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

After each stage (labelling, policy, value, merge) the job runs the garbage collector and empties the CUDA cache
(`training_phase.released_memory`): `module.compile()` stores a compiled wrapper of the module's own call on it, so a
compiled layer refers to itself and only the cyclic collector frees a stage's model, which would otherwise stay on the
GPU through the value training, the gate and the merges. `PhaseOutcome.memory` records the allocated and reserved GPU
memory after each stage (the largest rank's).

## Metrics

`tree_statistics.graph_statistics` adds per tree: tactics by label over every policy sample and over the groups,
groups with a signal, groups left out without a policy proof, the global and local reward parts, proofs with their
tactics and blocks, harvest expansions with the proofs and proof-graph nodes they created, ε-picks, and the policy
samples' blocks (`BlockCounts`: tactics and valid tactics per sample, valid tactics another tactic follows, and the
tactics after the first that failed or made no progress). The dashboard's search family charts block length and the
continue rate after a valid tactic next to the later tactics' failure rate; a steady fall in either length means the
stop credit pushes blocks short.
`training_phase.grpo_phase_record` turns a policy outcome into the dashboard's `grpo` line (trained groups, tactics
by label, local share of the advantages, sampler mismatch overall and by sampling age, i.e. the version trained from
minus the version that sampled, forced answers kept, training and sampling time).

## The loop (`loop.py`, `loop_services.py`, `experiments/grpo_loop.py`, `experiments/configs/grpo/loop.toml`)

One long-running process. `sampling.concurrency` workers take statements from the statement source and search them
with the new search (`search_theorem`; n = 8, harvesting and ε on, `grpo/search/visible_student_v2.toml` on the
loop's servers at the loop's own budget, `sampling.max_expansions` = 32), one Lean REPL each; every finished tree goes
gzipped to `trees/phase_<k>/` of the phase collecting at that moment, with a line in `trees/index.jsonl`
(`tree_store.py`) holding its `TreeSummary` ("Health checks and budget signals" below). A phase starts once
`min_sampling_minutes` (45) of sampling produced `min_trainable_groups` (300) groups the policy trains on (counted per
finished tree), or after `max_sampling_minutes` (90) with at least one, and runs:

| Stage | What happens |
|---|---|
| pause | every policy and value request waits at the pause gate; searches keep their trees and REPL states in place, and trees finishing now belong to the next phase |
| training | the paused searches' REPL processes stop (`training.paused_repl_memory_gib`, "Host memory" below); the servers on the training GPUs drain and sleep (level 2: weights and KV cache freed, `release_gpu`); `grpo_phase.py --merge-adapters` runs on those GPUs (`SubprocessTrainer`; several GPUs: `torchrun --standalone`, one rank each; log in `training/phase_<k>.log`): labels the phase's trees, trains the policy (two passes) and, every `value_every_phases` (4) with a gate benchmark, the value model on the window of recent phases' trees plus its gate (main rank; "The value model in the loop" below), then merges the new policy adapter and an accepted value adapter into their bases on the GPUs (`<adapter>/../merged`, one rank per adapter); the loop labels the same trees meanwhile for the `search` and `curriculum` metrics |
| publishing | `training_phase.publish_phase`: version k + 1 with the new policy adapter and the new value adapter only if it passed the gate, its weights the job's GPU merges moved into `weights/v<k+1>/` (`merging.merge`; without them, e.g. after a crash, merged on the CPU into `serving.policy_base_model` and `value_base_model`, `MergedPublisher`); sleeping servers wake with it (`restore_gpu`: memory back, `reload_weights` of the new directory, KV cache back), servers off the training GPUs swap in place (`publish_weights`), and the searches' pause gate records the version for the samples to come |
| evaluating | the paused searches' REPL processes stop (`evaluation.paused_repl_memory_gib`, "Host memory" below); due fixed targets run as their own jobs (`grpo_evaluate.py`) while the searches stay paused: by loop hours (`every_hours`), once before the first phase (`at_start`; `baseline_runs` independent runs), or when requested (`grpo_loop.py request-evaluation`); the value servers serve the evaluations' fixed value model meanwhile and the published one again afterwards; the value A/B search runs both its arms here |
| health | the phase's budget and health lines and alerts ("Health checks and budget signals"); the hard stop ends the loop here |
| resume | the searches continue with the new weights |

GPU layout (`loop.toml`): while sampling, each of the four GPUs serves the merged policy (62% of its memory) and the
merged value model (28%), so nothing is left for training; during a phase's pause all four sleep and train
(`training.gpus = [0, 1, 2, 3]`). The fallback, if the data-parallel pause costs more than it saves, is `gpus = [0]`:
GPU 0's servers sleep and one process trains there, the other GPUs' servers stay loaded and idle (every search is
paused either way) and swap to the new weights in place. Policy servers run with `--logprobs-mode processed_logprobs`
(`grpo_loop.py serve-commands` prints every start command); all servers with `SLEEP_MODE=1`.

Data parallelism (`training/data_parallel.py`): every rank plans the same steps (same seeds and data order); a step's
64 sequences are split across the ranks by tokens (`balanced_shards`, costliest first to the least loaded rank) and
each rank plans its own micro-batches; the loss keeps the global normalization, Σ weight · token loss / (sequences in
the step × 256), so the ranks' gradients sum to the single-GPU gradient; the LoRA gradients are summed with one
all-reduce per 256 MiB bucket (`sum_gradients`; no DDP wrapper, a rank without micro-batches adds zeros) before the
clipping, so every rank takes the same optimizer step. The old and reference log-probabilities are scored on each
rank's share of the sequences and gathered on every rank; replay examples are split the same way under the global
token mean. The fp32 output layer per chunk is per rank as before. Metrics are summed over the ranks (peak memory:
the largest); only the main rank writes step records, adapters, merged weights and `phase.json`. The value trainer
splits each step's units (sibling groups with their pairs) the same way, under the step's global weights. The value
gate scores on the main rank while the others wait. With one rank everything is the single-GPU path. A step on two
ranks equals the one-process step (`tests/graph/test_data_parallel_trainers.py`, gloo on the CPU). The LoRA
gradients are fp32 (~0.5 GB for the policy adapter), so each policy step all-reduces about that much over PCIe.

Restart: `loop_state.json` holds the phase, its stage, sampling and training time, whether a value model passed the
gate, the last value adapter trained, whether μ is on and the evaluation clock; `models/current.json` and `versions.jsonl` the published versions; the tree index the
searched statements and per-phase trees. `grpo_loop.py run` after a crash first swaps every server to the current
version, finishes the interrupted stage (training again, publishing only if `current.json` lacks the phase's
version, the remaining evaluations), then resumes sampling. Searches cut off by the crash are lost (the curriculum
feeds each statement once; the fixed list feeds it again). The node's disk is not persistent: back up the run's
`metrics/`, `phases.jsonl`, `evaluations*/summary.json` and `report.md`; trees and the retained adapters ("Disk")
stay on the node.

Jobs: the training and evaluation jobs run in their own process groups, each recorded in `children/<job>.pid` (process
id, start time and a marker) while it runs. Every process of a job carries the marker in its environment
(`LEAN_SEARCH_LOOP_JOB`), which finds the processes outside the group: torchrun starts each worker in a session of its
own. Stopping the loop (SIGTERM from `grpo_loop.sh stop`, or a failure) cancels the stage in flight, which sends
SIGTERM to the job's group and to every process with its marker, SIGKILL to what is left after 30 s, and waits; the
stage reruns after a restart. A job that ends by itself (torchrun killed by the OOM killer, say) gets the same
treatment for whatever it left running. A loop that died without stopping its job (SIGKILL, OOM) leaves the record
behind: the restarted loop refuses to start, before it wakes or swaps any server, while a recorded job or any process
with its marker still runs (the error lists their process ids: `kill -TERM` each, then restart).

Server failures: a search that ends on an HTTP error of a policy or value server says nothing about its statement, so
the statement is fed again (the curriculum's before new ones) up to `sampling.server_failure_retries` times, then
dropped; the worker waits `server_failure_pause_seconds` after each failure. `status` counts the failures
(`server_failures`) and the dropped statements (`statements_given_up`) of the session. The policy client cycles
over every server, so one dead server fails nearly every search: once at least `server_failure_share` (0.5) of the last
`server_failure_window` (20) searches ended on a server failure, the searches pause (one pause at a time, a phase's
included), the servers' health checks run, the ones not answering are stopped and started again on the current
version (`restart_dead_servers`; `loop_services.start_servers`: a GPU's servers one after another, the GPUs in
parallel), and the searches resume. A server still not answering, or a failed start, stops the loop with an error
naming the servers: a stopped loop costs less than GPUs idle until someone looks. If every server answers, the
searches resume without a restart.

Metrics per phase (`MetricsWriter`, `<run>/metrics/`): `status` every `status_seconds`, `curriculum` and `search`
(`phase_metrics.search_phase_record`: graph statistics, failure tiers, forced answers and repetition loops, Lean time
per expansion, block length), `grpo` (from the trainer's `phase.json`), `value` per value retrain with a benchmark
(the gate statistic, both models' benchmark metrics, `ValueDiagnostics`), `timing` (sampling, training, publishing and
evaluation seconds, and the pause's segments, below), `fixed_targets` from the evaluations, `value_ab` from the value
A/B search; `budget` and `health` after each phase's evaluations ("Health checks and budget signals"); `system`
from `dashboard.py record-system`, including host memory (the limit, what is available, the Lean REPLs' private
memory in total and at p90, the vLLM processes' private memory). Failure tiers are a message-based approximation
(`phase_metrics.py`).

The boundaries are protocols (`TreeSearcher`, `PhaseTrainer`, `ModelServers`, `Evaluations`); the tests run the loop
with fakes for them (`tests/rl/loop_fakes.py`) and real Lean for the start-state and renamed searches.

### The value model in the loop

- **Cadence and data**: every `training.value_every_phases` (4) phases the training job trains the value model on the
  trees of the last `value_window_phases` (8) phases (`TrainingRequest.value_trees`, `grpo_phase.py --value-trees`;
  only the main rank reads them, the other phases' records without their texts, `read_tree(texts=False)`, and sends
  the tokenized value data to the other ranks), continuing the last value adapter trained, accepted or not
  (`LoopProgress.value_adapter`; the published one before the first), with 10% v0 replay
  (`training.value_replay = "value/v0/train.jsonl"`: v0's own training data, `phase3_value_data.py --name v0`, the
  exact remaining steps of traced train-split proofs; on the node under `$LEAN_SEARCH_DATA`, restored from the
  backup's `generated_data` archive, `data/value/v0/`). The targets' q comes from the recorded bins
  (`value/README.md`).
- **Gate (a)**: the candidate against the published adapter on the held-out benchmark, by a paired cluster bootstrap
  of the gain in sibling pairs ordered by h (`value/README.md`, "The gate"). Passed: published with the next version.
- **A/B search (b)**: `evaluation.value_ab` (every 12 hours of loop time, or `request-evaluation --target value_ab`;
  only while the published value model is not the reference) searches the first `value_ab_test.problems` (250)
  problems of the probe set (the strata in turn) at the probe's budget with the current policy twice: with the
  reference (`EvaluationValueModel.INITIAL`, value v0) and with the published value model, into
  `evaluations/value_ab_v<version>_{initial,published}/`. The published arm's job pairs the two per problem
  (`evaluation.value_ab_result`: solved counts, the problems one arm solved, this run's two-sided exact McNemar test)
  and pools the problems one arm solved over every A/B of the same published value model (`loop.earlier_value_ab_results`,
  the other `value_ab_v*_published/comparison.json`) for two one-sided exact McNemar tests, "published better" and
  "published worse", into `comparison.json`, the summary and the `value_ab` line. Compared with v0,
  not with the previously published model: v0 is the fixed reference of the evaluations, and successive small steps
  would each be below the A/B's noise while their sum may not be. The reference arm is not reused from a probe of the
  same version because it covers a different set of problems and would tie the A/B to the probe's schedule.
  Under the null (identical arms, the review's simulation of 250 problems with 42-62 discordant ones) one A/B finds
  "better" 4% of the time and "worse" 4%; repeated A/Bs of one model look at the pooled evidence again each time, so
  over six of them about 12% find "better" at some point.
- **μ**: `value_share_after_gate` (0.15) turns on once a value model passed the gate (it is published) and an A/B
  found the published model better than v0 (`value_ab_test.significance`, 0.05, one-sided, pooled); before that every
  phase trains with μ = 0.
- **Revert**: an A/B that finds the published model worse than v0 at that level publishes a new version with the same
  policy and v0's value adapter (`loop.publish_value_model`; trigger "value v<k> worse than v0 in the A/B"), turns μ
  off and lets the next value training continue from v0's adapter. Whether gate (a) or the A/B decides publication
  itself is still open; publication stays with gate (a).
- **Evaluations with a fixed value model**: the probe and miniF2F search with `evaluation.value_model` (default
  `initial`, value v0), so they measure the policy alone; before them the value servers swap to its merged weights
  (`Publisher.kept_value_weights`, merged once under `weights/kept_value/`, which pruning leaves alone; no swap while
  the published value model is v0) and back to the published version's afterwards: every value server, on all GPUs,
  awake again after the phase's publish (a sleeping one would wake with the weights). Before this, the evaluations
  used whatever value model was published. The held-out states use no value model.

## Timing

Each phase's pause is recorded segment by segment (`PauseSegments`: the `timing` line's `pause.*`, `phases.jsonl`, a
`Phase <k> pause:` line in `loop.log`, and the System page's "Pause segments" chart). The loop measures its own
segments; the training job's come from its `phase.json` (`TrainerTimings`, the main rank's clock):

| Segment | Measured by | What |
|---|---|---|
| `drain` | loop | the searches' requests in flight finishing at the pause gate |
| `server_sleep` | loop | the paused searches' REPL processes stopping ("Host memory"), the training GPUs' servers draining and sleeping |
| `trainer_start` | loop | the job's wall time minus its own total: process and rank start, imports, NCCL setup, reading the trees, loading tokenizers, exit |
| `preparation` | job | labelling the trees, building the policy sequences, replay and value data |
| `policy_load` | job | loading the 4B base with the adapter (and torch.compile's wrappers) |
| `compile` | job | one scoring and one training micro-batch on the shortest sequence before scoring, which compile the compiled layers (`compile_warm_up`; 0 without `compile_layers`) |
| `scoring` | job | the old (and, when it differs, the reference's on `reference_sequences`) log-probabilities, sharded |
| `policy_training` | job | the policy steps (both passes, replay included) |
| `value_training` | job | the value model's load, compilation, steps and adapter save |
| `gate` | job | the gate's two benchmark scorings (main rank) |
| `merge` | job | loading each base and merging the new adapters on the GPUs (the slowest rank) |
| `write` | job | writing the policy adapter and the merged weights |
| `publish` | loop | recording the version: moving the job's merges into place (else merging on the CPU) |
| `wake` | loop | the slowest server waking with the new weights (or swapping them in place) |
| `resume` | loop | the slowest server resuming |

The evaluations that follow some phases are timed separately (`evaluation_seconds`). Estimate before the first node
hour: 10-15 minutes per pause on one GPU, of which training compute 4-8 minutes; on four GPUs the compute shrinks
about fourfold while `trainer_start`, the loads, `compile`, `gate`, the merges and the wake do not.

If the pause still costs too much, two levers:

- Longer sampling phases (`min_sampling_minutes`, `min_trainable_groups`): the fixed part of the pause (start, loads,
  compile, gate, merges, wake) is paid per phase, so its share falls with the sampling time, at the price of fewer and
  staler updates per hour.
- A trainer that stays alive between phases (not implemented): the ranks would keep their processes, NCCL group and
  compiled graphs and move the weights to host memory while the servers run, saving `trainer_start`, most of the loads
  and the recompilation (an estimated 1-3 minutes per phase). Its cost is host memory: per rank the 4B policy and 2B
  value bases in bf16, about 9 + 4.5 GB, so about 54 GB for four ranks (or about 14 GB with one shared copy), next to
  the 112 REPLs and eight vLLM processes of "Host memory", plus a CUDA context (~0.5 GB) left on each GPU that the
  servers' memory shares must leave free.

## Health checks and budget signals (`health_checks.py`, `budget_signals.py`, `tree_summary.py`)

Every finished tree gets a `TreeSummary` in the tree index as it finishes (a worker thread labels a solved tree once):
the groups the policy would train on (`trainable_groups`: groups at proof-graph nodes with a policy proof, as
`require_policy_proof` keeps them, and a non-zero advantage, as the trainer keeps them; μ is left out), the expansion
of the first proof, the shortest proof's top-level tactics (the root's remaining steps), the search's expansion budget,
and per policy expansion the distinct blocks (identical blocks run once), distinct sample texts, samples cut off at the
token cap and repetition loops among them. The phase trigger sums `trainable_groups` over the phase's entries, so it
never reads a tree again.

After a phase's evaluations, before the phase closes, the loop writes a `budget` line and a `health` line
(`PhaseHealth`, also appended to `<run>/health.jsonl`, which the next phases read back) and logs every alert to
`loop.log` (`Health of phase <k> (<severity>, <check>): ...`); the dashboard's Training page charts each signal with
its threshold dashed, and its alert list shows the latest phase's alerts. Thresholds are `[health]` in the loop config
(`HealthConfig`); the defaults are first guesses, to be calibrated on the first phases:

| Check | Signal | Default threshold | Reference |
|---|---|---|---|
| `kl_to_starting_policy` | KL (k3, per token) to the starting policy, last pass (`final_kl_to_reference`) | > 0.02 | absolute (version 0's is 0; review F expects 1e-4 to 1e-3 after 5-10 phases at lr 1e-5) |
| `clip_fraction` | clip fraction of the last pass's trained tokens | > 0.1 | absolute (PPO runs usually stay below 0.1-0.2) |
| `distinct_samples` | distinct blocks per policy expansion (of n = 8) | < 0.75 × reference | mean of the first `reference_phases` (2) phases |
| `explanation_length` | mean explanation tokens of the trained samples | outside 0.5-2 × reference | the first phases |
| `cut_off_samples` | share of policy samples cut off at the token cap (repetition loops shown with it) | > max(2 × reference, reference + 0.01) | the first phases |
| `held_out_valid_lean` | share of held-out samples whose block runs completely in Lean | < 0.9 × version 0's (warning); **< 0.7 × version 0's: hard stop** | version 0's held-out evaluation |
| `held_out_success` | held-out per-sample success | < 0.9 × version 0's | version 0's held-out evaluation |
| `search_budget` | share of solves in the budget's last quarter, pooled over the last 3 phases | > 0.10 (a note) | absolute |

The held-out checks run only after phases whose held-out evaluation ran (every 6 hours of loop time with the probe).
Relative thresholds stay unset (no alert) until their reference exists.

**Hard stop and rollback.** When the held-out valid-Lean rate falls below `stop_held_out_valid_fraction` (0.7; 0
never stops) of version 0's, the loop closes the phase, writes `<run>/health_stop.json` (the phase, the version that
collapsed, the last good version, the reason) and stops cleanly; it refuses to start while that file exists. The last
good version is the newest one whose held-out evaluation stayed above the stop threshold (version 0 before any); its
policy adapter is never pruned by the retention ("Disk"). With the loop stopped:

- `python experiments/grpo_loop.py --config <loop.toml> rollback` publishes the last good version's policy adapter
  (`--version N` for another) with the current value adapter as a new version (merged on the CPU, trigger
  `rollback to v<N>`) and keeps the stop beside it as `health_stop_<time>.json`. The next phase continues training
  from that adapter; lower the learning rate (or the passes) in the phase config before restarting, or it may collapse
  again.
- `python experiments/grpo_loop.py --config <loop.toml> clear-health-stop` keeps the current version (a false alarm, or
  a threshold to recalibrate in `[health]`).
- Then `deployment/grpo_loop.sh loop` as after any stop; `status` prints a pending health stop.

**Search budget.** The loop's searches run `sampling.max_expansions` (32) expansions, overriding the shared search
template's 64; the probe (16), miniF2F (64) and the gate search keep their own budgets. A budget that cuts off harder
proofs shows on the Training page as solves crowding into the last quarter (expansions 25-32), a distribution of
expansions to the first proof piling up at the top bucket, proof lengths (shortest proof-graph route, top-level
tactics) that stop growing, and a curriculum difficulty of the solved statements that stops rising. When the pooled
last-quarter share exceeds `max_late_solve_share` (0.10) over `late_solve_phases` (3) phases, the health check notes it
(`search_budget`); raise `[sampling] max_expansions` (e.g. 64) in the loop config and restart the loop (each tree
records its own budget, so the signals stay comparable). In the visible run, expansions 17-64 added 8 of 171 solves.

## Host memory

The node has about 128 GB of RAM (check the cgroup limit, `system.memory_total_gib`). Its users: one Lean REPL per
search (`sampling.concurrency`, 112) whose private memory grows from ~0.25 GiB after the import by ~0.25 MiB per proof
state, restarted at 1 GiB when released and at 2 GiB in any case (`lean/repl.py`; the Mathlib .olean mappings are
shared and not counted); an evaluation job's own pool (`evaluation.<target>.concurrency`, 64) next to the paused
searches; the eight vLLM processes; the training job's ranks (each reads and labels the phase's trees, about 13 MiB
per tree with its texts in a synthetic unsolved-tree test; in a value phase the main rank alone also reads the window
of 8 phases, about 1.4 MiB per tree without texts, and the others only receive its value data; the weights load
straight to the GPUs); and the loop process, which labels the phase's trees for its metrics while the job trains and
merges a published version on the CPU only when the job did not merge it on the GPUs. The budget:

    loop concurrency × p90 REPL memory + evaluation concurrency × p90 REPL memory + vLLM private memory + merge
        + training ranks × rank memory + loop labelling ≤ 0.85 × RAM

Training, merging (publishing) and evaluating never overlap. Before the training job starts the paused searches' REPL
processes above `training.paused_repl_memory_gib` stop, and before evaluating those above
`evaluation.paused_repl_memory_gib` (0 for both, the default: all of them; each restarts on its search's next request
and replays the proof states it needs, `LeanRepl.stop`), so with the defaults three tighter conditions hold instead:

    training:   vLLM + training ranks × rank memory + loop labelling ≤ 0.85 × RAM
    publishing: loop concurrency × p90 + vLLM + merge ≤ 0.85 × RAM
    evaluating: evaluation concurrency × p90 + vLLM ≤ 0.85 × RAM

The terms come from the `system` family (`lean_private_memory_p90_gib`, `vllm_private_memory_gib`; the merge is the
rise of `memory_used_gib` while publishing, the training term its rise while training) and from `loop.log`, which
reports the host memory at each stage boundary of a pause (`Host memory at the pause`, `before training`, `after
training`, `after publishing`, `before the evaluations`: available of the limit, the Lean processes' and vLLM's
private memory). The rank memory is not measured yet: take it from the rise during phase 1 and, since a value phase
reads 8 phases of trees per rank, again during phase 4 (`ps -o rss -p <rank pids>` during the stage). Measure in the
first hour with a probe running and lower `sampling.concurrency` or an evaluation's `concurrency` if a condition
fails; if training does not fit, the ranks' tree loading is what to shrink. Stopping the REPLs before training costs
each paused search a REPL restart and a replay of its proof states after the pause (a large
`training.paused_repl_memory_gib` keeps them).

## Disk

What grows per phase: the phase's gzipped trees (estimated 150-250 MB; kept, the value window and the analysis read
them), the policy adapter (~0.5 GB in fp32) and every fourth phase a value adapter (~0.26 GB). After each publish the
loop deletes the phase adapters (and any GPU merge left beside them) of versions older than the last
`retention.adapter_versions` (5) unless still used: the current version's and the value adapter the next value
training continues, and the health check's last good version's policy adapter, the rollback target
(`retention.py`; 0 keeps every adapter). The starting adapters live outside the loop's
checkpoints and are never touched. Merged weights (`MergedPublisher.prune`): the current version's and version 0's
(the baselines' weights, `weights/v0000/`), the evaluations' fixed value model under `weights/kept_value/`, and while
publishing the next version's beside them. The system sampler records the fullest filesystem of the run and the
checkpoints (`system.disk_total_gib`, `disk_free_gib`, `record-system --disk-path`); the dashboard warns below
`min_free_disk_gib` (50) free.

## Fixed targets (`fixed_sets.py`, `fixed_targets.py`, `evaluation.py`)

- `grpo_fixed_sets.py select` fixes the probe set (167 per stratum) and the value gate's set (134 per stratum):
  verified pool v3 statements the automation does not close, easy (difficulty < 2), medium (< 4) or hard by the
  curriculum's difficulty estimate (the known proof's tactic count until roots are scored), disjoint, in seeded hash
  orders. The loop's curriculum never feeds either (`statements.held_out`).
- `probe`: 16 expansions, no harvesting, no ε, with the fixed `evaluation.value_model` (v0); every 6 hours of loop
  time and before the first phase, inside the loop's pause (GPUs free, the evaluation's own pool of `concurrency`
  REPLs, 64, next to the paused searches, "Host memory" above). The per-problem wall cap (1 hour) is an emergency stop
  only, so that the
  expansions are the budget and the probe does not measure load; the searches it stopped are counted
  (`EvaluationSummary.wall_clock_stops`, `fixed_targets.probe_wall_clock_stops`, likewise for miniF2F) and should be
  zero. Version 0's probe runs twice (`baseline_runs = 2`; the second into `probe_v0000_repeat1/`, the policy samples
  unseeded and ε off, so the runs are independent): `comparison.json` there and the `fixed_targets` line
  (`probe_repeat_difference`, `probe_repeat_discordant`) give the run-to-run noise later versions are judged against.
  `minif2f`: miniF2F-valid at 64 expansions, before the first phase (version 0's baseline) and at milestones. `held_out_states`: per-sample success on the 512 per-step
  evaluation states (`single_step.py`), with the probe. Each writes `evaluations/<target>_v<version>/` (resumable), a
  `fixed_targets` line and `evaluations.jsonl`.
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
states are traced states and are never renamed. With `original_names_for_value` the priority function scores each
state with the original names (`OriginalNamePriority`: the renaming replaces whole identifiers one to one, so the
inverse changes restore them), so a value model trained on numbered names sees what it was trained on; the naming A/B
turns it on for the named arm (value v0), the loop leaves it off because its value model trains on its own renamed
trees.

## Cheap tests

- **Smoke cycle** (`grpo/loop_smoke.toml`, `phase_smoke.toml`; `deployment/README.md`, "GRPO loop" step 3): the loop on
  the overfit statements with short phases, a value phase every phase whose gate every candidate passes, and every
  evaluation at a tiny size (`EvaluationTarget.problems`; `grpo_fixed_sets.py gate-benchmark --problems` for a tiny
  benchmark), so every stage, merge, swap and evaluation runs within the first hour on the node.
- **Single-step GRPO** (`single_step.py`, `experiments/grpo_single_step.py`, `grpo/single_step.toml`): one policy
  request per held-out state, executed from the state rebuilt by replay (`search_theorem(..., start_state=...)`).
  Proof graph: the state's traced proof proves it and every later state of it, so a tactic that closes the goals or
  reaches one of those states (by goal key) is on the proof graph, at the traced proof's remaining steps (the root's
  are the traced proof's, or a found proof's if fewer); other new states are unknown (neutral). The root
  forms a group when a sample reaches the proof graph (states no sample solves train nothing). No extra search per
  state. Success per sample = the block runs completely and ends there (the per-step evaluation's criterion). Each arm (per-tactic, sequence credit) runs 3 rounds of sample, measure
  (training and 512 disjoint states), train (one phase, two passes), then a last measurement; `report` writes both
  curves. States whose goals had inaccessible names are renamed by the search, so their reference keys may not match.
- **Overfit on 300 statements** (`grpo/loop_overfit.toml`): the loop on a fixed list (`grpo_fixed_sets.py
  select-overfit`: 100 per stratum outside the probe and gate), policy only; `grpo_loop.py report` gives the solve
  rate per phase, which must rise.
- **Naming A/B** (`experiments/grpo_naming_ab.py`, `grpo/naming_ab.toml`): the data rewrite's two short fine-tunes on
  the probe (the named arm on renamed statements, its value queries with the original names), the unknown-name error
  rate per policy sample of those searches (`phase_metrics.unknown_names`) and MATH-500
  (`evaluation/reasoning_retention_naming_ab.toml`).
