"""Pure text handling for Lean proofs: tactic splitting, forbidden tokens, goal normalization, command assembly."""

import re
from collections.abc import Sequence

FORBIDDEN_TOKENS = frozenset(
    {
        "sorry",
        "admit",
        "sorryAx",
        "stop",
        "native_decide",
        "ofReduceBool",
        "ofReduceNat",
        "reduceBool",
        "reduceNat",
        "implemented_by",
        "extern",
        "unsafe",
        "set_option",
        "maxHeartbeats",
        "run_tac",
        "run_cmd",
        "run_elab",
        "run_meta",
        "by_elab",
        "polyrith",
        "lean_search_heartbeats",
    }
)

CONTINUATION_PREFIXES = ("<;>", "|", "else")

_IDENTIFIER_CHARACTER = r"[\w'!?]"
_FORBIDDEN_PATTERN = re.compile(
    rf"(?<!{_IDENTIFIER_CHARACTER})("
    + "|".join(sorted(map(re.escape, FORBIDDEN_TOKENS), key=len, reverse=True))
    + rf")(?!{_IDENTIFIER_CHARACTER})"
)
_THEOREM_NAME_PATTERN = re.compile(r"^\s*(?:theorem|lemma)\s+([^\s(){}\[\]:]+)", re.MULTILINE)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_PROOF_POSITION_PATTERN = re.compile(r":=\s*by$")


def find_forbidden_tokens(text: str) -> list[str]:
    return sorted(set(_FORBIDDEN_PATTERN.findall(text)))


def split_tactics(block: str) -> list[str]:
    tactics: list[list[str]] = []
    base_indentation: int | None = None
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        indentation = len(line) - len(line.lstrip(" "))
        if base_indentation is None:
            base_indentation = indentation
        starts_new_tactic = indentation <= base_indentation and not stripped.startswith(CONTINUATION_PREFIXES)
        if starts_new_tactic or not tactics:
            tactics.append([stripped])
        else:
            tactics[-1].append(" " * max(indentation - base_indentation, 0) + stripped)
    return ["\n".join(lines) for lines in tactics]


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def normalize_goal(goal: str) -> str:
    lines = (_WHITESPACE_PATTERN.sub(" ", line).strip() for line in goal.splitlines())
    return "\n".join(line for line in lines if line)


def theorem_name(statement: str) -> str:
    match = _THEOREM_NAME_PATTERN.search(statement)
    if match is None:
        raise ValueError(f"No theorem name found in statement: {statement[:200]!r}")
    return match.group(1)


def theorem_with_proof(statement: str, proof: str) -> str:
    statement = statement.rstrip()
    if statement.endswith(":="):
        statement += " by"
    if _PROOF_POSITION_PATTERN.search(statement) is None:
        raise ValueError(f"Statement must end with ':= by' or ':=': {statement[-200:]!r}")
    return statement + "\n" + indent(proof, 2)


def join_tactics(tactics: Sequence[str]) -> str:
    return "\n".join(tactics)
