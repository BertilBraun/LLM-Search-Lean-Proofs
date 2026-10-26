"""Execution plans for tactic blocks: top-level pieces, flattened nested `have` proofs and focus blocks, guards."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum

from lean_search.lean.text import LexicalKind, TacticPiece, join_tactics, lex, split_tactic_pieces

# Tactics that act on goals other than the main one, so they would see the outer goals once a nested proof is a
# sequence of top-level steps.
GOAL_LIST_TACTICS = frozenset(
    {
        "all_goals",
        "any_goals",
        "repeat",
        "repeat'",
        "repeat1",
        "iterate",
        "rotate_left",
        "rotate_right",
        "swap",
        "pick_goal",
        "on_goal",
        "case",
        "case'",
        "exacts",
        "focus",
        "solve_by_elim",
        "sorry",
        "admit",
    }
)
NO_GOALS_MESSAGE = "no goals to be proved"
UNSOLVED_MESSAGE = "unsolved goals: the nested proof (flattened by the search) ends with its goal open"
OUTSIDE_MESSAGE = "lean_search: the tactic changed goals outside its nested proof"
_WORD_PATTERN = re.compile(r"[^\W\d][\w'!?]*")
_HAVE_PATTERN = re.compile(r"(?:have|obtain)(?![\w'!?])")
_IDENTIFIER_PATTERN = re.compile(r"[^\W\d][\w'!?]*")
_HOLE_PATTERN = re.compile(r"(?<![\w'!?])_(?![\w'!?])|\?")
_OPENING_BRACKETS = "([{⟨⦃⟪"
_CLOSING_BRACKETS = ")]}⟩⦄⟫"
_BULLETS = ("·", ".")


class SegmentKind(StrEnum):
    # `have h : A` (or `obtain pat : A`) made A the first goal; the tactics of its nested proof follow.
    HAVE = "have"
    # The body of a `·` focus block.
    BULLET = "bullet"


@dataclass(frozen=True)
class FocusSegment:
    """Tactics first..last work on the main goal at `first` alone and must close it exactly at `last`."""

    kind: SegmentKind
    first: int
    last: int


@dataclass(frozen=True)
class Rejection:
    """The plan stops before tactic `index`, which was rejected without running Lean."""

    index: int
    message: str


@dataclass(frozen=True)
class TacticPlan:
    block: str
    tactics: tuple[TacticPiece, ...]
    segments: tuple[FocusSegment, ...] = ()
    rejection: Rejection | None = None

    @property
    def flattened(self) -> bool:
        return bool(self.segments)

    @property
    def texts(self) -> tuple[str, ...]:
        return tuple(tactic.text for tactic in self.tactics)

    @property
    def limit(self) -> int:
        return len(self.tactics) if self.rejection is None else self.rejection.index

    def rejecting(self, rejection: Rejection) -> "TacticPlan":
        return replace(self, rejection=rejection)

    def merged(self, index: int) -> "TacticPlan | None":
        """Tactics index and index + 1 as one tactic, or None when they belong to different nested proofs."""
        if index + 1 >= len(self.tactics) or any(
            (segment.first <= index <= segment.last) != (segment.first <= index + 1 <= segment.last)
            or segment.first == index + 1
            for segment in self.segments
        ):
            return None
        first, second = self.tactics[index], self.tactics[index + 1]
        combined = TacticPiece(join_tactics([first.text, second.text]), first.start, second.end)
        segments = tuple(
            FocusSegment(
                segment.kind,
                segment.first - (segment.first > index),
                segment.last - (segment.last > index),
            )
            for segment in self.segments
        )
        rejection = self.rejection
        if rejection is not None and rejection.index > index:
            rejection = Rejection(rejection.index - 1, rejection.message)
        tactics = (*self.tactics[:index], combined, *self.tactics[index + 2 :])
        return TacticPlan(self.block, tactics, segments, rejection)


@dataclass
class _Fragment:
    tactics: list[TacticPiece] = field(default_factory=list)
    segments: list[FocusSegment] = field(default_factory=list)

    def extend(self, other: "_Fragment") -> None:
        offset = len(self.tactics)
        self.tactics.extend(other.tactics)
        self.segments.extend(
            FocusSegment(segment.kind, segment.first + offset, segment.last + offset) for segment in other.segments
        )


def plain_plan(block: str) -> TacticPlan:
    return TacticPlan(block, tuple(split_tactic_pieces(block)))


def plan_block(block: str, flatten: bool = True) -> TacticPlan:
    """The block's top-level tactics; with `flatten`, nested `have … := by` proofs and `·` blocks become steps."""
    lexed = lex(block)
    if not flatten or not lexed.exact:
        return plain_plan(block)
    fragment = _plan_region(_Text(block, lexed.masked(frozenset({LexicalKind.CODE}))), 0, len(block))
    return TacticPlan(block, tuple(fragment.tactics), tuple(fragment.segments))


def flatten_proof(proof: str) -> str:
    """The proof with nested `have … := by` proofs as top-level steps (for rewriting training data)."""
    return join_tactics(plan_block(proof).texts)


@dataclass(frozen=True)
class _Text:
    """The block with some characters blanked, and its code (comments and strings blanked too)."""

    text: str
    code: str

    def blanked(self, start: int, end: int) -> "_Text":
        spaces = " " * (end - start)
        return _Text(self.text[:start] + spaces + self.text[end:], self.code[:start] + spaces + self.code[end:])

    def line_start(self, position: int) -> int:
        return self.text.rfind("\n", 0, position) + 1


def _plan_region(text: _Text, start: int, end: int) -> _Fragment:
    """`start` is a line start; the region's lines are split like a block of their own."""
    fragment = _Fragment()
    for piece in split_tactic_pieces(text.text[start:end]):
        shifted = TacticPiece(piece.text, piece.start + start, piece.end + start)
        fragment.extend(_flatten_piece(text, shifted) or _Fragment([shifted]))
    return fragment


def _flatten_piece(text: _Text, piece: TacticPiece) -> _Fragment | None:
    code = text.code[piece.start : piece.end]
    if code.startswith(_BULLETS) and code[1:2].isspace():
        return _flatten_bullet(text, piece)
    if _HAVE_PATTERN.match(code):
        return _flatten_have(text, piece)
    return None


def _flatten_bullet(text: _Text, piece: TacticPiece) -> _Fragment | None:
    body = text.blanked(piece.start, piece.start + 1)
    line_start = text.line_start(piece.start)
    line_end = _line_end(body.code, piece.start, piece.end)
    first_line = body.code[line_start:line_end]
    if not first_line.strip():
        return None
    column = len(first_line) - len(first_line.lstrip())
    if line_end < piece.end and not _lines_indented_at_least(body.code, line_end, piece.end, column):
        return None
    if _uses_goal_list_tactics(body.code[piece.start : piece.end]):
        return None
    inner = _plan_region(body, line_start, piece.end)
    if not inner.segments or not inner.tactics:
        return None
    inner.segments.append(FocusSegment(SegmentKind.BULLET, 0, len(inner.tactics) - 1))
    return inner


@dataclass(frozen=True)
class _HaveHeader:
    # The `:=` before the nested proof's `by`, and the end of that `by`.
    definition: int
    by_end: int


def _have_header(code: str, start: int, end: int) -> _HaveHeader | None:
    """`have name : type := by` or `obtain pattern : type := by` starting at `start`, without binders or holes."""
    keyword = _HAVE_PATTERN.match(code, start)
    assert keyword is not None
    position = keyword.end()
    is_have = code.startswith("have", start)
    colon = _depth_zero_colon(code, position, end)
    if colon is None:
        return None
    binder = code[position:colon].strip()
    if is_have and binder and not _IDENTIFIER_PATTERN.fullmatch(binder):
        return None
    if not is_have and not binder:
        return None
    definition = _depth_zero_definition(code, colon + 1, end)
    if definition is None:
        return None
    type_code = code[colon + 1 : definition]
    if not type_code.strip() or _HOLE_PATTERN.search(type_code):
        return None
    after = re.compile(r"\s*by(?![\w'!?])").match(code, definition + 2)
    if after is None:
        return None
    return _HaveHeader(definition, after.end())


def _flatten_have(text: _Text, piece: TacticPiece) -> _Fragment | None:
    header = _have_header(text.code, piece.start, piece.end)
    if header is None:
        return None
    line_start = text.line_start(piece.start)
    column = piece.start - line_start
    line_end = _line_end(text.code, header.by_end, piece.end)
    if text.code[header.by_end : line_end].strip():
        # The nested proof starts on the `by` line: only a proof on that line alone is unambiguous.
        if line_end != piece.end:
            return None
        region_text = text.blanked(line_start, header.by_end)
        region_start = line_start
    else:
        if line_end >= piece.end:
            return None
        region_text = text
        region_start = line_end + 1
        if not _lines_indented_at_least(text.code, line_end, piece.end, column + 1):
            return None
    if _uses_goal_list_tactics(region_text.code[region_start : piece.end]):
        return None
    nested = _plan_region(region_text, region_start, piece.end)
    if not nested.tactics:
        return None
    opener = TacticPiece(
        _relative_text(text.text[piece.start : header.definition].rstrip(), column), piece.start, header.by_end
    )
    fragment = _Fragment([opener])
    fragment.extend(nested)
    fragment.segments.append(FocusSegment(SegmentKind.HAVE, 1, len(fragment.tactics) - 1))
    return fragment


def _depth_zero_colon(code: str, start: int, end: int) -> int | None:
    depth = 0
    for index in range(start, end):
        character = code[index]
        if character in _OPENING_BRACKETS:
            depth += 1
        elif character in _CLOSING_BRACKETS:
            depth -= 1
        elif character == ":" and depth == 0:
            return None if code.startswith(":=", index) else index
    return None


def _depth_zero_definition(code: str, start: int, end: int) -> int | None:
    depth = 0
    for index in range(start, end):
        character = code[index]
        if character in _OPENING_BRACKETS:
            depth += 1
        elif character in _CLOSING_BRACKETS:
            depth -= 1
        elif depth == 0 and code.startswith(":=", index):
            return index
    return None


def _line_end(code: str, position: int, end: int) -> int:
    """The newline ending the line at `position`, or `end` when that line is the region's last."""
    newline = code.find("\n", position)
    return end if newline < 0 or newline > end else newline


def _lines_indented_at_least(code: str, newline: int, end: int, column: int) -> bool:
    """Every line with code after the newline at `newline` (up to `end`) starts at `column` or further right."""
    for line in code[newline + 1 : end].split("\n"):
        if line.strip() and len(line) - len(line.lstrip()) < column:
            return False
    return True


def _uses_goal_list_tactics(code: str) -> bool:
    return any(word in GOAL_LIST_TACTICS for word in _WORD_PATTERN.findall(code))


def _relative_text(text: str, column: int) -> str:
    first, *rest = text.split("\n")
    return "\n".join([first, *(line[min(column, len(line) - len(line.lstrip())) :] for line in rest)])


def no_op_without_goals(tactic: str) -> bool:
    """Succeeds without changing anything when no goals are left, as the rest of a closed nested proof does."""
    words = _WORD_PATTERN.findall(tactic)
    return bool(words) and (words[0] == "try" or (len(words) == 1 and words[0] in ("skip", "done")))


@dataclass(frozen=True)
class Proceed:
    next_index: int


@dataclass(frozen=True)
class Stop:
    message: str
    # The tactic's state is a valid prefix (the failure belongs to the next tactic); False: the tactic itself failed.
    keep_state: bool
    # Tactics up to here count as applied (no-ops skipped after a nested proof closed early included).
    applied_until: int


type SegmentVerdict = Proceed | Stop


def segment_verdict(plan: TacticPlan, goals_before: Mapping[int, int], index: int, goals_after: int) -> SegmentVerdict:
    """Whether tactic `index`, which left `goals_after` goals, kept to its nested proofs (innermost first)."""
    position = index
    containing = sorted(
        (segment for segment in plan.segments if segment.first <= index <= segment.last),
        key=lambda segment: -segment.first,
    )
    for segment in containing:
        base = goals_before[segment.first] - 1
        if goals_after < base:
            return Stop(OUTSIDE_MESSAGE, keep_state=False, applied_until=index)
        if position < segment.last:
            if goals_after > base:
                return Proceed(position + 1)
            remaining = plan.tactics[position + 1 : segment.last + 1]
            if not all(no_op_without_goals(tactic.text) for tactic in remaining):
                return Stop(NO_GOALS_MESSAGE, keep_state=True, applied_until=position + 1)
            position = segment.last
        elif goals_after > base:
            return Stop(UNSOLVED_MESSAGE, keep_state=True, applied_until=position + 1)
    return Proceed(position + 1)
