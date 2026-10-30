import asyncio
import contextlib

from search_trees import new_tree

from lean_search.data import Problem, Split
from lean_search.lean import LeanRepl
from lean_search.search import (
    Candidate,
    CandidateBatch,
    CandidateBatches,
    CompositeExpander,
    Node,
    SearchContext,
    StepSource,
)


class Request:
    """One batch per expansion, yielded once `released` is set; records whether it started and was cancelled."""

    def __init__(self, step: str, generated_tokens: int, released: bool = True) -> None:
        self.batch = CandidateBatch((Candidate(step, StepSource.POLICY),), generated_tokens=generated_tokens)
        self.released = asyncio.Event()
        if released:
            self.released.set()
        self.started = False
        self.cancelled = False

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        self.started = True
        try:
            await self.released.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield self.batch


def search_context() -> SearchContext:
    problem = Problem("t", Split.VALID, "", "theorem t : True := by\n", informal_prefix="", goal="")
    return SearchContext(problem, new_tree("⊢ True"), LeanRepl())


async def test_later_expander_starts_while_the_first_batch_runs() -> None:
    context = search_context()
    later = Request("simp", 10, released=False)
    expander = CompositeExpander([Request("rfl", 0), later], overlap=True)
    async with contextlib.aclosing(expander.expand(context.tree.root, context)) as batches:
        await anext(batches)
        await asyncio.sleep(0)
        assert later.started
        later.released.set()


async def test_overlapped_batches_keep_the_expander_order() -> None:
    context = search_context()
    first, later = Request("rfl", 0), Request("simp", 10)
    expander = CompositeExpander([first, later], overlap=True)
    batches = [batch async for batch in expander.expand(context.tree.root, context)]
    assert batches == [first.batch, later.batch]


async def test_without_overlap_the_later_expander_waits_for_the_first_batch() -> None:
    context = search_context()
    later = Request("simp", 10)
    expander = CompositeExpander([Request("rfl", 0), later])
    async with contextlib.aclosing(expander.expand(context.tree.root, context)) as batches:
        await anext(batches)
        await asyncio.sleep(0)
        assert not later.started


async def test_batch_the_search_stopped_before_is_left_as_abandoned() -> None:
    context = search_context()
    later = Request("simp", 10)
    expander = CompositeExpander([Request("rfl", 0), later], overlap=True)
    async with contextlib.aclosing(expander.expand(context.tree.root, context)) as batches:
        await anext(batches)
    assert context.abandoned_batches == [later.batch]


async def test_cancelled_search_cancels_the_overlapped_request() -> None:
    context = search_context()
    later = Request("simp", 10, released=False)
    expander = CompositeExpander([Request("rfl", 0), later], overlap=True)

    async def run_first_batch_forever() -> None:
        async with contextlib.aclosing(expander.expand(context.tree.root, context)) as batches:
            await anext(batches)
            await asyncio.Event().wait()

    search = asyncio.create_task(run_first_batch_forever())
    await asyncio.sleep(0.01)
    search.cancel()
    await asyncio.gather(search, return_exceptions=True)
    await asyncio.sleep(0)
    assert later.cancelled


class TwoRequests:
    """A first batch, then a second request made only when the search asks for the next batch."""

    def __init__(self) -> None:
        self.first = CandidateBatch((Candidate("simp", StepSource.POLICY),))
        self.second = CandidateBatch((Candidate("omega", StepSource.POLICY),))
        self.second_requested = False

    async def expand(self, node: Node, context: SearchContext) -> CandidateBatches:
        yield self.first
        self.second_requested = True
        yield self.second


async def test_overlapped_expander_requests_its_next_batch_only_when_asked() -> None:
    context = search_context()
    later = TwoRequests()
    expander = CompositeExpander([Request("rfl", 0), later], overlap=True)
    async with contextlib.aclosing(expander.expand(context.tree.root, context)) as batches:
        await anext(batches)
        await anext(batches)
        await asyncio.sleep(0)
        assert not later.second_requested


async def test_overlapped_expander_yields_all_its_batches_in_order() -> None:
    context = search_context()
    first, later = Request("rfl", 0), TwoRequests()
    expander = CompositeExpander([first, later], overlap=True)
    batches = [batch async for batch in expander.expand(context.tree.root, context)]
    assert batches == [first.batch, later.first, later.second]


async def test_search_stopping_after_a_later_first_batch_never_requests_its_second() -> None:
    context = search_context()
    later = TwoRequests()
    expander = CompositeExpander([Request("rfl", 0), later], overlap=True)
    async with contextlib.aclosing(expander.expand(context.tree.root, context)) as batches:
        await anext(batches)
        await anext(batches)
    assert (later.second_requested, context.abandoned_batches) == (False, [])
