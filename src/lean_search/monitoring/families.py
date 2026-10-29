"""The metric families of the RL loop: one dataclass per family, written by `MetricsWriter` to `<family>.jsonl`.

A new metric is a new field (optional with a default, so older lines still read) or a new dataclass with its own
`family`. The dashboard charts every numeric field, nested dataclasses and dicts flattened to dotted names.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

from lean_search.rl.policy_data import SamplerAgreement, SignedRatios
from lean_search.rl.tree_statistics import GraphStatistics
from lean_search.search.tactic_labels import TacticLabelCounts
from lean_search.value.benchmark import BenchmarkMetrics
from lean_search.value.diagnostics import ValueDiagnostics
from lean_search.value.gate_statistics import GateStatistic


class LoopState(StrEnum):
    SEARCHING = "searching"
    TRAINING = "training"
    PUBLISHING = "publishing"
    EVALUATING = "evaluating"
    PAUSED = "paused"
    STOPPED = "stopped"


@dataclass(frozen=True)
class LoopStatus:
    family: ClassVar[str] = "status"
    state: LoopState
    heartbeat_seconds: float
    searches_running: int
    statements_attempted: int
    statements_solved: int
    proofs: int
    proofs_per_hour: float
    statements_per_hour: float
    last_publish_time: float | None
    # Searches a server failed this session, and statements dropped after repeated failures.
    server_failures: int = 0
    statements_given_up: int = 0


@dataclass(frozen=True)
class SystemUsage:
    family: ClassVar[str] = "system"
    gpu_utilization: tuple[float, ...]
    gpu_memory_used_gib: tuple[float, ...]
    gpu_memory_total_gib: tuple[float, ...]
    gpu_power_watts: tuple[float, ...]
    cpu_cores_used: float
    cpu_cores_available: float
    # CPU time of the Lean REPL processes, in cores.
    lean_cores_used: float
    cpu_throttled_fraction: float
    memory_used_gib: float
    hourly_price: float
    cost_so_far: float
    # The limit (cgroup, else host) and what is left; private memory of all Lean REPLs and of vLLM (rl/README.md).
    memory_total_gib: float = 0.0
    memory_available_gib: float = 0.0
    lean_processes: int = 0
    lean_private_memory_gib: float = 0.0
    lean_private_memory_p90_gib: float = 0.0
    vllm_private_memory_gib: float = 0.0
    # The fullest filesystem of the sampled paths (the run directory and the checkpoints).
    disk_total_gib: float = 0.0
    disk_free_gib: float = 0.0


@dataclass(frozen=True)
class BandOutcome:
    attempts: int
    solved: int


@dataclass(frozen=True)
class FixedTargets:
    family: ClassVar[str] = "fixed_targets"
    minif2f_valid_solved: int | None = None
    minif2f_valid_problems: int | None = None
    expansion_budget: int | None = None
    # Per-sample success on the held-out states.
    held_out_success: float | None = None
    held_out_states: int | None = None
    math500_visible: float | None = None
    math500_thinking: float | None = None
    # The probe set (held-out pool statements, stratified by difficulty) at its small budget.
    probe_solved: int | None = None
    probe_problems: int | None = None
    probe_expansion_budget: int | None = None
    probe_by_difficulty: dict[str, BandOutcome] = field(default_factory=dict)
    # Problems whose search stopped on the wall-clock cap rather than the expansion budget.
    probe_wall_clock_stops: int | None = None
    minif2f_wall_clock_stops: int | None = None
    # A repeated run against the first run of the version: solved difference, problems solved by one only.
    probe_repeat_difference: int | None = None
    probe_repeat_discordant: int | None = None
    # Wall time of the evaluation this line reports.
    evaluation_seconds: float | None = None


@dataclass(frozen=True)
class GrpoPhase:
    family: ClassVar[str] = "grpo"
    # Groups at proof-graph nodes and their policy samples.
    groups: int
    group_samples: int
    # Groups with a non-zero advantage (the trained ones), as a share of all groups.
    mixed_reward_group_share: float
    # Means of λ · L and (1 − λ) · G plus the progress over the known tactics.
    mean_local_reward: float
    mean_global_reward: float
    kl_to_behaviour_policy: float
    clip_fraction: float
    mean_explanation_tokens: float
    # Executed tactics per sample.
    mean_block_tactics: float
    policy_loss: float
    trained_tokens: int
    # Scoring and training.
    training_seconds: float
    groups_trained: int = 0
    sequences: int = 0
    # Tactics of the trained groups' samples by credit label.
    tactics: TacticLabelCounts = field(default_factory=TacticLabelCounts)
    # Of the summed |tactic advantage|, the share from the local term.
    local_advantage_share: float = 0.0
    # The trainer's log-probabilities before the first update minus vLLM's recorded ones: mean, mean absolute, k3 KL.
    sampler_log_probability_difference: float = 0.0
    sampler_absolute_log_probability_difference: float = 0.0
    sampler_kl: float = 0.0
    # The same by sampling age: the version trained from minus the version that sampled ("0": current data).
    sampler_by_age: dict[str, SamplerAgreement] = field(default_factory=dict)
    # Ratio to the phase-start policy and clip fraction of the positive- and negative-advantage tokens, by pass ("1",
    # "2"): the earliest sign of whether the update goes the right way.
    ratios_by_pass: dict[str, SignedRatios] = field(default_factory=dict)
    # Samples whose answer was forced at the token cap, trained with the inserted text masked.
    forced_answers_kept: int = 0
    # Sequences from records without token ids, tokenized again.
    retokenized_sequences: int = 0
    # The searches that produced the phase's data; with training_seconds it decides one or two passes.
    sampling_seconds: float | None = None


@dataclass(frozen=True)
class ValueBenchmarkResult:
    """One value retrain: the gate against the published model, diagnostics, and what it trained on and predicts."""

    family: ClassVar[str] = "value"
    candidate_version: int
    # Ordered labelled siblings by h better than the published value model beyond the bootstrap's noise: published.
    gate_passed: bool
    # The candidate's benchmark metrics: diagnostics, not pass criteria.
    benchmark: BenchmarkMetrics
    training_loss: float | None = None
    gate: GateStatistic | None = None
    published_benchmark: BenchmarkMetrics | None = None
    # Trees of the training window.
    trees: int | None = None
    diagnostics: ValueDiagnostics | None = None


@dataclass(frozen=True)
class ValueAbResult:
    """The value A/B search: one policy version with the reference value model (v0) and the published one."""

    family: ClassVar[str] = "value_ab"
    problems: int
    reference_solved: int
    published_solved: int
    # Problems only one arm solved in this run: the paired test's evidence.
    only_reference: int
    only_published: int
    # Exact McNemar test on this run's, two-sided.
    p_value: float
    # One-sided exact McNemar tests, pooled over every A/B of this published value model: worse, better.
    worse_p_value: float
    # Better than the reference at the configured level (pooled): μ may turn on.
    passed: bool
    reference_value_version: int
    published_value_version: int
    better_p_value: float = 1.0
    # Worse than the reference at that level (pooled): the loop publishes the reference value model again.
    worse: bool = False
    # The A/B runs pooled, this one included, and their problems solved by one arm only.
    pooled_runs: int = 1
    pooled_only_reference: int = 0
    pooled_only_published: int = 0


@dataclass(frozen=True)
class FailureTiers:
    malformed: int = 0
    invalid_in_state: int = 0
    valid_but_failing: int = 0
    timeout: int = 0


@dataclass(frozen=True)
class SearchPhase:
    family: ClassVar[str] = "search"
    # `total_statistics` over the phase's labelled searches.
    graph: GraphStatistics
    failure_tiers: FailureTiers
    expansions: int
    lean_seconds: float
    lean_seconds_per_expansion: float
    # Answers forced at the token cap, and those of them that repeat their own text.
    forced_answers: int
    repetition_loops: int
    mean_block_tactics: float


@dataclass(frozen=True)
class CurriculumPhase:
    family: ClassVar[str] = "curriculum"
    band_low: float
    band_high: float
    pool_statements: int
    verified_statements: int
    by_difficulty: dict[str, BandOutcome] = field(default_factory=dict)
    by_stage: dict[str, BandOutcome] = field(default_factory=dict)


@dataclass(frozen=True)
class PauseSegments:
    """A phase's pause before its evaluations, segment by segment, in wall seconds (rl/README.md, "Timing")."""

    # The searches' requests in flight finishing at the pause gate.
    drain_seconds: float = 0.0
    # The servers on the training GPUs draining and sleeping (freeing their memory).
    server_sleep_seconds: float = 0.0
    # The training job outside its own parts: process and rank start, imports, reading the trees, exit. The
    # persistent job's start and model building, once per job: 0 in a pause it was already running for.
    trainer_start_seconds: float = 0.0
    # Labelling the trees and building the policy and value data (the persistent job: what was left at the pause).
    preparation_seconds: float = 0.0
    # Loading the policy (the persistent job: unparking it and loading the adapter to continue).
    policy_load_seconds: float = 0.0
    # Compiling the compiled layers: every phase in the per-phase job, once per persistent job.
    compile_seconds: float = 0.0
    # The persistent job moving its models onto the GPUs (part of the policy load, the value training and the merge)
    # and back into host memory, every time, the slowest rank.
    unpark_seconds: float = 0.0
    park_seconds: float = 0.0
    # The persistent job writing the merged weights to host memory for the servers, the slowest rank.
    handoff_seconds: float = 0.0
    # Old and reference log-probabilities.
    scoring_seconds: float = 0.0
    policy_training_seconds: float = 0.0
    # Loading, compiling, training and saving the value model.
    value_training_seconds: float = 0.0
    gate_seconds: float = 0.0
    # Merging the new adapters into their bases on the GPUs, and writing them (and the policy adapter).
    merge_seconds: float = 0.0
    write_seconds: float = 0.0
    # Recording the version (taking over the GPU merges, else merging on the CPU).
    publish_seconds: float = 0.0
    # The slowest server waking (or swapping in place) with the new weights, then resuming.
    wake_seconds: float = 0.0
    resume_seconds: float = 0.0
    # Not part of the pause: weights the servers loaded from host memory written to disk and the version recorded,
    # while the searches already ran again.
    durable_write_seconds: float = 0.0


@dataclass(frozen=True)
class PhaseTiming:
    """Where a phase's wall time went: sampling between pauses, then the pause's training, publish and evaluations."""

    family: ClassVar[str] = "timing"
    sampling_seconds: float
    # The training job as a whole (model loading, policy and value training, the value gate).
    training_seconds: float
    publishing_seconds: float
    evaluation_seconds: float
    # Trees the phase trained on and the searches still paused in place.
    trees: int
    searches_paused: int
    pause: PauseSegments = field(default_factory=PauseSegments)


FAMILIES = (
    LoopStatus,
    SystemUsage,
    FixedTargets,
    GrpoPhase,
    ValueBenchmarkResult,
    ValueAbResult,
    SearchPhase,
    CurriculumPhase,
    PhaseTiming,
)
