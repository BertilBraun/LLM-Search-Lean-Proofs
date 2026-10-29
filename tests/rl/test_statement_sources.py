from pathlib import Path

import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.monitoring.families import BandOutcome
from lean_search.rl.fixed_sets import HeldOutStatement, Stratum
from lean_search.rl.statement_sources import (
    CurriculumStatements,
    FixedStatements,
    difficulty_band,
    outcomes_by_band,
)
from lean_search.rl.tree_store import TreeEntry
from lean_search.search.records import to_json


def held_out(number: int) -> HeldOutStatement:
    record = StatementRecord("s", f"t{number}", "", f"theorem t{number} : True := by", "", "")
    return HeldOutStatement(record, 1.0, Stratum.EASY)


def entry(difficulty: float | None, proved: bool) -> TreeEntry:
    return TreeEntry(0, "s.t0", 1, "phase_0001/x.json.gz", proved, int(proved), 3, 0, difficulty, 1.0, 0.0)


@pytest.mark.parametrize(("difficulty", "band"), [(0.5, "0-1"), (1.0, "1-2"), (4.9, "4-5"), (5.0, "5+"), (12.0, "5+")])
def test_difficulty_bands(difficulty: float, band: str) -> None:
    assert difficulty_band(difficulty) == band


def test_outcomes_count_attempts_and_solved_per_band() -> None:
    entries = [entry(1.5, True), entry(1.2, False), entry(3.0, True)]
    assert outcomes_by_band(entries) == {"1-2": BandOutcome(2, 1), "3-4": BandOutcome(1, 1)}


def test_fixed_statements_cycle_in_order() -> None:
    source = FixedStatements([held_out(0), held_out(1)])
    names = []
    for _ in range(3):
        fed = source.next_statement()
        assert fed is not None
        names.append(fed.name)
        source.record_outcome(fed.name, solved=False)
    assert names == ["s.t0", "s.t1", "s.t0"]


def test_a_running_fixed_statement_is_not_fed_again() -> None:
    source = FixedStatements([held_out(0)])
    source.next_statement()
    assert source.next_statement() is None


def test_an_abandoned_fixed_statement_comes_again() -> None:
    source = FixedStatements([held_out(0)])
    source.next_statement()
    source.abandon("s.t0")
    assert source.next_statement() is not None


def write_verified(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for number in range(count):
        statement = StatementRecord("s", f"t{number}", "", f"theorem t{number} : True := by", "", "")
        record = VerifiedStatement(statement, ("s",), True, "s", 2, 20, ("⊢ True",), False, False, (), 1.0)
        lines.append(to_json(record) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def curriculum(tmp_path: Path, held: set[str], searched: set[str]) -> CurriculumStatements:
    config = CurriculumConfig(verified="pool/verified.jsonl", unverified="")
    write_verified(tmp_path / "pool/verified.jsonl", 4)
    return CurriculumStatements(config, tmp_path, tmp_path / "curriculum.json", held, searched)


def fed_names(source: CurriculumStatements) -> set[str]:
    names = set()
    while (fed := source.next_statement()) is not None:
        names.add(fed.name)
    return names


def test_the_curriculum_never_feeds_held_out_statements(tmp_path: Path) -> None:
    assert "s.t1" not in fed_names(curriculum(tmp_path, {"s.t1"}, set()))


def test_the_curriculum_does_not_feed_statements_searched_before_a_restart(tmp_path: Path) -> None:
    assert fed_names(curriculum(tmp_path, set(), {"s.t0", "s.t2"})) == {"s.t1", "s.t3"}
