"""Pool v3: statements with a known formal proof that no training used, certified by compiling a known proof.

Selection groups the normalized (decontaminated) proof corpora by canonical statement, drops every statement whose
proof was selected for tracing (SFT, the value data and everything derived from traced proofs) and keeps each
statement's shortest proofs as verification candidates, easiest statements first. Verification compiles the
candidates in our Lean environment, shortest first, until one passes; only verified statements enter the curriculum.
It also records the root goals (for the value model's root h) and whether the search's automation tactics alone
close the root. The proofs never train anything: they certify provability and estimate difficulty.
"""

import json
import re
import time
import tomllib
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.corpora.lean_text import split_top_level_tactics
from lean_search.corpora.records import ProofRecord, StatementRecord
from lean_search.expert_iteration.pool import canonical_header, problem_name
from lean_search.lean import LeanError, LeanRepl, LeanTimeout, ProofState, ReplFailure
from lean_search.search.records import from_json_object, to_json

MAX_FAILURE_CHARACTERS = 300
FIRST_PROOF_TACTICS = re.compile(rb'"top_level_tactics": (\d+)')
DECLARED_NAME = re.compile(r"\s*(?:theorem|lemma)\s+(\S+)")


@dataclass(frozen=True)
class KnownProof:
    source: str
    identifier: str
    tactic_proof: str
    top_level_tactics: int
    characters: int

    @property
    def length_key(self) -> tuple[int, int]:
        return self.top_level_tactics, self.characters


@dataclass(frozen=True)
class KnownProofStatement:
    statement: StatementRecord
    statement_key: str
    # Every pooled source with a proof of the statement.
    proof_sources: tuple[str, ...]
    # The shortest proofs (top-level tactics, then characters), the verification candidates.
    proofs: tuple[KnownProof, ...]

    @property
    def name(self) -> str:
        return problem_name(self.statement)


@dataclass(frozen=True)
class VerifiedStatement:
    statement: StatementRecord
    proof_sources: tuple[str, ...]
    verified: bool
    # The first candidate that compiled; its length is the difficulty estimate.
    proof_source: str | None
    proof_tactics: int
    proof_characters: int
    root_goals: tuple[str, ...]
    automation_solved: bool
    load_failed: bool
    failures: tuple[str, ...]
    seconds: float
    # Not checked: its shortest known proof is below verification.min_proof_tactics (almost always automation-trivial).
    skipped: bool = False

    @property
    def name(self) -> str:
        return problem_name(self.statement)


@dataclass(frozen=True)
class IndexedStatement:
    """A candidate as the curriculum needs it before verification: the statement and its shortest proof's length."""

    statement: StatementRecord
    proof_tactics: int
    proof_characters: int


def indexed_statement(candidate: KnownProofStatement) -> IndexedStatement:
    shortest = candidate.proofs[0]
    return IndexedStatement(candidate.statement, shortest.top_level_tactics, shortest.characters)


def read_index(path: Path) -> Iterator[IndexedStatement]:
    with path.open(encoding="utf-8") as lines:
        yield from (from_json_object(IndexedStatement, json.loads(line)) for line in lines if line.strip())


@dataclass
class StatementProofs:
    statement: StatementRecord
    sources: set[str] = field(default_factory=set)
    proofs: list[KnownProof] = field(default_factory=list)


def is_negation(statement: StatementRecord) -> bool:
    """A proved negation of a (often misformalized) conjecture, as Goedel-Prover's data names them."""
    declared = DECLARED_NAME.match(statement.formal_statement)
    return declared is not None and "negation" in declared.group(1)


def known_proof(record: ProofRecord) -> KnownProof:
    tactics = split_top_level_tactics(record.tactic_proof)
    return KnownProof(record.source, record.identifier, record.tactic_proof, len(tactics), len(record.tactic_proof))


def proof_statement(record: ProofRecord) -> StatementRecord:
    return StatementRecord(
        record.source,
        record.statement_identifier,
        canonical_header(record.header),
        record.formal_statement,
        "",
        record.lean_version_hint,
    )


def add_proof(groups: dict[str, StatementProofs], key: str, record: ProofRecord, proofs_per_statement: int) -> None:
    """Keeps the statement as its first source has it and the shortest distinct proofs over all sources."""
    group = groups.get(key)
    if group is None:
        group = groups[key] = StatementProofs(proof_statement(record))
    group.sources.add(record.source)
    proof = known_proof(record)
    if any(existing.tactic_proof == proof.tactic_proof for existing in group.proofs):
        return
    group.proofs.append(proof)
    group.proofs.sort(key=lambda candidate: candidate.length_key)
    del group.proofs[proofs_per_statement:]


def easiest_first(groups: dict[str, StatementProofs]) -> list[KnownProofStatement]:
    statements = [
        KnownProofStatement(group.statement, key, tuple(sorted(group.sources)), tuple(group.proofs))
        for key, group in groups.items()
    ]
    return sorted(statements, key=lambda statement: (statement.proofs[0].length_key, statement.statement_key))


def first_line(message: str) -> str:
    return message.strip().split("\n", 1)[0][:MAX_FAILURE_CHARACTERS]


async def automation_closes(repl: LeanRepl, root: ProofState, tactics: Sequence[str], timeout_seconds: float) -> bool:
    for tactic in tactics:
        result = await repl.apply_block(root, tactic, timeout_seconds=timeout_seconds)
        if result.failure is None and result.state.is_proved:
            return True
    return False


async def verify_statement(
    repl: LeanRepl, candidate: KnownProofStatement, automation_tactics: Sequence[str], automation_timeout: float
) -> VerifiedStatement:
    """Loads the statement, compiles its proofs shortest first until one passes, then probes the automation."""
    started = time.monotonic()
    statement = candidate.statement
    start = await repl.start_proof(statement.formal_statement, statement.header)
    match start.outcome:
        case LeanError() | LeanTimeout() | ReplFailure() as failure:
            return VerifiedStatement(
                statement,
                candidate.proof_sources,
                False,
                None,
                0,
                0,
                (),
                False,
                True,
                (first_line(failure.message),),
                time.monotonic() - started,
            )
        case ProofState() as root:
            pass
    failures: list[str] = []
    for proof in candidate.proofs:
        verification = await repl.verify_proof(statement.formal_statement, proof.tactic_proof, statement.header)
        if verification.verified:
            automation = await automation_closes(repl, root, automation_tactics, automation_timeout)
            return VerifiedStatement(
                statement,
                candidate.proof_sources,
                True,
                proof.source,
                proof.top_level_tactics,
                proof.characters,
                root.goals,
                automation,
                False,
                tuple(failures),
                time.monotonic() - started,
            )
        failures.append(first_line(verification.problems[0]) if verification.problems else "not verified")
    return VerifiedStatement(
        statement,
        candidate.proof_sources,
        False,
        None,
        0,
        0,
        root.goals,
        False,
        False,
        tuple(failures),
        time.monotonic() - started,
    )


def skipped_statement(candidate: KnownProofStatement) -> VerifiedStatement:
    tactics = candidate.proofs[0].top_level_tactics
    reason = f"skipped: shortest known proof has {tactics} top-level tactics"
    return VerifiedStatement(
        candidate.statement, candidate.proof_sources, False, None, tactics, 0, (), False, False, (reason,), 0.0, True
    )


def write_records(path: Path, records: Iterable[object]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(to_json(record) + "\n")
            count += 1
    return count


def read_candidates(path: Path) -> Iterator[KnownProofStatement]:
    with path.open(encoding="utf-8") as lines:
        yield from (from_json_object(KnownProofStatement, json.loads(line)) for line in lines if line.strip())


def length_buckets(path: Path, minimum_tactics: int, last_bucket: int) -> list[list[int]]:
    """Byte offsets of the candidates by their shortest proof's top-level tactics (the last bucket open-ended)."""
    buckets: list[list[int]] = [[] for _ in range(last_bucket - minimum_tactics + 1)]
    with path.open("rb") as lines:
        offset = 0
        for line in lines:
            # The shortest proof comes first, so the first count in the line is its.
            match = FIRST_PROOF_TACTICS.search(line)
            if match is not None and int(match.group(1)) >= minimum_tactics:
                buckets[min(int(match.group(1)), last_bucket) - minimum_tactics].append(offset)
            offset += len(line)
    return buckets


def stratified_candidates(path: Path, minimum_tactics: int, last_bucket: int) -> Iterator[KnownProofStatement]:
    """Round-robin over proof-length buckets, each easiest first, so verified statements span every difficulty."""
    queues = [iter(bucket) for bucket in length_buckets(path, minimum_tactics, last_bucket) if bucket]
    with path.open("rb") as lines:
        while queues:
            remaining = []
            for queue in queues:
                offset = next(queue, None)
                if offset is None:
                    continue
                remaining.append(queue)
                lines.seek(offset)
                yield from_json_object(KnownProofStatement, json.loads(lines.readline()))
            queues = remaining


def read_verified(path: Path, offset: int = 0) -> tuple[list[VerifiedStatement], int]:
    """The complete records from a byte offset on, and the offset after them (a line being written waits)."""
    if not path.exists():
        return [], offset
    with path.open("rb") as handle:
        handle.seek(offset)
        data = handle.read()
    complete = data[: data.rfind(b"\n") + 1]
    records = [
        from_json_object(VerifiedStatement, json.loads(line)) for line in complete.decode("utf-8").splitlines() if line
    ]
    return records, offset + len(complete)


@dataclass(frozen=True)
class ProofCorpus:
    name: str
    # Under $LEAN_SEARCH_DATA.
    path: str
    # Counted only when false (e.g. model-generated conjectures).
    pooled: bool = True


@dataclass(frozen=True)
class VerificationConfig:
    # Lean processes; a modest count next to the running loop (--concurrency raises it, e.g. before launch).
    concurrency: int = 6
    batch: int = 256
    # Verified, usable (not automation-solved) statements the loop has not started, kept ahead of its need.
    lead: int = 10000
    # Statements whose shortest known proof has fewer top-level tactics are recorded as skipped, not checked: the
    # automation sweep closes almost all one-tactic ones.
    min_proof_tactics: int = 2
    # Candidates in round-robin over proof-length buckets (min_proof_tactics up to this, the last open-ended), so
    # verified statements span every difficulty and the curriculum's band can rise; 0 verifies easiest first.
    stratified_last_bucket: int = 12
    check_seconds: float = 300.0
    command_timeout_seconds: float = 60.0
    # The automation probe: the loop search template's automation tactics, each with this time limit.
    automation_config: str = "experiments/configs/expert_iteration/loop_search.toml"
    automation_timeout_seconds: float = 5.0
    restart_fraction: float = 0.3


@dataclass(frozen=True)
class KnownProofPoolConfig:
    corpora: tuple[ProofCorpus, ...]
    excluded_proofs: tuple[str, ...]
    proofs_per_statement: int = 3
    # Statements whose estimated Jaccard similarity of normalized token 5-grams reaches this are one problem.
    near_duplicate_jaccard: float = 0.7
    # Proved negations of conjectures (`*_negation`) say little about solving problems; the curriculum leaves them out.
    drop_negations: bool = True
    verification: VerificationConfig = field(default_factory=VerificationConfig)


def load_known_proof_pool_config(path: Path) -> KnownProofPoolConfig:
    return from_json_object(KnownProofPoolConfig, tomllib.loads(path.read_text(encoding="utf-8")))
