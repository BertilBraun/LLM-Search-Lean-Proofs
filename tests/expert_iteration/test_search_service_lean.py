import asyncio
import json
import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.corpora.records import StatementRecord, write_jsonl
from lean_search.expert_iteration.config import PreferenceConfig
from lean_search.expert_iteration.curriculum import CurriculumConfig
from lean_search.expert_iteration.digests import DigestConfig, digest_new_shards
from lean_search.expert_iteration.known_proofs import VerifiedStatement
from lean_search.expert_iteration.loop_config import (
    EvaluationLoopConfig,
    InitialModels,
    LoopConfig,
    SchedulerConfig,
    SearchServiceConfig,
    SearchStage,
    ServerEndpoint,
    ServingConfig,
    TrainingConfig,
)
from lean_search.expert_iteration.preferences import ValueJumpConfig
from lean_search.expert_iteration.scheduler import Scheduler
from lean_search.expert_iteration.search_service import SearchService
from lean_search.expert_iteration.serving import LoopPaths, ModelVersion, record_published
from lean_search.expert_iteration.shards import Decision, all_attempts, closed_shards, now
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.search.config import parse_run_config
from lean_search.value.labels import TreeLabelConfig

HEADER = "import Mathlib\nimport Aesop\nset_option maxHeartbeats 400000\nopen BigOperators Real Nat Topology Rat"
STATEMENTS = (
    StatementRecord("lean_workbook", "solved", HEADER, "theorem solved : (2 : ℕ) + 2 = 4 := by", "", ""),
    StatementRecord("lean_workbook", "endless", HEADER, "theorem endless : (1 : ℕ) = 2 := by", "", ""),
    StatementRecord("lean_workbook", "broken", HEADER, 'theorem broken : (1 : ℕ) = "a" := by', "", ""),
)
# Every application of the second tactic adds a hypothesis, so the false statement never runs out of new states.
TEMPLATE = """
[lean]
pool_size = 2
concurrency = 2

[automation]
tactics = ["norm_num", "have : (1 : ℕ) = 1 := rfl"]
"""
SERVERS = (ServerEndpoint("gpu0", 0, "http://127.0.0.1:8100/v1"), ServerEndpoint("gpu1", 1, "http://127.0.0.1:8101/v1"))
SCHEDULER = SchedulerConfig(stages=(SearchStage(2, 60.0), SearchStage(4, 60.0)), promising_depth=1)
WAIT_SECONDS = 300

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


def loop_config() -> LoopConfig:
    return LoopConfig(
        name="loop",
        initial=InitialModels("/policy", "/value"),
        serving=ServingConfig("base", "served", "base", SERVERS),
        search=SearchServiceConfig(
            "unused",
            curriculum=CurriculumConfig(verified="pool/verified.jsonl", reload_seconds=1.0),
            concurrency=2,
            heartbeat_seconds=1.0,
            scheduler=SCHEDULER,
        ),
        training=TrainingConfig(),
        evaluation=EvaluationLoopConfig("unused"),
    )


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service_run(tmp_path_factory: pytest.TempPathFactory) -> AsyncIterator[LoopPaths]:
    root = tmp_path_factory.mktemp("loop")
    config = loop_config()
    paths = LoopPaths(root / "runs", root / "data", config.name)
    verified = [
        VerifiedStatement(statement, ("s",), True, "s", tactics, 10, (), False, False, (), 1.0)
        for tactics, statement in enumerate(STATEMENTS, start=1)
    ]
    write_jsonl(paths.data_root / config.search.curriculum.verified, verified)
    record_published(paths, ModelVersion(0, "/policy", "/value", now(), "initial"))
    service = SearchService(config, parse_run_config(TEMPLATE), paths, None, print)
    stop = asyncio.Event()
    task = asyncio.create_task(service.run(stop))
    for _ in range(WAIT_SECONDS):
        counts = service.scheduler.counts()
        if counts.known and counts.fresh == counts.queued == counts.in_flight == 0:
            break
        await asyncio.sleep(1)
    stop.set()
    await task
    yield paths


async def test_each_statement_ends_with_its_decision(service_run: LoopPaths) -> None:
    decisions: dict[str, list[Decision]] = {}
    for attempt in all_attempts(service_run.shards):
        decisions.setdefault(attempt.problem_name, []).append(attempt.decision)
    assert decisions == {
        "lean_workbook.solved": [Decision.SOLVED],
        "lean_workbook.endless": [Decision.ESCALATED, Decision.RETIRED_LAST_STAGE],
        "lean_workbook.broken": [Decision.RETIRED_LOAD_FAILURE],
    }


async def test_an_escalated_search_continues_its_tree(service_run: LoopPaths) -> None:
    endless = [attempt for attempt in all_attempts(service_run.shards) if attempt.problem_name.endswith("endless")]
    assert [(attempt.total_expansions, attempt.tree_file is not None) for attempt in endless] == [(2, False), (4, True)]


async def test_attempts_carry_the_published_version(service_run: LoopPaths) -> None:
    assert {attempt.model_version for attempt in all_attempts(service_run.shards)} == {0}


async def test_stopping_closes_the_open_shard(service_run: LoopPaths) -> None:
    shards = [path for path in service_run.shards.iterdir() if path.is_dir()]
    assert closed_shards(service_run.shards) == sorted(shards)


async def test_a_restarted_scheduler_has_nothing_left_to_do(service_run: LoopPaths) -> None:
    scheduler = Scheduler(SCHEDULER)
    scheduler.add_statements(STATEMENTS)
    scheduler.replay(all_attempts(service_run.shards))
    assert scheduler.next_job() is None


async def test_the_automation_proof_gives_value_labels_but_no_policy_samples(service_run: LoopPaths) -> None:
    config = DigestConfig(PreferenceConfig(), True, ValueJumpConfig(), TreeLabelConfig(), 16)
    summaries = digest_new_shards(service_run.shards, service_run.digests, config)
    assert (
        sum(summary.proofs for summary in summaries),
        sum(summary.policy_samples for summary in summaries),
        sum(summary.value_samples for summary in summaries) > 0,
    ) == (1, 0, True)


async def test_the_curriculum_fed_every_statement(service_run: LoopPaths) -> None:
    heartbeat = json.loads(service_run.heartbeat.read_text(encoding="utf-8"))
    assert (heartbeat["curriculum"]["statements"], heartbeat["curriculum"]["available"]) == (3, 0)
