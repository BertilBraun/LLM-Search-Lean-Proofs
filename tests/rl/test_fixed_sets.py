from collections import Counter
from pathlib import Path

import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.rl.fixed_sets import (
    FixedSetsConfig,
    Stratum,
    read_fixed_set,
    select_fixed_sets,
    select_overfit_set,
    stratum,
    write_fixed_set,
)

CONFIG = FixedSetsConfig(probe_per_stratum=3, gate_per_stratum=2, overfit_per_stratum=2)


def verified(number: int, tactics: int, automation_solved: bool = False) -> VerifiedStatement:
    statement = StatementRecord("s", f"t{number}", "", f"theorem t{number} : True := by", "", "")
    return VerifiedStatement(
        statement, ("s",), True, "s", tactics, 10 * tactics, (f"⊢ {number}",), automation_solved, False, (), 1.0
    )


# Difficulty is the proof's tactic count here (weights 0.5 + 0.5): 1 easy, 2-3 medium, 4+ hard.
POOL = [verified(number, 1 + number % 6) for number in range(60)]


@pytest.mark.parametrize(
    ("difficulty", "expected"), [(1.0, Stratum.EASY), (2.0, Stratum.MEDIUM), (3.5, Stratum.MEDIUM), (4.0, Stratum.HARD)]
)
def test_stratum_bounds(difficulty: float, expected: Stratum) -> None:
    assert stratum(difficulty, CONFIG) == expected


def test_probe_takes_the_same_number_from_each_stratum() -> None:
    probe = select_fixed_sets(POOL, CONFIG).probe
    assert Counter(statement.stratum for statement in probe) == {name: 3 for name in Stratum}


def test_gate_takes_the_same_number_from_each_stratum() -> None:
    gate = select_fixed_sets(POOL, CONFIG).gate
    assert Counter(statement.stratum for statement in gate) == {name: 2 for name in Stratum}


def test_probe_and_gate_are_disjoint() -> None:
    sets = select_fixed_sets(POOL, CONFIG)
    assert not {statement.name for statement in sets.probe} & {statement.name for statement in sets.gate}


def test_statements_the_automation_closes_are_never_held_out() -> None:
    sets = select_fixed_sets([verified(0, 1, automation_solved=True), *POOL[1:]], CONFIG)
    assert "s.t0" not in {statement.name for statement in (*sets.probe, *sets.gate)}


def test_selection_is_deterministic() -> None:
    assert select_fixed_sets(POOL, CONFIG) == select_fixed_sets(list(reversed(POOL)), CONFIG)


def test_overfit_set_avoids_the_held_out_statements() -> None:
    sets = select_fixed_sets(POOL, CONFIG)
    held_out = {statement.name for statement in (*sets.probe, *sets.gate)}
    assert not {statement.name for statement in select_overfit_set(POOL, CONFIG, held_out)} & held_out


def test_fixed_set_files_read_back(tmp_path: Path) -> None:
    probe = select_fixed_sets(POOL, CONFIG).probe
    write_fixed_set(tmp_path / "probe.jsonl", probe)
    assert tuple(read_fixed_set(tmp_path / "probe.jsonl")) == probe
