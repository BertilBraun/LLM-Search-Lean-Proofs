"""Phases on a generated-token budget, the run's end, the tokens of searches without a tree, and the seed offset."""

import asyncio
import dataclasses
import json
import tomllib
from collections.abc import Callable
from pathlib import Path

import pytest
from loop_fakes import (
    LOOP_TOML,
    PHASE_TEMPLATE,
    FakeSearcher,
    LoopWorld,
    loop_world,
    record_version_zero,
    run_until,
    solved_tree,
    statement,
)

from lean_search.expert_iteration.pool import pool_problem, problem_name
from lean_search.expert_iteration.serving import ModelVersion
from lean_search.monitoring.store import RunReader
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.loop import GrpoLoop, evaluation_due, phase_config_text
from lean_search.rl.loop_config import EvaluationTarget, SamplingConfig, parse_loop_config
from lean_search.rl.search_models import training_run_config
from lean_search.rl.tree_store import SearchEnd, TreeStore
from lean_search.rl.tree_summary import TreeSummary
from lean_search.search import Accounting, SearchResult, StopReason, load_run_config, tree_record

REPOSITORY = Path(__file__).resolve().parents[2]
TOKENS_PER_SEARCH = 100
# 250 tokens a phase at 100 a search: phase k ends at the first tree that brings the run to k * 250.
TOKEN_TOML = LOOP_TOML.replace("concurrency = 2\n", "concurrency = 1\n").replace(
    "check_seconds = 0.01\n", "check_seconds = 0.001\nphase_generated_tokens = 250\n"
)
# The tree boundaries of 100-token searches at 250 a phase, the overshoot paid back: 300, 500, 800, 1000 tokens.
PHASE_TREES = [3, 2, 3, 2]


def token_world(root: Path, toml: str = TOKEN_TOML, searcher: FakeSearcher | None = None) -> LoopWorld:
    searcher = searcher or FakeSearcher(tokens_per_search=TOKENS_PER_SEARCH, search_seconds=0.01)
    world = loop_world(root, toml=toml, searcher=searcher)
    record_version_zero(world)
    return world


def phase_trees(world: LoopWorld, phases: int) -> list[int]:
    store = TreeStore(world.paths.trees)
    return [len(store.phase_entries(phase)) for phase in range(1, phases + 1)]


async def run_while(loop: GrpoLoop, running: Callable[[], bool]) -> None:
    stop = asyncio.Event()
    task = asyncio.create_task(loop.run(stop))
    while running() and not task.done():
        await asyncio.sleep(0)
    stop.set()
    await task


async def run_to_its_end(loop: GrpoLoop) -> None:
    await asyncio.wait_for(loop.run(asyncio.Event()), timeout=60)


def phase_records(world: LoopWorld) -> list[dict]:
    return [json.loads(line) for line in world.paths.phases.read_text(encoding="utf-8").splitlines()]


async def test_token_phases_end_at_multiples_of_the_budget(tmp_path: Path) -> None:
    world = token_world(tmp_path)
    await run_until(world, world.loop(), phases=4)
    assert phase_trees(world, 4) == PHASE_TREES


@pytest.mark.parametrize("trees_before_the_stop", [2, 4, 7])
async def test_a_restart_ends_the_token_phases_at_the_same_trees(tmp_path: Path, trees_before_the_stop: int) -> None:
    world = token_world(tmp_path)
    loop = world.loop()
    await run_while(loop, lambda: len(loop.store.entries) < trees_before_the_stop)
    # A restarted process's searches start behind an open gate, whatever the stop left closed.
    world.searcher.open.set()
    await run_until(world, world.loop(), phases=4)
    assert phase_trees(world, 4) == PHASE_TREES


async def test_token_phases_need_no_minutes_or_groups(tmp_path: Path) -> None:
    toml = TOKEN_TOML.replace("min_sampling_minutes = 1.0", "min_sampling_minutes = 1e6").replace(
        "max_sampling_minutes = 2.0", "max_sampling_minutes = 1e6"
    )
    world = token_world(tmp_path, toml.replace("min_trainable_groups = 2", "min_trainable_groups = 10000"))
    await run_until(world, world.loop(), phases=2)
    assert phase_trees(world, 2) == PHASE_TREES[:2]


def add_tree(store: TreeStore, phase: int, tokens: int, groups: int = 0) -> None:
    problem = pool_problem(statement(len(store.entries)).statement)
    result = SearchResult(problem.name, True, StopReason.PROVED, "trivial", ("trivial",), (), Accounting(), None, 0, 1)
    record = tree_record(solved_tree(problem), problem.formal_statement, result)
    store.add(record, phase, 0, None, TreeSummary(trainable_groups=groups, generated_tokens=tokens))


def due_loop(root: Path, toml: str, phase: int, minutes: float = 0.0) -> GrpoLoop:
    loop = token_world(root, toml).loop()
    loop.progress = dataclasses.replace(loop.progress, phase=phase, sampling_seconds=minutes * 60)
    return loop


# LOOP_TOML: at least 1 minute and 2 groups, or 2 minutes and 1 group; every tree holds far more than any budget.
@pytest.mark.parametrize(
    ("minutes", "groups", "due"),
    [(1.5, 2, True), (1.5, 1, False), (0.5, 2, False), (2.0, 1, True), (2.0, 0, False)],
)
def test_without_a_token_budget_a_phase_ends_on_minutes_and_groups(
    tmp_path: Path, minutes: float, groups: int, due: bool
) -> None:
    loop = due_loop(tmp_path, LOOP_TOML, 1, minutes)
    add_tree(loop.store, 1, 10**9, groups)
    assert loop.phase_due() == due


@pytest.mark.parametrize(
    ("phase", "trees", "without_tree", "due"),
    [
        (1, [(1, 249)], [], False),
        (1, [(1, 250)], [], True),
        (1, [(1, 150)], [(1, 100, SearchEnd.SUMMARY_FAILED)], True),
        (1, [(1, 150)], [(1, 100, SearchEnd.NO_TREE)], True),
        (1, [(1, 150)], [(1, 100, SearchEnd.SERVER_FAILURE)], False),
        (1, [(1, 150)], [(1, 100, SearchEnd.STOPPED)], False),
        (2, [(1, 300), (2, 150)], [], False),
        (2, [(1, 300), (2, 200)], [], True),
    ],
    ids=[
        "below the budget",
        "at the budget",
        "a left-out tree counts",
        "a tree-less search counts",
        "a server failure does not count",
        "a stopped search does not count",
        "the overshoot is paid back",
        "the second budget",
    ],
)
def test_a_token_phase_is_due_at_its_share_of_the_runs_tokens(
    tmp_path: Path,
    phase: int,
    trees: list[tuple[int, int]],
    without_tree: list[tuple[int, int, SearchEnd]],
    due: bool,
) -> None:
    loop = due_loop(tmp_path, TOKEN_TOML, phase)
    for tree_phase, tokens in trees:
        add_tree(loop.store, tree_phase, tokens)
    for search_phase, tokens, end in without_tree:
        loop.store.add_without_tree("t", search_phase, tokens, end)
    assert loop.phase_due() == due


def test_the_tokens_of_searches_without_a_tree_survive_a_restart(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    add_tree(store, 1, 300)
    store.add_without_tree("t", 1, 100, SearchEnd.SUMMARY_FAILED)
    store.add_without_tree("u", 1, 50, SearchEnd.SERVER_FAILURE)
    assert TreeStore(tmp_path).generated_tokens(1, 1) == 400


def test_lost_tokens_are_kept_apart(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.add_without_tree("t", 1, 100, SearchEnd.SUMMARY_FAILED)
    store.add_without_tree("u", 1, 50, SearchEnd.SERVER_FAILURE)
    store.add_without_tree("v", 1, 20, SearchEnd.STOPPED)
    assert TreeStore(tmp_path).lost_tokens(1) == 70


FAILING = problem_name(statement(0).statement)
MALFORMED = problem_name(statement(1).statement)
FAILING_TOML = TOKEN_TOML.replace(
    "status_seconds = 0.01\n", "status_seconds = 0.01\nserver_failure_pause_seconds = 0.0\n"
)


def failing_world(root: Path) -> LoopWorld:
    searcher = FakeSearcher({FAILING: 1}, tokens_per_search=TOKENS_PER_SEARCH, search_seconds=0.01)
    return token_world(root, FAILING_TOML, searcher)


async def test_a_search_a_server_failed_is_recorded_with_its_tokens(tmp_path: Path) -> None:
    world = failing_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    without = TreeStore(world.paths.trees).without_tree
    failed = [search for search in without if search.end == SearchEnd.SERVER_FAILURE]
    assert [(search.problem_name, search.generated_tokens) for search in failed] == [(FAILING, TOKENS_PER_SEARCH)]


async def test_a_search_a_server_failed_does_not_count_towards_the_phase(tmp_path: Path) -> None:
    world = failing_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert phase_trees(world, 1) == PHASE_TREES[:1]


async def test_the_phase_record_holds_the_lost_tokens(tmp_path: Path) -> None:
    world = failing_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert phase_records(world)[0]["lost_generated_tokens"] == TOKENS_PER_SEARCH


async def test_a_tree_whose_summary_fails_counts_towards_the_phase(tmp_path: Path) -> None:
    searcher = FakeSearcher(malformed=frozenset({MALFORMED}), tokens_per_search=TOKENS_PER_SEARCH, search_seconds=0.01)
    world = token_world(tmp_path, searcher=searcher)
    await run_until(world, world.loop(), phases=1)
    assert phase_trees(world, 1) == [PHASE_TREES[0] - 1]


async def test_searches_a_stop_cuts_off_are_recorded_with_their_tokens(tmp_path: Path) -> None:
    world = token_world(tmp_path)
    world.searcher.open.clear()
    await run_while(world.loop(), lambda: world.searcher.in_flight < 1)
    without = TreeStore(world.paths.trees).without_tree
    assert [(search.end, search.generated_tokens) for search in without] == [(SearchEnd.STOPPED, TOKENS_PER_SEARCH)]


async def test_the_timing_line_holds_the_paused_searches_tokens(tmp_path: Path) -> None:
    world = token_world(tmp_path, TOKEN_TOML.replace("concurrency = 1\n", "concurrency = 2\n"))
    await run_until(world, world.loop(), phases=3)
    columns = RunReader(world.paths.directory).series("timing").columns
    paused = list(zip(columns["searches_paused"], columns["paused_search_tokens"], strict=True))
    assert all(tokens == TOKENS_PER_SEARCH * searches for searches, tokens in paused)


async def test_the_phase_record_holds_the_runs_tokens(tmp_path: Path) -> None:
    world = token_world(tmp_path)
    await run_until(world, world.loop(), phases=2)
    assert [record["run_generated_tokens"] for record in phase_records(world)][:2] == [300, 500]


ALERT = "Alert: phase 1 has sampled"


async def test_a_long_token_phase_alerts_once(tmp_path: Path) -> None:
    toml = TOKEN_TOML.replace("phase_generated_tokens = 250\n", "phase_generated_tokens = 1000000000\n")
    world = token_world(tmp_path, toml.replace("check_seconds", "sampling_alert_hours = 0.01\ncheck_seconds"))
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_while(loop, lambda: len(loop.store.entries) < 6)
    assert sum(message.startswith(ALERT) for message in messages) == 1


END_TOML = TOKEN_TOML.replace("phase_generated_tokens = 250\n", "phase_generated_tokens = 250\nmax_phases = 2\n")


async def test_the_run_ends_after_its_last_phase(tmp_path: Path) -> None:
    world = token_world(tmp_path, END_TOML)
    await run_to_its_end(world.loop())
    assert world.phases_done() == 2


async def test_the_last_phase_is_published_and_served(tmp_path: Path) -> None:
    world = token_world(tmp_path, END_TOML)
    await run_to_its_end(world.loop())
    assert world.servers.served[-1] == 2


async def test_the_searches_stay_paused_after_the_last_phase(tmp_path: Path) -> None:
    world = token_world(tmp_path, END_TOML)
    await run_to_its_end(world.loop())
    assert not world.searcher.open.is_set()


async def test_a_restart_after_the_end_trains_nothing_more(tmp_path: Path) -> None:
    world = token_world(tmp_path, END_TOML)
    await run_to_its_end(world.loop())
    world.searcher.open.set()
    await run_to_its_end(world.loop())
    assert [request.phase for request in world.trainer.requests] == [1, 2]


async def test_a_run_on_minutes_and_groups_ends_after_its_last_phase(tmp_path: Path) -> None:
    world = loop_world(tmp_path, LOOP_TOML.replace("check_seconds = 0.01\n", "check_seconds = 0.01\nmax_phases = 1\n"))
    record_version_zero(world)
    await run_to_its_end(world.loop())
    assert world.phases_done() == 1


SAMPLING_ONLY_TOML = TOKEN_TOML.replace(
    "phase_generated_tokens = 250\n", "phase_generated_tokens = 1000000\nmax_generated_tokens = 300\n"
)


async def test_a_sampling_only_run_stops_at_its_tokens_without_training(tmp_path: Path) -> None:
    world = token_world(tmp_path, SAMPLING_ONLY_TOML)
    await run_to_its_end(world.loop())
    assert world.trainer.requests == []


async def test_a_sampling_only_run_holds_its_tokens(tmp_path: Path) -> None:
    world = token_world(tmp_path, SAMPLING_ONLY_TOML)
    await run_to_its_end(world.loop())
    assert TreeStore(world.paths.trees).generated_tokens(1, 1) >= 300


HELD_OUT_BLOCK = (
    "[evaluation.held_out_states]\nmax_expansions = 1\nmax_wall_seconds = 600.0\nconcurrency = 4\n"
    "every_hours = 0.0\nat_start = false\n"
)


async def test_the_held_out_states_run_at_each_token_phases_pause(tmp_path: Path) -> None:
    toml = TOKEN_TOML.replace(
        HELD_OUT_BLOCK, HELD_OUT_BLOCK.replace("at_start = false", "at_start = true\nat_each_pause = true")
    )
    world = token_world(tmp_path, toml)
    await run_until(world, world.loop(), phases=2)
    held_out = [phase for run, phase in world.evaluations.runs if run.kind == EvaluationKind.HELD_OUT_STATES]
    assert held_out == [0, 1, 2]


@pytest.mark.parametrize(
    ("last", "loop_seconds", "at_start", "due"),
    [(None, 0.0, False, True), (60.0, 60.0, False, False), (60.0, 61.0, False, True), (60.0, 120.0, True, False)],
    ids=["never ran", "ran at this pause", "a phase trained since", "not at the start"],
)
def test_an_evaluation_at_each_pause(last: float | None, loop_seconds: float, at_start: bool, due: bool) -> None:
    target = EvaluationTarget(1, 600.0, 4, at_each_pause=True)
    assert evaluation_due(target, last, loop_seconds, at_start) == due


@pytest.mark.parametrize(
    "settings",
    ["max_phases = -1\n", "max_generated_tokens = -1\n", "phase_generated_tokens = 250\nsampling_alert_hours = 0.0\n"],
    ids=["negative phases", "negative tokens", "no alert hours"],
)
def test_impossible_token_settings_are_refused(settings: str) -> None:
    with pytest.raises(ValueError):
        parse_loop_config(LOOP_TOML.replace("check_seconds = 0.01\n", f"check_seconds = 0.01\n{settings}"))


def test_a_negative_seed_offset_is_refused() -> None:
    with pytest.raises(ValueError):
        parse_loop_config("seed_offset = -1\n" + LOOP_TOML)


def test_token_phases_refuse_an_evaluation_by_loop_hours() -> None:
    with pytest.raises(ValueError, match="every_hours"):
        parse_loop_config(TOKEN_TOML.replace("every_hours = 0.0", "every_hours = 2.0", 1))


VERSION = ModelVersion(3, "phase-3/policy/adapter", "phase-2/value/adapter", "2026-10-29T10:00:00+00:00", "phase 3")


def phase_seeds(seed_offset: int) -> dict:
    table = tomllib.loads(
        phase_config_text(PHASE_TEMPLATE, "base", "sft", VERSION, 4, 0.0, "value", seed_offset=seed_offset)
    )
    return {
        "policy": table["policy"]["optimization"]["seed"],
        "value": table["value"]["optimization"]["seed"],
        "replay": table["policy_replay"]["seed"],
    }


@pytest.mark.parametrize("seed", ["policy", "value", "replay"])
def test_a_seed_offset_moves_the_phase_seeds(seed: str) -> None:
    assert phase_seeds(1)[seed] != phase_seeds(0)[seed]


@pytest.mark.parametrize("seed", ["policy", "value", "replay"])
def test_two_seed_offsets_draw_different_phase_seeds(seed: str) -> None:
    assert phase_seeds(1)[seed] != phase_seeds(2)[seed]


def test_without_a_seed_offset_the_phase_seeds_are_the_phases() -> None:
    assert phase_seeds(0) == {"policy": 4, "value": 4, "replay": "grpo-replay/4"}


@pytest.mark.parametrize(("seed_offset", "moved"), [(0, False), (1, True)])
def test_a_seed_offset_moves_the_curriculum_seed(seed_offset: int, moved: bool) -> None:
    config = parse_loop_config(f"seed_offset = {seed_offset}\n" + LOOP_TOML)
    assert (config.curriculum().seed != config.statements.curriculum.seed) == moved


@pytest.mark.parametrize(("seed_offset", "moved"), [(0, False), (1, True)])
def test_a_seed_offset_moves_the_exploration_seed(seed_offset: int, moved: bool) -> None:
    template = load_run_config(REPOSITORY / "experiments/configs/grpo/search/visible_student_v2.toml")
    searched = training_run_config(template, SamplingConfig("template.toml"), seed_offset)
    assert (searched.search.exploration.seed != template.search.exploration.seed) == moved
