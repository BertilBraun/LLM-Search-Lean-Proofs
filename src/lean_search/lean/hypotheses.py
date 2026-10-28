"""Hypotheses in pretty-printed goals: names, types, redundant additions, and `rename_i` for inaccessible names."""

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


@dataclass(frozen=True)
class GoalParts:
    # One whitespace-normalized type per hypothesis name, in context order.
    hypothesis_types: tuple[str, ...]
    target: str


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
    return GoalParts(types, normalized_text(target or []))


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


def adds_only_redundant_hypotheses(before: Sequence[str], after: Sequence[str]) -> bool:
    """`after` is `before` plus known or reflexive hypotheses (a flattened `have h : A` also puts `⊢ A` first)."""
    if not before:
        return False
    before_parts = [goal_parts(goal) for goal in before]
    after_parts = [goal_parts(goal) for goal in after]
    first = before_parts[0]
    if (
        len(after_parts) == len(before_parts) + 1
        and after_parts[0].hypothesis_types == first.hypothesis_types
        and (after_parts[0].target in first.hypothesis_types or is_reflexive(after_parts[0].target))
    ):
        after_parts = after_parts[1:]
    if len(after_parts) != len(before_parts):
        return False
    added = False
    for old, new in zip(before_parts, after_parts, strict=True):
        old_types = Counter(old.hypothesis_types)
        new_types = Counter(new.hypothesis_types)
        if new.target != old.target or old_types - new_types:
            return False
        for proposition in (new_types - old_types).elements():
            if proposition not in old_types and not is_reflexive(proposition):
                return False
            added = True
    return added


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
