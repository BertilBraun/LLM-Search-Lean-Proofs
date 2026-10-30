"""Names a tactic block refers to, checked against the pinned environment and the goal's context before Lean runs."""

import asyncio
import difflib
import gzip
import hashlib
import os
import re
import tempfile
import threading
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.lean.hypotheses import INACCESSIBLE_MARK, hypothesis_names
from lean_search.lean.plans import Rejection
from lean_search.lean.repl import LeanRepl
from lean_search.lean.text import LexicalKind, lex, split_header

FORMAT_VERSION = "1"
# `Nat.card_fin` is no field of the type `Nat`; after any other constant, `name.field` may be field notation.
TYPE_KINDS = frozenset({"inductive"})
# Equation lemmas and the like are created on first use, so they are missing from the exported constants.
RESERVED_SUFFIX = re.compile(r"eq_\d+|eq_def|def|induct|mutual_induct|injEq|inj|sizeOf_spec")
ALWAYS_KNOWN = frozenset({"this", "self"})
# Words of tactic syntax that are not tokens of the parser (non-reserved symbols) and option fields.
NON_RESERVED_WORDS = frozenset(
    {
        "only",
        "says",
        "arith",
        "contextual",
        "discharger",
        "config",
        "using",
        "generalizing",
        "with",
        "at",
        "in",
        "to",
        "from",
        "add",
        "safe",
        "norm",
        "forward",
        "destruct",
        "erase",
        "apply",
        "constructors",
        "cases",
        "rule_sets",
        "simp_config",
        "using_whnf",
        "unfold",
        "ground",
        "ring_nf",
        "field_simp",
        "decide",
        "zeta",
        "beta",
        "eta",
        "proj",
        "iota",
        "maxSteps",
        "maxDischargeDepth",
        "failIfUnchanged",
        "singlePass",
        "zetaDelta",
        "lhs",
        "rhs",
        "left",
        "right",
    }
)
# Constructs whose binders or name resolution the rules below do not model.
UNCERTAIN_WORDS = frozenset(
    {
        "conv",
        "conv_lhs",
        "conv_rhs",
        "enter",
        "macro",
        "macro_rules",
        "syntax",
        "notation",
        "infix",
        "infixl",
        "infixr",
        "prefix",
        "postfix",
        "local",
        "scoped",
        "variable",
        "namespace",
        "section",
        "where",
        "elab",
        "deriving",
        "mutual",
        "termination_by",
        "decreasing_by",
        "export",
        "set_option",
        "open",
        "def",
        "theorem",
        "lemma",
        "instance",
        "structure",
        "class",
        "inductive",
        "abbrev",
        "universe",
    }
)
# Combinators that catch the errors of the tactics they run.
RECOVERING_WORDS = frozenset(
    {
        "try",
        "first",
        "any_goals",
        "all_goals",
        "repeat",
        "repeat'",
        "iterate",
        "<|>",
        "fail_if_success",
        "success_if_fail",
    }
)
# Binders up to the first `=>`, `↦` or `,` at their depth.
TERM_BINDERS = frozenset(
    {"fun", "λ", "∀", "∃", "∃!", "Π", "Σ", "Σ'", "∑", "∏", "⋃", "⋂", "⨆", "⨅", "∫", "∮", "∀ᶠ", "∃ᶠ", "∐", "assume"}
)
# Names after these words up to the end of the tactic's line, `=>`, `:=`, `:`, `using`, `;` or `<;>`.
TACTIC_BINDERS = frozenset(
    {
        "intro",
        "intros",
        "rintro",
        "rintros",
        "introv",
        "rename_i",
        "rename",
        "rename'",
        "ext",
        "ext1",
        "funext",
        "next",
        "case",
        "case'",
        "choose",
        "choose!",
        "with",
        "obtain",
        "set",
        "set!",
        "let",
        "have",
        "haveI",
        "letI",
        "replace",
        "suffices",
        "by_cases",
        "by_contra",
        "by_contra!",
        "by_contra'",
        "wlog",
        "generalize",
    }
)
# `generalize h : e = x` binds names on both sides of its type.
WHOLE_LINE_BINDERS = frozenset({"generalize"})
# Tactics that name a hypothesis by default.
DEFAULT_HYPOTHESIS_NAMES = {"by_cases": "h"}
_BINDER_ENDS = frozenset({"=>", "↦", ":=", ":", "using", ";", "<;>"})
_TERM_BINDER_ENDS = frozenset({"=>", "↦", ","})
_OPENING_BRACKETS = "([{⟨⦃⟪"
_CLOSING_BRACKETS = ")]}⟩⦄⟫"
_NUMBER = re.compile(r"0[xX][0-9a-fA-F]+|0[bB][01]+|0[oO][0-7]+|[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_SYMBOLS = ("<;>", "<|>", ":=", "=>", "::", "←", "↦", "..", "//")
_DECLARATION = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec)\s+)*"
    r"(?:theorem|lemma|def|abbrev|instance|axiom|opaque)\s+([^\s(){}\[\]:]+)",
    re.MULTILINE,
)
_HEADER_UNCERTAIN = re.compile(
    r"\b(?:namespace|variable|notation|infixl?|infixr|prefix|postfix|macro|macro_rules|syntax|elab|elab_rules|"
    r"export|local|mutual|structure|class|inductive)\b"
)
_OPEN_LINE = re.compile(r"^\s*open\s+(?P<rest>[^\n]*)$", re.MULTILINE)
_THEOREM_NAME = re.compile(r"^\s*(?:theorem|lemma)\s+([^\s(){}\[\]:]+)", re.MULTILINE)


def is_letter_like(character: str) -> bool:
    code = ord(character)
    return (
        (0x3B1 <= code <= 0x3C9 and code != 0x3BB)
        or (0x391 <= code <= 0x3A9 and code not in (0x3A0, 0x3A3))
        or 0x3CA <= code <= 0x3FB
        or 0x1F00 <= code <= 0x1FFE
        or 0x2100 <= code <= 0x214F
        or 0x1D49C <= code <= 0x1D59F
    )


def is_subscript(character: str) -> bool:
    code = ord(character)
    return 0x2080 <= code <= 0x2089 or 0x2090 <= code <= 0x209C or 0x1D62 <= code <= 0x1D6A or code == 0x2C7C


def is_identifier_start(character: str) -> bool:
    return (character.isascii() and character.isalpha()) or character == "_" or is_letter_like(character)


def is_identifier_rest(character: str) -> bool:
    return (
        is_identifier_start(character)
        or (character.isascii() and character.isdigit())
        or character in "'!?"
        or is_subscript(character)
    )


@dataclass(frozen=True)
class Token:
    text: str
    start: int
    is_identifier: bool
    # Brackets open around the token (a bracket itself counts as outside).
    depth: int
    column: int
    # The first token of its line, and that first token's column.
    line_start: bool
    indentation: int


def tokenize(code: str) -> list[Token]:
    """Lean's identifiers (dotted names joined), numbers and symbols of code whose comments and strings are blank."""
    tokens: list[Token] = []
    depth = 0
    index = 0
    line_begin = 0
    indentation = 0
    at_line_start = True
    while index < len(code):
        character = code[index]
        if character == "\n":
            at_line_start = True
            line_begin = index + 1
            index += 1
            continue
        if character.isspace():
            index += 1
            continue
        column = index - line_begin
        if at_line_start:
            indentation = column
        if is_identifier_start(character):
            end = index + 1
            while end < len(code):
                if is_identifier_rest(code[end]):
                    end += 1
                elif code[end] == "." and end + 1 < len(code) and is_identifier_start(code[end + 1]):
                    end += 2
                else:
                    break
            tokens.append(Token(code[index:end], index, True, depth, column, at_line_start, indentation))
        elif number := _NUMBER.match(code, index):
            end = number.end()
            tokens.append(Token(code[index:end], index, False, depth, column, at_line_start, indentation))
        else:
            symbol = next((symbol for symbol in _SYMBOLS if code.startswith(symbol, index)), character)
            end = index + len(symbol)
            if symbol in _CLOSING_BRACKETS:
                depth = max(depth - 1, 0)
            tokens.append(Token(symbol, index, False, depth, column, at_line_start, indentation))
            if symbol in _OPENING_BRACKETS:
                depth += 1
        at_line_start = False
        index = end
    return tokens


@dataclass(frozen=True)
class EnvironmentNames:
    """The names of an imported environment: constants (and aliases), the inductive types, and syntax keywords."""

    imports: str
    constants: frozenset[str]
    types: frozenset[str]
    keywords: frozenset[str]


def parse_environment_names(imports: str, lines: Iterable[str]) -> EnvironmentNames:
    constants: set[str] = set()
    types: set[str] = set()
    keywords: set[str] = set()
    for line in lines:
        fields = line.rstrip("\n").split("\t")
        match fields:
            case ["constant", kind, name]:
                constants.add(name)
                if kind in TYPE_KINDS:
                    types.add(name)
            case ["alias", name]:
                constants.add(name)
            case ["token", token] | ["leading", _, token] | ["trailing", _, token]:
                keywords.add(token)
            case _:
                pass
    return EnvironmentNames(imports, frozenset(constants), frozenset(types), frozenset(keywords))


EXPORT_COMMAND = """open Lean Elab Command in
#eval show CommandElabM Unit from do
  let env ← getEnv
  let handle ← IO.FS.Handle.mk {path} IO.FS.Mode.write
  for (name, info) in env.constants.toList do
    unless name.isInternal || name.hasMacroScopes do
      let kind := match info with
        | .thmInfo _ => "theorem"
        | .defnInfo _ => "def"
        | .axiomInfo _ => "axiom"
        | .opaqueInfo _ => "opaque"
        | .quotInfo _ => "quot"
        | .inductInfo _ => "inductive"
        | .ctorInfo _ => "constructor"
        | .recInfo _ => "recursor"
      handle.putStrLn s!"constant\\t{kind}\\t{name}"
  for (aliasName, _) in (aliasExtension.getState env).toList do
    handle.putStrLn s!"alias\\t{aliasName}"
  for token in (Parser.getTokenTable env).values do
    handle.putStrLn s!"token\\t{token}"
  for (_, entries) in (Parser.parserExtension.ext.getState env).scopedEntries.map.toList do
    for entry in entries.toList do
      match entry with
      | .token token => handle.putStrLn s!"token\\t{token}"
      | _ => pure ()
  for (category, parserCategory) in (Parser.parserExtension.getState env).categories.toList do
    for (key, _) in parserCategory.tables.leadingTable.toList do
      handle.putStrLn s!"leading\\t{category}\\t{key}"
    for (key, _) in parserCategory.tables.trailingTable.toList do
      handle.putStrLn s!"trailing\\t{category}\\t{key}"
"""


def export_command(path: Path) -> str:
    return EXPORT_COMMAND.replace("{path}", '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"')


def environment_names_path(imports: str, project_directory: Path, directory: Path | None = None) -> Path:
    """One cache file per import set and pinned Lean project (toolchain and package manifest)."""
    digest = hashlib.sha256(FORMAT_VERSION.encode())
    digest.update(imports.encode())
    for pin in ("lean-toolchain", "lake-manifest.json"):
        pin_path = project_directory / pin
        digest.update(pin_path.read_bytes() if pin_path.exists() else b"")
    directory = directory or Path(os.environ.get("LEAN_SEARCH_DATA") or Path.home() / ".cache" / "lean_search") / "lean"
    return directory / f"environment_names_{digest.hexdigest()[:16]}.tsv.gz"


def write_environment_names(exported: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(f".{os.getpid()}.tmp")
    with exported.open("rb") as source, gzip.open(temporary, "wb") as target:
        target.write(source.read())
    temporary.replace(destination)


def read_environment_names(imports: str, path: Path) -> EnvironmentNames:
    with gzip.open(path, "rt", encoding="utf-8") as lines:
        return parse_environment_names(imports, lines)


_loaded_names: dict[Path, EnvironmentNames] = {}
_export_locks: dict[Path, asyncio.Lock] = {}


async def environment_names(repl: LeanRepl, header: str, directory: Path | None = None) -> EnvironmentNames:
    """The names of the header's imports, exported once through the REPL and cached on disk and in memory."""
    imports = split_header(header).imports
    path = environment_names_path(imports, repl.config.project_directory, directory)
    async with _export_locks.setdefault(path, asyncio.Lock()):
        if path not in _loaded_names:
            if not path.exists():
                await _export(repl, header, path)
            _loaded_names[path] = await asyncio.to_thread(read_environment_names, imports, path)
    return _loaded_names[path]


async def _export(repl: LeanRepl, header: str, path: Path) -> None:
    with tempfile.TemporaryDirectory() as directory:
        exported = Path(directory) / "names.tsv"
        errors = await repl.export_environment_names(header, export_command(exported))
        if errors or not exported.exists():
            raise RuntimeError(f"Exporting the environment's names failed: {errors}")
        await asyncio.to_thread(write_environment_names, exported, path)


@dataclass(frozen=True)
class NameScope:
    """What the header and the statement add to name resolution."""

    namespaces: tuple[str, ...]
    declared: frozenset[str]


def name_scope(header: str, statement: str) -> NameScope | None:
    """None when the header changes names or syntax in ways the checker does not model."""
    commands = lex(split_header(header).commands)
    if not commands.exact:
        return None
    code = commands.masked(frozenset({LexicalKind.CODE}))
    if _HEADER_UNCERTAIN.search(code):
        return None
    namespaces = [""]
    for match in _OPEN_LINE.finditer(code):
        words = match["rest"].split()
        if any(not all(is_identifier_rest(c) or c == "." for c in word) for word in words):
            return None
        if words[:1] == ["scoped"]:
            continue
        if any(word in ("hiding", "renaming", "in") for word in words):
            return None
        namespaces.extend(words)
    declared = frozenset(match.group(1) for match in _DECLARATION.finditer(code))
    theorem = _THEOREM_NAME.search(statement)
    if theorem is not None:
        components = theorem.group(1).split(".")[:-1]
        namespaces.extend(".".join(components[:length]) for length in range(1, len(components) + 1))
    return NameScope(tuple(dict.fromkeys(namespaces)), declared)


@dataclass(frozen=True)
class UnknownNames:
    tactic_index: int
    names: tuple[str, ...]

    @property
    def rejection(self) -> Rejection:
        quoted = ", ".join(f"'{name}'" for name in self.names)
        return Rejection(self.tactic_index, f"{REJECTION_PREFIX}{quoted}{REJECTION_SUFFIX}", self.names)


class IdentifierChecker:
    def __init__(self, names: EnvironmentNames) -> None:
        self.names = names

    def first_unknown(self, tactics: Sequence[str], goals: Sequence[str], scope: NameScope) -> UnknownNames | None:
        """The first tactic that refers to a name that cannot exist there, or None (also when unsure)."""
        local = {name for goal in goals for name in hypothesis_names(goal) if INACCESSIBLE_MARK not in name}
        bound: set[str] = set()
        namespaces = list(scope.namespaces)
        for index, tactic in enumerate(tactics):
            lexed = lex(tactic)
            if not lexed.exact or INACCESSIBLE_MARK in tactic:
                return None
            tokens = tokenize(lexed.masked(frozenset({LexicalKind.CODE})))
            if any(token.is_identifier and token.text in UNCERTAIN_WORDS for token in tokens):
                return None
            bound |= bound_names(tokens)
            # Errors under `try` and its relatives are caught, so a wrong name there need not fail the tactic.
            if any(token.text in RECOVERING_WORDS for token in tokens):
                continue
            # After `<;>` a tactic runs only on the goals the one before it left, which may be none.
            checked = next((position for position, token in enumerate(tokens) if token.text == "<;>"), len(tokens))
            unknown = tuple(
                dict.fromkeys(
                    token.text
                    for position, token in enumerate(tokens[:checked])
                    if is_reference(tokens, position, self.names.keywords)
                    and not self._resolves(token.text, local | bound, namespaces, scope.declared)
                )
            )
            if unknown:
                return UnknownNames(index, unknown)
        return None

    def _resolves(self, name: str, local: set[str], namespaces: Sequence[str], declared: frozenset[str]) -> bool:
        if name in ALWAYS_KNOWN or name in self.names.keywords or name in NON_RESERVED_WORDS:
            return True
        name = name.removeprefix("_root_.")
        components = name.split(".")
        if name in local or components[0] in local or components[0] in ALWAYS_KNOWN:
            return True
        for length in range(len(components), 0, -1):
            prefix = ".".join(components[:length])
            constant = self._constant(prefix, namespaces, declared)
            if constant is None:
                continue
            rest = components[length:]
            if not rest or constant not in self.names.types or constant in declared:
                return True
            if len(rest) == 1 and RESERVED_SUFFIX.fullmatch(rest[0]):
                return True
        return False

    def _constant(self, name: str, namespaces: Sequence[str], declared: frozenset[str]) -> str | None:
        for namespace in namespaces:
            candidate = f"{namespace}.{name}" if namespace else name
            if candidate in self.names.constants or candidate in declared:
                return candidate
        return None


def is_reference(tokens: Sequence[Token], position: int, keywords: frozenset[str] = frozenset()) -> bool:
    """An identifier that must name something that exists: not a hole, field, metavariable or binder before `:`."""
    token = tokens[position]
    if not token.is_identifier or (token.text.startswith("_") and not token.text.startswith("_root_.")):
        return False
    previous = tokens[position - 1] if position > 0 else None
    # A field or metavariable name, or the end of a symbol token such as `[MOD`.
    if (
        previous is not None
        and previous.start + len(previous.text) == token.start
        and (previous.text in (".", "?") or previous.text + token.text in keywords)
    ):
        return False
    following = tokens[position + 1] if position + 1 < len(tokens) else None
    return following is None or following.text not in (":=", ":")


def bound_names(tokens: Sequence[Token]) -> set[str]:
    """Every name in a position that may bind it (an over-approximation, ignoring scopes)."""
    bound: set[str] = set()
    alternatives: set[int] = set()
    for position, token in enumerate(tokens):
        if token.text == "|" and _starts_alternative(tokens, position, alternatives):
            alternatives.add(position)
        if token.text in TERM_BINDERS:
            bound |= _names_until(tokens, position, _TERM_BINDER_ENDS, line_bound=False)
        elif token.is_identifier and token.text in TACTIC_BINDERS:
            ends = frozenset({";", "<;>"}) if token.text in WHOLE_LINE_BINDERS else _BINDER_ENDS
            bound |= _names_until(tokens, position, ends, line_bound=True)
            if token.text in DEFAULT_HYPOTHESIS_NAMES:
                bound.add(DEFAULT_HYPOTHESIS_NAMES[token.text])
        elif position in alternatives and _arrow_follows(tokens, position):
            bound |= _names_until(tokens, position, frozenset({"=>"}), line_bound=True)
        elif token.text == "{" and _set_builder(tokens, position):
            bound |= _names_until(tokens, position, frozenset({"|", "//"}), line_bound=False)
        elif token.is_identifier and position + 1 < len(tokens) and tokens[position + 1].text in (":=", ":"):
            bound.add(token.text)
    return bound


def _names_until(tokens: Sequence[Token], binder: int, ends: frozenset[str], *, line_bound: bool) -> set[str]:
    """Identifiers after the binder token up to an end token at its depth (or, `line_bound`, its next line)."""
    opener = tokens[binder]
    depth = opener.depth + (opener.text == "{")
    names: set[str] = set()
    for token in tokens[binder + 1 :]:
        if token.depth < depth or (token.depth == depth and token.text in ends):
            break
        if line_bound and token.line_start and token.column <= opener.indentation:
            break
        if token.is_identifier:
            names.add(token.text)
    return names


def _starts_alternative(tokens: Sequence[Token], position: int, alternatives: set[int]) -> bool:
    """A `|` that opens a match alternative, not an absolute value or an `rcases` pattern bar."""
    bar = tokens[position]
    if bar.line_start or (position > 0 and tokens[position - 1].text in ("with", "fun", "function")):
        return True
    for earlier in range(position - 1, -1, -1):
        if earlier in alternatives and tokens[earlier].depth == bar.depth:
            return True
        if tokens[earlier].line_start:
            return False
    return False


def _arrow_follows(tokens: Sequence[Token], position: int) -> bool:
    bar = tokens[position]
    for token in tokens[position + 1 :]:
        if token.depth < bar.depth or (token.line_start and token.column <= bar.indentation):
            return False
        if token.depth == bar.depth and token.text == "=>":
            return True
    return False


def _set_builder(tokens: Sequence[Token], position: int) -> bool:
    depth = tokens[position].depth + 1
    for token in tokens[position + 1 :]:
        if token.depth < depth:
            return False
        if token.depth == depth and token.text in ("|", "//"):
            return True
    return False


# A name may end in primes, so its closing quote is the one before a space or the end.
LEAN_UNKNOWN_NAME = re.compile(r"unknown (?:identifier|constant) '(.+?)'(?=\s|$)")
ROOT_PREFIX = "_root_."
REJECTION_PREFIX = "unknown identifier "
REJECTION_SUFFIX = " (checked before running Lean)"


@dataclass(frozen=True)
class NameRepair:
    original: str
    replacement: str


@dataclass(frozen=True)
class RepairedBlock:
    text: str
    repairs: tuple[NameRepair, ...]


def lean_unknown_names(message: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(LEAN_UNKNOWN_NAME.findall(message)))


def unknown_names(message: str) -> tuple[str, ...]:
    """The unknown names a recorded failure names: the identifier check's (`UnknownNames.rejection`) or Lean's."""
    if message.endswith(REJECTION_SUFFIX):
        quoted = message.removeprefix(REJECTION_PREFIX).removesuffix(REJECTION_SUFFIX)
        return tuple(quoted[1:-1].split("', '"))
    return lean_unknown_names(message)


def namespace_members(names: EnvironmentNames) -> dict[str, tuple[str, ...]]:
    """Each namespace's constants by their last component."""
    members: dict[str, list[str]] = {}
    for constant in names.constants:
        namespace, _, member = constant.rpartition(".")
        if namespace:
            members.setdefault(namespace, []).append(member)
    return {namespace: tuple(sorted(found)) for namespace, found in members.items()}


class NameRepairer:
    """Unknown dotted names replaced by the most similar constant of the namespace they are written in. Thread-safe:
    the searches share one per environment (`shared_name_repairer`) and repair in worker threads."""

    def __init__(self, members: Mapping[str, Sequence[str]], min_similarity: float) -> None:
        self.members = members
        self.min_similarity = min_similarity
        self._replacements: dict[tuple[str, tuple[str, ...]], str | None] = {}
        self._lock = threading.Lock()

    def replacement(self, name: str, namespaces: Sequence[str]) -> str | None:
        key = (name, tuple(namespaces))
        with self._lock:
            if key in self._replacements:
                return self._replacements[key]
        found = self._replacement(name, namespaces)
        with self._lock:
            self._replacements[key] = found
        return found

    def _replacement(self, name: str, namespaces: Sequence[str]) -> str | None:
        # Names without a namespace are mostly hypotheses, whose near neighbours (h₁ for h₂) mean something else.
        root = name.startswith(ROOT_PREFIX)
        components = name.removeprefix(ROOT_PREFIX).split(".")
        # The longest written prefix that is a namespace decides; a shorter one would only rename a namespace.
        for length in range(len(components) - 1, 0, -1):
            written = ".".join(components[:length])
            keys = (
                [written] if root else [f"{namespace}.{written}" if namespace else written for namespace in namespaces]
            )
            members = next((self.members[key] for key in keys if key in self.members), None)
            if members is None:
                continue
            member = components[length]
            matches = difflib.get_close_matches(member, members, n=1, cutoff=self.min_similarity)
            if not matches or matches[0] == member:
                return None
            repaired = ".".join([*components[:length], matches[0], *components[length + 1 :]])
            return ROOT_PREFIX + repaired if root else repaired
        return None

    def repaired(self, block: str, unknown: Sequence[str], namespaces: Sequence[str]) -> RepairedBlock | None:
        """The block with every unknown name replaced, or None when one has no close enough replacement."""
        lexed = lex(block)
        if not lexed.exact:
            return None
        repairs = []
        for name in unknown:
            replacement = self.replacement(name, namespaces)
            if replacement is None:
                return None
            repairs.append(NameRepair(name, replacement))
        replacements = {repair.original: repair.replacement for repair in repairs}
        pieces = []
        position = 0
        for token in tokenize(lexed.masked(frozenset({LexicalKind.CODE}))):
            if token.is_identifier and token.text in replacements:
                pieces.extend([block[position : token.start], replacements[token.text]])
                position = token.start + len(token.text)
        if not pieces:
            return None
        return RepairedBlock("".join([*pieces, block[position:]]), tuple(repairs))


_repairers: dict[tuple[EnvironmentNames, float], NameRepairer] = {}
_repairers_lock = threading.Lock()


def shared_name_repairer(names: EnvironmentNames, min_similarity: float) -> NameRepairer:
    """One repairer per environment and threshold, built once (a pass over ~200k constants) whoever asks first."""
    with _repairers_lock:
        key = (names, min_similarity)
        if key not in _repairers:
            _repairers[key] = NameRepairer(namespace_members(names), min_similarity)
        return _repairers[key]
