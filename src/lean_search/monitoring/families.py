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
from lean_search.value.diagnostics import (
    Calibration,
    LabelDistribution,
    LabelDistributions,
    PhaseValueMetrics,
    PredictionDistribution,
)
from lean_search.value.pair_statistics import PairShare, PairStatistic


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
    # This session: value benchmark scorings that failed (retried after the next phase), and finished trees left out
    # because their summary failed.
    value_benchmark_failures: int = 0
    trees_left_out: int = 0
    # This session: evaluations beside sampling that failed or were cut off at a pause (each runs again after it).
    evaluation_failures: int = 0


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
class ArmDifference:
    """The options arm's rate minus the control arm's, and its bootstrap interval over the arms' trees (95%; 99% for
    the balance)."""

    difference: float
    low: float
    high: float


@dataclass(frozen=True)
class ArmBalance:
    """An A/A check of the hash split: the options arm minus the control arm on what the round cannot change, each
    with its 99% interval; a difference outside it means the split or the routing is broken, not a result."""

    mean_difficulty: ArmDifference | None = None
    verified_share: ArmDifference | None = None
    # The root's first round: the share of its judged blocks that ran completely, and its distinct blocks per tree.
    root_valid_rate: ArmDifference | None = None
    root_blocks_per_tree: ArmDifference | None = None
    balanced: bool = True


@dataclass(frozen=True)
class ArmOutcome:
    """A search options A/B arm's trees of a phase (rl/README.md, "Search options A/B")."""

    trees: int
    solved: int
    trainable_groups: int
    generated_tokens: int
    solved_per_thousand_tokens: float
    trainable_groups_per_tree: float
    # Of the trainable groups, those of a node's feedback round.
    feedback_trainable_groups: int = 0
    # Of the generated tokens, those up to each tree's first proof (an unsolved tree's all); the rest harvested.
    generated_tokens_to_first_proof: int = 0
    # Summed over the trees: a search's wall clock (a pause it waited through included), the same without the pauses
    # (active) and its Lean time.
    wall_seconds: float = 0.0
    lean_seconds: float = 0.0
    # Per active tree-hour.
    solved_per_tree_hour: float = 0.0
    # The options arm's against the control arm; None for the control arm.
    solved_per_thousand_tokens_difference: ArmDifference | None = None
    solved_per_tree_hour_difference: ArmDifference | None = None
    active_seconds: float = 0.0
    # Trainable groups with a feedback round's weighted by its samples against a first round's (4 of 8), per 1k
    # generated tokens.
    weighted_trainable_groups: float = 0.0
    trainable_groups_per_thousand_tokens: float = 0.0
    trainable_groups_per_thousand_tokens_difference: ArmDifference | None = None
    # What the hash split leaves alike, per arm: the curriculum's difficulty, the share of verified statements, the
    # root's first-round valid share and distinct blocks per tree; the options arm's balance against the control arm.
    mean_difficulty: float | None = None
    verified_share: float | None = None
    root_valid_rate: float | None = None
    root_blocks_per_tree: float = 0.0
    balance: ArmBalance | None = None


@dataclass(frozen=True)
class RatioInterval:
    """The options arm's rate over the control arm's, with its percentile bootstrap interval."""

    ratio: float
    low: float
    high: float
    confidence: float


class OptionsVerdict(StrEnum):
    CONTINUE = "continue"
    ADOPT = "adopt"
    DROP_HARMFUL = "drop: harmful"
    DROP_FUTILE = "drop: futile"
    DROP_NOT_ADOPTED = "drop: not adopted"


@dataclass(frozen=True)
class OptionsLook:
    """A planned look of the search options A/B (rl/options_ab.py): the trees started in its first `look` phases,
    pooled with a bootstrap stratified by phase and arm."""

    arm: str
    look: int
    phases: tuple[int, ...]
    arm_trees: int
    control_trees: int
    # R: solves per generated token (all tokens), at the look's confidence and at 95%; to the first proof (diagnostic).
    solves_per_token: RatioInterval
    solves_per_token_95: RatioInterval
    solves_per_token_to_first_proof: RatioInterval
    # G: weighted trainable groups per generated token, at 95%; the guard needs its lower bound >= 0.95.
    groups_per_token: RatioInterval
    guard_holds: bool
    verdict: OptionsVerdict


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
    # The probe runs one part of the set per slot, the parts in turn (part = slot % parts); a repeated run's line
    # carries its part and the repeat fields only.
    probe_slot: int | None = None
    probe_part: int | None = None
    # The last `probe_parts` slots together, each part once: the whole set (across their policy versions).
    probe_rolling_solved: int | None = None
    probe_rolling_problems: int | None = None
    probe_rolling_by_difficulty: dict[str, BandOutcome] = field(default_factory=dict)
    # The slot's solve rate minus the mean of version 0's runs of the same part, so the parts' difficulty cancels
    # (no sawtooth across the parts), and that difference averaged over the last `probe_parts` slots.
    probe_baseline_difference: float | None = None
    probe_rolling_baseline_difference: float | None = None
    # A repeated run against the first run of the version: solved, difference, problems solved by one only.
    probe_repeat_solved: int | None = None
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
class ValueTraining:
    """One value retrain, published with the next version: what it trained on."""

    family: ClassVar[str] = "value_training"
    value_version: int
    # Trees of the training window.
    trees: int
    training_loss: float | None = None
    # The window's targets per bin by source (smoothed as trained) and the v0 replay.
    labels: LabelDistributions | None = None
    replay_labels: LabelDistribution | None = None


@dataclass(frozen=True)
class ValueBenchmarkTrend:
    """The value benchmark scored fresh through the value servers by a newly served value model, against v0 and
    against the value model served before it: a trend, never a decision."""

    family: ClassVar[str] = "value_benchmark"
    value_version: int
    # Labelled sibling pairs whose proof-graph child gets the lower h (ties half).
    pairs: PairShare
    reference_value_version: int | None
    previous_value_version: int | None
    # This model's share minus the other's, with a paired cluster bootstrap interval over problems.
    against_reference: PairStatistic | None
    against_previous: PairStatistic | None
    # AUC, Brier, ECE, pair accuracy by p_dead, Spearman and MAE of the steps.
    metrics: BenchmarkMetrics
    predictions: PredictionDistribution
    calibration: Calibration
    scoring_seconds: float = 0.0


@dataclass(frozen=True)
class ValuePhase:
    """Free per phase: μ in effect, and the serving value model against the phase's own labelled search graphs."""

    family: ClassVar[str] = "value_phase"
    value_share: float
    metrics: PhaseValueMetrics


@dataclass(frozen=True)
class PairedDifference:
    """Solve rates of the published value model's runs minus v0's on the same problems, paired per problem."""

    runs: int
    problems: int
    only_reference: int
    only_published: int
    # (only_published - only_reference) / problems, and its exact interval given the discordant problems.
    difference: float | None
    lower: float | None
    upper: float | None
    # One-sided exact McNemar tests.
    worse_p_value: float
    better_p_value: float


@dataclass(frozen=True)
class ValueArmResult:
    """A probe slot's part searched again with the published value model, paired with the slot's run with v0."""

    family: ClassVar[str] = "value_arm"
    slot: int
    part: int
    reference_value_version: int
    published_value_version: int
    reference_solved: int
    published_solved: int
    this_slot: PairedDifference
    # Pooled with the earlier value arms of the same published value model, and of every value model.
    same_value_version: PairedDifference
    all_value_versions: PairedDifference
    # Worse than v0 at the configured level, pooled over the same value model: an alert, no automatic action.
    worse: bool


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
    # The trees fed from the band and from below it (`below_band_share`).
    by_origin: dict[str, BandOutcome] = field(default_factory=dict)


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
    # The training job as a whole (model loading, policy and value training, the merges).
    training_seconds: float
    publishing_seconds: float
    evaluation_seconds: float
    # Trees the phase trained on and the searches its pause held in place.
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
    # The search options A/B's arms (`sampling.options_arm`); empty with it off.
    by_search_arm: dict[str, ArmOutcome] = field(default_factory=dict)
    # The A/B's planned look due at this phase's check, if any.
    options_look: OptionsLook | None = None


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
    # Of the phase's distinct policy blocks Lean judged (infrastructure failures left out), those that ran completely:
    # the held-out states' valid-Lean criterion on the training trees, free every phase.
    valid_block_rate: float | None = None
    # The reward hacking of phases 1-10 (`tree_summary.BlockHabits`, first-round samples with a block): the share
    # opening with a bare `have h : A`, of those leaving the claim open in their child the share whose claim got
    # proved, the share with closed-form filler (`0 < (1:ℝ)`), and the median explanation characters before the fence.
    bare_have_share: float | None = None
    claim_proved_rate: float | None = None
    closed_form_filler_share: float | None = None
    median_explanation_characters: float | None = None
    # Of the same samples: the shares opening with `have … :=` (a claim with its proof) and with linarith or
    # nlinarith; the mean tactics of a block run completely; of the tactics reaching a proof-graph state with goals
    # left, the share a further tactic of their block follows (the continue rate).
    proof_have_share: float | None = None
    linarith_opening_share: float | None = None
    valid_block_tactics: float | None = None
    continue_rate: float | None = None
    # The warned habits on the statements the curriculum fed from below its band (`TreeSummary.below_band`), nearer
    # the reference phases' difficulty; None without such statements.
    below_band_bare_have_share: float | None = None
    below_band_claim_proved_rate: float | None = None
    below_band_median_explanation_characters: float | None = None


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
    # Below this the held-out valid Lean collapsed: a rollback, or the loop stops.
    stop_held_out_valid_rate: float | None = None
    min_held_out_success: float | None = None
    min_valid_block_rate: float | None = None
    max_bare_have_share: float | None = None
    min_claim_proved_rate: float | None = None
    min_explanation_characters: float | None = None


class HealthCheck(StrEnum):
    KL_TO_STARTING_POLICY = "kl_to_starting_policy"
    CLIP_FRACTION = "clip_fraction"
    DISTINCT_SAMPLES = "distinct_samples"
    EXPLANATION_LENGTH = "explanation_length"
    CUT_OFF_SAMPLES = "cut_off_samples"
    HELD_OUT_VALID_LEAN = "held_out_valid_lean"
    HELD_OUT_SUCCESS = "held_out_success"
    SEARCH_BUDGET = "search_budget"
    VALID_BLOCKS = "valid_blocks"
    BARE_HAVES = "bare_haves"
    CLAIMS_PROVED = "claims_proved"
    EXPLANATION_CHARACTERS = "explanation_characters"


class HealthSeverity(StrEnum):
    # The held-out valid Lean collapsed: the loop rolled back or stopped after the phase.
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
    # The held-out valid Lean collapsed within `rollback_window_phases` of a rollback (or with rollbacks off): the loop
    # stopped after this phase.
    hard_stop: bool = False
    # The newest version whose held-out evaluation raised no held-out alert (0 before any): the rollback target.
    last_good_version: int = 0
    # The held-out valid Lean collapsed: this version's policy was published again and the searches continued.
    rolled_back_to: int | None = None


FAMILIES = (
    LoopStatus,
    SystemUsage,
    FixedTargets,
    GrpoPhase,
    ValueTraining,
    ValueBenchmarkTrend,
    ValuePhase,
    ValueArmResult,
    SearchPhase,
    CurriculumPhase,
    PhaseTiming,
    BudgetPhase,
    PhaseHealth,
)
