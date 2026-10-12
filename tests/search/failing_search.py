"""A program whose expander raises in one search while another search runs in Lean; it must exit with that error."""

import asyncio

from lean_search.data import Problem, Split
from lean_search.lean import LeanReplPool
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    CompletedSearch,
    DepthPlusGoals,
    Node,
    SearchConfig,
    SearchContext,
    StepSource,
    search_problems,
)

HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
ALWAYS_PROGRESSES = "have : (1 : ℕ) = 1 := rfl"
FAILURE_MESSAGE = "the expander failed"
FAILING_CALL = 4


class FailingPolicy:
    def __init__(self) -> None:
        self.calls = 0

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        self.calls += 1
        if self.calls == FAILING_CALL:
            raise RuntimeError(FAILURE_MESSAGE)
        yield CandidateBatch((Candidate(ALWAYS_PROGRESSES, StepSource.POLICY),))


async def ignore(completed: CompletedSearch) -> None:
    pass


async def search() -> None:
    problems = [
        Problem(
            f"squares_{index}",
            Split.VALID,
            HEADER,
            f"theorem squares_{index} (a b : ℕ) : a * b = b * a := by\n",
            "",
            "",
        )
        for index in range(3)
    ]
    # Without the failure every search would run for minutes.
    config = SearchConfig(max_expansions=10**6, max_depth=10**6, max_wall_seconds=600.0)
    async with LeanReplPool(2) as pool:
        await pool.start([HEADER])
        await search_problems(problems, pool, FailingPolicy(), DepthPlusGoals(), config, 2, ignore)


if __name__ == "__main__":
    asyncio.run(search())
