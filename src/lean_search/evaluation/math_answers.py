"""Final answers of natural-language math solutions: the last \\boxed{...}, normalized, compared by value."""

import random
import re

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

BOX_COMMANDS = ("\\boxed{", "\\fbox{")
TRANSFORMATIONS = (*standard_transformations, implicit_multiplication_application, convert_xor)
RELATIVE_TOLERANCE = 1e-6
SUBSTITUTION_TRIALS = 3
REMOVED_TOKENS = (
    "\\{",
    "\\}",
    "\\left",
    "\\right",
    "\\!",
    "\\,",
    "\\;",
    "\\:",
    "\\displaystyle",
    "$",
    "\\%",
    "%",
    "^\\circ",
    "^{\\circ}",
)
_TEXT = re.compile(r"\\(?:text|textbf|mathrm|mbox|operatorname)\{([^{}]*)\}")
_UNIT_WORDS = re.compile(
    r"\b(units?|degrees?|cm|meters?|inches|inch|feet|foot|dollars?|cents?|square|sq|hours?|minutes?|seconds?|days?)\b"
)
_LEADING_ASSIGNMENT = re.compile(r"^[a-zA-Z]\w*\s*=\s*(?!.*=)")
_SHORT_FRACTION = re.compile(r"\\frac(\d)(\d)")
_FRACTION_ONE_BRACE = re.compile(r"\\frac(\d)\{")
_SQRT_DIGIT = re.compile(r"\\sqrt(\d)")
_CHOICE = re.compile(r"^\(?([A-E])\)?$")


def last_boxed(text: str) -> str | None:
    start = max(text.rfind(command) for command in BOX_COMMANDS)
    if start < 0:
        return None
    position = text.index("{", start) + 1
    depth = 1
    for index in range(position, len(text)):
        match text[index]:
            case "{":
                depth += 1
            case "}":
                depth -= 1
                if depth == 0:
                    return text[position:index]
    return None


def normalize_answer(answer: str) -> str:
    text = answer.strip().replace("\n", "").replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    text = _TEXT.sub(r"\1", text)
    for token in REMOVED_TOKENS:
        text = text.replace(token, "")
    text = _UNIT_WORDS.sub("", text).replace("\\ ", "").replace(" ", "")
    text = _SHORT_FRACTION.sub(r"\\frac{\1}{\2}", text)
    text = _FRACTION_ONE_BRACE.sub(r"\\frac{\1}{", text)
    text = _SQRT_DIGIT.sub(r"\\sqrt{\1}", text)
    text = _LEADING_ASSIGNMENT.sub("", text)
    text = text.rstrip(".").removeprefix("+")
    if (choice := _CHOICE.match(text)) is not None:
        return choice.group(1)
    return text


def latex_to_sympy_text(latex: str) -> str:
    text = latex
    while "\\frac{" in text:
        start = text.index("\\frac{")
        numerator, after_numerator = _braced(text, start + len("\\frac"))
        denominator, after_denominator = _braced(text, after_numerator)
        text = f"{text[:start]}(({numerator})/({denominator})){text[after_denominator:]}"
    while "\\sqrt" in text:
        start = text.index("\\sqrt")
        position = start + len("\\sqrt")
        root = "2"
        if text.startswith("[", position):
            end = text.index("]", position)
            root, position = text[position + 1 : end], end + 1
        radicand, after = _braced(text, position)
        text = f"{text[:start]}(({radicand})**(1/({root}))){text[after:]}"
    replacements = {
        "\\leq": "<=",
        "\\geq": ">=",
        "\\pi": "pi",
        "\\cdot": "*",
        "\\times": "*",
        "\\infty": "oo",
        "\\le": "<=",
        "\\ge": ">=",
        "{": "(",
        "}": ")",
        "\\": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def _braced(text: str, position: int) -> tuple[str, int]:
    """The brace group starting at position (or a single character) and the index after it."""
    if text[position] != "{":
        return text[position], position + 1
    depth = 0
    for index in range(position, len(text)):
        depth += {"{": 1, "}": -1}.get(text[index], 0)
        if depth == 0:
            return text[position + 1 : index], index + 1
    raise ValueError(f"unbalanced braces in {text!r}")


def parse_value(latex: str) -> sympy.Expr | None:
    try:
        return parse_expr(latex_to_sympy_text(latex), transformations=TRANSFORMATIONS, evaluate=True)
    except Exception:
        return None


def values_equal(first: sympy.Expr, second: sympy.Expr) -> bool:
    difference = first - second
    symbols = sorted(difference.free_symbols, key=str)
    generator = random.Random(0)
    trials = [dict.fromkeys(symbols, 0)] if not symbols else []
    trials += [
        {symbol: generator.uniform(1.1, 2.9) for symbol in symbols} for _ in range(SUBSTITUTION_TRIALS * bool(symbols))
    ]
    try:
        for substitution in trials:
            value = complex(difference.subs(substitution).evalf())
            scale = max(1.0, abs(complex(second.subs(substitution).evalf())))
            if abs(value) > RELATIVE_TOLERANCE * scale:
                return False
        return True
    except (TypeError, ValueError, ZeroDivisionError, OverflowError):
        return False


def top_level_parts(text: str) -> tuple[str, list[str]]:
    """Bracket kind and comma-separated parts of a tuple or interval; a single part otherwise."""
    if len(text) >= 2 and text[0] in "([" and text[-1] in ")]":
        inner, kind = text[1:-1], text[0] + text[-1]
    else:
        inner, kind = text, ""
    parts, depth, current = [], 0, []
    for character in inner:
        depth += {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}.get(character, 0)
        if character == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(character)
    parts.append("".join(current))
    return (kind, parts) if len(parts) > 1 else ("", [text])


def answers_match(predicted: str, reference: str) -> bool:
    predicted, reference = normalize_answer(predicted), normalize_answer(reference)
    if predicted == reference:
        return True
    predicted_kind, predicted_parts = top_level_parts(predicted)
    reference_kind, reference_parts = top_level_parts(reference)
    if len(predicted_parts) != len(reference_parts) or predicted_kind != reference_kind:
        return False
    if len(reference_parts) > 1 and reference_kind:
        return all(answers_match(left, right) for left, right in zip(predicted_parts, reference_parts, strict=True))
    if len(reference_parts) > 1:
        # A bare list of solutions may come in any order.
        unmatched = list(reference_parts)
        for part in predicted_parts:
            match = next((candidate for candidate in unmatched if answers_match(part, candidate)), None)
            if match is None:
                return False
            unmatched.remove(match)
        return True
    first, second = parse_value(predicted), parse_value(reference)
    if first is None or second is None:
        return False
    try:
        return values_equal(first, second)
    except Exception:
        return False
