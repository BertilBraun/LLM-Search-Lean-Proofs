import math

import pytest

torch = pytest.importorskip("torch")

from lean_search.rl.policy_trainer import (  # noqa: E402
    MAX_PENALTY_LOG_RATIO,
    chunk_scores,
    clipped_policy_losses,
    kl_estimate,
    kl_penalties,
    reference_log_ratios,
    token_mean,
)


def gradient(ratio: float, advantage: float) -> float:
    """d loss / d log-probability at the given ratio to the data-collecting policy."""
    log_probability = torch.tensor([math.log(ratio)], requires_grad=True)
    losses = clipped_policy_losses(log_probability, torch.zeros(1), torch.tensor([advantage]), 0.2, 0.28)
    losses.losses.sum().backward()
    assert log_probability.grad is not None
    return log_probability.grad.item()


def test_positive_advantage_pushes_the_log_probability_up() -> None:
    assert gradient(1.0, 1.0) < 0


def test_negative_advantage_pushes_the_log_probability_down() -> None:
    assert gradient(1.0, -1.0) > 0


@pytest.mark.parametrize(("ratio", "advantage"), [(1.5, 1.0), (0.5, -1.0)])
def test_clipped_tokens_get_no_gradient(ratio: float, advantage: float) -> None:
    assert gradient(ratio, advantage) == 0.0


@pytest.mark.parametrize(
    ("ratio", "advantage", "clipped"),
    [(1.5, 1.0, True), (1.2, 1.0, False), (0.5, -1.0, True), (1.5, -1.0, False), (0.5, 1.0, False)],
)
def test_clip_flags(ratio: float, advantage: float, clipped: bool) -> None:
    losses = clipped_policy_losses(
        torch.tensor([math.log(ratio)]), torch.zeros(1), torch.tensor([advantage]), 0.2, 0.28
    )
    assert losses.clipped.item() is clipped


def test_pessimistic_bound_keeps_the_unclipped_loss_of_a_grown_bad_token() -> None:
    losses = clipped_policy_losses(torch.tensor([math.log(1.5)]), torch.zeros(1), torch.tensor([-1.0]), 0.2, 0.28)
    assert losses.losses.item() == pytest.approx(1.5)


def test_kl_estimate_vanishes_for_identical_policies() -> None:
    assert kl_estimate(torch.zeros(3)).abs().max().item() == 0.0


def test_kl_estimate_is_exact_in_expectation() -> None:
    p = torch.tensor([0.5, 0.3, 0.2])
    q = torch.tensor([0.2, 0.2, 0.6])
    expected = (p * kl_estimate(q.log() - p.log())).sum()
    assert expected.item() == pytest.approx((p * (p.log() - q.log())).sum().item())


def penalty_gradient(log_probability: float, reference_log_probability: float) -> float:
    policy = torch.tensor([log_probability], requires_grad=True)
    kl_penalties(policy, torch.tensor([reference_log_probability])).sum().backward()
    assert policy.grad is not None
    return policy.grad.item()


def test_the_kl_penalty_stays_finite_where_the_reference_prefers_a_token_by_100_nats() -> None:
    assert math.isfinite(penalty_gradient(-100.0, 0.0))


def test_the_kl_penalty_pulls_up_a_token_the_reference_prefers_by_100_nats_with_its_slope_at_the_cap() -> None:
    assert penalty_gradient(-100.0, 0.0) == pytest.approx(-math.expm1(MAX_PENALTY_LOG_RATIO))


def test_the_kl_penalty_is_continuous_at_its_cap() -> None:
    below = kl_penalties(torch.tensor([-MAX_PENALTY_LOG_RATIO + 1e-3]), torch.tensor([0.0])).item()
    above = kl_penalties(torch.tensor([-MAX_PENALTY_LOG_RATIO - 1e-3]), torch.tensor([0.0])).item()
    assert above - below == pytest.approx(2e-3 * math.expm1(MAX_PENALTY_LOG_RATIO), rel=1e-2)


def test_the_kl_penalty_pulls_down_a_token_the_policy_prefers_by_30_nats() -> None:
    assert penalty_gradient(0.0, -30.0) == pytest.approx(1.0)


def test_the_kl_penalty_is_k3_within_its_cap() -> None:
    assert kl_penalties(torch.tensor([-2.0]), torch.tensor([-1.0])).item() == pytest.approx(math.e - 2)


def test_scores_use_fp32_logits_under_bf16_autocast() -> None:
    generator = torch.Generator().manual_seed(0)
    hidden = (8 * torch.randn(4, 64, generator=generator)).to(torch.bfloat16)
    weight = torch.randn(1000, 64, generator=generator).to(torch.bfloat16)
    targets = torch.tensor([3, 30, 300, 999])
    with torch.autocast("cpu", dtype=torch.bfloat16):
        scores, _ = chunk_scores(weight, hidden, targets, torch.full((4,), 0.8))
    exact = torch.log_softmax(hidden.double() @ weight.double().T / 0.8, dim=-1)[torch.arange(4), targets]
    assert torch.allclose(scores.double(), exact, atol=1e-4)


def phase_kl_to_reference(log_probabilities: torch.Tensor, reference: torch.Tensor, steps: int) -> float | None:
    """As the trainer aggregates it: per-step means over the steps' tokens, then their token mean."""
    parts = reference_log_ratios(log_probabilities, reference).chunk(steps)
    return token_mean([part.mean().item() for part in parts], [len(part) for part in parts])


def test_one_token_the_reference_prefers_by_22_nats_barely_moves_the_phases_kl_to_the_reference() -> None:
    log_probabilities = torch.full((256 * 300,), -1.0)
    reference = log_probabilities - 0.03
    log_probabilities[0], reference[0] = -23.0, -1.0
    assert phase_kl_to_reference(log_probabilities, reference, steps=229) == pytest.approx(0.03, abs=1e-3)


def test_the_phases_kl_to_the_reference_weighs_steps_by_their_reference_tokens() -> None:
    assert token_mean([0.1, 0.4], [300, 100]) == pytest.approx(0.175)


def test_a_phase_without_reference_tokens_has_no_kl_to_the_reference() -> None:
    assert token_mean([0.0, 0.0], [0, 0]) is None
