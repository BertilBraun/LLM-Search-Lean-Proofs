"""Phases on a generated-token budget, the run's end, the tokens of searches without a tree, and the seed offset."""

import asyncio
import contextlib
import dataclasses
import json
import os
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
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

from lean_search.data import Problem
from lean_search.expert_iteration.pool import pool_problem, problem_name
from lean_search.expert_iteration.serving import ModelVersion, read_versions
from lean_search.monitoring.families import LoopState
from lean_search.monitoring.store import RunReader
from lean_search.rl.evaluation import EvaluationKind
from lean_search.rl.loop import GrpoLoop, PhaseStage, evaluation_due, phase_config_text
from lean_search.rl.loop_config import EvaluationTarget, SamplingConfig, parse_loop_config
from lean_search.rl.search_models import training_run_config
from lean_search.rl.tree_store import SearchEnd, TreeStore
from lean_search.rl.tree_summary import TreeSummary
from lean_search.search import (
    Accounting,
    CompletedSearch,
    SearchResult,
    StopReason,
    load_run_config,
    tree_record,
)
from lean_search.search.texts import SampledCompletion, SampledTokens

REPOSITORY = Path(__file__).resolve().parents[2]
TOKENS_PER_SEARCH = 100
# 250 tokens a phase at 100 a search: phase k ends at the first tree that brings the run to k * 250.
TOKEN_TOML = LOOP_TOML.replace("concurrency = 2\n", "concurrency = 1\n").replace(
    "check_seconds = 0.01\n", "check_seconds = 0.001\nphase_generated_tokens = 250\n"
)
# The tree boundaries of 100-token searches at 250 a phase, the overshoot paid back: 300, 500, 800, 1000 tokens.
PHASE_TREES = [3, 2, 3, 2]


class CheckedSearcher(FakeSearcher):
    """Each search ends only once the loop's watch checked the phase after it started (the sampling progress saved
    again, or the phase paused), so no second tree lands before a check: the phase boundaries do not hang on the event
    loop's timing, as at the node's 30 s checks against searches of minutes."""

    def __init__(self, server_failures: dict[str, int] | None = None, malformed: frozenset[str] = frozenset()) -> None:
        super().__init__(server_failures, malformed, tokens_per_search=TOKENS_PER_SEARCH, search_seconds=0.0)
        self.loop: GrpoLoop | None = None

    async def proving_search(self, problem: Problem) -> CompletedSearch:
        assert self.loop is not None
        seen = self.loop.progress
        while self.loop.progress is seen:
            await asyncio.sleep(0)
        return await super().proving_search(problem)


@dataclass
class CheckedWorld(LoopWorld):
    def loop(self, statement_count: int = 6) -> GrpoLoop:
        loop = super().loop(statement_count)
        if isinstance(self.searcher, CheckedSearcher):
            self.searcher.loop = loop
        return loop


def token_world(root: Path, toml: str = TOKEN_TOML, searcher: FakeSearcher | None = None) -> CheckedWorld:
    world = loop_world(root, toml=toml, searcher=searcher or CheckedSearcher())
    record_version_zero(world)
    return CheckedWorld(**{item.name: getattr(world, item.name) for item in dataclasses.fields(world)})


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
    assert TreeStore(tmp_path).lost_tokens(1, 1) == 70


def test_only_a_server_failures_tokens_count_as_lost_to_server_failures(tmp_path: Path) -> None:
    store = TreeStore(tmp_path)
    store.add_without_tree("u", 1, 50, SearchEnd.SERVER_FAILURE)
    store.add_without_tree("v", 1, 20, SearchEnd.STOPPED)
    assert TreeStore(tmp_path).server_failure_tokens(1, 1) == 50


FAILING = problem_name(statement(0).statement)
MALFORMED = problem_name(statement(1).statement)
FAILING_TOML = TOKEN_TOML.replace(
    "status_seconds = 0.01\n", "status_seconds = 0.01\nserver_failure_pause_seconds = 0.0\n"
)


def failing_world(root: Path, toml: str = FAILING_TOML) -> CheckedWorld:
    return token_world(root, toml, CheckedSearcher({FAILING: 1}))


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
    world = token_world(tmp_path, searcher=CheckedSearcher(malformed=frozenset({MALFORMED})))
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


END_SETTINGS = "phase_generated_tokens = 250\nmax_phases = 2\n"
END_TOML = TOKEN_TOML.replace("phase_generated_tokens = 250\n", END_SETTINGS)


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


def in_stage(loop: GrpoLoop, phase: int, stage: PhaseStage) -> bool:
    return loop.progress.phase == phase and loop.progress.stage == stage


async def restart_in_training(root: Path) -> CheckedWorld:
    """Stopped while phase 2 trains, restarted, run to 4 phases."""
    world = token_world(root)
    world.trainer.train_seconds = 0.05
    loop = world.loop()
    await run_while(
        loop,
        lambda: (
            not (
                in_stage(loop, 2, PhaseStage.TRAINING) and any(request.phase == 2 for request in world.trainer.requests)
            )
        ),
    )
    world.trainer.train_seconds = 0.0
    world.searcher.open.set()
    await run_until(world, world.loop(), phases=4)
    return world


async def test_a_restart_in_training_publishes_each_phase_once(tmp_path: Path) -> None:
    world = await restart_in_training(tmp_path)
    triggers = [version.trigger for version in read_versions(world.paths.models)]
    assert triggers == ["initial", "phase 1", "phase 2", "phase 3", "phase 4"]


async def test_a_restart_in_training_keeps_the_token_boundaries(tmp_path: Path) -> None:
    world = await restart_in_training(tmp_path)
    assert phase_trees(world, 4) == PHASE_TREES


HELD_OUT_AT_EACH_PAUSE = TOKEN_TOML.replace(
    HELD_OUT_BLOCK, HELD_OUT_BLOCK.replace("at_start = false", "at_start = true\nat_each_pause = true")
)


async def restart_in_evaluating(root: Path) -> CheckedWorld:
    """Stopped while phase 1's held-out states run (the searches resumed beside their last checks), restarted."""
    lean_checks = asyncio.Event()
    world = token_world(root, HELD_OUT_AT_EACH_PAUSE)
    world.evaluations.lean_checks = lean_checks
    loop = world.loop()
    await run_while(loop, lambda: not (in_stage(loop, 1, PhaseStage.EVALUATING) and world.evaluations.generated))
    lean_checks.set()
    world.searcher.open.set()
    await run_until(world, world.loop(), phases=4)
    return world


async def test_a_restart_in_evaluating_trains_each_phase_once(tmp_path: Path) -> None:
    world = await restart_in_evaluating(tmp_path)
    assert [request.phase for request in world.trainer.requests] == [1, 2, 3, 4]


async def test_a_restart_in_evaluating_keeps_the_token_boundaries(tmp_path: Path) -> None:
    world = await restart_in_evaluating(tmp_path)
    assert phase_trees(world, 4) == PHASE_TREES


def last_state(world: LoopWorld) -> str:
    lines = (world.paths.directory / "metrics" / "status.jsonl").read_text(encoding="utf-8").splitlines()
    return json.loads(lines[-1])["fields"]["state"]


async def test_a_run_that_ends_by_itself_is_finished_not_stopped(tmp_path: Path) -> None:
    world = token_world(tmp_path, END_TOML)
    await run_to_its_end(world.loop())
    assert last_state(world) == LoopState.FINISHED


async def test_a_finished_run_records_its_last_phase(tmp_path: Path) -> None:
    world = token_world(tmp_path, END_TOML)
    await run_to_its_end(world.loop())
    assert json.loads(world.paths.finished.read_text(encoding="utf-8"))["last_phase"] == 2


@pytest.mark.parametrize(("own", "kept"), [(True, False), (False, True)], ids=["its own", "another process's"])
async def test_a_finished_run_removes_its_own_pid_file(tmp_path: Path, own: bool, kept: bool) -> None:
    world = token_world(tmp_path, END_TOML)
    world.paths.pid.write_text(str(os.getpid() if own else os.getpid() + 1), encoding="utf-8")
    await run_to_its_end(world.loop())
    assert world.paths.pid.exists() == kept


async def test_the_end_line_says_the_servers_are_up_and_how_to_stop_them(tmp_path: Path) -> None:
    world = token_world(tmp_path, END_TOML)
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_to_its_end(loop)
    assert any("servers are still up" in message and "grpo_loop.sh stop" in message for message in messages)


async def test_the_end_line_reports_the_runs_lost_share(tmp_path: Path) -> None:
    world = failing_world(tmp_path, FAILING_TOML.replace("phase_generated_tokens = 250\n", END_SETTINGS))
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_to_its_end(loop)
    finished = next(message for message in messages if message.startswith("The run finished"))
    assert "100 lost to server failures and stops (16.7% of what the searches generated)" in finished


async def test_a_stopped_run_is_stopped_not_finished(tmp_path: Path) -> None:
    world = token_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    assert last_state(world) == LoopState.STOPPED


async def failure_of(world: LoopWorld) -> BaseException | None:
    loop = world.loop()
    with contextlib.suppress(RuntimeError):
        await run_until(world, loop, phases=2)
    return loop.failure


async def test_a_token_budget_is_refused_in_a_run_that_closed_phases_without_it(tmp_path: Path) -> None:
    world = loop_world(tmp_path)
    record_version_zero(world)
    await run_until(world, world.loop(), phases=1)
    failure = await failure_of(loop_world(tmp_path, TOKEN_TOML))
    assert "minutes and groups" in str(failure)


async def test_another_token_budget_is_refused_in_a_run(tmp_path: Path) -> None:
    world = token_world(tmp_path)
    await run_until(world, world.loop(), phases=1)
    other = TOKEN_TOML.replace("phase_generated_tokens = 250\n", "phase_generated_tokens = 300\n")
    failure = await failure_of(loop_world(tmp_path, other))
    assert "would move every phase boundary" in str(failure)


async def test_a_phase_losing_more_than_its_share_of_the_budget_alerts(tmp_path: Path) -> None:
    world = failing_world(tmp_path)
    messages: list[str] = []
    loop = world.loop()
    loop.log = messages.append
    await run_until(world, loop, phases=1)
    assert any(message.startswith("Alert: phase 1 lost 100 generated tokens") for message in messages)


@pytest.mark.parametrize(
    "settings",
    ["max_generated_tokens = 500\n", "phase_generated_tokens = 250\nmax_generated_tokens = 600\n"],
    ids=["on minutes", "not a multiple of the budget"],
)
def test_a_token_total_that_would_end_inside_a_phase_is_refused(settings: str) -> None:
    with pytest.raises(ValueError, match="max_generated_tokens"):
        parse_loop_config(LOOP_TOML.replace("check_seconds = 0.01\n", f"check_seconds = 0.01\n{settings}"))


@pytest.mark.parametrize(
    ("settings", "last"),
    [
        ("phase_generated_tokens = 250\nmax_generated_tokens = 750\n", 3),
        ("phase_generated_tokens = 250\nmax_generated_tokens = 750\nmax_phases = 2\n", 2),
        ("phase_generated_tokens = 250\nmax_generated_tokens = 200\n", None),
        ("phase_generated_tokens = 250\n", None),
    ],
    ids=["a multiple of the budget", "the earlier of the two", "sampling only", "no end"],
)
def test_the_last_phase(settings: str, last: int | None) -> None:
    config = parse_loop_config(LOOP_TOML.replace("check_seconds = 0.01\n", f"check_seconds = 0.01\n{settings}"))
    assert config.training.last_phase() == last


class FailingDecoder:
    def decode(self, token_ids: Sequence[int], *, skip_special_tokens: bool) -> str:
        raise RuntimeError("the tokenizer failed")


class SampledSearcher(CheckedSearcher):
    """Each tree with one first-round sample whose tokens were recorded."""

    async def proving_search(self, problem: Problem) -> CompletedSearch:
        completed = await super().proving_search(problem)
        assert completed.tree is not None
        sample = SampledCompletion(0, "Idea", (), tokens=SampledTokens((1, 2)))
        completed.tree.expansion_texts[0] = dataclasses.replace(
            completed.tree.expansion_texts[0], completions=(sample,)
        )
        return completed


async def habitless_world(root: Path) -> tuple[CheckedWorld, list[str]]:
    """Phase 1 run with a decoder that fails on every sample."""
    world = token_world(root, searcher=SampledSearcher())
    messages: list[str] = []
    loop = world.loop()
    loop.decoder = FailingDecoder()
    loop.log = messages.append
    await run_until(world, loop, phases=1)
    return world, messages


async def test_trees_whose_habits_failed_still_train(tmp_path: Path) -> None:
    world, _ = await habitless_world(tmp_path)
    assert phase_trees(world, 1) == PHASE_TREES[:1]


async def test_the_phase_record_counts_the_trees_without_habits(tmp_path: Path) -> None:
    world, _ = await habitless_world(tmp_path)
    assert phase_records(world)[0]["trees_without_habits"] == PHASE_TREES[0]


async def test_a_phase_with_trees_without_habits_alerts(tmp_path: Path) -> None:
    _, messages = await habitless_world(tmp_path)
    assert any(message.startswith("Alert: 3 of phase 1's 3 trees have no block habits") for message in messages)
