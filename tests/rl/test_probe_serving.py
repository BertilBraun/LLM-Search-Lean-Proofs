"""How a probe run's weights reach the servers: skipped only where a server provably holds byte-identical weights it
started from (its trusted pid file, no swap mark, its log on the checked vLLM version, awake), every server held to its
merge's fingerprint, and how run.json records the run's sessions, restarts and dropped statements."""

import asyncio
import contextlib
import dataclasses
import json
import math
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_vllm import FakeVllmServer
from server_process_fakes import age_file, fake_server_process

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig, SwapMethod
from lean_search.policy.rotation import RequestFailures
from lean_search.policy.server_control import release_gpu
from lean_search.policy.server_processes import mark_swapped, server_process, swapped_marker
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationSummary,
    FailureOutcome,
    SearchFailure,
    ServerRecoveryError,
)
from lean_search.rl.loop_services import ServedWeightsOn, ServerStart
from lean_search.rl.probe_evaluation import (
    FINGERPRINT_FILE,
    SWAP_MARKERS_VLLM,
    DeathRule,
    ProbeCheckpoint,
    ProbeRunStart,
    ProbeServers,
    ProbeSession,
    RetriedStatement,
    RunEnvironment,
    ServedWeights,
    ServerRestart,
    ServersUnsoundError,
    SessionServing,
    TokenLogProbability,
    check_fingerprints,
    fingerprint_distance,
    holds_start_weights,
    merges_in_use,
    read_fingerprint,
    read_sessions,
    restart_allowance,
    run_record,
    same_served_weights,
    serve_checkpoint,
    server_restarts,
)
from lean_search.search import load_run_config
from lean_search.search.records import from_json_object

CHECKPOINT = ProbeCheckpoint("A", 2, "/policy", "p" * 64, "/value", "v" * 64, 0, 2, 1)
START = ProbeRunStart("identity", False, CHECKPOINT, "search.toml", "c" * 64, 84, 7200.0, 16, "probe.jsonl", "d" * 64)
ENVIRONMENT = RunEnvironment("node", "leanprover/lean4:v4.9.0", "0.31.0", "2.13.0")
FRESH_LOG = "(APIServer pid={pid}) INFO 11-14 14:43:39 [api_utils.py:286] non-default args: {{}}\n"
WAKE_LINE = "(APIServer pid={pid}) INFO 11-14 14:47:39 [api_router.py:42] wake up the engine with tags: ['weights']\n"
RELOAD_LINE = "(EngineCore pid=7) INFO 11-14 14:47:39 [gpu_model_runner.py:5543] Reloading weights inplace...\n"
SLEEP_LINE = "(EngineCore pid=7) INFO 11-14 14:47:39 [gpu_worker.py:303] Sleep mode freed 5.36 GiB memory\n"
REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
SERVER = ServerEndpoint("policy-gpu0", 0, "http://127.0.0.1:8100/v1")


@pytest.mark.parametrize(
    ("log", "holds"),
    [
        (FRESH_LOG, True),
        (FRESH_LOG + WAKE_LINE, False),
        (FRESH_LOG + RELOAD_LINE, False),
        (FRESH_LOG + SLEEP_LINE, False),
    ],
    ids=["fresh", "woken", "reloaded", "slept"],
)
def test_a_server_holds_its_start_weights_only_without_a_sleep_wake_or_reload_in_its_log(
    tmp_path: Path, log: str, holds: bool
) -> None:
    with fake_server_process(tmp_path / "servers", "policy-gpu0", tmp_path / "merge", log):
        assert holds_start_weights(tmp_path / "servers", SERVER, SWAP_MARKERS_VLLM) == holds


def test_a_server_the_tooling_marked_as_swapped_holds_nothing_known(tmp_path: Path) -> None:
    servers = tmp_path / "servers"
    with fake_server_process(servers, "policy-gpu0", tmp_path / "merge", FRESH_LOG):
        mark_swapped(servers, 8100)
        assert not holds_start_weights(servers, SERVER, SWAP_MARKERS_VLLM)


def test_on_another_vllm_version_no_server_holds_anything_known(tmp_path: Path) -> None:
    with fake_server_process(tmp_path / "servers", "policy-gpu0", tmp_path / "merge", FRESH_LOG):
        assert not holds_start_weights(tmp_path / "servers", SERVER, "0.32.0")


def test_a_log_of_another_process_holds_nothing_known(tmp_path: Path) -> None:
    servers = tmp_path / "servers"
    with fake_server_process(servers, "policy-gpu0", tmp_path / "merge", FRESH_LOG):
        (servers / "policy-gpu0.log").write_text(FRESH_LOG.format(pid=1), encoding="utf-8")
        assert not holds_start_weights(servers, SERVER, SWAP_MARKERS_VLLM)


def test_a_server_without_a_pid_file_holds_nothing_known(tmp_path: Path) -> None:
    assert not holds_start_weights(tmp_path, SERVER, SWAP_MARKERS_VLLM)


def test_a_pid_file_naming_another_program_is_not_trusted(tmp_path: Path) -> None:
    (tmp_path / "policy-gpu0.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    assert server_process(tmp_path, "policy-gpu0") is None


def test_a_pid_file_written_long_before_its_process_started_is_not_trusted(tmp_path: Path) -> None:
    with fake_server_process(tmp_path, "policy-gpu0", tmp_path / "merge"):
        age_file(tmp_path / "policy-gpu0.pid", 3600)
        assert server_process(tmp_path, "policy-gpu0") is None


def test_a_pid_file_of_another_servers_vllm_is_not_trusted(tmp_path: Path) -> None:
    with fake_server_process(tmp_path, "value-gpu0", tmp_path / "merge"):
        os.replace(tmp_path / "value-gpu0.pid", tmp_path / "policy-gpu0.pid")
        assert server_process(tmp_path, "policy-gpu0") is None


def test_a_trusted_servers_start_weights_are_in_use(tmp_path: Path) -> None:
    serving = ServingConfig("policy-base", "value-base", (ServerEndpoint("policy-gpu0", 0, "http://x/v1"),), ())
    with fake_server_process(tmp_path, "policy-gpu0", tmp_path / "merge"):
        assert merges_in_use(tmp_path, serving) == {(tmp_path / "merge").resolve()}


def weights(directory: Path, content: bytes) -> Path:
    directory.mkdir(parents=True)
    (directory / "model.safetensors").write_bytes(content)
    (directory / "config.json").write_text("{}", encoding="utf-8")
    return directory


@pytest.mark.parametrize(("second", "same"), [(b"weights", True), (b"weightz", False)])
def test_served_weights_are_the_same_only_byte_for_byte(tmp_path: Path, second: bytes, same: bool) -> None:
    assert same_served_weights(weights(tmp_path / "a", b"weights"), weights(tmp_path / "b", second)) == same


def test_weights_missing_a_file_are_not_the_same(tmp_path: Path) -> None:
    first = weights(tmp_path / "a", b"weights")
    second = weights(tmp_path / "b", b"weights")
    (second / "config.json").unlink()
    assert not same_served_weights(first, second)


@dataclass(frozen=True)
class SkipHistory:
    served: ServedWeights
    reloads: tuple[tuple[str, ...], ...]
    fresh: frozenset[str]


@pytest.fixture(scope="module")
def skip_history(tmp_path_factory: pytest.TempPathFactory) -> SkipHistory:
    """policy-gpu0 started from byte-identical weights and never swapped, policy-gpu1 woke since its start, policy-gpu2
    started from them but is asleep, value-gpu0 started from other weights."""
    root = tmp_path_factory.mktemp("skip")
    fakes = [FakeVllmServer() for _ in range(4)]
    names = ("policy-gpu0", "policy-gpu1", "policy-gpu2", "value-gpu0")
    serving = ServingConfig(
        "policy-base",
        "value-base",
        tuple(ServerEndpoint(name, index, fakes[index].url) for index, name in enumerate(names[:3])),
        (ServerEndpoint("value-gpu0", 0, fakes[3].url),),
    )

    def merge(base_model: str, adapter: Path, output: Path) -> None:
        output.mkdir(parents=True)
        (output / "model.safetensors").write_text(f"{base_model} merged", encoding="utf-8")

    started_from = root / "started"
    started_from.mkdir()
    (started_from / "model.safetensors").write_text("policy-base merged", encoding="utf-8")
    other = root / "other"
    other.mkdir()
    (other / "model.safetensors").write_text("value-base merged long ago", encoding="utf-8")
    for fake, directory in zip(fakes, (started_from, started_from, started_from, other), strict=True):
        fake.state.root = str(directory)
    fakes[2].state.sleeping = True
    servers = root / "servers"
    fresh: list[frozenset[str]] = []

    async def record_fresh(assignments: Sequence[ServedWeightsOn], started: frozenset[str]) -> tuple[str, ...]:
        fresh.append(started)
        return ()

    logs = (FRESH_LOG, FRESH_LOG + WAKE_LINE, FRESH_LOG, FRESH_LOG)
    with contextlib.ExitStack() as stack:
        for name, log, directory in zip(names, logs, (started_from, started_from, started_from, other), strict=True):
            stack.enter_context(fake_server_process(servers, name, directory, log))
        served = asyncio.run(
            serve_checkpoint(serving, CHECKPOINT, root / "weights", merge, servers, record_fresh, print)
        )
    reloads = tuple(tuple(fake.state.reloads) for fake in fakes)
    for fake in fakes:
        fake.close()
    return SkipHistory(served, reloads, fresh[0])


def test_a_server_holding_identical_start_weights_is_not_swapped(skip_history: SkipHistory) -> None:
    assert skip_history.reloads[0] == ()


def test_a_server_that_woke_since_its_start_is_swapped(skip_history: SkipHistory) -> None:
    assert skip_history.reloads[1] == (str(skip_history.served.policy),)


def test_a_sleeping_server_is_swapped(skip_history: SkipHistory) -> None:
    assert skip_history.reloads[2] == (str(skip_history.served.policy),)


def test_a_server_holding_other_weights_is_swapped(skip_history: SkipHistory) -> None:
    assert skip_history.reloads[3] == (str(skip_history.served.value),)


def test_the_skipped_and_swapped_servers_are_named(skip_history: SkipHistory) -> None:
    assert (skip_history.served.skipped, skip_history.served.swapped) == (
        ("policy-gpu0",),
        ("policy-gpu1", "policy-gpu2", "value-gpu0"),
    )


def test_neither_a_skipped_nor_a_swapped_server_gives_its_weights_their_fingerprint(skip_history: SkipHistory) -> None:
    assert skip_history.fresh == frozenset()


def fingerprint(
    shift: float = 0.0, tokens: tuple[str, ...] = ("token_id:1", "token_id:2")
) -> tuple[tuple[TokenLogProbability, ...], ...]:
    return ((TokenLogProbability(tokens[0], -0.1 + shift), TokenLogProbability(tokens[1], -3.0)),)


@pytest.mark.parametrize(
    ("observed", "distance"),
    [
        (fingerprint(0.01), 0.01),
        (fingerprint(0.2), 0.2),
        (fingerprint(tokens=("token_id:9", "token_id:2")), math.inf),
    ],
    ids=["near", "shifted", "a reference token missing"],
)
def test_the_fingerprint_distance_is_the_largest_difference_on_the_references_tokens(
    observed: tuple[tuple[TokenLogProbability, ...], ...], distance: float
) -> None:
    assert fingerprint_distance(fingerprint(), observed) == pytest.approx(distance)


@dataclass(frozen=True)
class FingerprintCheck:
    reference_written: bool
    warnings: tuple[str, ...]
    error: str


async def check_two_servers(directory: Path, shift: float, fresh: frozenset[str]) -> FingerprintCheck:
    fakes = [FakeVllmServer(), FakeVllmServer()]
    fakes[1].state.logprob_shift = shift
    template = load_run_config(REPOSITORY_DIRECTORY / "experiments/configs/grpo/search/visible_student_v2.toml")
    urls = tuple(fake.url for fake in fakes)
    run_config = dataclasses.replace(template, policy=dataclasses.replace(template.policy, server_urls=urls))
    merge = directory / "merge"
    merge.mkdir()
    assignments = [
        ServedWeightsOn(ServerEndpoint(f"policy-gpu{index}", index, fake.url), str(merge))
        for index, fake in enumerate(fakes)
    ]
    warnings: tuple[str, ...] = ()
    error = ""
    try:
        warnings = await check_fingerprints(run_config, assignments, fresh, SWAP_MARKERS_VLLM, print)
    except ServersUnsoundError as unsound:
        error = str(unsound)
    for fake in fakes:
        fake.close()
    return FingerprintCheck((merge / FINGERPRINT_FILE).exists(), warnings, error)


def test_the_first_server_freshly_started_from_a_merge_writes_its_fingerprint(tmp_path: Path) -> None:
    assert asyncio.run(check_two_servers(tmp_path, 0.0, frozenset({"policy-gpu0"}))).reference_written


def test_without_a_freshly_started_server_no_fingerprint_is_written(tmp_path: Path) -> None:
    assert not asyncio.run(check_two_servers(tmp_path, 0.0, frozenset())).reference_written


def test_a_server_somewhat_off_its_reference_is_a_warning_not_a_failure(tmp_path: Path) -> None:
    check = asyncio.run(check_two_servers(tmp_path, 0.5, frozenset({"policy-gpu0"})))
    assert (check.error, len(check.warnings), "policy-gpu1" in check.warnings[0]) == ("", 1, True)


def test_a_server_grossly_off_its_reference_fails_the_start(tmp_path: Path) -> None:
    assert "policy-gpu1" in asyncio.run(check_two_servers(tmp_path, 1.5, frozenset({"policy-gpu0"}))).error


def test_servers_without_a_reference_are_held_to_each_other(tmp_path: Path) -> None:
    assert "policy-gpu1" in asyncio.run(check_two_servers(tmp_path, 1.5, frozenset())).error


def test_a_written_fingerprint_reads_back(tmp_path: Path) -> None:
    asyncio.run(check_two_servers(tmp_path, 0.0, frozenset({"policy-gpu0"})))
    reference = read_fingerprint(tmp_path / "merge")
    assert reference is not None and reference.server == "policy-gpu0"


async def swap_a_server(runs: Path) -> bool:
    fake = FakeVllmServer()
    await release_gpu(fake.url)
    fake.close()
    return swapped_marker(runs / "servers", fake.port).exists()


def test_server_control_marks_a_server_it_sleeps(runs_directory: Path) -> None:
    assert asyncio.run(swap_a_server(runs_directory))


def summary(problems: int, stops: int) -> EvaluationSummary:
    return EvaluationSummary(
        EvaluationKind.PROBE, "probe_x", 0, 0, problems, 0, (), 16, 0, 0, 0.0, 0.0, "", "", 0, 0, stops
    )


def session(serving: SessionServing, started_at: str = "2026-11-14T15:00:00+00:00") -> ProbeSession:
    return ProbeSession("session", 0, "p" * 64, "v" * 64, serving=serving, started_at=started_at)


def test_a_run_with_a_dropped_statement_is_not_accepted() -> None:
    assert not run_record(START, ENVIRONMENT, summary(2000, 0), (), 0.01, dropped=("s.t3",)).accepted


def test_a_run_record_names_its_dropped_statements() -> None:
    record = run_record(START, ENVIRONMENT, summary(2000, 0), (), 0.01, dropped=("s.t3",))
    assert record.dropped_statements == ("s.t3",)


def test_a_run_record_counts_each_retried_statements_failed_searches() -> None:
    failures = [
        SearchFailure("s.t1", 1, "500", FailureOutcome.RETRIED, ""),
        SearchFailure("s.t1", 2, "500", FailureOutcome.RETRIED, ""),
        SearchFailure("s.t2", 1, "500", FailureOutcome.RETRIED, ""),
    ]
    record = run_record(START, ENVIRONMENT, summary(2000, 0), (), 0.01, failures=failures)
    assert record.retried_statements == (RetriedStatement("s.t1", 2), RetriedStatement("s.t2", 1))


def test_a_run_record_lists_the_server_restarts_with_their_times() -> None:
    sessions = [
        session(SessionServing(SwapMethod.IN_PLACE, ("policy-gpu0",))),
        session(SessionServing(SwapMethod.RESTART, restarted=("value-gpu0",)), "2026-11-14T16:00:00+00:00"),
    ]
    record = run_record(START, ENVIRONMENT, summary(2000, 0), (), 0.01, sessions)
    assert record.server_restarts == (ServerRestart("2026-11-14T16:00:00+00:00", ("value-gpu0",)),)


@pytest.mark.parametrize(
    ("swapped", "skipped", "restarted"),
    [
        ((), ("policy-gpu0", "value-gpu0"), ()),
        (("policy-gpu0",), ("value-gpu0",), ()),
        ((), ("policy-gpu0", "value-gpu0"), ("value-gpu0",)),
    ],
    ids=["all_skipped", "one_swapped", "one_restarted"],
)
def test_a_run_skipped_the_swap_only_when_no_session_put_weights_on_a_server(
    swapped: tuple[str, ...], skipped: tuple[str, ...], restarted: tuple[str, ...]
) -> None:
    sessions = [session(SessionServing(SwapMethod.IN_PLACE, swapped, skipped, restarted))]
    record = run_record(START, ENVIRONMENT, summary(2000, 0), (), 0.01, sessions)
    assert record.swap_skipped == (not swapped and not restarted)


def test_a_session_written_before_the_serving_record_reads_back() -> None:
    line = (
        '{"session": "2026-11-14T15:08:25+00:00 pid 71247", "results_before": 271, "policy_digest": "p", '
        '"value_digest": "v", "spoiled": false}'
    )
    assert from_json_object(ProbeSession, json.loads(line)).serving == SessionServing()


@dataclass(frozen=True)
class Restart:
    commands: list[str]
    ports: tuple[int, int]


async def restart_from_merges(directory: Path) -> Restart:
    fakes = [FakeVllmServer(), FakeVllmServer()]
    serving = ServingConfig(
        "policy-base",
        "value-base",
        (ServerEndpoint("policy-gpu0", 0, fakes[0].url, memory_share=0.62),),
        (ServerEndpoint("value-gpu0", 0, fakes[1].url, memory_share=0.28),),
    )
    started: list[ServerStart] = []

    async def start(starts: Sequence[ServerStart]) -> None:
        started.extend(starts)
        fakes[0].state.root, fakes[1].state.root = "/merges/policy", "/merges/value"

    async def verify(assignments: Sequence[ServedWeightsOn], fresh: frozenset[str]) -> tuple[str, ...]:
        return ()

    served = ServedWeights(Path("/merges/policy"), Path("/merges/value"), SwapMethod.RESTART)
    servers = ProbeServers(
        serving,
        served,
        CHECKPOINT,
        directory,
        directory / "results.jsonl",
        verify,
        start,
        RequestFailures(),
        DeathRule(),
    )
    await servers.restart(["policy-gpu0", "value-gpu0"])
    for fake in fakes:
        fake.close()
    return Restart([start.command for start in started], (fakes[0].port, fakes[1].port))


async def restart_failing_to_start(directory: Path) -> list[ProbeSession]:
    serving = ServingConfig(
        "policy-base", "value-base", (ServerEndpoint("policy-gpu0", 0, "http://127.0.0.1:9/v1"),), ()
    )

    async def start(starts: Sequence[ServerStart]) -> None:
        raise RuntimeError("serve_model.sh was killed")

    async def verify(assignments: Sequence[ServedWeightsOn], fresh: frozenset[str]) -> tuple[str, ...]:
        return ()

    served = ServedWeights(Path("/merges/policy"), None, SwapMethod.RESTART)
    servers = ProbeServers(
        serving,
        served,
        CHECKPOINT,
        directory,
        directory / "results.jsonl",
        verify,
        start,
        RequestFailures(),
        DeathRule(),
    )
    with contextlib.suppress(ServerRecoveryError):
        await servers.restart(["policy-gpu0"])
    return read_sessions(directory)


def test_a_restart_cut_off_before_its_server_answered_is_recorded(tmp_path: Path) -> None:
    assert server_restarts(asyncio.run(restart_failing_to_start(tmp_path))) == (
        ServerRestart(read_sessions(tmp_path)[0].started_at, ("policy-gpu0",), completed=False),
    )


def test_a_completed_restart_is_one_restart(tmp_path: Path) -> None:
    asyncio.run(restart_from_merges(tmp_path))
    assert [restart.completed for restart in server_restarts(read_sessions(tmp_path))] == [True]


def test_restarts_granted_in_a_session_raise_the_cap() -> None:
    sessions = [session(SessionServing(restarts_granted=2)), session(SessionServing())]
    assert restart_allowance(sessions, 3) == 5


def test_a_dead_server_is_started_again_from_the_runs_merges(tmp_path: Path) -> None:
    restart = asyncio.run(restart_from_merges(tmp_path))
    policy_port, value_port = restart.ports
    assert restart.commands == [
        "GPU_MEMORY_UTILIZATION=0.62 SLEEP_MODE=1 deployment/serve_model.sh policy-gpu0 /merges/policy 0 "
        f"{policy_port} --served-model-name policy-merged --no-enable-lora --dtype bfloat16 "
        "--logprobs-mode processed_logprobs",
        f"GPU_MEMORY_UTILIZATION=0.28 SLEEP_MODE=1 deployment/serve_model.sh value-gpu0 /merges/value 0 {value_port} "
        "--served-model-name value-merged --no-enable-lora --dtype bfloat16",
    ]
