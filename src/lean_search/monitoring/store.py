"""Append-only metric files under `<run>/metrics/<family>.jsonl`, written by the loop and read incrementally.

Each line is one record: {"time": unix seconds, "phase", "policy_version", "value_version", "fields": {...}}. The
reader keeps every family as columns of numbers (nested fields flattened to dotted names, list items to `.0`, `.1`)
and only parses the bytes appended since its last refresh.
"""

import bisect
import dataclasses
import importlib.util
import json
import math
import threading
import time
from collections.abc import Collection, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, Protocol

METRICS_DIRECTORY = "metrics"
TENSORBOARD_DIRECTORY = "tensorboard"


class MetricRecord(Protocol):
    family: ClassVar[str]
    __dataclass_fields__: ClassVar[dict[str, Any]]


@dataclass(frozen=True)
class LoopContext:
    phase: int | None = None
    policy_version: int | None = None
    value_version: int | None = None


NO_CONTEXT = LoopContext()


def metrics_directory(run_directory: Path) -> Path:
    return run_directory / METRICS_DIRECTORY


def family_path(run_directory: Path, family: str) -> Path:
    return metrics_directory(run_directory) / f"{family}.jsonl"


def finite_or_none(value: float) -> float | None:
    return value if math.isfinite(value) else None


def flattened(value: object, prefix: str = "") -> Iterator[tuple[str, float | None]]:
    """Numeric leaves of a parsed record; strings and lists of objects are not series and are skipped."""
    match value:
        case bool():
            yield prefix, float(value)
        case int() | float():
            yield prefix, finite_or_none(float(value))
        case None:
            yield prefix, None
        case dict():
            for key, item in value.items():
                yield from flattened(item, f"{prefix}.{key}" if prefix else str(key))
        case list() | tuple() if all(item is None or isinstance(item, int | float) for item in value):
            for index, item in enumerate(value):
                yield from flattened(item, f"{prefix}.{index}")
        case _:
            pass


class TensorBoardMirror:
    def __init__(self, directory: Path) -> None:
        from torch.utils.tensorboard import SummaryWriter

        self.writer = SummaryWriter(log_dir=str(directory))

    def add(self, family: str, fields: object, record_time: float) -> None:
        for name, value in flattened(fields):
            if value is not None:
                self.writer.add_scalar(f"{family}/{name}", value, global_step=int(record_time), walltime=record_time)
        self.writer.flush()


def tensorboard_mirror(directory: Path) -> TensorBoardMirror | None:
    """Only when TensorBoard is installed; it is not a dependency of the metrics store."""
    if importlib.util.find_spec("tensorboard") is None or importlib.util.find_spec("torch") is None:
        return None
    return TensorBoardMirror(directory)


class MetricsWriter:
    def __init__(self, run_directory: Path, context: LoopContext = NO_CONTEXT, tensorboard: bool = False) -> None:
        self.run_directory = run_directory
        self.context = context
        metrics_directory(run_directory).mkdir(parents=True, exist_ok=True)
        self.mirror = tensorboard_mirror(run_directory / TENSORBOARD_DIRECTORY) if tensorboard else None

    def update_context(self, **changes: int | None) -> None:
        self.context = dataclasses.replace(self.context, **changes)

    def write(self, record: MetricRecord, record_time: float | None = None) -> None:
        assert dataclasses.is_dataclass(record) and not isinstance(record, type)
        moment = time.time() if record_time is None else record_time
        fields = dataclasses.asdict(record)
        line = {"time": moment, **dataclasses.asdict(self.context), "fields": fields}
        # One write per line, so concurrent appenders never interleave inside a line.
        with family_path(self.run_directory, record.family).open("a", encoding="utf-8") as file:
            file.write(json.dumps(line, ensure_ascii=False) + "\n")
        if self.mirror is not None:
            self.mirror.add(record.family, fields, moment)


@dataclass
class FamilySeries:
    times: list[float] = field(default_factory=list)
    phases: list[int | None] = field(default_factory=list)
    policy_versions: list[int | None] = field(default_factory=list)
    value_versions: list[int | None] = field(default_factory=list)
    columns: dict[str, list[float | None]] = field(default_factory=dict)
    # The last parsed line as written, for strings and nested lists that are not series.
    latest: dict[str, Any] | None = None

    def __len__(self) -> int:
        return len(self.times)

    def append(self, line: dict[str, Any]) -> None:
        count = len(self.times)
        values = dict(flattened(line.get("fields", {})))
        for name, column in self.columns.items():
            column.append(values.pop(name, None))
        for name, value in values.items():
            self.columns[name] = [None] * count + [value]
        self.times.append(float(line["time"]))
        self.phases.append(line.get("phase"))
        self.policy_versions.append(line.get("policy_version"))
        self.value_versions.append(line.get("value_version"))
        self.latest = line


class FamilyFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.offset = 0
        self.series = FamilySeries()

    def refresh(self) -> None:
        size = self.path.stat().st_size if self.path.exists() else 0
        if size < self.offset:
            self.offset = 0
            self.series = FamilySeries()
        if size == self.offset:
            return
        with self.path.open("rb") as file:
            file.seek(self.offset)
            appended = file.read(size - self.offset)
        # A line still being written has no newline yet; it is read on the next refresh.
        complete = appended.rfind(b"\n") + 1
        for raw in appended[:complete].splitlines():
            if raw.strip():
                self.series.append(json.loads(raw))
        self.offset += complete


class RunReader:
    def __init__(self, run_directory: Path) -> None:
        self.run_directory = run_directory
        self.files: dict[str, FamilyFile] = {}
        self.lock = threading.Lock()

    def families(self) -> list[str]:
        return sorted(path.stem for path in metrics_directory(self.run_directory).glob("*.jsonl"))

    def series(self, family: str) -> FamilySeries:
        with self.lock:
            if family not in self.files:
                self.files[family] = FamilyFile(family_path(self.run_directory, family))
            current = self.files[family]
            current.refresh()
            return current.series


@dataclass(frozen=True)
class SeriesWindow:
    times: list[float]
    phases: list[int | None]
    policy_versions: list[int | None]
    value_versions: list[int | None]
    columns: dict[str, list[float | None]]
    # Records in the window before downsampling.
    records: int


def mean_or_none(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def downsampled(
    series: FamilySeries, points: int, since: float | None = None, fields: Collection[str] | None = None
) -> SeriesWindow:
    """At most `points` buckets of consecutive records: mean time and values, the last record's versions."""
    assert points > 0
    start = 0 if since is None else bisect.bisect_left(series.times, since)
    end = len(series)
    names = [name for name in series.columns if fields is None or name in fields]
    count = end - start
    if count <= points:
        bounds = [(index, index + 1) for index in range(start, end)]
    else:
        edges = [start + count * bucket // points for bucket in range(points + 1)]
        bounds = list(zip(edges[:-1], edges[1:], strict=True))
    return SeriesWindow(
        times=[sum(series.times[low:high]) / (high - low) for low, high in bounds],
        phases=[series.phases[high - 1] for _, high in bounds],
        policy_versions=[series.policy_versions[high - 1] for _, high in bounds],
        value_versions=[series.value_versions[high - 1] for _, high in bounds],
        columns={name: [mean_or_none(series.columns[name][low:high]) for low, high in bounds] for name in names},
        records=count,
    )
