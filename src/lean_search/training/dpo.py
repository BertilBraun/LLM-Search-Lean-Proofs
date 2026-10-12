"""DPO of a LoRA policy adapter on completion tokens; the reference is the starting adapter, frozen by precomputing."""

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import torch
import torch.nn.functional as functional
import transformers

from lean_search.training.dpo_data import TokenizedPair
from lean_search.training.sft import (
    Batch,
    CompletionLoss,
    LoraSettings,
    OptimizationConfig,
    collate,
    learning_rate_factor,
    length_grouped_micro_batches,
    load_trainable_model,
    trainable_parameters,
)


@dataclass(frozen=True)
class DpoEvaluationConfig:
    interval_steps: int = 50
    validation_pairs: int = 1000
    micro_batch_tokens: int = 16384


@dataclass(frozen=True)
class DpoConfig:
    model: str
    # The adapter to improve; its frozen starting weights are the reference.
    initial_adapter: str
    data: str
    beta: float = 0.1
    # Weight of the chosen completions' mean token negative log-likelihood, added to keep their likelihood up.
    chosen_nll_weight: float = 0.0
    max_prompt_tokens: int = 2048
    max_completion_tokens: int = 256
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    evaluation: DpoEvaluationConfig = field(default_factory=DpoEvaluationConfig)


@dataclass(frozen=True)
class SequenceLogProbabilities:
    chosen: torch.Tensor
    rejected: torch.Tensor


@dataclass(frozen=True)
class DpoLosses:
    losses: torch.Tensor
    chosen_rewards: torch.Tensor
    rejected_rewards: torch.Tensor


@dataclass(frozen=True)
class DpoMetrics:
    pairs: int
    loss: float
    # Pairs whose chosen reward beta * (log pi - log pi_ref) exceeds the rejected one.
    reward_accuracy: float
    reward_margin: float
    chosen_reward: float
    rejected_reward: float
    # Pairs where the policy itself gives the chosen completion the higher log-probability.
    chosen_preferred: float


@dataclass(frozen=True)
class PairStep:
    micro_batches: tuple[tuple[int, ...], ...]
    pairs: int
    chosen_completion_tokens: int


@dataclass(frozen=True)
class DpoStepRecord:
    step: int
    epoch: float
    learning_rate: float
    metrics: DpoMetrics
    chosen_nll: float
    gradient_norm: float
    tokens: int
    padded_tokens: int
    training_seconds: float
    tokens_per_second: float


@dataclass(frozen=True)
class DpoEvaluationRecord:
    step: int
    metrics: DpoMetrics
    seconds: float


@dataclass(frozen=True)
class DpoTrainingResult:
    steps: int
    pairs: int
    tokens: int
    padded_tokens: int
    training_seconds: float
    tokens_per_second: float
    peak_memory_gib: float
    trainable_parameters: int
    reference_seconds: float
    evaluations: tuple[DpoEvaluationRecord, ...]


def dpo_losses(policy: SequenceLogProbabilities, reference: SequenceLogProbabilities, beta: float) -> DpoLosses:
    chosen_rewards = beta * (policy.chosen - reference.chosen)
    rejected_rewards = beta * (policy.rejected - reference.rejected)
    return DpoLosses(-functional.logsigmoid(chosen_rewards - rejected_rewards), chosen_rewards, rejected_rewards)


def dpo_metrics(policy: SequenceLogProbabilities, reference: SequenceLogProbabilities, beta: float) -> DpoMetrics:
    losses = dpo_losses(policy, reference, beta)
    margins = losses.chosen_rewards - losses.rejected_rewards
    return DpoMetrics(
        pairs=len(margins),
        loss=losses.losses.mean().item(),
        reward_accuracy=(margins > 0).float().mean().item(),
        reward_margin=margins.mean().item(),
        chosen_reward=losses.chosen_rewards.mean().item(),
        rejected_reward=losses.rejected_rewards.mean().item(),
        chosen_preferred=(policy.chosen > policy.rejected).float().mean().item(),
    )


def sequence_log_probabilities(token_losses: torch.Tensor, rows: torch.Tensor, row_count: int) -> torch.Tensor:
    """Per row, the summed log-probability of its completion tokens, from per-token negative log-likelihoods."""
    totals = torch.zeros(row_count, dtype=token_losses.dtype, device=token_losses.device)
    return -totals.index_add(0, rows, token_losses)


def pair_batch(pairs: Sequence[TokenizedPair], pad_token_id: int, device: torch.device) -> Batch:
    """Chosen completions in the first rows, rejected ones in the rows after them."""
    return collate([pair.chosen for pair in pairs] + [pair.rejected for pair in pairs], pad_token_id, device)


def plan_pair_steps(pairs: Sequence[TokenizedPair], config: OptimizationConfig) -> list[PairStep]:
    generator = random.Random(config.seed)
    lengths = [pair.padded_length for pair in pairs]
    steps: list[PairStep] = []
    for _ in range(config.epochs):
        micro_batches = length_grouped_micro_batches(
            lengths, config.micro_batch_tokens, config.length_group_examples, generator
        )
        # The last incomplete step of an epoch is dropped so every step has the same number of micro-batches.
        for start in range(0, len(micro_batches) - config.micro_batches_per_step + 1, config.micro_batches_per_step):
            step_batches = tuple(micro_batches[start : start + config.micro_batches_per_step])
            indices = [index for batch in step_batches for index in batch]
            chosen_tokens = sum(pairs[index].chosen.completion_token_count for index in indices)
            steps.append(PairStep(step_batches, len(indices), chosen_tokens))
    return steps[: config.max_steps] if config.max_steps else steps


class PairScorer:
    """Completion log-probabilities of chosen and rejected sequences under the model being trained."""

    def __init__(self, causal_model: transformers.PreTrainedModel, pad_token_id: int, device: torch.device) -> None:
        self.loss_module = CompletionLoss(causal_model)
        self.pad_token_id = pad_token_id
        self.device = device

    def score(self, pairs: Sequence[TokenizedPair]) -> tuple[SequenceLogProbabilities, torch.Tensor]:
        """The log-probabilities, and the chosen completions' summed token negative log-likelihood."""
        batch = pair_batch(pairs, self.pad_token_id, self.device)
        with torch.autocast(self.device.type, dtype=torch.bfloat16):
            token_losses, _, rows = self.loss_module(batch.input_ids, batch.attention_mask, batch.labels)
        log_probabilities = sequence_log_probabilities(token_losses, rows, 2 * len(pairs))
        chosen_nll = token_losses[rows < len(pairs)].sum()
        return SequenceLogProbabilities(log_probabilities[: len(pairs)], log_probabilities[len(pairs) :]), chosen_nll

    @torch.no_grad()
    def score_all(self, pairs: Sequence[TokenizedPair], micro_batch_tokens: int) -> SequenceLogProbabilities:
        lengths = [pair.padded_length for pair in pairs]
        micro_batches = length_grouped_micro_batches(lengths, micro_batch_tokens, len(pairs), random.Random(0))
        chosen = torch.zeros(len(pairs))
        rejected = torch.zeros(len(pairs))
        for micro_batch in micro_batches:
            scores, _ = self.score([pairs[index] for index in micro_batch])
            indices = torch.tensor(micro_batch)
            chosen[indices] = scores.chosen.float().cpu()
            rejected[indices] = scores.rejected.float().cpu()
        return SequenceLogProbabilities(chosen, rejected)


def select_scores(
    scores: SequenceLogProbabilities, indices: Sequence[int], device: torch.device
) -> SequenceLogProbabilities:
    selected = torch.tensor(indices)
    return SequenceLogProbabilities(scores.chosen[selected].to(device), scores.rejected[selected].to(device))


def train_dpo(
    config: DpoConfig,
    tokenizer: transformers.PreTrainedTokenizerBase,
    train_pairs: Sequence[TokenizedPair],
    validation_pairs: Sequence[TokenizedPair],
    device: torch.device,
    output_directory: Path,
    on_step: Callable[[DpoStepRecord], None],
    on_evaluation: Callable[[DpoEvaluationRecord], None],
) -> DpoTrainingResult:
    optimization = config.optimization
    saved_module, causal_model = load_trainable_model(
        config.model, optimization, LoraSettings(), device, config.initial_adapter
    )
    scorer = PairScorer(causal_model, tokenizer.pad_token_id, device)
    validation = validation_pairs[: config.evaluation.validation_pairs]
    reference_started = time.perf_counter()
    causal_model.eval()
    train_reference = scorer.score_all(train_pairs, config.evaluation.micro_batch_tokens)
    validation_reference = scorer.score_all(validation, config.evaluation.micro_batch_tokens)
    causal_model.train()
    reference_seconds = time.perf_counter() - reference_started
    parameters = trainable_parameters(saved_module)
    optimizer = torch.optim.AdamW(
        parameters,
        lr=optimization.learning_rate,
        weight_decay=optimization.weight_decay,
        fused=device.type == "cuda",
    )
    steps = plan_pair_steps(train_pairs, optimization)
    warmup_steps = max(1, round(optimization.warmup_fraction * len(steps)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: learning_rate_factor(step, warmup_steps, len(steps), optimization.minimum_learning_rate_ratio),
    )
    steps_per_epoch = len(steps) / optimization.epochs
    evaluations: list[DpoEvaluationRecord] = []

    def evaluate_now(step: int) -> None:
        started = time.perf_counter()
        causal_model.eval()
        policy = scorer.score_all(validation, config.evaluation.micro_batch_tokens)
        causal_model.train()
        record = DpoEvaluationRecord(
            step, dpo_metrics(policy, validation_reference, config.beta), time.perf_counter() - started
        )
        evaluations.append(record)
        on_evaluation(record)

    if validation:
        evaluate_now(0)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    training_seconds = 0.0
    total_tokens = 0
    total_padded_tokens = 0
    for step_index, step in enumerate(steps):
        step_start = time.perf_counter()
        step_policy: list[SequenceLogProbabilities] = []
        step_reference: list[SequenceLogProbabilities] = []
        chosen_nll_sum = 0.0
        tokens = 0
        padded_tokens = 0
        for micro_batch in step.micro_batches:
            batch_pairs = [train_pairs[index] for index in micro_batch]
            policy, chosen_nll = scorer.score(batch_pairs)
            reference = select_scores(train_reference, micro_batch, device)
            loss = dpo_losses(policy, reference, config.beta).losses.sum() / step.pairs
            if config.chosen_nll_weight:
                loss = loss + config.chosen_nll_weight * chosen_nll / step.chosen_completion_tokens
            loss.backward()
            step_policy.append(SequenceLogProbabilities(policy.chosen.detach(), policy.rejected.detach()))
            step_reference.append(reference)
            chosen_nll_sum += chosen_nll.item()
            tokens += sum(pair.token_count for pair in batch_pairs)
            padded_tokens += (
                2
                * len(batch_pairs)
                * max(max(pair.chosen.token_count, pair.rejected.token_count) for pair in batch_pairs)
            )
        gradient_norm = torch.nn.utils.clip_grad_norm_(parameters, optimization.max_gradient_norm).item()
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        training_seconds += time.perf_counter() - step_start
        total_tokens += tokens
        total_padded_tokens += padded_tokens
        on_step(
            DpoStepRecord(
                step=step_index + 1,
                epoch=(step_index + 1) / steps_per_epoch,
                learning_rate=scheduler.get_last_lr()[0],
                metrics=dpo_metrics(concatenate(step_policy), concatenate(step_reference), config.beta),
                chosen_nll=chosen_nll_sum / step.chosen_completion_tokens,
                gradient_norm=gradient_norm,
                tokens=tokens,
                padded_tokens=padded_tokens,
                training_seconds=training_seconds,
                tokens_per_second=total_tokens / training_seconds,
            )
        )
        is_last = step_index == len(steps) - 1
        if validation and (is_last or (step_index + 1) % config.evaluation.interval_steps == 0):
            evaluate_now(step_index + 1)
    saved_module.save_pretrained(output_directory)
    return DpoTrainingResult(
        steps=len(steps),
        pairs=sum(step.pairs for step in steps),
        tokens=total_tokens,
        padded_tokens=total_padded_tokens,
        training_seconds=training_seconds,
        tokens_per_second=total_tokens / training_seconds if training_seconds else 0.0,
        peak_memory_gib=torch.cuda.max_memory_allocated(device) / 2**30 if device.type == "cuda" else 0.0,
        trainable_parameters=sum(parameter.numel() for parameter in parameters),
        reference_seconds=reference_seconds,
        evaluations=tuple(evaluations),
    )


def concatenate(scores: Sequence[SequenceLogProbabilities]) -> SequenceLogProbabilities:
    return SequenceLogProbabilities(
        torch.cat([score.chosen for score in scores]), torch.cat([score.rejected for score in scores])
    )
