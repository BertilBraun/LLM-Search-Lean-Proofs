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
| off graph | μ · q (`value_share`, 0 until set by hand, "The value model in the loop"; q averages the state's expanded descendants, else its own estimate) | 0 | 0 while μ = 0 |
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
else scored with its weights loaded in the trained adapter's place (they share rank and scale, asserted), the trained
weights put back before the first step (`policy_trainer.reference_weights_in_place`). Loading it as a second adapter
added modules, which made a resident model's compiled layers recompile (2 graphs) in every phase.

After each stage (labelling, policy, value, merge) the job runs the garbage collector and empties the CUDA cache
(`training_phase.released_memory`): `module.compile()` stores a compiled wrapper of the module's own call on it, so a
compiled layer refers to itself and only the cyclic collector frees a stage's model, which would otherwise stay on the
GPU through the value training and the merges. `PhaseOutcome.memory` records the allocated and reserved GPU
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
| training | the paused searches' REPL processes stop (`training.paused_repl_memory_gib`, "Host memory" below); the servers on the training GPUs drain and sleep (level 2: weights and KV cache freed, `release_gpu`); the training job trains on those GPUs: with `training.persistent` the loop's persistent job (`PersistentTrainer`, "Persistent trainer" below; log in `training/trainer.log`), else `grpo_phase.py --merge-adapters` for this phase alone (`SubprocessTrainer`; several GPUs: `torchrun --standalone`, one rank each; log in `training/phase_<k>.log`). It labels the phase's trees (the persistent job: what was not labelled while sampling), trains the policy (two passes, with the μ of `value_share.json`) and, every `value_every_phases` (2), the value model on the window of recent phases' trees ("The value model in the loop" below), then merges the new adapters into their bases on the main rank's GPU, one after the other (transformers writes checkpoint weights only on distributed rank 0; a merge without a weights file is an assertion): to `<adapter>/../merged` on disk, or the persistent job's into host memory; the loop labels the same trees meanwhile for the `search`, `curriculum` and `value_phase` metrics (awaited only before the phase closes) |
| publishing | version k + 1 with the new policy adapter and, in a value phase, the new value adapter (no gate). With the persistent job's merges in host memory (`loop.handed_off_version`): sleeping servers wake with them (`restore_gpu`: memory back, `reload_weights` of the directory, KV cache back), servers off the training GPUs swap in place (`publish_weights`), the searches resume unless evaluations are due, and only then `training_phase.publish_phase` copies the merges to `weights/v<k+1>/` (a temporary directory renamed once complete, `MergedPublisher`) and records the version, prunes, and clears host memory (`GrpoLoop.record_durably`). Otherwise `publish_phase` first (and host memory cleared once recorded, also by a restart that finds the version already recorded), the job's GPU merges moved into `weights/v<k+1>/` (`merging.merge`; without them, e.g. after a crash, merged on the CPU into `serving.policy_base_model` and `value_base_model`), then the servers wake or swap with it. Either way the searches' pause gate records the served version for the samples to come |
| evaluating | the paused searches' REPL processes stop (`evaluation.paused_repl_memory_gib`, "Host memory" below); due fixed targets run as their own jobs (`grpo_evaluate.py`) while the searches stay paused: by loop hours (`every_hours`), once before the first phase (`at_start`; `baseline_runs` independent runs), or when requested (`grpo_loop.py request-evaluation`); the value servers serve the evaluations' fixed value model meanwhile and the published one again afterwards; the probe runs its next slot (one part of the set), the held-out states with it, and, at the first slot after a new value model was published, that slot's value arm with it ("Fixed targets" below) |
| health | the phase's budget and health lines and alerts ("Health checks and budget signals"), after the version is recorded (with the persistent job the searches may already run); a held-out collapse publishes the last good version's policy again and continues, a second one within 4 phases stops the loop here |
| resume | the searches continue with the new weights; a value model served for the first time scores the value benchmark through the value servers meanwhile ("The value model in the loop"), which the next pause waits for; it starts once the version is recorded |

GPU layout (`loop.toml`): while sampling, each of the four GPUs serves the merged policy (62% of its memory) and the
merged value model (28%), so nothing is left for training; during a phase's pause all four sleep and train
(`training.gpus = [0, 1, 2, 3]`). The fallback, if the data-parallel pause costs more than it saves, is `gpus = [0]`:
GPU 0's servers sleep and one process trains there, the other GPUs' servers stay loaded and idle (every search is
paused either way) and swap to the new weights in place. Policy servers run with `--logprobs-mode processed_logprobs`
(`grpo_loop.py serve-commands` prints every start command); all servers with `SLEEP_MODE=1`. The persistent training
job (`training.persistent = true` in `loop.toml`, "Persistent trainer" below) stays on the training GPUs between
phases with its models parked in host memory, holding a CUDA context and NCCL's buffers (~0.5-1 GiB) on each, which
the servers' shares leave free.

Data parallelism (`training/data_parallel.py`): every rank plans the same steps (same seeds and data order); a step's
64 sequences are split across the ranks by tokens (`balanced_shards`, costliest first to the least loaded rank) and
each rank plans its own micro-batches; the loss keeps the global normalization, Σ weight · token loss / (sequences in
the step × 256), so the ranks' gradients sum to the single-GPU gradient; the LoRA gradients are summed with one
all-reduce per 256 MiB bucket (`sum_gradients`; no DDP wrapper, a rank without micro-batches adds zeros) before the
clipping, so every rank takes the same optimizer step. The old and reference log-probabilities are scored on each
rank's share of the sequences and gathered on every rank; replay examples are split the same way under the global
token mean. The fp32 output layer per chunk is per rank as before. Metrics are summed over the ranks (peak memory:
the largest); only the main rank writes step records, adapters, merged weights and `phase.json`. The value trainer
splits each step's units (sibling groups with their pairs) the same way, under the step's global weights. With one
rank everything is the single-GPU path. A step on two ranks equals the one-process step
(`tests/graph/test_data_parallel_trainers.py`, gloo on the CPU). The LoRA gradients are fp32 (~0.5 GB for the policy adapter), so each policy step all-reduces about that much over PCIe.

Restart: `loop_state.json` holds the phase, its stage, sampling and training time, the last value adapter trained, the μ
of the last phase that trained, the evaluation clock and the next probe slot; `models/current.json` and `versions.jsonl`
the published versions; the tree index the searched statements and per-phase trees. `grpo_loop.py run` after a crash
first swaps every server to the current version, finishes the interrupted stage (training again, publishing only if
`current.json` lacks the phase's version, the remaining evaluations), then resumes sampling. A crash after the servers
loaded the persistent job's merges from host memory but before the version was recorded leaves `current.json` at version
k and the stage at publishing: the restart serves version k from disk (pruning only follows a record, so its weights
exist), then serves version k + 1 from host memory again and records it once on disk, or, when host memory is gone (a
reboot), merges it on the CPU first. At every start the loop clears merges in host memory that no restart will serve
(all of them unless the interrupted phase's version awaits its record; then only partly written ones). Searches cut off
by the crash are lost (the curriculum feeds each statement once; the fixed list feeds it again). The node's disk is not
persistent: back up the run's `metrics/`, `phases.jsonl`, `evaluations*/summary.json` and `report.md`; trees and the
retained adapters ("Disk") stay on the node.

Jobs: the training and evaluation jobs run in their own process groups, each recorded in `children/<job>.pid` (process
id, start time and a marker) while it runs. Every process of a job carries the marker in its environment
(`LEAN_SEARCH_LOOP_JOB`), which finds the processes outside the group: torchrun starts each worker in a session of its
own. Stopping the loop (SIGTERM from `grpo_loop.sh stop`, or a failure) cancels the stage in flight, which sends SIGTERM
to the job's group and to every process with its marker, SIGKILL to what is left after 30 s, and waits; the stage reruns
after a restart. A job that ends by itself (torchrun killed by the OOM killer, say) gets the same treatment for whatever
it left running. A loop that died without stopping its job (SIGKILL, OOM) leaves the record behind: the restarted loop
refuses to start, before it wakes or swaps any server, while a recorded job or any process with its marker still runs
(the error lists their process ids: `kill -TERM` each, then restart). The persistent training job is such a job,
recorded in `children/persistent/` so that evaluation jobs start beside it; between commands its ranks also stop by
themselves within a second once the loop's process is gone (its id and start time are their arguments); during a command
(a `train`, minutes, or a first `prepare`'s model building) they finish it first, so a loop SIGKILLed then leaves them
holding the GPUs until it ends, and the restarted loop refuses to start until they are gone. A persistent job that ends
by itself is started again at the loop's next command; during a phase the loop logs it, starts it again and trains the
phase once more, and a second death fails the phase like a failed per-phase job.

Server failures: a search that ends on an HTTP error of a policy or value server says nothing about its statement, so
the statement is fed again (the curriculum's before new ones) up to `sampling.server_failure_retries` times, then
dropped; the worker waits `server_failure_pause_seconds` after each failure. `status` counts the failures
(`server_failures`) and the dropped statements (`statements_given_up`) of the session. The policy client cycles
over every server, so one dead server fails nearly every search: once at least `server_failure_share` (0.5) of the last
`server_failure_window` (20) searches ended on a server failure, the searches pause (one pause at a time, a phase's
included), the servers' health checks run, the ones not answering are stopped and started again on the current
version (`restart_dead_servers`; `loop_services.start_servers`: a GPU's servers one after another, the GPUs in
parallel), and the searches resume. The check takes the pause lock, so it never overlaps a phase's pause: a persistent
job is parked then and holds only its CUDA context and NCCL buffers on each GPU, which the restarted servers' memory
shares leave room for (0.62 + 0.28 of 24 GiB leave ~2.4 GiB). A server still not answering, or a failed start, stops the loop with an error
naming the servers: a stopped loop costs less than GPUs idle until someone looks. If every server answers, the
searches resume without a restart.

Metrics per phase (`MetricsWriter`, `<run>/metrics/`): `status` every `status_seconds`, `curriculum` and `search`
(`phase_metrics.search_phase_record`: graph statistics, failure tiers, forced answers and repetition loops, Lean time
per expansion, block length), `value_phase` (μ in effect and `diagnostics.PhaseValueMetrics` of the phase's trees),
`grpo` (from the trainer's `phase.json`), `value_training` per value retrain (window trees, loss, its label
distributions), `value_benchmark` per served value model (`value_trends.benchmark_trend`), `timing` (sampling,
training, publishing and evaluation seconds, and the pause's segments, below), `fixed_targets` from the evaluations,
`value_arm` from the value arms; `budget` and `health` after each phase's evaluations ("Health checks and budget
signals"); `system`
from `dashboard.py record-system`, including host memory (the limit, what is available, the Lean REPLs' private
memory in total and at p90, the vLLM processes' private memory). Failure tiers are a message-based approximation
(`phase_metrics.py`).

The boundaries are protocols (`TreeSearcher`, `PhaseTrainer`, `ModelServers`, `Evaluations`); the tests run the loop
with fakes for them (`tests/rl/loop_fakes.py`) and real Lean for the start-state and renamed searches.

### The value model in the loop

- **Cadence and data**: every `training.value_every_phases` (2) phases the training job trains the value model on the
  trees of the last `value_window_phases` (4) phases (with 45-90-minute phases: a retrain every 1.5-3 h on 3-6 h of
  trees, decided 2026-10-29 after review G; the old 4 and 8 were chosen for 15-30-minute phases)
  (`TrainingRequest.value_trees`, `grpo_phase.py --value-trees`; only the main rank reads them, the other phases'
  records without their texts, `read_tree(texts=False)`, and sends the tokenized value data to the other ranks),
  continuing the last value adapter trained, which is the published one (`LoopProgress.value_adapter`; v0's before the
  first), with 10% v0 replay (`training.value_replay = "value/v0/train.jsonl"`: v0's own training data,
  `phase3_value_data.py --name v0`, the exact remaining steps of traced train-split proofs; on the node under
  `$LEAN_SEARCH_DATA`, restored from the backup's `generated_data` archive, `data/value/v0/`). The targets' q comes from
  the recorded bins (`value/README.md`).
- **No gate** (owner decision 2026-10-29): every value model trained is published with the next version and the
  searches use it; nothing in the loop decides on value statistics. The two former gates are trends instead:
- **Benchmark trend** (`value_trends.py`, `evaluation.value_benchmark`): when the value servers serve a value version
  for the first time (at the start, and after each publish once the searches resumed), the loop scores the benchmark
  through them (`loop_services.ServedValueScorer`: `value/benchmark_scoring.score_benchmark` on the search template's
  `[value]`, the search's own top-20 read of the bins) while the searches run, keeps the scores under
  `value_benchmark/scores_v<value version>.json.gz` and writes a `value_benchmark` line: the share of labelled sibling
  pairs ordered by h (`value/pair_statistics.py`), its difference to v0's and to the previous scored value version's
  with a paired cluster bootstrap over problems, the benchmark metrics (AUC, Brier, pair accuracy by kind, Spearman and
  MAE of the steps), the predicted distributions and the calibration on expanded states. The next phase's pause and any
  evaluation wait for a scoring in flight (they change what the value servers serve). It is a trend only: any error of
  the scoring or of the trend is logged as an `Alert:` with its traceback (the `status` line counts them, the dashboard
  warns), never stops the loop, and the version is scored again after the next phase; the scores are kept only once the
  trend exists. A few thousand prefill-only states: well under a minute of value server time per retrain, outside the
  training pause (the old gate scored both models in the job).
- **Value arm** (`evaluation.value_arm`, `evaluation.value_arm_result`): exactly once per published value model other
  than v0 (`enabled`; the evaluations' fixed model is v0), at the first probe slot after it was published
  (`LoopProgress.value_arm_version`), the slot's part is searched again with the published value model and the same
  policy version (`--value-arm`, `probe_slot<k>_v<version>_value_arm/`) and paired per problem with the slot's run: the
  paired solve-rate difference with McNemar's exact interval (Clopper-Pearson on the problems one arm solved,
  conditional on their number; `confidence` 0.95), and one-sided exact McNemar p-values, for the slot and pooled over
  the earlier value arms of the same published value model and of every one (`loop.earlier_value_arm_results`). When the
  published model is worse than v0 at `significance` (0.05), pooled over its own value arms, `loop.log` gets an `Alert:`
  line and the dashboard a warning until a newer value model is published; nothing else happens. Compared with v0, not
  with the previous model: v0 is the fixed reference of the evaluations.
- **μ** is a manual switch starting at 0: `grpo_loop.py set-value-share 0.15` (`deployment/grpo_loop.sh value-share`)
  writes `value_share.json` in the run directory (`loop.set_value_share`, 0 ≤ μ ≤ 1), and the loop reads it each time
  a phase starts training (`loop.read_value_share`), so it applies from the next phase to train; 0 turns it off. The
  μ in effect is logged when it changes, is part of the phase's training log line, the `value_phase` line and
  `phases.jsonl`.
- **Per-phase value metrics** (`diagnostics.phase_value_metrics`, free): from the phase's labelled trees and the bins
  the serving value model recorded, read with A*'s readout (the search template's `[value.readout]`): the targets'
  label distribution per bin by source and tree outcome (exact steps unsmoothed) next to the recorded predictions of
  the same states and of the never-expanded frontier (mean per bin, p_dead per tenth, expected steps given alive), the
  calibration on expanded states (ECE, Brier, reliability bins) and the remaining-steps MAE and Spearman on proof-graph
  states (exact steps: the shortest route to a proof, independent of the order the search found it in).
- **Evaluations with a fixed value model**: the probe and miniF2F search with `evaluation.value_model` (default
  `initial`, value v0), so they measure the policy alone; before them the value servers swap to its merged weights
  (`Publisher.kept_value_weights`, merged once under `weights/kept_value/`, which pruning leaves alone; no swap while
  the published value model is v0) and back to the published version's afterwards: every value server, on all GPUs,
  awake again after the phase's publish (a sleeping one would wake with the weights). Before this, the evaluations
  used whatever value model was published. The held-out states use no value model.

## Timing

Each phase's pause is recorded segment by segment (`PauseSegments`: the `timing` line's `pause.*`, `phases.jsonl`, a
`Phase <k> pause:` line in `loop.log`, and the System page's "Pause segments" chart). The loop measures its own
segments; the training job's come from its `phase.json` (`TrainerTimings`, the main rank's clock unless noted):

| Segment | Measured by | What |
|---|---|---|
| `drain` | loop | the searches' requests in flight finishing at the pause gate |
| `server_sleep` | loop | the paused searches' REPL processes stopping ("Host memory"), the training GPUs' servers draining and sleeping |
| `trainer_start` | loop | the job's wall time minus its own total: process and rank start, imports, NCCL setup, reading the trees, loading tokenizers, exit. The persistent job: waiting for it to start and its model building within this phase, both once per job (0 in later phases; a job started at the first `prepare` builds its models while the searches run) |
| `preparation` | job | labelling the trees, building the policy sequences, replay and value data. The persistent job: the trees its main rank had not prepared while sampling, the sequences sent to the other ranks, and in a value phase the window's trees not yet labelled |
| `policy_load` | job | loading the 4B base with the adapter (and torch.compile's wrappers). The persistent job: unparking the policy and loading the adapter to continue |
| `compile` | job | one scoring and one training micro-batch on the shortest sequence before scoring, which compile the compiled layers (`compile_warm_up`; 0 without `compile_layers`). The persistent job compiles in its first phase only; `phase.json`'s `compiled_graphs` counts the graphs compiled per phase, 0 after the first |
| `unpark` | job | the persistent job moving its models from host memory onto the GPUs, every time (the slowest rank; also part of `policy_load`, `value_training` and `merge`) |
| `scoring` | job | the old (and, when it differs, the reference's on `reference_sequences`) log-probabilities, sharded |
| `policy_training` | job | the policy steps (both passes, replay included) |
| `value_training` | job | the value model's load (the persistent job: unpark), compilation, steps and adapter save |
| `merge` | job | loading each base (the persistent job: unparking it) and merging the new adapters on the main rank's GPU |
| `write` | job | writing the policy adapter and, per-phase job, the merged weights |
| `park` | job | the persistent job dropping its models' GPU copies and moving the LoRA weights to the CPU (the slowest rank) |
| `handoff` | job | the persistent job writing the merged weights to host memory for the servers (the main rank) |
| `publish` | loop | recording the version: moving the job's merges into place (else merging on the CPU); about 0 with merges in host memory, recorded later |
| `wake` | loop | the slowest server waking with the new weights (or swapping them in place) |
| `resume` | loop | the slowest server resuming |
| `durable_write` | loop | not part of the pause: the merges from host memory copied to disk and the version recorded, while the searches run |

The evaluations that follow some phases are timed separately (`evaluation_seconds`). Estimate before the first node
hour, per-phase job: 10-15 minutes per pause on one GPU, of which training compute 4-8 minutes; on four GPUs the
compute shrinks about fourfold while `trainer_start`, the loads, `compile`, the merges and the wake do not (an
estimated 5-8 minutes of fixed part with the GPUs mostly idle). The persistent trainer, below, cuts the fixed part to
an estimated 1-2 minutes.

### Persistent trainer (`training.persistent`, `loop_services.PersistentTrainer`, `resident_trainer.py`)

Decided 2026-10-29: keep four-GPU data-parallel training with the searches paused, but pay the trainer's start once.
`experiments/grpo_trainer.py` runs for the whole loop (one process, or `torchrun` with a rank per training GPU) and
takes the loop's commands through files (`trainer_channel.py`, under `training/trainer/`: the loop writes
`command.json`, numbered from 1 per job, each a temporary file renamed into place; every rank polls it every 0.5 s and
runs each newer command; the main rank writes `ready.json` once the ranks are up and `reply.json` with the command's
number once `phase.json` is written). Between commands no collective waits, so the NCCL timeout never binds.

- **Models** (`training/resident.py`): built once per job, at the first command that needs them, on the CPU and the
  ranks in turn (one transient copy at a time). The main rank writes the frozen tensors (base weights and buffers) of
  each model to one file under `training.host_directory` / loop name / `parked/` (a tmpfs) and every rank maps it shared
  (`torch.from_file(shared=True)`): one copy for all ranks, ~9.4 GB policy and ~4.5 GB value. Parking points a rank's
  frozen tensors at the mapping and moves its LoRA weights to the CPU, which leaves only the CUDA context and NCCL's
  buffers on the GPU; unparking copies them back (pageable host memory, a few seconds for 9.4 GB). The value model is
  resident too: one more 4.5 GB in the same file system, no GPU memory while parked. The module objects stay, so the
  compiled layers keep their graphs: packing keeps the shapes, the adapter to continue is loaded into the existing LoRA
  parameters, and the KL reference's weights are swapped in place rather than added as a second adapter (which
  recompiled 2 graphs per phase; `test_resident_trainer.py` checks 18 graphs in the first phase on the CPU, 0 in the
  second and third). The base never changes: merges happen in the unparked GPU copy, which parking drops.
- **Preparation while sampling**: the loop sends `prepare` with the phase's config as sampling starts (`GrpoLoop` at the
  session start and after each phase). Every rank builds the models the phase needs (so the first job's model building
  runs next to the searches); the main rank starts a thread that reads and labels the phase's trees as they arrive,
  every 30 s, one tree at a time into its policy sequences (`training_phase.prepare_policy_tree`; the record itself is
  not kept). The thread runs on the last `BACKGROUND_CPUS` (32) logical CPUs at nice 19, as `deployment/background.sh`
  pins CPU-heavy work, so with the Lean REPLs it never takes more than one of their cores. At the pause `train` finishes
  what is left and sends the sequences to the other ranks (`broadcast_from_main`); they no longer read the trees. In a
  value phase a second thread labels the value model's window the same way (`WindowPreparation`: the finished phases'
  trees at once, the collecting phase's as they arrive, read without texts, `label_value_trees`), so the pause only
  labels the last trees: an estimated 2-5 GiB on the main rank while that phase samples (4 phases of 300-900 trees at
  ~1.4 MiB), which the ~240 GiB node holds beside the 112 REPLs.
- **Training**: as the per-phase job, through the same trainers with the resident model as their loader (`train_grpo`,
  `train_graph_value_model`, `load=`); each model is parked after its stage. A phase with resident models trains
  bit-identical adapters to a fresh per-phase job on the CPU (`test_resident_trainer.py`, policy over two phases and a
  value phase).
- **Handoff**: the new policy adapter and, in a value phase, the new value adapter are merged on the main rank, one
  after the other (transformers' `save_pretrained` writes checkpoint weights only on distributed rank 0; a value merge
  on rank 1 left a directory with its marker and no weights, `tests/graph/test_merges_on_ranks.py`), in the unparked
  copy (`peft` `merge_adapter`, the same arithmetic as `merge_and_unload`; equal tensors on the CPU) and written as a
  servable checkpoint to `handoff/<hash of the adapter path>/` in host memory (a temporary directory renamed with its
  marker inside, `adapters.write_premerged`), then the models are parked. The servers load that directory with the
  existing in-place path (`reload_weights` from a directory: on the old node ~20 s from disk, now from the page cache);
  vLLM needs no extension. CUDA IPC or an NCCL broadcast into the vLLM workers would save the tmpfs write and the file
  parsing but needs a vLLM worker extension that cannot be tested off the node.
- **Durability**: the loop serves version k + 1 from host memory, resumes the searches (unless evaluations are due:
  they need the version recorded and wait for it), then copies the merges to `weights/v<k+1>/` through the
  publisher's temporary directory and rename, records the version (`versions.jsonl`, then `current.json`), prunes old
  weights and adapters, and clears host memory. A version is never recorded before its files exist; the previous
  version's weights are pruned only after the record. Trees found meanwhile record the served version
  (`GrpoLoop.served_version`). A crash in between is the restart case of "The loop" above.
- **Failure**: the job's ranks stop on the loop's `stop`, or by themselves between commands once the loop's process is
  gone. A `train` that gets no answer in time (`training.first_train_timeout_minutes`, 45, for a job's first phase with
  its model building and compilation; later `train_timeout_factor` (2) times the median of the earlier phases of the
  same kind, value phase or not, at least `train_timeout_minimum_minutes`, 15; all below the collectives' 1-hour
  timeout) stops the job, which then counts as died. Closing the loop removes the parked weights from host memory. A job
  that died is started again at the next command (`loop.log`: "Persistent trainer ended ...", "starting it again"); one
  that dies during `train` is started again and the phase trained once more, a second death fails the phase. `persistent
  = false` (and `gpus = [0]`) keep the per-phase job; the publish then records first and serves from disk as before.

Expected fixed part per non-value phase on 4x RTX 3090 (estimates; measure on the smoke cycle): `drain` and
`server_sleep` a few seconds each; `trainer_start` 0; `preparation` 5-20 s (the last 30 s of trees and the broadcast);
`policy_load` 3-6 s (unpark 9.4 GB, adapter); `compile` 1-3 s (the warm-up with cached graphs); `park` ~1 s per model;
`merge` ~5 s (unpark on rank 0, merge); `handoff` 5-15 s (9.4 GB to tmpfs); `write` 1-2 s; `publish` ~0; `wake` 5-10 s
(reload from the page cache); `resume` <1 s: about 1 minute, against 5-8 minutes with the per-phase job. Value phases
add the window's last trees (labelled during sampling), the value unpark and the value merge after the policy's on the
main rank (~10 s). Once per job: the start and model building (~1-2 minutes, overlapping sampling when it starts at a
`prepare`) and the first `compile` (1-2 minutes). After the pause, `durable_write` copies ~9.4 GB (14 GB in a value
phase) to disk in the background (~0.5-1.5 minutes).

If the pause still costs too much: longer sampling phases (`min_sampling_minutes`, `min_trainable_groups`), whose fixed
part is paid per phase, at the price of fewer and staler updates per hour.

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
| `kl_to_starting_policy` | KL (k3, per token) to the starting policy, last pass (`final_kl_to_reference`) | > 0.5 | absolute (version 0's is 0; the single-step test at lr 3e-5 measured 0.03-0.08 after 76 steps, and the KL grows phase by phase, so 0.5 flags a policy far from its start) |
| `clip_fraction` | clip fraction of the last pass's trained tokens | > 0.1 | absolute (PPO runs usually stay below 0.1-0.2) |
| `distinct_samples` | distinct blocks per policy expansion (of n = 8) | < 0.75 × reference | mean of the first `reference_phases` (2) phases |
| `explanation_length` | mean explanation tokens of the trained samples | outside 0.5-2 × reference | the first phases |
| `cut_off_samples` | share of policy samples cut off at the token cap (repetition loops shown with it) | > max(2 × reference, reference + 0.01) | the first phases |
| `valid_blocks` | share of the phase's distinct policy blocks Lean judged that ran completely (`TreeSummary.valid_blocks`, free) | < 0.85 × reference: the held-out states run at the next pause | the first phases |
| `held_out_valid_lean` | share of held-out samples whose block runs completely in Lean | < 0.9 × version 0's (warning); **< 0.7 × version 0's: a collapse** (rollback, below) | version 0's held-out evaluation |
| `held_out_success` | held-out per-sample success | < 0.9 × version 0's | version 0's held-out evaluation |
| `search_budget` | share of solves in the budget's last quarter, pooled over the last 3 phases | > 0.10 (a note) | absolute |

The held-out checks run after phases whose held-out evaluation ran: with every probe slot (every 2 hours of loop time),
and at the next pause after a `valid_blocks` warning. They judge the version the phase published, so a restart judges
the phase alike. Relative thresholds stay unset (no alert) until their reference exists; with the held-out states on a
schedule and the hard stop on, the loop refuses to start without version 0's held-out evaluation (or with one without
valid samples), since the stop could never fire.

**Rollback and hard stop** (decided 2026-10-29 after review G). When the held-out valid-Lean rate falls below
`stop_held_out_valid_fraction` (0.7; 0 never acts) of version 0's, the loop publishes the last good version's policy
adapter again as a new version (`health_checks.publish_rollback`, trigger `rollback to v<N> after phase <k>`, merged on
the CPU, the current value model kept), serves it and keeps sampling; the next phase trains on from it. `loop.log` gets
an `Alert:` line, the health line `rolled_back_to`, and the dashboard warns for the rest of the run. A second collapse
within `rollback_window_phases` (4) phases of that rollback (or any collapse with 0) closes the phase, writes
`<run>/health_stop.json` (the phase, the version that collapsed, the last good version, the reason) and stops the loop
cleanly; it refuses to start while that file exists. The last good version is the newest one whose held-out evaluation
raised no held-out alert, neither warning nor collapse (version 0 before any); the policy adapters of the last
`retention.healthy_versions` (3) such versions are never pruned ("Disk"). With the loop stopped:

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

The node has about 240 GiB of RAM (check the cgroup limit, `system.memory_total_gib`). Its users: one Lean REPL per
search (`sampling.concurrency`, 112) whose private memory grows from ~0.25 GiB after the import by ~0.25 MiB per proof
state, restarted at 1 GiB when released and at 2 GiB in any case (`lean/repl.py`; the Mathlib .olean mappings are shared
and not counted); an evaluation job's own pool (`evaluation.<target>.concurrency`, 112) once the paused searches' REPLs
stopped; the eight vLLM processes; the training job's ranks (per-phase job: each reads and labels the phase's trees,
about 13 MiB per tree with its texts in a synthetic unsolved-tree test; persistent job: only the main rank, one tree at
a time while sampling, keeping the policy sequences, which every rank then holds during training; in a value phase the
main rank alone also holds the labelled window of 4 phases while that phase samples, about 1.4 MiB per tree without
texts, and the others only receive its value data; the per-phase job's weights load straight to the GPUs); the
persistent job's host directory (a tmpfs: the parked bases, one shared copy of ~14 GB for all ranks, and the merges
handed to the servers, up to ~14 GB from the handoff until written to disk); and the loop process, which labels the
phase's trees for its metrics while the job trains and merges a published version on the CPU only when the job did not
merge it. The budget:

    loop concurrency × p90 REPL memory + evaluation concurrency × p90 REPL memory + vLLM private memory + merge
        + training ranks × rank memory + loop labelling + parked + handoff ≤ 0.85 × RAM

Training, merging (publishing) and evaluating never overlap. Before the training job starts the paused searches' REPL
processes above `training.paused_repl_memory_gib` stop, and before evaluating those above
`evaluation.paused_repl_memory_gib` (0 for both, the default: all of them; each restarts on its search's next request
and replays the proof states it needs, `LeanRepl.stop`), so with the defaults tighter conditions hold instead
(`host_memory.budget_conditions`; parked and handoff are 0 without the persistent job):

    sampling:   loop concurrency × p90 + vLLM + parked + handoff ≤ 0.85 × RAM
    training:   vLLM + training ranks × rank memory + loop labelling + parked + handoff ≤ 0.85 × RAM
    publishing: loop concurrency × p90 + vLLM + merge + parked + handoff ≤ 0.85 × RAM
    evaluating: evaluation concurrency × p90 + vLLM + parked ≤ 0.85 × RAM

The sampling condition carries the handoff because the searches resume while the merges are written to disk (about a
minute; their REPLs restart one by one, so the REPL term is low then). With 112 REPLs at a p90 of 0.5 GiB and ~25 GiB of
vLLM: 56 + 25 + 14 + 14 = 109 GiB at the moment of the handoff, 95 GiB otherwise, against 0.85 × 240 = 204 GiB; an
evaluation at 112 REPLs needs 56 + 25 + 14 = 95 GiB (at a p90 of 1 GiB, 151 GiB); one copy of the parked weights per
rank (54 GB) is no longer needed either. The loop process itself (not a budget term so far) now also holds the value
benchmark it scores through the value servers and the tree summaries; its scoring starts only once the version is
recorded and host memory cleared, so it never overlaps the handoff. Measure the loop's resident memory once (`ps -o rss
-p <loop pid>`) and count it in the sampling condition if it is more than a few GiB. The terms come from the `system`
family (`lean_private_memory_p90_gib`, `vllm_private_memory_gib`; the merge is the rise of `memory_used_gib` while
publishing, the training term its rise while training) and from `loop.log`, which reports the host memory at each stage
boundary of a pause (`Host memory at the pause`, `before training`, `after training`, `after publishing`, `before the
evaluations`, and at the sampling condition's peak: `after the early resume, the handoff not yet on disk` and `after the
durable write, before clearing the handoff`: available of the limit, the Lean processes' and vLLM's private memory, the
persistent job's parked and handed-off GiB, and the four conditions on these measurements, `OVER` where one fails; the
rank and merge terms count 0 there). Before every wake it also logs each training GPU's free memory beside its servers'
shares (`GPU memory before the wake`: a parked rank's CUDA context and NCCL buffers, or a stray process, show as the
difference). The rank memory is not measured yet: take it from the rise during phase 1 and, since a value phase holds 4
phases of labelled trees on the main rank, again during phase 2 (`ps -o rss -p <rank pids>` during the stage). Measure
in the first hour with a probe running and lower `sampling.concurrency` or an evaluation's `concurrency` if a condition
fails; if training does not fit, the ranks' tree loading is what to shrink. Stopping the REPLs before training costs
each paused search a REPL restart and a replay of its proof states after the pause (a large
`training.paused_repl_memory_gib` keeps them).

## Disk

What grows per phase: the phase's gzipped trees (estimated 150-250 MB; kept, the value window and the analysis read
them), the policy adapter (~0.5 GB in fp32) and every second phase a value adapter (~0.26 GB). After each publish the
loop deletes the phase adapters (and any GPU merge left beside them) of versions older than the last
`retention.adapter_versions` (5) unless still used: the current version's and the value adapter the next value training
continues, and the policy adapters of the last good version and of the last `healthy_versions` (3) versions whose
held-out evaluation raised no alert, the rollback targets (`retention.py`; 0 keeps every adapter). The starting adapters
live outside the loop's checkpoints and are never touched. Merged weights (`MergedPublisher.prune`): the current
version's and version 0's (the baselines' weights, `weights/v0000/`), the evaluations' fixed value model under
`weights/kept_value/`, and while publishing the next version's beside them. The persistent job's merges wait in host
memory (`handoff/`) until copied there, and the version's record clears them. The system sampler records the fullest
filesystem of the run and the checkpoints (`system.disk_total_gib`, `disk_free_gib`, `record-system --disk-path`); the
dashboard warns below `min_free_disk_gib` (50) free.

## Fixed targets (`fixed_sets.py`, `fixed_targets.py`, `evaluation.py`)

- `grpo_fixed_sets.py select` fixes the probe set (167 per stratum) and the gate set (134 per stratum, the value
  benchmark's problems):
  verified pool v3 statements the automation does not close, easy (difficulty < 2), medium (< 4) or hard by the
  curriculum's difficulty estimate (the known proof's tactic count until roots are scored), disjoint, in seeded hash
  orders. The loop's curriculum never feeds either (`statements.held_out`).
- `probe`: 16 expansions, no harvesting, no ε, with the fixed `evaluation.value_model` (v0), in slots: slot k searches
  part k % `probe_parts` (3) of the set (`fixed_targets.probe_part`: every third problem of each stratum, so each part
  is stratified like the set; `EvaluationRun.slot`, `probe_slot<k>_v<version>/`), every 2 hours of loop time
  (`every_hours`), inside the loop's pause (GPUs free, the evaluation's own pool of `concurrency` REPLs, 112, once the
  paused searches' REPLs stopped, "Host memory" above), so the whole set every ~6 hours. The slot's `fixed_targets` line
  carries its part's solve rate per stratum and, once the last `probe_parts` slots exist, their sum (`probe_rolling_*`,
  `evaluation.rolling_probe`: the whole set, each problem once, across their policy versions). The parts differ in
  difficulty by about the run-to-run noise (review G simulated an offset SD of 2.3 points against 2.0 of noise), so the
  trend is the slot's solve rate minus the mean of version 0's two runs of the same part (`probe_baseline_difference`,
  `loop.probe_baseline_differences`) and that difference averaged over the last `probe_parts` slots
  (`probe_rolling_baseline_difference`); the Evaluations page charts both above the raw rates.
  `LoopProgress.probe_slots` numbers the slots across restarts; a requested probe runs the next slot, and
  `grpo_evaluate.py --target probe` without `--slot` the whole set. The per-problem wall cap (1 hour) is an emergency
  stop only, so that the expansions are the budget and the probe does not measure load; the searches it stopped are
  counted (`EvaluationSummary.wall_clock_stops`, `fixed_targets.probe_wall_clock_stops`, likewise for miniF2F) and
  should be zero. Version 0's probe runs every part twice before the first phase (`baseline_runs = 2`; the second into
  `..._repeat1/`, the policy samples unseeded and ε off, so the runs are independent): `comparison.json` there and the
  repeat's `fixed_targets` line (`probe_repeat_difference`, `probe_repeat_discordant`, per part, kept out of the slot
  series) give the run-to-run noise later versions are judged against; `loop.log` sums the parts.
- `minif2f`: miniF2F-valid at 64 expansions, before the first phase (version 0's baseline) and at milestones.
  `held_out_states`: per-sample success and valid Lean on the 512 per-step evaluation states (`single_step.py`), with
  every probe slot (every 2 hours, a few minutes at 112 REPLs): the hard stop's signal. Each writes
  `evaluations/<target>_v<version>/` (resumable), a `fixed_targets` line and `evaluations.jsonl`.
- `grpo_fixed_sets.py gate-benchmark` searches the gate set once with the starting policy and no value model
  (`grpo/gate_search.toml`, log-probability best-first) and builds the value benchmark from those trees
  (`value/benchmark.py`), the loop's `evaluation.value_benchmark.path`.

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
  the overfit statements with short phases, a value phase every phase (published, then scoring the loop's benchmark),
  every evaluation at a tiny size (`EvaluationTarget.problems`), the held-out states after every phase, and a value arm per published value model, so at every slot,
  so every stage, merge, swap and evaluation runs within the first hour on the node.
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
