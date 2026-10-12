from collections.abc import Sequence

import pytest
from reasoning_records import execution, sample_record, state_record

from lean_search.reasoning.compression import (
    Rewrite,
    RewriteDefect,
    RewriteMode,
    RewriteRequest,
    SufficiencyCheck,
    SufficiencyItem,
)
from lean_search.reasoning.dataset import ReasoningOrigin, SelectionConfig
from lean_search.reasoning.pipeline import LeanTaskResult
from lean_search.reasoning.reward import RewardConfig, StepOutcome
from lean_search.reasoning.shortening import (
    CheckedRewrite,
    ShortenedReasoning,
    ShorteningConfig,
    compression_targets,
    rationalization_targets,
    short_reasoning_examples,
    shorten,
    shortening_statistics,
    shortening_targets,
)

REWARD = RewardConfig()
SELECTION = SelectionConfig(max_per_state=2, min_reasoning_tokens=16)
CONFIG = ShorteningConfig(max_kept_reasoning_tokens=256, candidates_per_state=3)
EXECUTIONS = [
    execution("omega", StepOutcome.CLOSED),
    execution("subst h₀", StepOutcome.REFERENCE, 1),
    execution("simp", StepOutcome.ERROR),
]


def thinking_record(*samples):
    return state_record(list(samples), EXECUTIONS)


def test_only_long_successful_reasoning_is_compressed() -> None:
    record = thinking_record(sample_record(0, "omega", 100), sample_record(1, "subst h₀", 400))
    assert [sample.index for sample in compression_targets(record, REWARD, SELECTION, CONFIG)] == [1]


def test_only_the_first_successes_of_a_state_are_compressed() -> None:
    samples = [sample_record(index, "omega", 300 + index, reasoning=f"Reason {index}.") for index in range(5)]
    assert len(compression_targets(thinking_record(*samples), REWARD, SELECTION, CONFIG)) == 3


def test_failed_samples_are_not_compressed() -> None:
    record = thinking_record(sample_record(0, "simp", 400))
    assert compression_targets(record, REWARD, SELECTION, CONFIG) == []


def test_steps_of_another_run_are_rationalized_when_thinking_found_nothing() -> None:
    record = thinking_record(sample_record(0, "simp", 100))
    other = state_record(
        [sample_record(0, "omega", 0, reasoning=""), sample_record(1, "omega", 0, reasoning="")], EXECUTIONS
    )
    assert [sample.tactic_block for sample in rationalization_targets(record, other, REWARD, SELECTION, CONFIG)] == [
        "omega"
    ]


def test_nothing_is_rationalized_when_thinking_succeeded() -> None:
    record = thinking_record(sample_record(0, "omega", 100))
    other = state_record([sample_record(0, "subst h₀", 0, reasoning="")], EXECUTIONS)
    assert rationalization_targets(record, other, REWARD, SELECTION, CONFIG) == []


class FixedRewriter:
    """Two candidates per request: one with the given text, one defective."""

    def __init__(self, text: str) -> None:
        self.text = text

    async def rewrite(self, request: RewriteRequest, mode: RewriteMode) -> tuple[Rewrite, ...]:
        return (Rewrite(self.text, 20, None), Rewrite("", 0, RewriteDefect.EMPTY))


class KeywordChecker:
    """A rewrite is sufficient when it mentions the keyword (one of four steps succeeds)."""

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword
        self.items: list[SufficiencyItem] = []

    async def check(self, items: Sequence[SufficiencyItem]) -> list[SufficiencyCheck]:
        self.items += items
        return [
            SufficiencyCheck(("omega",), LeanTaskResult("", ()), int(self.keyword in item.reasoning)) for item in items
        ]


def long_success_record():
    return thinking_record(sample_record(0, "omega", 400))


async def test_only_well_formed_rewrites_are_checked() -> None:
    checker = KeywordChecker("linear")
    targets = shortening_targets([long_success_record()], {}, REWARD, SELECTION, CONFIG)
    await shorten(targets, FixedRewriter("A linear goal."), checker)
    assert len(checker.items) == 1


async def test_a_sufficient_rewrite_is_the_shortened_reasoning() -> None:
    targets = shortening_targets([long_success_record()], {}, REWARD, SELECTION, CONFIG)
    (shortened,) = await shorten(targets, FixedRewriter("A linear goal."), KeywordChecker("linear"))
    assert shortened.shortest_sufficient() == Rewrite("A linear goal.", 20, None)


async def test_an_insufficient_rewrite_shortens_nothing() -> None:
    targets = shortening_targets([long_success_record()], {}, REWARD, SELECTION, CONFIG)
    (shortened,) = await shorten(targets, FixedRewriter("A linear goal."), KeywordChecker("square"))
    assert shortened.shortest_sufficient() is None


def shortened_entry(mode: RewriteMode, sample_index: int, text: str, sufficient: bool, block: str = "omega"):
    check = SufficiencyCheck(("omega",), LeanTaskResult("", ()), int(sufficient))
    return ShortenedReasoning(
        "test/sum#0", mode, sample_index, block, "Long.", 400, (CheckedRewrite(Rewrite(text, 20, None), check),)
    )


def test_short_reasoning_is_kept_as_it_is() -> None:
    record = thinking_record(sample_record(0, "omega", 100))
    (example,) = short_reasoning_examples(record, [], REWARD, SELECTION, 256)
    assert example.origin == ReasoningOrigin.SAMPLED


def test_long_reasoning_is_replaced_by_its_sufficient_compression() -> None:
    record = long_success_record()
    entries = [shortened_entry(RewriteMode.COMPRESS, 0, "Linear, so omega.", True)]
    (example,) = short_reasoning_examples(record, entries, REWARD, SELECTION, 256)
    assert (example.reasoning, example.origin) == ("Linear, so omega.", ReasoningOrigin.COMPRESSED)


def test_long_reasoning_without_a_sufficient_compression_is_dropped() -> None:
    entries = [shortened_entry(RewriteMode.COMPRESS, 0, "Linear, so omega.", False)]
    assert short_reasoning_examples(long_success_record(), entries, REWARD, SELECTION, 256) == []


def test_a_state_without_thinking_success_gets_its_rationalized_step() -> None:
    record = thinking_record(sample_record(0, "simp", 100))
    entries = [shortened_entry(RewriteMode.RATIONALIZE, 0, "Omega decides it.", True, block="subst h₀")]
    (example,) = short_reasoning_examples(record, entries, REWARD, SELECTION, 256)
    assert (example.tactic_block, example.origin) == ("subst h₀", ReasoningOrigin.RATIONALIZED)


def test_a_compression_ratio_and_pass_rate_are_reported() -> None:
    entries = [
        shortened_entry(RewriteMode.COMPRESS, 0, "Linear, so omega.", True),
        shortened_entry(RewriteMode.COMPRESS, 1, "Linear, so omega.", False),
    ]
    statistics = shortening_statistics(entries, RewriteMode.COMPRESS, sample_count=4)
    assert (statistics.pass_rate, statistics.median_compression_ratio) == (0.5, pytest.approx(20 / 400))
