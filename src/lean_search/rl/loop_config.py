"""Configuration of the search-tree GRPO loop (experiments/grpo_loop.py), loaded from TOML."""

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.loop_config import InitialModels, ServerEndpoint, ServingConfig
from lean_search.rl.renaming import RenamingConfig
from lean_search.search.records import from_json_object
from lean_search.value.benchmark import BenchmarkConfig
from lean_search.value.pair_statistics import PairStatisticConfig


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
    # Fixed-set files under $LEAN_SEARCH_DATA whose statements the curriculum never feeds (the probe and gate sets).
    held_out: tuple[str, ...] = ("grpo/fixed_sets/probe.jsonl", "grpo/fixed_sets/gate.jsonl")


@dataclass(frozen=True)
class SamplingConfig:
    # The run config template of every search (budgets, harvesting, ε); its server URLs come from [serving].
    search_config: str
    # Expansions per search (the template's harvesting comes on top), overriding the template's: the loop's training
    # searches only; the evaluations keep their own. Raise it by editing the loop config and restarting the loop when
    # the budget signals (rl/budget_signals.py) show solves crowding into its last quarter.
    max_expansions: int = 32
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
    # A training phase template (experiments/grpo_phase.py); the loop fills in the adapters, μ (`grpo_loop.py
    # set-value-share`, 0 until set) and the seed.
    phase_config: str
    # The GPUs that train, data-parallel (torchrun, one rank each) when several; servers on them sleep while a phase
    # trains, servers on the others stay loaded and idle (every search is paused).
    gpus: tuple[int, ...] = (0,)
    # A phase starts once `min_sampling_minutes` of sampling produced `min_trainable_groups` groups the policy trains on
    # (proof-graph nodes of solved trees with a policy proof and a non-zero advantage, counted as each tree finishes),
    # or after `max_sampling_minutes` with at least one.
    min_sampling_minutes: float = 45.0
    max_sampling_minutes: float = 90.0
    min_trainable_groups: int = 300
    check_seconds: float = 30.0
    # The value model trains every this many phases (0 never) on the trees of the last `value_window_phases` phases,
    # continuing the last value adapter trained; every one is published with the next version.
    value_every_phases: int = 4
    value_window_phases: int = 8
    # Replay files under $LEAN_SEARCH_DATA (grpo_phase.py --lean-replay, --math-replay, --value-replay); empty: none.
    # The value replay is v0's own training data (phase3_value_data.py --name v0: value/v0/train.jsonl).
    lean_replay: str = ""
    math_replay: str = ""
    value_replay: str = ""
    # Command prefix of the training job, e.g. "nice -n 5"; the job runs with CUDA_VISIBLE_DEVICES=gpus.
    command_prefix: str = ""
    # One training job for the whole loop (experiments/grpo_trainer.py; rl/README.md, "Persistent trainer"): its ranks
    # keep their models parked in host memory between phases and hand the merged weights to the servers in memory;
    # false starts grpo_phase.py for every phase.
    persistent: bool = False
    # The persistent job's host memory, a tmpfs, per loop under <host_directory>/<name>: one shared copy of each parked
    # base (~9.4 GB policy, ~4.5 GB value) and the merged weights handed to the servers until written to disk.
    host_directory: str = "/dev/shm/lean_search"
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
    # tiny evaluations.
    problems: int = 0


class EvaluationValueModel(StrEnum):
    # The loop's starting value adapter (value v0): evaluations then measure the policy alone.
    INITIAL = "initial"
    # Whatever value model the loop published last.
    PUBLISHED = "published"


@dataclass(frozen=True)
class ValueArmConfig:
    # Every probe slot whose number is a multiple of this (0: never) searches its part again with the published value
    # model (while that is not the reference), paired per problem with the slot's run with the reference.
    every_slots: int = 2
    # The exact interval of the paired solve-rate difference.
    confidence: float = 0.95
    # Alert (dashboard and loop.log, nothing else) when a one-sided exact McNemar test, pooled over the value arms of
    # the published value model, finds it worse than the reference at this level.
    significance: float = 0.05


@dataclass(frozen=True)
class ValueBenchmarkConfig:
    # The value benchmark (grpo_fixed_sets.py gate-benchmark) under $LEAN_SEARCH_RUNS; empty: no benchmark trend.
    path: str = ""
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    pairs: PairStatisticConfig = field(default_factory=PairStatisticConfig)


@dataclass(frozen=True)
class EvaluationConfig:
    # The probe set: ~500 held-out pool statements stratified by difficulty, at a small budget; one part of
    # `probe_parts` per slot, in turn (the at-start baseline runs every part).
    probe: EvaluationTarget = field(
        default_factory=lambda: EvaluationTarget(16, 3600.0, 64, every_hours=2.0, at_start=True, baseline_runs=2)
    )
    probe_parts: int = 3
    value_arm: ValueArmConfig = field(default_factory=ValueArmConfig)
    # miniF2F-valid at the full budget, at milestones (grpo_loop.py request-evaluation) and at the start and end.
    minif2f: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(64, 7200.0, 64))
    # Per-sample success on the held-out states (one policy request per state, no search).
    held_out_states: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(1, 600.0, 64))
    # The value model the probe and miniF2F search with: fixed, so that they measure the policy alone. The servers
    # swap to it for the evaluations and back afterwards.
    value_model: EvaluationValueModel = EvaluationValueModel.INITIAL
    # Scored through the value servers by every newly served value model, during sampling.
    value_benchmark: ValueBenchmarkConfig = field(default_factory=ValueBenchmarkConfig)
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
class HealthConfig:
    # Relative limits compare with the mean of the first this many phases (version 0's samples, the first updates).
    reference_phases: int = 2
    # Per token, k3; version 0's is 0. At lr 1e-5 review F expects 1e-4 to 1e-3 after 5-10 phases.
    max_kl_to_starting_policy: float = 0.02
    # Of the last pass's trained tokens; PPO runs usually stay below 0.1-0.2, this loop's small steps far below.
    max_clip_fraction: float = 0.1
    # Fractions of the reference phases' mean: fewer distinct samples is collapse, explanations shrinking or growing
    # a drift of the visible reasoning.
    min_distinct_samples_fraction: float = 0.75
    min_explanation_fraction: float = 0.5
    max_explanation_fraction: float = 2.0
    # The cut-off share may reach this multiple of the reference, and at least the reference plus `min_cut_off_rise`.
    max_cut_off_factor: float = 2.0
    min_cut_off_rise: float = 0.01
    # Fractions of version 0's held-out evaluation.
    min_held_out_valid_fraction: float = 0.9
    min_held_out_success_fraction: float = 0.9
    # Below this fraction of version 0's held-out valid-Lean rate the loop stops after the phase; 0 never stops.
    stop_held_out_valid_fraction: float = 0.7
    # The share of solves in the budget's last quarter, pooled over the last `late_solve_phases` phases, above which
    # a larger `sampling.max_expansions` is suggested.
    max_late_solve_share: float = 0.10
    late_solve_phases: int = 3


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
    health: HealthConfig = field(default_factory=HealthConfig)

    def released_servers(self) -> tuple[ServerEndpoint, ...]:
        """Servers on the training GPUs: asleep while a phase trains."""
        return tuple(server for server in self.serving.servers if server.gpu in self.training.gpus)

    def host_directory(self) -> Path:
        """The persistent training job's host memory for this loop (`training.resident.HostDirectories`)."""
        return Path(self.training.host_directory) / self.name


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
    if not 0 < training.min_sampling_minutes <= training.max_sampling_minutes or training.min_trainable_groups < 1:
        raise ValueError(
            "training needs 0 < min_sampling_minutes <= max_sampling_minutes and min_trainable_groups >= 1."
        )
    if sampling.max_expansions < 1:
        raise ValueError("sampling.max_expansions must be at least 1.")
    if config.health.reference_phases < 1 or config.health.late_solve_phases < 1:
        raise ValueError("health needs reference_phases >= 1 and late_solve_phases >= 1.")
    if training.value_every_phases and training.value_window_phases < 1:
        raise ValueError("training.value_window_phases must be at least 1.")
    evaluation = config.evaluation
    targets = (evaluation.probe, evaluation.minif2f, evaluation.held_out_states)
    if any(target.baseline_runs < 1 for target in targets):
        raise ValueError("evaluation targets need baseline_runs >= 1.")
    if evaluation.probe_parts < 1 or evaluation.value_arm.every_slots < 0:
        raise ValueError("evaluation needs probe_parts >= 1 and value_arm.every_slots >= 0.")
    return config


def load_loop_config(path: Path) -> GrpoLoopConfig:
    return parse_loop_config(path.read_text(encoding="utf-8"))
