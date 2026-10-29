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
    # A search a server failed feeds its statement again up to this many times, each after the pause.
    server_failure_retries: int = 3
    server_failure_pause_seconds: float = 5.0
    # Once at least this share of the last `server_failure_window` searches ended on a server failure, the searches
    # pause and the servers are checked: dead ones are restarted (if `restart_dead_servers`), and the loop stops with
    # an error when any stays down.
    server_failure_window: int = 20
    server_failure_share: float = 0.5
    restart_dead_servers: bool = True


@dataclass(frozen=True)
class LoopTrainingConfig:
    # A training phase template (experiments/grpo_phase.py); the loop fills in the adapters, μ and the seed.
    phase_config: str
    # The GPUs that train, data-parallel (torchrun, one rank each) when several; servers on them sleep while a phase
    # trains, servers on the others stay loaded and idle (every search is paused).
    gpus: tuple[int, ...] = (0,)
    # A phase starts once `min_sampling_minutes` of sampling produced `min_solved_trees` solved trees, or after
    # `max_sampling_minutes` with at least one.
    min_sampling_minutes: float = 15.0
    max_sampling_minutes: float = 30.0
    min_solved_trees: int = 100
    check_seconds: float = 30.0
    # The value model trains every this many phases (0 never) on the trees of the last `value_window_phases` phases,
    # continuing the last value adapter trained (published or not); it is published only if it passes the gate.
    value_every_phases: int = 4
    value_window_phases: int = 8
    # μ in the policy reward and the value targets once a value model passed the gate and a value A/B search
    # (evaluation.value_ab) found it better than the reference (0 before, and again once an A/B finds it worse).
    value_share_after_gate: float = 0.15
    # The gate's benchmark (grpo_fixed_sets.py gate-benchmark) under $LEAN_SEARCH_RUNS; without it the value model
    # does not train, since nothing could accept it.
    value_benchmark: str = ""
    # Replay files under $LEAN_SEARCH_DATA (grpo_phase.py --lean-replay, --math-replay, --value-replay); empty: none.
    # The value replay is v0's own training data (phase3_value_data.py --name v0: value/v0/train.jsonl).
    lean_replay: str = ""
    math_replay: str = ""
    value_replay: str = ""
    # Command prefix of the training job, e.g. "nice -n 5"; the job runs with CUDA_VISIBLE_DEVICES=gpus.
    command_prefix: str = ""
    # Paused searches' REPL processes above this private memory (0: all) stop before the training job starts, to
    # leave host memory to its ranks; they replay their proof states later. A large value keeps them.
    paused_repl_memory_gib: float = 0.0


@dataclass(frozen=True)
class EvaluationTarget:
    max_expansions: int
    # Per problem; an emergency cap, so that the expansions are the budget and the result does not measure load.
    max_wall_seconds: float
    # Lean REPLs of the evaluation's own pool, next to the paused searches' (rl/README.md, "Host memory").
    concurrency: int
    # Hours of loop time (sampling and training, evaluations excluded) between runs; 0: only when requested.
    every_hours: float = 0.0
    # Run once before the first phase (the baseline of version 0).
    at_start: bool = False
    # Independent runs of that baseline; two measure the run-to-run noise.
    baseline_runs: int = 1
    # Only the first this many problems (the probe's strata in turn; held-out states: states), 0 all: a smoke test's
    # tiny evaluations. The value A/B takes value_ab_test.problems instead.
    problems: int = 0


class EvaluationValueModel(StrEnum):
    # The loop's starting value adapter (value v0): evaluations then measure the policy alone.
    INITIAL = "initial"
    # Whatever value model the loop published last.
    PUBLISHED = "published"


@dataclass(frozen=True)
class ValueAbConfig:
    # Probe-set problems searched by both arms: the first ones of each stratum in the set's order, strata alternating.
    problems: int = 250
    # One-sided exact McNemar tests on the problems only one arm solved, pooled over the A/Bs of one published value
    # model: better at this level turns μ on, worse publishes the reference value model again (and turns μ off).
    significance: float = 0.05


@dataclass(frozen=True)
class EvaluationConfig:
    # The probe set: ~500 held-out pool statements stratified by difficulty, at a small budget.
    probe: EvaluationTarget = field(
        default_factory=lambda: EvaluationTarget(16, 3600.0, 64, every_hours=6.0, at_start=True, baseline_runs=2)
    )
    # miniF2F-valid at the full budget, at milestones (grpo_loop.py request-evaluation) and at the start and end.
    minif2f: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(64, 7200.0, 64))
    # Per-sample success on the held-out states (one policy request per state, no search).
    held_out_states: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(1, 600.0, 64))
    # The value A/B search: the policy fixed, the published value model against `value_model`, at the probe's budget;
    # runs only while the published value model is not that one.
    value_ab: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(16, 3600.0, 64, every_hours=12.0))
    value_ab_test: ValueAbConfig = field(default_factory=ValueAbConfig)
    # The value model the probe and miniF2F search with: fixed, so that they measure the policy alone. The servers
    # swap to it for the evaluations and back afterwards.
    value_model: EvaluationValueModel = EvaluationValueModel.INITIAL
    # Under $LEAN_SEARCH_DATA: the probe set, and the states (a phase5 run's states.jsonl, under $LEAN_SEARCH_RUNS).
    probe_set: str = "grpo/fixed_sets/probe.jsonl"
    held_out_states_file: str = "phase5_eval_visible_student_v2_visible/states.jsonl"
    command_prefix: str = ""
    # Paused searches' REPL processes above this private memory (0: all) stop before evaluating; they replay later.
    paused_repl_memory_gib: float = 0.0


@dataclass(frozen=True)
class RetentionConfig:
    # The phase adapters (policy and value) of the last this many published versions stay on disk, and those still in
    # use (the value adapter the next value training continues); older ones are deleted after each publish, ~0.5 GB of
    # fp32 policy adapter per phase. 0 keeps every adapter. Merged weights: only the current version's and version 0's.
    adapter_versions: int = 5


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
    retention: RetentionConfig = field(default_factory=RetentionConfig)

    def released_servers(self) -> tuple[ServerEndpoint, ...]:
        """Servers on the training GPUs: asleep while a phase trains."""
        return tuple(server for server in self.serving.servers if server.gpu in self.training.gpus)


def parse_loop_config(text: str) -> GrpoLoopConfig:
    config = from_json_object(GrpoLoopConfig, tomllib.loads(text))
    if not config.serving.policy_servers:
        raise ValueError("The loop needs at least one policy server.")
    gpus = config.training.gpus
    if not gpus or len(set(gpus)) < len(gpus):
        raise ValueError("training.gpus needs at least one GPU, each once.")
    shares: dict[int, float] = {}
    for server in config.serving.servers:
        shares[server.gpu] = shares.get(server.gpu, 0.0) + server.memory_share
    if any(share > 1.0 for share in shares.values()):
        raise ValueError(f"The servers' memory shares exceed a GPU's memory: {shares}.")
    sampling = config.sampling
    if sampling.server_failure_window < 1 or not 0 < sampling.server_failure_share <= 1:
        raise ValueError("sampling needs server_failure_window >= 1 and 0 < server_failure_share <= 1.")
    if config.statements.kind == StatementSourceKind.FIXED and not config.statements.fixed:
        raise ValueError('statements.kind = "fixed" needs statements.fixed.')
    training = config.training
    if not 0 < training.min_sampling_minutes <= training.max_sampling_minutes or training.min_solved_trees < 1:
        raise ValueError("training needs 0 < min_sampling_minutes <= max_sampling_minutes and min_solved_trees >= 1.")
    if training.value_every_phases and training.value_window_phases < 1:
        raise ValueError("training.value_window_phases must be at least 1.")
    evaluation = config.evaluation
    targets = (evaluation.probe, evaluation.minif2f, evaluation.held_out_states, evaluation.value_ab)
    if any(target.baseline_runs < 1 for target in targets):
        raise ValueError("evaluation targets need baseline_runs >= 1.")
    return config


def load_loop_config(path: Path) -> GrpoLoopConfig:
    return parse_loop_config(path.read_text(encoding="utf-8"))
