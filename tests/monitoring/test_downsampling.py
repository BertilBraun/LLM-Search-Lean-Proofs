import pytest

from lean_search.monitoring.store import FamilySeries, downsampled


def series_of(values: list[float | None], versions: list[int] | None = None) -> FamilySeries:
    series = FamilySeries()
    for index, value in enumerate(values):
        version = versions[index] if versions else None
        series.append({"time": float(index), "policy_version": version, "fields": {"value": value}})
    return series


def test_short_series_is_returned_unchanged() -> None:
    assert downsampled(series_of([1.0, 2.0, 3.0]), points=10).columns["value"] == [1.0, 2.0, 3.0]


@pytest.mark.parametrize(("records", "points"), [(10, 3), (1000, 400), (401, 400), (7, 1)])
def test_long_series_has_at_most_the_requested_points(records: int, points: int) -> None:
    assert len(downsampled(series_of([1.0] * records), points).times) == points


def test_buckets_average_their_values() -> None:
    assert downsampled(series_of([1.0, 3.0, 5.0, 7.0]), points=2).columns["value"] == [2.0, 6.0]


def test_buckets_average_their_times() -> None:
    assert downsampled(series_of([1.0, 3.0, 5.0, 7.0]), points=2).times == [0.5, 2.5]


def test_missing_values_are_left_out_of_the_mean() -> None:
    assert downsampled(series_of([1.0, None, None, None]), points=2).columns["value"] == [1.0, None]


def test_buckets_keep_the_last_version() -> None:
    window = downsampled(series_of([1.0, 1.0, 1.0, 1.0], versions=[1, 2, 3, 4]), points=2)
    assert window.policy_versions == [2, 4]


def test_since_drops_earlier_records() -> None:
    assert downsampled(series_of([1.0, 2.0, 3.0, 4.0]), points=10, since=2.0).columns["value"] == [3.0, 4.0]


def test_window_counts_records_before_downsampling() -> None:
    assert downsampled(series_of([1.0] * 50), points=5).records == 50


def test_fields_select_columns() -> None:
    series = series_of([1.0])
    series.append({"time": 1.0, "fields": {"value": 2.0, "other": 3.0}})
    assert list(downsampled(series, points=5, fields={"other"}).columns) == ["other"]
