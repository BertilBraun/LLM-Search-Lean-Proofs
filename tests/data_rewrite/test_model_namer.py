import pytest

from lean_search.data_rewrite.model_namer import naming_messages, parse_names
from lean_search.data_rewrite.naming import Hypothesis, NamingConfig, NamingRequest

REQUEST = NamingRequest(
    "theorem t (x y : ℝ) (h₀ : 0 < x) (h₁ : x + y = 3) : x < 3 := by",
    (Hypothesis("h₀", "0 < x"), Hypothesis("h₁", "x + y = 3")),
    ("x", "y"),
    frozenset({"x", "y", "h₀", "h₁", "hx"}),
)


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ('{"h₀": "hx_pos", "h₁": "h_sum"}', ("hx_pos", "h_sum")),
        ('```json\n{"h₀": " hx_pos ", "h₁": "h_sum"}\n```', ("hx_pos", "h_sum")),
        ('{"h₀": "hx_pos"}', ("hx_pos", "")),
        ('{"h₀": 3, "h₁": ["h_sum"]}', ("", "")),
        ('["hx_pos", "h_sum"]', ("", "")),
        ("I would call them hx_pos and h_sum.", ("", "")),
        ('{"h₀": "hx_pos",', ("", "")),
    ],
)
def test_parse_names_takes_only_string_names_per_hypothesis(reply: str, expected: tuple[str, ...]) -> None:
    assert parse_names(reply, REQUEST) == expected


def test_naming_prompt_lists_every_hypothesis_with_its_type() -> None:
    user = naming_messages(REQUEST, NamingConfig())[-1].content
    assert "- h₀ : 0 < x\n- h₁ : x + y = 3" in user


def test_naming_prompt_lists_taken_hypothesis_style_names() -> None:
    user = naming_messages(REQUEST, NamingConfig())[-1].content
    assert "names in use: hx, h₀, h₁." in user
