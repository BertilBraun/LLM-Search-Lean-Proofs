"""The order a probe run starts its searches in, and the file of expected search seconds per statement it can order
by (experiments/probe_runs.py expected-search-seconds). Only the start order changes: the same statements, the same
search each, results keyed by statement."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.expert_iteration.curriculum import file_sha256
from lean_search.rl.evaluation import EvaluationProblem

PROBE_SET_LINE = "# probe_set_sha256\t"
RUN_LINE = "# run\t"
MAX_UNCOVERED_SHARE = 0.01


class SubmissionOrder(StrEnum):
    FILE = "file"
    # The longest expected searches first; statements the file lacks before them (unknown may be long).
    LONGEST_EXPECTED_SEARCH_FIRST = "longest_expected_search_first"


@dataclass(frozen=True)
class StartOrder:
    order: SubmissionOrder = SubmissionOrder.FILE
    # The expected-seconds file's content digest; empty in file order.
    expected_search_seconds_sha256: str = ""

    @property
    def text(self) -> str:
        match self.order:
            case SubmissionOrder.FILE:
                return self.order.value
            case SubmissionOrder.LONGEST_EXPECTED_SEARCH_FIRST:
                return f"{self.order.value} (expected seconds {self.expected_search_seconds_sha256[:12]})"


IN_FILE_ORDER = StartOrder()


@dataclass(frozen=True)
class RecordedRun:
    name: str
    identity: str
    probe_set_sha256: str
    wall_seconds: Mapping[str, float]


def expected_search_seconds_text(runs: Sequence[RecordedRun]) -> str:
    """One line per statement (sorted by name): the mean recorded wall seconds over the runs that searched it, and how
    many did; a header naming the runs (sorted by name), their identities and the probe set's digest."""
    runs = sorted(runs, key=lambda run: run.name)
    digests = sorted({run.probe_set_sha256 for run in runs})
    if len(digests) != 1:
        raise ValueError(f"The runs searched different probe sets: {digests}")
    names = sorted({name for run in runs for name in run.wall_seconds})
    lines = [
        "# Expected search seconds per probe statement: the mean recorded accounting.wall_seconds over the runs that "
        "searched it (columns: statement, seconds, runs).\n",
        f"{PROBE_SET_LINE}{digests[0]}\n",
        *(f"{RUN_LINE}{run.name}\t{run.identity}\t{len(run.wall_seconds)} statements\n" for run in runs),
    ]
    for name in names:
        recorded = [run.wall_seconds[name] for run in runs if name in run.wall_seconds]
        lines.append(f"{name}\t{sum(recorded) / len(recorded):.1f}\t{len(recorded)}\n")
    return "".join(lines)


def read_expected_search_seconds(path: Path, probe_set_sha256: str) -> dict[str, float]:
    """The file's seconds per statement; ValueError when it was made on another probe set than `probe_set_sha256`."""
    made_on = ""
    seconds = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(PROBE_SET_LINE):
            made_on = line.removeprefix(PROBE_SET_LINE)
        elif line and not line.startswith("#"):
            name, expected, _ = line.split("\t")
            seconds[name] = float(expected)
    if made_on != probe_set_sha256:
        raise ValueError(f"{path} was made on probe set {made_on or '(none named)'}, the run's is {probe_set_sha256}")
    return seconds


def configured_start_order(order: SubmissionOrder, expected_search_seconds: str, repository: Path) -> StartOrder:
    """`expected_search_seconds`: the file's path, relative to the repository or absolute."""
    match order:
        case SubmissionOrder.FILE:
            if expected_search_seconds:
                raise ValueError("expected_search_seconds is given, but submission_order is file")
            return StartOrder()
        case SubmissionOrder.LONGEST_EXPECTED_SEARCH_FIRST:
            if not expected_search_seconds:
                raise ValueError(f"submission_order {order.value} needs expected_search_seconds")
            return StartOrder(order, file_sha256(repository / expected_search_seconds))


def orders_note(orders: Sequence[tuple[StartOrder, ...]]) -> str:
    """For a comparison of runs whose sessions started in `orders`: a warning when they differ, else empty."""
    if len(set(orders)) == 1:
        return ""
    return "orders differ: load pattern differs; paired comparison assumes outcomes do not depend on start order"


def uncovered_statements(problems: Sequence[EvaluationProblem], seconds: Mapping[str, float]) -> list[str]:
    """The statements without expected seconds, in file order; ValueError above `MAX_UNCOVERED_SHARE` of them (a file
    of another probe set's statements, or a broken one)."""
    uncovered = [problem.problem.name for problem in problems if problem.problem.name not in seconds]
    if len(uncovered) > MAX_UNCOVERED_SHARE * len(problems):
        raise ValueError(
            f"The expected-seconds file lacks {len(uncovered)} of the run's {len(problems)} statements (more than "
            f"{MAX_UNCOVERED_SHARE:.0%}), e.g. {uncovered[:5]}"
        )
    return uncovered


def longest_expected_search_first(
    problems: Sequence[EvaluationProblem], seconds: Mapping[str, float]
) -> list[EvaluationProblem]:
    """Statements without an expected time first, then the longest expected first; ties keep file order."""
    return sorted(
        problems, key=lambda problem: (problem.problem.name in seconds, -seconds.get(problem.problem.name, 0.0))
    )
