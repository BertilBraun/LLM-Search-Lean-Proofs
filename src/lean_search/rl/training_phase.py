"""One search-tree GRPO training phase: label the trees, train the policy and/or the value model, gate, publish."""

import dataclasses
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import torch

from lean_search.expert_iteration.serving import LoopPaths, ModelVersion, Publisher, read_current, record_published
from lean_search.expert_iteration.shards import now
from lean_search.monitoring.families import GrpoPhase
from lean_search.reasoning.dataset import ReasoningExample, tokenize_reasoning_example
from lean_search.rl.grpo_groups import PolicyGroup, RewardConfig, policy_groups
from lean_search.rl.policy_data import ExpansionTexts, PolicyDataMetrics, PolicyTokenizer, build_policy_data
from lean_search.rl.policy_trainer import GrpoConfig, GrpoStepRecord, GrpoTrainingResult, train_grpo
from lean_search.rl.tree_statistics import GraphStatistics, graph_statistics, total_statistics
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import TreeRecord, to_json
from lean_search.search.tactic_labels import policy_tactics
from lean_search.training.math_data import MathSolution, tokenize_math_solution
from lean_search.training.sft_data import TokenizedExample
from lean_search.value.benchmark import LabelledTree, ValueBenchmark
from lean_search.value.graph_targets import (
    RemainingStepsReadout,
    ValueTargetConfig,
    recorded_estimates,
    value_targets,
)
from lean_search.value.graph_trainer import (
    GateResult,
    GraphValueConfig,
    GraphValueStepRecord,
    GraphValueTrainingResult,
    build_graph_value_data,
    run_value_gate,
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
    # value_share (μ) stays 0 until a value model passed the gate.
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
    texts: Sequence[ExpansionTexts] = ()
    lean_replay: Sequence[ReasoningExample] = ()
    math_replay: Sequence[MathSolution] = ()
    value_replay: Sequence[ValueExample] = ()
    # Without a benchmark the new value adapter is trained but not accepted.
    value_benchmark: ValueBenchmark | None = None


@dataclass(frozen=True)
class LabelledPhaseData:
    trees: tuple[LabelledTree, ...]
    groups: tuple[PolicyGroup, ...]
    # Summed over the trees, for the search family of the dashboard.
    statistics: GraphStatistics


@dataclass(frozen=True)
class PolicyOutcome:
    adapter: str
    data: PolicyDataMetrics
    replay_examples: int
    result: GrpoTrainingResult


@dataclass(frozen=True)
class ValueOutcome:
    adapter: str
    result: GraphValueTrainingResult
    gate: GateResult | None

    @property
    def accepted(self) -> bool:
        return self.gate is not None and self.gate.passed


@dataclass(frozen=True)
class PhaseOutcome:
    trees: int
    groups: int
    policy: PolicyOutcome | None
    value: ValueOutcome | None


def label_phase_data(records: Sequence[TreeRecord], config: TrainingPhaseConfig) -> LabelledPhaseData:
    """Value targets from the recorded estimates (the value version that ran the search) and the GRPO groups."""
    trees = []
    groups: list[PolicyGroup] = []
    statistics = []
    for record in records:
        labels = label_graph(record)
        estimates = recorded_estimates(record, config.readout)
        targets = value_targets(record, labels, estimates, config.value_targets)
        tactics = policy_tactics(record, labels)
        tree_groups = policy_groups(record, labels, tactics, estimates, config.reward)
        trees.append(LabelledTree(record, labels, targets))
        groups.extend(tree_groups)
        statistics.append(graph_statistics(record, labels, targets, tactics, tree_groups))
    return LabelledPhaseData(tuple(trees), tuple(groups), total_statistics(statistics))


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
) -> PolicyOutcome:
    data = build_policy_data(labelled.groups, inputs.texts, tokenizer, grpo.data)
    replay = policy_replay_examples(tokenizer, inputs, config.policy_replay, grpo.max_sequence_tokens)
    adapter = directory / "adapter"
    result = train_grpo(grpo, tokenizer.pad_token_id, data.sequences, replay, device, adapter, on_step)
    return PolicyOutcome(str(adapter), data.metrics, len(replay), result)


def train_value_phase(
    config: TrainingPhaseConfig,
    value: GraphValueConfig,
    labelled: LabelledPhaseData,
    inputs: PhaseInputs,
    tokenizer: ValueTokenizer,
    pad_token_id: int,
    device: torch.device,
    directory: Path,
    on_step: Callable[[GraphValueStepRecord], None],
) -> ValueOutcome:
    data = build_graph_value_data(labelled.trees, config.ranking, inputs.value_replay, tokenizer, value)
    adapter = directory / "adapter"
    result = train_graph_value_model(value, tokenizer, pad_token_id, data, device, adapter, on_step)
    gate = None
    if inputs.value_benchmark is not None:
        gate = run_value_gate(
            value, tokenizer, pad_token_id, inputs.value_benchmark, str(adapter), value.initial_adapter, device
        )
    return ValueOutcome(str(adapter), result, gate)


def run_training_phase(
    config: TrainingPhaseConfig,
    inputs: PhaseInputs,
    policy_tokenizer: PolicyTokenizer | None,
    value_tokenizer: ValueTokenizer | None,
    device: torch.device,
    output_directory: Path,
) -> PhaseOutcome:
    """Adapters under output_directory/{policy,value}/adapter, step records next to them, phase.json at the top."""
    labelled = label_phase_data(inputs.records, config)
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
        )
        if device.type == "cuda":
            torch.cuda.empty_cache()
    value = None
    if config.value is not None:
        assert value_tokenizer is not None
        directory = output_directory / "value"
        value = train_value_phase(
            config,
            config.value,
            labelled,
            inputs,
            value_tokenizer,
            value_tokenizer.pad_token_id,
            device,
            directory,
            lambda record: append_json_line(directory / "steps.jsonl", record),
        )
    outcome = PhaseOutcome(len(labelled.trees), len(labelled.groups), policy, value)
    (output_directory / "phase.json").write_text(to_json(outcome), encoding="utf-8")
    return outcome


def grpo_phase_record(policy: PolicyOutcome, sampling_seconds: float | None) -> GrpoPhase:
    """The phase's line of the dashboard's grpo family; `sampling_seconds` is the search time behind the data."""
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
        forced_answers_kept=data.forced_sequences,
        retokenized_sequences=data.retokenized_sequences,
        sampling_seconds=sampling_seconds,
    )


def publish_phase(paths: LoopPaths, publisher: Publisher, outcome: PhaseOutcome, trigger: str) -> ModelVersion:
    """The next version: the new policy adapter if one trained, the new value adapter only if it passed the gate."""
    current = read_current(paths)
    version = ModelVersion(
        version=current.version + 1,
        policy_adapter=current.policy_adapter if outcome.policy is None else outcome.policy.adapter,
        value_adapter=outcome.value.adapter
        if outcome.value is not None and outcome.value.accepted
        else current.value_adapter,
        published_at=now(),
        trigger=trigger,
    )
    prepared = publisher.prepare(version)
    record_published(paths, prepared)
    publisher.prune(prepared)
    return prepared
