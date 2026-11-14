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
from lean_search.policy.rotation import RequestFailures, ServerRotation
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationProblem,
    FailureOutcome,
    FailureTolerance,
    SearchFailure,
    ServerRecoveryError,
    ToleratedSearches,
    now,
    problem_name,
    read_failures,
    search_summary,
)
from lean_search.rl.loop_services import ServedWeightsOn, ServerStart, unhealthy_servers
from lean_search.rl.probe_evaluation import (
    DeathRule,
    ProbeCheckpoint,
    ProbeServers,
    ServedWeights,
    ServersUnsoundError,
    read_sessions,
)
from lean_search.search import Accounting, SearchResult, StopReason, load_run_config
from lean_search.search.records import to_json

PROBLEMS = tuple(Problem(f"s.t{number}", Split.VALID, "", "", "", "") for number in range(12))
STEPS = 3
CONCURRENCY = 4
CHECKPOINT = ProbeCheckpoint("A", 2, "/policy", "p" * 64, "/value", "v" * 64, 0, 2, 1)
REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
FAST_DEATH_RULE = DeathRule(failing_requests=5, health_probes=3, probe_interval_seconds=0.05)


@dataclass(frozen=True)
class SearchOutcome:
    problem_name: str
    answers: tuple[str, ...]


@dataclass(frozen=True)
class Scenario:
    # Per policy server and for the value server: 500s for its next completions, prompts it always fails (500) or
    # refuses (400), 503s for its next /health checks, asleep, and after how many completions it dies (0: never) and
    # again after each revival; a server that dies while the first restart runs.
    policy_failures: tuple[int, int] = (0, 0)
    failing_prompts: frozenset[str] = frozenset()
    refused_prompts: frozenset[str] = frozenset()
    policy_health_failures: tuple[int, int] = (0, 0)
    policy_asleep: tuple[bool, bool] = (False, False)
    policy_deaths: tuple[int, int] = (0, 0)
    value_deaths: int = 0
    value_deaths_after_revival: int = 0
    dies_during_restart: str = ""
    # Earlier processes of the run: their restarts and failed searches.
    restarts_before: int = 0
    failures_before: tuple[SearchFailure, ...] = ()


@dataclass
class RunOutcome:
    outcomes: dict[str, tuple[str, ...]] = field(default_factory=dict)
    error: BaseException | None = None
    failures_path: Path = Path()
    directory: Path = Path()
    deaths: int = 0
    restarted: list[str] = field(default_factory=list)


async def verify_health(assignments: Sequence[ServedWeightsOn], fresh: frozenset[str]) -> None:
    down = await unhealthy_servers([assigned.server for assigned in assignments])
    if down:
        raise ServersUnsoundError(f"{down} do not answer")


async def run_scenario(scenario: Scenario, directory: Path) -> RunOutcome:
    policy_fakes = [FakeVllmServer(), FakeVllmServer()]
    value_fake = FakeVllmServer()
    for index, fake in enumerate(policy_fakes):
        fake.state.failures_left = scenario.policy_failures[index]
        fake.state.failing_prompts = set(scenario.failing_prompts)
        fake.state.refused_prompts = set(scenario.refused_prompts)
        fake.state.health_failures_left = scenario.policy_health_failures[index]
        fake.state.sleeping = scenario.policy_asleep[index]
        fake.state.completions_until_death = scenario.policy_deaths[index]
        fake.state.root = str(directory / "policy-merge")
    value_fake.state.completions_until_death = scenario.value_deaths
    value_fake.state.root = str(directory / "value-merge")
    fakes = {f"policy-gpu{index}": fake for index, fake in enumerate(policy_fakes)} | {"value-gpu0": value_fake}
    serving = ServingConfig(
        "policy-base",
        "value-base",
        tuple(ServerEndpoint(f"policy-gpu{index}", index, fake.url) for index, fake in enumerate(policy_fakes)),
        (ServerEndpoint("value-gpu0", 0, value_fake.url),),
        swap=SwapMethod.RESTART,
    )
    run = RunOutcome(failures_path=directory / "failures.jsonl", directory=directory)
    dying = [scenario.dies_during_restart] if scenario.dies_during_restart else []

    async def revive(starts: Sequence[ServerStart]) -> None:
        if dying:
            await asyncio.to_thread(fakes[dying.pop()].die)
            # The dying server's searches fail while this restart runs.
            await asyncio.sleep(0.3)
        for start in starts:
            run.restarted.append(start.server.name)
            fake = fakes[start.server.name]
            deaths = scenario.value_deaths_after_revival if fake is value_fake else 0
            await asyncio.to_thread(fake.revive, deaths)

    run.failures_path.parent.mkdir(parents=True, exist_ok=True)
    run.failures_path.write_text("".join(to_json(failure) + "\n" for failure in scenario.failures_before))
    request_failures = RequestFailures()
    served = ServedWeights(directory / "policy-merge", directory / "value-merge", SwapMethod.RESTART)
    servers = ProbeServers(
        serving,
        served,
        CHECKPOINT,
        directory,
        directory / "results.jsonl",
        verify_health,
        revive,
        request_failures,
        FAST_DEATH_RULE,
    )
    tolerance = FailureTolerance(servers, 3, 3, run.failures_path, scenario.restarts_before, request_failures)
    async with contextlib.AsyncExitStack() as stack:
        policy_clients = [
            await stack.enter_async_context(PolicyClient(fake.url, "policy-merged")) for fake in policy_fakes
        ]
        value_client = await stack.enter_async_context(PolicyClient(value_fake.url, "value-merged"))
        policy = ServerRotation(policy_clients, recheck_seconds=0.05, request_failures=request_failures)
        value = ServerRotation([value_client], recheck_seconds=0.05, request_failures=request_failures)
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

        searches = ToleratedSearches[Problem, SearchOutcome](PROBLEMS, problem_name, tolerance, lambda message: None)
        try:
            await searches.run(CONCURRENCY, search, completed)
        except (ServerRecoveryError, httpx.HTTPStatusError) as error:
            run.error = error
    run.deaths = sum(fake.deaths for fake in fakes.values())
    for fake in fakes.values():
        fake.close()
    return run


def scenario_run(tmp_path_factory: pytest.TempPathFactory, scenario: Scenario) -> RunOutcome:
    return asyncio.run(run_scenario(scenario, tmp_path_factory.mktemp("run")))


SCENARIOS = {
    "undisturbed": Scenario(),
    "one_500": Scenario(policy_failures=(1, 0)),
    "one_death": Scenario(policy_deaths=(0, 10)),
    "cursed": Scenario(failing_prompts=frozenset({"s.t3 step 1"})),
    "dying_value_server": Scenario(value_deaths=5, value_deaths_after_revival=5),
    "second_death_during_restart": Scenario(policy_deaths=(0, 10), dies_during_restart="policy-gpu0"),
    "refused": Scenario(refused_prompts=frozenset({"s.t3 step 0"})),
    "answers_health_fails_requests": Scenario(policy_failures=(0, 10_000)),
    "one_slow_health": Scenario(policy_failures=(1, 0), policy_health_failures=(1, 0)),
    "asleep": Scenario(policy_asleep=(False, True)),
    "restarts_used_before": Scenario(policy_deaths=(0, 10), restarts_before=3),
    "failed_before": Scenario(
        failing_prompts=frozenset({"s.t3 step 1"}),
        failures_before=(SearchFailure("s.t3", 3, "500", FailureOutcome.RETRIED, now()),),
    ),
}


@pytest.fixture(scope="module")
def runs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, RunOutcome]:
    return {name: scenario_run(tmp_path_factory, scenario) for name, scenario in SCENARIOS.items()}


def failed_problems(run: RunOutcome) -> set[str]:
    return {failure.problem_name for failure in read_failures(run.failures_path)}


def restart_sessions(run: RunOutcome) -> list[tuple[str, ...]]:
    return [session.serving.restarted for session in read_sessions(run.directory)]


ALL = {problem.name for problem in PROBLEMS}


def test_an_undisturbed_run_searches_every_statement(runs: dict[str, RunOutcome]) -> None:
    assert set(runs["undisturbed"].outcomes) == ALL


def test_a_statement_whose_search_got_a_500_is_searched_again(runs: dict[str, RunOutcome]) -> None:
    assert set(runs["one_500"].outcomes) == ALL


@pytest.mark.parametrize("scenario", ["one_500", "one_slow_health"])
def test_a_server_that_stumbles_once_is_not_restarted(scenario: str, runs: dict[str, RunOutcome]) -> None:
    assert restart_sessions(runs[scenario]) == []


@pytest.mark.parametrize("scenario", ["one_500", "one_death", "second_death_during_restart"])
def test_statements_a_failure_did_not_touch_end_as_in_an_undisturbed_run(
    scenario: str, runs: dict[str, RunOutcome]
) -> None:
    run, undisturbed = runs[scenario], runs["undisturbed"]
    untouched = set(run.outcomes) - failed_problems(run)
    assert {name: run.outcomes[name] for name in untouched} == {name: undisturbed.outcomes[name] for name in untouched}


@pytest.mark.parametrize("scenario", ["one_500", "one_death"])
def test_a_retried_statement_ends_as_in_an_undisturbed_run(scenario: str, runs: dict[str, RunOutcome]) -> None:
    run, undisturbed = runs[scenario], runs["undisturbed"]
    retried = failed_problems(run)
    assert retried and {name: run.outcomes[name] for name in retried} == {
        name: undisturbed.outcomes[name] for name in retried
    }


def test_a_dead_server_is_restarted_once(runs: dict[str, RunOutcome]) -> None:
    assert restart_sessions(runs["one_death"]) == [("policy-gpu1",)]


def test_a_run_through_a_dead_server_searches_every_statement(runs: dict[str, RunOutcome]) -> None:
    assert set(runs["one_death"].outcomes) == ALL


def test_the_restart_is_recorded_as_a_session_from_the_merges(runs: dict[str, RunOutcome]) -> None:
    (session,) = read_sessions(runs["one_death"].directory)
    assert session.serving.swap == SwapMethod.RESTART


def test_a_dead_server_is_left_out_so_few_searches_fail(runs: dict[str, RunOutcome]) -> None:
    assert len(failed_problems(runs["one_death"])) < CONCURRENCY


def test_a_server_that_dies_while_another_restarts_is_restarted_too(runs: dict[str, RunOutcome]) -> None:
    assert sorted(runs["second_death_during_restart"].restarted) == ["policy-gpu0", "policy-gpu1"]


def test_a_statement_failing_four_times_is_left_without_a_result(runs: dict[str, RunOutcome]) -> None:
    assert set(runs["cursed"].outcomes) == ALL - {"s.t3"}


def test_a_statement_failing_four_times_is_given_up_on_its_fourth_failure(runs: dict[str, RunOutcome]) -> None:
    outcomes = [failure.outcome for failure in read_failures(runs["cursed"].failures_path)]
    assert outcomes == [FailureOutcome.RETRIED] * 3 + [FailureOutcome.DROPPED]


def test_a_server_that_keeps_dying_stops_the_run_after_three_restarts(runs: dict[str, RunOutcome]) -> None:
    assert isinstance(runs["dying_value_server"].error, ServerRecoveryError)


def test_the_stopped_run_restarted_its_server_three_times(runs: dict[str, RunOutcome]) -> None:
    assert restart_sessions(runs["dying_value_server"]) == [("value-gpu0",)] * 3


def test_a_request_the_server_refuses_ends_the_run(runs: dict[str, RunOutcome]) -> None:
    error = runs["refused"].error
    assert isinstance(error, httpx.HTTPStatusError) and error.response.status_code == 400


def test_a_refused_request_is_not_recorded_as_a_server_failure(runs: dict[str, RunOutcome]) -> None:
    assert read_failures(runs["refused"].failures_path) == []


@pytest.mark.parametrize("scenario", ["answers_health_fails_requests", "asleep"])
def test_a_server_that_answers_health_but_not_its_requests_is_restarted(
    scenario: str, runs: dict[str, RunOutcome]
) -> None:
    assert restart_sessions(runs[scenario]) == [("policy-gpu1",)]


def test_the_restarts_of_earlier_processes_count_against_the_cap(runs: dict[str, RunOutcome]) -> None:
    run = runs["restarts_used_before"]
    assert isinstance(run.error, ServerRecoveryError) and run.restarted == []


def test_the_failed_searches_of_earlier_processes_count_against_the_retries(runs: dict[str, RunOutcome]) -> None:
    outcomes = [failure.outcome for failure in read_failures(runs["failed_before"].failures_path)]
    assert outcomes == [FailureOutcome.RETRIED, FailureOutcome.DROPPED]


def test_without_a_tolerance_a_server_error_ends_the_searches() -> None:
    async def failing(problem: Problem) -> SearchOutcome:
        raise httpx.ConnectError("refused")

    async def completed(outcome: SearchOutcome) -> None:
        return

    searches = ToleratedSearches[Problem, SearchOutcome](PROBLEMS, problem_name, None, lambda message: None)
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


def test_a_dropped_statement_is_neither_searched_nor_unsolved_in_the_summary() -> None:
    config = load_run_config(REPOSITORY_DIRECTORY / "experiments/configs/grpo/search/visible_student_v2.toml")
    problems = [EvaluationProblem(problem) for problem in PROBLEMS[:2]]
    results = [SearchResult("s.t0", True, StopReason.PROVED, None, (), (), Accounting(), None, 0, 1)]
    summary = search_summary(EvaluationKind.PROBE, "probe_x", (0, 0), problems, results, config, "", 1.0)
    assert (summary.problems, summary.solved, summary.dropped) == (1, 1, ("s.t1",))
