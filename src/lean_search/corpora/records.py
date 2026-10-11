import dataclasses
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from lean_search.corpora.lean_text import split_top_level_tactics


@dataclass(frozen=True)
class ProofRecord:
    source: str
    identifier: str
    statement_identifier: str
    header: str
    formal_statement: str
    tactic_proof: str
    lean_version_hint: str
    distinct_proofs_for_statement: int = 1

    def top_level_tactics(self) -> tuple[str, ...]:
        return split_top_level_tactics(self.tactic_proof)


@dataclass(frozen=True)
class StatementRecord:
    source: str
    identifier: str
    header: str
    formal_statement: str
    informal_statement: str
    lean_version_hint: str


@dataclass(frozen=True)
class PremiseReference:
    full_name: str
    definition_path: str


@dataclass(frozen=True)
class TacticExample:
    source: str
    identifier: str
    split: str
    file_path: str
    theorem_full_name: str
    theorem_start_line: int
    tactic_index: int
    state_before: str
    tactic: str
    annotated_tactic: str
    state_after: str
    premises: tuple[PremiseReference, ...]


@dataclass(frozen=True)
class PremiseRecord:
    source: str
    full_name: str
    file_path: str
    start_line: int
    kind: str
    code: str


@dataclass(frozen=True)
class FileImports:
    source: str
    file_path: str
    imports: tuple[str, ...]


class DataSplit(StrEnum):
    TRAIN = "train"
    VALIDATION = "validation"


class TraceStatus(StrEnum):
    COMPLETE = "complete"
    STEP_ERROR = "step_error"
    CLOSED_EARLY = "closed_early"
    GOALS_REMAINING = "goals_remaining"
    TIMEOUT = "timeout"
    START_FAILURE = "start_failure"
    REPL_FAILURE = "repl_failure"


class TracePath(StrEnum):
    STEPS = "steps"
    BLOCK = "block"


@dataclass(frozen=True)
class TracedStep:
    source: str
    proof_identifier: str
    statement_identifier: str
    split: DataSplit
    header: str
    formal_statement: str
    step_index: int
    total_steps: int
    remaining_steps: int
    goals_before: tuple[str, ...]
    step: str
    goals_after: tuple[str, ...]
    previous_steps: tuple[str, ...]
    heartbeats: int
    elapsed_seconds: float


@dataclass(frozen=True)
class TracedProof:
    source: str
    proof_identifier: str
    statement_identifier: str
    split: DataSplit
    header: str
    formal_statement: str
    status: TraceStatus
    path: TracePath
    total_steps: int
    applied_steps: tuple[str, ...]
    open_goals: int
    failing_step_index: int | None
    failing_step: str
    failure_message: str
    repl_failure_kind: str
    heartbeats: int
    start_seconds: float
    step_seconds: tuple[float, ...]
    elapsed_seconds: float
    verification_seconds: float
    verified: bool | None
    plain_verified: bool | None
    verification_problems: tuple[str, ...]


Record = ProofRecord | StatementRecord | TacticExample | PremiseRecord | FileImports | TracedStep | TracedProof


def write_jsonl(path: Path, records: Iterable[Record]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False))
            handle.write("\n")
            count += 1
    return count


def _read_json_lines(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            yield json.loads(line)


def read_proof_records(path: Path) -> Iterator[ProofRecord]:
    for fields in _read_json_lines(path):
        yield ProofRecord(**fields)


def read_statement_records(path: Path) -> Iterator[StatementRecord]:
    for fields in _read_json_lines(path):
        yield StatementRecord(**fields)


def read_tactic_examples(path: Path) -> Iterator[TacticExample]:
    for fields in _read_json_lines(path):
        fields["premises"] = tuple(PremiseReference(**premise) for premise in fields["premises"])
        yield TacticExample(**fields)


def read_premise_records(path: Path) -> Iterator[PremiseRecord]:
    for fields in _read_json_lines(path):
        yield PremiseRecord(**fields)


def read_file_imports(path: Path) -> Iterator[FileImports]:
    for fields in _read_json_lines(path):
        fields["imports"] = tuple(fields["imports"])
        yield FileImports(**fields)


def read_traced_steps(path: Path) -> Iterator[TracedStep]:
    for fields in _read_json_lines(path):
        fields["split"] = DataSplit(fields["split"])
        for name in ("goals_before", "goals_after", "previous_steps"):
            fields[name] = tuple(fields[name])
        yield TracedStep(**fields)


def read_traced_proofs(path: Path) -> Iterator[TracedProof]:
    for fields in _read_json_lines(path):
        fields["split"] = DataSplit(fields["split"])
        fields["status"] = TraceStatus(fields["status"])
        fields["path"] = TracePath(fields["path"])
        for name in ("applied_steps", "step_seconds", "verification_problems"):
            fields[name] = tuple(fields[name])
        yield TracedProof(**fields)
