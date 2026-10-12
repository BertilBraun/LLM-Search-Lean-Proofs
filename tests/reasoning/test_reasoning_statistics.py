import pytest
from reasoning_records import execution, sample_record, state_record

from lean_search.reasoning.dataset import SelectionConfig
from lean_search.reasoning.records import ScoredSample, scored_samples
from lean_search.reasoning.reward import RewardConfig, StepOutcome
from lean_search.reasoning.statistics import BUCKET_LABELS, ScoredState, cap_simulation, length_bucket, run_statistics

EXECUTIONS = [execution("omega", StepOutcome.CLOSED), execution("simp", StepOutcome.ERROR)]


def scored(reasoning_tokens: int, outcome: StepOutcome = StepOutcome.CLOSED) -> ScoredSample:
    return ScoredSample(sample_record(0, "omega", reasoning_tokens), outcome, 0, outcome == StepOutcome.CLOSED)


@pytest.mark.parametrize(
    ("reasoning_tokens", "label"),
    [
        (0, "0"),
        (1, "1–31"),
        (31, "1–31"),
        (32, "32–63"),
        (511, "384–511"),
        (1024, "1024–1535"),
        (2500, "2048–3071"),
        (5000, "3072+"),
    ],
)
def test_length_buckets(reasoning_tokens: int, label: str) -> None:
    assert length_bucket(scored(reasoning_tokens)) == label


def test_truncated_samples_have_their_own_bucket() -> None:
    assert length_bucket(scored(512, StepOutcome.TRUNCATED)) == BUCKET_LABELS[-1]


def statistics_of_two_states():
    first = state_record(
        [sample_record(0, "omega", 20), sample_record(1, "simp", 100), sample_record(2, "omega", 200)], EXECUTIONS
    )
    second = state_record(
        [sample_record(0, "simp", 20), sample_record(1, None, 512, parse_failure=StepOutcome.TRUNCATED)], EXECUTIONS
    )
    return run_statistics([first, second], RewardConfig(), SelectionConfig(max_per_state=2))


def test_success_rate_is_per_sample() -> None:
    assert statistics_of_two_states().overall.success_rate == pytest.approx(2 / 5)


def test_any_success_rate_is_per_state() -> None:
    assert statistics_of_two_states().overall.any_success_rate == pytest.approx(1 / 2)


def test_success_rate_by_reasoning_length() -> None:
    by_length = {group.label: group.success_rate for group in statistics_of_two_states().by_reasoning_length}
    assert by_length == {"1–31": 0.5, "64–127": 0.0, "192–255": 1.0, "truncated": 0.0}


def test_selection_yield_counts_selected_examples() -> None:
    assert statistics_of_two_states().selection.examples == 2


def test_states_that_failed_to_replay_are_excluded() -> None:
    failed = state_record([sample_record(0, "omega", 20)], [], start_failure="replay failed")
    assert run_statistics([failed], RewardConfig(), SelectionConfig()).unusable_states == 1


def test_recovered_samples_are_reported_separately() -> None:
    record = state_record(
        [sample_record(0, "omega", 40, recovered_format=True), sample_record(1, "simp", 40)], EXECUTIONS
    )
    recovered = run_statistics([record], RewardConfig(), SelectionConfig()).recovered_format
    assert (recovered.samples, recovered.success_rate) == (1, 1.0)


def long_and_short_successes() -> list[ScoredState]:
    record = state_record(
        [sample_record(0, "omega", 588), sample_record(1, "omega", 100), sample_record(2, "simp", 100)], EXECUTIONS
    )
    return [ScoredState(record, tuple(scored_samples(record, RewardConfig())))]


def test_a_success_longer_than_the_cap_does_not_count_under_it() -> None:
    assert cap_simulation(long_and_short_successes(), 512).success_rate == pytest.approx(1 / 3)


def test_samples_cost_at_most_the_cap() -> None:
    assert cap_simulation(long_and_short_successes(), 512).tokens_per_sample == pytest.approx((512 + 112 + 112) / 3)


def test_samples_finishing_beyond_the_cap_are_counted_with_their_success() -> None:
    simulation = cap_simulation(long_and_short_successes(), 512)
    assert (simulation.finished_beyond_cap, simulation.finished_beyond_cap_success_rate) == (1, 1.0)


def test_caps_above_the_runs_own_cap_are_not_simulated() -> None:
    record = state_record([sample_record(0, "omega", 40)], EXECUTIONS)
    assert [entry.cap for entry in run_statistics([record], RewardConfig(), SelectionConfig()).caps] == [256, 512]
