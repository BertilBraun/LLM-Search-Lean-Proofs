"""GRPO of the policy LoRA: a PPO-clipped objective per sampled token, at the sampling temperature, with replay."""

import contextlib
import random
import statistics
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

import peft
import torch
import torch.utils.checkpoint
import transformers

from lean_search.policy.adapters import load_adapter_weights, lora_rank, lora_scale, saved_adapter_weights
from lean_search.rl.policy_data import (
    AdvantageSignRatios,
    PolicyDataConfig,
    PolicySequence,
    SamplerAgreement,
    SignedRatios,
    VersionSamplerAgreement,
)
from lean_search.training.data_parallel import (
    SINGLE_PROCESS,
    Ranks,
    balanced_shards,
    barrier,
    gathered,
    largest,
    local_shard,
    sum_gradients,
    summed,
)
from lean_search.training.dpo import packed_item_micro_batches, token_micro_batches
from lean_search.training.packing import packed_hidden_states
from lean_search.training.sft import (
    Batch,
    FineTuningMethod,
    LoraSettings,
    OptimizationConfig,
    TrainableLoader,
    learning_rate_factor,
    load_trainable_model,
    micro_batch,
    trainable_parameters,
)
from lean_search.training.sft_data import IGNORE_INDEX, TokenizedExample

# Smaller than the SFT loss chunks: the entropy needs the full log-softmax next to the logits.
SCORE_CHUNK_POSITIONS = 512
# PEFT's name of the adapter that trains.
TRAINED_ADAPTER_NAME = "default"


class ReferencePolicy(StrEnum):
    # The GRPO starting policy: `model` with `reference_adapter` (without any adapter when that is empty).
    STARTING_WEIGHTS = "starting_weights"
    # The policy at the phase's start, which collected most of the data.
    PHASE_START = "phase_start"


@dataclass(frozen=True)
class GrpoConfig:
    # The weights the LoRA adapter applies to: those the starting policy's own (SFT) adapter was trained on.
    model: str
    # The adapter to continue (the published one); empty starts a fresh adapter on `model`.
    initial_adapter: str = ""
    # The starting policy's adapter on `model` (the KL reference); empty: `model` itself is the starting policy.
    reference_adapter: str = ""
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
    # Without a KL penalty the reference only feeds the reported KL: scored on this many sequences (seeded draw).
    reference_sequences: int = 256
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
    # Per rank, the micro-batches of its share of the step's sequences (shares balanced by tokens).
    rank_micro_batches: tuple[tuple[tuple[int, ...], ...], ...]
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
    ratios: SignedRatios
    # Trained tokens of the sequences with a reference score, which the KL to the reference averages over.
    reference_tokens: int
    # The same over the first round's sequences alone (feedback rounds left out), for the health checks.
    first_round_kl_to_reference: float = 0.0
    first_round_clip_fraction: float = 0.0
    first_round_reference_tokens: int = 0
    first_round_trained_tokens: int = 0


@dataclass(frozen=True)
class GrpoTrainingResult:
    steps: int
    sequences: int
    trained_tokens: int
    scoring_seconds: float
    training_seconds: float
    peak_memory_gib: float
    trainable_parameters: int
    # Means over the last pass's steps; the KL to the reference their median.
    final_kl_to_data_policy: float
    final_kl_to_reference: float
    final_clip_fraction: float
    final_entropy: float
    final_policy_loss: float
    sampler_agreement: SamplerAgreement
    # The same per sampling version: trees spanning phases hold samples of earlier versions.
    sampler_agreement_by_version: tuple[VersionSamplerAgreement, ...] = ()
    # Per pass, in order, over its trained tokens.
    ratios_by_pass: tuple[SignedRatios, ...] = ()
    # Sequences scored under the reference policy.
    reference_sequences: int = 0
    load_seconds: float = 0.0
    # One scoring and one training micro-batch before scoring, which compile the compiled layers.
    compile_seconds: float = 0.0
    save_seconds: float = 0.0
    ranks: int = 1
    # The KL to the reference and the clip fraction of the first round's sequences, as the final values; None without
    # first-round tokens (and in older outcomes).
    final_first_round_kl_to_reference: float | None = None
    final_first_round_clip_fraction: float | None = None


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
    output_weight: torch.Tensor, hidden: torch.Tensor, targets: torch.Tensor, temperatures: torch.Tensor
) -> tuple[torch.Tensor, torch.Tensor]:
    # fp32 logits: one bf16 logit step (0.125 at |logit| 16-32) would move a PPO ratio by ~x1.17 at T = 0.8.
    with torch.autocast(hidden.device.type, enabled=False):
        logits = hidden.float() @ output_weight.float().T
    log_probabilities = torch.log_softmax(logits / temperatures[:, None], dim=-1)
    with torch.no_grad():
        entropies = -(log_probabilities.exp() * log_probabilities).sum(dim=-1)
    return log_probabilities.gather(-1, targets[:, None])[:, 0], entropies


class CompletionTokenScores(torch.nn.Module):
    """Log-probabilities and entropies at the completion positions, rows (or packed slots) in order."""

    def __init__(self, causal_model: transformers.PreTrainedModel) -> None:
        super().__init__()
        self.causal_model = causal_model
        assert causal_model.lm_head.bias is None

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
                self.causal_model.lm_head.weight,
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


def sharded_log_probabilities(
    scorer: CompletionTokenScores,
    examples: Sequence[TokenizedExample],
    temperatures: Sequence[float],
    micro_batch_tokens: int,
    packing: bool,
    pad_token_id: int,
    device: torch.device,
    ranks: Ranks,
) -> list[torch.Tensor]:
    """`completion_log_probabilities` of the rank's share of the examples (by tokens), gathered on every rank."""
    shard = local_shard(range(len(examples)), [example.token_count for example in examples], ranks)
    scores = completion_log_probabilities(
        scorer,
        [examples[index] for index in shard],
        [temperatures[index] for index in shard],
        micro_batch_tokens,
        packing,
        pad_token_id,
        device,
    )
    return gathered(list(zip(shard, scores, strict=True)), len(examples), ranks)


def plan_grpo_steps(sequences: Sequence[PolicySequence], config: GrpoConfig, world_size: int = 1) -> list[GrpoStep]:
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
            rank_micro_batches = tuple(
                tuple(plan_micro_batches(shard, lengths, optimization.micro_batch_tokens, optimization.packing))
                for shard in balanced_shards(indices, lengths, world_size)
            )
            steps.append(GrpoStep(tuple(indices), rank_micro_batches, pass_index))
    return steps[: optimization.max_steps] if optimization.max_steps else steps


def sequence_tensors(sequences: Sequence[PolicySequence], device: torch.device) -> tuple[torch.Tensor, torch.Tensor]:
    """Per completion token of the sequences in order: advantage, and 1 where trained (else 0)."""
    advantages = torch.tensor([value for sequence in sequences for value in sequence.advantages])
    weights = torch.tensor([trained for sequence in sequences for trained in sequence.trained], dtype=torch.float32)
    return advantages.to(device), weights.to(device)


def first_round_tensor(sequences: Sequence[PolicySequence], device: torch.device) -> torch.Tensor:
    """Per completion token of the sequences in order: whether its sequence is of a first round (not feedback)."""
    return torch.tensor(
        [not sequence.feedback for sequence in sequences for _ in sequence.advantages], dtype=torch.bool
    ).to(device)


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


def sampler_agreement_by_version(
    sequences: Sequence[PolicySequence], old: Sequence[torch.Tensor]
) -> tuple[VersionSamplerAgreement, ...]:
    """`sampler_agreement` per sampling version, unrecorded versions first."""
    indices_by_version: dict[int | None, list[int]] = {}
    for index, sequence in enumerate(sequences):
        indices_by_version.setdefault(sequence.policy_version, []).append(index)
    return tuple(
        VersionSamplerAgreement(
            version, sampler_agreement([sequences[index] for index in indices], [old[index] for index in indices])
        )
        for version, indices in sorted(indices_by_version.items(), key=lambda item: -1 if item[0] is None else item[0])
    )


def reference_sample(config: GrpoConfig, sequence_count: int) -> list[int]:
    """The sequences scored under the reference: all of them when the KL penalty trains on it."""
    if config.kl_coefficient or sequence_count <= config.reference_sequences:
        return list(range(sequence_count))
    return sorted(random.Random(config.optimization.seed).sample(range(sequence_count), config.reference_sequences))


def reference_log_probabilities(
    config: GrpoConfig,
    saved_module: torch.nn.Module,
    scorer: CompletionTokenScores,
    examples: Sequence[TokenizedExample],
    temperatures: Sequence[float],
    old: list[torch.Tensor],
    pad_token_id: int,
    device: torch.device,
    ranks: Ranks = SINGLE_PROCESS,
) -> list[torch.Tensor | None]:
    """Per example its reference log-probabilities, None outside `reference_sample`."""
    if config.reference == ReferencePolicy.PHASE_START or config.initial_adapter == config.reference_adapter:
        return list(old)
    chosen = reference_sample(config, len(examples))

    def scored() -> list[torch.Tensor | None]:
        scores = sharded_log_probabilities(
            scorer,
            [examples[index] for index in chosen],
            [temperatures[index] for index in chosen],
            config.scoring_micro_batch_tokens,
            config.optimization.packing,
            pad_token_id,
            device,
            ranks,
        )
        results: list[torch.Tensor | None] = [None] * len(examples)
        for index, score in zip(chosen, scores, strict=True):
            results[index] = score
        return results

    if not config.reference_adapter:
        with saved_module.disable_adapter():
            return scored()
    with reference_weights_in_place(saved_module, config.reference_adapter):
        return scored()


@contextlib.contextmanager
def reference_weights_in_place(saved_module: peft.PeftModel, reference_adapter: str) -> Iterator[None]:
    """The reference adapter's weights in the trained adapter's place, the trained ones back afterwards. The reference
    is the starting adapter the trained one continues, so they share rank and scale; loading it as a second adapter
    would add modules, which recompiles the compiled layers of a resident model in every phase."""
    trained = saved_module.peft_config[TRAINED_ADAPTER_NAME]
    reference = Path(reference_adapter)
    assert (lora_rank(reference), lora_scale(reference)) == (trained.r, trained.lora_alpha / trained.r), reference
    kept = {name: tensor.clone() for name, tensor in peft.get_peft_model_state_dict(saved_module).items()}
    load_adapter_weights(saved_module, saved_adapter_weights(reference, next(saved_module.parameters()).device))
    try:
        yield
    finally:
        load_adapter_weights(saved_module, kept)


def reference_tensors(
    reference: Sequence[torch.Tensor | None], sequences: Sequence[PolicySequence], device: torch.device
) -> tuple[torch.Tensor, torch.Tensor]:
    """Per completion token of the sequences in order: the reference log-probability (0 where not scored), and
    whether it was scored."""
    counts = [sequence.tokenized.completion_token_count for sequence in sequences]
    values = [torch.zeros(count) if scores is None else scores for scores, count in zip(reference, counts, strict=True)]
    scored = [torch.full((count,), scores is not None) for scores, count in zip(reference, counts, strict=True)]
    return torch.cat(values).to(device), torch.cat(scored).to(device)


def sign_ratios(ratio_sum: float, clipped: float, tokens: float) -> AdvantageSignRatios:
    return AdvantageSignRatios(int(tokens), ratio_sum / max(1.0, tokens), clipped / max(1.0, tokens))


def signed_ratios(sums: Sequence[float]) -> SignedRatios:
    """From the ratio sum, clipped tokens and tokens of the positive, then of the negative advantages."""
    return SignedRatios(sign_ratios(*sums[:3]), sign_ratios(*sums[3:6]))


def ratio_sums(ratios: SignedRatios) -> list[float]:
    return [
        value
        for side in (ratios.positive, ratios.negative)
        for value in (side.mean_ratio * side.tokens, side.clip_fraction * side.tokens, float(side.tokens))
    ]


def ratios_by_pass(records: Sequence[GrpoStepRecord]) -> tuple[SignedRatios, ...]:
    """Token-weighted over each pass's steps, in pass order."""
    sums_by_pass: dict[int, list[float]] = {}
    for record in records:
        earlier = sums_by_pass.get(record.pass_index, [0.0] * 6)
        step = ratio_sums(record.ratios)
        sums_by_pass[record.pass_index] = [total + value for total, value in zip(earlier, step, strict=True)]
    return tuple(signed_ratios(sums) for _, sums in sorted(sums_by_pass.items()))


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


def median(values: Sequence[float]) -> float:
    return statistics.median(values) if values else 0.0


def compile_warm_up(
    saved_module: torch.nn.Module,
    scorer: CompletionTokenScores,
    example: TokenizedExample,
    temperature: float,
    packing: bool,
    pad_token_id: int,
    device: torch.device,
) -> float:
    """Compiles the compiled layers' scoring and training graphs on one example, so the timed passes exclude it."""
    started = time.perf_counter()
    batch = micro_batch([example], packing, pad_token_id, device)
    temperatures = completion_temperatures([example], [temperature], device)
    scorer.causal_model.eval()
    with torch.no_grad(), torch.autocast(device.type, dtype=torch.bfloat16):
        scorer(batch, temperatures)
    scorer.causal_model.train()
    with torch.autocast(device.type, dtype=torch.bfloat16):
        log_probabilities, _ = scorer(batch, temperatures)
    log_probabilities.float().sum().backward()
    saved_module.zero_grad(set_to_none=True)
    if device.type == "cuda":
        torch.cuda.synchronize(device)
    return time.perf_counter() - started


def train_grpo(
    config: GrpoConfig,
    pad_token_id: int,
    sequences: Sequence[PolicySequence],
    replay: Sequence[TokenizedExample],
    device: torch.device,
    output_directory: Path,
    on_step: Callable[[GrpoStepRecord], None],
    ranks: Ranks = SINGLE_PROCESS,
    load: TrainableLoader = load_trainable_model,
) -> GrpoTrainingResult:
    """On every rank with the same arguments; only the main rank reports steps and saves the adapter. `load` gives
    the model (a resident one in the persistent training job)."""
    optimization = config.optimization
    assert optimization.method == FineTuningMethod.LORA, optimization.method
    longest = max((sequence.token_count for sequence in sequences), default=0)
    assert longest <= config.max_sequence_tokens, f"a recorded sample of {longest} tokens"
    load_started = time.perf_counter()
    saved_module, causal_model = load(config.model, optimization, config.lora, device, config.initial_adapter)
    scorer = CompletionTokenScores(causal_model)
    load_seconds = time.perf_counter() - load_started
    examples = [sequence.tokenized for sequence in sequences]
    temperatures = [sequence.temperature for sequence in sequences]
    compile_seconds = 0.0
    if optimization.compile_layers and sequences:
        shortest = min(range(len(sequences)), key=lambda index: examples[index].token_count)
        compile_seconds = compile_warm_up(
            saved_module, scorer, examples[shortest], temperatures[shortest], optimization.packing, pad_token_id, device
        )
    scoring_started = time.perf_counter()
    causal_model.eval()
    old = sharded_log_probabilities(
        scorer,
        examples,
        temperatures,
        config.scoring_micro_batch_tokens,
        optimization.packing,
        pad_token_id,
        device,
        ranks,
    )
    agreement = sampler_agreement(sequences, old)
    agreement_by_version = sampler_agreement_by_version(sequences, old)
    reference = reference_log_probabilities(
        config, saved_module, scorer, examples, temperatures, old, pad_token_id, device, ranks
    )
    causal_model.train()
    scoring_seconds = time.perf_counter() - scoring_started
    parameters = trainable_parameters(saved_module)
    optimizer = torch.optim.AdamW(
        parameters, lr=optimization.learning_rate, weight_decay=optimization.weight_decay, fused=device.type == "cuda"
    )
    steps = plan_grpo_steps(sequences, config, ranks.world_size)
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
        totals = torch.zeros(20, dtype=torch.float64, device=device)
        # The whole step's sequences on every rank, so that the ranks' gradients sum to the single-process gradient.
        normalizer = len(step.sequences) * config.normalization_tokens
        for indices in step.rank_micro_batches[ranks.rank]:
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
            reference_values, reference_scored = reference_tensors(
                [reference[index] for index in indices], batch_sequences, device
            )
            advantages, weights = sequence_tensors(batch_sequences, device)
            token_losses = clipped_policy_losses(
                log_probabilities, old_log_probabilities, advantages, config.clip_low, config.clip_high
            )
            # Unscored tokens get their own value: a log-ratio of 0, so no KL and no gradient.
            reference_values = torch.where(reference_scored, reference_values, log_probabilities.detach())
            kl_to_reference = kl_estimate(reference_values - log_probabilities)
            policy_loss = (weights * token_losses.losses).sum() / normalizer
            loss = policy_loss + config.kl_coefficient * (weights * kl_to_reference).sum() / normalizer
            loss.backward()
            trained = weights > 0
            first_round = trained & first_round_tensor(batch_sequences, device)
            with torch.no_grad():
                ratio = torch.exp(log_probabilities - old_log_probabilities)
                positive = trained & (advantages > 0)
                negative = trained & (advantages < 0)
                totals[:8] += torch.stack(
                    [
                        loss.detach().double(),
                        policy_loss.detach().double(),
                        kl_estimate(log_probabilities - old_log_probabilities)[trained].sum().double(),
                        kl_to_reference[trained].sum().double(),
                        token_losses.clipped[trained].sum().double(),
                        entropies[trained].sum().double(),
                        ratio[trained].sum().double(),
                        trained.sum().double(),
                    ]
                )
                totals[9:16] += torch.stack(
                    [
                        (trained & reference_scored).sum().double(),
                        ratio[positive].sum().double(),
                        token_losses.clipped[positive].sum().double(),
                        positive.sum().double(),
                        ratio[negative].sum().double(),
                        token_losses.clipped[negative].sum().double(),
                        negative.sum().double(),
                    ]
                )
                totals[16:] += torch.stack(
                    [
                        kl_to_reference[first_round].sum().double(),
                        (first_round & reference_scored).sum().double(),
                        token_losses.clipped[first_round].sum().double(),
                        first_round.sum().double(),
                    ]
                )
            totals[8] += batch.input_ids.numel()
        replay_nll = 0.0
        if config.replay_sequences_per_step and config.replay_weight:
            replay_nll = replay_backward(
                scorer, replay_cycle.draw(config.replay_sequences_per_step), config, pad_token_id, device, ranks
            )
        sum_gradients(parameters, ranks)
        gradient_norm = torch.nn.utils.clip_grad_norm_(parameters, optimization.max_gradient_norm).item()
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad(set_to_none=True)
        summed(totals, ranks)
        if device.type == "cuda":
            torch.cuda.synchronize(device)
        training_seconds += time.perf_counter() - step_started
        values = totals.tolist()
        loss, policy_loss, kl_old, kl_reference, clipped, entropy, ratio, trained_tokens, tokens = values[:9]
        reference_tokens = values[9]
        first_round_kl, first_round_reference_tokens, first_round_clipped, first_round_tokens = values[16:]
        per_token = max(1.0, trained_tokens)
        record = GrpoStepRecord(
            step=step_index + 1,
            pass_index=step.pass_index,
            learning_rate=scheduler.get_last_lr()[0],
            loss=loss + config.replay_weight * replay_nll,
            policy_loss=policy_loss,
            kl_to_data_policy=kl_old / per_token,
            kl_to_reference=kl_reference / max(1.0, reference_tokens),
            clip_fraction=clipped / per_token,
            entropy=entropy / per_token,
            mean_ratio=ratio / per_token,
            replay_nll=replay_nll,
            gradient_norm=gradient_norm,
            sequences=len(step.sequences),
            trained_tokens=int(trained_tokens),
            tokens=int(tokens),
            training_seconds=training_seconds,
            ratios=signed_ratios(values[10:16]),
            reference_tokens=int(reference_tokens),
            first_round_kl_to_reference=first_round_kl / max(1.0, first_round_reference_tokens),
            first_round_clip_fraction=first_round_clipped / max(1.0, first_round_tokens),
            first_round_reference_tokens=int(first_round_reference_tokens),
            first_round_trained_tokens=int(first_round_tokens),
        )
        records.append(record)
        if ranks.is_main:
            on_step(record)
    save_started = time.perf_counter()
    if ranks.is_main:
        saved_module.save_pretrained(output_directory)
    barrier(ranks)
    save_seconds = time.perf_counter() - save_started
    peak_memory = torch.cuda.max_memory_allocated(device) / 2**30 if device.type == "cuda" else 0.0
    last_pass = [record for record in records if record.pass_index == records[-1].pass_index] if records else []
    first_round_kl = [record.first_round_kl_to_reference for record in last_pass if record.first_round_reference_tokens]
    first_round_clip = [record.first_round_clip_fraction for record in last_pass if record.first_round_trained_tokens]
    return GrpoTrainingResult(
        steps=len(steps),
        sequences=len(sequences),
        trained_tokens=sum(record.trained_tokens for record in records),
        scoring_seconds=scoring_seconds,
        training_seconds=training_seconds,
        peak_memory_gib=largest(peak_memory, device, ranks),
        trainable_parameters=sum(parameter.numel() for parameter in parameters),
        final_kl_to_data_policy=mean([record.kl_to_data_policy for record in last_pass]),
        # k3 on tokens the data policy sampled has a heavy tail: a rare token the reference prefers by ~e^10 alone
        # moves a step's mean by 10^3-10^5 (phase 1 of grpo_loop_v1), so the phase's value is the steps' median.
        final_kl_to_reference=median([record.kl_to_reference for record in last_pass]),
        final_clip_fraction=mean([record.clip_fraction for record in last_pass]),
        final_entropy=mean([record.entropy for record in last_pass]),
        final_policy_loss=mean([record.policy_loss for record in last_pass]),
        sampler_agreement=agreement,
        sampler_agreement_by_version=agreement_by_version,
        ratios_by_pass=ratios_by_pass(records),
        reference_sequences=sum(scores is not None for scores in reference),
        load_seconds=load_seconds,
        compile_seconds=compile_seconds,
        save_seconds=save_seconds,
        ranks=ranks.world_size,
        final_first_round_kl_to_reference=median(first_round_kl) if first_round_kl else None,
        final_first_round_clip_fraction=mean(first_round_clip) if first_round_clip else None,
    )


def replay_backward(
    scorer: CompletionTokenScores,
    examples: Sequence[TokenizedExample],
    config: GrpoConfig,
    pad_token_id: int,
    device: torch.device,
    ranks: Ranks = SINGLE_PROCESS,
) -> float:
    """Back-propagates replay_weight times the mean token NLL of the examples, each rank its share by tokens;
    returns that mean NLL."""
    if not examples:
        return 0.0
    completion_tokens = sum(example.completion_token_count for example in examples)
    lengths = [example.token_count for example in examples]
    packing = config.optimization.packing
    nll_sum = torch.zeros((), dtype=torch.float64, device=device)
    local = local_shard(range(len(examples)), lengths, ranks)
    for indices in plan_micro_batches(local, lengths, config.optimization.micro_batch_tokens, packing):
        batch_examples = [examples[index] for index in indices]
        batch = micro_batch(batch_examples, packing, pad_token_id, device)
        temperatures = completion_temperatures(batch_examples, [1.0] * len(batch_examples), device)
        with torch.autocast(device.type, dtype=torch.bfloat16):
            log_probabilities, _ = scorer(batch, temperatures)
        nll = -log_probabilities.float().sum()
        (config.replay_weight * nll / completion_tokens).backward()
        nll_sum += nll.detach().double()
    return summed(nll_sum, ranks).item() / completion_tokens
