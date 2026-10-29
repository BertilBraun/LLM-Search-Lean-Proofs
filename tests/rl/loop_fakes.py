"""The GRPO loop's outside world for tests: searches, training job, vLLM servers and evaluation jobs as fakes."""

import asyncio
import dataclasses
import enum
import itertools
import json
import types
import typing
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.corpora.records import StatementRecord
from lean_search.data import Problem
from lean_search.expert_iteration.serving import MergedPublisher, ModelVersion, record_published
from lean_search.lean import ProofState
from lean_search.monitoring.store import MetricsWriter
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary
from lean_search.rl.fixed_sets import HeldOutStatement, Stratum
from lean_search.rl.loop import PHASE_OUTCOME_FILE, GrpoLoop, GrpoLoopPaths, TrainingRequest
from lean_search.rl.loop_config import GrpoLoopConfig, parse_loop_config
from lean_search.rl.statement_sources import FixedStatements
from lean_search.rl.training_phase import PhaseOutcome, PolicyOutcome, ValueOutcome
from lean_search.search import (
    Accounting,
    CompletedSearch,
    EdgeOutcome,
    Failure,
    FailureKind,
    SearchResult,
    SearchTree,
    StepSource,
    StopReason,
)
from lean_search.search.records import to_json
from lean_search.value.graph_trainer import GateResult

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
PHASE_TEMPLATE = (REPOSITORY_DIRECTORY / "experiments/configs/grpo/phase.toml").read_text(encoding="utf-8")

LOOP_TOML = """
name = "test_loop"

[initial]
policy_adapter = ""
value_adapter = "value-v0-adapter"

[serving]
policy_base_model = "start-policy"
value_base_model = "value-base"

[[serving.policy_servers]]
name = "policy-gpu1"
gpu = 1
url = "http://127.0.0.1:8101/v1"

[[serving.value_servers]]
name = "value-gpu0"
gpu = 0
url = "http://127.0.0.1:8200/v1"

[sampling]
search_config = "unused.toml"
concurrency = 2
status_seconds = 0.01

[training]
phase_config = "unused.toml"
gpu = 0
min_sampling_minutes = 1.0
max_sampling_minutes = 2.0
min_solved_trees = 2
check_seconds = 0.01
value_benchmark = "gate/benchmark.json.gz"

[evaluation.probe]
max_expansions = 16
max_wall_seconds = 600.0
concurrency = 4
every_hours = 0.0
at_start = false

[evaluation.held_out_states]
max_expansions = 1
max_wall_seconds = 600.0
concurrency = 4
every_hours = 0.0
at_start = false
"""


def zero[T](cls: type[T]) -> T:
    """An instance with every field zero, empty, None or the first enum member."""
    hints = typing.get_type_hints(cls)
    values = {}
    for item in dataclasses.fields(typing.cast(typing.Any, cls)):
        if item.default is not dataclasses.MISSING or item.default_factory is not dataclasses.MISSING:
            continue
        values[item.name] = zero_value(hints[item.name])
    return cls(**values)


def zero_value(hint: object) -> object:
    origin = typing.get_origin(hint)
    if origin is types.UnionType or origin is typing.Union:
        return None
    if origin in (tuple, list):
        return ()
    if origin is dict:
        return {}
    assert isinstance(hint, type), hint
    if dataclasses.is_dataclass(hint):
        return zero(hint)
    if issubclass(hint, enum.Enum):
        return next(iter(hint))
    return hint()


def statement(number: int) -> HeldOutStatement:
    record = StatementRecord("test", f"t{number}", "", f"theorem t{number} : True := by", "", "")
    return HeldOutStatement(record, 1.0 + number % 3, Stratum.EASY)


def solved_tree(problem: Problem) -> SearchTree:
    """The root, a failed policy step, then a policy step that proves it."""
    state = ProofState(problem.header, problem.formal_statement, (), ("⊢ True",), 0, 0)
    tree = SearchTree(problem.name, state, 0.0)
    root = tree.root
    root.expansion_index = 0
    tree.add_edge(
        root,
        text="exact foo",
        source=StepSource.POLICY,
        log_probability=-1.0,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.FAILED,
        failure=Failure(FailureKind.ERROR, "unknown identifier 'foo'"),
    )
    edge = tree.add_edge(
        root,
        text="trivial",
        source=StepSource.POLICY,
        log_probability=-0.5,
        prompt_tokens=0,
        generated_tokens=0,
        outcome=EdgeOutcome.CHILD,
        target_id=tree.next_node_id(),
        applied_tactics=1,
        total_tactics=1,
    )
    proved_state = ProofState(problem.header, problem.formal_statement, ("trivial",), (), 0, 0)
    proved = tree.add_child(root, edge.edge_id, "trivial", StepSource.POLICY, -0.5, proved_state, 0.0, 0.0)
    tree.mark_proof_path(proved)
    tree.settle_statuses()
    return tree


class FakeSearcher:
    """Every search proves its statement at once; requests wait while paused."""

    def __init__(self) -> None:
        self.open = asyncio.Event()
        self.open.set()
        self.searched: list[str] = []
        self.pauses = 0
        self.policy_versions: list[int] = []

    async def search(self, problem: Problem) -> CompletedSearch:
        await self.open.wait()
        await asyncio.sleep(0.001)
        self.searched.append(problem.name)
        accounting = Accounting(expansions=1, nodes=2, edges=2, proofs=1)
        result = SearchResult(
            problem.name, True, StopReason.PROVED, "trivial", ("trivial",), (), accounting, None, 0, 1
        )
        return CompletedSearch(result, solved_tree(problem))

    async def pause(self) -> None:
        self.pauses += 1
        self.open.clear()

    def resume(self) -> None:
        self.open.set()

    def serving(self, policy_version: int) -> None:
        self.policy_versions.append(policy_version)


@dataclass
class FakeTrainer:
    """Writes phase.json as the training job does: a new policy adapter, a value adapter that passes when asked."""

    value_passes: bool = False
    fail_phases: set[int] = field(default_factory=set)
    requests: list[TrainingRequest] = field(default_factory=list)

    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        self.requests.append(request)
        if request.phase in self.fail_phases:
            raise RuntimeError(f"training of phase {request.phase} failed")
        policy = dataclasses.replace(zero(PolicyOutcome), adapter=str(request.output_directory / "policy/adapter"))
        value = None
        if request.train_value:
            gate = dataclasses.replace(zero(GateResult), passed=self.value_passes)
            value = dataclasses.replace(
                zero(ValueOutcome), adapter=str(request.output_directory / "value/adapter"), gate=gate
            )
        outcome = PhaseOutcome(trees=len(list(request.trees.glob("*.json.gz"))), groups=1, policy=policy, value=value)
        request.output_directory.mkdir(parents=True, exist_ok=True)
        (request.output_directory / PHASE_OUTCOME_FILE).write_text(to_json(outcome), encoding="utf-8")
        return outcome


@dataclass
class FakeServers:
    served: list[int] = field(default_factory=list)
    releases: int = 0

    async def check(self) -> None:
        pass

    async def release(self) -> None:
        self.releases += 1

    async def serve(self, version: ModelVersion) -> None:
        self.served.append(version.version)


@dataclass
class FakeEvaluations:
    runs: list[tuple[EvaluationKind, int]] = field(default_factory=list)

    async def evaluate(self, kind: EvaluationKind, phase: int) -> EvaluationSummary:
        self.runs.append((kind, phase))
        return dataclasses.replace(zero(EvaluationSummary), kind=kind, problems=10, solved=4)


def merge_by_writing(base_model: str, adapter: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "merged.json").write_text(json.dumps([base_model, adapter]), encoding="utf-8")


class SteppingClock:
    """Every reading is a minute later, so sampling triggers a phase within a few checks."""

    def __init__(self) -> None:
        self.minutes = itertools.count()

    def __call__(self) -> float:
        return 60.0 * next(self.minutes)


@dataclass
class LoopWorld:
    config: GrpoLoopConfig
    paths: GrpoLoopPaths
    searcher: FakeSearcher
    trainer: FakeTrainer
    servers: FakeServers
    evaluations: FakeEvaluations

    def loop(self, statement_count: int = 6) -> GrpoLoop:
        return GrpoLoop(
            self.config,
            self.paths,
            FixedStatements([statement(number) for number in range(statement_count)]),
            self.searcher,
            self.trainer,
            self.servers,
            MergedPublisher(self.config.serving, self.paths.weights, merge_by_writing),
            self.evaluations,
            MetricsWriter(self.paths.directory),
            print,
            PHASE_TEMPLATE,
            SteppingClock(),
        )

    def phases_done(self) -> int:
        return len(self.paths.phases.read_text(encoding="utf-8").splitlines()) if self.paths.phases.exists() else 0


def loop_world(root: Path, toml: str = LOOP_TOML, trainer: FakeTrainer | None = None) -> LoopWorld:
    config = parse_loop_config(toml)
    paths = GrpoLoopPaths(root / "runs", root / "data", root / "checkpoints", config.name)
    return LoopWorld(config, paths, FakeSearcher(), trainer or FakeTrainer(), FakeServers(), FakeEvaluations())


def record_version_zero(world: LoopWorld) -> None:
    version = ModelVersion(0, "", world.config.initial.value_adapter, "2026-10-29T10:00:00+00:00", "initial")
    publisher = MergedPublisher(world.config.serving, world.paths.weights, merge_by_writing)
    record_published(world.paths.models, publisher.prepare(version))


async def run_until(
    world: LoopWorld, loop: GrpoLoop, phases: int, on_sampling: Callable[[], None] | None = None
) -> None:
    """Runs the loop until `phases` phases closed (the phases log), then stops it; `on_sampling` after a first tree."""
    stop = asyncio.Event()
    task = asyncio.create_task(loop.run(stop))
    if on_sampling is not None:
        while not world.searcher.searched and not task.done():
            await asyncio.sleep(0.001)
        on_sampling()
    while world.phases_done() < phases and not task.done():
        await asyncio.sleep(0.01)
    stop.set()
    await task
