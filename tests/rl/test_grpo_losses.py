import math

import pytest

torch = pytest.importorskip("torch")

from lean_search.rl.policy_trainer import chunk_scores, clipped_policy_losses, kl_estimate, median  # noqa: E402


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


def test_scores_use_fp32_logits_under_bf16_autocast() -> None:
    generator = torch.Generator().manual_seed(0)
    hidden = (8 * torch.randn(4, 64, generator=generator)).to(torch.bfloat16)
    weight = torch.randn(1000, 64, generator=generator).to(torch.bfloat16)
    targets = torch.tensor([3, 30, 300, 999])
    with torch.autocast("cpu", dtype=torch.bfloat16):
        scores, _ = chunk_scores(weight, hidden, targets, torch.full((4,), 0.8))
    exact = torch.log_softmax(hidden.double() @ weight.double().T / 0.8, dim=-1)[torch.arange(4), targets]
    assert torch.allclose(scores.double(), exact, atol=1e-4)


def test_a_steps_kl_spike_leaves_the_phases_kl_to_the_reference_alone() -> None:
    assert median([0.02, 0.09, 139501.0, 0.03, 0.05]) == 0.05
