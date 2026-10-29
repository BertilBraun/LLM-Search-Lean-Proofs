"""Descriptive hypothesis names: which names are renamed, validated proposals, rule-based names, consistent renaming."""

import re
from collections import Counter
from collections.abc import Collection, Iterable, MutableMapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from lean_search.lean.identifiers import bound_names, tokenize
from lean_search.lean.text import LexicalKind, lex

_THEOREM_NAME = re.compile(r"(?:theorem|lemma)\s+[^\s(){}\[\]:]+")
_BINDER_OPENINGS = "([{⦃"
_OPENING_BRACKETS = "([{⟨⦃⟪"
_CLOSING_BRACKETS = ")]}⟩⦄⟫"
_VALID_NAME = re.compile(r"h[A-Za-z0-9]*(?:_[A-Za-z0-9]+)*")
_SUBSCRIPT_DIGITS = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789")
_PROPOSITION_MARKS = ("=", "≠", "<", "≤", ">", "≥", "∣", "∧", "∨", "¬", "↔", "∀", "∃", "∈", "∉", "⊆", "⊂", "≡")
_PREDICATE_WORDS = ("Prime", "Odd", "Even", "Injective", "Surjective", "Bijective", "Continuous", "Monotone")
# Relation symbols, longer spellings first, with the suffix they give a name.
_RELATIONS = (
    ("<=", "le"),
    (">=", "ge"),
    ("≠", "ne"),
    ("≤", "le"),
    ("≥", "ge"),
    ("∣", "dvd"),
    ("↔", "iff"),
    ("∉", "not_mem"),
    ("∈", "mem"),
    ("⊆", "subset"),
    ("≡", "modeq"),
    ("=", "eq"),
    ("<", "lt"),
    (">", "gt"),
)
_RELATION_SUFFIXES = dict(_RELATIONS)
# Arrows and definitions, which contain relation characters.
_NOT_RELATIONS = ("=>", ":=", "<;>", "<|>", "<|", "|>", "->", "<-", "==")
# The sign a comparison with zero states, by relation, with zero on the right and on the left.
_ZERO_ON_RIGHT = {"<": "neg", "≤": "nonpos", ">": "pos", "≥": "nonneg", "≠": "ne_zero", "=": "eq_zero"}
_ZERO_ON_LEFT = {"<": "pos", "≤": "nonneg", ">": "neg", "≥": "nonpos", "≠": "ne_zero", "=": "eq_zero"}
_ZERO_ON_RIGHT |= {"<=": "nonpos", ">=": "nonneg"}
_ZERO_ON_LEFT |= {"<=": "nonneg", ">=": "nonpos"}
_ZERO = re.compile(r"\(?\s*0\s*(?::[^)]*)?\)?")
KEYWORDS = frozenset({"have", "haveI", "hiding", "hygiene"})


@dataclass(frozen=True)
class NamingConfig:
    # Hypothesis names that are renamed: statement binders and `have` names matching this pattern. A binder whose name
    # has no digit (a bare `h`) is renamed only if its type looks like a proposition (`h : ℝ` is a variable).
    renamed_pattern: str = r"h[0-9₀-₉]*"
    max_name_length: int = 20


@dataclass(frozen=True)
class Binder:
    name: str
    type: str


@dataclass(frozen=True)
class Hypothesis:
    name: str
    type: str


@dataclass(frozen=True)
class NamingRequest:
    # The statement the hypotheses belong to, as shown to the namer.
    context: str
    hypotheses: tuple[Hypothesis, ...]
    # The statement's variables, from which rule-based names are built.
    variables: tuple[str, ...]
    # Names in use in the statement and its proof text: a new name must differ from all of them.
    taken: frozenset[str]


class NameSource(StrEnum):
    MODEL = "model"
    RULES = "rules"


class NameRejection(StrEnum):
    MISSING = "missing"
    NOT_A_NAME = "not_a_name"
    NUMBERED = "numbered"
    TOO_LONG = "too_long"
    RESERVED = "reserved"
    TAKEN = "taken"


@dataclass(frozen=True)
class NameChange:
    old: str
    new: str
    source: NameSource
    # Why the model's proposal was replaced by the rule-based name; None when it was used or no model was asked.
    rejection: NameRejection | None = None


class HypothesisNamer(Protocol):
    source: NameSource

    async def propose(self, requests: Sequence[NamingRequest]) -> list[tuple[str, ...]]:
        """One proposed name per hypothesis of each request ("" when there is none); validated by the caller."""
        ...


def code_of(text: str) -> str:
    return lex(text).masked(frozenset({LexicalKind.CODE}))


def collapsed(text: str) -> str:
    return " ".join(text.split())


def _matching_bracket(code: str, opening: int) -> int | None:
    depth = 0
    for index in range(opening, len(code)):
        if code[index] in _OPENING_BRACKETS:
            depth += 1
        elif code[index] in _CLOSING_BRACKETS:
            depth -= 1
            if depth == 0:
                return index
    return None


def _depth_zero_colon(code: str) -> int | None:
    depth = 0
    for index, character in enumerate(code):
        if character in _OPENING_BRACKETS:
            depth += 1
        elif character in _CLOSING_BRACKETS:
            depth -= 1
        elif character == ":" and depth == 0 and not code.startswith(":=", index):
            return index
    return None


def statement_binders(statement: str) -> tuple[Binder, ...]:
    """The bracketed binders between the theorem's name and its signature colon, one per name."""
    code = code_of(statement)
    name = _THEOREM_NAME.search(code)
    if name is None:
        return ()
    binders: list[Binder] = []
    position = name.end()
    while True:
        while position < len(code) and code[position].isspace():
            position += 1
        if position >= len(code) or code[position] not in _BINDER_OPENINGS:
            break
        closing = _matching_bracket(code, position)
        if closing is None:
            break
        group = code[position + 1 : closing]
        colon = _depth_zero_colon(group)
        if colon is not None:
            binders += [Binder(name, collapsed(group[colon + 1 :])) for name in group[:colon].split()]
        position = closing + 1
    return tuple(binders)


def looks_like_proposition(type_text: str) -> bool:
    return any(mark in type_text for mark in _PROPOSITION_MARKS) or any(word in type_text for word in _PREDICATE_WORDS)


def is_renamed(name: str, config: NamingConfig) -> bool:
    return re.fullmatch(config.renamed_pattern, name) is not None


def statement_hypotheses(statement: str, config: NamingConfig) -> tuple[Hypothesis, ...]:
    return tuple(
        Hypothesis(binder.name, binder.type)
        for binder in statement_binders(statement)
        if is_renamed(binder.name, config)
        and (any(character.isdigit() for character in binder.name) or looks_like_proposition(binder.type))
    )


def have_hypotheses(tactics: Sequence[str], config: NamingConfig) -> tuple[Hypothesis, ...]:
    """`have name : type` in the tactics (anywhere, nested ones too) whose name is renamed, in order."""
    found: list[Hypothesis] = []
    for tactic in tactics:
        code = code_of(tactic)
        tokens = tokenize(code)
        for position, token in enumerate(tokens[:-2]):
            name, colon = tokens[position + 1], tokens[position + 2]
            if token.text != "have" or not name.is_identifier or colon.text != ":" or not is_renamed(name.text, config):
                continue
            end = next(
                (
                    later.start
                    for later in tokens[position + 3 :]
                    if (later.depth == colon.depth and later.text == ":=")
                    or (later.line_start and later.column <= token.column)
                ),
                len(code),
            )
            found.append(Hypothesis(name.text, collapsed(code[colon.start + 1 : end])))
    return tuple(found)


def identifiers_in(texts: Iterable[str]) -> frozenset[str]:
    """Every identifier token of the texts and the first component of each dotted one."""
    names: set[str] = set()
    for text in texts:
        for token in tokenize(code_of(text)):
            if token.is_identifier:
                names.add(token.text)
                names.add(token.text.split(".")[0])
    return frozenset(names)


def binding_counts(statement: str, tactics: Sequence[str]) -> Counter[str]:
    """How many binders (statement binders, then at most one per tactic) may bind each name."""
    counts = Counter(binder.name for binder in statement_binders(statement))
    for tactic in tactics:
        counts.update(bound_names(tokenize(code_of(tactic))))
    return counts


def renamed_text(text: str, changes: Sequence[NameChange]) -> str:
    """Every occurrence of an old name as a whole identifier (not a field after `.`) replaced by its new name."""
    if not changes:
        return text
    mapping = {change.old: change.new for change in changes}
    alternatives = "|".join(re.escape(old) for old in sorted(mapping, key=len, reverse=True))
    pattern = re.compile(rf"(?<![\w'!?.])(?:{alternatives})(?![\w'!?])")
    return pattern.sub(lambda match: mapping[match.group(0)], text)


def name_rejection(
    name: str, used: Collection[str], reserved: frozenset[str], config: NamingConfig
) -> NameRejection | None:
    if not name:
        return NameRejection.MISSING
    if _VALID_NAME.fullmatch(name) is None:
        return NameRejection.NOT_A_NAME
    if is_renamed(name, config):
        return NameRejection.NUMBERED
    if len(name) > config.max_name_length:
        return NameRejection.TOO_LONG
    if name in KEYWORDS or name in reserved:
        return NameRejection.RESERVED
    if name in used:
        return NameRejection.TAKEN
    return None


def unique_name(base: str, used: set[str], reserved: frozenset[str]) -> str:
    name = base
    suffix = 2
    while name in used or name in reserved or name in KEYWORDS:
        name = f"{base}_{suffix}"
        suffix += 1
    return name


def _split_depth_zero(code: str, separator: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    start = 0
    for index, character in enumerate(code):
        if character in _OPENING_BRACKETS:
            depth += 1
        elif character in _CLOSING_BRACKETS:
            depth -= 1
        elif depth == 0 and code.startswith(separator, index):
            parts.append(code[start:index])
            start = index + len(separator)
    parts.append(code[start:])
    return [part.strip() for part in parts]


def _without_quantifiers(code: str) -> str:
    """The body under leading `∀ …,`, `∃ …,` and `¬`, and the conclusion of an implication."""
    code = code.strip()
    while True:
        if code.startswith(("∀", "∃")):
            parts = _split_depth_zero(code, ",")
            if len(parts) == 1:
                return code
            code = ",".join(parts[1:]).strip()
        else:
            break
    return _split_depth_zero(code, "→")[-1]


def _relation(code: str) -> tuple[str, str, str] | None:
    """The first relation at bracket depth zero: (left side, symbol, right side)."""
    depth = 0
    for index, character in enumerate(code):
        if character in _OPENING_BRACKETS:
            depth += 1
        elif character in _CLOSING_BRACKETS:
            depth -= 1
        elif depth == 0 and not any(code.startswith(arrow, index - 1) for arrow in _NOT_RELATIONS):
            if any(code.startswith(arrow, index) for arrow in _NOT_RELATIONS):
                continue
            for symbol, _ in _RELATIONS:
                if code.startswith(symbol, index):
                    return code[:index].strip(), symbol, code[index + len(symbol) :].strip()
    return None


def _suffix(code: str) -> str:
    """What a fact says, as a name suffix (`pos`, `ne_zero`, `le`, `prime`, …); "" for an equation."""
    if code.startswith("¬"):
        inner = _suffix(code[1:].strip())
        return f"not_{inner}" if inner else "not"
    conjuncts = _split_depth_zero(code, "∧")
    if len(conjuncts) > 1:
        suffixes = {_suffix(part) for part in conjuncts}
        return suffixes.pop() if len(suffixes) == 1 else "and"
    if len(_split_depth_zero(code, "∨")) > 1:
        return "or"
    relation = _relation(code)
    if relation is None:
        words = [word for word in re.findall(r"[A-Za-z][A-Za-z_.]*", code) if word[0].isupper() or "." in word]
        return words[0].split(".")[-1].lower() if words else ""
    left, symbol, right = relation
    if _ZERO.fullmatch(right):
        return _ZERO_ON_RIGHT.get(symbol, _RELATION_SUFFIXES[symbol])
    if _ZERO.fullmatch(left):
        return _ZERO_ON_LEFT.get(symbol, _RELATION_SUFFIXES[symbol])
    return "" if symbol == "=" else _RELATION_SUFFIXES[symbol]


def _ascii_variable(name: str) -> str | None:
    transliterated = name.translate(_SUBSCRIPT_DIGITS)
    return transliterated if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", transliterated) else None


def _subject(code: str, variables: Sequence[str]) -> str:
    """The variables a fact is about: `xyz` for single letters, `a0` for a sequence term `a 0`, else the first."""
    relation = _relation(_split_depth_zero(code, "∧")[0])
    if relation is not None:
        term = re.fullmatch(r"(\S+)\s+(\d+)", relation[0])
        if term is not None and term.group(1) in variables and (name := _ascii_variable(term.group(1))):
            return name + term.group(2)
    mentioned = dict.fromkeys(token.text for token in tokenize(code) if token.is_identifier and token.text in variables)
    names = [converted for name in mentioned if (converted := _ascii_variable(name)) is not None]
    if not names:
        return ""
    if all(len(name) == 1 for name in names[:3]):
        return "".join(names[:3])
    return names[0]


def rule_based_name(type_text: str, variables: Sequence[str], config: NamingConfig) -> str:
    """A Mathlib-style name from the hypothesis type: `hx_pos` for `0 < x`, `habc` for `a + b + c = 1`."""
    body = _without_quantifiers(type_text)
    suffix = re.sub(r"[^a-z0-9_]", "", _suffix(body).lower()).strip("_")
    subject = _subject(body, variables)
    if not subject:
        suffix = suffix or "fact"
    name = f"h{subject}_{suffix}" if suffix else f"h{subject}"
    return name[: config.max_name_length].rstrip("_")


class RuleBasedNamer:
    """Deterministic names from the hypothesis types; also the fallback for rejected model proposals."""

    source = NameSource.RULES

    def __init__(self, config: NamingConfig) -> None:
        self.config = config

    async def propose(self, requests: Sequence[NamingRequest]) -> list[tuple[str, ...]]:
        return [
            tuple(rule_based_name(hypothesis.type, request.variables, self.config) for hypothesis in request.hypotheses)
            for request in requests
        ]


def choose_names(
    request: NamingRequest,
    proposed: Sequence[str],
    source: NameSource,
    config: NamingConfig,
    reserved: frozenset[str] = frozenset(),
) -> tuple[NameChange, ...]:
    """The proposals that pass validation; the others replaced by unique rule-based names."""
    used = set(request.taken)
    changes: list[NameChange] = []
    for hypothesis, name in zip(request.hypotheses, proposed, strict=True):
        rejection = name_rejection(name, used, reserved, config)
        if rejection is None:
            changes.append(NameChange(hypothesis.name, name, source))
        else:
            fallback = unique_name(rule_based_name(hypothesis.type, request.variables, config), used, reserved)
            model_rejection = rejection if source is NameSource.MODEL else None
            changes.append(NameChange(hypothesis.name, fallback, NameSource.RULES, model_rejection))
        used.add(changes[-1].new)
    return tuple(changes)


async def assign_names(
    requests: Sequence[NamingRequest],
    namer: HypothesisNamer,
    config: NamingConfig,
    reserved: frozenset[str] = frozenset(),
) -> list[tuple[NameChange, ...]]:
    proposals = await namer.propose(requests) if requests else []
    return [
        choose_names(request, proposed, namer.source, config, reserved)
        for request, proposed in zip(requests, proposals, strict=True)
    ]


def statement_request(statement: str, config: NamingConfig) -> NamingRequest | None:
    hypotheses = statement_hypotheses(statement, config)
    if not hypotheses:
        return None
    renamed = {hypothesis.name for hypothesis in hypotheses}
    variables = tuple(binder.name for binder in statement_binders(statement) if binder.name not in renamed)
    return NamingRequest(statement, hypotheses, variables, identifiers_in([statement]))


class RenamingStatus(StrEnum):
    RENAMED = "renamed"
    NOTHING_TO_RENAME = "nothing_to_rename"
    # A statement name chosen once per statement is already used in this proof text.
    NAME_CONFLICT = "name_conflict"


@dataclass(frozen=True)
class NamingSubject:
    statement: str
    # The proof text whose `have` names are renamed with the statement's (in order).
    tactics: tuple[str, ...]


@dataclass(frozen=True)
class Renaming:
    status: RenamingStatus
    statement_changes: tuple[NameChange, ...] = ()
    have_changes: tuple[NameChange, ...] = ()

    @property
    def changes(self) -> tuple[NameChange, ...]:
        return self.statement_changes + self.have_changes


type StatementNames = MutableMapping[str, tuple[NameChange, ...]]


async def plan_renamings(
    subjects: Sequence[NamingSubject],
    namer: HypothesisNamer,
    config: NamingConfig,
    reserved: frozenset[str] = frozenset(),
    statement_names: StatementNames | None = None,
) -> list[Renaming]:
    """Statement names once per statement (shared by its proofs, as at search time), then each text's `have` names."""
    cache: StatementNames = {} if statement_names is None else statement_names
    pending = {
        statement: request
        for statement in dict.fromkeys(subject.statement for subject in subjects)
        if statement not in cache and (request := statement_request(statement, config)) is not None
    }
    assigned = await assign_names(list(pending.values()), namer, config, reserved)
    cache.update(zip(pending, assigned, strict=True))
    verdicts: list[Renaming | NamingRequest | None] = [
        _renaming_verdict(subject, cache.get(subject.statement, ()), config) for subject in subjects
    ]
    have_requests = [verdict for verdict in verdicts if isinstance(verdict, NamingRequest)]
    have_names = iter(await assign_names(have_requests, namer, config, reserved))
    results: list[Renaming] = []
    for subject, verdict in zip(subjects, verdicts, strict=True):
        statement_changes = cache.get(subject.statement, ())
        match verdict:
            case Renaming():
                results.append(verdict)
            case NamingRequest():
                results.append(Renaming(RenamingStatus.RENAMED, statement_changes, next(have_names)))
            case None:
                results.append(Renaming(RenamingStatus.RENAMED, statement_changes))
    return results


def _renaming_verdict(
    subject: NamingSubject, statement_changes: tuple[NameChange, ...], config: NamingConfig
) -> Renaming | NamingRequest | None:
    """A final renaming, the request for the text's `have` names, or None when only the statement's are renamed."""
    # A fresh name replacing every occurrence keeps the meaning whatever the scopes; a `have` name bound twice
    # (reused in another branch, rebound by a pattern) would name two facts by one description, so it stays numbered.
    old_statement_names = {change.old for change in statement_changes}
    counts = binding_counts(subject.statement, subject.tactics)
    haves = tuple(
        hypothesis
        for hypothesis in have_hypotheses(subject.tactics, config)
        if counts[hypothesis.name] == 1 and hypothesis.name not in old_statement_names
    )
    used = identifiers_in([subject.statement, *subject.tactics])
    if not statement_changes and not haves:
        return Renaming(RenamingStatus.NOTHING_TO_RENAME)
    if any(change.new in used for change in statement_changes):
        return Renaming(RenamingStatus.NAME_CONFLICT)
    if not haves:
        return None
    statement_variables = [
        binder.name for binder in statement_binders(subject.statement) if binder.name not in old_statement_names
    ]
    # Variables the proof introduces itself (`intro x y`) count too.
    proof_variables = sorted(name for name in identifiers_in(subject.tactics) if re.fullmatch(r"[a-z]", name))
    variables = tuple(dict.fromkeys([*statement_variables, *proof_variables]))
    context = renamed_text(subject.statement, statement_changes)
    return NamingRequest(context, haves, variables, used | {change.new for change in statement_changes})
