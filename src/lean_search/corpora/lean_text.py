import re
from dataclasses import dataclass
from enum import StrEnum

OPENING_BRACKETS = "([{⟨⦃"
CLOSING_BRACKETS = ")]}⟩⦄"

_COMMENT_OR_STRING = re.compile(r'/-|--|"')
_BLOCK_COMMENT_DELIMITER = re.compile(r"/-|-/")
_STRING_END = re.compile(r'\\.|"', re.DOTALL)
_DECLARATION = re.compile(
    r"^[ \t]*(?:@\[[^\]\n]*\][ \t]*)?(?:(?:private|protected|nonrec|noncomputable)[ \t]+)*(?:theorem|lemma|example)\b",
    re.MULTILINE,
)
_STATEMENT_SCAN = re.compile(r"[(\[{⟨⦃]|[)\]}⟩⦄]|:=|\"|(?<![\w.'])(?:let|have)(?![\w'])")
_BY_KEYWORD = re.compile(r"[ \t\n]*by\b")
_INCOMPLETE_PROOF = re.compile(r"\b(?:sorry|admit)\b")
_AXIOM_DECLARATION = re.compile(r"^\s*axiom\b", re.MULTILINE)
# A line at the tactic-block column that starts with one of these cannot begin a new tactic.
_CONTINUATION_START = re.compile(r"(?:[|)\]}⟩⦄_+*/=≤≥<>∧∨→↔≠^,:∣∘]|-(?!-)|(?:then|else|with|at|using|from)\b)")
# A line ending in one of these continues on the next line even if that line sits at the block column.
_CONTINUATION_END = re.compile(r"(?:<;>|<\||\|>|[;,(\[{⟨⦃+*/∧∨→↔]|=>|↦|:=|\b(?:by|from|at|with|then|else|fun))\s*$")


class DeclarationError(StrEnum):
    NO_DECLARATION = "no_declaration"
    NO_ASSIGNMENT = "no_assignment"
    TERM_MODE = "term_mode"


@dataclass(frozen=True)
class StatementParts:
    header: str
    formal_statement: str


@dataclass(frozen=True)
class DeclarationParts:
    header: str
    formal_statement: str
    tactic_proof: str
    trailing_text: str


def _block_comment_end(text: str, start: int) -> int:
    depth = 0
    for match in _BLOCK_COMMENT_DELIMITER.finditer(text, start):
        depth += 1 if match.group() == "/-" else -1
        if depth == 0:
            return match.end()
    return len(text)


def _string_end(text: str, start: int) -> int:
    for match in _STRING_END.finditer(text, start + 1):
        if match.group() == '"':
            return match.end()
    return len(text)


def strip_comments(text: str) -> str:
    pieces: list[str] = []
    position = 0
    while (match := _COMMENT_OR_STRING.search(text, position)) is not None:
        start = match.start()
        pieces.append(text[position:start])
        match match.group():
            case "--":
                line_end = text.find("\n", start)
                position = len(text) if line_end == -1 else line_end
            case "/-":
                position = _block_comment_end(text, start)
                # Blank out instead of deleting so that the columns of code after the comment are preserved.
                pieces.append(re.sub(r"[^\n]", " ", text[start:position]))
            case _:
                position = _string_end(text, start)
                pieces.append(text[start:position])
    pieces.append(text[position:])
    lines = (line.rstrip() for line in "".join(pieces).split("\n"))
    return "\n".join(line for line in lines if line)


def bracket_depth_change(text: str) -> int:
    change = 0
    in_string = False
    previous = ""
    for character in text:
        if in_string:
            if character == '"' and previous != "\\":
                in_string = False
        elif character == '"':
            in_string = True
        elif character in OPENING_BRACKETS:
            change += 1
        elif character in CLOSING_BRACKETS:
            change -= 1
        previous = character
    return change


def _find_declaration_start(text: str, theorem_name: str | None) -> int | None:
    if theorem_name is not None:
        named = re.search(
            rf"^[^\S\n]*(?:@\[[^\]\n]*\][^\S\n]*)?(?:theorem|lemma)\s+{re.escape(theorem_name)}(?=[\s(\[{{⦃:])",
            text,
            re.MULTILINE,
        )
        if named is not None:
            return named.start()
    starts = [match.start() for match in _DECLARATION.finditer(text)]
    return starts[-1] if starts else None


def _find_top_level_assignment(text: str, start: int) -> int | None:
    depth = 0
    pending_local_definitions = 0
    position = start
    while (match := _STATEMENT_SCAN.search(text, position)) is not None:
        token = match.group()
        position = match.end()
        match token:
            case '"':
                position = _string_end(text, match.start())
            case "let" | "have" if depth == 0:
                pending_local_definitions += 1
            case ":=" if depth == 0 and pending_local_definitions > 0:
                pending_local_definitions -= 1
            case ":=" if depth == 0:
                return match.start()
            case _ if token in OPENING_BRACKETS:
                depth += 1
            case _ if token in CLOSING_BRACKETS:
                depth -= 1
    return None


def _indentation(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _dedent_tactic_block(first_line_remainder: str, following_lines: list[str], block_column: int) -> list[str]:
    lines = [first_line_remainder.strip()] if first_line_remainder.strip() else []
    for line in following_lines:
        indentation = _indentation(line)
        # Continuation lines of a tactic written on the `by` line may sit left of the block column.
        kept_indentation = indentation - block_column if indentation >= block_column else indentation
        lines.append(" " * kept_indentation + line.lstrip(" "))
    return lines


def _split_trailing_commands(
    first_line_remainder: str, following_lines: list[str], block_column: int
) -> tuple[list[str], str]:
    if block_column == 0:
        return following_lines, ""
    depth = bracket_depth_change(first_line_remainder)
    for index, line in enumerate(following_lines):
        if depth <= 0 and _indentation(line) == 0:
            return following_lines[:index], "\n".join(following_lines[index:])
        depth += bracket_depth_change(line)
    return following_lines, ""


def _locate_declaration(text: str, theorem_name: str | None) -> tuple[int, int] | DeclarationError:
    declaration_start = _find_declaration_start(text, theorem_name)
    if declaration_start is None:
        return DeclarationError.NO_DECLARATION
    assignment = _find_top_level_assignment(text, declaration_start)
    if assignment is None:
        return DeclarationError.NO_ASSIGNMENT
    return declaration_start, assignment


def split_statement(source_text: str, theorem_name: str | None = None) -> StatementParts | DeclarationError:
    text = strip_comments(source_text)
    location = _locate_declaration(text, theorem_name)
    if isinstance(location, DeclarationError):
        return location
    declaration_start, assignment = location
    signature = text[declaration_start:assignment].strip()
    return StatementParts(header=text[:declaration_start].strip("\n"), formal_statement=f"{signature} := by")


def split_declaration(source_text: str, theorem_name: str | None = None) -> DeclarationParts | DeclarationError:
    text = strip_comments(source_text)
    location = _locate_declaration(text, theorem_name)
    if isinstance(location, DeclarationError):
        return location
    declaration_start, assignment = location
    by_match = _BY_KEYWORD.match(text, assignment + 2)
    if by_match is None:
        return DeclarationError.TERM_MODE
    header = text[:declaration_start].strip("\n")
    signature = text[declaration_start:assignment].strip()
    formal_statement = f"{signature} := by"
    by_line_end = text.find("\n", by_match.end())
    if by_line_end == -1:
        by_line_end = len(text)
    first_line_remainder = text[by_match.end() : by_line_end]
    following_lines = text[by_line_end + 1 :].split("\n") if by_line_end < len(text) else []
    if first_line_remainder.strip():
        block_column = by_match.end() - (text.rfind("\n", 0, by_match.end()) + 1)
        block_column += len(first_line_remainder) - len(first_line_remainder.lstrip(" "))
    elif following_lines:
        block_column = _indentation(following_lines[0])
    else:
        block_column = 0
    following_lines, trailing_text = _split_trailing_commands(first_line_remainder, following_lines, block_column)
    tactic_lines = _dedent_tactic_block(first_line_remainder, following_lines, block_column)
    return DeclarationParts(
        header=header,
        formal_statement=formal_statement,
        tactic_proof="\n".join(tactic_lines),
        trailing_text=trailing_text,
    )


def split_top_level_tactics(tactic_proof: str) -> tuple[str, ...]:
    tactics: list[list[str]] = []
    depth = 0
    for line in tactic_proof.split("\n"):
        if not line.strip():
            continue
        starts_new_tactic = not tactics or (
            depth <= 0
            and _indentation(line) == 0
            and not _CONTINUATION_START.match(line)
            and not _CONTINUATION_END.search(tactics[-1][-1])
        )
        if starts_new_tactic:
            tactics.append([line])
        else:
            tactics[-1].append(line)
        depth += bracket_depth_change(line)
    return tuple("\n".join(lines) for lines in tactics)


def contains_incomplete_proof(text: str) -> bool:
    return _INCOMPLETE_PROOF.search(text) is not None


def declares_axiom(text: str) -> bool:
    return _AXIOM_DECLARATION.search(text) is not None
