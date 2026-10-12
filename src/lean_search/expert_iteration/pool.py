"""Statement pools for expert iteration: a stratified, deterministic candidate order and the pre-filter outcomes."""

import hashlib
import re
from collections.abc import Callable, Collection, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from lean_search.corpora.records import StatementRecord
from lean_search.data import Problem, Split
from lean_search.lean.text import split_header
from lean_search.search import SearchResult, StopReason

# Mathlib imports Aesop, so both lists give the same environment, and one import list per process saves a second
# Mathlib import (~4 GiB of private memory).
CANONICAL_IMPORTS = "import Mathlib\nimport Aesop"
INTERCHANGEABLE_IMPORTS = frozenset({"import Mathlib", "import Aesop"})
QUOTED_NAME = re.compile(r"'[^'\n]*'|`[^`\n]*`")
MAX_CATEGORY_CHARACTERS = 80


@dataclass(frozen=True)
class SourceQuota:
    name: str
    candidates: int


@dataclass
class SourceSelection:
    """The `capacity` statements with the smallest ordering keys seen so far, and what was seen."""

    name: str
    capacity: int
    available: int = 0
    # Exclusion is only checked for statements whose key could still be selected.
    checked: int = 0
    excluded: int = 0
    keyed: list[tuple[bytes, StatementRecord]] = field(default_factory=list)
    threshold: bytes | None = None

    def admits(self, key: bytes) -> bool:
        return self.capacity > 0 and (self.threshold is None or key < self.threshold)

    def add(self, key: bytes, statement: StatementRecord) -> None:
        self.keyed.append((key, statement))
        if len(self.keyed) >= 2 * self.capacity:
            self._truncate()

    def ordered(self) -> list[StatementRecord]:
        self._truncate()
        return [statement for _, statement in self.keyed]

    def _truncate(self) -> None:
        self.keyed.sort(key=lambda pair: pair[0])
        del self.keyed[self.capacity :]
        if self.capacity and len(self.keyed) == self.capacity:
            self.threshold = self.keyed[-1][0]


class PrefilterOutcome(StrEnum):
    LOAD_FAILED = "load_failed"
    AUTOMATION_SOLVED = "automation_solved"
    UNSOLVED = "unsolved"


def problem_name(statement: StatementRecord) -> str:
    return f"{statement.source}.{statement.identifier}".replace("/", "_")


def problem_source(problem_name: str) -> str:
    """The pool source a problem name starts with; names without one (miniF2F's) count as `other`."""
    source, separator, _ = problem_name.partition(".")
    return source if separator else "other"


def pool_problem(statement: StatementRecord) -> Problem:
    # The search reads only the name, header and statement; the split field is miniF2F's and does not apply.
    return Problem(problem_name(statement), Split.VALID, statement.header, statement.formal_statement, "", "")


def canonical_header(header: str) -> str:
    imports, commands = split_header(header)
    if not frozenset(imports.split("\n")) <= INTERCHANGEABLE_IMPORTS:
        return header
    return f"{CANONICAL_IMPORTS}\n{commands}"


def ordering_key(seed: str, statement: StatementRecord) -> bytes:
    return hashlib.sha256(f"{seed}\n{statement.source}\n{statement.identifier}".encode()).digest()


def select_by_source(
    statements: Iterable[StatementRecord],
    quotas: Sequence[SourceQuota],
    seed: str,
    is_excluded: Callable[[StatementRecord], bool],
) -> list[SourceSelection]:
    """Per source, the `candidates` non-excluded statements that come first in the seeded hash order."""
    selections = {quota.name: SourceSelection(quota.name, quota.candidates) for quota in quotas}
    for statement in statements:
        selection = selections.get(statement.source)
        if selection is None:
            continue
        selection.available += 1
        key = ordering_key(seed, statement)
        if not selection.admits(key):
            continue
        selection.checked += 1
        if is_excluded(statement):
            selection.excluded += 1
            continue
        selection.add(key, statement)
    return [selections[quota.name] for quota in quotas]


def interleave[T](lists: Sequence[Sequence[T]]) -> list[T]:
    """Merges the lists so that every prefix holds them in proportion to their lengths, earlier lists first on ties."""
    positioned = [
        ((index + 0.5) / len(items), list_index, index)
        for list_index, items in enumerate(lists)
        for index in range(len(items))
    ]
    return [lists[list_index][index] for _, list_index, index in sorted(positioned)]


def first_per_name(statements: Iterable[StatementRecord]) -> tuple[list[StatementRecord], int]:
    """The first statement of each problem name, and how many later ones were dropped."""
    seen: set[str] = set()
    kept = []
    dropped = 0
    for statement in statements:
        name = problem_name(statement)
        if name in seen:
            dropped += 1
            continue
        seen.add(name)
        kept.append(statement)
    return kept, dropped


def prefilter_outcome(result: SearchResult) -> PrefilterOutcome:
    if result.stop_reason == StopReason.START_FAILED:
        return PrefilterOutcome.LOAD_FAILED
    return PrefilterOutcome.AUTOMATION_SOLVED if result.proved else PrefilterOutcome.UNSOLVED


def completed_prefix(names: Sequence[str], completed: Collection[str]) -> int:
    """The number of leading names that all have a result, so outputs built on it never reorder later."""
    for index, name in enumerate(names):
        if name not in completed:
            return index
    return len(names)


def load_failure_category(message: str) -> str:
    first_line = message.strip().split("\n", 1)[0]
    return QUOTED_NAME.sub("'…'", first_line)[:MAX_CATEGORY_CHARACTERS]
