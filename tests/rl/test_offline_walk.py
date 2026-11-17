"""The walk's block construction against a stand-in for the Lean REPL process (the walk's only external boundary): a
goal list on which `close` closes the first goal, `split` makes two of it, `noop` changes nothing, `fail` is a Lean
error and any other tactic replaces the first goal by its own text. tests/rl/test_offline_walk_lean.py runs real
Lean."""

import itertools
import random
from collections.abc import Callable

from lean_search.data import Problem, Split
from lean_search.lean import LeanError, ProofState
from lean_search.lean.plans import TacticPlan
from lean_search.lean.repl import BlockResult, TacticResult
from lean_search.lean.text import FORBIDDEN_TOKENS
from lean_search.rl.offline_walk import ProofWalk, WalkSettings, WalkStatus, walk_candidates, walk_proof

PROBLEM = Problem("pool.p", Split.VALID, "import Mathlib", "theorem p : True := by", "", "")
ROOT_GOALS = ("⊢ root",)


def settings(max_block_tactics: int = 5) -> WalkSettings:
    return WalkSettings(
        heartbeats=50_000,
        timeout_seconds=60.0,
        flatten=True,
        name_hypotheses=True,
        check_identifiers=False,
        environment_names_directory="",
        forbidden_steps=("exact?",),
        forbidden_tokens=FORBIDDEN_TOKENS | {"exact?"},
        max_block_tactics=max_block_tactics,
    )


class ScriptedRepl:
    def __init__(self) -> None:
        self.blocks: list[tuple[str, ...]] = []

    async def start_proof(self, statement: str, header: str) -> TacticResult:
        return TacticResult(ProofState(header, statement, (), ROOT_GOALS, 0, 1), 0.0)

    async def apply_block(
        self, state: ProofState, plan: TacticPlan, heartbeats: int | None = None, timeout_seconds: float | None = None
    ) -> BlockResult:
        self.blocks.append(plan.texts)
        goals = list(state.goals)
        applied: list[str] = []
        for tactic in plan.texts:
            if not goals:
                break
            match tactic:
                case "fail":
                    return BlockResult(state, tuple(applied), len(plan.tactics), LeanError("failed"), 0.0, plan.tactics)
                case "close":
                    goals.pop(0)
                case "split":
                    goals[0:1] = [f"{goals[0]} a", f"{goals[0]} b"]
                case "noop":
                    pass
                case _:
                    goals[0] = f"⊢ {tactic}"
            applied.append(tactic)
        after = ProofState(state.header, state.statement, (*state.tactics, *applied), tuple(goals), 0, 1)
        return BlockResult(after, tuple(applied), len(plan.tactics), None, 0.0, plan.tactics)


class FixedLengths(random.Random):
    def __init__(self, length: int) -> None:
        super().__init__(0)
        self.length = length

    def randint(self, a: int, b: int) -> int:
        return self.length


def always(block: str) -> bool:
    return True


async def walk(
    proof: str, length: int = 2, fits: Callable[[str], bool] = always, maximum: int = 5
) -> tuple[ScriptedRepl, ProofWalk]:
    repl = ScriptedRepl()
    found = await walk_proof(repl, PROBLEM, proof, settings(maximum), FixedLengths(length), fits)
    return repl, found


async def test_a_proof_walks_to_the_end() -> None:
    _, found = await walk("step 1\nstep 2\nstep 3\nclose")
    assert found.status == WalkStatus.COMPLETE


async def test_the_blocks_together_are_the_proofs_steps_in_order() -> None:
    _, found = await walk("step 1\nstep 2\nstep 3\nclose", length=3)
    steps = list(itertools.chain.from_iterable(block.block.split("\n") for block in found.blocks))
    assert steps == ["step 1", "step 2", "step 3", "close"]


async def test_a_block_takes_the_drawn_number_of_steps() -> None:
    _, found = await walk("step 1\nstep 2\nstep 3\nstep 4\nclose", length=2)
    assert [block.tactics for block in found.blocks] == [2, 2, 1]


async def test_each_block_is_prompted_with_the_state_before_it() -> None:
    _, found = await walk("step 1\nstep 2\nclose", length=1)
    assert [block.goals for block in found.blocks] == [ROOT_GOALS, ("⊢ step 1",), ("⊢ step 2",)]


async def test_drawn_lengths_stay_within_one_and_the_maximum() -> None:
    repl = ScriptedRepl()
    proof = "\n".join(f"step {number}" for number in range(40)) + "\nclose"
    found = await walk_proof(repl, PROBLEM, proof, settings(3), random.Random(7), always)
    assert {block.tactics for block in found.blocks} <= {1, 2, 3}


async def test_a_failing_step_fails_the_walk() -> None:
    _, found = await walk("step 1\nfail\nclose", length=1)
    assert (found.status, found.failing_block) == (WalkStatus.BLOCK_FAILED, 1)


async def test_a_block_after_which_the_proof_is_closed_keeps_only_the_steps_that_ran() -> None:
    _, found = await walk("step 1\nclose\nstep 2", length=3)
    assert [block.block for block in found.blocks] == ["step 1\nclose"]


async def test_a_block_that_changes_nothing_revisits_a_state() -> None:
    _, found = await walk("step 1\nnoop\nclose", length=1)
    assert found.status == WalkStatus.REVISITED_STATE


async def test_a_forbidden_token_fails_the_walk_before_lean_runs_it() -> None:
    repl, found = await walk("step 1\nsorry", length=2)
    assert (found.status, repl.blocks) == (WalkStatus.FORBIDDEN, [])


async def test_a_forbidden_step_fails_the_walk() -> None:
    _, found = await walk("exact?", length=1)
    assert found.status == WalkStatus.FORBIDDEN


async def test_goals_left_after_the_last_step_fail_the_walk() -> None:
    _, found = await walk("split\nclose", length=1)
    assert found.status == WalkStatus.GOALS_REMAIN


async def test_a_block_over_the_completion_cap_falls_back_to_fewer_steps() -> None:
    _, found = await walk("step 1\nstep 2\nstep 3\nclose", length=3, fits=lambda block: "\n" not in block)
    assert [block.tactics for block in found.blocks] == [1, 1, 1, 1]


async def test_a_single_step_over_the_cap_runs_without_an_example() -> None:
    _, found = await walk("step 1\nlong 2\nclose", length=1, fits=lambda block: "long" not in block)
    assert (found.status, len(found.blocks), found.skipped_blocks) == (WalkStatus.COMPLETE, 2, 1)


async def test_the_first_candidate_that_walks_is_taken() -> None:
    walked = await walk_candidates(
        ScriptedRepl(),
        PROBLEM,
        ["fail", "close"],
        settings(),
        "seed",
        always,
        lambda: 0.0,
    )
    assert (walked.candidate, walked.attempts) == (1, (WalkStatus.BLOCK_FAILED, WalkStatus.COMPLETE))


async def test_without_a_walking_candidate_the_first_ones_walk_is_kept() -> None:
    walked = await walk_candidates(
        ScriptedRepl(),
        PROBLEM,
        ["fail", "split\nclose"],
        settings(),
        "seed",
        always,
        lambda: 0.0,
    )
    assert (walked.candidate, walked.walk.status) == (None, WalkStatus.BLOCK_FAILED)
