import pytest

from lean_search.evaluation.math_answers import answers_match, last_boxed, normalize_answer


def test_last_boxed_takes_the_last_box_with_nested_braces() -> None:
    assert last_boxed("first \\boxed{1}, then \\boxed{\\frac{1}{2}}.") == "\\frac{1}{2}"


def test_a_text_without_a_box_has_no_answer() -> None:
    assert last_boxed("the answer is 3") is None


def test_an_unclosed_box_has_no_answer() -> None:
    assert last_boxed("\\boxed{\\frac{1}{2") is None


@pytest.mark.parametrize(
    ("answer", "normalized"),
    [
        ("\\dfrac{3}{4}", "\\frac{3}{4}"),
        ("\\frac34", "\\frac{3}{4}"),
        ("x = 4", "4"),
        ("10\\%", "10"),
        ("30^\\circ", "30"),
        ("\\text{(C)}", "C"),
        ("5 \\text{ cm}", "5"),
    ],
)
def test_normalization(answer: str, normalized: str) -> None:
    assert normalize_answer(answer) == normalized


@pytest.mark.parametrize(
    ("predicted", "reference"),
    [
        ("0.5", "\\frac{1}{2}"),
        ("\\frac{\\sqrt{3}}{2}", "\\frac{\\sqrt3}{2}"),
        ("2\\sqrt{2}", "\\sqrt{8}"),
        ("(x+1)^2", "x^2+2x+1"),
        ("\\left( 3, \\frac{\\pi}{2} \\right)", "(3,\\frac{\\pi}{2})"),
        ("[2, 5)", "[2,5)"),
        ("3, -1", "-1, 3"),
        ("\\{1, 2\\}", "1,2"),
        ("\\sqrt[3]{8}", "2"),
        ("\\text{Monday}", "\\text{Monday}"),
    ],
)
def test_equivalent_answers_match(predicted: str, reference: str) -> None:
    assert answers_match(predicted, reference)


@pytest.mark.parametrize(
    ("predicted", "reference"),
    [
        ("5", "6"),
        ("(2,5)", "[2,5)"),
        ("x^2+1", "(x+1)^2"),
        ("(1,2)", "(1,2,3)"),
        ("\\frac{1}{3}", "0.33"),
        ("\\text{Monday}", "\\text{Tuesday}"),
    ],
)
def test_different_answers_do_not_match(predicted: str, reference: str) -> None:
    assert not answers_match(predicted, reference)
