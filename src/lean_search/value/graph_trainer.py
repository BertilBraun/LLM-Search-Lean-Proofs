"""Value LoRA training on search-graph targets: soft bin targets plus a sibling ranking loss, and the publish gate."""

import hashlib
import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import peft
import torch
import torch.nn.functional as functional

from lean_search.policy.adapters import load_base_model
from lean_search.training.packing import packed_positions, sequence_starts
from lean_search.training.sft import (
    LoraSettings,
    OptimizationConfig,
    learning_rate_factor,
    load_trainable_model,
    trainable_parameters,
)
from lean_search.value.benchmark import BenchmarkConfig, BenchmarkMetrics, LabelledTree, ValueBenchmark
from lean_search.value.benchmark import benchmark_metrics as compute_benchmark_metrics
from lean_search.value.bins import BIN_COUNT, DEAD_BIN, STEP_BIN_COUNT, Readout
from lean_search.value.graph_targets import (
    SourceShares,
    ValueEstimate,
    ValueTarget,
    balanced_weights,
    bin_estimate,
    bin_target,
    step_bin_masses,
)
from lean_search.value.labels import LabelKind, ValueExample
from lean_search.value.loss import bin_mass_losses
from lean_search.value.prompts import ValueTokenizer, bin_token_ids, render_value_prompt
from lean_search.value.ranking import PairKind, RankingConfig, SiblingPair, sibling_pairs
from lean_search.value.training import LastPositionLogits, PromptBatch


class RankingScore(StrEnum):
    # log(1 - p_dead) - log(p_dead): monotone in the proof probability without saturating near 0 and 1.
    LOG_ODDS = "log_odds"
    PROBABILITY = "probability"


@dataclass(frozen=True)
class GateConfig:
    # The new model must beat the current one's sibling pairwise accuracy by this much...
    min_ranking_gain: float = 0.01
    # ...without losing more than this in proof-graph-over-dead-end AUC or gaining more in the anchors' Brier score.
    max_separation_drop: float = 0.02
    max_brier_increase: float = 0.01


@dataclass(frozen=True)
class GraphValueConfig:
    model: str
    # The current value adapter, continued unless retrain_from_base; empty starts a fresh adapter.
    initial_adapter: str = ""
    retrain_from_base: bool = False
    lora: LoraSettings = field(default_factory=LoraSettings)
    # micro_batch_tokens: padded prompt tokens (real ones when packing), filled with whole sibling units.
    optimization: OptimizationConfig = field(
        default_factory=lambda: OptimizationConfig(
            learning_rate=5e-5, minimum_learning_rate_ratio=1.0, micro_batch_tokens=32768, micro_batches_per_step=1
        )
    )
    max_prompt_tokens: int = 2048
    # Spread of a target's remaining steps over the step bins (as for v0).
    smoothing_sigma: float = 0.5
    bin_mass_weight: float = 1.0
    # Mixing factor of the sibling ranking loss against the pointwise loss.
    ranking_weight: float = 0.5
    ranking_score: RankingScore = RankingScore.LOG_ODDS
    ranking_temperature: float = 1.0
    # Per step, each target source present holds this share of the pointwise weight.
    source_shares: SourceShares = field(default_factory=SourceShares)
    # 0: no cap; the heaviest pairs are kept.
    max_pairs_per_tree: int = 64
    # v0 examples (exact and dead labels) as this share of all pointwise items.
    replay_share: float = 0.1
    readout: Readout = field(default_factory=Readout)
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    gate: GateConfig = field(default_factory=GateConfig)


@dataclass(frozen=True)
class ValueState:
    problem_name: str
    node_id: int
    input_ids: tuple[int, ...]

    @property
    def token_count(self) -> int:
        return len(self.input_ids)


@dataclass(frozen=True)
class PointwiseItem:
    state: int
    distribution: tuple[float, ...]
    weight: float
    # None for a v0 replay example.
    target: ValueTarget | None


@dataclass(frozen=True)
class PairItem:
    preferred: int
    other: int
    weight: float
    kind: PairKind


@dataclass(frozen=True)
class TrainingUnit:
    """States trained together: the siblings of one parent with their pairs, or a single state."""

    states: tuple[int, ...]
    pointwise: tuple[int, ...]
    pairs: tuple[int, ...]


@dataclass(frozen=True)
class GraphValueData:
    states: tuple[ValueState, ...]
    pointwise: tuple[PointwiseItem, ...]
    pairs: tuple[PairItem, ...]
    units: tuple[TrainingUnit, ...]
    replay_items: int
    dropped_replay_examples: int
    over_length_states: int


@dataclass(frozen=True)
class ValueMicroBatch:
    states: tuple[int, ...]
    pointwise: tuple[int, ...]
    pairs: tuple[int, ...]


@dataclass(frozen=True)
class GraphValueStep:
    micro_batches: tuple[ValueMicroBatch, ...]
    # Per pointwise item of the step, its weight after the step's class balance.
    pointwise_weights: tuple[tuple[int, float], ...]
    pointwise_weight: float
    pair_weight: float


@dataclass(frozen=True)
class GraphValueStepRecord:
    step: int
    learning_rate: float
    # Weighted means over the step's items.
    pointwise_loss: float
    bin_mass_loss: float
    ranking_loss: float
    # Pairs whose preferred state scores higher.
    pair_accuracy: float
    gradient_norm: float
    states: int
    pointwise_items: int
    pairs: int
    training_seconds: float


@dataclass(frozen=True)
class GraphValueTrainingResult:
    steps: int
    states: int
    pointwise_items: int
    replay_items: int
    pairs: int
    training_seconds: float
    trainable_parameters: int
    final_pointwise_loss: float
    final_ranking_loss: float
    final_pair_accuracy: float


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: tuple[str, ...]
    new: BenchmarkMetrics
    current: BenchmarkMetrics


def stable_key(*parts: object) -> str:
    return hashlib.sha256("/".join(str(part) for part in parts).encode()).hexdigest()


def capped_pairs(problem_name: str, pairs: Sequence[SiblingPair], max_pairs: int) -> list[SiblingPair]:
    if not max_pairs or len(pairs) <= max_pairs:
        return list(pairs)
    return sorted(
        pairs,
        key=lambda pair: (-pair.weight, stable_key(problem_name, pair.parent_id, pair.preferred_id, pair.other_id)),
    )[:max_pairs]


def replay_distribution(example: ValueExample, sigma: float) -> tuple[float, ...] | None:
    """Exact and dead v0 labels as nine-bin targets; censored ones have no single target."""
    match example.kind:
        case LabelKind.EXACT:
            return (*step_bin_masses(float(example.steps), sigma), 0.0)
        case LabelKind.DEAD:
            return tuple(float(index == DEAD_BIN) for index in range(BIN_COUNT))
        case LabelKind.AT_LEAST:
            return None


class StateTable:
    def __init__(self, tokenizer: ValueTokenizer, max_prompt_tokens: int) -> None:
        self.tokenizer = tokenizer
        self.max_prompt_tokens = max_prompt_tokens
        self.states: list[ValueState] = []
        self.index: dict[tuple[str, int], int | None] = {}
        self.over_length = 0

    def add(self, problem_name: str, node_id: int, goals: Sequence[str]) -> int | None:
        key = (problem_name, node_id)
        if key not in self.index:
            input_ids = tuple(
                self.tokenizer.encode(render_value_prompt(self.tokenizer, goals), add_special_tokens=False)
            )
            if len(input_ids) > self.max_prompt_tokens:
                self.over_length += 1
                self.index[key] = None
            else:
                self.index[key] = len(self.states)
                self.states.append(ValueState(problem_name, node_id, input_ids))
        return self.index[key]


def build_graph_value_data(
    trees: Sequence[LabelledTree],
    ranking: RankingConfig,
    replay: Sequence[ValueExample],
    tokenizer: ValueTokenizer,
    config: GraphValueConfig,
) -> GraphValueData:
    """Units per tree: each parent's pair members with their pairs and targets, then every other target alone."""
    table = StateTable(tokenizer, config.max_prompt_tokens)
    pointwise: list[PointwiseItem] = []
    pairs: list[PairItem] = []
    units: list[TrainingUnit] = []
    for tree in trees:
        record = tree.record
        tree_pairs = capped_pairs(record.problem_name, sibling_pairs(tree.labels, ranking), config.max_pairs_per_tree)
        targets = {target.node_id: target for target in tree.targets}
        assigned: set[int] = set()
        by_parent: dict[int, list[SiblingPair]] = {}
        for pair in tree_pairs:
            by_parent.setdefault(pair.parent_id, []).append(pair)
        for parent_pairs in by_parent.values():
            state_by_node: dict[int, int] = {}
            pair_indices = []
            for pair in parent_pairs:
                preferred = table.add(record.problem_name, pair.preferred_id, record.nodes[pair.preferred_id].goals)
                other = table.add(record.problem_name, pair.other_id, record.nodes[pair.other_id].goals)
                if preferred is None or other is None:
                    continue
                state_by_node |= {pair.preferred_id: preferred, pair.other_id: other}
                pair_indices.append(len(pairs))
                pairs.append(PairItem(preferred, other, pair.weight, pair.kind))
            pointwise_indices = []
            for node_id, state in state_by_node.items():
                if node_id in targets and node_id not in assigned:
                    assigned.add(node_id)
                    pointwise_indices.append(len(pointwise))
                    pointwise.append(graph_item(state, targets[node_id], config))
            if pair_indices:
                units.append(TrainingUnit(tuple(state_by_node.values()), tuple(pointwise_indices), tuple(pair_indices)))
        for target in tree.targets:
            if target.node_id in assigned:
                continue
            state = table.add(record.problem_name, target.node_id, target.goals)
            if state is not None:
                units.append(TrainingUnit((state,), (len(pointwise),), ()))
                pointwise.append(graph_item(state, target, config))
    replay_count = round(config.replay_share / (1 - config.replay_share) * len(pointwise)) if pointwise else 0
    usable = [
        (example, distribution)
        for example in replay
        if (distribution := replay_distribution(example, config.smoothing_sigma)) is not None
    ]
    chosen = sorted(usable, key=lambda item: stable_key(item[0].identifier, item[0].depth, item[0].goals))
    replay_items = 0
    for number, (example, distribution) in enumerate(chosen[:replay_count]):
        state = table.add("replay", number, example.goals)
        if state is not None:
            units.append(TrainingUnit((state,), (len(pointwise),), ()))
            pointwise.append(PointwiseItem(state, distribution, example.weight, None))
            replay_items += 1
    return GraphValueData(
        states=tuple(table.states),
        pointwise=tuple(pointwise),
        pairs=tuple(pairs),
        units=tuple(units),
        replay_items=replay_items,
        dropped_replay_examples=len(replay) - len(usable),
        over_length_states=table.over_length,
    )


def graph_item(state: int, target: ValueTarget, config: GraphValueConfig) -> PointwiseItem:
    return PointwiseItem(state, bin_target(target, config.smoothing_sigma), target.weight, target)


def unit_cost(unit: TrainingUnit, states: Sequence[ValueState]) -> tuple[int, int]:
    """Real tokens and the longest prompt of a unit."""
    lengths = [states[state].token_count for state in unit.states]
    return sum(lengths), max(lengths)


def plan_unit_micro_batches(
    units: Sequence[TrainingUnit], states: Sequence[ValueState], max_tokens: int, packing: bool, order: Sequence[int]
) -> list[ValueMicroBatch]:
    micro_batches: list[ValueMicroBatch] = []
    current: list[TrainingUnit] = []
    real_tokens = longest = state_count = 0
    for index in order:
        unit = units[index]
        tokens, unit_longest = unit_cost(unit, states)
        new_longest = max(longest, unit_longest)
        new_cost = real_tokens + tokens if packing else new_longest * (state_count + len(unit.states))
        if current and new_cost > max_tokens:
            micro_batches.append(merged_micro_batch(current))
            current, real_tokens, longest, state_count = [], 0, 0, 0
            new_longest = unit_longest
        current.append(unit)
        real_tokens += tokens
        longest = new_longest
        state_count += len(unit.states)
    if current:
        micro_batches.append(merged_micro_batch(current))
    return micro_batches


def merged_micro_batch(units: Sequence[TrainingUnit]) -> ValueMicroBatch:
    states = dict.fromkeys(state for unit in units for state in unit.states)
    return ValueMicroBatch(
        tuple(states),
        tuple(index for unit in units for index in unit.pointwise),
        tuple(index for unit in units for index in unit.pairs),
    )


def balanced_step_weights(items: Sequence[int], data: GraphValueData, shares: SourceShares) -> list[tuple[int, float]]:
    """The step's graph targets rebalanced across sources; replay items keep their weights."""
    graph = [(index, target) for index in items if (target := data.pointwise[index].target) is not None]
    balanced = balanced_weights([target for _, target in graph], shares)
    weights = {index: target.weight for (index, _), target in zip(graph, balanced, strict=True)}
    return [(index, weights.get(index, data.pointwise[index].weight)) for index in items]


def plan_graph_value_steps(data: GraphValueData, config: GraphValueConfig) -> list[GraphValueStep]:
    optimization = config.optimization
    generator = random.Random(optimization.seed)
    steps: list[GraphValueStep] = []
    for _ in range(optimization.epochs):
        order = list(range(len(data.units)))
        generator.shuffle(order)
        micro_batches = plan_unit_micro_batches(
            data.units, data.states, optimization.micro_batch_tokens, optimization.packing, order
        )
        for start in range(0, len(micro_batches), optimization.micro_batches_per_step):
            step_batches = tuple(micro_batches[start : start + optimization.micro_batches_per_step])
            items = [index for batch in step_batches for index in batch.pointwise]
            weights = balanced_step_weights(items, data, config.source_shares)
            steps.append(
                GraphValueStep(
                    micro_batches=step_batches,
                    pointwise_weights=tuple(weights),
                    pointwise_weight=sum(weight for _, weight in weights),
                    pair_weight=sum(data.pairs[index].weight for batch in step_batches for index in batch.pairs),
                )
            )
    return steps[: optimization.max_steps] if optimization.max_steps else steps


def soft_target_losses(bin_logits: torch.Tensor, distributions: torch.Tensor) -> torch.Tensor:
    return -(distributions * torch.log_softmax(bin_logits.float(), dim=-1)).sum(dim=-1)


def ranking_scores(bin_logits: torch.Tensor, score: RankingScore) -> torch.Tensor:
    log_probabilities = torch.log_softmax(bin_logits.float(), dim=-1)
    alive = torch.logsumexp(log_probabilities[:, :STEP_BIN_COUNT], dim=-1)
    match score:
        case RankingScore.LOG_ODDS:
            return alive - log_probabilities[:, DEAD_BIN]
        case RankingScore.PROBABILITY:
            return alive.exp()


def ranking_losses(preferred: torch.Tensor, other: torch.Tensor, temperature: float) -> torch.Tensor:
    """Logistic loss on the score difference: -log sigmoid((preferred - other) / temperature)."""
    return functional.softplus(-(preferred - other) / temperature)


def state_batch(states: Sequence[ValueState], packing: bool, pad_token_id: int, device: torch.device) -> PromptBatch:
    lengths = [state.token_count for state in states]
    if packing:
        starts = sequence_starts(lengths)
        input_ids = torch.tensor([token for state in states for token in state.input_ids]).unsqueeze(0)
        last_positions = torch.tensor(starts[1:]) - 1
        return PromptBatch(
            input_ids.to(device), None, last_positions.to(device), packed_positions(lengths).to(device), starts
        )
    width = max(lengths)
    input_ids = torch.full((len(states), width), pad_token_id, dtype=torch.long)
    attention_mask = torch.zeros((len(states), width), dtype=torch.long)
    for row, state in enumerate(states):
        input_ids[row, : state.token_count] = torch.tensor(state.input_ids)
        attention_mask[row, : state.token_count] = 1
    return PromptBatch(input_ids.to(device), attention_mask.to(device), torch.tensor(lengths, device=device) - 1)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def train_graph_value_model(
    config: GraphValueConfig,
    tokenizer: ValueTokenizer,
    pad_token_id: int,
    data: GraphValueData,
    device: torch.device,
    output_directory: Path,
    on_step: Callable[[GraphValueStepRecord], None],
) -> GraphValueTrainingResult:
    optimization = config.optimization
    initial_adapter = "" if config.retrain_from_base else config.initial_adapter
    saved_module, causal_model = load_trainable_model(config.model, optimization, config.lora, device, initial_adapter)
    model = LastPositionLogits(causal_model)
    bin_ids = torch.tensor(bin_token_ids(tokenizer), device=device)
    parameters = trainable_parameters(saved_module)
    optimizer = torch.optim.AdamW(
        parameters, lr=optimization.learning_rate, weight_decay=optimization.weight_decay, fused=device.type == "cuda"
    )
    steps = plan_graph_value_steps(data, config)
    warmup_steps = max(1, round(optimization.warmup_fraction * len(steps)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: learning_rate_factor(step, warmup_steps, len(steps), optimization.minimum_learning_rate_ratio),
    )
    records: list[GraphValueStepRecord] = []
    training_seconds = 0.0
    for step_index, step in enumerate(steps):
        started = time.perf_counter()
        weights = dict(step.pointwise_weights)
        totals = torch.zeros(4, dtype=torch.float64, device=device)
        states = pointwise_items = pairs = 0
        for micro in step.micro_batches:
            row = {state: position for position, state in enumerate(micro.states)}
            batch = state_batch(
                [data.states[state] for state in micro.states], optimization.packing, pad_token_id, device
            )
            with torch.autocast(device.type, dtype=torch.bfloat16):
                full_logits = model(batch)
            bin_logits = full_logits[:, bin_ids].float()
            loss = torch.zeros((), device=device)
            if micro.pointwise:
                items = [data.pointwise[index] for index in micro.pointwise]
                rows = torch.tensor([row[item.state] for item in items], device=device)
                item_weights = torch.tensor([weights[index] for index in micro.pointwise], device=device)
                distributions = torch.tensor([item.distribution for item in items], device=device)
                losses = soft_target_losses(bin_logits[rows], distributions)
                mass_losses = bin_mass_losses(full_logits[rows], bin_ids)
                loss = (
                    loss
                    + (item_weights * (losses + config.bin_mass_weight * mass_losses)).sum() / step.pointwise_weight
                )
                totals[0] += (item_weights * losses).detach().sum()
                totals[1] += (item_weights * mass_losses).detach().sum()
            if micro.pairs and step.pair_weight > 0:
                pair_items = [data.pairs[index] for index in micro.pairs]
                scores = ranking_scores(bin_logits, config.ranking_score)
                preferred = scores[torch.tensor([row[pair.preferred] for pair in pair_items], device=device)]
                other = scores[torch.tensor([row[pair.other] for pair in pair_items], device=device)]
                pair_weights = torch.tensor([pair.weight for pair in pair_items], device=device)
                losses = ranking_losses(preferred, other, config.ranking_temperature)
                loss = loss + config.ranking_weight * (pair_weights * losses).sum() / step.pair_weight
                totals[2] += (pair_weights * losses).detach().sum()
                totals[3] += (preferred > other).detach().sum()
            loss.backward()
            states += len(micro.states)
            pointwise_items += len(micro.pointwise)
            pairs += len(micro.pairs)
        gradient_norm = torch.nn.utils.clip_grad_norm_(parameters, optimization.max_gradient_norm).item()
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        training_seconds += time.perf_counter() - started
        pointwise_loss, mass_loss, ranking_loss, correct_pairs = totals.tolist()
        record = GraphValueStepRecord(
            step=step_index + 1,
            learning_rate=scheduler.get_last_lr()[0],
            pointwise_loss=pointwise_loss / step.pointwise_weight if step.pointwise_weight else 0.0,
            bin_mass_loss=mass_loss / step.pointwise_weight if step.pointwise_weight else 0.0,
            ranking_loss=ranking_loss / step.pair_weight if step.pair_weight else 0.0,
            pair_accuracy=correct_pairs / pairs if pairs else 0.0,
            gradient_norm=gradient_norm,
            states=states,
            pointwise_items=pointwise_items,
            pairs=pairs,
            training_seconds=training_seconds,
        )
        records.append(record)
        on_step(record)
    saved_module.save_pretrained(output_directory)
    last = records[-max(1, len(records) // 10) :]
    return GraphValueTrainingResult(
        steps=len(steps),
        states=len(data.states),
        pointwise_items=len(data.pointwise),
        replay_items=data.replay_items,
        pairs=len(data.pairs),
        training_seconds=training_seconds,
        trainable_parameters=sum(parameter.numel() for parameter in parameters),
        final_pointwise_loss=mean([record.pointwise_loss for record in last]),
        final_ranking_loss=mean([record.ranking_loss for record in last if record.pairs]),
        final_pair_accuracy=mean([record.pair_accuracy for record in last if record.pairs]),
    )


def load_scoring_model(model: str, adapter: str, device: torch.device) -> LastPositionLogits:
    """The base weights with the adapter merged in for inference; no adapter scores the base weights."""
    causal_model = load_base_model(model, device=str(device))
    if adapter:
        causal_model = peft.PeftModel.from_pretrained(causal_model, adapter).merge_and_unload()
    causal_model.eval()
    return LastPositionLogits(causal_model)


@torch.no_grad()
def bin_probabilities(
    model: LastPositionLogits,
    states: Sequence[ValueState],
    bin_ids: torch.Tensor,
    micro_batch_tokens: int,
    pad_token_id: int,
    device: torch.device,
) -> list[tuple[float, ...]]:
    """Each state's distribution over the nine bins (renormalized over the bin tokens)."""
    order = sorted(range(len(states)), key=lambda index: states[index].token_count)
    results: list[tuple[float, ...]] = [()] * len(states)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and states[order[end]].token_count * (end + 1 - start) <= micro_batch_tokens:
            end += 1
        indices = order[start:end]
        batch = state_batch([states[index] for index in indices], False, pad_token_id, device)
        with torch.autocast(device.type, dtype=torch.bfloat16):
            full_logits = model(batch)
        for index, probabilities in zip(
            indices, torch.softmax(full_logits[:, bin_ids].float(), dim=-1).tolist(), strict=True
        ):
            results[index] = tuple(probabilities)
        start = end
    return results


def benchmark_estimates(
    model: LastPositionLogits,
    tokenizer: ValueTokenizer,
    pad_token_id: int,
    benchmark: ValueBenchmark,
    config: GraphValueConfig,
    device: torch.device,
) -> list[ValueEstimate]:
    states = [
        ValueState(
            state.problem_name,
            state.node_id,
            tuple(tokenizer.encode(render_value_prompt(tokenizer, state.goals), add_special_tokens=False)),
        )
        for state in benchmark.states
    ]
    bin_ids = torch.tensor(bin_token_ids(tokenizer), device=device)
    distributions = bin_probabilities(
        model, states, bin_ids, config.optimization.micro_batch_tokens, pad_token_id, device
    )
    return [bin_estimate(probabilities, config.readout) for probabilities in distributions]


def gate_decision(new: BenchmarkMetrics, current: BenchmarkMetrics, config: GateConfig) -> GateResult:
    """Pass when the new model ranks siblings better by min_ranking_gain without regressing beyond the tolerances."""
    reasons = []
    new_ranking, current_ranking = new.ranking.pairwise_accuracy, current.ranking.pairwise_accuracy
    if new_ranking is None:
        reasons.append("no sibling pairs scored")
    elif current_ranking is not None and new_ranking < current_ranking + config.min_ranking_gain:
        reasons.append(f"pairwise accuracy {new_ranking:.3f} < {current_ranking:.3f} + {config.min_ranking_gain:g}")
    new_auc = new.separation.proof_graph_over_dead_end_auc
    current_auc = current.separation.proof_graph_over_dead_end_auc
    if current_auc is not None and (new_auc is None or new_auc < current_auc - config.max_separation_drop):
        reasons.append(f"proof-graph over dead-end AUC {new_auc} < {current_auc:.3f} - {config.max_separation_drop:g}")
    new_brier = new.calibration.anchor_brier_score
    current_brier = current.calibration.anchor_brier_score
    if current_brier is not None and (new_brier is None or new_brier > current_brier + config.max_brier_increase):
        reasons.append(f"anchor Brier {new_brier} > {current_brier:.4f} + {config.max_brier_increase:g}")
    return GateResult(not reasons, tuple(reasons), new, current)


def run_value_gate(
    config: GraphValueConfig,
    tokenizer: ValueTokenizer,
    pad_token_id: int,
    benchmark: ValueBenchmark,
    new_adapter: str,
    current_adapter: str,
    device: torch.device,
) -> GateResult:
    """The benchmark metrics of the new and the current value adapter (one loaded at a time) and the decision."""
    metrics = []
    for adapter in (new_adapter, current_adapter):
        model = load_scoring_model(config.model, adapter, device)
        estimates = benchmark_estimates(model, tokenizer, pad_token_id, benchmark, config, device)
        metrics.append(compute_benchmark_metrics(benchmark, estimates, config.benchmark))
        del model
    return gate_decision(metrics[0], metrics[1], config.gate)
