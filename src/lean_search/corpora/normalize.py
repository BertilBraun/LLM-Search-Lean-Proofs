import hashlib
from enum import StrEnum

from lean_search.corpora.decontamination import canonical_statement
from lean_search.corpora.lean_text import (
    DeclarationError,
    bracket_depth_change,
    contains_incomplete_proof,
    declares_axiom,
    split_declaration,
    split_statement,
)
from lean_search.corpora.records import ProofRecord, StatementRecord
from lean_search.corpora.sources import RawProof, RawStatement

MAXIMUM_PROOF_CHARACTERS = 20_000


class Rejection(StrEnum):
    NO_DECLARATION = "no_declaration"
    NO_ASSIGNMENT = "no_assignment"
    TERM_MODE = "term_mode"
    EMPTY_PROOF = "empty_proof"
    INCOMPLETE_PROOF = "sorry_or_admit"
    DECLARES_AXIOM = "declares_axiom"
    UNBALANCED_BRACKETS = "unbalanced_brackets"
    TOO_LONG = "too_long"


_DECLARATION_REJECTIONS = {
    DeclarationError.NO_DECLARATION: Rejection.NO_DECLARATION,
    DeclarationError.NO_ASSIGNMENT: Rejection.NO_ASSIGNMENT,
    DeclarationError.TERM_MODE: Rejection.TERM_MODE,
}


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def normalized_proof_text(tactic_proof: str) -> str:
    return " ".join(tactic_proof.split())


def normalize_proof(
    raw: RawProof, identifier: str, lean_version_hint: str, statement_identifiers_unique: bool
) -> ProofRecord | Rejection:
    parts = split_declaration(raw.lean_text, raw.theorem_name)
    if isinstance(parts, DeclarationError):
        return _DECLARATION_REJECTIONS[parts]
    if not parts.tactic_proof.strip():
        return Rejection.EMPTY_PROOF
    if contains_incomplete_proof(parts.tactic_proof) or contains_incomplete_proof(parts.header):
        return Rejection.INCOMPLETE_PROOF
    if declares_axiom(parts.header):
        return Rejection.DECLARES_AXIOM
    if bracket_depth_change(parts.formal_statement) != 0 or bracket_depth_change(parts.tactic_proof) != 0:
        return Rejection.UNBALANCED_BRACKETS
    if len(parts.tactic_proof) > MAXIMUM_PROOF_CHARACTERS:
        return Rejection.TOO_LONG
    statement_identifier = raw.statement_identifier
    if not statement_identifiers_unique:
        statement_identifier = f"{statement_identifier}@{short_hash(canonical_statement(parts.formal_statement))}"
    return ProofRecord(
        source=raw.source,
        identifier=identifier,
        statement_identifier=statement_identifier,
        header=parts.header,
        formal_statement=parts.formal_statement,
        tactic_proof=parts.tactic_proof,
        lean_version_hint=lean_version_hint,
    )


def normalize_statement(raw: RawStatement, lean_version_hint: str) -> StatementRecord | Rejection:
    parts = split_statement(raw.lean_text, raw.theorem_name)
    if isinstance(parts, DeclarationError):
        return _DECLARATION_REJECTIONS[parts]
    if contains_incomplete_proof(parts.header):
        return Rejection.INCOMPLETE_PROOF
    if bracket_depth_change(parts.formal_statement) != 0:
        return Rejection.UNBALANCED_BRACKETS
    return StatementRecord(
        source=raw.source,
        identifier=raw.identifier,
        header=parts.header,
        formal_statement=parts.formal_statement,
        informal_statement=raw.informal_statement,
        lean_version_hint=lean_version_hint,
    )
