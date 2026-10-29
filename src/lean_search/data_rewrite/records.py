"""Records of the rewrite pass: each proof and reasoning example with its flat version, named version and fate."""

from dataclasses import dataclass
from enum import StrEnum

from lean_search.corpora.records import DataSplit
from lean_search.data_rewrite.naming import NameChange
from lean_search.reasoning.dataset import ReasoningExample


class ProofStatus(StrEnum):
    # A tactic in which flattening left a nested `have … := by` proof stays; the build drops the chunks containing it.
    KEPT = "kept"
    START_FAILED = "start_failed"
    # Neither the flat nor the original proof replays (the data no longer holds in this environment).
    ORIGINAL_FAILS = "original_fails"
    # The original proof replays but its flat version does not, or a flattened nested proof broke its segment.
    FLATTENING_CHANGED_BEHAVIOUR = "flattening_changed_behaviour"
    REPL_FAILURE = "repl_failure"


class ExampleStatus(StrEnum):
    KEPT = "kept"
    # No reasoning run's states hold the example's (proof, step).
    STATE_NOT_FOUND = "state_not_found"
    NESTED_HAVE_REMAINS = "nested_have_remains"
    START_FAILED = "start_failed"
    # Replaying the reference steps before the example did not reach its prompt's goals.
    STATE_MISMATCH = "state_mismatch"
    ORIGINAL_BLOCK_FAILS = "original_block_fails"
    # The flat block fails, breaks a segment, or ends in other goals than the original block.
    FLATTENING_CHANGED_BEHAVIOUR = "flattening_changed_behaviour"
    REPL_FAILURE = "repl_failure"


class NamedStatus(StrEnum):
    RENAMED = "renamed"
    NOTHING_TO_RENAME = "nothing_to_rename"
    NAME_CONFLICT = "name_conflict"
    START_FAILED = "start_failed"
    REPLAY_FAILED = "replay_failed"
    # The renamed replay's states are not the numbered ones with the names replaced.
    STATES_DIFFER = "states_differ"
    # The renamed proof, prefixed with `rename'`, does not verify against the original statement.
    ORIGINAL_CHECK_FAILED = "original_check_failed"
    # The numbered version was dropped, so no renaming was attempted.
    NOT_ATTEMPTED = "not_attempted"

    @property
    def usable(self) -> bool:
        return self in (NamedStatus.RENAMED, NamedStatus.NOTHING_TO_RENAME)


@dataclass(frozen=True)
class NamedProof:
    status: NamedStatus
    statement_changes: tuple[NameChange, ...] = ()
    have_changes: tuple[NameChange, ...] = ()
    statement: str = ""
    tactics: tuple[str, ...] = ()
    goals: tuple[tuple[str, ...], ...] = ()
    # Checked against the original statement (a sampled fraction); None when not checked.
    original_verified: bool | None = None
    message: str = ""


@dataclass(frozen=True)
class RewrittenProof:
    source: str
    proof_identifier: str
    split: DataSplit
    header: str
    formal_statement: str
    # Top-level tactics of the original proof, and whether flattening changed it.
    original_tactics: int
    flattened: bool
    status: ProofStatus
    message: str
    # The flat proof as replayed, the goals before each tactic and after the last (empty: proved).
    tactics: tuple[str, ...]
    goals: tuple[tuple[str, ...], ...]
    named: NamedProof
    lean_seconds: float


@dataclass(frozen=True)
class NamedExample:
    status: NamedStatus
    statement_changes: tuple[NameChange, ...] = ()
    have_changes: tuple[NameChange, ...] = ()
    goals: tuple[str, ...] = ()
    tactic_block: str = ""
    reasoning: str = ""
    goals_after: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class RewrittenExample:
    original: ReasoningExample
    split: DataSplit
    status: ExampleStatus
    message: str
    flattened: bool
    # The flat block and the goals after it (the prompt's goals are the original's).
    tactic_block: str
    goals_after: tuple[str, ...]
    named: NamedExample
    lean_seconds: float
