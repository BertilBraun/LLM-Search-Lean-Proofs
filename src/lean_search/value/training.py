"""LoRA training of the value model on the nine bin-token logits at the last prompt position."""

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import torch
import transformers

from lean_search.training.packing import (
    packed_hidden_states,
    packed_micro_batches,
    packed_positions,
    sequence_starts,
)
from lean_search.training.sft import (
    LoraSettings,
    OptimizationConfig,
    learning_rate_factor,
    length_grouped_micro_batches,
    load_trainable_model,
    trainable_parameters,
)
from lean_search.value.bins import Readout, bin_distribution
from lean_search.value.labels import ValueExample
from lean_search.value.loss import LossConfig, bin_mass_losses, label_tensors, value_losses
from lean_search.value.metrics import ValueMetrics, value_metrics
from lean_search.value.prompts import ValueTokenizer, bin_token_ids, render_value_prompt


@dataclass(frozen=True)
class ValueEvaluationConfig:
    interval_steps: int = 200
    validation_examples: int = 4000
    micro_batch_tokens: int = 32768
    # vLLM returns at most --max-logprobs (default 20) logprobs; bins outside them are not read exactly.
    served_top_k: int = 20


@dataclass(frozen=True)
class ValueTrainingConfig:
    model: str
    data: str
    max_prompt_tokens: int = 2048
    lora: LoraSettings = field(default_factory=LoraSettings)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    loss: LossConfig = field(default_factory=LossConfig)
    readout: Readout = field(default_factory=Readout)
    evaluation: ValueEvaluationConfig = field(default_factory=ValueEvaluationConfig)
    # A value LoRA adapter to continue training (its own rank and alpha replace `lora`); empty starts a new one.
    initial_adapter: str = ""


@dataclass(frozen=True)
class TokenizedValueExample:
    example: ValueExample
    input_ids: tuple[int, ...]

    @property
    def token_count(self) -> int:
        return len(self.input_ids)


@dataclass(frozen=True)
class PromptBatch:
    input_ids: torch.Tensor
    # Padded rows have a mask; a packed row has the positions and boundaries of its prompts instead.
    attention_mask: torch.Tensor | None
    # Per prompt, its last position in its row (padded) or in the packed row.
    last_positions: torch.Tensor
    position_ids: torch.Tensor | None = None
    sequence_starts: tuple[int, ...] = ()


@dataclass(frozen=True)
class ValueStep:
    micro_batches: tuple[tuple[int, ...], ...]
    weight: float


@dataclass(frozen=True)
class ValueStepRecord:
    step: int
    epoch: float
    learning_rate: float
    # Weighted mean over the step's examples.
    value_loss: float
    bin_mass_loss: float
    gradient_norm: float
    examples: int
    tokens: int
    padded_tokens: int
    training_seconds: float
    tokens_per_second: float


@dataclass(frozen=True)
class ValueEvaluationRecord:
    step: int
    examples: int
    value_loss: float
    # Mean full-vocabulary probability of the nine bin tokens together.
    bin_mass: float
    # Mean |h read from the served_top_k logprobs vLLM returns - h from all nine bins|.
    served_h_error: float
    metrics: ValueMetrics
    seconds: float


@dataclass(frozen=True)
class ValueTrainingResult:
    steps: int
    examples: int
    tokens: int
    padded_tokens: int
    training_seconds: float
    tokens_per_second: float
    peak_memory_gib: float
    trainable_parameters: int
    evaluations: tuple[ValueEvaluationRecord, ...]


class LastPositionLogits(torch.nn.Module):
    """Full-vocabulary logits at each prompt's last position, where the bin token is predicted."""

    def __init__(self, causal_model: transformers.PreTrainedModel) -> None:
        super().__init__()
        self.causal_model = causal_model

    def forward(self, batch: PromptBatch) -> torch.Tensor:
        if batch.sequence_starts:
            hidden = packed_hidden_states(
                self.causal_model.model, batch.input_ids, batch.position_ids, batch.sequence_starts
            )
            return self.causal_model.lm_head(hidden[0, batch.last_positions]).float()
        hidden = self.causal_model.model(
            input_ids=batch.input_ids, attention_mask=batch.attention_mask, use_cache=False
        ).last_hidden_state
        rows = torch.arange(len(batch.last_positions), device=hidden.device)
        return self.causal_model.lm_head(hidden[rows, batch.last_positions]).float()


def tokenize_value_example(tokenizer: ValueTokenizer, example: ValueExample) -> TokenizedValueExample:
    prompt = render_value_prompt(tokenizer, example.goals)
    return TokenizedValueExample(example, tuple(tokenizer.encode(prompt, add_special_tokens=False)))


def collate_prompts(examples: Sequence[TokenizedValueExample], pad_token_id: int, device: torch.device) -> PromptBatch:
    # Right padding, as in SFT: the recurrent layers of Qwen3.5 never see padding before a real token.
    width = max(example.token_count for example in examples)
    input_ids = torch.full((len(examples), width), pad_token_id, dtype=torch.long)
    attention_mask = torch.zeros((len(examples), width), dtype=torch.long)
    for row, example in enumerate(examples):
        input_ids[row, : example.token_count] = torch.tensor(example.input_ids)
        attention_mask[row, : example.token_count] = 1
    last_positions = torch.tensor([example.token_count - 1 for example in examples])
    return PromptBatch(input_ids.to(device), attention_mask.to(device), last_positions.to(device))


def pack_prompts(examples: Sequence[TokenizedValueExample], device: torch.device) -> PromptBatch:
    lengths = [example.token_count for example in examples]
    starts = sequence_starts(lengths)
    input_ids = torch.tensor([token for example in examples for token in example.input_ids]).unsqueeze(0)
    last_positions = torch.tensor(starts[1:]) - 1
    return PromptBatch(
        input_ids.to(device), None, last_positions.to(device), packed_positions(lengths).to(device), starts
    )


def prompt_batch(
    examples: Sequence[TokenizedValueExample], packing: bool, pad_token_id: int, device: torch.device
) -> PromptBatch:
    return pack_prompts(examples, device) if packing else collate_prompts(examples, pad_token_id, device)


def plan_micro_batches(
    lengths: Sequence[int], max_tokens: int, group_size: int, packing: bool, generator: random.Random
) -> list[tuple[int, ...]]:
    if packing:
        return packed_micro_batches(lengths, max_tokens, generator)
    return length_grouped_micro_batches(lengths, max_tokens, group_size, generator)


def plan_value_steps(examples: Sequence[TokenizedValueExample], config: OptimizationConfig) -> list[ValueStep]:
    generator = random.Random(config.seed)
    lengths = [example.token_count for example in examples]
    steps: list[ValueStep] = []
    for _ in range(config.epochs):
        micro_batches = plan_micro_batches(
            lengths, config.micro_batch_tokens, config.length_group_examples, config.packing, generator
        )
        # The last incomplete step of an epoch is dropped so every step has the same number of micro-batches.
        for start in range(0, len(micro_batches) - config.micro_batches_per_step + 1, config.micro_batches_per_step):
            step_batches = tuple(micro_batches[start : start + config.micro_batches_per_step])
            weight = sum(examples[index].example.weight for batch in step_batches for index in batch)
            steps.append(ValueStep(step_batches, weight))
    return steps[: config.max_steps] if config.max_steps else steps


@torch.no_grad()
def evaluate(
    step: int,
    model: LastPositionLogits,
    examples: Sequence[TokenizedValueExample],
    config: ValueTrainingConfig,
    bin_ids: torch.Tensor,
    pad_token_id: int,
    device: torch.device,
) -> ValueEvaluationRecord:
    started = time.perf_counter()
    model.eval()
    lengths = [example.token_count for example in examples]
    packing = config.optimization.packing
    micro_batches = plan_micro_batches(
        lengths, config.evaluation.micro_batch_tokens, len(examples), packing, random.Random(0)
    )
    distributions: list[list[float]] = [[] for _ in examples]
    weighted_loss = 0.0
    bin_mass = 0.0
    served_h_error = 0.0
    token_ids = bin_ids.tolist()
    for micro_batch in micro_batches:
        batch_examples = [examples[index] for index in micro_batch]
        batch = prompt_batch(batch_examples, packing, pad_token_id, device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            full_logits = model(batch)
        bin_logits = full_logits[:, bin_ids]
        labels = label_tensors([example.example for example in batch_examples], device)
        weighted_loss += (labels.weights * value_losses(bin_logits, labels, config.loss.smoothing_sigma)).sum().item()
        bin_mass += torch.exp(-bin_mass_losses(full_logits, bin_ids)).sum().item()
        top_k = torch.log_softmax(full_logits, dim=-1).topk(config.evaluation.served_top_k, dim=-1)
        for index, probabilities, top_ids, top_logprobs in zip(
            micro_batch,
            torch.softmax(bin_logits, dim=-1).tolist(),
            top_k.indices.tolist(),
            top_k.values.tolist(),
            strict=True,
        ):
            distributions[index] = probabilities
            served = bin_distribution(dict(zip(top_ids, top_logprobs, strict=True)), token_ids)
            served_steps = config.readout.remaining_steps(served.probabilities)
            served_h_error += abs(served_steps - config.readout.remaining_steps(probabilities))
    model.train()
    value_examples = [example.example for example in examples]
    return ValueEvaluationRecord(
        step=step,
        examples=len(examples),
        value_loss=weighted_loss / sum(example.weight for example in value_examples),
        bin_mass=bin_mass / len(examples),
        served_h_error=served_h_error / len(examples),
        metrics=value_metrics(distributions, value_examples, config.readout),
        seconds=time.perf_counter() - started,
    )


def load_value_model(config: ValueTrainingConfig, device: torch.device) -> tuple[torch.nn.Module, LastPositionLogits]:
    """The PEFT module to save and the logits module it trains, from config.initial_adapter when one is given."""
    saved_module, causal_model = load_trainable_model(
        config.model, config.optimization, config.lora, device, config.initial_adapter
    )
    return saved_module, LastPositionLogits(causal_model)


def train_value_model(
    config: ValueTrainingConfig,
    tokenizer: transformers.PreTrainedTokenizerBase,
    train_examples: Sequence[TokenizedValueExample],
    validation_examples: Sequence[TokenizedValueExample],
    device: torch.device,
    output_directory: Path,
    on_step: Callable[[ValueStepRecord], None],
    on_evaluation: Callable[[ValueEvaluationRecord], None],
) -> ValueTrainingResult:
    optimization = config.optimization
    saved_module, model = load_value_model(config, device)
    bin_ids = torch.tensor(bin_token_ids(tokenizer), device=device)
    parameters = trainable_parameters(model)
    optimizer = torch.optim.AdamW(
        parameters, lr=optimization.learning_rate, weight_decay=optimization.weight_decay, fused=True
    )
    steps = plan_value_steps(train_examples, optimization)
    warmup_steps = max(1, round(optimization.warmup_fraction * len(steps)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: learning_rate_factor(step, warmup_steps, len(steps), optimization.minimum_learning_rate_ratio),
    )
    steps_per_epoch = len(steps) / optimization.epochs
    validation = validation_examples[: config.evaluation.validation_examples]
    evaluations: list[ValueEvaluationRecord] = []

    def evaluate_now(step: int) -> None:
        record = evaluate(step, model, validation, config, bin_ids, tokenizer.pad_token_id, device)
        evaluations.append(record)
        on_evaluation(record)

    evaluate_now(0)
    torch.cuda.reset_peak_memory_stats(device)
    training_seconds = 0.0
    total_examples = 0
    total_tokens = 0
    total_padded_tokens = 0
    for step_index, step in enumerate(steps):
        step_start = time.perf_counter()
        value_loss_sum = torch.zeros((), device=device)
        bin_mass_loss_sum = torch.zeros((), device=device)
        examples = 0
        tokens = 0
        padded_tokens = 0
        for micro_batch in step.micro_batches:
            batch_examples = [train_examples[index] for index in micro_batch]
            batch = prompt_batch(batch_examples, optimization.packing, tokenizer.pad_token_id, device)
            labels = label_tensors([example.example for example in batch_examples], device)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                full_logits = model(batch)
            losses = value_losses(full_logits[:, bin_ids], labels, config.loss.smoothing_sigma)
            mass_losses = bin_mass_losses(full_logits, bin_ids)
            loss = (labels.weights * (losses + config.loss.bin_mass_weight * mass_losses)).sum() / step.weight
            loss.backward()
            value_loss_sum += (labels.weights * losses).detach().sum()
            bin_mass_loss_sum += (labels.weights * mass_losses).detach().sum()
            examples += len(batch_examples)
            tokens += sum(example.token_count for example in batch_examples)
            padded_tokens += batch.input_ids.numel()
        gradient_norm = torch.nn.utils.clip_grad_norm_(parameters, optimization.max_gradient_norm).item()
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        torch.cuda.synchronize(device)
        training_seconds += time.perf_counter() - step_start
        total_examples += examples
        total_tokens += tokens
        total_padded_tokens += padded_tokens
        on_step(
            ValueStepRecord(
                step=step_index + 1,
                epoch=(step_index + 1) / steps_per_epoch,
                learning_rate=scheduler.get_last_lr()[0],
                value_loss=value_loss_sum.item() / step.weight,
                bin_mass_loss=bin_mass_loss_sum.item() / step.weight,
                gradient_norm=gradient_norm,
                examples=examples,
                tokens=tokens,
                padded_tokens=padded_tokens,
                training_seconds=training_seconds,
                tokens_per_second=total_tokens / training_seconds,
            )
        )
        is_last = step_index == len(steps) - 1
        if is_last or (step_index + 1) % config.evaluation.interval_steps == 0:
            evaluate_now(step_index + 1)
    saved_module.save_pretrained(output_directory)
    return ValueTrainingResult(
        steps=len(steps),
        examples=total_examples,
        tokens=total_tokens,
        padded_tokens=total_padded_tokens,
        training_seconds=training_seconds,
        tokens_per_second=total_tokens / training_seconds,
        peak_memory_gib=torch.cuda.max_memory_allocated(device) / 2**30,
        trainable_parameters=sum(parameter.numel() for parameter in parameters),
        evaluations=tuple(evaluations),
    )
