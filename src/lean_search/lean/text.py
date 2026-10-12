"""Pure text handling for Lean proofs: lexing, tactic splitting, forbidden tokens, goal normalization, commands."""

import functools
import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

FORBIDDEN_TOKENS = frozenset(
    {
        # Unsound or proof-irrelevant closers.
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
        # Resource limits and arbitrary metaprograms.
        "set_option",
        "maxHeartbeats",
        "run_tac",
        "run_cmd",
        "run_elab",
        "run_meta",
        "by_elab",
        "sleep",
        "polyrith",
        # Our own wrapper syntax and names.
        "lean_search_heartbeats",
        "lean_search_single_command",
        "lean_search_check_constants",
        "lean_search_auxiliaries",
        "lean_search_step",
        # `apply?`, `hint` and `slim_check` close goals with `sorryAx` and no error; the others build a lemma index.
        "apply?",
        "exact?",
        "rw?",
        "hint",
        "slim_check",
        "aesop?",
        "simp?",
        "simp?!",
        "simp_all?",
        "simp_all?!",
        "dsimp?",
        "dsimp?!",
        "rw_search",
        "library_search",
        "observe",
    }
)

CONTINUATION_PREFIXES = ("<;>", "<|>", "|", ")", "]", "}", "⟩", ":=", "_")
CONTINUATION_PREFIX_WORDS = ("else", "then", "with")
CONTINUATION_SUFFIXES = ("<;>", ",", ":=", "=>", "↦", "<|")
CONTINUATION_SUFFIX_WORDS = ("by", "with", "then", "else", "do", "from", "fun", "calc")
INCOMPLETE_INPUT_MESSAGES = ("unexpected end of input", "unterminated comment")

_OPENING_BRACKETS = "([{⟨⦃⟪"
_CLOSING_BRACKETS = ")]}⟩⦄⟫"
_SAFE_BEFORE_COMMENT = ")]}⟩,"
_THEOREM_NAME_PATTERN = re.compile(r"^\s*(?:theorem|lemma)\s+([^\s(){}\[\]:]+)", re.MULTILINE)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_PROOF_POSITION_PATTERN = re.compile(r":=\s*by$")
_PROOF_START_PATTERN = re.compile(r":=\s*(?:by\s*)?$")
_HEADER_LINE_PATTERN = re.compile(r"^\s*(?:import\s|prelude\b)")
AUXILIARY_THEOREM_SUFFIX = "lean_search_auxiliaries"


class HeaderParts(NamedTuple):
    imports: str
    commands: str


class LexicalKind(Enum):
    CODE = "code"
    STRING = "string"
    COMMENT = "comment"


@dataclass(frozen=True)
class LexedText:
    text: str
    kinds: tuple[LexicalKind, ...]
    exact: bool

    def masked(self, kept: frozenset[LexicalKind]) -> str:
        return "".join(
            character if kind in kept or character == "\n" else " "
            for character, kind in zip(self.text, self.kinds, strict=True)
        )


def is_identifier_character(character: str) -> bool:
    return character.isalnum() or character in "_'!?"


def lex(text: str) -> LexedText:
    """Classify characters as code, string or comment like Lean; `exact` is False where Lean might disagree."""
    kinds: list[LexicalKind] = []
    exact = "«" not in text and "`" not in text
    index = 0

    def at_token_boundary() -> bool:
        if index == 0 or kinds[-1] is not LexicalKind.CODE:
            return True
        previous = text[index - 1]
        return previous.isspace() or is_identifier_character(previous) or previous in _SAFE_BEFORE_COMMENT

    while index < len(text):
        character = text[index]
        if text.startswith("--", index):
            exact = exact and at_token_boundary()
            end = text.find("\n", index)
            end = len(text) if end < 0 else end
            kinds += [LexicalKind.COMMENT] * (end - index)
            index = end
        elif text.startswith("/-", index):
            exact = exact and at_token_boundary()
            # A plain `/-` skips its next character before counting nesting; `/--` and `/-!` start right after.
            end = _block_comment_end(text, index + 3)
            kinds += [LexicalKind.COMMENT] * (end - index)
            index = end
        elif character == '"':
            exact = exact and (index == 0 or text[index - 1].isspace())
            end = _string_end(text, index + 1)
            kinds += [LexicalKind.STRING] * (end - index)
            index = end
        else:
            if character == "'" and not (index > 0 and is_identifier_character(text[index - 1])):
                exact = False
            kinds.append(LexicalKind.CODE)
            index += 1
    return LexedText(text, tuple(kinds), exact)


def _block_comment_end(text: str, position: int) -> int:
    nesting = 1
    while position < len(text):
        if text.startswith("-/", position):
            nesting -= 1
            position += 2
            if nesting == 0:
                return position
        elif text.startswith("/-", position):
            nesting += 1
            position += 2
        else:
            position += 1
    return len(text)


def _string_end(text: str, position: int) -> int:
    while position < len(text):
        if text[position] == "\\":
            position += 2
        elif text[position] == '"':
            return position + 1
        else:
            position += 1
    return len(text)


@functools.cache
def _forbidden_pattern(tokens: frozenset[str]) -> re.Pattern[str]:
    identifier = r"[\w'!?]"
    alternatives = "|".join(sorted(map(re.escape, tokens), key=len, reverse=True))
    return re.compile(rf"(?<!{identifier})({alternatives})(?!{identifier})")


def find_forbidden_tokens(text: str, tokens: frozenset[str] = FORBIDDEN_TOKENS) -> list[str]:
    if not tokens:
        return []
    lexed = lex(text)
    searched = lexed.masked(frozenset({LexicalKind.CODE, LexicalKind.STRING})) if lexed.exact else text
    return sorted(set(_forbidden_pattern(tokens).findall(searched)))


def split_tactics(block: str) -> list[str]:
    lexed = lex(block)
    content_lines = lexed.masked(frozenset({LexicalKind.CODE, LexicalKind.STRING})).split("\n")
    code_lines = lexed.masked(frozenset({LexicalKind.CODE})).split("\n")
    tactics: list[list[str]] = []
    base_indentation: int | None = None
    bracket_depth = 0
    continues = False
    previous_line_kept = False
    offset = 0
    for line, content_line, code_line in zip(block.split("\n"), content_lines, code_lines, strict=True):
        starts_inside = offset > 0 and lexed.kinds[offset - 1] is not LexicalKind.CODE
        offset += len(line) + 1
        line = line.rstrip()
        content = content_line.strip()
        if starts_inside and not previous_line_kept:
            # The comment or string began on a dropped line, so only the code after it remains.
            first_content = len(content_line) - len(content_line.lstrip())
            line, starts_inside = line[first_content:], False
        if not content:
            previous_line_kept = starts_inside and previous_line_kept and bool(tactics)
            if previous_line_kept:
                tactics[-1].append(_relative_line(line, base_indentation or 0))
            continue
        indentation = len(content_line) - len(content_line.lstrip())
        if base_indentation is None:
            base_indentation = indentation
        code = code_line.strip()
        is_continuation = bool(tactics) and (
            starts_inside
            or bracket_depth > 0
            or continues
            or indentation > base_indentation
            or code.startswith(CONTINUATION_PREFIXES)
            or _starts_with_word(code, CONTINUATION_PREFIX_WORDS)
        )
        if is_continuation:
            tactics[-1].append(_relative_line(line, base_indentation))
        else:
            tactics.append([line.strip()])
        previous_line_kept = True
        bracket_depth = max(bracket_depth + _bracket_balance(code), 0)
        continues = code.endswith(CONTINUATION_SUFFIXES) or _ends_with_word(code, CONTINUATION_SUFFIX_WORDS)
    return ["\n".join(lines) for lines in tactics]


def _relative_line(line: str, base_indentation: int) -> str:
    indentation = len(line) - len(line.lstrip())
    return line[min(indentation, base_indentation) :]


def _bracket_balance(code: str) -> int:
    return sum(character in _OPENING_BRACKETS for character in code) - sum(
        character in _CLOSING_BRACKETS for character in code
    )


def _starts_with_word(code: str, words: Sequence[str]) -> bool:
    return any(
        code.startswith(word) and not is_identifier_character(code[len(word) : len(word) + 1] or " ") for word in words
    )


def _ends_with_word(code: str, words: Sequence[str]) -> bool:
    return any(
        code.endswith(word) and not is_identifier_character(code[-len(word) - 1 : -len(word)] or " ") for word in words
    )


def is_incomplete_input(message: str) -> bool:
    return any(marker in message for marker in INCOMPLETE_INPUT_MESSAGES)


def indent(text: str, spaces: int) -> str:
    prefix = " " * spaces
    return "\n".join(prefix + line if line.strip() else line for line in text.splitlines())


def wrap_tactic(tactic: str, heartbeats: int) -> str:
    return f"lean_search_heartbeats {heartbeats} =>\n{indent(tactic, 2)}"


def executed_proof(tactics: Sequence[str], heartbeats: Sequence[int]) -> str:
    return join_tactics([wrap_tactic(tactic, limit) for tactic, limit in zip(tactics, heartbeats, strict=True)])


def lean_string_literal(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


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


def split_header(header: str) -> HeaderParts:
    """The leading `import` (and `prelude`) lines, whitespace-normalized, and the text after the last of them."""
    lines = header.split("\n")
    import_lines: list[str] = []
    commands_start = 0
    for index, code_line in enumerate(lex(header).masked(frozenset({LexicalKind.CODE})).split("\n")):
        if _HEADER_LINE_PATTERN.match(code_line):
            import_lines.append(" ".join(code_line.split()))
            commands_start = index + 1
        elif code_line.strip():
            break
    return HeaderParts("\n".join(import_lines), "\n".join(lines[commands_start:]))


def auxiliary_statement(statement: str) -> str | None:
    """`theorem X.lean_search_auxiliaries binders : (type) → True`: the statement's matchers without a proof of it."""
    name_match = _THEOREM_NAME_PATTERN.search(statement)
    code = lex(statement).masked(frozenset({LexicalKind.CODE}))
    proof_start = _PROOF_START_PATTERN.search(code)
    if name_match is None or proof_start is None:
        return None
    colon = _signature_colon(code, name_match.end(), proof_start.start())
    if colon is None:
        return None
    return (
        f"{statement[: name_match.end()]}.{AUXILIARY_THEOREM_SUFFIX}{statement[name_match.end() : colon]}"
        f": ({statement[colon + 1 : proof_start.start()]}\n) → True := fun _ => trivial"
    )


def _signature_colon(code: str, start: int, end: int) -> int | None:
    depth = 0
    for index in range(start, end):
        character = code[index]
        if character in _OPENING_BRACKETS:
            depth += 1
        elif character in _CLOSING_BRACKETS:
            depth -= 1
        elif character == ":" and depth == 0 and code[index + 1 : index + 2] != "=":
            return index
    return None
