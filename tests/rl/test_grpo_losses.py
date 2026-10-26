import math

import pytest

torch = pytest.importorskip("torch")

from lean_search.rl.policy_trainer import clipped_policy_losses, kl_estimate  # noqa: E402


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
