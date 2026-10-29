"""The GRPO loop's outside world for tests: searches, training job, vLLM servers, evaluation jobs and the value
benchmark's scoring as fakes."""

import asyncio
import dataclasses
import enum
import itertools
import json
import shutil
import types
import typing
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lean_search.corpora.records import StatementRecord
from lean_search.data import Problem
from lean_search.expert_iteration.serving import (
    MergedPublisher,
    ModelVersion,
    read_current,
    record_published,
    write_json_atomically,
)
from lean_search.lean import ProofState
from lean_search.monitoring.families import ValueArmResult
from lean_search.monitoring.store import MetricsWriter
from lean_search.policy.adapters import PREMERGED_MARKER, PremergedWeights, handed_off_weights, handoff_directory
from lean_search.policy.server_control import PhaseSeconds
from lean_search.rl.evaluation import EvaluationKind, EvaluationRun, EvaluationSummary
from lean_search.rl.fixed_sets import HeldOutStatement, Stratum
from lean_search.rl.loop import (
    PHASE_OUTCOME_FILE,
    GrpoLoop,
    GrpoLoopPaths,
    ReleasedLeanMemory,
    TrainingRequest,
    ValueBenchmarkScoring,
)
from lean_search.rl.loop_config import GrpoLoopConfig, parse_loop_config
from lean_search.rl.statement_sources import FixedStatements
from lean_search.rl.training_phase import PhaseOutcome, PolicyOutcome, TrainerTimings, ValueOutcome
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
from lean_search.value.benchmark import BenchmarkScores, ValueBenchmark, benchmark_fingerprint

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
name = "policy-gpu0"
gpu = 0
url = "http://127.0.0.1:8100/v1"

[[serving.policy_servers]]
name = "policy-gpu1"
gpu = 1
url = "http://127.0.0.1:8101/v1"

[[serving.value_servers]]
name = "value-gpu0"
gpu = 0
url = "http://127.0.0.1:8200/v1"

[[serving.value_servers]]
name = "value-gpu1"
gpu = 1
url = "http://127.0.0.1:8201/v1"

[sampling]
search_config = "unused.toml"
concurrency = 2
status_seconds = 0.01

[training]
phase_config = "unused.toml"
gpus = [0, 1]
min_sampling_minutes = 1.0
max_sampling_minutes = 2.0
min_trainable_groups = 2
check_seconds = 0.01
value_every_phases = 1

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
    """Every search proves its statement at once (after its `server_failures`); requests wait while paused."""

    def __init__(self, server_failures: dict[str, int] | None = None) -> None:
        self.open = asyncio.Event()
        self.open.set()
        self.searched: list[str] = []
        self.pauses = 0
        self.policy_versions: list[int] = []
        self.server_failures = dict(server_failures or {})
        self.memory_releases: list[int] = []
        # Shared with the trainer and the servers: the order of the pause's stages.
        self.events: list[str] = []
        # Shared with the servers: while one is down, every search fails.
        self.servers_down: set[str] = set()

    async def search(self, problem: Problem) -> CompletedSearch:
        await self.open.wait()
        await asyncio.sleep(0.001)
        self.searched.append(problem.name)
        if self.servers_down:
            raise httpx.ConnectError(f"{sorted(self.servers_down)} down")
        if self.server_failures.get(problem.name, 0) > 0:
            self.server_failures[problem.name] -= 1
            raise httpx.ConnectError("policy server down")
        accounting = Accounting(expansions=1, nodes=2, edges=2, proofs=1)
        result = SearchResult(
            problem.name, True, StopReason.PROVED, "trivial", ("trivial",), (), accounting, None, 0, 1
        )
        return CompletedSearch(result, solved_tree(problem))

    async def pause(self) -> None:
        self.pauses += 1
        self.open.clear()
        self.events.append("pause")

    def resume(self) -> None:
        self.open.set()
        self.events.append("resume")

    def serving(self, policy_version: int) -> None:
        self.policy_versions.append(policy_version)

    async def release_lean_memory(self, above_bytes: int) -> ReleasedLeanMemory:
        self.memory_releases.append(above_bytes)
        self.events.append(f"stop repls above {above_bytes}")
        return ReleasedLeanMemory(0, 0)


@dataclass
class FakeTrainer:
    """Writes phase.json as the training job does: a new policy adapter, and a value adapter when one trains; with a
    `handoff` root, also the new adapters' merges there, as the persistent job leaves them in host memory."""

    fail_phases: set[int] = field(default_factory=set)
    requests: list[TrainingRequest] = field(default_factory=list)
    prepared: list[TrainingRequest] = field(default_factory=list)
    timings: TrainerTimings = field(default_factory=TrainerTimings)
    events: list[str] = field(default_factory=list)
    # A job of an earlier loop still running.
    earlier_job: str | None = None
    handoff: Path | None = None
    policy_base_model: str = "start-policy"
    value_base_model: str = "value-base"

    def earlier_jobs(self) -> str | None:
        return self.earlier_job

    async def prepare(self, request: TrainingRequest) -> None:
        self.prepared.append(request)

    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        self.requests.append(request)
        self.events.append(f"train {request.phase}")
        if request.phase in self.fail_phases:
            raise RuntimeError(f"training of phase {request.phase} failed")
        policy = dataclasses.replace(zero(PolicyOutcome), adapter=str(request.output_directory / "policy/adapter"))
        value = None
        if request.train_value:
            value = dataclasses.replace(zero(ValueOutcome), adapter=str(request.output_directory / "value/adapter"))
        trees = len(list(request.trees.glob("*.json.gz")))
        outcome = PhaseOutcome(trees=trees, groups=1, policy=policy, value=value, timings=self.timings)
        for adapter in (policy.adapter, *([] if value is None else [value.adapter])):
            Path(adapter).mkdir(parents=True, exist_ok=True)
        if self.handoff is not None:
            hand_off(self.handoff, PremergedWeights(self.policy_base_model, policy.adapter))
            if value is not None:
                hand_off(self.handoff, PremergedWeights(self.value_base_model, value.adapter))
        (request.output_directory / PHASE_OUTCOME_FILE).write_text(to_json(outcome), encoding="utf-8")
        return outcome


def hand_off(root: Path, weights: PremergedWeights) -> None:
    """A merge in host memory as the persistent job leaves it: a directory with its marker."""
    directory = handoff_directory(root, weights.adapter)
    directory.mkdir(parents=True)
    (directory / "merged.json").write_text(json.dumps([weights.base_model, weights.adapter]), encoding="utf-8")
    (directory / PREMERGED_MARKER).write_text(json.dumps(dataclasses.asdict(weights)), encoding="utf-8")


# What every fake release and wake reports as the slowest server's seconds.
RELEASE_SECONDS = PhaseSeconds(pause=1.0, weights=2.0, resume=0.0)
SERVE_SECONDS = PhaseSeconds(pause=0.0, weights=3.0, resume=0.5)


@dataclass
class FakeServers:
    """The servers by name as `VllmServers` treats them: the released ones sleep, sleeping ones wake with a version,
    the others swap to it in place."""

    names: tuple[str, ...] = ()
    released: tuple[str, ...] = ()
    served: list[int] = field(default_factory=list)
    # The policy weights each `serve` loaded.
    served_policy_weights: list[str] = field(default_factory=list)
    releases: int = 0
    # Merged value weights served in place of the version's, in order.
    value_weights: list[str] = field(default_factory=list)
    asleep: set[str] = field(default_factory=set)
    events: list[str] = field(default_factory=list)
    # Servers not answering (shared with the searcher); a restart brings them back unless `restarts_fail`.
    down: set[str] = field(default_factory=set)
    restarts_fail: bool = False
    restarted: list[str] = field(default_factory=list)

    async def check(self) -> None:
        pass

    async def unhealthy(self) -> list[str]:
        return sorted(self.down)

    async def restart(self, names: Sequence[str], version: ModelVersion) -> None:
        self.restarted += names
        self.events += [f"restart {name} v{version.version}" for name in names]
        if not self.restarts_fail:
            self.down.difference_update(names)

    async def release(self) -> PhaseSeconds:
        self.releases += 1
        self.asleep |= set(self.released)
        self.events += [f"sleep {name}" for name in self.released]
        return RELEASE_SECONDS

    async def serve(self, version: ModelVersion) -> PhaseSeconds:
        self.served.append(version.version)
        self.served_policy_weights.append(version.policy_weights)
        self.events += [f"{'wake' if name in self.asleep else 'swap'} {name} v{version.version}" for name in self.names]
        self.asleep.clear()
        return SERVE_SECONDS

    async def serve_value(self, weights: str) -> None:
        self.value_weights.append(weights)
        self.events.append(f"value {Path(weights).name}")


@dataclass
class FakeEvaluations:
    """Each run with the phase it ran in; value arms find the published value model worse when asked. Held-out
    runs report the rates in `held_out_rates` in order (later runs repeat the last), written where the loop's health
    check reads them."""

    runs: list[tuple[EvaluationRun, int]] = field(default_factory=list)
    value_arm_worse: bool = False
    # (valid-Lean rate, per-sample success) per held-out run.
    held_out_rates: list[tuple[float, float]] = field(default_factory=lambda: [(0.8, 0.4)])
    paths: GrpoLoopPaths | None = None

    async def evaluate(self, run: EvaluationRun, phase: int) -> EvaluationSummary:
        self.runs.append((run, phase))
        summary = dataclasses.replace(
            zero(EvaluationSummary), kind=run.kind, problems=10, solved=4 + run.repeat, slot=run.slot
        )
        if run.kind == EvaluationKind.HELD_OUT_STATES:
            return self.held_out_summary(summary, run)
        if run.value_arm:
            assert run.slot is not None
            result = dataclasses.replace(zero(ValueArmResult), slot=run.slot, worse=self.value_arm_worse)
            return dataclasses.replace(summary, value_arm=result)
        return summary

    def held_out_summary(self, summary: EvaluationSummary, run: EvaluationRun) -> EvaluationSummary:
        valid_rate, success = self.held_out_rates[0]
        if len(self.held_out_rates) > 1:
            self.held_out_rates.pop(0)
        summary = dataclasses.replace(summary, samples=1000, valid_samples=round(1000 * valid_rate))
        summary = dataclasses.replace(summary, solved=round(1000 * success))
        if self.paths is not None:
            version = read_current(self.paths.models).version
            directory = self.paths.evaluation_directory(run, version)
            write_json_atomically(directory / "summary.json", summary)
        return summary

    def slots(self, value_arm: bool = False) -> list[tuple[int | None, int]]:
        """(slot, repeat) of the probe runs, or of the value arms."""
        return [
            (run.slot, run.repeat)
            for run, _ in self.runs
            if run.kind == EvaluationKind.PROBE and run.value_arm == value_arm
        ]


def scored_benchmark() -> ValueBenchmark:
    return ValueBenchmark(provenance=(), states=(), groups=())


@dataclass
class FakeValueScorer:
    """Scores the empty benchmark, failing on a server while `failing`; records its start and end in `events`."""

    events: list[str] = field(default_factory=list)
    failing: bool = False

    async def score(self, benchmark: ValueBenchmark) -> BenchmarkScores:
        self.events.append("score")
        await asyncio.sleep(0.001)
        if self.failing:
            raise httpx.ConnectError("value server down")
        self.events.append("scored")
        return BenchmarkScores("value-merged", benchmark_fingerprint(benchmark), ())


def merge_by_writing(base_model: str, adapter: str, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "merged.json").write_text(json.dumps([base_model, adapter]), encoding="utf-8")


def taking_over_handoff(handoff: Path, events: list[str]) -> Callable[[str, str, Path], None]:
    """The production merge's take-over of merges handed off in host memory, else `merge_by_writing` for the CPU
    merge; every merge is an event."""

    def merge(base_model: str, adapter: str, output: Path) -> None:
        handed_off = handed_off_weights(handoff, base_model, adapter)
        events.append(f"write {output.parent.name}/{output.name.removesuffix('.tmp')}")
        if handed_off is None:
            merge_by_writing(base_model, adapter, output)
        else:
            shutil.copytree(handed_off, output)

    return merge


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
    merge: Callable[[str, str, Path], None] = merge_by_writing
    scorer: FakeValueScorer | None = None

    def loop(self, statement_count: int = 6) -> GrpoLoop:
        return GrpoLoop(
            self.config,
            self.paths,
            FixedStatements([statement(number) for number in range(statement_count)]),
            self.searcher,
            self.trainer,
            self.servers,
            MergedPublisher(self.config.serving, self.paths.weights, self.merge),
            self.evaluations,
            MetricsWriter(self.paths.directory),
            print,
            PHASE_TEMPLATE,
            SteppingClock(),
            value_benchmark=None if self.scorer is None else ValueBenchmarkScoring(scored_benchmark(), self.scorer),
        )

    def phases_done(self) -> int:
        return len(self.paths.phases.read_text(encoding="utf-8").splitlines()) if self.paths.phases.exists() else 0


def loop_world(
    root: Path,
    toml: str = LOOP_TOML,
    trainer: FakeTrainer | None = None,
    searcher: FakeSearcher | None = None,
    evaluations: FakeEvaluations | None = None,
    scorer: FakeValueScorer | None = None,
) -> LoopWorld:
    config = parse_loop_config(toml)
    paths = GrpoLoopPaths(root / "runs", root / "data", root / "checkpoints", config.name)
    searcher = searcher or FakeSearcher()
    trainer = trainer or FakeTrainer()
    servers = FakeServers(
        tuple(server.name for server in config.serving.servers),
        tuple(server.name for server in config.released_servers()),
    )
    trainer.events = servers.events = searcher.events
    if scorer is not None:
        scorer.events = searcher.events
    servers.down = searcher.servers_down
    evaluations = evaluations or FakeEvaluations()
    evaluations.paths = paths
    return LoopWorld(config, paths, searcher, trainer, servers, evaluations, scorer=scorer)


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
            await asyncio.sleep(0)
        on_sampling()
    # Each event-loop step: the watcher sleeps after closing a phase and starts none once `stop` is set.
    while world.phases_done() < phases and not task.done():
        await asyncio.sleep(0)
    stop.set()
    await task
