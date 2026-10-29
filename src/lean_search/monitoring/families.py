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
    # Per sample on the held-out states: the block runs completely in Lean.
    held_out_valid_rate: float | None = None
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
    # The training job outside its own parts: process and rank start, imports, reading the trees, exit.
    trainer_start_seconds: float = 0.0
    # Labelling the trees and building the policy and value data.
    preparation_seconds: float = 0.0
    policy_load_seconds: float = 0.0
    compile_seconds: float = 0.0
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


@dataclass(frozen=True)
class BudgetPhase:
    """How the phase's searches used their expansion budget and what they solved (rl/budget_signals.py): a budget too
    small for the harder proofs shows as solves crowding into its last quarter."""

    family: ClassVar[str] = "budget"
    trees: int
    solved_trees: int
    # Groups the policy trains on, the phase trigger's count.
    trainable_groups: int
    # The searches' expansion budget (the largest, should it have changed within the phase).
    expansion_budget: int
    # Solved trees whose first proof came in the last quarter of their budget (expansions 25-32 of 32), and their share
    # of the solved trees with a known first-proof expansion.
    late_solves: int
    late_solve_share: float | None
    # That share pooled over the last `recent_phases` phases, this one included, and its alert threshold.
    recent_late_solve_share: float | None
    recent_phases: int
    max_late_solve_share: float
    # Solved trees by the expansion of their first proof ("25-32": 25 to 32), and the mean.
    expansions_to_solve: dict[str, int] = field(default_factory=dict)
    mean_expansions_to_solve: float | None = None
    # Solved trees by the top-level tactics of their shortest proof on the proof graph, and the mean.
    proof_steps: dict[str, int] = field(default_factory=dict)
    mean_proof_steps: float | None = None
    # The curriculum's difficulty estimate of the solved statements, and of every searched one.
    mean_difficulty_solved: float | None = None
    median_difficulty_solved: float | None = None
    p90_difficulty_solved: float | None = None
    mean_difficulty_searched: float | None = None


@dataclass(frozen=True)
class HealthMeasurements:
    """A phase's training-stability signals (rl/health_checks.py); None when not measured in this phase."""

    # KL (k3, per token) of the trained policy to the starting policy and the clip fraction, both of the last pass.
    kl_to_starting_policy: float | None = None
    clip_fraction: float | None = None
    # Per policy expansion of the phase's searches (n = 8 samples): distinct blocks (identical ones run once), and
    # distinct sample texts.
    distinct_samples_per_expansion: float | None = None
    distinct_texts_per_expansion: float | None = None
    # Explanation tokens of the trained samples.
    mean_explanation_tokens: float | None = None
    # Policy samples cut off at the token cap (their answer forced), and those repeating their own text.
    cut_off_share: float | None = None
    repetition_loop_share: float | None = None
    # The held-out states, when evaluated after this phase: samples whose block runs completely in Lean, and that
    # succeed.
    held_out_valid_rate: float | None = None
    held_out_success: float | None = None


@dataclass(frozen=True)
class HealthThresholds:
    """The limits a phase was judged against; the relative ones are None until their reference exists (version 0's
    held-out evaluation, the mean of the first phases)."""

    max_kl_to_starting_policy: float
    max_clip_fraction: float
    min_distinct_samples_per_expansion: float | None = None
    min_explanation_tokens: float | None = None
    max_explanation_tokens: float | None = None
    max_cut_off_share: float | None = None
    min_held_out_valid_rate: float | None = None
    # Below this the loop stops after the phase.
    stop_held_out_valid_rate: float | None = None
    min_held_out_success: float | None = None


class HealthCheck(StrEnum):
    KL_TO_STARTING_POLICY = "kl_to_starting_policy"
    CLIP_FRACTION = "clip_fraction"
    DISTINCT_SAMPLES = "distinct_samples"
    EXPLANATION_LENGTH = "explanation_length"
    CUT_OFF_SAMPLES = "cut_off_samples"
    HELD_OUT_VALID_LEAN = "held_out_valid_lean"
    HELD_OUT_SUCCESS = "held_out_success"
    SEARCH_BUDGET = "search_budget"


class HealthSeverity(StrEnum):
    # The loop stopped after the phase.
    STOP = "stop"
    WARNING = "warning"
    # A suggestion, e.g. a larger search budget.
    NOTE = "note"


@dataclass(frozen=True)
class HealthAlert:
    check: HealthCheck
    severity: HealthSeverity
    title: str
    detail: str


@dataclass(frozen=True)
class PhaseHealth:
    """A phase's health checks: what was measured, the limits, the alerts (also in loop.log) and the rollback target."""

    family: ClassVar[str] = "health"
    phase: int
    # The version the phase published.
    policy_version: int
    measured: HealthMeasurements
    thresholds: HealthThresholds
    alerts: tuple[HealthAlert, ...] = ()
    # The held-out valid-Lean rate fell below its stop threshold: the loop stopped after this phase.
    hard_stop: bool = False
    # The newest version whose held-out evaluation stayed above the stop threshold (0 before any): the rollback target.
    last_good_version: int = 0


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
    BudgetPhase,
    PhaseHealth,
)
