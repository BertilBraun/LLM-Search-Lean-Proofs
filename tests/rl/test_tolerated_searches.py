"""Standalone evaluations through server failures: the searches of `evaluation.ToleratedSearches` send their requests
to fake vLLM servers through the clients' server rotation, and `probe_evaluation.ProbeServers` restarts a dead one
(serve_model.sh replaced by reviving the fake on its port)."""

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fake_vllm import FakeVllmServer

from lean_search.data import Problem, Split
from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig, SwapMethod
from lean_search.policy.client import PolicyClient
from lean_search.policy.rotation import ServerRotation
from lean_search.rl.evaluation import (
    FailureOutcome,
    FailureTolerance,
    ServerRecoveryError,
    ToleratedSearches,
    read_failures,
)
from lean_search.rl.loop_services import ServerStart, unhealthy_servers
from lean_search.rl.probe_evaluation import (
    ProbeCheckpoint,
    ProbeServers,
    ServedWeights,
    ServersUnsoundError,
    read_sessions,
)

PROBLEMS = tuple(Problem(f"s.t{number}", Split.VALID, "", "", "", "") for number in range(12))
STEPS = 3
CONCURRENCY = 4
CHECKPOINT = ProbeCheckpoint("A", 2, "/policy", "p" * 64, "/value", "v" * 64, 0, 2, 1)


@dataclass(frozen=True)
class SearchOutcome:
    problem_name: str
    answers: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    # Per policy server and for the value server: 500s for its next completions, prompts it always fails, and after how
    # many completions it dies (0: never) and again after each revival.
    policy_failures: tuple[int, int] = (0, 0)
    failing_prompts: frozenset[str] = frozenset()
    policy_deaths: tuple[int, int] = (0, 0)
    value_deaths: int = 0
    value_deaths_after_revival: int = 0


@dataclass
class RunOutcome:
    outcomes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    error: BaseException | None = None
    failures_path: Path = Path()
    directory: Path = Path()
    deaths: int = 0


async def verify_health(servers: Sequence[ServerEndpoint]) -> None:
    down = await unhealthy_servers(servers)
    if down:
        raise ServersUnsoundError(f"{down} do not answer")


async def run_scenario(scenario: Scenario, directory: Path) -> RunOutcome:
    policy_fakes = [FakeVllmServer(), FakeVllmServer()]
    value_fake = FakeVllmServer()
    for fake, failures, deaths in zip(policy_fakes, scenario.policy_failures, scenario.policy_deaths, strict=True):
        fake.state.failures_left = failures
        fake.state.failing_prompts = set(scenario.failing_prompts)
        fake.state.completions_until_death = deaths
    value_fake.state.completions_until_death = scenario.value_deaths
    fakes = {f"policy-gpu{index}": fake for index, fake in enumerate(policy_fakes)} | {"value-gpu0": value_fake}
    serving = ServingConfig(
        "policy-base",
        "value-base",
        tuple(ServerEndpoint(f"policy-gpu{index}", index, fake.url) for index, fake in enumerate(policy_fakes)),
        (ServerEndpoint("value-gpu0", 0, value_fake.url),),
        swap=SwapMethod.RESTART,
    )

    async def revive(starts: Sequence[ServerStart]) -> None:
        for start in starts:
            fake = fakes[start.server.name]
            deaths = scenario.value_deaths_after_revival if fake is value_fake else 0
            await asyncio.to_thread(fake.revive, deaths)

    served = ServedWeights(directory / "policy-merge", directory / "value-merge", SwapMethod.RESTART)
    servers = ProbeServers(serving, served, CHECKPOINT, directory, directory / "results.jsonl", verify_health, revive)
    run = RunOutcome(failures_path=directory / "failures.jsonl", directory=directory)
    tolerance = FailureTolerance(servers, 3, 3, run.failures_path)
    async with contextlib.AsyncExitStack() as stack:
        policy_clients = [
            await stack.enter_async_context(PolicyClient(fake.url, "policy-merged")) for fake in policy_fakes
        ]
        value_client = await stack.enter_async_context(PolicyClient(value_fake.url, "value-merged"))
        policy = ServerRotation(policy_clients, recheck_seconds=0.05)
        value = ServerRotation([value_client], recheck_seconds=0.05)
        stack.push_async_callback(policy.close)
        stack.push_async_callback(value.close)

        async def search(problem: Problem) -> SearchOutcome:
            answers = []
            for step in range(STEPS):
                for rotation in (policy, value):
                    with rotation.client() as client:
                        generation = await client.generate(f"{problem.name} step {step}", sample_count=1, max_tokens=1)
                    answers.append(generation.samples[0].text)
            return SearchOutcome(problem.name, tuple(answers))

        async def completed(outcome: SearchOutcome) -> None:
            run.outcomes[outcome.problem_name] = outcome.answers

        try:
            await ToleratedSearches[SearchOutcome](PROBLEMS, tolerance, lambda message: None).run(
                CONCURRENCY, search, completed
            )
        except ServerRecoveryError as error:
            run.error = error
    run.deaths = sum(fake.deaths for fake in fakes.values())
    for fake in fakes.values():
        if not fake.state.dead:
            fake.close()
    return run


def scenario_run(tmp_path_factory: pytest.TempPathFactory, scenario: Scenario) -> RunOutcome:
    return asyncio.run(run_scenario(scenario, tmp_path_factory.mktemp("run")))


@pytest.fixture(scope="module")
def undisturbed(tmp_path_factory: pytest.TempPathFactory) -> RunOutcome:
    return scenario_run(tmp_path_factory, Scenario())


@pytest.fixture(scope="module")
def one_500(tmp_path_factory: pytest.TempPathFactory) -> RunOutcome:
    return scenario_run(tmp_path_factory, Scenario(policy_failures=(1, 0)))


@pytest.fixture(scope="module")
def one_death(tmp_path_factory: pytest.TempPathFactory) -> RunOutcome:
    return scenario_run(tmp_path_factory, Scenario(policy_deaths=(0, 10)))


@pytest.fixture(scope="module")
def cursed(tmp_path_factory: pytest.TempPathFactory) -> RunOutcome:
    return scenario_run(tmp_path_factory, Scenario(failing_prompts=frozenset({"s.t3 step 1"})))


@pytest.fixture(scope="module")
def dying_value_server(tmp_path_factory: pytest.TempPathFactory) -> RunOutcome:
    return scenario_run(tmp_path_factory, Scenario(value_deaths=5, value_deaths_after_revival=5))


def failed_problems(run: RunOutcome) -> set[str]:
    return {failure.problem_name for failure in read_failures(run.failures_path)}


def test_an_undisturbed_run_searches_every_statement(undisturbed: RunOutcome) -> None:
    assert set(undisturbed.outcomes) == {problem.name for problem in PROBLEMS}


def test_a_statement_whose_search_got_a_500_is_searched_again(one_500: RunOutcome) -> None:
    assert set(one_500.outcomes) == {problem.name for problem in PROBLEMS}


def test_a_single_500_restarts_no_server(one_500: RunOutcome) -> None:
    assert [session.serving.restarted for session in read_sessions(one_500.directory)] == []


@pytest.mark.parametrize("scenario", ["one_500", "one_death"])
def test_statements_a_failure_did_not_touch_end_as_in_an_undisturbed_run(
    scenario: str, undisturbed: RunOutcome, request: pytest.FixtureRequest
) -> None:
    run: RunOutcome = request.getfixturevalue(scenario)
    untouched = set(run.outcomes) - failed_problems(run)
    assert {name: run.outcomes[name] for name in untouched} == {name: undisturbed.outcomes[name] for name in untouched}


@pytest.mark.parametrize("scenario", ["one_500", "one_death"])
def test_a_retried_statement_ends_as_in_an_undisturbed_run(
    scenario: str, undisturbed: RunOutcome, request: pytest.FixtureRequest
) -> None:
    run: RunOutcome = request.getfixturevalue(scenario)
    retried = failed_problems(run)
    assert retried and {name: run.outcomes[name] for name in retried} == {
        name: undisturbed.outcomes[name] for name in retried
    }


def test_a_dead_server_is_restarted_once(one_death: RunOutcome) -> None:
    assert [session.serving.restarted for session in read_sessions(one_death.directory)] == [("policy-gpu1",)]


def test_a_run_through_a_dead_server_searches_every_statement(one_death: RunOutcome) -> None:
    assert set(one_death.outcomes) == {problem.name for problem in PROBLEMS}


def test_the_restart_is_recorded_as_a_session_from_the_merges(one_death: RunOutcome) -> None:
    (session,) = read_sessions(one_death.directory)
    assert session.serving.swap == SwapMethod.RESTART


def test_a_dead_server_is_left_out_so_few_searches_fail(one_death: RunOutcome) -> None:
    assert len(failed_problems(one_death)) < CONCURRENCY


def test_a_statement_failing_four_times_is_left_without_a_result(cursed: RunOutcome) -> None:
    assert set(cursed.outcomes) == {problem.name for problem in PROBLEMS} - {"s.t3"}


def test_a_statement_failing_four_times_is_given_up_on_its_fourth_failure(cursed: RunOutcome) -> None:
    outcomes = [failure.outcome for failure in read_failures(cursed.failures_path)]
    assert outcomes == [FailureOutcome.RETRIED] * 3 + [FailureOutcome.DROPPED]


def test_a_server_that_keeps_dying_stops_the_run_after_three_restarts(dying_value_server: RunOutcome) -> None:
    assert isinstance(dying_value_server.error, ServerRecoveryError)


def test_the_stopped_run_restarted_its_server_three_times(dying_value_server: RunOutcome) -> None:
    restarted = [session.serving.restarted for session in read_sessions(dying_value_server.directory)]
    assert restarted == [("value-gpu0",)] * 3


def test_without_a_tolerance_a_server_error_ends_the_searches() -> None:
    async def failing(problem: Problem) -> SearchOutcome:
        raise httpx.ConnectError("refused")

    async def completed(outcome: SearchOutcome) -> None:
        return

    searches = ToleratedSearches[SearchOutcome](PROBLEMS, None, lambda message: None)
    with pytest.raises(httpx.ConnectError):
        asyncio.run(searches.run(CONCURRENCY, failing, completed))


@dataclass
class Rotated:
    first: list[str]
    after_revival: list[str]


async def rotate_through_a_death() -> Rotated:
    fakes = [FakeVllmServer(), FakeVllmServer()]
    async with contextlib.AsyncExitStack() as stack:
        clients = [await stack.enter_async_context(PolicyClient(fake.url, "policy-merged")) for fake in fakes]
        rotation = ServerRotation(clients, recheck_seconds=0.05)
        stack.push_async_callback(rotation.close)
        fakes[0].die()
        with contextlib.suppress(httpx.HTTPError), rotation.client() as client:
            await client.generate("x", sample_count=1, max_tokens=1)
        first = [rotation.next_client().server_url for _ in range(4)]
        fakes[0].revive()
        while rotation.left_out:
            await asyncio.sleep(0.05)
        after_revival = [rotation.next_client().server_url for _ in range(4)]
    for fake in fakes:
        fake.close()
    return Rotated(first, after_revival)


@pytest.fixture(scope="module")
def rotated() -> Rotated:
    return asyncio.run(rotate_through_a_death())


def test_a_server_that_failed_is_left_out_of_the_turn(rotated: Rotated) -> None:
    assert len(set(rotated.first)) == 1


def test_a_left_out_server_is_taken_back_once_it_answers(rotated: Rotated) -> None:
    assert len(set(rotated.after_revival)) == 2
