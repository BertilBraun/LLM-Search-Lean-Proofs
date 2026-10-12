"""Configuration of the continuous expert-iteration loop, loaded from TOML."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.preferences import ValueJumpConfig
from lean_search.search.records import from_json_object
from lean_search.training.sft_data import SourceWeight
from lean_search.value.labels import TreeLabelConfig


@dataclass(frozen=True)
class ServerEndpoint:
    # The serve_model.sh server name, its GPU and its OpenAI-compatible base URL.
    name: str
    gpu: int
    url: str


@dataclass(frozen=True)
class ServingConfig:
    base_model: str
    # The --served-model-name of every server; the policy and value adapters keep their names across phases.
    served_model: str
    tokenizer: str
    servers: tuple[ServerEndpoint, ...]
    policy_adapter_name: str = "policy"
    value_adapter_name: str = "value"


@dataclass(frozen=True)
class SearchStage:
    """A statement's search budget up to and including this stage; each stage continues the previous stage's tree."""

    max_expansions: int
    # Search time without training pauses; a backstop next to the expansion cap.
    max_wall_seconds: float
    # An unsolved statement enters this stage when the best h on its open frontier is at most this; None for the
    # first stage, which every statement gets.
    max_frontier_value: float | None = None


@dataclass(frozen=True)
class HarvestConfig:
    """After a proof, expand the frontier states the value model puts this close to done, for more proofs."""

    max_remaining_steps: float = 1.5
    # Extra expansions per solved statement; 0 turns harvesting off.
    max_expansions: int = 8


@dataclass(frozen=True)
class SchedulerConfig:
    # Budget escalation: 32 expansions for every statement, then 128 and 512 in total while the open frontier stays
    # close to a proof by the value model; the wall caps scale with the stage.
    stages: tuple[SearchStage, ...] = (
        SearchStage(32, 600.0),
        SearchStage(128, 2400.0, 3.0),
        SearchStage(512, 9600.0, 2.0),
    )
    # Statements of the open pool (no known proofs) are drawn by these weights; sources not listed weigh 1, weight 0
    # leaves a source out.
    source_weights: tuple[SourceWeight, ...] = ()
    # Without a value model, an unsolved statement enters the next stage when its search got this deep (0 never).
    promising_depth: int = 0


@dataclass(frozen=True)
class SearchServiceConfig:
    # A run config whose sections are the template for every search; budgets come from the scheduler's stages.
    search_config: str
    # Fresh statements come from the curriculum over verified known-proof statements (pool v3)...
    curriculum: CurriculumConfig = field(default_factory=CurriculumConfig)
    # ...and, for `open_share` of the fresh starts (or once the curriculum has none), from an open pool without known
    # proofs under $LEAN_SEARCH_DATA (pool v2: phase6_pool.py --step select); empty for none.
    open_candidates: str = ""
    open_share: float = 0.0
    # Stale frontier states (scored by an older value model) re-scored together when one reaches the top; 0 never.
    lazy_rescore_states: int = 32
    # Concurrent searches, each holding a REPL; REPLs mostly wait on the GPU, so this may exceed the core count.
    concurrency: int = 128
    shard_attempts: int = 1000
    shard_minutes: float = 10.0
    heartbeat_seconds: float = 30.0
    harvest: HarvestConfig = field(default_factory=HarvestConfig)
    scheduler: SchedulerConfig = field(default_factory=SchedulerConfig)


@dataclass(frozen=True)
class BufferConfig:
    """A rolling FIFO buffer: dataset samples fill it first and leave first; then the oldest search samples go."""

    # The capacity until the inflow is measured, then `capacity_phases` times the inflow per phase (a moving average),
    # at least `minimum_capacity`.
    initial_capacity: int
    minimum_capacity: int = 1000
    capacity_phases: float = 3.5
    # Samples trained per phase = reuse x samples added in it, so each sample is trained on about `reuse` times.
    reuse: float = 1.0
    # Dataset samples keep at least this share of the capacity (against format and skill drift); 0 lets them fade out.
    minimum_dataset_share: float = 0.1


@dataclass(frozen=True)
class TrainingStage:
    # A training config template (experiments/phase6_dpo.py or phase3_value.py); data and initial_adapter are filled
    # in per phase. The two stages run in parallel, one GPU each.
    config: str
    gpu: int


@dataclass(frozen=True)
class TrainingConfig:
    # A phase starts after `new_proofs` new proofs once `min_minutes` passed since the last one, or after
    # `max_minutes` with at least `minimum_new_proofs`.
    new_proofs: int = 400
    min_minutes: float = 20.0
    max_minutes: float = 60.0
    minimum_new_proofs: int = 20
    check_seconds: float = 30.0
    # Re-score every open frontier node with the new value model right after a phase (one prefill each), skipped when
    # the last measured rate predicts more than `rescore_max_seconds` and stopped at that limit; lazy re-scoring at pop
    # time (search.lazy_rescore_states) replaces it by default.
    rescore_frontier: bool = False
    rescore_max_seconds: float = 60.0
    seed: str = "loop"
    # Statements whose trees only validate (the value gate, validation sets), by hash.
    held_out_fraction: float = 0.02
    policy: TrainingStage = field(default_factory=lambda: TrainingStage("", 0))
    value: TrainingStage = field(default_factory=lambda: TrainingStage("", 1))
    policy_buffer: BufferConfig = field(default_factory=lambda: BufferConfig(10000, 2000))
    value_buffer: BufferConfig = field(default_factory=lambda: BufferConfig(80000, 16000))
    # Value labels per statement attempt at most: every exact and dead label first, then censored ones sampled.
    max_labels_per_tree: int = 16
    # Policy samples: the policy's steps on found proofs (also harvested ones) against dead or failed siblings;
    # automation steps are left out, so automation-only proofs add nothing. Proof steps without a rejected sibling
    # train as chosen-only samples when `chosen_only_steps` is set.
    preferences: PreferenceConfig = field(default_factory=PreferenceConfig)
    chosen_only_steps: bool = False
    value_jumps: ValueJumpConfig = field(default_factory=ValueJumpConfig)
    labels: TreeLabelConfig = field(default_factory=TreeLabelConfig)
    # The initial dataset samples: traced steps (NLL only) by source, and a data set under $LEAN_SEARCH_DATA/value.
    traced_directory: str = "traced"
    traced_sources: tuple[SourceWeight, ...] = ()
    value_dataset: str = "v0"
    # Thinking mode: shorten long reasoning traces of the policy samples before training (the reasoning module's
    # compression with its sufficiency check); the trainer refuses to run with it on until that module is wired in.
    compress_reasoning: bool = False


@dataclass(frozen=True)
class EvaluationLoopConfig:
    # miniF2F-valid at a reduced budget every `every_versions` versions (phases), from a run config template.
    config: str
    every_versions: int = 3
    max_expansions: int = 32
    concurrency: int = 16
    check_seconds: float = 120.0


@dataclass(frozen=True)
class InitialModels:
    policy_adapter: str
    value_adapter: str


@dataclass(frozen=True)
class LoopConfig:
    # The loop's directory under $LEAN_SEARCH_RUNS; phase data goes to $LEAN_SEARCH_DATA/expert_iteration/<name>/.
    name: str
    initial: InitialModels
    serving: ServingConfig
    search: SearchServiceConfig
    training: TrainingConfig
    evaluation: EvaluationLoopConfig


def load_loop_config(path: Path) -> LoopConfig:
    config = from_json_object(LoopConfig, tomllib.loads(path.read_text(encoding="utf-8")))
    stages = config.search.scheduler.stages
    if not stages or stages[0].max_frontier_value is not None:
        raise ValueError("The scheduler needs a first stage, which every statement enters (no max_frontier_value).")
    if any(later.max_expansions <= earlier.max_expansions for earlier, later in zip(stages, stages[1:], strict=False)):
        raise ValueError("Each stage's max_expansions is a total and must exceed the previous stage's.")
    gpus = {server.gpu for server in config.serving.servers}
    if not {config.training.policy.gpu, config.training.value.gpu} <= gpus:
        raise ValueError("Training runs on the servers' GPUs, which a phase frees.")
    return config
