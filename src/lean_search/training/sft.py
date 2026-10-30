"""LoRA or full fine-tuning of the policy on completion tokens only, with length-grouped batches and optional DDP."""

import contextlib
import math
import os
import random
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import peft
import torch
import torch.distributed
import torch.nn.functional as functional
import torch.utils.checkpoint
import transformers

from lean_search.policy.adapters import LORA_TARGET_PATTERN, copy_tokenizer_and_processor_files, load_base_model
from lean_search.policy.prompts import END_OF_TURN, FENCE, normalize_tactic_block
from lean_search.training.data_parallel import COLLECTIVE_TIMEOUT
from lean_search.training.packing import (
    enable_packed_sequences,
    packed_hidden_states,
    packed_micro_batches,
    packed_positions,
    sequence_starts,
)
from lean_search.training.sft_data import IGNORE_INDEX, TokenizedExample

VISION_PARAMETER = re.compile(r"\bvisual\b")
# Element-wise chains (norms, SiLU gating, LoRA scaling and sums) that torch.compile fuses; matmuls stay cuBLAS.
# Not the token mixers as a whole: compiled around the FLA kernels and varlen attention, training diverges.
COMPILED_MODULE = re.compile(
    r"\.layers\.\d+\.(mlp|input_layernorm|post_attention_layernorm"
    r"|linear_attn\.(norm|in_proj_qkv|in_proj_z|in_proj_a|in_proj_b|out_proj)"
    r"|self_attn\.(q_proj|k_proj|v_proj|o_proj|q_norm|k_norm))$"
)
LOSS_CHUNK_POSITIONS = 1024


class FineTuningMethod(StrEnum):
    LORA = "lora"
    FULL = "full"


@dataclass(frozen=True)
class LoraSettings:
    rank: int = 64
    alpha: int = 64
    dropout: float = 0.0


@dataclass(frozen=True)
class OptimizationConfig:
    method: FineTuningMethod = FineTuningMethod.LORA
    learning_rate: float = 2e-4
    warmup_fraction: float = 0.03
    minimum_learning_rate_ratio: float = 0.1
    weight_decay: float = 0.0
    max_gradient_norm: float = 1.0
    epochs: int = 1
    # 0 runs every step of the planned epochs.
    max_steps: int = 0
    # Padded tokens (longest example times examples) per micro-batch on one GPU; real tokens when packing.
    micro_batch_tokens: int = 16384
    micro_batches_per_step: int = 4
    # Examples sorted by length within groups of this size before batching (padded micro-batches only).
    length_group_examples: int = 4096
    gradient_checkpointing: bool = True
    # Concatenate shuffled examples into one row per micro-batch, without padding (Qwen3.5 only).
    packing: bool = False
    compile_layers: bool = False
    seed: int = 0


@dataclass(frozen=True)
class EvaluationConfig:
    interval_steps: int = 100
    validation_examples: int = 1000
    micro_batch_tokens: int = 16384
    generation_examples: int = 128
    generation_batch_size: int = 32
    max_new_tokens: int = 256


@dataclass(frozen=True)
class SftConfig:
    model: str
    data: str
    lora: LoraSettings = field(default_factory=LoraSettings)
    optimization: OptimizationConfig = field(default_factory=OptimizationConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    merge: bool = True
    # A LoRA adapter to continue training (its own rank and alpha replace `lora`); empty starts a new one.
    initial_adapter: str = ""
    # General math worked solutions (name under $LEAN_SEARCH_DATA/math_sft) mixed into the training examples.
    math_data: str = ""


@dataclass(frozen=True)
class OptimizerStep:
    micro_batches: tuple[tuple[int, ...], ...]
    completion_tokens: int


@dataclass(frozen=True)
class Batch:
    input_ids: torch.Tensor
    # Padded rows have a mask; a packed row has the positions and boundaries of its examples instead.
    attention_mask: torch.Tensor | None
    labels: torch.Tensor
    position_ids: torch.Tensor | None = None
    sequence_starts: tuple[int, ...] = ()


@dataclass(frozen=True)
class DistributedContext:
    rank: int
    world_size: int
    device: torch.device

    @property
    def is_main(self) -> bool:
        return self.rank == 0


@dataclass(frozen=True)
class StepRecord:
    step: int
    epoch: float
    learning_rate: float
    loss: float
    gradient_norm: float
    tokens: int
    padded_tokens: int
    completion_tokens: int
    training_seconds: float
    tokens_per_second: float


@dataclass(frozen=True)
class GeneratedSample:
    goals: tuple[str, ...]
    target: str
    generated: str


@dataclass(frozen=True)
class EvaluationRecord:
    step: int
    validation_loss: float
    validation_examples: int
    teacher_forced_exact_match: float
    generation_exact_match: float
    generation_examples: int
    evaluation_seconds: float
    mismatches: tuple[GeneratedSample, ...]


@dataclass(frozen=True)
class TrainingResult:
    steps: int
    examples: int
    tokens: int
    padded_tokens: int
    completion_tokens: int
    training_seconds: float
    tokens_per_second: float
    peak_memory_gib: float
    trainable_parameters: int
    evaluations: tuple[EvaluationRecord, ...]


@dataclass(frozen=True)
class SftRunSummary:
    run_name: str
    started: str
    git_revision: str
    config: SftConfig
    world_size: int
    flash_linear_attention: bool
    train_examples: int
    train_tokens: int
    validation_examples: int
    tokenization_seconds: float
    result: TrainingResult
    trained_model_directory: str
    merged_directory: str
    merge_seconds: float


def distributed_context() -> DistributedContext:
    world_size = int(os.environ.get("WORLD_SIZE", "1"))
    if world_size == 1:
        return DistributedContext(0, 1, torch.device("cuda"))
    local_rank = int(os.environ["LOCAL_RANK"])
    torch.cuda.set_device(local_rank)
    # The main rank's greedy evaluation can outlast NCCL's 10-minute default while the other ranks wait.
    torch.distributed.init_process_group("nccl", timeout=COLLECTIVE_TIMEOUT)
    return DistributedContext(torch.distributed.get_rank(), world_size, torch.device("cuda", local_rank))


def length_grouped_micro_batches(
    lengths: Sequence[int], max_tokens: int, group_size: int, generator: random.Random
) -> list[tuple[int, ...]]:
    """Shuffled micro-batches of similar-length examples whose padded size stays within max_tokens."""
    order = list(range(len(lengths)))
    generator.shuffle(order)
    micro_batches: list[tuple[int, ...]] = []
    for start in range(0, len(order), group_size):
        current: list[int] = []
        for index in sorted(order[start : start + group_size], key=lambda index: lengths[index]):
            if current and lengths[index] * (len(current) + 1) > max_tokens:
                micro_batches.append(tuple(current))
                current = []
            current.append(index)
        if current:
            micro_batches.append(tuple(current))
    generator.shuffle(micro_batches)
    return micro_batches


def plan_steps(
    examples: Sequence[TokenizedExample], config: OptimizationConfig, world_size: int
) -> list[OptimizerStep]:
    generator = random.Random(config.seed)
    lengths = [example.token_count for example in examples]
    micro_batches_per_step = config.micro_batches_per_step * world_size
    steps: list[OptimizerStep] = []
    for _ in range(config.epochs):
        micro_batches = (
            packed_micro_batches(lengths, config.micro_batch_tokens, generator)
            if config.packing
            else length_grouped_micro_batches(
                lengths, config.micro_batch_tokens, config.length_group_examples, generator
            )
        )
        # The last incomplete step of an epoch is dropped so every step has the same number of micro-batches.
        for start in range(0, len(micro_batches) - micro_batches_per_step + 1, micro_batches_per_step):
            step_batches = tuple(micro_batches[start : start + micro_batches_per_step])
            completion_tokens = sum(examples[index].completion_token_count for batch in step_batches for index in batch)
            steps.append(OptimizerStep(step_batches, completion_tokens))
    return steps[: config.max_steps] if config.max_steps else steps


def learning_rate_factor(step: int, warmup_steps: int, total_steps: int, minimum_ratio: float) -> float:
    if step < warmup_steps:
        return (step + 1) / warmup_steps
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    return minimum_ratio + (1 - minimum_ratio) * 0.5 * (1 + math.cos(math.pi * progress))


def collate(examples: Sequence[TokenizedExample], pad_token_id: int, device: torch.device) -> Batch:
    # Right padding: the recurrent layers of Qwen3.5 then never see padding before a real token.
    width = max(example.token_count for example in examples)
    input_ids = torch.full((len(examples), width), pad_token_id, dtype=torch.long)
    labels = torch.full((len(examples), width), IGNORE_INDEX, dtype=torch.long)
    attention_mask = torch.zeros((len(examples), width), dtype=torch.long)
    for row, example in enumerate(examples):
        input_ids[row, : example.token_count] = torch.tensor(example.input_ids)
        labels[row, : example.token_count] = torch.tensor(example.labels)
        attention_mask[row, : example.token_count] = 1
    return Batch(input_ids.to(device), attention_mask.to(device), labels.to(device))


def pack(examples: Sequence[TokenizedExample], device: torch.device) -> Batch:
    # Each example starts with a prompt token, whose label is ignored, so no target crosses an example boundary.
    lengths = [example.token_count for example in examples]
    input_ids = torch.tensor([token for example in examples for token in example.input_ids]).unsqueeze(0)
    labels = torch.tensor([label for example in examples for label in example.labels]).unsqueeze(0)
    return Batch(
        input_ids.to(device), None, labels.to(device), packed_positions(lengths).to(device), sequence_starts(lengths)
    )


def micro_batch(examples: Sequence[TokenizedExample], packing: bool, pad_token_id: int, device: torch.device) -> Batch:
    return pack(examples, device) if packing else collate(examples, pad_token_id, device)


def token_losses_and_correctness(
    lm_head: torch.nn.Module, hidden: torch.Tensor, targets: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    logits = lm_head(hidden).float()
    return functional.cross_entropy(logits, targets, reduction="none"), logits.argmax(dim=-1) == targets


class CompletionLoss(torch.nn.Module):
    """Per-token losses on completion positions only, projecting just those hidden states onto the vocabulary."""

    def __init__(self, causal_model: transformers.PreTrainedModel) -> None:
        super().__init__()
        self.causal_model = causal_model

    def forward(
        self,
        input_ids: torch.Tensor,
        attention_mask: torch.Tensor | None,
        labels: torch.Tensor,
        position_ids: torch.Tensor | None = None,
        sequence_starts: tuple[int, ...] = (),
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Losses and argmax hits of the completion positions, and the example (row or packed slot) of each."""
        if sequence_starts:
            hidden = packed_hidden_states(self.causal_model.model, input_ids, position_ids, sequence_starts)
        else:
            hidden = self.causal_model.model(
                input_ids=input_ids, attention_mask=attention_mask, use_cache=False
            ).last_hidden_state
        targets = labels[:, 1:]
        mask = targets != IGNORE_INDEX
        selected_hidden = hidden[:, :-1][mask]
        selected_targets = targets[mask]
        # Logits over a 248k vocabulary are recomputed per chunk in the backward pass instead of being kept.
        chunks = [
            torch.utils.checkpoint.checkpoint(
                token_losses_and_correctness,
                self.causal_model.lm_head,
                selected_hidden[start : start + LOSS_CHUNK_POSITIONS],
                selected_targets[start : start + LOSS_CHUNK_POSITIONS],
                use_reentrant=False,
            )
            for start in range(0, len(selected_targets), LOSS_CHUNK_POSITIONS)
        ]
        token_losses = torch.cat([losses for losses, _ in chunks])
        correct = torch.cat([chunk_correct for _, chunk_correct in chunks])
        if not sequence_starts:
            return token_losses, correct, mask.nonzero()[:, 0]
        sequence_ends = torch.tensor(sequence_starts[1:], device=input_ids.device)
        return token_losses, correct, torch.searchsorted(sequence_ends, mask[0].nonzero()[:, 0], right=True)


def load_trainable_model(
    model_name: str,
    optimization: OptimizationConfig,
    lora: LoraSettings,
    device: torch.device,
    initial_adapter: str = "",
) -> tuple[torch.nn.Module, transformers.PreTrainedModel]:
    """The module to save (a PEFT model or the full model) and the causal model it trains."""
    torch.manual_seed(optimization.seed)
    model = load_base_model(model_name, device=str(device))
    model.config.use_cache = False
    if optimization.packing:
        enable_packed_sequences(model)
    if optimization.gradient_checkpointing:
        model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    match optimization.method:
        case FineTuningMethod.LORA if initial_adapter:
            # PEFT otherwise loads the adapter onto cuda:0, which the servers fill while a resident trainer starts.
            saved: torch.nn.Module = peft.PeftModel.from_pretrained(
                model, initial_adapter, is_trainable=True, torch_device=str(device)
            )
            saved.train()
            causal_model = saved.get_base_model()
        case FineTuningMethod.LORA:
            lora_config = peft.LoraConfig(
                r=lora.rank, lora_alpha=lora.alpha, lora_dropout=lora.dropout, target_modules=LORA_TARGET_PATTERN
            )
            saved = peft.get_peft_model(model, lora_config)
            saved.train()
            causal_model = saved.get_base_model()
        case FineTuningMethod.FULL:
            # fp32 master weights; bf16 compute comes from autocast.
            model.to(torch.float32)
            for name, parameter in model.named_parameters():
                parameter.requires_grad_(VISION_PARAMETER.search(name) is None)
            model.train()
            saved = causal_model = model
    if optimization.compile_layers:
        for name, module in causal_model.named_modules():
            if COMPILED_MODULE.search(name):
                module.compile(dynamic=True)
    return saved, causal_model


# Gives a trainer its model as load_trainable_model does: loaded from disk, or a resident one (training/resident.py).
TrainableLoader = Callable[
    [str, OptimizationConfig, LoraSettings, torch.device, str], tuple[torch.nn.Module, transformers.PreTrainedModel]
]


def trainable_parameters(module: torch.nn.Module) -> list[torch.nn.Parameter]:
    return [parameter for parameter in module.parameters() if parameter.requires_grad]


@torch.no_grad()
def validation_metrics(
    loss_module: CompletionLoss,
    examples: Sequence[TokenizedExample],
    micro_batch_tokens: int,
    packing: bool,
    pad_token_id: int,
    device: torch.device,
) -> tuple[float, float]:
    """Mean completion-token loss and the fraction of examples whose every target token is the argmax."""
    lengths = [example.token_count for example in examples]
    micro_batches = (
        packed_micro_batches(lengths, micro_batch_tokens, random.Random(0))
        if packing
        else length_grouped_micro_batches(lengths, micro_batch_tokens, len(examples), random.Random(0))
    )
    loss_sum = 0.0
    token_count = 0
    exact = 0
    for indices in micro_batches:
        batch = micro_batch([examples[index] for index in indices], packing, pad_token_id, device)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            token_losses, correct, rows = loss_module(
                batch.input_ids, batch.attention_mask, batch.labels, batch.position_ids, batch.sequence_starts
            )
        loss_sum += token_losses.sum().item()
        token_count += token_losses.numel()
        wrong_per_row = torch.bincount(rows[~correct], minlength=len(indices))
        exact += int((wrong_per_row == 0).sum().item())
    return loss_sum / token_count, exact / len(examples)


@torch.no_grad()
def generate_tactic_blocks(
    causal_model: transformers.PreTrainedModel,
    tokenizer: transformers.PreTrainedTokenizerBase,
    examples: Sequence[TokenizedExample],
    batch_size: int,
    max_new_tokens: int,
    device: torch.device,
) -> list[str]:
    end_of_turn = tokenizer.convert_tokens_to_ids(END_OF_TURN)
    pad_token_id = tokenizer.pad_token_id
    generated: list[str] = []
    for start in range(0, len(examples), batch_size):
        prompts = [example.input_ids[: example.prompt_token_count] for example in examples[start : start + batch_size]]
        width = max(len(prompt) for prompt in prompts)
        input_ids = torch.tensor([(pad_token_id,) * (width - len(prompt)) + prompt for prompt in prompts])
        attention_mask = torch.tensor([[0] * (width - len(prompt)) + [1] * len(prompt) for prompt in prompts])
        with torch.autocast("cuda", dtype=torch.bfloat16):
            output = causal_model.generate(
                input_ids=input_ids.to(device),
                attention_mask=attention_mask.to(device),
                max_new_tokens=max_new_tokens,
                do_sample=False,
                eos_token_id=end_of_turn,
                pad_token_id=pad_token_id,
                use_cache=True,
            )
        for row in output[:, width:].tolist():
            text = tokenizer.decode(row, skip_special_tokens=True)
            generated.append(normalize_tactic_block(text.partition(FENCE)[0]))
    return generated


def evaluate(
    step: int,
    loss_module: CompletionLoss,
    causal_model: transformers.PreTrainedModel,
    tokenizer: transformers.PreTrainedTokenizerBase,
    validation: Sequence[TokenizedExample],
    config: EvaluationConfig,
    packing: bool,
    device: torch.device,
) -> EvaluationRecord:
    start = time.perf_counter()
    causal_model.eval()
    validation_loss, teacher_forced = validation_metrics(
        loss_module,
        validation[: config.validation_examples],
        config.micro_batch_tokens,
        packing,
        tokenizer.pad_token_id,
        device,
    )
    generation_sample = validation[: config.generation_examples]
    generated = generate_tactic_blocks(
        causal_model, tokenizer, generation_sample, config.generation_batch_size, config.max_new_tokens, device
    )
    causal_model.train()
    samples = [
        GeneratedSample(example.example.goals, example.example.tactic_block, text)
        for example, text in zip(generation_sample, generated, strict=True)
    ]
    mismatches = tuple(sample for sample in samples if sample.generated != sample.target)
    return EvaluationRecord(
        step=step,
        validation_loss=validation_loss,
        validation_examples=min(len(validation), config.validation_examples),
        teacher_forced_exact_match=teacher_forced,
        generation_exact_match=(len(samples) - len(mismatches)) / len(samples) if samples else 0.0,
        generation_examples=len(samples),
        evaluation_seconds=time.perf_counter() - start,
        mismatches=mismatches[:8],
    )


def train(
    config: SftConfig,
    tokenizer: transformers.PreTrainedTokenizerBase,
    train_examples: Sequence[TokenizedExample],
    validation_examples: Sequence[TokenizedExample],
    context: DistributedContext,
    output_directory: Path,
    on_step: Callable[[StepRecord], None],
    on_evaluation: Callable[[EvaluationRecord], None],
) -> TrainingResult:
    optimization = config.optimization
    saved_module, causal_model = load_trainable_model(
        config.model, optimization, config.lora, context.device, config.initial_adapter
    )
    loss_module = CompletionLoss(causal_model)
    distributed_module: torch.nn.Module = loss_module
    if context.world_size > 1:
        distributed_module = torch.nn.parallel.DistributedDataParallel(loss_module, device_ids=[context.device.index])
    parameters = trainable_parameters(loss_module)
    optimizer = torch.optim.AdamW(
        parameters, lr=optimization.learning_rate, weight_decay=optimization.weight_decay, fused=True
    )
    steps = plan_steps(train_examples, optimization, context.world_size)
    warmup_steps = max(1, round(optimization.warmup_fraction * len(steps)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: learning_rate_factor(step, warmup_steps, len(steps), optimization.minimum_learning_rate_ratio),
    )
    steps_per_epoch = len(steps) / optimization.epochs
    evaluations: list[EvaluationRecord] = []

    def evaluate_now(step: int) -> None:
        if not config.evaluation.validation_examples:
            return
        if context.is_main:
            record = evaluate(
                step,
                loss_module,
                causal_model,
                tokenizer,
                validation_examples,
                config.evaluation,
                optimization.packing,
                context.device,
            )
            evaluations.append(record)
            on_evaluation(record)
        if context.world_size > 1:
            torch.distributed.barrier()

    evaluate_now(0)
    torch.cuda.reset_peak_memory_stats(context.device)
    totals = torch.zeros(5, dtype=torch.float64, device=context.device)
    training_seconds = 0.0
    for step_index, step in enumerate(steps):
        step_start = time.perf_counter()
        local_batches = step.micro_batches[context.rank :: context.world_size]
        # Summed losses over the step's completion tokens on all ranks; DDP averages gradients across ranks.
        scale = context.world_size / step.completion_tokens
        step_totals = torch.zeros(5, dtype=torch.float64, device=context.device)
        for micro_index, indices in enumerate(local_batches):
            batch_examples = [train_examples[index] for index in indices]
            batch = micro_batch(batch_examples, optimization.packing, tokenizer.pad_token_id, context.device)
            synchronize = micro_index == len(local_batches) - 1 or context.world_size == 1
            with (
                contextlib.nullcontext() if synchronize else distributed_module.no_sync(),
                torch.autocast("cuda", dtype=torch.bfloat16),
            ):
                token_losses, _, _ = distributed_module(
                    batch.input_ids, batch.attention_mask, batch.labels, batch.position_ids, batch.sequence_starts
                )
                loss = token_losses.sum() * scale
            loss.backward()
            step_totals[0] += token_losses.detach().sum()
            step_totals[1:] += torch.tensor(
                [
                    sum(example.token_count for example in batch_examples),
                    batch.input_ids.numel(),
                    token_losses.numel(),
                    len(batch_examples),
                ],
                dtype=torch.float64,
                device=context.device,
            )
        gradient_norm = torch.nn.utils.clip_grad_norm_(parameters, optimization.max_gradient_norm).item()
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        if context.world_size > 1:
            torch.distributed.all_reduce(step_totals)
        torch.cuda.synchronize(context.device)
        training_seconds += time.perf_counter() - step_start
        totals += step_totals
        loss_sum, tokens, padded_tokens, completion_tokens, _ = step_totals.tolist()
        if context.is_main:
            on_step(
                StepRecord(
                    step=step_index + 1,
                    epoch=(step_index + 1) / steps_per_epoch,
                    learning_rate=scheduler.get_last_lr()[0],
                    loss=loss_sum / completion_tokens,
                    gradient_norm=gradient_norm,
                    tokens=int(tokens),
                    padded_tokens=int(padded_tokens),
                    completion_tokens=int(completion_tokens),
                    training_seconds=training_seconds,
                    tokens_per_second=float(totals[1].item()) / training_seconds,
                )
            )
        is_last = step_index == len(steps) - 1
        if is_last or (step_index + 1) % config.evaluation.interval_steps == 0:
            evaluate_now(step_index + 1)
    if context.is_main:
        save_trained_model(saved_module, config, output_directory)
    if context.world_size > 1:
        torch.distributed.barrier()
    _, tokens, padded_tokens, completion_tokens, examples = totals.tolist()
    return TrainingResult(
        steps=len(steps),
        examples=int(examples),
        tokens=int(tokens),
        padded_tokens=int(padded_tokens),
        completion_tokens=int(completion_tokens),
        training_seconds=training_seconds,
        tokens_per_second=tokens / training_seconds,
        peak_memory_gib=torch.cuda.max_memory_allocated(context.device) / 2**30,
        trainable_parameters=sum(parameter.numel() for parameter in parameters),
        evaluations=tuple(evaluations),
    )


def save_trained_model(saved_module: torch.nn.Module, config: SftConfig, output_directory: Path) -> None:
    match config.optimization.method:
        case FineTuningMethod.LORA:
            saved_module.save_pretrained(output_directory)
        case FineTuningMethod.FULL:
            saved_module.to(torch.bfloat16).save_pretrained(output_directory)
            copy_tokenizer_and_processor_files(config.model, output_directory)
