"""How a probe run's weights reach the servers: skipped where a server already holds byte-identical weights it started
from (serve_model.sh's log and pid file), and how run.json records the run's sessions, restarts and dropped
statements."""

import asyncio
import json
import os
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_vllm import FakeVllmServer

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig, SwapMethod
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary, FailureOutcome, SearchFailure
from lean_search.rl.loop_services import ServerStart
from lean_search.rl.probe_evaluation import (
    ProbeCheckpoint,
    ProbeRunStart,
    ProbeServers,
    ProbeSession,
    RetriedStatement,
    RunEnvironment,
    ServedWeights,
    ServerRestart,
    SessionServing,
    holds_start_weights,
    run_record,
    same_served_weights,
    serve_checkpoint,
)
from lean_search.search.records import from_json_object

CHECKPOINT = ProbeCheckpoint("A", 2, "/policy", "p" * 64, "/value", "v" * 64, 0, 2, 1)
START = ProbeRunStart("identity", False, CHECKPOINT, "search.toml", "c" * 64, 84, 7200.0, 16, "probe.jsonl", "d" * 64)
ENVIRONMENT = RunEnvironment("node", "leanprover/lean4:v4.9.0", "0.31.0", "2.13.0")
FRESH_LOG = "(APIServer pid={pid}) INFO 11-14 14:43:39 [api_utils.py:286] non-default args: {{}}\n"
WAKE_LINE = "(APIServer pid={pid}) INFO 11-14 14:47:39 [api_router.py:42] wake up the engine with tags: ['weights']\n"
RELOAD_LINE = "(EngineCore pid=7) INFO 11-14 14:47:39 [gpu_model_runner.py:5543] Reloading weights inplace...\n"


def server_files(directory: Path, name: str, log: str, process_id: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    (directory / f"{name}.log").write_text(log.format(pid=process_id), encoding="utf-8")


@pytest.mark.parametrize(
    ("log", "process_id", "holds"),
    [
        (FRESH_LOG, os.getpid(), True),
        (FRESH_LOG + WAKE_LINE, os.getpid(), False),
        (FRESH_LOG + RELOAD_LINE, os.getpid(), False),
        (FRESH_LOG, os.getpid() + 100000, False),
    ],
    ids=["fresh", "woken", "reloaded", "another_process"],
)
def test_a_server_holds_its_start_weights_only_without_a_wake_or_reload_since(
    tmp_path: Path, log: str, process_id: int, holds: bool
) -> None:
    server_files(tmp_path, "policy-gpu0", log, process_id)
    assert holds_start_weights(tmp_path, "policy-gpu0") == holds


def test_a_server_without_a_pid_file_holds_nothing_known(tmp_path: Path) -> None:
    assert not holds_start_weights(tmp_path, "policy-gpu0")


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


@pytest.fixture(scope="module")
def skip_history(tmp_path_factory: pytest.TempPathFactory) -> SkipHistory:
    """policy-gpu0 started from byte-identical weights and never swapped, policy-gpu1 woke since its start, value-gpu0
    started from other weights."""
    root = tmp_path_factory.mktemp("skip")
    fakes = [FakeVllmServer(), FakeVllmServer(), FakeVllmServer()]
    serving = ServingConfig(
        "policy-base",
        "value-base",
        (ServerEndpoint("policy-gpu0", 0, fakes[0].url), ServerEndpoint("policy-gpu1", 1, fakes[1].url)),
        (ServerEndpoint("value-gpu0", 0, fakes[2].url),),
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
    for fake, directory in zip(fakes, (started_from, started_from, other), strict=True):
        fake.state.root = str(directory)
    servers = root / "servers"
    server_files(servers, "policy-gpu0", FRESH_LOG, os.getpid())
    server_files(servers, "policy-gpu1", FRESH_LOG + WAKE_LINE, os.getpid())
    server_files(servers, "value-gpu0", FRESH_LOG, os.getpid())
    served = asyncio.run(serve_checkpoint(serving, CHECKPOINT, root / "weights", merge, servers))
    reloads = tuple(tuple(fake.state.reloads) for fake in fakes)
    for fake in fakes:
        fake.close()
    shutil.rmtree(root)
    return SkipHistory(served, reloads)


def test_a_server_holding_identical_start_weights_is_not_swapped(skip_history: SkipHistory) -> None:
    assert skip_history.reloads[0] == ()


def test_a_server_that_swapped_since_its_start_is_swapped(skip_history: SkipHistory) -> None:
    assert skip_history.reloads[1] == (str(skip_history.served.policy),)


def test_a_server_holding_other_weights_is_swapped(skip_history: SkipHistory) -> None:
    assert skip_history.reloads[2] == (str(skip_history.served.value),)


def test_the_skipped_and_swapped_servers_are_named(skip_history: SkipHistory) -> None:
    assert (skip_history.served.skipped, skip_history.served.swapped) == (
        ("policy-gpu0",),
        ("policy-gpu1", "value-gpu0"),
    )


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
    ("swapped", "skipped"), [((), ("policy-gpu0", "value-gpu0")), (("policy-gpu0",), ("value-gpu0",))]
)
def test_a_run_skipped_the_swap_only_when_no_session_put_weights_on_a_server(
    swapped: tuple[str, ...], skipped: tuple[str, ...]
) -> None:
    sessions = [session(SessionServing(SwapMethod.IN_PLACE, swapped, skipped))]
    record = run_record(START, ENVIRONMENT, summary(2000, 0), (), 0.01, sessions)
    assert record.swap_skipped == (not swapped)


def test_a_session_written_before_the_serving_record_reads_back() -> None:
    line = (
        '{"session": "2026-11-14T15:08:25+00:00 pid 71247", "results_before": 271, "policy_digest": "p", '
        '"value_digest": "v", "spoiled": false}'
    )
    assert from_json_object(ProbeSession, json.loads(line)).serving == SessionServing()


async def restart_commands(directory: Path) -> list[str]:
    serving = ServingConfig(
        "policy-base",
        "value-base",
        (ServerEndpoint("policy-gpu0", 0, "http://127.0.0.1:8100/v1", memory_share=0.62),),
        (ServerEndpoint("value-gpu0", 0, "http://127.0.0.1:8200/v1", memory_share=0.28),),
    )
    started: list[ServerStart] = []

    async def start(starts: Sequence[ServerStart]) -> None:
        started.extend(starts)

    async def verify(servers: Sequence[ServerEndpoint]) -> None:
        return

    served = ServedWeights(Path("/merges/policy"), Path("/merges/value"), SwapMethod.RESTART)
    servers = ProbeServers(serving, served, CHECKPOINT, directory, directory / "results.jsonl", verify, start)
    await servers.restart(["policy-gpu0", "value-gpu0"])
    return [start.command for start in started]


def test_a_dead_server_is_started_again_from_the_runs_merges(tmp_path: Path) -> None:
    assert asyncio.run(restart_commands(tmp_path)) == [
        "GPU_MEMORY_UTILIZATION=0.62 SLEEP_MODE=1 deployment/serve_model.sh policy-gpu0 /merges/policy 0 8100 "
        "--served-model-name policy-merged --no-enable-lora --dtype bfloat16 --logprobs-mode processed_logprobs",
        "GPU_MEMORY_UTILIZATION=0.28 SLEEP_MODE=1 deployment/serve_model.sh value-gpu0 /merges/value 0 8200 "
        "--served-model-name value-merged --no-enable-lora --dtype bfloat16",
    ]
