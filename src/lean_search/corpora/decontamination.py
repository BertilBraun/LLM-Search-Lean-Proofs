import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from lean_search.corpora.lean_text import strip_comments

NGRAM_SIZE = 5
INFORMAL_NGRAM_SIZE = 4

_TOKEN = re.compile(r"[\w.'!?]+|\S")
_IDENTIFIER = re.compile(r"[^\W\d][\w.'!?]*")
_DECLARED_NAME = re.compile(r"\s*(?:theorem|lemma)\s+([^\s(\[{⦃:]+)")
_DECLARATION_PREFIX = re.compile(r"^\s*(?:theorem|lemma)\s+[^\s(\[{⦃:]+|^\s*example\b")
_PROOF_SUFFIX = re.compile(r":=\s*(?:by\b.*|sorry\s*)$", re.DOTALL)
_ASCII_TO_UNICODE = (("<->", "↔"), ("->", "→"), ("<=", "≤"), (">=", "≥"), ("!=", "≠"), ("=>", "↦"))
_BINDER_OPENERS = frozenset("({⦃[")
_BINDER_CLOSERS = frozenset(")}⦄]⟩")
_SHOW_THAT_SUFFIX = re.compile(r"show that it is.*$", re.DOTALL)
_INFORMAL_TOKEN = re.compile(r"[a-z]+|\d+(?:\.\d+)?")
_LATEX_FORMATTING = frozenset({"textbf", "qquad", "quad", "mathrm", "mathbf", "text", "left", "right", "displaystyle"})
_QUANTIFIERS = frozenset({"∀", "∃", "∃!", "fun", "λ", "∑", "∏", "⋃", "⋂"})
_QUANTIFIER_STOPS = frozenset({",", ":", "↦", "∈", "in", "<", "≤", ">", "≥", "∉", "|", "∣"})
_HYPOTHESIS_NAME = re.compile(r"h[\w'!?]*|this")
_KEYWORDS = frozenset({"fun", "λ", "in", "let", "have", "show", "if", "then", "else", "match", "with", "by", "at"})


class MatchKind(StrEnum):
    EXACT = "exact"
    NAME = "name"
    FORMAL_NGRAM = "formal_ngram"
    SHARED_CONCLUSION = "shared_conclusion"
    INFORMAL_NGRAM = "informal_ngram"
    PROPAGATED = "propagated"


@dataclass(frozen=True)
class ReferenceProblem:
    name: str
    split: str
    formal_statement: str
    informal_statement: str


@dataclass(frozen=True)
class DecontaminationThresholds:
    formal_ngram: float
    shared_conclusion_formal_ngram: float
    minimum_conclusion_tokens: int
    informal_ngram: float


@dataclass(frozen=True)
class ContaminationMatch:
    reference_name: str
    reference_split: str
    kind: MatchKind
    similarity: float


@dataclass(frozen=True)
class SimilarityAssessment:
    match: ContaminationMatch | None
    best_formal_similarity: float
    best_formal_reference: str
    best_informal_similarity: float
    best_informal_reference: str


def statement_tokens(formal_statement: str) -> list[str]:
    text = strip_comments(formal_statement)
    text = _PROOF_SUFFIX.sub("", _DECLARATION_PREFIX.sub("", text, count=1))
    for ascii_form, unicode_form in _ASCII_TO_UNICODE:
        text = text.replace(ascii_form, unicode_form)
    return _TOKEN.findall(text)


def canonical_statement(formal_statement: str) -> str:
    return " ".join(statement_tokens(formal_statement))


def _is_binder_name(token: str) -> bool:
    return _IDENTIFIER.fullmatch(token) is not None and token not in _KEYWORDS


def _bound_names(tokens: list[str]) -> list[str]:
    names: list[str] = []
    for index, token in enumerate(tokens):
        if token in _BINDER_OPENERS:
            end = index + 1
            while end < len(tokens) and _is_binder_name(tokens[end]):
                end += 1
            if end > index + 1 and end < len(tokens) and tokens[end] in (":", "|"):
                names.extend(tokens[index + 1 : end])
        elif token in _QUANTIFIERS:
            for following in tokens[index + 1 :]:
                if following in _QUANTIFIER_STOPS:
                    break
                if _is_binder_name(following):
                    names.append(following)
                elif following not in ("(", ")"):
                    break
    return names


def anonymized_statement_tokens(formal_statement: str) -> list[str]:
    tokens = statement_tokens(formal_statement)
    renaming: dict[str, str] = {}
    variable_count = 0
    for name in _bound_names(tokens):
        if name in renaming:
            continue
        # Hypothesis names carry no meaning, so all of them collapse to one token; variables keep their order.
        if _HYPOTHESIS_NAME.fullmatch(name):
            renaming[name] = "h"
        else:
            renaming[name] = f"v{variable_count}"
            variable_count += 1
    return [renaming.get(token, token) for token in tokens]


def token_ngrams(tokens: list[str], size: int = NGRAM_SIZE) -> frozenset[str]:
    if not tokens:
        return frozenset()
    if len(tokens) < size:
        return frozenset({" ".join(tokens)})
    return frozenset(" ".join(tokens[index : index + size]) for index in range(len(tokens) - size + 1))


def jaccard_similarity(first: frozenset[str], second: frozenset[str]) -> float:
    if not first and not second:
        return 1.0
    shared = len(first & second)
    return shared / (len(first) + len(second) - shared)


def conclusion_tokens(anonymized_tokens: list[str]) -> tuple[str, ...]:
    depth = 0
    for index, token in enumerate(anonymized_tokens):
        if token in _BINDER_OPENERS or token == "⟨":
            depth += 1
        elif token in _BINDER_CLOSERS:
            depth -= 1
        elif token == ":" and depth == 0:
            return tuple(anonymized_tokens[index + 1 :])
    return tuple(anonymized_tokens)


def informal_tokens(informal_statement: str) -> list[str]:
    text = _SHOW_THAT_SUFFIX.sub("", informal_statement.lower())
    return [token for token in _INFORMAL_TOKEN.findall(text) if token not in _LATEX_FORMATTING]


def informal_ngrams(informal_statement: str) -> frozenset[str]:
    return token_ngrams(informal_tokens(informal_statement), INFORMAL_NGRAM_SIZE)


class NgramIndex:
    def __init__(self, ngram_sets: list[frozenset[str]]) -> None:
        self.ngram_sets = ngram_sets
        self.ngram_to_entries: dict[str, list[int]] = {}
        for index, ngrams in enumerate(ngram_sets):
            for ngram in ngrams:
                self.ngram_to_entries.setdefault(ngram, []).append(index)

    def similarities(self, ngrams: frozenset[str]) -> dict[int, float]:
        shared_counts: Counter[int] = Counter()
        for ngram in ngrams:
            shared_counts.update(self.ngram_to_entries.get(ngram, ()))
        return {
            index: shared / (len(ngrams) + len(self.ngram_sets[index]) - shared)
            for index, shared in shared_counts.items()
        }


def _best(similarities: dict[int, float]) -> tuple[int, float] | None:
    return max(similarities.items(), key=lambda item: item[1], default=None)


class ContaminationIndex:
    def __init__(self, references: Iterable[ReferenceProblem], thresholds: DecontaminationThresholds) -> None:
        self.references = list(references)
        self.thresholds = thresholds
        self.canonical_to_reference = {
            canonical_statement(reference.formal_statement): index for index, reference in enumerate(self.references)
        }
        anonymized = [anonymized_statement_tokens(reference.formal_statement) for reference in self.references]
        self.formal_index = NgramIndex([token_ngrams(tokens) for tokens in anonymized])
        self.conclusion_to_references: dict[tuple[str, ...], list[int]] = {}
        for index, tokens in enumerate(anonymized):
            conclusion = conclusion_tokens(tokens)
            if len(conclusion) >= thresholds.minimum_conclusion_tokens:
                self.conclusion_to_references.setdefault(conclusion, []).append(index)
        self.informal_index = NgramIndex(
            [informal_ngrams(reference.informal_statement) for reference in self.references]
        )
        self.name_to_reference = {reference.name: index for index, reference in enumerate(self.references)}
        names_longest_first = sorted(self.name_to_reference, key=len, reverse=True)
        # Generated variants keep the benchmark name plus a suffix (`_v2`, `sq`); a digit would name another problem.
        self.name_prefix = re.compile("(" + "|".join(map(re.escape, names_longest_first)) + ")(?![0-9])")

    def _named_reference(self, formal_statement: str) -> int | None:
        declared = _DECLARED_NAME.match(formal_statement)
        if declared is None:
            return None
        prefix = self.name_prefix.match(declared.group(1).rsplit(".", 1)[-1])
        return None if prefix is None else self.name_to_reference[prefix.group(1)]

    def _match(self, index: int, kind: MatchKind, similarity: float) -> ContaminationMatch:
        reference = self.references[index]
        return ContaminationMatch(reference.name, reference.split, kind, similarity)

    def assess(self, formal_statement: str, informal_statement: str) -> SimilarityAssessment:
        tokens = anonymized_statement_tokens(formal_statement)
        formal_similarities = self.formal_index.similarities(token_ngrams(tokens))
        best_formal = _best(formal_similarities)
        informal_similarities = (
            self.informal_index.similarities(informal_ngrams(informal_statement)) if informal_statement.strip() else {}
        )
        best_informal = _best(informal_similarities)
        match = None
        exact_index = self.canonical_to_reference.get(canonical_statement(formal_statement))
        named_index = self._named_reference(formal_statement)
        if exact_index is not None:
            match = self._match(exact_index, MatchKind.EXACT, 1.0)
        elif named_index is not None:
            match = self._match(named_index, MatchKind.NAME, formal_similarities.get(named_index, 0.0))
        elif best_formal is not None and best_formal[1] >= self.thresholds.formal_ngram:
            match = self._match(best_formal[0], MatchKind.FORMAL_NGRAM, best_formal[1])
        else:
            for index in self.conclusion_to_references.get(conclusion_tokens(tokens), ()):
                similarity = formal_similarities.get(index, 0.0)
                if similarity >= self.thresholds.shared_conclusion_formal_ngram:
                    match = self._match(index, MatchKind.SHARED_CONCLUSION, similarity)
                    break
        if match is None and best_informal is not None and best_informal[1] >= self.thresholds.informal_ngram:
            match = self._match(best_informal[0], MatchKind.INFORMAL_NGRAM, best_informal[1])
        return SimilarityAssessment(
            match=match,
            best_formal_similarity=best_formal[1] if best_formal else 0.0,
            best_formal_reference=self.references[best_formal[0]].name if best_formal else "",
            best_informal_similarity=best_informal[1] if best_informal else 0.0,
            best_informal_reference=self.references[best_informal[0]].name if best_informal else "",
        )
