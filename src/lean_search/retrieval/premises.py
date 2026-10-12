"""Premise and goal text: ReProver's serialization for the retriever, compact signatures for the prompt."""

import dataclasses
import json
import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

MARK_START = "<a>"
MARK_END = "</a>"
_OPENING_BRACKETS = {"(": ")", "{": "}", "[": "]", "⦃": "⦄"}
_ALL_OPENING = "([{⦃⟨"
_ALL_CLOSING = ")]}⦄⟩"
_SORT_BINDER = re.compile(r"^[{⦃][^:]*:\s*(?:Type|Sort)\b[^:]*[}⦄]$")
_WHITESPACE = re.compile(r"\s+")
ELLIPSIS = " …"


@dataclass(frozen=True)
class PremiseSignature:
    full_name: str
    # Lean's `ppSignature` in the pinned environment, on one line, without universe parameters.
    signature: str


def serialize_premise(full_name: str, code: str) -> str:
    """ReProver's `Premise.serialize`: the declaration's source with its name marked."""
    marked_name = f"{MARK_START}{full_name}{MARK_END}"
    code = code.replace(f"_root_.{full_name}", marked_name)
    fields = full_name.split(".")
    for index in range(len(fields)):
        suffix = ".".join(fields[index:])
        marked = re.sub(rf"(?<=\s)«?{re.escape(suffix)}»?", lambda _: marked_name, code)
        if marked != code:
            return marked
    return code


def serialize_goals(goals: Sequence[str]) -> str:
    return "\n\n".join(goals)


def strip_leandojo_goal_count(state: str) -> str:
    # ReProver's `format_state`: LeanDojo prefixes states with several goals by "N goals".
    match = re.match(r"\d+ goals", state)
    return state[match.end() :].strip() if match else state


def one_line(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def strip_universe_parameters(signature: str, full_name: str) -> str:
    prefix = full_name + ".{"
    if not signature.startswith(prefix):
        return signature
    closing = signature.index("}", len(prefix))
    return full_name + signature[closing + 1 :]


def matching_bracket(text: str, start: int) -> int:
    depth = 0
    for position in range(start, len(text)):
        character = text[position]
        if character in _ALL_OPENING:
            depth += 1
        elif character in _ALL_CLOSING:
            depth -= 1
            if depth == 0:
                return position
    return -1


def split_signature(signature: str, full_name: str) -> tuple[tuple[str, ...], str] | None:
    """The binder groups and the conclusion of `name binders : type`, or None if the text has another shape."""
    if not signature.startswith(full_name):
        return None
    binders: list[str] = []
    position = len(full_name)
    while True:
        while signature.startswith(" ", position):
            position += 1
        if signature.startswith(":", position):
            return tuple(binders), signature[position + 1 :].strip()
        if position >= len(signature) or signature[position] not in _OPENING_BRACKETS:
            return None
        closing = matching_bracket(signature, position)
        if closing < 0 or signature[closing] != _OPENING_BRACKETS[signature[position]]:
            return None
        binders.append(signature[position : closing + 1])
        position = closing + 1


def is_dropped_binder(binder: str) -> bool:
    # Instance arguments and implicit type variables are found by unification; the model never writes them.
    return binder.startswith("[") or _SORT_BINDER.match(binder) is not None


def compact_signature(signature: str, full_name: str, max_characters: int) -> str:
    parts = split_signature(signature, full_name)
    if parts is not None:
        binders, conclusion = parts
        kept = [binder for binder in binders if not is_dropped_binder(binder)]
        signature = " ".join([full_name, *kept, ":", conclusion])
    if len(signature) <= max_characters:
        return signature
    return signature[: max_characters - len(ELLIPSIS)].rstrip() + ELLIPSIS


def write_signatures(path: Path, signatures: Iterable[PremiseSignature]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for signature in signatures:
            handle.write(json.dumps(dataclasses.asdict(signature), ensure_ascii=False) + "\n")
            count += 1
    return count


def read_signatures(path: Path) -> Iterator[PremiseSignature]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield PremiseSignature(**json.loads(line))
