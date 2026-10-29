"""Configuration of the search-tree GRPO loop (experiments/grpo_loop.py), loaded from TOML."""

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.loop_config import InitialModels, ServerEndpoint, ServingConfig
from lean_search.rl.renaming import RenamingConfig
from lean_search.search.records import from_json_object


class StatementSourceKind(StrEnum):
    # Pool v3 statements with a verified known proof, by a difficulty band that follows the solve rate.
    CURRICULUM = "curriculum"
    # A fixed list searched over and over (the overfit test).
    FIXED = "fixed"


@dataclass(frozen=True)
class StatementsConfig:
    kind: StatementSourceKind = StatementSourceKind.CURRICULUM
    curriculum: CurriculumConfig = field(default_factory=CurriculumConfig)
    # FIXED: a fixed-set file (grpo_fixed_sets.py format) under $LEAN_SEARCH_DATA.
    fixed: str = ""
    # Fixed-set files under $LEAN_SEARCH_DATA whose statements the curriculum never feeds (probe and value gate sets).
    held_out: tuple[str, ...] = ("grpo/fixed_sets/probe.jsonl", "grpo/fixed_sets/gate.jsonl")


@dataclass(frozen=True)
class SamplingConfig:
    # The run config template of every search (budgets, harvesting, ε); its server URLs come from [serving].
    search_config: str
    # Concurrent searches, each holding a Lean REPL; most wait on the GPUs, so this may exceed the core count.
    concurrency: int = 112
    status_seconds: float = 30.0


@dataclass(frozen=True)
class LoopTrainingConfig:
    # A training phase template (experiments/grpo_phase.py); the loop fills in the adapters, μ and the seed.
    phase_config: str
    # The GPU that trains; servers on it sleep while a phase trains, servers on the others pause in place.
    gpu: int = 0
    # A phase starts once `min_sampling_minutes` of sampling produced `min_solved_trees` solved trees, or after
    # `max_sampling_minutes` with at least one.
    min_sampling_minutes: float = 15.0
    max_sampling_minutes: float = 30.0
    min_solved_trees: int = 100
    check_seconds: float = 30.0
    # The value model trains every this many phases (0 never); it is published only if it passes the gate.
    value_every_phases: int = 1
    # μ in the policy reward and the value targets once a value model passed the gate (0 before).
    value_share_after_gate: float = 0.15
    # The gate's benchmark (grpo_fixed_sets.py gate-benchmark) under $LEAN_SEARCH_RUNS; without it the value model
    # does not train, since nothing could accept it.
    value_benchmark: str = ""
    # Replay files under $LEAN_SEARCH_DATA (grpo_phase.py --lean-replay, --math-replay, --value-replay); empty: none.
    lean_replay: str = ""
    math_replay: str = ""
    value_replay: str = ""
    # Command prefix of the training job, e.g. "nice -n 5"; the job runs with CUDA_VISIBLE_DEVICES=gpu.
    command_prefix: str = ""


@dataclass(frozen=True)
class EvaluationTarget:
    max_expansions: int
    # Per problem; a backstop next to the expansion budget.
    max_wall_seconds: float
    # Lean REPLs of the evaluation's own pool (the paused searches keep theirs).
    concurrency: int
    # Hours of loop time (sampling and training, evaluations excluded) between runs; 0: only when requested.
    every_hours: float = 0.0
    # Run once before the first phase (the baseline of version 0).
    at_start: bool = False


@dataclass(frozen=True)
class EvaluationConfig:
    # The probe set: ~500 held-out pool statements stratified by difficulty, at a small budget.
    probe: EvaluationTarget = field(
        default_factory=lambda: EvaluationTarget(16, 600.0, 96, every_hours=6.0, at_start=True)
    )
    # miniF2F-valid at the full budget, at milestones (grpo_loop.py request-evaluation) and at the start and end.
    minif2f: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(64, 7200.0, 120))
    # Per-sample success on the held-out states (one policy request per state, no search).
    held_out_states: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(1, 600.0, 64))
    # Under $LEAN_SEARCH_DATA: the probe set, and the states (a phase5 run's states.jsonl, under $LEAN_SEARCH_RUNS).
    probe_set: str = "grpo/fixed_sets/probe.jsonl"
    held_out_states_file: str = "phase5_eval_visible_student_v2_visible/states.jsonl"
    command_prefix: str = ""


@dataclass(frozen=True)
class GrpoLoopConfig:
    # The run directory $LEAN_SEARCH_RUNS/<name>; checkpoints under $LEAN_SEARCH_CHECKPOINTS/<name>_phase_<k>.
    name: str
    # The policy adapter on serving.policy_base_model ("" serves the base itself), the value adapter on the value base.
    initial: InitialModels
    serving: ServingConfig
    sampling: SamplingConfig
    training: LoopTrainingConfig
    statements: StatementsConfig = field(default_factory=StatementsConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    # Descriptive hypothesis names at search time (loop, probe, miniF2F), for a policy trained on named data.
    renaming: RenamingConfig = field(default_factory=RenamingConfig)

    def released_servers(self) -> tuple[ServerEndpoint, ...]:
        """Servers on the training GPU: asleep while a phase trains."""
        return tuple(server for server in self.serving.servers if server.gpu == self.training.gpu)


def parse_loop_config(text: str) -> GrpoLoopConfig:
    config = from_json_object(GrpoLoopConfig, tomllib.loads(text))
    if not config.serving.policy_servers:
        raise ValueError("The loop needs at least one policy server.")
    if all(server.gpu == config.training.gpu for server in config.serving.policy_servers):
        raise ValueError("Every policy server is on the training GPU: nothing would sample while a phase trains.")
    if config.statements.kind == StatementSourceKind.FIXED and not config.statements.fixed:
        raise ValueError('statements.kind = "fixed" needs statements.fixed.')
    training = config.training
    if not 0 < training.min_sampling_minutes <= training.max_sampling_minutes or training.min_solved_trees < 1:
        raise ValueError("training needs 0 < min_sampling_minutes <= max_sampling_minutes and min_solved_trees >= 1.")
    return config


def load_loop_config(path: Path) -> GrpoLoopConfig:
    return parse_loop_config(path.read_text(encoding="utf-8"))
