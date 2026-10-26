"""The metric families of the RL loop: one dataclass per family, written by `MetricsWriter` to `<family>.jsonl`.

A new metric is a new field (optional with a default, so older lines still read) or a new dataclass with its own
`family`. The dashboard charts every numeric field, nested dataclasses and dicts flattened to dotted names.
"""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

from lean_search.rl.tree_statistics import GraphStatistics
from lean_search.value.benchmark import BenchmarkMetrics


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


@dataclass(frozen=True)
class GrpoPhase:
    family: ClassVar[str] = "grpo"
    groups: int
    group_samples: int
    mixed_reward_group_share: float
    mean_local_reward: float
    mean_global_reward: float
    # Share of the positive local reward earned on states off the proof graph.
    off_proof_graph_local_reward_share: float
    kl_to_behaviour_policy: float
    clip_fraction: float
    mean_explanation_tokens: float
    mean_block_tactics: float
    policy_loss: float
    trained_tokens: int
    training_seconds: float


@dataclass(frozen=True)
class ValueBenchmarkResult:
    family: ClassVar[str] = "value"
    candidate_version: int
    # Beat the published value model on the benchmark, hence published.
    gate_passed: bool
    benchmark: BenchmarkMetrics
    # The decisive A/B search: policy fixed, only the value model swapped.
    ab_problems: int | None = None
    ab_solved_candidate: int | None = None
    ab_solved_current: int | None = None
    training_loss: float | None = None


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
class BandOutcome:
    attempts: int
    solved: int


@dataclass(frozen=True)
class CurriculumPhase:
    family: ClassVar[str] = "curriculum"
    band_low: float
    band_high: float
    pool_statements: int
    verified_statements: int
    by_difficulty: dict[str, BandOutcome] = field(default_factory=dict)
    by_stage: dict[str, BandOutcome] = field(default_factory=dict)


FAMILIES = (LoopStatus, SystemUsage, FixedTargets, GrpoPhase, ValueBenchmarkResult, SearchPhase, CurriculumPhase)
