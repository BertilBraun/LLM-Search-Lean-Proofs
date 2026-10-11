import pytest

from lean_search.data import Split, load_minif2f


def test_minif2f_has_488_problems() -> None:
    assert len(load_minif2f()) == 488


@pytest.mark.parametrize("split", [Split.VALID, Split.TEST])
def test_each_split_has_244_problems(split: Split) -> None:
    assert len(load_minif2f(split)) == 244


def test_problem_names_are_unique() -> None:
    names = [problem.name for problem in load_minif2f()]
    assert len(set(names)) == len(names)


def test_formal_statements_end_at_the_proof_position() -> None:
    assert all(problem.formal_statement.endswith(":= by\n") for problem in load_minif2f())
