"""An expert-iteration round inside the loop's persistent training job (rl/README.md, "Expert iteration inside the
loop"). The round's data is what `grpo_expert_iteration.py build` wrote for it, with the Lean and math replay at their
completion-token shares (`expert_iteration_data.training_data`, as the hand-run `train` assembles it). The round
fine-tunes the policy adapter as `train` does with `training/sft.train`: the same step plan, schedule, loss over the
completion tokens, gradient clipping and validation at the start, halfway and the end. It runs on the job's resident
model with the ranks' gradients summed (`data_parallel.sum_gradients`) instead of DDP, as the job's other trainers do:
the same arithmetic, since DDP's mean of the ranks' gradients of `world_size / completion_tokens` times the loss is
their sum at `1 / completion_tokens`."""

import math
import statistics
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import torch

from lean_search.policy.adapters import saved_adapter_weights
from lean_search.rl.expert_iteration_data import (
    ExpertIterationConfig,
    TrainingData,
    ValidationPoint,
    replay_loss_change,
    training_data,
)
from lean_search.rl.policy_data import ParameterChange, PolicyTokenizer
from lean_search.rl.policy_trainer import parameter_change, parameter_snapshot
from lean_search.training.data_parallel import SINGLE_PROCESS, Ranks, barrier, sum_gradients, summed
from lean_search.training.sft import (
    CompletionLoss,
    SftConfig,
    StepRecord,
    TrainableLoader,
    learning_rate_factor,
    load_trainable_model,
    micro_batch,
    plan_steps,
    trainable_parameters,
    validation_metrics,
)
from lean_search.training.sft_data import TokenizedExample

CPU = torch.device("cpu")


@dataclass(frozen=True)
class ExpertIterationResult:
    steps: int
    # The training examples by part (the round's, the Lean replay's, the math replay's) and the round's validation
    # examples.
    examples: int
    lean_replay_examples: int
    math_replay_examples: int
    validation_examples: int
    tokens: int
    # The completion tokens the loss covered, the round's and the replay's.
    trained_tokens: int
    # Means over the steps: the completion-token loss and the total gradient norm before clipping; None without one.
    mean_loss: float | None
    mean_gradient_norm: float | None
    # The LoRA parameters' change over the round (`policy_trainer.parameter_change`, as GRPO's `UpdateSize`); the
    # validation at the start, halfway and the end (the round's loss and the replay's, the forgetting signal); the
    # replay validation loss at the end over the start's, minus 1. The main rank's: None and empty on the others.
    parameter_change: ParameterChange | None
    curve: tuple[ValidationPoint, ...]
    replay_loss_change: float | None
    training_seconds: float


@dataclass(frozen=True)
class ExpertIterationOutcome:
    """The round of a phase: the adapter it published, its training, and the whole phase's policy update from the
    published adapter to it (the round alone, or with the phase's GRPO update before it; the main rank's)."""

    adapter: str
    result: ExpertIterationResult
    phase_parameter_change: ParameterChange | None
    # Reading the round's data and the replay.
    data_seconds: float = 0.0


def round_training_data(tokenizer: PolicyTokenizer, config: ExpertIterationConfig, data_root: Path) -> TrainingData:
    """The round's examples from its build directory (`sft.data`, a path the loop fills in) and the replay files under
    `data_root`."""
    return training_data(tokenizer, Path(config.sft.data), config.replay, data_root)


def adapter_change(start: Path, end: Path) -> ParameterChange:
    """The change between two saved adapters of the same LoRA, as `parameter_change` measures it in training."""
    before = saved_adapter_weights(start, CPU)
    after = saved_adapter_weights(end, CPU)
    names = sorted(before)
    return parameter_change([after[name] for name in names], [before[name].float() for name in names])


def train_expert_iteration(
    config: SftConfig,
    data: TrainingData,
    pad_token_id: int,
    device: torch.device,
    output_directory: Path,
    on_step: Callable[[StepRecord], None],
    ranks: Ranks = SINGLE_PROCESS,
    load: TrainableLoader = load_trainable_model,
) -> ExpertIterationResult:
    """On every rank with the same arguments; the main rank validates, reports the steps and saves the adapter
    (continuing `config.initial_adapter`) to `output_directory`."""
    optimization = config.optimization
    saved_module, causal_model = load(config.model, optimization, config.lora, device, config.initial_adapter)
    loss_module = CompletionLoss(causal_model)
    parameters = trainable_parameters(saved_module)
    start = parameter_snapshot(parameters) if ranks.is_main else []
    optimizer = torch.optim.AdamW(
        parameters, lr=optimization.learning_rate, weight_decay=optimization.weight_decay, fused=device.type == "cuda"
    )
    train = data.train
    steps = plan_steps(train, optimization, ranks.world_size)
    warmup_steps = max(1, round(optimization.warmup_fraction * len(steps)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: learning_rate_factor(step, warmup_steps, len(steps), optimization.minimum_learning_rate_ratio),
    )
    steps_per_epoch = len(steps) / optimization.epochs
    # As the hand-run round: the start, halfway and the end.
    interval = max(1, math.ceil(len(steps) / 2))
    curve: list[ValidationPoint] = []

    def validate(step: int) -> None:
        if ranks.is_main:
            causal_model.eval()
            curve.append(
                ValidationPoint(
                    step,
                    validation_loss(loss_module, data.expert_iteration_validation, config, pad_token_id, device),
                    validation_loss(loss_module, data.replay_validation, config, pad_token_id, device),
                )
            )
            causal_model.train()
        barrier(ranks)

    validate(0)
    totals = torch.zeros(5, dtype=torch.float64, device=device)
    losses: list[float] = []
    gradient_norms: list[float] = []
    training_seconds = 0.0
    for step_index, step in enumerate(steps):
        step_started = time.perf_counter()
        step_totals = torch.zeros(5, dtype=torch.float64, device=device)
        for indices in step.micro_batches[ranks.rank :: ranks.world_size]:
            examples = [train[index] for index in indices]
            batch = micro_batch(examples, optimization.packing, pad_token_id, device)
            with torch.autocast(device.type, dtype=torch.bfloat16):
                token_losses, _, _ = loss_module(
                    batch.input_ids, batch.attention_mask, batch.labels, batch.position_ids, batch.sequence_starts
                )
                loss = token_losses.sum() / step.completion_tokens
            loss.backward()
            step_totals[0] += token_losses.detach().sum()
            step_totals[1:] += torch.tensor(
                [
                    sum(example.token_count for example in examples),
                    batch.input_ids.numel(),
                    token_losses.numel(),
                    len(examples),
                ],
                dtype=torch.float64,
                device=device,
            )
        sum_gradients(parameters, ranks)
        gradient_norm = torch.nn.utils.clip_grad_norm_(parameters, optimization.max_gradient_norm).item()
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        summed(step_totals, ranks)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        training_seconds += time.perf_counter() - step_started
        totals += step_totals
        loss_sum, tokens, padded_tokens, completion_tokens, _ = step_totals.tolist()
        losses.append(loss_sum / completion_tokens)
        gradient_norms.append(gradient_norm)
        if ranks.is_main:
            on_step(
                StepRecord(
                    step=step_index + 1,
                    epoch=(step_index + 1) / steps_per_epoch,
                    learning_rate=scheduler.get_last_lr()[0],
                    loss=losses[-1],
                    gradient_norm=gradient_norm,
                    tokens=int(tokens),
                    padded_tokens=int(padded_tokens),
                    completion_tokens=int(completion_tokens),
                    training_seconds=training_seconds,
                    tokens_per_second=float(totals[1]) / training_seconds,
                )
            )
        if step_index == len(steps) - 1 or (step_index + 1) % interval == 0:
            validate(step_index + 1)
    if ranks.is_main:
        saved_module.save_pretrained(output_directory)
    barrier(ranks)
    points = tuple(curve)
    return ExpertIterationResult(
        steps=len(steps),
        examples=len(data.expert_iteration),
        lean_replay_examples=len(data.lean_replay),
        math_replay_examples=len(data.math_replay),
        validation_examples=len(data.expert_iteration_validation),
        tokens=int(totals[1]),
        trained_tokens=int(totals[3]),
        mean_loss=statistics.fmean(losses) if losses else None,
        mean_gradient_norm=statistics.fmean(gradient_norms) if gradient_norms else None,
        parameter_change=parameter_change(parameters, start) if ranks.is_main else None,
        curve=points,
        replay_loss_change=replay_loss_change(points) if ranks.is_main else None,
        training_seconds=training_seconds,
    )


def validation_loss(
    loss_module: CompletionLoss,
    examples: Sequence[TokenizedExample],
    config: SftConfig,
    pad_token_id: int,
    device: torch.device,
) -> float | None:
    """The mean completion-token loss (`sft.validation_metrics`); None without examples."""
    if not examples:
        return None
    loss, _ = validation_metrics(
        loss_module, examples, config.evaluation.micro_batch_tokens, config.optimization.packing, pad_token_id, device
    )
    return loss
