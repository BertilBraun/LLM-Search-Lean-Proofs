"""One search-tree GRPO training phase: label the trees, train the policy and/or the value model, publish."""

import dataclasses
import gc
import json
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import torch

from lean_search.expert_iteration.serving import LoopPaths, ModelVersion, Publisher, read_current, record_published
from lean_search.expert_iteration.shards import now
from lean_search.monitoring.families import GrpoPhase
from lean_search.policy.adapters import MergeSeconds, PremergedWeights, premerge_adapter
from lean_search.reasoning.dataset import ReasoningExample, tokenize_reasoning_example
from lean_search.rl.grpo_groups import PolicyGroup, RewardConfig, policy_groups
from lean_search.rl.policy_data import (
    PolicyDataMetrics,
    PolicyTokenizer,
    PolicyTree,
    SamplerAgreement,
    build_policy_data,
)
from lean_search.rl.policy_trainer import GrpoConfig, GrpoStepRecord, GrpoTrainingResult, train_grpo
from lean_search.rl.tree_statistics import GraphStatistics, graph_statistics, total_statistics
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import TreeRecord, to_json
from lean_search.search.tactic_labels import policy_tactics
from lean_search.training.data_parallel import SINGLE_PROCESS, Ranks, broadcast_from_main, largest
from lean_search.training.math_data import MathSolution, tokenize_math_solution
from lean_search.training.sft_data import TokenizedExample
from lean_search.value.benchmark import LabelledTree
from lean_search.value.diagnostics import LabelDistribution, LabelDistributions, label_distribution, label_distributions
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    ValueTargetConfig,
    recorded_estimates,
    value_targets,
)
from lean_search.value.graph_trainer import (
    GraphValueConfig,
    GraphValueStepRecord,
    GraphValueTrainingResult,
    build_graph_value_data,
    train_graph_value_model,
)
from lean_search.value.labels import ValueExample
from lean_search.value.prompts import ValueTokenizer
from lean_search.value.ranking import RankingConfig


@dataclass(frozen=True)
class PolicyReplayConfig:
    # Lean SFT examples (reasoning data set format) and math worked solutions per phase; 0 leaves one out.
    lean_examples: int = 0
    math_examples: int = 0
    seed: str = "grpo-replay"


@dataclass(frozen=True)
class TrainingPhaseConfig:
    reward: RewardConfig = field(default_factory=RewardConfig)
    readout: RemainingStepsReadout = field(default_factory=RemainingStepsReadout)
    # value_share (μ): the loop sets it per phase (0 until the owner turns it on).
    value_targets: ValueTargetConfig = field(
        default_factory=lambda: ValueTargetConfig(value_share=0.0, max_targets_per_tree=64)
    )
    ranking: RankingConfig = field(default_factory=RankingConfig)
    # Absent: that model does not train this phase.
    policy: GrpoConfig | None = None
    policy_replay: PolicyReplayConfig = field(default_factory=PolicyReplayConfig)
    value: GraphValueConfig | None = None


@dataclass(frozen=True)
class PhaseInputs:
    records: Sequence[TreeRecord]
    lean_replay: Sequence[ReasoningExample] = ()
    math_replay: Sequence[MathSolution] = ()
    value_replay: Sequence[ValueExample] = ()
    # The value model's window of recent phases' trees, this phase's included; empty: this phase's trees alone. Only
    # the main rank's are read.
    value_records: Sequence[TreeRecord] = ()


@dataclass(frozen=True)
class LabelledPhaseData:
    trees: tuple[LabelledTree, ...]
    policy_trees: tuple[PolicyTree, ...]
    # Summed over the trees, for the search family of the dashboard.
    statistics: GraphStatistics

    @property
    def groups(self) -> list[PolicyGroup]:
        return [group for tree in self.policy_trees for group in tree.groups]


@dataclass(frozen=True)
class PolicyOutcome:
    adapter: str
    data: PolicyDataMetrics
    replay_examples: int
    result: GrpoTrainingResult
    # Building the sequences and the replay examples.
    data_seconds: float = 0.0


@dataclass(frozen=True)
class ValueOutcome:
    adapter: str
    result: GraphValueTrainingResult
    # The window's trees the value model trained on.
    trees: int = 0
    # What it trained on per bin (the main rank's; the window's targets as smoothed for training, and the v0 replay).
    labels: LabelDistributions | None = None
    replay_labels: LabelDistribution | None = None
    data_seconds: float = 0.0
    # Loading, compiling, training and saving.
    training_seconds: float = 0.0


@dataclass(frozen=True)
class TrainerTimings:
    """The training job's parts in wall seconds, as the main rank saw them; the parts need not add up to the total."""

    # Labelling the trees and building the policy and value data.
    preparation_seconds: float = 0.0
    policy_load_seconds: float = 0.0
    compile_seconds: float = 0.0
    scoring_seconds: float = 0.0
    policy_training_seconds: float = 0.0
    value_training_seconds: float = 0.0
    # Merging the new adapters into their bases on the GPUs (grpo_phase.py --merge-adapters), the slowest rank.
    merge_seconds: float = 0.0
    # The policy adapter and the merged weights written.
    write_seconds: float = 0.0
    total_seconds: float = 0.0


class TrainingStage(StrEnum):
    LABELLING = "labelling"
    POLICY = "policy"
    VALUE = "value"
    MERGE = "merge"


@dataclass(frozen=True)
class StageMemory:
    """GPU memory after a stage and the release of its models, the largest over the ranks."""

    stage: TrainingStage
    allocated_gib: float
    reserved_gib: float


@dataclass(frozen=True)
class PhaseOutcome:
    trees: int
    groups: int
    policy: PolicyOutcome | None
    value: ValueOutcome | None
    timings: TrainerTimings = field(default_factory=TrainerTimings)
    memory: tuple[StageMemory, ...] = ()


def label_phase_data(records: Sequence[TreeRecord], config: TrainingPhaseConfig) -> LabelledPhaseData:
    """Value targets from the recorded estimates (the value version that ran the search) and the GRPO groups."""
    trees = []
    policy_trees = []
    statistics = []
    for record in records:
        labels = label_graph(record)
        estimates = recorded_estimates(record, config.readout)
        targets = value_targets(record, labels, estimates, config.value_targets)
        tactics = policy_tactics(record, labels, config.reward.off_graph_min_expanded_nodes)
        tree_groups = policy_groups(record, labels, tactics, estimates, config.reward)
        trees.append(LabelledTree(record, labels, targets))
        policy_trees.append(PolicyTree(tree_groups.groups, record.expansions))
        statistics.append(graph_statistics(record, labels, targets, tactics, tree_groups))
    return LabelledPhaseData(tuple(trees), tuple(policy_trees), total_statistics(statistics))


def label_value_trees(records: Sequence[TreeRecord], config: TrainingPhaseConfig) -> tuple[LabelledTree, ...]:
    trees = []
    for record in records:
        labels = label_graph(record)
        targets = value_targets(record, labels, recorded_estimates(record, config.readout), config.value_targets)
        trees.append(LabelledTree(record, labels, targets))
    return tuple(trees)


def chosen[T](items: Sequence[T], count: int, seed: str) -> list[T]:
    return random.Random(seed).sample(list(items), min(count, len(items)))


def policy_replay_examples(
    tokenizer: PolicyTokenizer, inputs: PhaseInputs, config: PolicyReplayConfig, max_tokens: int
) -> list[TokenizedExample]:
    examples = [
        tokenize_reasoning_example(tokenizer, example)
        for example in chosen(inputs.lean_replay, config.lean_examples, f"{config.seed}/lean")
    ]
    examples += [
        tokenize_math_solution(tokenizer, solution)
        for solution in chosen(inputs.math_replay, config.math_examples, f"{config.seed}/math")
    ]
    return [example for example in examples if example.token_count <= max_tokens]


def append_json_line(path: Path, record: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")


def train_policy_phase(
    config: TrainingPhaseConfig,
    grpo: GrpoConfig,
    labelled: LabelledPhaseData,
    inputs: PhaseInputs,
    tokenizer: PolicyTokenizer,
    device: torch.device,
    directory: Path,
    on_step: Callable[[GrpoStepRecord], None],
    ranks: Ranks = SINGLE_PROCESS,
) -> PolicyOutcome:
    started = time.perf_counter()
    data = build_policy_data(labelled.policy_trees, tokenizer, grpo.data)
    replay = policy_replay_examples(tokenizer, inputs, config.policy_replay, grpo.max_sequence_tokens)
    data_seconds = time.perf_counter() - started
    adapter = directory / "adapter"
    result = train_grpo(grpo, tokenizer.pad_token_id, data.sequences, replay, device, adapter, on_step, ranks)
    return PolicyOutcome(str(adapter), data.metrics, len(replay), result, data_seconds)


def train_value_phase(
    config: TrainingPhaseConfig,
    value: GraphValueConfig,
    window: Sequence[LabelledTree],
    inputs: PhaseInputs,
    tokenizer: ValueTokenizer,
    pad_token_id: int,
    device: torch.device,
    directory: Path,
    on_step: Callable[[GraphValueStepRecord], None],
    ranks: Ranks = SINGLE_PROCESS,
) -> ValueOutcome:
    """Trains on the window's trees, split across the ranks: the main rank holds the window and builds the data, the
    others receive it. Only the main rank's outcome has the label distributions."""
    started = time.perf_counter()
    built = (
        build_graph_value_data(window, config.ranking, inputs.value_replay, tokenizer, value) if ranks.is_main else None
    )
    data = broadcast_from_main(built, ranks)
    data_built = time.perf_counter()
    adapter = directory / "adapter"
    result = train_graph_value_model(value, tokenizer, pad_token_id, data, device, adapter, on_step, ranks)
    outcome = ValueOutcome(
        str(adapter),
        result,
        data.trees,
        data_seconds=data_built - started,
        training_seconds=time.perf_counter() - data_built,
    )
    if built is None:
        return outcome
    replay = [(item.distribution, item.weight) for item in built.pointwise if item.target is None]
    return dataclasses.replace(
        outcome,
        labels=label_distributions(window, value.smoothing_sigma),
        replay_labels=label_distribution(replay),
    )


def released_memory(stage: TrainingStage, device: torch.device, ranks: Ranks) -> StageMemory:
    """Frees what the stage's models left: compiled layers refer to themselves, so only the cyclic collector does."""
    gc.collect()
    allocated = reserved = 0.0
    if device.type == "cuda":
        torch.cuda.empty_cache()
        allocated = torch.cuda.memory_allocated(device) / 2**30
        reserved = torch.cuda.memory_reserved(device) / 2**30
    return StageMemory(stage, largest(allocated, device, ranks), largest(reserved, device, ranks))


def merge_on_gpus(merges: Sequence[PremergedWeights], device: torch.device, ranks: Ranks) -> MergeSeconds:
    """Each adapter merged into its base on one rank's GPU (in turn), next to the adapter; the slowest rank's time."""
    seconds = [
        premerge_adapter(merge.base_model, Path(merge.adapter), device)
        for index, merge in enumerate(merges)
        if index % ranks.world_size == ranks.rank
    ]
    return MergeSeconds(
        largest(sum(part.merge for part in seconds), device, ranks),
        largest(sum(part.write for part in seconds), device, ranks),
    )


def run_training_phase(
    config: TrainingPhaseConfig,
    inputs: PhaseInputs,
    policy_tokenizer: PolicyTokenizer | None,
    value_tokenizer: ValueTokenizer | None,
    device: torch.device,
    output_directory: Path,
    ranks: Ranks = SINGLE_PROCESS,
    merge_adapters: bool = False,
) -> PhaseOutcome:
    """Adapters under output_directory/{policy,value}/adapter, step records next to them, phase.json at the top, all
    written by the main rank; `merge_adapters` also merges the new adapters on the GPUs (`premerged_directory`)."""
    started = time.perf_counter()
    labelled = label_phase_data(inputs.records, config)
    labelling_seconds = time.perf_counter() - started
    memory = [released_memory(TrainingStage.LABELLING, device, ranks)]
    merges: list[PremergedWeights] = []
    policy = None
    if config.policy is not None:
        assert policy_tokenizer is not None
        directory = output_directory / "policy"
        policy = train_policy_phase(
            config,
            config.policy,
            labelled,
            inputs,
            policy_tokenizer,
            device,
            directory,
            lambda record: append_json_line(directory / "steps.jsonl", record),
            ranks,
        )
        merges.append(PremergedWeights(config.policy.model, policy.adapter))
        memory.append(released_memory(TrainingStage.POLICY, device, ranks))
    value = None
    if config.value is not None:
        assert value_tokenizer is not None
        directory = output_directory / "value"
        window: Sequence[LabelledTree] = ()
        if ranks.is_main:
            window = label_value_trees(inputs.value_records, config) if inputs.value_records else labelled.trees
        value = train_value_phase(
            config,
            config.value,
            window,
            inputs,
            value_tokenizer,
            value_tokenizer.pad_token_id,
            device,
            directory,
            lambda record: append_json_line(directory / "steps.jsonl", record),
            ranks,
        )
        merges.append(PremergedWeights(config.value.model, value.adapter))
        memory.append(released_memory(TrainingStage.VALUE, device, ranks))
    merged = MergeSeconds()
    if merge_adapters:
        merged = merge_on_gpus(merges, device, ranks)
        memory.append(released_memory(TrainingStage.MERGE, device, ranks))
    timings = trainer_timings(labelling_seconds, policy, value, merged, time.perf_counter() - started)
    outcome = PhaseOutcome(len(labelled.trees), len(labelled.groups), policy, value, timings, tuple(memory))
    if ranks.is_main:
        (output_directory / "phase.json").write_text(to_json(outcome), encoding="utf-8")
    return outcome


def trainer_timings(
    labelling_seconds: float,
    policy: PolicyOutcome | None,
    value: ValueOutcome | None,
    merged: MergeSeconds,
    total_seconds: float,
) -> TrainerTimings:
    timings = TrainerTimings(
        preparation_seconds=labelling_seconds,
        merge_seconds=merged.merge,
        write_seconds=merged.write,
        total_seconds=total_seconds,
    )
    if policy is not None:
        result = policy.result
        timings = dataclasses.replace(
            timings,
            preparation_seconds=timings.preparation_seconds + policy.data_seconds,
            policy_load_seconds=result.load_seconds,
            compile_seconds=result.compile_seconds,
            scoring_seconds=result.scoring_seconds,
            policy_training_seconds=result.training_seconds,
            write_seconds=timings.write_seconds + result.save_seconds,
        )
    if value is not None:
        timings = dataclasses.replace(
            timings,
            preparation_seconds=timings.preparation_seconds + value.data_seconds,
            value_training_seconds=value.training_seconds,
        )
    return timings


def sampler_agreement_by_age(result: GrpoTrainingResult, trained_version: int) -> dict[str, SamplerAgreement]:
    return {
        str(trained_version - entry.policy_version): entry.agreement
        for entry in result.sampler_agreement_by_version
        if entry.policy_version is not None
    }


def grpo_phase_record(
    policy: PolicyOutcome, sampling_seconds: float | None, trained_version: int | None = None
) -> GrpoPhase:
    """The phase's line of the dashboard's grpo family; `sampling_seconds` is the search time behind the data and
    `trained_version` the published version the phase trained from (without it the line has no sampling ages)."""
    data = policy.data
    result = policy.result
    return GrpoPhase(
        groups=data.groups,
        group_samples=data.samples,
        mixed_reward_group_share=data.groups_trained / data.groups if data.groups else 0.0,
        mean_local_reward=data.mean_local_reward,
        mean_global_reward=data.mean_global_reward,
        kl_to_behaviour_policy=result.final_kl_to_data_policy,
        clip_fraction=result.final_clip_fraction,
        mean_explanation_tokens=data.mean_explanation_tokens,
        mean_block_tactics=data.mean_tactics_per_sample,
        policy_loss=result.final_policy_loss,
        trained_tokens=result.trained_tokens,
        training_seconds=result.scoring_seconds + result.training_seconds,
        groups_trained=data.groups_trained,
        sequences=data.sequences,
        tactics=data.tactics,
        local_advantage_share=data.local_advantage_share,
        sampler_log_probability_difference=result.sampler_agreement.mean_difference,
        sampler_absolute_log_probability_difference=result.sampler_agreement.mean_absolute_difference,
        sampler_kl=result.sampler_agreement.kl_sampler_to_trainer,
        sampler_by_age={} if trained_version is None else sampler_agreement_by_age(result, trained_version),
        ratios_by_pass={str(number): ratios for number, ratios in enumerate(result.ratios_by_pass, start=1)},
        forced_answers_kept=data.forced_sequences,
        retokenized_sequences=data.retokenized_sequences,
        sampling_seconds=sampling_seconds,
    )


def publish_phase(paths: LoopPaths, publisher: Publisher, outcome: PhaseOutcome, trigger: str) -> ModelVersion:
    """The next version: the new policy adapter and the new value adapter, each if one trained."""
    current = read_current(paths)
    version = ModelVersion(
        version=current.version + 1,
        policy_adapter=current.policy_adapter if outcome.policy is None else outcome.policy.adapter,
        value_adapter=current.value_adapter if outcome.value is None else outcome.value.adapter,
        published_at=now(),
        trigger=trigger,
    )
    prepared = publisher.prepare(version)
    record_published(paths, prepared)
    publisher.prune(prepared)
    return prepared
