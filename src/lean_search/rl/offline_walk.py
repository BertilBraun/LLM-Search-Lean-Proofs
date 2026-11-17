"""A known proof walked in Lean the way the search runs the policy's blocks without reasoning, into the offline arm's
examples (rl/offline_arm.py).

The proof is flattened as the search flattens a policy block (`plan_block`: nested `have … := by` proofs and `·` blocks
become steps). From the root, named as the search names a new state, the walk draws a block length k from 1 to
`max_block_tactics`, takes the next k steps as one block, normalized as the search normalizes a sample's block, and runs
it as the search runs a policy block: refused for a forbidden step or token, planned with the identifier check, applied
at the search's heartbeat and wall-clock limits. The state after it, named, is the next block's start; so to the end. A
block over the policy's completion cap falls back to fewer steps; a single step over it still runs but gives no
example. The walk fails at the first block the search would not run to the next state, at a revisited state (a block
that made no progress), or with goals left after the last step; a failed walk gives no example at all.
"""

import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from lean_search.data import Problem
from lean_search.lean import LeanRepl, ProofState
from lean_search.lean.plans import plan_block
from lean_search.lean.text import find_forbidden_tokens, join_tactics
from lean_search.policy.prompts import normalize_tactic_block
from lean_search.search.search import ForbiddenSteps, IdentifierCheck, identifier_check, named_state, policy_plan

MAX_FAILURE_CHARACTERS = 300


class WalkStatus(StrEnum):
    COMPLETE = "complete"
    START_FAILED = "start failed"
    FORBIDDEN = "forbidden step or token"
    BLOCK_FAILED = "block failed"
    REVISITED_STATE = "revisited a state"
    GOALS_REMAIN = "goals remain after the last step"
    # The walk raised (a REPL that could not be restarted, ...): recorded by the caller.
    ERROR = "the walk raised"


@dataclass(frozen=True)
class WalkSettings:
    """The search's handling of a policy block (SearchConfig, the expander's forbidden tokens)."""

    heartbeats: int
    timeout_seconds: float
    flatten: bool
    name_hypotheses: bool
    check_identifiers: bool
    environment_names_directory: str
    forbidden_steps: tuple[str, ...]
    forbidden_tokens: frozenset[str]
    max_block_tactics: int


@dataclass(frozen=True)
class WalkBlock:
    goals: tuple[str, ...]
    block: str
    tactics: int


@dataclass(frozen=True)
class ProofWalk:
    status: WalkStatus
    blocks: tuple[WalkBlock, ...]
    # Blocks run without an example: one step over the completion cap.
    skipped_blocks: int = 0
    failure: str = ""
    # The block (0-based) the walk failed at.
    failing_block: int | None = None


@dataclass(frozen=True)
class WalkedProof:
    name: str
    # The first candidate proof that walked to the end, else None.
    candidate: int | None
    # Per candidate tried, its walk's status.
    attempts: tuple[WalkStatus, ...]
    walk: ProofWalk
    seconds: float


def first_line(message: str) -> str:
    return message.strip().split("\n", 1)[0][:MAX_FAILURE_CHARACTERS]


def failed(status: WalkStatus, blocks: Sequence[WalkBlock], skipped: int, message: str, index: int) -> ProofWalk:
    return ProofWalk(status, tuple(blocks), skipped, first_line(message), index)


async def walk_proof(
    repl: LeanRepl,
    problem: Problem,
    tactic_proof: str,
    settings: WalkSettings,
    lengths: random.Random,
    fits: Callable[[str], bool],
) -> ProofWalk:
    """`fits`: whether a block's completion is within the policy's cap."""
    steps = plan_block(tactic_proof, flatten=settings.flatten).texts
    start = await repl.start_proof(problem.formal_statement, problem.header)
    match start.outcome:
        case ProofState() as root:
            state = root
        case failure:
            return failed(WalkStatus.START_FAILED, (), 0, failure.message, 0)
    if settings.name_hypotheses:
        state, _ = await named_state(repl, state)
    check: IdentifierCheck | None = None
    if settings.check_identifiers:
        check = await identifier_check(repl, problem, settings.environment_names_directory)
    forbidden_steps = ForbiddenSteps(settings.forbidden_steps)
    seen = {state.goal_key}
    blocks: list[WalkBlock] = []
    skipped = 0
    position = 0
    while position < len(steps):
        count = min(lengths.randint(1, settings.max_block_tactics), len(steps) - position)
        block = normalize_tactic_block(join_tactics(steps[position : position + count]))
        while count > 1 and not fits(block):
            count -= 1
            block = normalize_tactic_block(join_tactics(steps[position : position + count]))
        forbidden = forbidden_steps.find(block) or find_forbidden_tokens(block, settings.forbidden_tokens)
        if forbidden:
            return failed(WalkStatus.FORBIDDEN, blocks, skipped, ", ".join(forbidden), len(blocks) + skipped)
        plan = policy_plan(block, state.goals, settings.flatten, check)
        result = await repl.apply_block(state, plan, settings.heartbeats, settings.timeout_seconds)
        if result.failure is not None:
            return failed(WalkStatus.BLOCK_FAILED, blocks, skipped, result.failure.message, len(blocks) + skipped)
        if result.state.is_proved and len(result.applied_tactics) < len(result.tactics):
            # The goals closed before the block's last step: the example is the part that ran.
            block = normalize_tactic_block(join_tactics(result.applied_tactics))
            count = len(result.applied_tactics)
        emitted = fits(block)
        skipped += not emitted
        if result.state.is_proved:
            if emitted:
                blocks.append(WalkBlock(state.goals, block, count))
            return ProofWalk(WalkStatus.COMPLETE, tuple(blocks), skipped)
        following = (await named_state(repl, result.state))[0] if settings.name_hypotheses else result.state
        if following.goal_key in seen:
            return failed(WalkStatus.REVISITED_STATE, blocks, skipped, block, len(blocks) + skipped)
        seen.add(following.goal_key)
        if emitted:
            blocks.append(WalkBlock(state.goals, block, count))
        state = following
        position += count
    return failed(WalkStatus.GOALS_REMAIN, blocks, skipped, "\n\n".join(state.goals), len(blocks) + skipped)


async def walk_candidates(
    repl: LeanRepl,
    problem: Problem,
    candidates: Sequence[str],
    settings: WalkSettings,
    seed: str,
    fits: Callable[[str], bool],
    clock: Callable[[], float],
) -> WalkedProof:
    """The candidates in order until one walks to the end (each with the statement's own block lengths); the first
    candidate's walk when none does."""
    started = clock()
    attempts: list[ProofWalk] = []
    for index, tactic_proof in enumerate(candidates):
        lengths = random.Random(f"{seed}\n{problem.name}")
        walk = await walk_proof(repl, problem, tactic_proof, settings, lengths, fits)
        attempts.append(walk)
        if walk.status == WalkStatus.COMPLETE:
            statuses = tuple(attempt.status for attempt in attempts)
            return WalkedProof(problem.name, index, statuses, walk, clock() - started)
    return WalkedProof(
        problem.name, None, tuple(attempt.status for attempt in attempts), attempts[0], clock() - started
    )
