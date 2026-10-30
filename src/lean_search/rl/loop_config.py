"""Configuration of the search-tree GRPO loop (experiments/grpo_loop.py), loaded from TOML."""

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.loop_config import InitialModels, ServerEndpoint, ServingConfig
from lean_search.rl.renaming import RenamingConfig
from lean_search.rl.search_options import CONTROL_ARM, OptionsArmConfig
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
    # While an evaluation runs beside sampling (`evaluation.beside_sampling`), the searches taking new statements are
    # `concurrency` minus the evaluation's searches in flight, at least this many; the others finish their search and
    # wait, their idle REPL processes stopped.
    min_concurrency_beside_evaluations: int = 56
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
    # Off by default: half of the statements (by a hash of the name) search with these options, the loop's evaluations
    # never (rl/README.md, "Search options A/B").
    options_arm: OptionsArmConfig = field(default_factory=OptionsArmConfig)


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
    # continuing the last value adapter trained; every one is published with the next version. With 45-90-minute
    # phases: a retrain every 1.5-3 hours on 3-6 hours of trees.
    value_every_phases: int = 2
    value_window_phases: int = 4
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
    # A persistent job that does not answer a phase's `train` in time is stopped and started again (the phase trained
    # once more; a second time fails the phase): `train_timeout_factor` times the median of the earlier phases of the
    # same kind (value phase or not), at least `train_timeout_minimum_minutes`; a job's first phase, with its model
    # building and compilation, `first_train_timeout_minutes`. Below the collectives' own 1-hour timeout.
    train_timeout_factor: float = 2.0
    train_timeout_minimum_minutes: float = 15.0
    first_train_timeout_minutes: float = 45.0
    # Paused searches' REPL processes above this private memory (0: all) stop before the training job starts, to
    # leave host memory to its ranks; they replay their proof states later. A large value keeps them.
    paused_repl_memory_gib: float = 0.0


@dataclass(frozen=True)
class EvaluationTarget:
    max_expansions: int
    # Per problem; a cap on the Lean-bound tail, so that mostly the expansions are the budget (stops are reported).
    max_wall_seconds: float
    # Lean REPLs of the evaluation's own pool; at a pause the paused searches' REPL processes stop first
    # (`paused_repl_memory_gib`), so the loop's sampling concurrency fits (rl/README.md, "Host memory").
    concurrency: int
    # Hours of loop time (sampling and training, evaluations excluded) between runs; 0: only when requested.
    every_hours: float = 0.0
    # Run once before the first phase (the baseline of version 0).
    at_start: bool = False
    # Independent runs of that baseline; two measure the run-to-run noise.
    baseline_runs: int = 1
    # REPLs of each of its baseline runs (every probe part's), which all run at once before sampling; 0: an equal
    # share of `sampling.concurrency` over every at-start run.
    baseline_concurrency: int = 0
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
    # Once per published value model other than the reference, at the first probe slot after it was published, the
    # slot's part is searched again with it, paired per problem with the slot's run with the reference; false: never.
    enabled: bool = True
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
        default_factory=lambda: EvaluationTarget(16, 3600.0, 112, every_hours=2.0, at_start=True, baseline_runs=2)
    )
    probe_parts: int = 3
    value_arm: ValueArmConfig = field(default_factory=ValueArmConfig)
    # miniF2F-valid at the full budget, at milestones (grpo_loop.py request-evaluation) and at the start and end.
    minif2f: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(64, 7200.0, 112))
    # Per-sample success and valid Lean on the held-out states (one policy request per state, no search), with every
    # probe slot: the hard stop's signal, against version 0's run at the start.
    held_out_states: EvaluationTarget = field(
        default_factory=lambda: EvaluationTarget(1, 600.0, 112, every_hours=2.0, at_start=True)
    )
    # The value model the probe and miniF2F search with. INITIAL measures the policy alone: the servers swap to it for
    # the evaluations and back afterwards.
    value_model: EvaluationValueModel = EvaluationValueModel.INITIAL
    # The probe and miniF2F run after the pause, while the searches sample (`sampling.min_concurrency_beside_
    # evaluations`); the held-out states and version 0's baselines stay before sampling. Needs the published value
    # model and no value arm: nothing swaps. A failure is an alert and runs again after the next pause.
    beside_sampling: bool = False
    # A phase due while an evaluation runs beside sampling waits this long for it, then cancels it (it runs again after
    # the pause).
    max_pause_wait_minutes: float = 30.0
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
    # The policy adapters of the last this many versions whose held-out evaluation raised no held-out alert stay too:
    # the automatic rollback's target and the alternatives to it.
    healthy_versions: int = 3


@dataclass(frozen=True)
class HealthConfig:
    # Relative limits compare with the mean of the first this many phases (version 0's samples, the first updates).
    reference_phases: int = 2
    # Per token, k3; version 0's is 0. The single-step test at lr 3e-5 measured 0.03-0.08 after 76 steps and the KL
    # grows phase by phase: 0.5 alerts on a policy far from its start.
    max_kl_to_starting_policy: float = 0.5
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
    # Below this fraction of version 0's held-out valid-Lean rate the held-out valid Lean collapsed (0: never): the
    # loop publishes the last healthy version's policy again and continues sampling, and stops only when it collapses
    # again within `rollback_window_phases` phases of that rollback (0: stop at the first collapse).
    stop_held_out_valid_fraction: float = 0.7
    rollback_window_phases: int = 4
    # Below this fraction of the reference phases' valid-block rate (the sampled blocks that run completely in Lean, a
    # free per-phase early warning) the held-out states run at the next pause. Lower than the held-out warning: the
    # rate falls with longer blocks too.
    min_valid_block_fraction: float = 0.85
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
    if sampling.options_arm.name == CONTROL_ARM:
        raise ValueError(f"sampling.options_arm.name must not be {CONTROL_ARM!r}, the other arm's.")
    if (
        config.evaluation.beside_sampling
        and not 1 <= sampling.min_concurrency_beside_evaluations <= sampling.concurrency
    ):
        raise ValueError(
            "evaluation.beside_sampling needs 1 <= sampling.min_concurrency_beside_evaluations <= concurrency."
        )
    if config.health.reference_phases < 1 or config.health.late_solve_phases < 1:
        raise ValueError("health needs reference_phases >= 1 and late_solve_phases >= 1.")
    if training.value_every_phases and training.value_window_phases < 1:
        raise ValueError("training.value_window_phases must be at least 1.")
    evaluation = config.evaluation
    targets = (evaluation.probe, evaluation.minif2f, evaluation.held_out_states)
    if any(target.baseline_runs < 1 or target.baseline_concurrency < 0 for target in targets):
        raise ValueError("evaluation targets need baseline_runs >= 1 and baseline_concurrency >= 0.")
    if evaluation.probe_parts < 1:
        raise ValueError("evaluation needs probe_parts >= 1.")
    if evaluation.beside_sampling and (
        evaluation.value_model != EvaluationValueModel.PUBLISHED or evaluation.value_arm.enabled
    ):
        raise ValueError(
            'evaluation.beside_sampling needs value_model = "published" and [evaluation.value_arm] enabled = false: '
            "the value servers keep serving the searches' value model."
        )
    return config


def load_loop_config(path: Path) -> GrpoLoopConfig:
    return parse_loop_config(path.read_text(encoding="utf-8"))
