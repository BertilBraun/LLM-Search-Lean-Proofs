from collections import Counter
from pathlib import Path

import pytest

from lean_search.corpora.records import StatementRecord
from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.rl.fixed_sets import (
    CharacterStrataConfig,
    Exclusions,
    FixedSetsConfig,
    Stratum,
    StratumDraw,
    character_candidates,
    character_strata,
    character_stratum,
    read_fixed_set,
    same_statements,
    select_by_characters,
    select_fixed_sets,
    select_overfit_set,
    stratum,
    stratum_order,
    validate_character_strata,
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


def test_the_three_strata_probe_selection_is_unchanged() -> None:
    probe = select_fixed_sets(POOL, CONFIG).probe
    assert [(statement.name, statement.stratum) for statement in probe] == [
        ("s.t42", "easy"),
        ("s.t24", "easy"),
        ("s.t18", "easy"),
        ("s.t8", "medium"),
        ("s.t19", "medium"),
        ("s.t44", "medium"),
        ("s.t23", "hard"),
        ("s.t27", "hard"),
        ("s.t33", "hard"),
    ]


def test_the_three_strata_gate_selection_is_unchanged() -> None:
    gate = select_fixed_sets(POOL, CONFIG).gate
    assert [(statement.name, statement.stratum) for statement in gate] == [
        ("s.t12", "easy"),
        ("s.t0", "easy"),
        ("s.t31", "medium"),
        ("s.t56", "medium"),
        ("s.t45", "hard"),
        ("s.t3", "hard"),
    ]


def test_the_overfit_selection_is_unchanged() -> None:
    sets = select_fixed_sets(POOL, CONFIG)
    held_out = {statement.name for statement in (*sets.probe, *sets.gate)}
    overfit = [statement.name for statement in select_overfit_set(POOL, CONFIG, held_out)]
    assert overfit == ["s.t30", "s.t54", "s.t37", "s.t50", "s.t59", "s.t53"]


def test_fixed_set_files_read_back(tmp_path: Path) -> None:
    probe = select_fixed_sets(POOL, CONFIG).probe
    write_fixed_set(tmp_path / "probe.jsonl", probe)
    assert tuple(read_fixed_set(tmp_path / "probe.jsonl")) == probe


CHARACTERS = CharacterStrataConfig(
    curriculum=CurriculumConfig(proof_steps_weight=0.0, root_value_weight=0.0, characters_weight=1.0),
    edges=(500, 1000),
    counts=(2, 3, 1),
)
NO_EXCLUSIONS = Exclusions(frozenset(), frozenset(), frozenset())


def with_characters(number: int, characters: int) -> VerifiedStatement:
    statement = StatementRecord("s", f"c{number}", "", f"theorem c{number} (x : ℕ) : x = {number} := by", "", "")
    return VerifiedStatement(statement, ("s",), True, "s", 3, characters, (f"⊢ {number}",), False, False, (), 1.0)


# Ten statements in each band: under 500, 500-999 and 1000 on.
CHARACTER_POOL = [with_characters(number, 50 * number) for number in range(30)]


def drawn(exclusions: Exclusions = NO_EXCLUSIONS) -> list[str]:
    selection = select_by_characters(character_candidates(CHARACTER_POOL, CHARACTERS), CHARACTERS, exclusions)
    return [statement.name for statement in selection.statements]


@pytest.mark.parametrize(
    ("characters", "expected"),
    [(0, "0-499"), (499, "0-499"), (500, "500-999"), (4499, "3000-4499"), (4500, "4500+"), (20000, "4500+")],
)
def test_character_strata_bounds(characters: int, expected: str) -> None:
    assert character_stratum(characters, CharacterStrataConfig().edges) == expected


def test_the_default_character_strata_are_the_seven_bands_of_the_pool_analysis() -> None:
    assert character_strata(CharacterStrataConfig().edges) == [
        "0-499",
        "500-999",
        "1000-1499",
        "1500-1999",
        "2000-2999",
        "3000-4499",
        "4500+",
    ]


def test_the_character_selection_takes_each_bands_count() -> None:
    selection = select_by_characters(character_candidates(CHARACTER_POOL, CHARACTERS), CHARACTERS, NO_EXCLUSIONS)
    assert Counter(statement.stratum for statement in selection.statements) == {"0-499": 2, "500-999": 3, "1000+": 1}


def test_the_character_selection_records_characters_over_100_as_difficulty() -> None:
    candidates = character_candidates([with_characters(1, 1250)], CHARACTERS)
    assert candidates[0].held_out.difficulty == 12.5


def test_the_character_selection_is_deterministic() -> None:
    reversed_pool = character_candidates(list(reversed(CHARACTER_POOL)), CHARACTERS)
    assert drawn() == [
        statement.name for statement in select_by_characters(reversed_pool, CHARACTERS, NO_EXCLUSIONS).statements
    ]


@pytest.mark.parametrize("reason", ["fixed_sets", "held_out_states", "near_training_duplicates"])
def test_excluded_statements_are_never_drawn(reason: str) -> None:
    excluded = frozenset(drawn())
    exclusions = Exclusions(
        excluded if reason == "fixed_sets" else frozenset(),
        excluded if reason == "held_out_states" else frozenset(),
        excluded if reason == "near_training_duplicates" else frozenset(),
    )
    assert not set(drawn(exclusions)) & excluded


def test_the_draw_reports_each_bands_drops_under_their_first_reason() -> None:
    names = ["s.c0", "s.c1", "s.c2"]
    exclusions = Exclusions(frozenset(names[:1]), frozenset(names[:2]), frozenset(names))
    selection = select_by_characters(character_candidates(CHARACTER_POOL, CHARACTERS), CHARACTERS, exclusions)
    assert selection.strata[0] == StratumDraw("0-499", 10, 1, 1, 1, 2)


def test_a_band_with_too_few_statements_is_refused() -> None:
    config = CharacterStrataConfig(curriculum=CHARACTERS.curriculum, edges=(500, 1000), counts=(2, 3, 11))
    with pytest.raises(ValueError, match="1000\\+"):
        select_by_characters(character_candidates(CHARACTER_POOL, config), config, NO_EXCLUSIONS)


@pytest.mark.parametrize(
    ("edges", "counts"), [((500, 1000), (1, 2)), ((1000, 500), (1, 2, 3)), ((0, 500), (1, 2, 3)), ((500,), (1, -1))]
)
def test_inconsistent_character_strata_are_refused(edges: tuple[int, ...], counts: tuple[int, ...]) -> None:
    with pytest.raises(ValueError):
        validate_character_strata(CharacterStrataConfig(edges=edges, counts=counts))


def test_a_held_out_states_statement_matches_up_to_whitespace() -> None:
    candidates = character_candidates(CHARACTER_POOL, CHARACTERS)
    assert same_statements(candidates, ["theorem c3  (x : ℕ) :\n  x = 3 := by"]) == {"s.c3"}


def test_strata_order_numbered_labels_by_their_low_end_after_the_old_names_by_name() -> None:
    labels = ["hard", "500-999", "easy", "4500+", "0-499", "medium"]
    assert sorted(labels, key=stratum_order) == ["0-499", "500-999", "4500+", "easy", "hard", "medium"]
