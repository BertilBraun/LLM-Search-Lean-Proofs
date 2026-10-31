"""Hypotheses in pretty-printed goals: names, types, redundant and closed-form (numeral comparison) additions, and
`rename_i` for inaccessible names."""

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

INACCESSIBLE_MARK = "✝"
_HYPOTHESIS_LINE = re.compile(r"(?P<names>[^\s⊢][^:]*?) :(?=\s|$)")
_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_INACCESSIBLE_NAME = re.compile(rf"[^\s✝]*✝[{_SUPERSCRIPT_DIGITS}]*")
_OPENING_BRACKETS = "([{⟨"
_CLOSING_BRACKETS = ")]}⟩"
_SYMMETRIC_RELATIONS = (" = ", " ↔ ")
_COMPARISONS = (" = ", " ≠ ", " < ", " ≤ ", " > ", " ≥ ")
_NUMERAL = re.compile(r"-?\d+(\.\d+)?")
_NUMBER_TYPES = frozenset({"ℕ", "ℤ", "ℚ", "ℝ", "ℂ"})


@dataclass(frozen=True)
class GoalParts:
    # One whitespace-normalized type per hypothesis name, in context order.
    hypothesis_types: tuple[str, ...]
    target: str
    hypothesis_names: tuple[str, ...] = ()


def normalized_text(lines: Sequence[str]) -> str:
    return " ".join(" ".join(lines).split())


def goal_parts(goal: str) -> GoalParts:
    """The hypotheses' types and the target of a goal; a hypothesis or the target continues on indented lines."""
    entries: list[tuple[list[str], list[str]]] = []
    target: list[str] | None = None
    for line in goal.split("\n"):
        if target is not None:
            target.append(line)
        elif line.startswith("⊢"):
            target = [line[1:]]
        elif line.startswith("case ") and not entries:
            continue
        elif (match := _HYPOTHESIS_LINE.match(line)) is not None:
            entries.append((match["names"].split(), [line[match.end() :]]))
        elif entries:
            entries[-1][1].append(line)
    types = tuple(normalized_text(type_lines) for names, type_lines in entries for _ in names)
    names = tuple(name for entry_names, _ in entries for name in entry_names)
    return GoalParts(types, normalized_text(target or []), names)


def top_level_parts(proposition: str, separator: str) -> list[str]:
    parts = []
    depth = 0
    start = 0
    index = 0
    while index < len(proposition):
        character = proposition[index]
        if character in _OPENING_BRACKETS:
            depth += 1
        elif character in _CLOSING_BRACKETS:
            depth -= 1
        elif depth == 0 and proposition.startswith(separator, index):
            parts.append(proposition[start:index])
            start = index + len(separator)
            index = start
            continue
        index += 1
    parts.append(proposition[start:])
    return parts


def is_reflexive(proposition: str) -> bool:
    """`a = a` or `a ↔ a` at the top level."""
    for relation in _SYMMETRIC_RELATIONS:
        sides = top_level_parts(proposition, relation)
        if len(sides) == 2 and sides[0].strip() == sides[1].strip():
            return True
    return False


def is_numeral(term: str) -> bool:
    """A numeral, or a cast of one: `2`, `-1`, `(1:ℝ)`, `((2 : ℕ) : ℝ)`, `↑3`, in any parentheses."""
    term = term.strip()
    if _NUMERAL.fullmatch(term):
        return True
    if term.startswith("↑"):
        return is_numeral(term[1:])
    if not (term.startswith("(") and term.endswith(")")):
        return False
    match top_level_parts(term[1:-1], ":"):
        case [inner]:
            return is_numeral(inner)
        case [inner, number_type]:
            return number_type.strip() in _NUMBER_TYPES and is_numeral(inner)
        case _:
            return False


def is_numeral_comparison(proposition: str) -> bool:
    """`0 < (1:ℝ)`, `2 ≤ 3`, `(4:ℕ) = 4`: one comparison or equality of numerals and casts of numerals."""
    for relation in _COMPARISONS:
        sides = top_level_parts(proposition, relation)
        if len(sides) == 2 and all(is_numeral(side) for side in sides):
            return True
    return False


@dataclass(frozen=True)
class AddedHypothesis:
    proposition: str
    # The goal it was added to, as it was before.
    before: GoalParts

    @property
    def known(self) -> bool:
        return self.proposition in self.before.hypothesis_types or is_reflexive(self.proposition)

    @property
    def closed_form(self) -> bool:
        """A comparison of numerals like `0 < (1:ℝ)`, in a context with names: a statement without any is exempt."""
        return bool(self.before.hypothesis_names) and is_numeral_comparison(self.proposition)


def added_hypotheses(before: Sequence[str], after: Sequence[str]) -> tuple[AddedHypothesis, ...] | None:
    """What `after` adds to `before` when it only adds hypotheses (a flattened `have h : A` also puts `⊢ A` first,
    A counted as added); None when anything else changed."""
    if not before:
        return None
    before_parts = [goal_parts(goal) for goal in before]
    after_parts = [goal_parts(goal) for goal in after]
    first = before_parts[0]
    added = []
    if len(after_parts) == len(before_parts) + 1 and after_parts[0].hypothesis_types == first.hypothesis_types:
        added.append(AddedHypothesis(after_parts[0].target, first))
        after_parts = after_parts[1:]
    if len(after_parts) != len(before_parts):
        return None
    for old, new in zip(before_parts, after_parts, strict=True):
        old_types = Counter(old.hypothesis_types)
        new_types = Counter(new.hypothesis_types)
        if new.target != old.target or old_types - new_types:
            return None
        added.extend(AddedHypothesis(proposition, old) for proposition in (new_types - old_types).elements())
    return tuple(added)


def adds_only_redundant_hypotheses(before: Sequence[str], after: Sequence[str]) -> bool:
    """`after` is `before` plus known or reflexive hypotheses."""
    added = added_hypotheses(before, after)
    return bool(added) and all(hypothesis.known for hypothesis in added)


def adds_only_closed_form_hypotheses(before: Sequence[str], after: Sequence[str]) -> bool:
    """`after` is `before` plus closed-form hypotheses, besides known or reflexive ones: filler like `0 < (1:ℝ)`."""
    added = added_hypotheses(before, after)
    return (
        bool(added)
        and all(hypothesis.known or hypothesis.closed_form for hypothesis in added)
        and any(hypothesis.closed_form for hypothesis in added)
    )


def hypothesis_names(goal: str) -> list[str]:
    """Every hypothesis name of the goal in context order, as printed (inaccessible ones with their mark)."""
    names: list[str] = []
    for line in goal.split("\n"):
        if line.startswith("case "):
            continue
        match = _HYPOTHESIS_LINE.match(line)
        if match is not None:
            names.extend(match["names"].split())
    return names


def is_inaccessible(name: str) -> bool:
    return INACCESSIBLE_MARK in name


def fresh_name(inaccessible: str, taken: set[str]) -> str:
    base = inaccessible.split(INACCESSIBLE_MARK)[0] or "x"
    suffix = 1
    while f"{base}_{suffix}" in taken:
        suffix += 1
    return f"{base}_{suffix}"


def accessible_names(goal: str) -> list[str]:
    """Fresh names for the goal's inaccessible hypotheses (shadowed ones included), in context order."""
    names = hypothesis_names(goal)
    taken = {name for name in names if not is_inaccessible(name)}
    fresh = []
    for name in names:
        if is_inaccessible(name) and _INACCESSIBLE_NAME.fullmatch(name):
            fresh.append(fresh_name(name, taken))
            taken.add(fresh[-1])
    return fresh


def renaming_tactic(goals: Sequence[str]) -> str | None:
    """`rename_i` for the main goal and `on_goal k => rename_i …` for the others; None without inaccessible names."""
    # `rename_i` renames the newest inaccessible or shadowed hypotheses: naming all of them covers every marked one.
    lines = []
    for index, goal in enumerate(goals):
        names = accessible_names(goal)
        if not names:
            continue
        rename = f"rename_i {' '.join(names)}"
        lines.append(rename if index == 0 else f"on_goal {index + 1} => {rename}")
    return "\n".join(lines) if lines else None


def has_inaccessible_names(goals: Sequence[str]) -> bool:
    return any(INACCESSIBLE_MARK in goal for goal in goals)
