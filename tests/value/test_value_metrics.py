import pytest

from lean_search.value.bins import BIN_COUNT, DEAD_BIN, Readout
from lean_search.value.labels import LabelKind, ValueExample
from lean_search.value.metrics import average_ranks, roc_auc, spearman_correlation, value_metrics

READOUT = Readout(eight_or_more_steps=10.0, dead_steps=20.0)


def one_hot(bin_index: int) -> tuple[float, ...]:
    return tuple(float(index == bin_index) for index in range(BIN_COUNT))


def example(kind: LabelKind, steps: int) -> ValueExample:
    return ValueExample(("⊢ p",), kind, steps, 1.0, "source", "p", 0)


@pytest.mark.parametrize(
    ("distribution", "steps"),
    [(one_hot(0), 1.0), (one_hot(6), 7.0), (one_hot(7), 10.0), (one_hot(DEAD_BIN), 20.0)],
)
def test_readout_counts_each_bins_steps(distribution: tuple[float, ...], steps: float) -> None:
    assert READOUT.remaining_steps(distribution) == steps


def test_readout_mixes_bins_by_probability() -> None:
    distribution = (0.5,) + (0.0,) * 7 + (0.5,)
    assert READOUT.remaining_steps(distribution) == pytest.approx(10.5)


def test_alive_readout_ignores_the_dead_probability() -> None:
    distribution = (0.25, 0.25) + (0.0,) * 6 + (0.5,)
    assert READOUT.alive_remaining_steps(distribution) == pytest.approx(1.5)


@pytest.mark.parametrize(("steps", "readout_steps"), [(3, 3.0), (8, 10.0), (15, 10.0)])
def test_label_steps_are_read_out_like_their_bin(steps: int, readout_steps: float) -> None:
    assert READOUT.label_steps(steps) == readout_steps


def test_tied_values_share_their_mean_rank() -> None:
    assert average_ranks([3.0, 1.0, 3.0, 2.0]) == [3.5, 1.0, 3.5, 2.0]


@pytest.mark.parametrize(("second", "expected"), [([10.0, 20.0, 30.0, 40.0], 1.0), ([4.0, 3.0, 2.0, 1.0], -1.0)])
def test_spearman_correlation_of_ranks(second: list[float], expected: float) -> None:
    assert spearman_correlation([1.0, 2.0, 3.0, 4.0], second) == pytest.approx(expected)


def test_spearman_correlation_with_a_constant_side_is_undefined() -> None:
    assert spearman_correlation([1.0, 2.0, 3.0, 4.0], [1.0, 1.0, 1.0, 1.0]) is None


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ([0.9, 0.8, 0.1, 0.2], 1.0),
        ([0.1, 0.2, 0.9, 0.8], 0.0),
        ([0.5, 0.5, 0.5, 0.5], 0.5),
        ([0.9, 0.3, 0.8, 0.2], 0.75),
    ],
)
def test_roc_auc_of_positives_scoring_higher(scores: list[float], expected: float) -> None:
    assert roc_auc(scores, [True, True, False, False]) == expected


def test_roc_auc_needs_both_classes() -> None:
    assert roc_auc([0.1, 0.2], [False, False]) is None


def metrics_examples() -> tuple[list[tuple[float, ...]], list[ValueExample]]:
    distributions = [one_hot(0), one_hot(2), one_hot(7), one_hot(DEAD_BIN), one_hot(1)]
    examples = [
        example(LabelKind.EXACT, 1),
        example(LabelKind.EXACT, 2),
        example(LabelKind.EXACT, 9),
        example(LabelKind.DEAD, 0),
        example(LabelKind.AT_LEAST, 3),
    ]
    return distributions, examples


def test_bin_accuracy_counts_exact_and_dead_labels() -> None:
    assert value_metrics(*metrics_examples(), READOUT).bin_accuracy == pytest.approx(3 / 4)


def test_mean_absolute_error_compares_alive_steps_on_exact_labels() -> None:
    # |1 - 1| + |3 - 2| + |10 - 10| over three exact labels.
    assert value_metrics(*metrics_examples(), READOUT).alive_mean_absolute_error == pytest.approx(1 / 3)


def test_spearman_ranks_h_against_exact_steps() -> None:
    assert value_metrics(*metrics_examples(), READOUT).spearman == pytest.approx(1.0)


def test_dead_auc_separates_dead_from_exact_labels() -> None:
    assert value_metrics(*metrics_examples(), READOUT).dead_auc == 1.0


def test_censored_labels_report_the_probability_of_their_event() -> None:
    assert value_metrics(*metrics_examples(), READOUT).at_least_probability == 0.0


def test_confusion_counts_label_bin_against_most_likely_bin() -> None:
    confusion = value_metrics(*metrics_examples(), READOUT).confusion
    assert (confusion[1][2], confusion[DEAD_BIN][DEAD_BIN], sum(map(sum, confusion))) == (1, 1, 4)


def test_dead_auc_is_absent_without_dead_labels() -> None:
    distributions, examples = metrics_examples()
    assert value_metrics(distributions[:3], examples[:3], READOUT).dead_auc is None
