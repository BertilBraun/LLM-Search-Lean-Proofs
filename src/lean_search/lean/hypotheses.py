"""Hypothesis names in pretty-printed goals, and the `rename_i` step that makes inaccessible ones accessible."""

import re
from collections.abc import Sequence

INACCESSIBLE_MARK = "✝"
_HYPOTHESIS_LINE = re.compile(r"(?P<names>[^\s⊢][^:]*?) :(?=\s|$)")
_SUPERSCRIPT_DIGITS = "⁰¹²³⁴⁵⁶⁷⁸⁹"
_INACCESSIBLE_NAME = re.compile(rf"[^\s✝]*✝[{_SUPERSCRIPT_DIGITS}]*")


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
