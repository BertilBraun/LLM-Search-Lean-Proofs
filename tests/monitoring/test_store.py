import importlib.util
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar

import pytest

from lean_search.monitoring.families import BandOutcome, CurriculumPhase, FixedTargets
from lean_search.monitoring.store import (
    NO_CONTEXT,
    FamilySeries,
    LoopContext,
    MetricsWriter,
    RunReader,
    family_path,
    flattened,
)


@dataclass(frozen=True)
class Example:
    family: ClassVar[str] = "example"
    value: float
    per_gpu: tuple[float, ...] = ()
    by_name: dict[str, int] = field(default_factory=dict)
    note: str = ""


def written(tmp_path: Path, *records: object, context: LoopContext = NO_CONTEXT) -> FamilySeries:
    writer = MetricsWriter(tmp_path, context)
    for index, record in enumerate(records):
        writer.write(record, record_time=1000.0 + index)
    family = type(records[0]).family
    return RunReader(tmp_path).series(family)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("minif2f_valid_solved", 171.0),
        ("minif2f_valid_problems", 244.0),
        ("held_out_success", 0.446),
        ("math500_thinking", None),
    ],
)
def test_written_fields_read_back_as_columns(tmp_path: Path, name: str, value: float | None) -> None:
    series = written(
        tmp_path, FixedTargets(minif2f_valid_solved=171, minif2f_valid_problems=244, held_out_success=0.446)
    )
    assert series.columns[name] == [value]


def test_loop_context_is_recorded_with_each_line(tmp_path: Path) -> None:
    series = written(tmp_path, Example(1.0), context=LoopContext(phase=3, policy_version=3, value_version=1))
    assert (series.phases, series.policy_versions, series.value_versions) == ([3], [3], [1])


def test_record_time_is_kept(tmp_path: Path) -> None:
    assert written(tmp_path, Example(1.0), Example(2.0)).times == [1000.0, 1001.0]


def test_nested_dicts_flatten_to_dotted_names(tmp_path: Path) -> None:
    record = CurriculumPhase(1.0, 2.0, 100, 50, by_difficulty={"1-2": BandOutcome(attempts=10, solved=4)})
    assert written(tmp_path, record).columns["by_difficulty.1-2.solved"] == [4.0]


def test_list_items_flatten_to_indexed_names(tmp_path: Path) -> None:
    assert written(tmp_path, Example(1.0, per_gpu=(90.0, 80.0))).columns["per_gpu.1"] == [80.0]


def test_strings_are_not_series(tmp_path: Path) -> None:
    assert "note" not in written(tmp_path, Example(1.0, note="text")).columns


def test_latest_line_keeps_strings(tmp_path: Path) -> None:
    assert (
        written(tmp_path, Example(1.0, note="first"), Example(2.0, note="second")).latest["fields"]["note"] == "second"
    )


def test_field_added_later_is_backfilled_with_none(tmp_path: Path) -> None:
    series = written(tmp_path, Example(1.0), Example(2.0, by_name={"new": 5}))
    assert series.columns["by_name.new"] == [None, 5.0]


def test_field_missing_later_reads_as_none(tmp_path: Path) -> None:
    series = written(tmp_path, Example(1.0, by_name={"old": 5}), Example(2.0))
    assert series.columns["by_name.old"] == [5.0, None]


@pytest.mark.parametrize("value", [float("nan"), float("inf")])
def test_non_finite_values_read_as_none(tmp_path: Path, value: float) -> None:
    assert written(tmp_path, Example(value)).columns["value"] == [None]


def test_booleans_are_numbers() -> None:
    assert dict(flattened({"passed": True})) == {"passed": 1.0}


def test_reader_parses_only_appended_lines(tmp_path: Path) -> None:
    writer = MetricsWriter(tmp_path)
    reader = RunReader(tmp_path)
    writer.write(Example(1.0), record_time=1.0)
    reader.series("example")
    writer.write(Example(2.0), record_time=2.0)
    assert reader.series("example").columns["value"] == [1.0, 2.0]


def test_line_without_newline_waits_for_the_next_refresh(tmp_path: Path) -> None:
    MetricsWriter(tmp_path).write(Example(1.0), record_time=1.0)
    line = json.dumps({"time": 2.0, "fields": {"value": 2.0}})
    path = family_path(tmp_path, "example")
    with path.open("a") as file:
        file.write(line[:10])
    reader = RunReader(tmp_path)
    first = len(reader.series("example"))
    with path.open("a") as file:
        file.write(line[10:] + "\n")
    assert (first, len(reader.series("example"))) == (1, 2)


def test_truncated_file_is_read_again_from_the_start(tmp_path: Path) -> None:
    writer = MetricsWriter(tmp_path)
    writer.write(Example(1.0), record_time=1.0)
    writer.write(Example(2.0), record_time=2.0)
    reader = RunReader(tmp_path)
    reader.series("example")
    family_path(tmp_path, "example").unlink()
    writer.write(Example(3.0), record_time=3.0)
    assert reader.series("example").columns["value"] == [3.0]


def test_families_are_the_files_present(tmp_path: Path) -> None:
    writer = MetricsWriter(tmp_path)
    writer.write(Example(1.0))
    writer.write(FixedTargets(math500_visible=0.87))
    assert RunReader(tmp_path).families() == ["example", "fixed_targets"]


@pytest.mark.skipif(importlib.util.find_spec("tensorboard") is not None, reason="TensorBoard is installed")
def test_tensorboard_mirror_is_skipped_without_tensorboard(tmp_path: Path) -> None:
    assert MetricsWriter(tmp_path, tensorboard=True).mirror is None
