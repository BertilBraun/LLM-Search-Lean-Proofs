"""The value loss on the nine bin logits: smoothed exact targets, censored lower bounds and dead ends."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import torch

from lean_search.value.bins import BIN_COUNT, DEAD_BIN, STEP_BIN_COUNT
from lean_search.value.labels import LabelKind, ValueExample

KIND_INDEX = {LabelKind.EXACT: 0, LabelKind.AT_LEAST: 1, LabelKind.DEAD: 2}


@dataclass(frozen=True)
class LossConfig:
    # Standard deviation of the Gaussian over remaining steps, in bins; 0 gives one-hot targets.
    smoothing_sigma: float = 0.5
    # Weight of -log(full-vocabulary probability of any bin token), which keeps the bins in vLLM's top-k logprobs.
    bin_mass_weight: float = 1.0


@dataclass(frozen=True)
class LabelTensors:
    kinds: torch.Tensor
    steps: torch.Tensor
    weights: torch.Tensor


def label_tensors(examples: Sequence[ValueExample], device: torch.device) -> LabelTensors:
    return LabelTensors(
        kinds=torch.tensor([KIND_INDEX[example.kind] for example in examples], device=device),
        steps=torch.tensor([example.steps for example in examples], device=device),
        weights=torch.tensor([example.weight for example in examples], dtype=torch.float32, device=device),
    )


def exact_targets(steps: torch.Tensor, sigma: float) -> torch.Tensor:
    """The mass of N(steps, sigma^2) on each step bin (the first and the 8+ bin are open-ended); dead gets none."""
    if sigma == 0:
        step_bins = steps.clamp(1, STEP_BIN_COUNT) - 1
        return torch.nn.functional.one_hot(step_bins, BIN_COUNT).float()
    inner_edges = torch.arange(1.5, STEP_BIN_COUNT, 1.0, device=steps.device)
    cumulative = 0.5 * (1 + torch.erf((inner_edges - steps.float()[:, None]) / (sigma * math.sqrt(2))))
    zeros = torch.zeros_like(cumulative[:, :1])
    cumulative = torch.cat([zeros, cumulative, zeros + 1], dim=1)
    return torch.cat([cumulative.diff(dim=1), zeros], dim=1)


def at_least_mask(steps: torch.Tensor) -> torch.Tensor:
    """Bins consistent with "at least `steps` more steps, possibly dead"."""
    bins = torch.arange(BIN_COUNT, device=steps.device)
    return (bins[None, :] >= steps.clamp(1, STEP_BIN_COUNT)[:, None] - 1) | (bins[None, :] == DEAD_BIN)


def value_losses(bin_logits: torch.Tensor, labels: LabelTensors, sigma: float) -> torch.Tensor:
    """Per-example losses under the softmax over the nine bin logits."""
    log_probabilities = torch.log_softmax(bin_logits.float(), dim=-1)
    exact = -(exact_targets(labels.steps, sigma) * log_probabilities).sum(dim=-1)
    at_least = -torch.logsumexp(log_probabilities.masked_fill(~at_least_mask(labels.steps), -math.inf), dim=-1)
    dead = -log_probabilities[:, DEAD_BIN]
    is_exact = labels.kinds == KIND_INDEX[LabelKind.EXACT]
    is_at_least = labels.kinds == KIND_INDEX[LabelKind.AT_LEAST]
    return torch.where(is_exact, exact, torch.where(is_at_least, at_least, dead))


def bin_mass_losses(full_logits: torch.Tensor, bin_token_ids: torch.Tensor) -> torch.Tensor:
    """-log of the full-vocabulary probability that the next token is any bin token."""
    full_logits = full_logits.float()
    return torch.logsumexp(full_logits, dim=-1) - torch.logsumexp(full_logits[:, bin_token_ids], dim=-1)
