"""Serving precision (DESIGN.md "Precision"): served log-probabilities of fixed tokens against an exact reference."""

import contextlib
import inspect
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import torch
import transformers

from lean_search.policy.adapters import LORA_A_SUFFIX, LORA_B_SUFFIX
from lean_search.training.dpo import token_micro_batches
from lean_search.training.sft import collate
from lean_search.training.sft_data import IGNORE_INDEX, SftExample, TokenizedExample

SCORE_CHUNK_POSITIONS = 512
# vLLM reports a -inf log-probability as -9999.
SERVED_NEGATIVE_INFINITY = -9999.0


class ServingMode(StrEnum):
    BF16_MERGED = "bf16_merged"
    FP16_MERGED = "fp16_merged"
    # The adapter at runtime (vLLM LoRA, computed in bf16) on the bf16 base.
    LORA_BF16 = "lora_bf16"


class ReferencePrecision(StrEnum):
    # fp32 base and fp32 LoRA, unmerged, fp32 compute throughout: the trainer's exact model.
    FP32 = "fp32"
    # bf16 base, fp32 LoRA, bf16 autocast with an fp32 output layer: the trainer as it runs.
    TRAINER_BF16 = "trainer_bf16"


@dataclass(frozen=True)
class Perturbation:
    name: str
    learning_rate: float
    # Adam's bias-corrected first step moves every parameter by about learning_rate * sign(gradient); `steps` such steps
    # with a consistent sign move it by learning_rate * steps.
    steps: int = 1
    seed: int = 0

    @property
    def element_step(self) -> float:
        return self.learning_rate * self.steps


@dataclass(frozen=True)
class PerturbationSize:
    element_step: float
    # |delta| / |adapter| over all LoRA parameters.
    relative_norm: float
    # RMS over the adapted weights' elements of the change of the merged update, scale * (B'A' - BA).
    merged_update_rms: float
    # RMS of the adapter's whole merged update scale * BA, for scale.
    adapter_merged_rms: float


@dataclass(frozen=True)
class SampleSequence:
    prompt_index: int
    sample_index: int
    prompt_token_ids: tuple[int, ...]
    completion_token_ids: tuple[int, ...]
    # The generating server's processed (tempered) log-probabilities of the sampled tokens.
    sampled_log_probabilities: tuple[float, ...]
    finish_reason: str


@dataclass(frozen=True)
class TokenScores:
    """Per completion token of every sequence, concatenated in the sample set's order."""

    raw: np.ndarray
    tempered_top_k: np.ndarray
    # Exact at the temperature; only the transformers reference has it.
    tempered: np.ndarray | None = None


@dataclass(frozen=True)
class Agreement:
    tokens: int
    sequences: int
    # Tokens left out because a side is not finite (or vLLM's -inf); their sequences leave the sequence statistics.
    non_finite_tokens: int
    mean_absolute_difference: float
    p95_absolute_difference: float
    max_absolute_difference: float
    # Served minus reference: a systematic offset (e.g. a temperature mismatch) shows here.
    mean_difference: float
    # k3 with log_ratio = served - reference: exp(r) - r - 1, averaged over tokens; the tokens were sampled from the
    # bf16-merged server, close to the reference, so this approximates KL(reference || served).
    k3_kl: float
    sequence_mean_absolute_difference: float
    sequence_p95_absolute_difference: float


@dataclass(frozen=True)
class UpdateVisibility:
    tokens: int
    sequences: int
    reference_change_mean_absolute: float
    served_change_mean_absolute: float
    # Least-squares slope of the served change on the reference change: 1 survives serving, 0 rounded away.
    slope: float
    correlation: float
    sequence_slope: float
    sequence_correlation: float


@dataclass(frozen=True)
class ChunkScores:
    raw: torch.Tensor
    tempered: torch.Tensor
    # The top k raw log-probabilities and the target's when outside them (else -inf), per position.
    candidates: torch.Tensor


def sequence_lengths(sequences: Sequence[SampleSequence]) -> list[int]:
    return [len(sequence.completion_token_ids) for sequence in sequences]


def tempered_from_candidates(target: np.ndarray, candidates: np.ndarray, temperature: float) -> np.ndarray:
    """log p_T(target) from raw log-probabilities and a candidate set containing the target (-inf padded)."""
    scaled = candidates / temperature
    maximum = scaled.max(axis=1, keepdims=True)
    log_partition = maximum[:, 0] + np.log(np.exp(scaled - maximum).sum(axis=1))
    return target / temperature - log_partition


def served_completion_scores(
    prompt_logprobs: Sequence[Mapping[str, Mapping[str, object]] | None],
    returned_token_ids: Sequence[int],
    sequence: SampleSequence,
    top_k: int,
    temperature: float,
) -> TokenScores:
    """The completion tokens' scores from vLLM's `prompt_logprobs` of prompt + completion, alignment checked."""
    token_ids = (*sequence.prompt_token_ids, *sequence.completion_token_ids)
    if tuple(returned_token_ids) != token_ids:
        raise ValueError(f"Sequence {sequence.prompt_index}/{sequence.sample_index}: the server scored other tokens")
    if len(prompt_logprobs) != len(token_ids):
        raise ValueError(
            f"Sequence {sequence.prompt_index}/{sequence.sample_index}: {len(prompt_logprobs)} prompt log-probability "
            f"positions for {len(token_ids)} tokens"
        )
    prompt_length = len(sequence.prompt_token_ids)
    completion_length = len(sequence.completion_token_ids)
    target = np.empty(completion_length)
    candidates = np.full((completion_length, top_k + 1), -np.inf)
    for offset, token_id in enumerate(sequence.completion_token_ids):
        position = prompt_logprobs[prompt_length + offset]
        key = str(token_id)
        if position is None or key not in position or len(position) > top_k + 1:
            raise ValueError(
                f"Sequence {sequence.prompt_index}/{sequence.sample_index}: completion token {offset} ({token_id}) is "
                "not the scored token at its position"
            )
        values = [float(entry["logprob"]) for entry in position.values()]
        target[offset] = float(position[key]["logprob"])
        candidates[offset, : len(values)] = values
    finite_candidates = np.where(candidates <= SERVED_NEGATIVE_INFINITY, -np.inf, candidates)
    return TokenScores(target, tempered_from_candidates(target, finite_candidates, temperature))


def chunk_token_scores(
    output_weight: torch.Tensor, hidden: torch.Tensor, targets: torch.Tensor, temperature: float, top_k: int
) -> ChunkScores:
    """fp32 logits as in policy_trainer.chunk_scores, scored at temperature 1 and at `temperature`."""
    with torch.autocast(hidden.device.type, enabled=False):
        logits = hidden.float() @ output_weight.float().T
    raw_all = torch.log_softmax(logits, dim=-1)
    raw = raw_all.gather(-1, targets[:, None])[:, 0]
    tempered = torch.log_softmax(logits / temperature, dim=-1).gather(-1, targets[:, None])[:, 0]
    top = raw_all.topk(top_k, dim=-1)
    in_top = (top.indices == targets[:, None]).any(dim=-1)
    outside = torch.where(in_top, torch.full_like(raw, -torch.inf), raw)
    return ChunkScores(raw, tempered, torch.cat([top.values, outside[:, None]], dim=1))


def tokenized(sequence: SampleSequence) -> TokenizedExample:
    placeholder = SftExample("serving_precision", str(sequence.prompt_index), sequence.sample_index, (), "")
    return TokenizedExample(
        placeholder, (*sequence.prompt_token_ids, *sequence.completion_token_ids), len(sequence.prompt_token_ids)
    )


@torch.no_grad()
def reference_scores(
    causal_model: transformers.PreTrainedModel,
    sequences: Sequence[SampleSequence],
    precision: ReferencePrecision,
    temperature: float,
    top_k: int,
    micro_batch_tokens: int,
    pad_token_id: int,
    device: torch.device,
) -> TokenScores:
    """The completion tokens' scores under a transformers model with its adapter."""
    examples = [tokenized(sequence) for sequence in sequences]
    raw: list[np.ndarray] = [np.empty(0)] * len(sequences)
    tempered: list[np.ndarray] = [np.empty(0)] * len(sequences)
    tempered_top_k: list[np.ndarray] = [np.empty(0)] * len(sequences)
    autocast = torch.autocast(device.type, dtype=torch.bfloat16, enabled=precision == ReferencePrecision.TRAINER_BF16)
    lengths = [example.token_count for example in examples]
    for indices in token_micro_batches(range(len(examples)), lengths, micro_batch_tokens):
        batch = collate([examples[index] for index in indices], pad_token_id, device)
        with autocast:
            hidden = causal_model.model(
                input_ids=batch.input_ids, attention_mask=batch.attention_mask, use_cache=False
            ).last_hidden_state
        targets = batch.labels[:, 1:]
        mask = targets != IGNORE_INDEX
        selected_hidden = hidden[:, :-1][mask]
        selected_targets = targets[mask]
        expected = [token for index in indices for token in sequences[index].completion_token_ids]
        assert selected_targets.tolist() == expected
        chunks = [
            chunk_token_scores(
                causal_model.lm_head.weight,
                selected_hidden[start : start + SCORE_CHUNK_POSITIONS],
                selected_targets[start : start + SCORE_CHUNK_POSITIONS],
                temperature,
                top_k,
            )
            for start in range(0, len(selected_targets), SCORE_CHUNK_POSITIONS)
        ]
        batch_raw = torch.cat([chunk.raw for chunk in chunks]).double().cpu().numpy()
        batch_tempered = torch.cat([chunk.tempered for chunk in chunks]).double().cpu().numpy()
        batch_candidates = torch.cat([chunk.candidates for chunk in chunks]).double().cpu().numpy()
        batch_top_k = tempered_from_candidates(batch_raw, batch_candidates, temperature)
        boundaries = np.cumsum([len(sequences[index].completion_token_ids) for index in indices])[:-1]
        for index, part_raw, part_tempered, part_top_k in zip(
            indices,
            np.split(batch_raw, boundaries),
            np.split(batch_tempered, boundaries),
            np.split(batch_top_k, boundaries),
            strict=True,
        ):
            raw[index], tempered[index], tempered_top_k[index] = part_raw, part_tempered, part_top_k
    return TokenScores(np.concatenate(raw), np.concatenate(tempered_top_k), np.concatenate(tempered))


@contextlib.contextmanager
def exact_fp32_compute() -> Iterator[None]:
    """IEEE fp32 throughout; flash-linear-attention's kernels and cuDNN's default use TF32 for fp32 on Ampere."""
    import transformers.models.qwen3_5.modeling_qwen3_5 as qwen3_5

    matmul_precision = torch.backends.cuda.matmul.fp32_precision
    convolution_precision = torch.backends.cudnn.conv.fp32_precision
    chunk_rule = qwen3_5.torch_chunk_gated_delta_rule
    torch.backends.cuda.matmul.fp32_precision = "ieee"
    torch.backends.cudnn.conv.fp32_precision = "ieee"
    qwen3_5.torch_chunk_gated_delta_rule = inspect.unwrap(chunk_rule)
    try:
        with torch.nn.attention.sdpa_kernel(torch.nn.attention.SDPBackend.MATH):
            yield
    finally:
        qwen3_5.torch_chunk_gated_delta_rule = chunk_rule
        torch.backends.cuda.matmul.fp32_precision = matmul_precision
        torch.backends.cudnn.conv.fp32_precision = convolution_precision


def sign_perturbation(weights: Mapping[str, torch.Tensor], perturbation: Perturbation) -> dict[str, torch.Tensor]:
    """Every LoRA parameter moved by element_step with a seeded random sign."""
    generator = torch.Generator().manual_seed(perturbation.seed)
    perturbed = {}
    for key in sorted(weights):
        tensor = weights[key]
        signs = torch.randint(0, 2, tensor.shape, generator=generator).to(tensor.dtype) * 2 - 1
        perturbed[key] = tensor + perturbation.element_step * signs
    return perturbed


def perturbation_size(
    original: Mapping[str, torch.Tensor], perturbed: Mapping[str, torch.Tensor], scale: float, element_step: float
) -> PerturbationSize:
    assert original.keys() == perturbed.keys()
    delta_square = sum(float((perturbed[key].double() - original[key].double()).square().sum()) for key in original)
    original_square = sum(float(original[key].double().square().sum()) for key in original)
    update_square = adapter_square = 0.0
    elements = 0
    for key in original:
        if not key.endswith(LORA_A_SUFFIX):
            continue
        b_key = key.removesuffix(LORA_A_SUFFIX) + LORA_B_SUFFIX
        merged = scale * original[b_key].double() @ original[key].double()
        merged_perturbed = scale * perturbed[b_key].double() @ perturbed[key].double()
        update_square += float((merged_perturbed - merged).square().sum())
        adapter_square += float(merged.square().sum())
        elements += merged.numel()
    return PerturbationSize(
        element_step=element_step,
        relative_norm=(delta_square / original_square) ** 0.5,
        merged_update_rms=(update_square / elements) ** 0.5,
        adapter_merged_rms=(adapter_square / elements) ** 0.5,
    )


def finite_tokens(*scores: np.ndarray) -> np.ndarray:
    mask = np.ones(len(scores[0]), dtype=bool)
    for values in scores:
        mask &= np.isfinite(values) & (values > SERVED_NEGATIVE_INFINITY)
    return mask


def sequence_sums(values: np.ndarray, mask: np.ndarray, lengths: Sequence[int]) -> tuple[np.ndarray, np.ndarray]:
    """Per sequence, the sum of `values` and whether all its tokens are in `mask`."""
    starts = np.concatenate([[0], np.cumsum(lengths)[:-1]]).astype(int)
    nonempty = np.asarray(lengths) > 0
    sums = np.zeros(len(lengths))
    complete = np.ones(len(lengths), dtype=bool)
    sums[nonempty] = np.add.reduceat(np.where(mask, values, 0.0), starts[nonempty])
    complete[nonempty] = np.logical_and.reduceat(mask, starts[nonempty])
    return sums, complete


def mean_or_nan(values: np.ndarray) -> float:
    # An fp16 server can overflow to NaN everywhere; the report then says so instead of failing.
    return float(values.mean()) if values.size else float("nan")


def quantile_or_nan(values: np.ndarray, fraction: float) -> float:
    return float(np.quantile(values, fraction)) if values.size else float("nan")


def agreement(served: np.ndarray, reference: np.ndarray, lengths: Sequence[int]) -> Agreement:
    assert len(served) == len(reference) == sum(lengths)
    mask = finite_tokens(served, reference)
    difference = np.where(mask, served - reference, 0.0)
    log_ratio = difference[mask]
    absolute = np.abs(log_ratio)
    sums, complete = sequence_sums(difference, mask, lengths)
    sequence_absolute = np.abs(sums[complete])
    return Agreement(
        tokens=int(mask.sum()),
        sequences=int(complete.sum()),
        non_finite_tokens=int((~mask).sum()),
        mean_absolute_difference=mean_or_nan(absolute),
        p95_absolute_difference=quantile_or_nan(absolute, 0.95),
        max_absolute_difference=float(absolute.max()) if absolute.size else float("nan"),
        mean_difference=mean_or_nan(log_ratio),
        k3_kl=mean_or_nan(np.expm1(log_ratio) - log_ratio),
        sequence_mean_absolute_difference=mean_or_nan(sequence_absolute),
        sequence_p95_absolute_difference=quantile_or_nan(sequence_absolute, 0.95),
    )


def regression(reference: np.ndarray, served: np.ndarray) -> tuple[float, float]:
    """Least-squares slope of served on reference, and their correlation."""
    reference_centered = reference - reference.mean()
    served_centered = served - served.mean()
    covariance = float(reference_centered @ served_centered)
    reference_variance = float(reference_centered @ reference_centered)
    served_variance = float(served_centered @ served_centered)
    # A served change of exactly zero (the update rounded away entirely) has slope 0 and no correlation.
    slope = covariance / reference_variance if reference_variance > 0 else float("nan")
    scale = (reference_variance * served_variance) ** 0.5
    return slope, covariance / scale if scale > 0 else float("nan")


def update_visibility(
    served_base: np.ndarray,
    served_perturbed: np.ndarray,
    reference_base: np.ndarray,
    reference_perturbed: np.ndarray,
    lengths: Sequence[int],
) -> UpdateVisibility:
    mask = finite_tokens(served_base, served_perturbed, reference_base, reference_perturbed)
    served_change = np.where(mask, served_perturbed - served_base, 0.0)
    reference_change = np.where(mask, reference_perturbed - reference_base, 0.0)
    slope, correlation = regression(reference_change[mask], served_change[mask])
    served_sums, complete = sequence_sums(served_change, mask, lengths)
    reference_sums, _ = sequence_sums(reference_change, mask, lengths)
    sequence_slope, sequence_correlation = regression(reference_sums[complete], served_sums[complete])
    return UpdateVisibility(
        tokens=int(mask.sum()),
        sequences=int(complete.sum()),
        reference_change_mean_absolute=mean_or_nan(np.abs(reference_change[mask])),
        served_change_mean_absolute=mean_or_nan(np.abs(served_change[mask])),
        slope=slope,
        correlation=correlation,
        sequence_slope=sequence_slope,
        sequence_correlation=sequence_correlation,
    )
