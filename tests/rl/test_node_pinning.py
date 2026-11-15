import pytest

from lean_search.rl.node_pinning import (
    PinningRecord,
    background_set,
    pinned_as_background,
    pinning_refusals,
)

ALL_CPUS = range(128)


def test_background_sh_pins_the_last_cpus_of_the_host() -> None:
    assert background_set(4, 16) == (12, 13, 14, 15)


def test_a_pinned_set_below_the_quota_within_the_allowed_cpus_passes() -> None:
    assert pinning_refusals(52, 128, ALL_CPUS, 61.0) == []


def test_a_pinned_set_at_the_quota_is_refused() -> None:
    assert pinning_refusals(61, 128, ALL_CPUS, 61.0)


def test_a_pinned_set_outside_the_allowed_cpus_is_refused() -> None:
    assert pinning_refusals(52, 128, range(64), 61.0)


def record(affinity: tuple[int, ...], background_cpus: int | None) -> PinningRecord:
    return PinningRecord("2026-11-14T00:00:00+00:00", affinity, 128, 61.0, background_cpus)


@pytest.mark.parametrize(
    ("affinity", "background_cpus", "pinned"),
    [(tuple(range(76, 128)), 52, True), (tuple(range(128)), 52, False), (tuple(range(76, 128)), None, False)],
    ids=["pinned", "unpinned", "no BACKGROUND_CPUS"],
)
def test_a_process_counts_as_pinned_only_on_background_shs_set(
    affinity: tuple[int, ...], background_cpus: int | None, pinned: bool
) -> None:
    assert pinned_as_background(record(affinity, background_cpus)) == pinned
