"""Visible-mode explanations for chunk examples: a teacher (the served namer model) writes the plan before a block."""

import asyncio
import contextlib
import dataclasses
import itertools
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field

import httpx

from lean_search.corpora.records import DataSplit
from lean_search.data_rewrite.dataset import (
    ChunkPosition,
    NameVariant,
    PlannedChunk,
    chunk_block,
    ordered,
    reasoning_key,
    rewritten_example,
    usable_example,
)
from lean_search.data_rewrite.naming import NameChange, collapsed, renamed_text
from lean_search.data_rewrite.records import (
    ChunkExplanation,
    ExplanationOutcome,
    ExplanationRejection,
    NamedStatus,
    RejectedExplanation,
    RewrittenExample,
)
from lean_search.data_rewrite.rewrite import RewriteDirectory, ensure_plan, shard_digest, shards
from lean_search.lean.text import FORBIDDEN_TOKENS, find_forbidden_tokens, split_tactics
from lean_search.policy.client import ChatMessage, PolicyClient
from lean_search.policy.prompts import END_OF_TURN, FENCE, LENGTH_FINISH_REASON, THINK_END, THINK_START, user_message
from lean_search.reasoning.dataset import ReasoningOrigin
from lean_search.reasoning.records import write_records

EXPLAINER_SYSTEM_PROMPT = (
    "You are a Lean 4 and Mathlib expert. Given a proof state and the tactics a prover writes next, you write the "
    "short explanation the prover gives right before them: the key idea, what to do and why it works."
)
EXPLANATION_INSTRUCTION = (
    "Write the explanation that comes right before these tactics: the prover's plan in a few sentences of plain prose "
    "(at most about 80 words), what to do and why it works. Do not walk through the tactics line by line, do not "
    "mention that they are given and do not restate the goal. Write no code blocks; mention Lean only as short inline "
    "names or expressions in backticks. Reply with the explanation only."
)
MARKUP = (THINK_START, THINK_END, END_OF_TURN, "<|im_start|>", "<|endoftext|>")
REJECTED_TEXT_CHARACTERS = 300
# A quoted block or tactic shorter than this is an ordinary mention (`linarith`), not a copy.
MINIMUM_COPIED_BLOCK_CHARACTERS = 24
MINIMUM_QUOTED_TACTIC_CHARACTERS = 12
# Forbidden tokens that are also English words count only inside inline code.
ENGLISH_FORBIDDEN_TOKENS = frozenset({"stop", "hint", "observe", "sleep", "extern", "unsafe", "admit"})
_INLINE_CODE = re.compile(r"`([^`]*)`")
_LABEL = re.compile(r"\s*(?:\*\*|#|(?:explanation|plan|reasoning|answer)\s*:)", re.IGNORECASE)
# Cyrillic, Arabic, Thai, kana, CJK ideographs, Hangul.
_OTHER_SCRIPTS = (
    (0x0400, 0x04FF),
    (0x0600, 0x06FF),
    (0x0E00, 0x0E7F),
    (0x3040, 0x30FF),
    (0x3400, 0x9FFF),
    (0xAC00, 0xD7AF),
)
_NOT_ENGLISH = re.compile("[" + "".join(f"{chr(first)}-{chr(last)}" for first, last in _OTHER_SCRIPTS) + "]")
_GIVEN_BLOCK = re.compile(
    r"\b(?:given|provided|above|below|shown)\s+(?:tactics?|block|code|steps?|lines?)\b", re.IGNORECASE
)
_FORBIDDEN_IN_PROSE = re.compile(
    r"(?<![\w.])(?:"
    + "|".join(re.escape(token) for token in sorted(FORBIDDEN_TOKENS - ENGLISH_FORBIDDEN_TOKENS, key=len, reverse=True))
    + r")(?![\w?!])"
)
# Spellings a name keeps in prose and LaTeX: `h₀` as `h_0` or `h_{0}`, `hx_pos` as `hx\_pos`.
_LOOSE = str.maketrans("₀₁₂₃₄₅₆₇₈₉", "0123456789", "\\{}_$")


@dataclass(frozen=True)
class TeacherServer:
    # The name the server serves the model under (serve_model.sh's first argument).
    model: str
    base_url: str


@dataclass(frozen=True)
class TeacherConfig:
    # Replicas of one model: the namer of the rewrite pass and any started beside it; requests go round-robin.
    servers: tuple[TeacherServer, ...] = ()
    max_tokens: int = 384
    # Above 0, so that the retry differs.
    temperature: float = 0.7
    top_p: float = 0.95
    requests_in_flight: int = 64
    request_timeout_seconds: float = 600.0
    enable_thinking: bool = False


@dataclass(frozen=True)
class ExplanationBounds:
    # The visible explanations of the reasoning data: p1 38, p50 199, p99 ~1,000 characters.
    min_characters: int = 30
    max_characters: int = 1000
    # Inline code there: p50 6, p99 44 characters.
    max_inline_code_characters: int = 80


@dataclass(frozen=True)
class FewShotConfig:
    # One per block length 1, 2, …, the last of that many tactics or more.
    examples: int = 4
    max_goal_characters: int = 600
    max_explanation_characters: int = 500


@dataclass(frozen=True)
class ExplainConfig:
    teacher: TeacherConfig = field(default_factory=TeacherConfig)
    bounds: ExplanationBounds = field(default_factory=ExplanationBounds)
    few_shot: FewShotConfig = field(default_factory=FewShotConfig)
    attempts: int = 2
    shard_size: int = 1000
    shards_in_flight: int = 2
    seed: str = "chunk-explanations"


@dataclass(frozen=True)
class ExplainedBlock:
    goals: tuple[str, ...]
    tactic_block: str
    explanation: str


@dataclass(frozen=True)
class ExplanationRequest:
    position: ChunkPosition
    # The named chunk (the numbered one when nothing is renamed).
    goals: tuple[str, ...]
    tactic_block: str
    # Numbered to named; empty when nothing is renamed.
    changes: tuple[NameChange, ...]


@dataclass(frozen=True)
class TeacherReply:
    text: str
    finish_reason: str


@dataclass(frozen=True)
class AcceptedExplanation:
    named: str
    numbered: str


def explanation_request(planned: PlannedChunk) -> ExplanationRequest:
    named = planned.versions.record.named
    changes = (*named.statement_changes, *named.have_changes) if named.status is NamedStatus.RENAMED else ()
    version = planned.versions.named
    block = chunk_block(version, planned.chunk)
    return ExplanationRequest(planned.position, version.goals[planned.chunk.start], block, changes)


def explanation_user_message(goals: Sequence[str], tactic_block: str) -> str:
    return f"{user_message(goals)}\n\nNext tactics:\n```lean\n{tactic_block}\n```\n\n{EXPLANATION_INSTRUCTION}"


def explanation_messages(
    goals: Sequence[str], tactic_block: str, few_shots: Sequence[ExplainedBlock]
) -> list[ChatMessage]:
    """The same system prompt and few-shot turns for every chunk, so the server caches them as one prefix."""
    messages = [ChatMessage("system", EXPLAINER_SYSTEM_PROMPT)]
    for example in few_shots:
        messages.append(ChatMessage("user", explanation_user_message(example.goals, example.tactic_block)))
        messages.append(ChatMessage("assistant", example.explanation))
    messages.append(ChatMessage("user", explanation_user_message(goals, tactic_block)))
    return messages


def loosened(text: str) -> str:
    return text.translate(_LOOSE)


def mentions_loosely(text: str, name: str) -> bool:
    return re.search(rf"(?<![\w']){re.escape(loosened(name))}(?![\w'])", loosened(text)) is not None


def inverse_changes(changes: Sequence[NameChange]) -> tuple[NameChange, ...]:
    return tuple(dataclasses.replace(change, old=change.new, new=change.old) for change in changes)


def copies_block(text: str, tactic_block: str) -> bool:
    block = collapsed(tactic_block)
    return len(block) >= MINIMUM_COPIED_BLOCK_CHARACTERS and block in collapsed(text)


def walks_through_tactics(text: str, tactic_block: str) -> bool:
    """At least two tactics, and at least half of them, quoted verbatim with their arguments."""
    tactics = [collapsed(tactic) for tactic in split_tactics(tactic_block)]
    quoted = sum(len(tactic) >= MINIMUM_QUOTED_TACTIC_CHARACTERS and tactic in collapsed(text) for tactic in tactics)
    return quoted >= 2 and 2 * quoted >= len(tactics)


def explanation_rejection(
    text: str, finish_reason: str, tactic_block: str, bounds: ExplanationBounds
) -> ExplanationRejection | None:
    """What makes a reply unusable as an explanation before this block, in either variant's names."""
    inline_code = _INLINE_CODE.findall(text)
    if finish_reason == LENGTH_FINISH_REASON:
        return ExplanationRejection.TRUNCATED
    if not text:
        return ExplanationRejection.EMPTY
    if any(marker in text for marker in MARKUP):
        return ExplanationRejection.MARKUP
    if FENCE in text:
        return ExplanationRejection.CODE_BLOCK
    if _LABEL.match(text):
        return ExplanationRejection.LABEL
    if len(text) < bounds.min_characters:
        return ExplanationRejection.TOO_SHORT
    if len(text) > bounds.max_characters:
        return ExplanationRejection.TOO_LONG
    if _NOT_ENGLISH.search(text):
        return ExplanationRejection.NOT_ENGLISH
    if any(len(code) > bounds.max_inline_code_characters or "\n" in code for code in inline_code):
        return ExplanationRejection.LONG_INLINE_CODE
    if _FORBIDDEN_IN_PROSE.search(text) or any(find_forbidden_tokens(code) for code in inline_code):
        return ExplanationRejection.FORBIDDEN_TOKEN
    if copies_block(text, tactic_block):
        return ExplanationRejection.COPIES_BLOCK
    if walks_through_tactics(text, tactic_block):
        return ExplanationRejection.LINE_BY_LINE
    if _GIVEN_BLOCK.search(text):
        return ExplanationRejection.MENTIONS_GIVEN_BLOCK
    return None


def judge_explanation(
    reply: TeacherReply, tactic_block: str, changes: Sequence[NameChange], bounds: ExplanationBounds
) -> AcceptedExplanation | ExplanationRejection:
    """The explanation in both variants, or why the reply is rejected."""
    text = reply.text.strip()
    if (rejection := explanation_rejection(text, reply.finish_reason, tactic_block, bounds)) is not None:
        return rejection
    if any(mentions_loosely(text, change.old) for change in changes):
        return ExplanationRejection.STALE_NAME
    numbered = renamed_text(text, inverse_changes(changes))
    if any(mentions_loosely(numbered, change.new) for change in changes):
        return ExplanationRejection.UNRENAMED_NAME
    return AcceptedExplanation(text, numbered)


def explanation_record(
    request: ExplanationRequest, replies: Sequence[TeacherReply], bounds: ExplanationBounds
) -> ChunkExplanation:
    """The first accepted reply with the rejected ones before it; rejected when no reply is accepted."""
    rejected: list[RejectedExplanation] = []
    for reply in replies:
        match judge_explanation(reply, request.tactic_block, request.changes, bounds):
            case AcceptedExplanation(named=named, numbered=numbered):
                return ChunkExplanation(
                    *request.position, ExplanationOutcome.EXPLAINED, named, numbered, tuple(rejected)
                )
            case ExplanationRejection() as rejection:
                rejected.append(RejectedExplanation(rejection, reply.text.strip()[:REJECTED_TEXT_CHARACTERS]))
    return ChunkExplanation(*request.position, ExplanationOutcome.REJECTED, "", "", tuple(rejected))


def few_shot_explanations(examples: Sequence[RewrittenExample], config: ExplainConfig) -> tuple[ExplainedBlock, ...]:
    """Real visible explanations (named, flat block) as style references, one per block length, shortest first."""
    few_shot = config.few_shot
    candidates: list[ExplainedBlock] = []
    for record in ordered(examples, reasoning_key, f"{config.seed} few-shot"):
        if not (
            usable_example(record)
            and record.split is DataSplit.TRAIN
            and record.original.visible
            and record.original.origin is ReasoningOrigin.SAMPLED
        ):
            continue
        example = rewritten_example(record, NameVariant.NAMED)
        explanation = (example.reasoning or "").strip()
        if (
            len("\n\n".join(example.goals)) <= few_shot.max_goal_characters
            and len(explanation) <= few_shot.max_explanation_characters
            and explanation_rejection(explanation, "stop", example.tactic_block, config.bounds) is None
        ):
            candidates.append(ExplainedBlock(example.goals, example.tactic_block, explanation))
    chosen = (
        next(
            (
                candidate
                for candidate in candidates
                if min(len(split_tactics(candidate.tactic_block)), few_shot.examples) == length
            ),
            None,
        )
        for length in range(1, few_shot.examples + 1)
    )
    return tuple(example for example in chosen if example is not None)


class ChunkTeacher:
    def __init__(
        self, clients: Sequence[PolicyClient], config: ExplainConfig, few_shots: Sequence[ExplainedBlock]
    ) -> None:
        self._clients = itertools.cycle(clients)
        self.config = config
        self.few_shots = tuple(few_shots)

    async def explain(self, request: ExplanationRequest) -> ChunkExplanation:
        teacher = self.config.teacher
        messages = explanation_messages(request.goals, request.tactic_block, self.few_shots)
        replies: list[TeacherReply] = []
        for _ in range(self.config.attempts):
            try:
                generation = await next(self._clients).generate_chat(
                    messages,
                    enable_thinking=teacher.enable_thinking,
                    sample_count=1,
                    max_tokens=teacher.max_tokens,
                    temperature=teacher.temperature,
                    top_p=teacher.top_p,
                )
            except httpx.HTTPStatusError:
                # A request the server refuses (e.g. a prompt over its context) leaves the chunk non-visible.
                record = explanation_record(request, replies, self.config.bounds)
                return dataclasses.replace(record, outcome=ExplanationOutcome.REQUEST_FAILED)
            sample = generation.samples[0]
            replies.append(TeacherReply(sample.text, sample.finish_reason))
            judged = judge_explanation(replies[-1], request.tactic_block, request.changes, self.config.bounds)
            if isinstance(judged, AcceptedExplanation):
                break
        return explanation_record(request, replies, self.config.bounds)


@contextlib.asynccontextmanager
async def open_teacher(config: ExplainConfig, few_shots: Sequence[ExplainedBlock]) -> AsyncIterator[ChunkTeacher]:
    teacher = config.teacher
    if not teacher.servers:
        raise ValueError("The explain pass needs a served teacher model (teacher.servers).")
    async with contextlib.AsyncExitStack() as stack:
        clients = [
            await stack.enter_async_context(
                PolicyClient(server.base_url, server.model, teacher.request_timeout_seconds, teacher.requests_in_flight)
            )
            for server in teacher.servers
        ]
        yield ChunkTeacher(clients, config, few_shots)


def request_key(request: ExplanationRequest) -> str:
    position = request.position
    return f"{position.proof_identifier}#{position.start}#{position.tactics}"


async def explain_chunks(
    teacher: ChunkTeacher,
    requests: Sequence[ExplanationRequest],
    directory: RewriteDirectory,
    on_shard: Callable[[int, Sequence[ChunkExplanation]], None],
) -> None:
    """Every pending shard of requests, a few at a time; finished shards are skipped (resumable)."""
    size = teacher.config.shard_size
    keys = [request_key(request) for request in requests]
    plan = {"shard_size": size, "chunks": [shard_digest(part) for part in shards(keys, size)]}
    ensure_plan(directory.explanation_plan, plan)
    gate = asyncio.Semaphore(teacher.config.shards_in_flight)

    async def explain_shard(index: int, part: Sequence[ExplanationRequest]) -> None:
        async with gate:
            explained = await asyncio.gather(*map(teacher.explain, part))
            await asyncio.to_thread(write_records, directory.explanations(index), explained)
            on_shard(index, explained)

    await asyncio.gather(
        *(
            explain_shard(index, part)
            for index, part in enumerate(shards(requests, size))
            if not directory.explanations(index).exists()
        )
    )
