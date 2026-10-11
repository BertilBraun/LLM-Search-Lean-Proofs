import math

import pytest

torch = pytest.importorskip("torch")

from lean_search.value.bins import BIN_COUNT, DEAD_BIN  # noqa: E402
from lean_search.value.labels import LabelKind, ValueExample  # noqa: E402
from lean_search.value.loss import (  # noqa: E402
    LabelTensors,
    bin_mass_losses,
    exact_targets,
    label_tensors,
    value_losses,
)

CPU = torch.device("cpu")
UNIFORM = torch.zeros(1, BIN_COUNT)


def standard_normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def labels(kind: LabelKind, steps: int) -> LabelTensors:
    return label_tensors([ValueExample(("⊢ p",), kind, steps, 1.0, "source", "p", 0)], CPU)


def loss(logits: torch.Tensor, kind: LabelKind, steps: int, sigma: float = 0.5) -> float:
    return value_losses(logits, labels(kind, steps), sigma).item()


@pytest.mark.parametrize(("steps", "hot_bin"), [(1, 0), (4, 3), (7, 6), (8, 7), (12, 7)])
def test_unsmoothed_exact_target_is_one_hot_on_the_step_bin(steps: int, hot_bin: int) -> None:
    expected = torch.nn.functional.one_hot(torch.tensor([hot_bin]), BIN_COUNT).float()
    assert torch.equal(exact_targets(torch.tensor([steps]), 0.0), expected)


@pytest.mark.parametrize("steps", [1, 2, 5, 8, 15])
def test_smoothed_exact_target_is_a_distribution(steps: int) -> None:
    assert exact_targets(torch.tensor([steps]), 0.5).sum().item() == pytest.approx(1.0)


@pytest.mark.parametrize("sigma", [0.0, 0.5, 2.0])
def test_dead_is_never_smoothed_into(sigma: float) -> None:
    assert exact_targets(torch.tensor([8]), sigma)[0, DEAD_BIN].item() == 0.0


@pytest.mark.parametrize(
    ("steps", "bin_index", "mass"),
    [
        # The Gaussian's mass within half a bin of its centre.
        (4, 3, standard_normal_cdf(1) - standard_normal_cdf(-1)),
        (4, 4, standard_normal_cdf(3) - standard_normal_cdf(1)),
        # The first bin is open-ended below, the 8+ bin above.
        (1, 0, standard_normal_cdf(1)),
        (8, 7, 1 - standard_normal_cdf(-1)),
        (8, 6, standard_normal_cdf(-1) - standard_normal_cdf(-3)),
        (12, 7, 1 - standard_normal_cdf(-9)),
    ],
)
def test_smoothed_exact_target_is_the_gaussian_mass_per_bin(steps: int, bin_index: int, mass: float) -> None:
    assert exact_targets(torch.tensor([steps]), 0.5)[0, bin_index].item() == pytest.approx(mass, abs=1e-6)


@pytest.mark.parametrize(
    ("kind", "steps", "expected"),
    [
        (LabelKind.EXACT, 3, math.log(9)),
        (LabelKind.DEAD, 0, math.log(9)),
        (LabelKind.AT_LEAST, 1, 0.0),
        # Bins 3..7, 8+ and dead.
        (LabelKind.AT_LEAST, 3, -math.log(7 / 9)),
        (LabelKind.AT_LEAST, 8, -math.log(2 / 9)),
        (LabelKind.AT_LEAST, 20, -math.log(2 / 9)),
    ],
)
def test_loss_under_uniform_bins(kind: LabelKind, steps: int, expected: float) -> None:
    assert loss(UNIFORM, kind, steps) == pytest.approx(expected, abs=1e-6)


def test_unsmoothed_exact_loss_is_the_cross_entropy_of_the_bin() -> None:
    logits = torch.zeros(1, BIN_COUNT)
    logits[0, 0] = 2.0
    assert loss(logits, LabelKind.EXACT, 1, sigma=0.0) == pytest.approx(math.log(math.exp(2) + 8) - 2, abs=1e-6)


def test_dead_loss_is_minus_log_p_dead() -> None:
    logits = torch.zeros(1, BIN_COUNT)
    logits[0, DEAD_BIN] = math.log(8)
    assert loss(logits, LabelKind.DEAD, 0) == pytest.approx(math.log(2), abs=1e-6)


def test_dead_loss_does_not_depend_on_smoothing() -> None:
    logits = torch.arange(BIN_COUNT, dtype=torch.float32)[None, :]
    assert loss(logits, LabelKind.DEAD, 0, sigma=0.0) == loss(logits, LabelKind.DEAD, 0, sigma=2.0)


def test_censored_label_accepts_a_dead_end() -> None:
    logits = torch.zeros(1, BIN_COUNT)
    logits[0, DEAD_BIN] = 50.0
    assert loss(logits, LabelKind.AT_LEAST, 5) == pytest.approx(0.0, abs=1e-6)


def test_censored_label_penalizes_fewer_steps() -> None:
    logits = torch.zeros(1, BIN_COUNT)
    logits[0, 0] = math.log(91)
    assert loss(logits, LabelKind.AT_LEAST, 2) == pytest.approx(math.log(99 / 8), abs=1e-5)


def test_at_least_one_step_carries_no_gradient() -> None:
    logits = torch.randn(1, BIN_COUNT, requires_grad=True)
    value_losses(logits, labels(LabelKind.AT_LEAST, 1), 0.5).sum().backward()
    assert torch.allclose(logits.grad, torch.zeros_like(logits), atol=1e-7)


def test_losses_are_per_example_in_a_mixed_batch() -> None:
    examples = [
        ValueExample(("⊢ a",), LabelKind.EXACT, 2, 1.0, "source", "a", 0),
        ValueExample(("⊢ b",), LabelKind.AT_LEAST, 3, 0.5, "source", "b", 0),
        ValueExample(("⊢ c",), LabelKind.DEAD, 0, 0.5, "source", "c", 0),
    ]
    losses = value_losses(torch.zeros(3, BIN_COUNT), label_tensors(examples, CPU), 0.5)
    assert losses.tolist() == pytest.approx([math.log(9), -math.log(7 / 9), math.log(9)], abs=1e-6)


@pytest.mark.parametrize(("vocabulary", "expected"), [(BIN_COUNT, 0.0), (2 * BIN_COUNT, math.log(2))])
def test_bin_mass_loss_is_minus_log_the_bins_share(vocabulary: int, expected: float) -> None:
    losses = bin_mass_losses(torch.zeros(1, vocabulary), torch.arange(BIN_COUNT))
    assert losses.item() == pytest.approx(expected, abs=1e-6)
