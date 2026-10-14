import asyncio

from lean_search.expert_iteration.search_slots import SearchSlots


async def test_a_search_escalates_at_once_below_the_cap() -> None:
    slots = SearchSlots(capacity=2, escalated_capacity=1, max_waiting=2)
    assert await slots.escalate(await slots.start(), 1.0)


async def test_without_a_queue_a_full_cap_retires_the_search() -> None:
    slots = SearchSlots(capacity=2, escalated_capacity=1, max_waiting=0)
    await slots.escalate(await slots.start(), 1.0)
    assert not await slots.escalate(await slots.start(), 1.0)


async def test_a_waiting_search_frees_its_active_slot() -> None:
    slots = SearchSlots(capacity=2, escalated_capacity=1, max_waiting=2)
    await slots.escalate(await slots.start(), 1.0)
    waiting = asyncio.ensure_future(slots.escalate(await slots.start(), 1.0))
    await asyncio.sleep(0)
    fresh = await asyncio.wait_for(slots.start(), timeout=1.0)
    assert (fresh.active, waiting.done(), slots.active) == (True, False, 2)


async def test_a_waiting_search_resumes_when_an_escalated_one_ends() -> None:
    slots = SearchSlots(capacity=2, escalated_capacity=1, max_waiting=2)
    escalated = await slots.start()
    await slots.escalate(escalated, 1.0)
    waiting = asyncio.ensure_future(slots.escalate(await slots.start(), 1.0))
    await asyncio.sleep(0)
    slots.finish(escalated)
    assert await asyncio.wait_for(waiting, timeout=1.0)


async def test_the_most_promising_waiter_resumes_first() -> None:
    slots = SearchSlots(capacity=3, escalated_capacity=1, max_waiting=2)
    escalated = await slots.start()
    await slots.escalate(escalated, 1.0)
    far = asyncio.ensure_future(slots.escalate(await slots.start(), 2.5))
    near = asyncio.ensure_future(slots.escalate(await slots.start(), 0.5))
    await asyncio.sleep(0)
    slots.finish(escalated)
    await asyncio.sleep(0)
    assert (near.done(), far.done()) == (True, False)


async def test_a_full_queue_retires_the_least_promising_waiter() -> None:
    slots = SearchSlots(capacity=3, escalated_capacity=1, max_waiting=1)
    await slots.escalate(await slots.start(), 1.0)
    far = asyncio.ensure_future(slots.escalate(await slots.start(), 2.5))
    near = asyncio.ensure_future(slots.escalate(await slots.start(), 0.5))
    await asyncio.sleep(0)
    assert (await asyncio.wait_for(far, timeout=1.0), near.done(), slots.waiting) == (False, False, 1)


async def test_a_retired_waiter_holds_no_slot() -> None:
    slots = SearchSlots(capacity=3, escalated_capacity=1, max_waiting=1)
    await slots.escalate(await slots.start(), 1.0)
    far_lease = await slots.start()
    far = asyncio.ensure_future(slots.escalate(far_lease, 2.5))
    asyncio.ensure_future(slots.escalate(await slots.start(), 0.5))
    await far
    slots.finish(far_lease)
    assert (slots.active, slots.escalated) == (1, 1)


async def test_a_search_past_stage_one_keeps_its_escalated_slot() -> None:
    slots = SearchSlots(capacity=2, escalated_capacity=1, max_waiting=2)
    lease = await slots.start()
    await slots.escalate(lease, 1.0)
    assert (await slots.escalate(lease, 0.5), slots.escalated) == (True, 1)
