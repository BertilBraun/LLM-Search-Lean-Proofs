"""GRPO of the policy LoRA: a PPO-clipped objective per sampled token, at the sampling temperature, with replay."""

import random
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import torch
import torch.utils.checkpoint
import transformers

from lean_search.rl.policy_data import PolicyDataConfig, PolicySequence
from lean_search.training.dpo import packed_item_micro_batches, token_micro_batches
from lean_search.training.packing import packed_hidden_states
from lean_search.training.sft import (
    Batch,
    FineTuningMethod,
    LoraSettings,
    OptimizationConfig,
    learning_rate_factor,
    load_trainable_model,
    micro_batch,
    trainable_parameters,
)
from lean_search.training.sft_data import IGNORE_INDEX, TokenizedExample

# Smaller than the SFT loss chunks: the entropy needs the full log-softmax next to the logits.
SCORE_CHUNK_POSITIONS = 512


class ReferencePolicy(StrEnum):
    # The weights in `model` without the adapter: the GRPO starting policy when `model` holds its merged weights.
    STARTING_WEIGHTS = "starting_weights"
    # The policy at the phase's start, which collected most of the data.
    PHASE_START = "phase_start"


@dataclass(frozen=True)
class GrpoConfig:
    # The weights the LoRA adapter applies to, e.g. the merged starting policy.
    model: str
    # The adapter to continue (the published one); empty starts a fresh adapter on `model`.
    initial_adapter: str = ""
    lora: LoraSettings = field(default_factory=LoraSettings)
    # micro_batch_tokens: padded tokens (real ones when packing); epochs is unused (passes_per_phase).
    optimization: OptimizationConfig = field(
        default_factory=lambda: OptimizationConfig(learning_rate=1e-5, minimum_learning_rate_ratio=1.0)
    )
    sequences_per_step: int = 64
    # Passes over the phase's sequences; PPO clipping keeps the second pass close to the data-collecting policy.
    passes_per_phase: int = 2
    # 0 takes optimization.warmup_fraction of the steps.
    warmup_steps: int = 0
    clip_low: float = 0.2
    # Clip-higher (DAPO): low-probability tokens with a positive advantage may grow further than they may shrink.
    clip_high: float = 0.28
    # The KL penalty's weight; the KL to the reference is measured and reported either way.
    kl_coefficient: float = 0.0
    reference: ReferencePolicy = ReferencePolicy.STARTING_WEIGHTS
    # A step's loss is sum(weight * token loss) / (its sequences * this): no per-sequence mean, so no length bias.
    normalization_tokens: int = 256
    # NLL on replay examples (Lean SFT data, math solutions) mixed into every step, as a mean over their tokens.
    replay_weight: float = 0.1
    replay_sequences_per_step: int = 0
    # No length filter: every recorded sample trains; a longer one is a bug (the servers' context is 8192 tokens).
    max_sequence_tokens: int = 8192
    # Micro-batches of the gradient-free passes (data-collecting and reference log-probabilities).
    scoring_micro_batch_tokens: int = 16384
    data: PolicyDataConfig = field(default_factory=PolicyDataConfig)


@dataclass(frozen=True)
class TokenLosses:
    losses: torch.Tensor
    # Tokens whose clipped branch is active, so that they get no gradient.
    clipped: torch.Tensor


@dataclass(frozen=True)
class GrpoStep:
    sequences: tuple[int, ...]
    micro_batches: tuple[tuple[int, ...], ...]
    pass_index: int


@dataclass(frozen=True)
class GrpoStepRecord:
    step: int
    pass_index: int
    learning_rate: float
    loss: float
    policy_loss: float
    # Means over the step's trained tokens; KLs are k3 estimates.
    kl_to_data_policy: float
    kl_to_reference: float
    clip_fraction: float
    entropy: float
    mean_ratio: float
    replay_nll: float
    gradient_norm: float
    sequences: int
    trained_tokens: int
    tokens: int
    training_seconds: float


@dataclass(frozen=True)
class SamplerAgreement:
    """The trainer's log-probabilities before the first update against the sampler's recorded ones."""

    tokens: int
    # Means over the tokens of trainer minus sampler, of its absolute value, and the k3 KL(sampler || trainer).
    mean_difference: float
    mean_absolute_difference: float
    kl_sampler_to_trainer: float


@dataclass(frozen=True)
class GrpoTrainingResult:
    steps: int
    sequences: int
    trained_tokens: int
    scoring_seconds: float
    training_seconds: float
    peak_memory_gib: float
    trainable_parameters: int
    # Means over the last pass's steps.
    final_kl_to_data_policy: float
    final_kl_to_reference: float
    final_clip_fraction: float
    final_entropy: float
    final_policy_loss: float
    sampler_agreement: SamplerAgreement


def clipped_policy_losses(
    log_probabilities: torch.Tensor,
    old_log_probabilities: torch.Tensor,
    advantages: torch.Tensor,
    clip_low: float,
    clip_high: float,
) -> TokenLosses:
    """-min(ratio * A, clip(ratio, 1 - clip_low, 1 + clip_high) * A) per token."""
    ratio = torch.exp(log_probabilities - old_log_probabilities)
    objective = torch.minimum(ratio * advantages, ratio.clamp(1 - clip_low, 1 + clip_high) * advantages)
    clipped = ((advantages > 0) & (ratio > 1 + clip_high)) | ((advantages < 0) & (ratio < 1 - clip_low))
    return TokenLosses(-objective, clipped)


def kl_estimate(log_ratio: torch.Tensor) -> torch.Tensor:
    """k3: with log_ratio = log q(x) - log p(x) for x drawn from p, an unbiased, non-negative estimate of KL(p || q)."""
    return torch.exp(log_ratio) - log_ratio - 1


def chunk_scores(
    lm_head: torch.nn.Module, hidden: torch.Tensor, targets: torch.Tensor, temperatures: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    log_probabilities = torch.log_softmax(lm_head(hidden).float() / temperatures[:, None], dim=-1)
    with torch.no_grad():
        entropies = -(log_probabilities.exp() * log_probabilities).sum(dim=-1)
    return log_probabilities.gather(-1, targets[:, None])[:, 0], entropies


class CompletionTokenScores(torch.nn.Module):
    """Log-probabilities and entropies at the completion positions, rows (or packed slots) in order."""

    def __init__(self, causal_model: transformers.PreTrainedModel) -> None:
        super().__init__()
        self.causal_model = causal_model

    def forward(self, batch: Batch, temperatures: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """`temperatures`: per completion position, what its logits are divided by."""
        if batch.sequence_starts:
            hidden = packed_hidden_states(
                self.causal_model.model, batch.input_ids, batch.position_ids, batch.sequence_starts
            )
        else:
            hidden = self.causal_model.model(
                input_ids=batch.input_ids, attention_mask=batch.attention_mask, use_cache=False
            ).last_hidden_state
        targets = batch.labels[:, 1:]
        mask = targets != IGNORE_INDEX
        selected_hidden = hidden[:, :-1][mask]
        selected_targets = targets[mask]
        chunks = [
            torch.utils.checkpoint.checkpoint(
                chunk_scores,
                self.causal_model.lm_head,
                selected_hidden[start : start + SCORE_CHUNK_POSITIONS],
                selected_targets[start : start + SCORE_CHUNK_POSITIONS],
                temperatures[start : start + SCORE_CHUNK_POSITIONS],
                use_reentrant=False,
            )
            for start in range(0, len(selected_targets), SCORE_CHUNK_POSITIONS)
        ]
        return torch.cat([scores for scores, _ in chunks]), torch.cat([entropies for _, entropies in chunks])


def plan_micro_batches(
    indices: Sequence[int], lengths: Sequence[int], max_tokens: int, packing: bool
) -> list[tuple[int, ...]]:
    if packing:
        return packed_item_micro_batches(indices, lengths, max_tokens)
    return token_micro_batches(indices, lengths, max_tokens)


def completion_temperatures(
    examples: Sequence[TokenizedExample], temperatures: Sequence[float], device: torch.device
) -> torch.Tensor:
    return torch.tensor(
        [
            temperature
            for example, temperature in zip(examples, temperatures, strict=True)
            for _ in range(example.completion_token_count)
        ],
        dtype=torch.float32,
        device=device,
    )


@torch.no_grad()
def completion_log_probabilities(
    scorer: CompletionTokenScores,
    examples: Sequence[TokenizedExample],
    temperatures: Sequence[float],
    micro_batch_tokens: int,
    packing: bool,
    pad_token_id: int,
    device: torch.device,
) -> list[torch.Tensor]:
    """Per example, the log-probabilities of its completion tokens at its temperature (on the CPU, float32)."""
    lengths = [example.token_count for example in examples]
    results: list[torch.Tensor] = [torch.empty(0)] * len(examples)
    for indices in plan_micro_batches(range(len(examples)), lengths, micro_batch_tokens, packing):
        batch_examples = [examples[index] for index in indices]
        batch = micro_batch(batch_examples, packing, pad_token_id, device)
        batch_temperatures = completion_temperatures(batch_examples, [temperatures[index] for index in indices], device)
        with torch.autocast(device.type, dtype=torch.bfloat16):
            scores, _ = scorer(batch, batch_temperatures)
        sizes = [examples[index].completion_token_count for index in indices]
        for index, part in zip(indices, scores.float().cpu().split(sizes), strict=True):
            results[index] = part
    return results


def plan_grpo_steps(sequences: Sequence[PolicySequence], config: GrpoConfig) -> list[GrpoStep]:
    """Shuffled steps of `sequences_per_step` sequences per pass; a pass's last step may be smaller."""
    generator = random.Random(config.optimization.seed)
    lengths = [sequence.token_count for sequence in sequences]
    optimization = config.optimization
    steps = []
    for pass_index in range(config.passes_per_phase):
        order = list(range(len(sequences)))
        generator.shuffle(order)
        for start in range(0, len(order), config.sequences_per_step):
            indices = order[start : start + config.sequences_per_step]
            micro_batches = plan_micro_batches(indices, lengths, optimization.micro_batch_tokens, optimization.packing)
            steps.append(GrpoStep(tuple(indices), tuple(micro_batches), pass_index))
    return steps[: optimization.max_steps] if optimization.max_steps else steps


def sequence_tensors(sequences: Sequence[PolicySequence], device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    """Per completion token of the sequences in order: advantage, and 1 where trained (else 0)."""
    advantages = torch.tensor([value for sequence in sequences for value in sequence.advantages])
    weights = torch.tensor([trained for sequence in sequences for trained in sequence.trained], dtype=torch.float32)
    return advantages.to(device), weights.to(device)


def sampler_agreement(sequences: Sequence[PolicySequence], old: Sequence[torch.Tensor]) -> SamplerAgreement:
    """Over the tokens with a recorded sampler log-probability (re-tokenized records have none)."""
    trainer_values = []
    sampler_values = []
    for sequence, scores in zip(sequences, old, strict=True):
        for index, value in enumerate(sequence.sampler_log_probabilities):
            if value is not None:
                trainer_values.append(scores[index].item())
                sampler_values.append(value)
    if not sampler_values:
        return SamplerAgreement(0, 0.0, 0.0, 0.0)
    difference = torch.tensor(trainer_values, dtype=torch.float64) - torch.tensor(sampler_values, dtype=torch.float64)
    return SamplerAgreement(
        tokens=len(sampler_values),
        mean_difference=difference.mean().item(),
        mean_absolute_difference=difference.abs().mean().item(),
        kl_sampler_to_trainer=kl_estimate(difference).mean().item(),
    )


def reference_log_probabilities(
    config: GrpoConfig,
    saved_module: torch.nn.Module,
    scorer: CompletionTokenScores,
    examples: Sequence[TokenizedExample],
    temperatures: Sequence[float],
    old: list[torch.Tensor],
    pad_token_id: int,
    device: torch.device,
) -> list[torch.Tensor]:
    if config.reference == ReferencePolicy.PHASE_START or not config.initial_adapter:
        return old
    with saved_module.disable_adapter():
        return completion_log_probabilities(
            scorer,
            examples,
            temperatures,
            config.scoring_micro_batch_tokens,
            config.optimization.packing,
            pad_token_id,
            device,
        )


class ReplayCycle:
    """Replay examples in a shuffled order, drawn a few per step and reshuffled when used up."""

    def __init__(self, examples: Sequence[TokenizedExample], seed: int) -> None:
        self.examples = examples
        self.generator = random.Random(seed)
        self.order: list[int] = []

    def draw(self, count: int) -> list[TokenizedExample]:
        drawn = []
        while self.examples and len(drawn) < count:
            if not self.order:
                self.order = list(range(len(self.examples)))
                self.generator.shuffle(self.order)
            drawn.append(self.examples[self.order.pop()])
        return drawn


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def train_grpo(
    config: GrpoConfig,
    pad_token_id: int,
    sequences: Sequence[PolicySequence],
    replay: Sequence[TokenizedExample],
    device: torch.device,
    output_directory: Path,
    on_step: Callable[[GrpoStepRecord], None],
) -> GrpoTrainingResult:
    optimization = config.optimization
    assert optimization.method == FineTuningMethod.LORA, optimization.method
    longest = max((sequence.token_count for sequence in sequences), default=0)
    assert longest <= config.max_sequence_tokens, f"a recorded sample of {longest} tokens"
    saved_module, causal_model = load_trainable_model(
        config.model, optimization, config.lora, device, config.initial_adapter
    )
    scorer = CompletionTokenScores(causal_model)
    examples = [sequence.tokenized for sequence in sequences]
    temperatures = [sequence.temperature for sequence in sequences]
    scoring_started = time.perf_counter()
    causal_model.eval()
    old = completion_log_probabilities(
        scorer, examples, temperatures, config.scoring_micro_batch_tokens, optimization.packing, pad_token_id, device
    )
    agreement = sampler_agreement(sequences, old)
    reference = reference_log_probabilities(
        config, saved_module, scorer, examples, temperatures, old, pad_token_id, device
    )
    causal_model.train()
    scoring_seconds = time.perf_counter() - scoring_started
    parameters = trainable_parameters(saved_module)
    optimizer = torch.optim.AdamW(
        parameters, lr=optimization.learning_rate, weight_decay=optimization.weight_decay, fused=device.type == "cuda"
    )
    steps = plan_grpo_steps(sequences, config)
    warmup_steps = config.warmup_steps or max(1, round(optimization.warmup_fraction * len(steps)))
    scheduler = torch.optim.lr_scheduler.LambdaLR(
        optimizer,
        lambda step: learning_rate_factor(step, warmup_steps, len(steps), optimization.minimum_learning_rate_ratio),
    )
    replay_cycle = ReplayCycle(replay, optimization.seed)
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    records: list[GrpoStepRecord] = []
    training_seconds = 0.0
    for step_index, step in enumerate(steps):
        step_started = time.perf_counter()
        totals = torch.zeros(8, dtype=torch.float64, device=device)
        normalizer = len(step.sequences) * config.normalization_tokens
        tokens = 0
        for indices in step.micro_batches:
            batch_sequences = [sequences[index] for index in indices]
            batch = micro_batch(
                [sequence.tokenized for sequence in batch_sequences], optimization.packing, pad_token_id, device
            )
            batch_temperatures = completion_temperatures(
                [sequence.tokenized for sequence in batch_sequences],
                [sequence.temperature for sequence in batch_sequences],
                device,
            )
            with torch.autocast(device.type, dtype=torch.bfloat16):
                log_probabilities, entropies = scorer(batch, batch_temperatures)
            log_probabilities = log_probabilities.float()
            old_log_probabilities = torch.cat([old[index] for index in indices]).to(device)
            reference_values = torch.cat([reference[index] for index in indices]).to(device)
            advantages, weights = sequence_tensors(batch_sequences, device)
            token_losses = clipped_policy_losses(
                log_probabilities, old_log_probabilities, advantages, config.clip_low, config.clip_high
            )
            kl_to_reference = kl_estimate(reference_values - log_probabilities)
            policy_loss = (weights * token_losses.losses).sum() / normalizer
            loss = policy_loss + config.kl_coefficient * (weights * kl_to_reference).sum() / normalizer
            loss.backward()
            trained = weights > 0
            with torch.no_grad():
                difference = log_probabilities - old_log_probabilities
                totals += torch.stack(
                    [
                        loss.detach().double(),
                        policy_loss.detach().double(),
                        kl_estimate(difference)[trained].sum().double(),
                        kl_to_reference[trained].sum().double(),
                        token_losses.clipped[trained].sum().double(),
                        entropies[trained].sum().double(),
                        torch.exp(difference)[trained].sum().double(),
                        trained.sum().double(),
                    ]
                )
            tokens += batch.input_ids.numel()
        replay_nll = 0.0
        if config.replay_sequences_per_step and config.replay_weight:
            replay_nll = replay_backward(
                scorer, replay_cycle.draw(config.replay_sequences_per_step), config, pad_token_id, device
            )
        gradient_norm = torch.nn.utils.clip_grad_norm_(parameters, optimization.max_gradient_norm).item()
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        training_seconds += time.perf_counter() - step_started
        loss, policy_loss, kl_old, kl_reference, clipped, entropy, ratio, trained_tokens = totals.tolist()
        per_token = max(1.0, trained_tokens)
        record = GrpoStepRecord(
            step=step_index + 1,
            pass_index=step.pass_index,
            learning_rate=scheduler.get_last_lr()[0],
            loss=loss + config.replay_weight * replay_nll,
            policy_loss=policy_loss,
            kl_to_data_policy=kl_old / per_token,
            kl_to_reference=kl_reference / per_token,
            clip_fraction=clipped / per_token,
            entropy=entropy / per_token,
            mean_ratio=ratio / per_token,
            replay_nll=replay_nll,
            gradient_norm=gradient_norm,
            sequences=len(step.sequences),
            trained_tokens=int(trained_tokens),
            tokens=tokens,
            training_seconds=training_seconds,
        )
        records.append(record)
        on_step(record)
    saved_module.save_pretrained(output_directory)
    last_pass = [record for record in records if record.pass_index == records[-1].pass_index] if records else []
    return GrpoTrainingResult(
        steps=len(steps),
        sequences=len(sequences),
        trained_tokens=sum(record.trained_tokens for record in records),
        scoring_seconds=scoring_seconds,
        training_seconds=training_seconds,
        peak_memory_gib=torch.cuda.max_memory_allocated(device) / 2**30 if device.type == "cuda" else 0.0,
        trainable_parameters=sum(parameter.numel() for parameter in parameters),
        final_kl_to_data_policy=mean([record.kl_to_data_policy for record in last_pass]),
        final_kl_to_reference=mean([record.kl_to_reference for record in last_pass]),
        final_clip_fraction=mean([record.clip_fraction for record in last_pass]),
        final_entropy=mean([record.entropy for record in last_pass]),
        final_policy_loss=mean([record.policy_loss for record in last_pass]),
        sampler_agreement=agreement,
    )


def replay_backward(
    scorer: CompletionTokenScores,
    examples: Sequence[TokenizedExample],
    config: GrpoConfig,
    pad_token_id: int,
    device: torch.device,
) -> float:
    """Back-propagates replay_weight times the mean token NLL of the examples; returns that mean NLL."""
    if not examples:
        return 0.0
    completion_tokens = sum(example.completion_token_count for example in examples)
    lengths = [example.token_count for example in examples]
    packing = config.optimization.packing
    nll_sum = 0.0
    for indices in plan_micro_batches(range(len(examples)), lengths, config.optimization.micro_batch_tokens, packing):
        batch_examples = [examples[index] for index in indices]
        batch = micro_batch(batch_examples, packing, pad_token_id, device)
        temperatures = completion_temperatures(batch_examples, [1.0] * len(batch_examples), device)
        with torch.autocast(device.type, dtype=torch.bfloat16):
            log_probabilities, _ = scorer(batch, temperatures)
        nll = -log_probabilities.float().sum()
        (config.replay_weight * nll / completion_tokens).backward()
        nll_sum += nll.item()
    return nll_sum / completion_tokens
