"""The Lean pass of the data rewrite: flatten, re-trace and rename proofs and reasoning examples, shard by shard."""

import asyncio
import hashlib
import json
import time
from collections import Counter
from collections.abc import Awaitable, Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.corpora.records import DataSplit, ProofRecord, TracedStep
from lean_search.corpora.tracing import assign_split, stable_fraction
from lean_search.data_rewrite.model_namer import ModelNamerConfig
from lean_search.data_rewrite.naming import (
    HypothesisNamer,
    NamingConfig,
    NamingSubject,
    Renaming,
    RenamingStatus,
    StatementNames,
    collapsed,
    plan_renamings,
    renamed_text,
)
from lean_search.data_rewrite.records import (
    ChunkExplanation,
    ExampleStatus,
    NamedExample,
    NamedProof,
    NamedStatus,
    ProofStatus,
    RewrittenExample,
    RewrittenProof,
)
from lean_search.data_rewrite.replay import (
    Replay,
    ReplayLimits,
    ReplayOutcome,
    has_nested_have_proof,
    replay_plan,
    tactic_plan,
)
from lean_search.data_rewrite.statement_renaming import verify_against_original
from lean_search.lean import LeanRepl, LeanReplPool, ProofState, ReplFailure
from lean_search.lean.plans import plain_plan, plan_block
from lean_search.lean.text import join_tactics, normalize_goal
from lean_search.reasoning.dataset import ReasoningExample
from lean_search.reasoning.records import read_records, write_records
from lean_search.reasoning.states import ReasoningState, step_identifier

MESSAGE_CHARACTERS = 300


@dataclass(frozen=True)
class RewriteConfig:
    # ProofRecords (relative to $LEAN_SEARCH_DATA) re-traced flat for the chunk examples.
    proof_records: str = "normalized/proofs/selected_for_tracing.jsonl"
    # SFT data sets ($LEAN_SEARCH_DATA/sft/<name>) whose proofs are taken; empty takes every record.
    proof_data: tuple[str, ...] = ("4b",)
    # At most this many proofs, in a fixed pseudo-random order; 0 takes all.
    max_proofs: int = 0
    # The reasoning data set ($LEAN_SEARCH_DATA/reasoning/<name>) whose reasoning examples are rewritten.
    reasoning_data: str = "visible_student_v2"
    # Reasoning runs ($LEAN_SEARCH_RUNS/<run>/states.jsonl) holding the examples' states (statement, earlier steps).
    state_runs: tuple[str, ...] = ()
    max_examples: int = 0
    shard_size: int = 200
    shards_in_flight: int = 4
    pool_size: int = 16
    heartbeats: int = 200_000
    timeout_seconds: float = 60.0
    # Fraction of renamed proofs also verified against the original statement (with `rename'`).
    original_check_fraction: float = 0.1
    seed: str = "data-rewrite"
    naming: NamingConfig = field(default_factory=NamingConfig)
    # Without a model the rule-based namer names everything.
    namer: ModelNamerConfig = field(default_factory=ModelNamerConfig)


@dataclass(frozen=True)
class ReasoningItem:
    example: ReasoningExample
    split: DataSplit


@dataclass(frozen=True)
class RewriteDirectory:
    path: Path

    @property
    def plan(self) -> Path:
        return self.path / "plan.json"

    @property
    def summary(self) -> Path:
        return self.path / "summary"

    def proofs(self, shard: int) -> Path:
        return self.path / "proofs" / f"{shard:05d}.jsonl"

    def examples(self, shard: int) -> Path:
        return self.path / "examples" / f"{shard:05d}.jsonl"

    @property
    def explanation_directory(self) -> Path:
        return self.path / "explanations"

    @property
    def explanation_plan(self) -> Path:
        return self.explanation_directory / "plan.json"

    def explanations(self, shard: int) -> Path:
        return self.explanation_directory / f"{shard:05d}.jsonl"

    def read_explanations(self) -> list[ChunkExplanation]:
        return [
            record
            for path in sorted(self.explanation_directory.glob("*.jsonl"))
            for record in read_records(path, ChunkExplanation)
        ]

    def read_proofs(self) -> list[RewrittenProof]:
        return [
            record for path in sorted(self.path.glob("proofs/*.jsonl")) for record in read_records(path, RewrittenProof)
        ]

    def read_examples(self) -> list[RewrittenExample]:
        return [
            record
            for path in sorted(self.path.glob("examples/*.jsonl"))
            for record in read_records(path, RewrittenExample)
        ]


def select_proofs(
    records: Iterable[ProofRecord], identifiers: Collection[str] | None, max_proofs: int, seed: str
) -> list[ProofRecord]:
    """The records of the given proofs (all without identifiers), first `max_proofs` in a fixed pseudo-random order."""
    selected = [record for record in records if identifiers is None or record.identifier in identifiers]
    selected.sort(key=lambda record: stable_fraction(record.identifier, f"{seed} proofs"))
    return selected[:max_proofs] if max_proofs else selected


def reasoning_items(train: Iterable[ReasoningExample], validation: Iterable[ReasoningExample]) -> list[ReasoningItem]:
    """Examples with reasoning (visible or thinking); the replay examples are replaced by chunk examples."""
    return [
        ReasoningItem(example, split)
        for split, examples in ((DataSplit.TRAIN, train), (DataSplit.VALIDATION, validation))
        for example in examples
        if example.reasoning is not None
    ]


def read_states(paths: Iterable[Path]) -> dict[str, TracedStep]:
    return {step_identifier(state.step): state.step for path in paths for state in read_records(path, ReasoningState)}


def state_key(example: ReasoningExample) -> str:
    return f"{example.proof_identifier}#{example.step_index}"


def shard_digest(keys: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()[:16]


def shards[T](items: Sequence[T], size: int) -> list[Sequence[T]]:
    return [items[start : start + size] for start in range(0, len(items), size)]


def same_goals(numbered: Sequence[str], named: Sequence[str], renaming: Renaming) -> bool:
    """The named goals are the numbered ones with the names replaced (line breaks may differ: longer names)."""
    return len(numbered) == len(named) and all(
        collapsed(renamed_text(left, renaming.changes)) == collapsed(right)
        for left, right in zip(numbered, named, strict=True)
    )


def goal_key(goals: Sequence[str]) -> tuple[str, ...]:
    return tuple(normalize_goal(goal) for goal in goals)


def shortened(message: str) -> str:
    return message[:MESSAGE_CHARACTERS]


async def start_state(repl: LeanRepl, statement: str, header: str) -> ProofState | ReplFailure | str:
    """The root state, the infrastructure failure, or why the statement does not elaborate."""
    outcome = (await repl.start_proof(statement, header)).outcome
    match outcome:
        case ProofState() | ReplFailure():
            return outcome
        case _:
            return outcome.message


def named_status_of(renaming: Renaming) -> NamedStatus | None:
    """The final named status when no Lean work is needed, else None."""
    match renaming.status:
        case RenamingStatus.RENAMED:
            return None
        case status:
            return NamedStatus(status.value)


async def rewrite_proof(
    repl: LeanRepl, record: ProofRecord, renaming: Renaming, limits: ReplayLimits, check_original: bool
) -> RewrittenProof:
    started = time.monotonic()
    plan = plan_block(record.tactic_proof)
    original_tactics = len(plain_plan(record.tactic_proof).tactics)

    def result(
        status: ProofStatus, message: str = "", flat: Replay | None = None, named: NamedProof | None = None
    ) -> RewrittenProof:
        return RewrittenProof(
            source=record.source,
            proof_identifier=record.identifier,
            split=assign_split(record.formal_statement),
            header=record.header,
            formal_statement=record.formal_statement,
            original_tactics=original_tactics,
            flattened=plan.flattened,
            status=status,
            message=shortened(message),
            tactics=() if flat is None else flat.tactics,
            goals=() if flat is None else flat.goals,
            named=named or NamedProof(NamedStatus.NOT_ATTEMPTED),
            lean_seconds=time.monotonic() - started,
        )

    match await start_state(repl, record.formal_statement, record.header):
        case ProofState() as root:
            pass
        case ReplFailure(message=message):
            return result(ProofStatus.REPL_FAILURE, message)
        case message:
            return result(ProofStatus.START_FAILED, message)
    flat = await replay_plan(repl, root, plan, limits, proof=True)
    if flat.outcome is not ReplayOutcome.COMPLETE:
        message = f"{flat.outcome}: {flat.message}"
        if flat.outcome is ReplayOutcome.REPL_FAILURE:
            return result(ProofStatus.REPL_FAILURE, message)
        if not plan.flattened:
            return result(ProofStatus.ORIGINAL_FAILS, message)
        original = await replay_plan(repl, root, plain_plan(record.tactic_proof), limits, proof=True)
        if original.outcome is ReplayOutcome.COMPLETE:
            return result(ProofStatus.FLATTENING_CHANGED_BEHAVIOUR, message)
        return result(ProofStatus.ORIGINAL_FAILS, message)
    named = await named_proof(repl, record, flat, renaming, limits, check_original)
    return result(ProofStatus.KEPT, flat=flat, named=named)


async def named_proof(
    repl: LeanRepl, record: ProofRecord, flat: Replay, renaming: Renaming, limits: ReplayLimits, check_original: bool
) -> NamedProof:
    if (status := named_status_of(renaming)) is not None:
        return NamedProof(status)
    changes = (renaming.statement_changes, renaming.have_changes)
    statement = renamed_text(record.formal_statement, renaming.statement_changes)
    tactics = tuple(renamed_text(tactic, renaming.changes) for tactic in flat.tactics)
    match await start_state(repl, statement, record.header):
        case ProofState() as root:
            pass
        case ReplFailure(message=message) | str(message):
            return NamedProof(NamedStatus.START_FAILED, *changes, statement, message=shortened(message))
    replay = await replay_plan(repl, root, tactic_plan(tactics), limits, proof=True)
    if replay.outcome is not ReplayOutcome.COMPLETE:
        message = shortened(f"{replay.outcome}: {replay.message}")
        return NamedProof(NamedStatus.REPLAY_FAILED, *changes, statement, tactics, message=message)
    if len(replay.states) != len(flat.states) or not all(
        same_goals(numbered, named, renaming) for numbered, named in zip(flat.goals, replay.goals, strict=True)
    ):
        return NamedProof(NamedStatus.STATES_DIFFER, *changes, statement, replay.tactics, replay.goals)
    verified: bool | None = None
    if check_original:
        verification = await verify_against_original(
            repl, record.header, record.formal_statement, renaming.statement_changes, join_tactics(replay.tactics)
        )
        verified = verification.verified
        if not verified:
            message = shortened("; ".join(verification.problems))
            return NamedProof(
                NamedStatus.ORIGINAL_CHECK_FAILED, *changes, statement, replay.tactics, replay.goals, False, message
            )
    return NamedProof(NamedStatus.RENAMED, *changes, statement, replay.tactics, replay.goals, verified)


def missing_state_example(item: ReasoningItem) -> RewrittenExample:
    return RewrittenExample(
        original=item.example,
        split=item.split,
        status=ExampleStatus.STATE_NOT_FOUND,
        message="",
        flattened=plan_block(item.example.tactic_block).flattened,
        tactic_block="",
        goals_after=(),
        named=NamedExample(NamedStatus.NOT_ATTEMPTED),
        lean_seconds=0.0,
    )


async def rewrite_example(
    repl: LeanRepl, item: ReasoningItem, step: TracedStep, renaming: Renaming, limits: ReplayLimits
) -> RewrittenExample:
    started = time.monotonic()
    example = item.example
    plan = plan_block(example.tactic_block)

    def result(
        status: ExampleStatus,
        message: str = "",
        block: str = "",
        goals_after: tuple[str, ...] = (),
        named: NamedExample | None = None,
    ) -> RewrittenExample:
        return RewrittenExample(
            original=example,
            split=item.split,
            status=status,
            message=shortened(message),
            flattened=plan.flattened,
            tactic_block=block,
            goals_after=goals_after,
            named=named or NamedExample(NamedStatus.NOT_ATTEMPTED),
            lean_seconds=time.monotonic() - started,
        )

    if has_nested_have_proof(plan.texts):
        return result(ExampleStatus.NESTED_HAVE_REMAINS)
    match await start_state(repl, step.formal_statement, step.header):
        case ProofState() as root:
            pass
        case ReplFailure(message=message):
            return result(ExampleStatus.REPL_FAILURE, message)
        case message:
            return result(ExampleStatus.START_FAILED, message)
    before = await replay_plan(repl, root, tactic_plan(step.previous_steps), limits, proof=False)
    if before.outcome is not ReplayOutcome.COMPLETE or goal_key(before.states[-1].goals) != goal_key(example.goals):
        return result(ExampleStatus.STATE_MISMATCH, f"{before.outcome}: {before.message}")
    state = before.states[-1]
    original = await replay_plan(repl, state, plain_plan(example.tactic_block), limits, proof=False)
    if original.outcome is not ReplayOutcome.COMPLETE:
        status = ExampleStatus.REPL_FAILURE if original.outcome is ReplayOutcome.REPL_FAILURE else None
        return result(status or ExampleStatus.ORIGINAL_BLOCK_FAILS, f"{original.outcome}: {original.message}")
    flat, block = original, example.tactic_block
    if plan.flattened:
        flat = await replay_plan(repl, state, plan, limits, proof=False)
        if flat.outcome is not ReplayOutcome.COMPLETE or goal_key(flat.goals[-1]) != goal_key(original.goals[-1]):
            return result(ExampleStatus.FLATTENING_CHANGED_BEHAVIOUR, f"{flat.outcome}: {flat.message}")
        block = join_tactics(flat.tactics)
    named = await named_example(repl, example, step, before, flat, block, renaming, limits)
    return result(ExampleStatus.KEPT, block=block, goals_after=flat.goals[-1], named=named)


async def named_example(
    repl: LeanRepl,
    example: ReasoningExample,
    step: TracedStep,
    before: Replay,
    flat: Replay,
    block: str,
    renaming: Renaming,
    limits: ReplayLimits,
) -> NamedExample:
    if (status := named_status_of(renaming)) is not None:
        return NamedExample(status)
    changes = (renaming.statement_changes, renaming.have_changes)
    statement = renamed_text(step.formal_statement, renaming.statement_changes)
    match await start_state(repl, statement, step.header):
        case ProofState() as root:
            pass
        case ReplFailure(message=message) | str(message):
            return NamedExample(NamedStatus.START_FAILED, *changes, message=shortened(message))
    previous = tuple(renamed_text(tactic, renaming.changes) for tactic in step.previous_steps)
    named_before = await replay_plan(repl, root, tactic_plan(previous), limits, proof=False)
    if named_before.outcome is not ReplayOutcome.COMPLETE:
        message = shortened(f"{named_before.outcome}: {named_before.message}")
        return NamedExample(NamedStatus.REPLAY_FAILED, *changes, message=message)
    goals = named_before.states[-1].goals
    named_block = renamed_text(block, renaming.changes)
    after = await replay_plan(repl, named_before.states[-1], plain_plan(named_block), limits, proof=False)
    if after.outcome is not ReplayOutcome.COMPLETE:
        message = shortened(f"{after.outcome}: {after.message}")
        return NamedExample(NamedStatus.REPLAY_FAILED, *changes, goals, named_block, message=message)
    reasoning = renamed_text(example.reasoning or "", renaming.changes)
    same = same_goals(before.states[-1].goals, goals, renaming) and same_goals(
        flat.goals[-1], after.goals[-1], renaming
    )
    status = NamedStatus.RENAMED if same else NamedStatus.STATES_DIFFER
    return NamedExample(status, *changes, goals, named_block, reasoning, after.goals[-1])


type ShardCallback = Callable[[str, int, int], Awaitable[None]]


@dataclass
class RewriteRun:
    """Everything one invocation shares: the pool, the namer, the statement names and the progress counters."""

    config: RewriteConfig
    directory: RewriteDirectory
    pool: LeanReplPool
    namer: HypothesisNamer
    reserved: frozenset[str]
    statement_names: StatementNames = field(default_factory=dict)
    progress: Counter[str] = field(default_factory=Counter)

    @property
    def limits(self) -> ReplayLimits:
        return ReplayLimits(self.config.heartbeats, self.config.timeout_seconds)

    def checks_original(self, proof_identifier: str) -> bool:
        return (
            stable_fraction(proof_identifier, f"{self.config.seed} original check")
            < self.config.original_check_fraction
        )

    async def renamings(self, subjects: Sequence[NamingSubject]) -> list[Renaming]:
        return await plan_renamings(subjects, self.namer, self.config.naming, self.reserved, self.statement_names)

    async def proof_shard(self, index: int, records: Sequence[ProofRecord]) -> None:
        subjects = [NamingSubject(record.formal_statement, plan_block(record.tactic_proof).texts) for record in records]
        renamings = await self.renamings(subjects)

        async def one(record: ProofRecord, renaming: Renaming) -> RewrittenProof:
            async with self.pool.acquire() as repl:
                return await rewrite_proof(repl, record, renaming, self.limits, self.checks_original(record.identifier))

        rewritten = await asyncio.gather(*map(one, records, renamings))
        await asyncio.to_thread(write_records, self.directory.proofs(index), rewritten)
        self.progress.update(proofs=len(rewritten), kept_proofs=sum(r.status is ProofStatus.KEPT for r in rewritten))

    async def example_shard(self, index: int, items: Sequence[ReasoningItem], states: dict[str, TracedStep]) -> None:
        found = [(item, states[state_key(item.example)]) for item in items if state_key(item.example) in states]
        subjects = [
            NamingSubject(step.formal_statement, (*step.previous_steps, *plan_block(item.example.tactic_block).texts))
            for item, step in found
        ]
        renamings = await self.renamings(subjects)

        async def one(item: ReasoningItem, step: TracedStep, renaming: Renaming) -> RewrittenExample:
            async with self.pool.acquire() as repl:
                return await rewrite_example(repl, item, step, renaming, self.limits)

        missing = [missing_state_example(item) for item in items if state_key(item.example) not in states]
        rewritten = [
            *await asyncio.gather(*(one(*pair, renaming) for pair, renaming in zip(found, renamings, strict=True))),
            *missing,
        ]
        await asyncio.to_thread(write_records, self.directory.examples(index), rewritten)
        self.progress.update(
            examples=len(rewritten), kept_examples=sum(r.status is ExampleStatus.KEPT for r in rewritten)
        )


def ensure_plan(path: Path, plan: Mapping[str, object]) -> None:
    """Writes the shard plan of a new run; a resumed run must have the same one."""
    if path.exists():
        if json.loads(path.read_text(encoding="utf-8")) != plan:
            raise ValueError(f"The shard plan differs from {path}; use the original inputs or a new run.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=1), encoding="utf-8")


def check_plan(directory: RewriteDirectory, proof_keys: Sequence[str], example_keys: Sequence[str], size: int) -> None:
    plan = {
        "shard_size": size,
        "proofs": [shard_digest(keys) for keys in shards(proof_keys, size)],
        "examples": [shard_digest(keys) for keys in shards(example_keys, size)],
    }
    ensure_plan(directory.plan, plan)


def example_key(item: ReasoningItem) -> str:
    example = item.example
    digest = hashlib.sha256(f"{example.tactic_block}\n{example.reasoning}".encode()).hexdigest()[:12]
    return f"{item.split}:{state_key(example)}#{digest}"


async def run_rewrite(
    run: RewriteRun,
    proofs: Sequence[ProofRecord],
    items: Sequence[ReasoningItem],
    states: dict[str, TracedStep],
    on_shard: Callable[[str], None],
) -> None:
    """Every pending shard (proofs first), a few at a time so the pool stays busy; finished shards are skipped."""
    size = run.config.shard_size
    check_plan(run.directory, [record.identifier for record in proofs], [example_key(item) for item in items], size)
    gate = asyncio.Semaphore(run.config.shards_in_flight)

    async def gated(name: str, work: Awaitable[None]) -> None:
        async with gate:
            await work
            on_shard(name)

    tasks = [
        gated(f"proofs {index}", run.proof_shard(index, shard))
        for index, shard in enumerate(shards(proofs, size))
        if not run.directory.proofs(index).exists()
    ] + [
        gated(f"examples {index}", run.example_shard(index, shard, states))
        for index, shard in enumerate(shards(items, size))
        if not run.directory.examples(index).exists()
    ]
    await asyncio.gather(*tasks)
