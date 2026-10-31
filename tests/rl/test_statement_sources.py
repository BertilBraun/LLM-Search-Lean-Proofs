from pathlib import Path

import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.curriculum import CurriculumConfig, CurriculumState
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.monitoring.families import BandOutcome
from lean_search.rl.fixed_sets import HeldOutStatement, Stratum
from lean_search.rl.statement_sources import (
    CurriculumStatements,
    FixedStatements,
    difficulty_band,
    origin_text,
    outcomes_by_band,
    outcomes_by_origin,
)
from lean_search.rl.tree_store import TreeEntry
from lean_search.rl.tree_summary import TreeSummary
from lean_search.search.records import to_json


def held_out(number: int) -> HeldOutStatement:
    record = StatementRecord("s", f"t{number}", "", f"theorem t{number} : True := by", "", "")
    return HeldOutStatement(record, 1.0, Stratum.EASY)


def entry(difficulty: float | None, proved: bool, below_band: bool = False) -> TreeEntry:
    summary = TreeSummary(below_band=below_band)
    return TreeEntry(0, "s.t0", 1, "phase_0001/x.json.gz", proved, int(proved), 3, 0, difficulty, 1.0, 0.0, summary)


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


def write_verified(path: Path, tactics: list[int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for number, count in enumerate(tactics):
        statement = StatementRecord("s", f"t{number}", "", f"theorem t{number} : True := by", "", "")
        record = VerifiedStatement(statement, ("s",), True, "s", count, 20, ("⊢ True",), False, False, (), 1.0)
        lines.append(to_json(record) + "\n")
    path.write_text("".join(lines), encoding="utf-8")


def curriculum(
    tmp_path: Path, held: set[str], searched: list[str], tactics: list[int] | None = None, share: float = 0.0
) -> CurriculumStatements:
    config = CurriculumConfig(verified="pool/verified.jsonl", unverified="", below_band_share=share)
    write_verified(tmp_path / "pool/verified.jsonl", tactics or [2] * 4)
    return CurriculumStatements(config, tmp_path, tmp_path / "curriculum.json", held, searched)


def fed_names(source: CurriculumStatements) -> set[str]:
    names = set()
    while (fed := source.next_statement()) is not None:
        names.add(fed.name)
    return names


def test_the_curriculum_never_feeds_held_out_statements(tmp_path: Path) -> None:
    assert "s.t1" not in fed_names(curriculum(tmp_path, {"s.t1"}, []))


def test_the_curriculum_does_not_feed_statements_searched_before_a_restart(tmp_path: Path) -> None:
    assert fed_names(curriculum(tmp_path, set(), ["s.t0", "s.t2"])) == {"s.t1", "s.t3"}


def test_a_retried_curriculum_statement_is_fed_before_new_ones(tmp_path: Path) -> None:
    source = curriculum(tmp_path, set(), [])
    failed = source.next_statement()
    assert failed is not None
    source.retry(failed)
    assert source.next_statement() == failed


def test_an_abandoned_curriculum_statement_is_not_fed_again(tmp_path: Path) -> None:
    source = curriculum(tmp_path, set(), [])
    abandoned = source.next_statement()
    assert abandoned is not None
    source.abandon(abandoned.name)
    assert abandoned.name not in fed_names(source)


def test_outcomes_count_the_trees_from_the_band_and_from_below_it() -> None:
    entries = [entry(1.0, True, below_band=True), entry(3.0, False), entry(3.0, True)]
    assert outcomes_by_origin(entries) == {"band": BandOutcome(2, 1), "below_band": BandOutcome(1, 1)}


def test_the_origin_text_gives_both_solve_rates() -> None:
    entries = [entry(1.0, True, below_band=True), entry(3.0, False), entry(3.0, True)]
    assert origin_text(entries) == "from the band 2 trees, 1 solved (50%); from below it 1 trees, 1 solved (100%)"


def restarted_below_band_three(tmp_path: Path, searched: list[str]) -> CurriculumStatements:
    """t0 and t1 below the band (difficulty 1), t2-t4 in it (4); the band at 4 from before the restart."""
    state = CurriculumState(4.0, 1, ())
    (tmp_path / "curriculum.json").write_text(to_json(state), encoding="utf-8")
    return curriculum(tmp_path, set(), searched, tactics=[1, 1, 4, 4, 4], share=0.5)


def test_a_statement_fed_from_below_the_band_says_so(tmp_path: Path) -> None:
    source = restarted_below_band_three(tmp_path, [])
    fed = [source.next_statement() for _ in range(2)]
    assert [statement.below_band for statement in fed if statement] == [False, True]


def test_statements_searched_before_a_restart_are_fed_again_below_the_band(tmp_path: Path) -> None:
    source = restarted_below_band_three(tmp_path, ["s.t1", "s.t0", "s.t2"])
    fed = [source.next_statement() for _ in range(2)]
    assert [statement.name for statement in fed if statement and statement.below_band] == ["s.t1"]


def test_a_restart_keeps_statements_searched_in_the_band_out_of_it(tmp_path: Path) -> None:
    source = restarted_below_band_three(tmp_path, ["s.t2"])
    assert "s.t2" not in fed_names(source)
