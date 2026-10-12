import pytest

from lean_search.expert_iteration.search_service import rescoring_fits


@pytest.mark.parametrize(
    ("states", "rate", "fits"),
    [(50_000, None, True), (5_000, 100.0, True), (6_001, 100.0, False)],
    ids=["unmeasured", "within", "beyond"],
)
def test_rescoring_runs_only_when_the_measured_rate_fits_the_limit(states: int, rate: float | None, fits: bool) -> None:
    assert rescoring_fits(states, rate, 60.0) == fits
