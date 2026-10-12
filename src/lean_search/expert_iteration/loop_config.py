"""Configuration of the continuous expert-iteration loop, loaded from TOML."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.expert_iteration.config import PreferenceConfig
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
class PassBudget:
    max_expansions: int
    # Search time without training pauses; a backstop next to the expansion cap.
    max_wall_seconds: float


@dataclass(frozen=True)
class HarvestConfig:
    """After a proof, expand the frontier states the value model puts this close to done, for more proofs."""

    max_remaining_steps: float = 1.5
    # Extra expansions per solved statement; 0 turns harvesting off.
    max_expansions: int = 8


@dataclass(frozen=True)
class SchedulerConfig:
    # One budget per pass: the first pass for every statement, later ones (each at most once) for promising unsolved
    # statements. Row 4 found 88% of its miniF2F-valid proofs within 8 expansions; the first pass allows twice that.
    budgets: tuple[PassBudget, ...] = (PassBudget(16, 300.0), PassBudget(64, 1200.0))
    # Fresh statements are drawn by these weights; sources not listed weigh 1, weight 0 leaves a source out.
    source_weights: tuple[SourceWeight, ...] = ()
    # While fresh statements remain, at most this share of the started attempts are later passes.
    retry_share: float = 0.2
    # An unsolved statement gets the next pass when the best h on its open frontier is at most this; without a value
    # model, when the search got `promising_depth` deep (0 never).
    promising_value: float = 2.5
    promising_depth: int = 0


@dataclass(frozen=True)
class SearchServiceConfig:
    # Statements under $LEAN_SEARCH_DATA (phase6_pool.py --step select): load failures and statements the automation
    # sweep proves surface in the search itself.
    candidates: str
    # A run config whose sections are the template for every search; budgets come from the scheduler's passes.
    search_config: str
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
    # Re-score every open frontier node with the new value model after a phase (one prefill each).
    rescore_frontier: bool = True
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
    max_prompt_tokens: int = 2048
    max_completion_tokens: int = 256


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
    if not config.search.scheduler.budgets:
        raise ValueError("The scheduler needs at least one pass budget.")
    gpus = {server.gpu for server in config.serving.servers}
    if not {config.training.policy.gpu, config.training.value.gpu} <= gpus:
        raise ValueError("Training runs on the servers' GPUs, which a phase frees.")
    return config
