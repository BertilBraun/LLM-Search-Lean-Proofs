import math

import numpy as np
import pytest
import torch

from lean_search.evaluation.serving_precision import (
    Perturbation,
    SampleSequence,
    agreement,
    chunk_token_scores,
    perturbation_size,
    served_completion_scores,
    sign_perturbation,
    tempered_from_candidates,
    update_visibility,
)
from lean_search.policy.adapters import LORA_A_SUFFIX, LORA_B_SUFFIX

VOCABULARY = 50
TOP_K = 5
TEMPERATURE = 0.8


def raw_log_probabilities(positions: int, seed: int = 0) -> np.ndarray:
    logits = np.random.default_rng(seed).normal(scale=3.0, size=(positions, VOCABULARY))
    return logits - np.log(np.exp(logits).sum(axis=1, keepdims=True))


def exact_tempered(raw: np.ndarray, targets: np.ndarray, temperature: float) -> np.ndarray:
    scaled = raw / temperature
    log_partition = np.log(np.exp(scaled).sum(axis=1))
    return scaled[np.arange(len(targets)), targets] - log_partition


def prompt_logprob_position(raw_row: np.ndarray, target: int, top_k: int) -> dict[str, dict[str, object]]:
    top = np.argsort(-raw_row)[:top_k]
    chosen = dict.fromkeys([target, *top.tolist()])
    return {str(token): {"logprob": float(raw_row[token]), "rank": 1, "decoded_token": ""} for token in chosen}


def scored_sequence() -> tuple[SampleSequence, list[dict[str, dict[str, object]] | None], np.ndarray]:
    prompt = (3, 4, 5)
    completion = (7, 11, 13, 2)
    raw = raw_log_probabilities(len(prompt) + len(completion))
    tokens = (*prompt, *completion)
    positions: list[dict[str, dict[str, object]] | None] = [None] + [
        prompt_logprob_position(raw[index], tokens[index], TOP_K) for index in range(1, len(tokens))
    ]
    sequence = SampleSequence(0, 0, prompt, completion, (0.0,) * len(completion), "stop")
    return sequence, positions, raw[len(prompt) :]


@pytest.mark.parametrize("temperature", [1.0, 0.8, 0.5])
def test_tempered_estimate_with_the_whole_vocabulary_is_exact(temperature: float) -> None:
    raw = raw_log_probabilities(8)
    targets = np.arange(8)
    estimate = tempered_from_candidates(raw[np.arange(8), targets], raw, temperature)
    np.testing.assert_allclose(estimate, exact_tempered(raw, targets, temperature), atol=1e-12)


def test_tempered_estimate_from_the_top_k_overestimates() -> None:
    raw = raw_log_probabilities(8)
    targets = np.argsort(-raw, axis=1)[:, 0]
    candidates = -np.sort(-raw, axis=1)[:, :TOP_K]
    estimate = tempered_from_candidates(raw[np.arange(8), targets], candidates, TEMPERATURE)
    assert np.all(estimate >= exact_tempered(raw, targets, TEMPERATURE))


def test_served_scores_are_the_completion_tokens_raw_log_probabilities() -> None:
    sequence, positions, completion_raw = scored_sequence()
    tokens = (*sequence.prompt_token_ids, *sequence.completion_token_ids)
    scores = served_completion_scores(positions, tokens, sequence, TOP_K, TEMPERATURE)
    expected = completion_raw[np.arange(len(sequence.completion_token_ids)), list(sequence.completion_token_ids)]
    np.testing.assert_array_equal(scores.raw, expected)


def test_served_tempered_scores_use_the_top_k_and_the_target() -> None:
    sequence, positions, completion_raw = scored_sequence()
    tokens = (*sequence.prompt_token_ids, *sequence.completion_token_ids)
    scores = served_completion_scores(positions, tokens, sequence, TOP_K, TEMPERATURE)
    targets = list(sequence.completion_token_ids)
    candidates = np.full((len(targets), TOP_K + 1), -np.inf)
    for row, target in enumerate(targets):
        values = [
            completion_raw[row, token] for token in dict.fromkeys([target, *np.argsort(-completion_raw[row])[:5]])
        ]
        candidates[row, : len(values)] = values
    expected = tempered_from_candidates(completion_raw[np.arange(len(targets)), targets], candidates, TEMPERATURE)
    np.testing.assert_allclose(scores.tempered_top_k, expected, atol=1e-12)


@pytest.mark.parametrize(
    "misalignment",
    ["other tokens returned", "one position short", "shifted by one"],
)
def test_misaligned_prompt_logprobs_are_rejected(misalignment: str) -> None:
    sequence, positions, _ = scored_sequence()
    tokens = (*sequence.prompt_token_ids, *sequence.completion_token_ids)
    match misalignment:
        case "other tokens returned":
            tokens = (*tokens[:-1], tokens[-1] + 1)
        case "one position short":
            positions = positions[:-1]
        case "shifted by one":
            positions = [None, *positions[:-1]]
    with pytest.raises(ValueError):
        served_completion_scores(positions, tokens, sequence, TOP_K, TEMPERATURE)


def chunk_scores_of_random_logits() -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    generator = torch.Generator().manual_seed(0)
    output_weight = torch.randn(VOCABULARY, 16, generator=generator, dtype=torch.float64)
    hidden = torch.randn(6, 16, generator=generator, dtype=torch.float64)
    targets = torch.randint(0, VOCABULARY, (6,), generator=generator)
    return output_weight, hidden, targets


def test_chunk_raw_scores_are_the_log_softmax_of_the_targets() -> None:
    output_weight, hidden, targets = chunk_scores_of_random_logits()
    scores = chunk_token_scores(output_weight, hidden, targets, TEMPERATURE, TOP_K)
    expected = torch.log_softmax((hidden.float() @ output_weight.float().T), dim=-1)[torch.arange(6), targets]
    torch.testing.assert_close(scores.raw, expected)


def test_chunk_tempered_scores_divide_the_logits_by_the_temperature() -> None:
    output_weight, hidden, targets = chunk_scores_of_random_logits()
    scores = chunk_token_scores(output_weight, hidden, targets, TEMPERATURE, TOP_K)
    logits = hidden.float() @ output_weight.float().T
    expected = torch.log_softmax(logits / TEMPERATURE, dim=-1)[torch.arange(6), targets]
    torch.testing.assert_close(scores.tempered, expected)


def test_chunk_candidates_with_the_whole_vocabulary_give_the_exact_tempered_score() -> None:
    output_weight, hidden, targets = chunk_scores_of_random_logits()
    scores = chunk_token_scores(output_weight, hidden, targets, TEMPERATURE, VOCABULARY)
    estimate = tempered_from_candidates(scores.raw.double().numpy(), scores.candidates.double().numpy(), TEMPERATURE)
    np.testing.assert_allclose(estimate, scores.tempered.double().numpy(), atol=1e-5)


def test_identical_scores_agree_exactly() -> None:
    reference = raw_log_probabilities(1, seed=1)[0][:10]
    result = agreement(reference.copy(), reference, [4, 6])
    assert (result.mean_absolute_difference, result.k3_kl, result.sequence_mean_absolute_difference) == (0, 0, 0)


def test_a_constant_offset_shows_as_the_mean_difference() -> None:
    reference = raw_log_probabilities(1, seed=1)[0][:10]
    result = agreement(reference + 0.05, reference, [4, 6])
    assert result.mean_difference == pytest.approx(0.05)


def test_k3_of_a_constant_offset_is_its_closed_form() -> None:
    reference = raw_log_probabilities(1, seed=1)[0][:10]
    result = agreement(reference + 0.05, reference, [4, 6])
    assert result.k3_kl == pytest.approx(math.exp(0.05) - 0.05 - 1)


def test_sequence_differences_sum_the_token_differences() -> None:
    reference = raw_log_probabilities(1, seed=1)[0][:10]
    result = agreement(reference + 0.05, reference, [4, 6])
    assert result.sequence_mean_absolute_difference == pytest.approx(0.05 * 5)


def test_non_finite_served_tokens_are_left_out() -> None:
    reference = raw_log_probabilities(1, seed=1)[0][:10]
    served = reference.copy()
    served[[1, 7]] = [np.nan, -9999.0]
    result = agreement(served, reference, [4, 6])
    assert (result.tokens, result.non_finite_tokens, result.sequences) == (8, 2, 0)


@pytest.mark.parametrize("factor", [1.0, 0.5, 0.0])
def test_update_slope_is_the_share_of_the_reference_change_served(factor: float) -> None:
    rng = np.random.default_rng(2)
    reference_base = rng.normal(size=40)
    reference_change = rng.normal(scale=0.01, size=40)
    served_base = reference_base + 0.03
    visibility = update_visibility(
        served_base, served_base + factor * reference_change, reference_base, reference_base + reference_change, [40]
    )
    assert visibility.slope == pytest.approx(factor)


def lora_weights() -> dict[str, torch.Tensor]:
    generator = torch.Generator().manual_seed(0)
    module = "base_model.model.layers.0.mlp.up_proj"
    return {
        module + LORA_A_SUFFIX: torch.randn(4, 12, generator=generator) * 0.02,
        module + LORA_B_SUFFIX: torch.randn(10, 4, generator=generator) * 0.01,
    }


@pytest.mark.parametrize(("learning_rate", "steps"), [(1e-5, 1), (3e-5, 1), (3e-5, 10)])
def test_sign_perturbation_moves_every_parameter_by_the_element_step(learning_rate: float, steps: int) -> None:
    weights = lora_weights()
    perturbation = Perturbation("p", learning_rate, steps, seed=1)
    perturbed = sign_perturbation(weights, perturbation)
    moves = torch.cat([(perturbed[key].double() - weights[key].double()).abs().flatten() for key in weights])
    torch.testing.assert_close(moves, torch.full_like(moves, learning_rate * steps), rtol=1e-3, atol=0)


def test_sign_perturbation_is_reproducible_from_its_seed() -> None:
    weights = lora_weights()
    first = sign_perturbation(weights, Perturbation("p", 1e-5, seed=4))
    second = sign_perturbation(weights, Perturbation("p", 1e-5, seed=4))
    assert all(torch.equal(first[key], second[key]) for key in weights)


def test_relative_norm_is_the_element_step_over_the_adapter_rms() -> None:
    weights = lora_weights()
    perturbed = sign_perturbation(weights, Perturbation("p", 1e-4, seed=1))
    size = perturbation_size(weights, perturbed, scale=2.0, element_step=1e-4)
    elements = sum(tensor.numel() for tensor in weights.values())
    adapter_norm = math.sqrt(sum(float(tensor.double().square().sum()) for tensor in weights.values()))
    assert size.relative_norm == pytest.approx(1e-4 * math.sqrt(elements) / adapter_norm, rel=1e-3)


def test_merged_update_rms_is_that_of_the_scaled_product_change() -> None:
    weights = lora_weights()
    perturbed = sign_perturbation(weights, Perturbation("p", 1e-4, seed=1))
    size = perturbation_size(weights, perturbed, scale=2.0, element_step=1e-4)
    a_key, b_key = sorted(weights)
    change = 2.0 * (
        perturbed[b_key].double() @ perturbed[a_key].double() - weights[b_key].double() @ weights[a_key].double()
    )
    assert size.merged_update_rms == pytest.approx(float(change.square().mean().sqrt()))
