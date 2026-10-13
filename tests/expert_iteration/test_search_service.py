import asyncio
from pathlib import Path

import pytest
from loop_fixtures import verified

from lean_search.corpora.records import write_jsonl
from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.loop_config import (
    EvaluationLoopConfig,
    InitialModels,
    LoopConfig,
    SearchServiceConfig,
    ServerEndpoint,
    ServingConfig,
    ThinkingConfig,
    TrainingConfig,
)
from lean_search.expert_iteration.search_service import SearchService, rescoring_fits, served_run_config
from lean_search.expert_iteration.serving import LoopPaths, ModelVersion, record_published
from lean_search.search import RunConfig
from lean_search.search.records import to_json


@pytest.mark.parametrize(
    ("states", "rate", "fits"),
    [(50_000, None, True), (5_000, 100.0, True), (6_001, 100.0, False)],
    ids=["unmeasured", "within", "beyond"],
)
def test_rescoring_runs_only_when_the_measured_rate_fits_the_limit(states: int, rate: float | None, fits: bool) -> None:
    assert rescoring_fits(states, rate, 60.0) == fits


async def test_the_searches_wait_for_the_curriculum_minimum(tmp_path: Path) -> None:
    curriculum = CurriculumConfig(verified="verified.jsonl", unverified="", minimum_statements=2, reload_seconds=0.01)
    servers = (ServerEndpoint("p", 0, "http://p/v1"), ServerEndpoint("v", 0, "http://v/v1"))
    config = LoopConfig(
        "loop",
        InitialModels("/p", "/v"),
        ServingConfig("base", "base", servers[:1], servers[1:]),
        SearchServiceConfig("search.toml", curriculum=curriculum),
        TrainingConfig(),
        EvaluationLoopConfig("evaluation.toml"),
    )
    paths = LoopPaths(tmp_path / "runs", tmp_path, "loop")
    record_published(paths, ModelVersion(0, "/p", "/v", "now", "initial"))
    write_jsonl(tmp_path / "verified.jsonl", [verified(0, 1)])
    service = SearchService(config, RunConfig(), paths, None, print)
    service.load_state()
    waiting = asyncio.create_task(service.wait_for_curriculum(asyncio.Event()))
    await asyncio.sleep(0.05)
    with (tmp_path / "verified.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(to_json(verified(1, 2)) + "\n")
    assert [statement.identifier for statement in await asyncio.wait_for(waiting, 5.0)] == ["t1"]


def test_a_thinking_loop_samples_in_thinking_mode() -> None:
    servers = (ServerEndpoint("p", 0, "http://p/v1"), ServerEndpoint("v", 0, "http://v/v1"))
    thinking = ThinkingConfig(enabled=True, max_tokens=512, instruction="")
    config = LoopConfig(
        "loop",
        InitialModels("/p", "/v"),
        ServingConfig("base", "base", servers[:1], servers[1:]),
        SearchServiceConfig("search.toml", thinking=thinking),
        TrainingConfig(),
        EvaluationLoopConfig("evaluation.toml"),
    )
    policy = served_run_config(RunConfig(), config).policy
    assert (policy.thinking, policy.max_tokens, policy.model, policy.server_urls) == (
        True,
        512,
        "policy-merged",
        ("http://p/v1",),
    )
