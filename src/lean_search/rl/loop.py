"""The search-tree GRPO loop: search curriculum statements, label the finished trees, pause, train, publish, resume.

`concurrency` workers search statements from the statement source with the published models; every finished tree is
written to the tree store under the phase collecting at that moment. A phase starts once enough sampling produced
enough solved trees and runs these stages, each recorded in loop_state.json so a restarted loop finishes the stage a
crash interrupted (searches cut off by the crash are lost and their statements fed again where the source allows):

pause       every policy and value request waits at the gate; searches keep their trees and REPL states in place
training    the servers on the training GPUs sleep; the training job (grpo_phase.py, data-parallel over those GPUs)
            labels the phase's trees, trains the policy (GRPO) and, every `value_every_phases`, the value model on the
            window of recent phases' trees, gated on the held-out benchmark, and merges the new adapters on the GPUs;
            meanwhile the loop labels the phase's trees for the search and curriculum metrics
publishing  version k + 1 (the new policy adapter, the new value adapter only if it passed the gate) is recorded
            with the job's merges; the sleeping servers wake with it, the others swap to it in place
evaluating  the fixed targets that are due (by loop hours, at the start, or requested) run as separate jobs while
            the searches stay paused, after the paused searches' REPL processes stopped to free host memory; the value
            servers serve the evaluations' fixed value model meanwhile; the value A/B search (both arms) turns μ on
            once the published value model, which passed the gate, is better than the reference, and publishes the
            reference again (μ off) once it is worse
resume      the searches continue with the new weights

The boundaries to the outside (the searches with Lean and vLLM, the training job, the vLLM servers, the evaluation
jobs) are protocols; `loop_services.py` holds the production implementations.
"""

import asyncio
import dataclasses
import datetime
import json
import time
import tomllib
import traceback
from collections import deque
from collections.abc import Callable, Coroutine, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

import httpx

from lean_search.data import Problem
from lean_search.expert_iteration.pool import pool_problem
from lean_search.expert_iteration.serving import (
    LoopPaths,
    ModelVersion,
    Publisher,
    read_current,
    read_versions,
    record_published,
    write_json_atomically,
)
from lean_search.expert_iteration.toml_text import toml_text
from lean_search.monitoring.families import (
    LoopState,
    LoopStatus,
    PauseSegments,
    PhaseTiming,
    ValueAbResult,
    ValueBenchmarkResult,
)
from lean_search.monitoring.store import MetricsWriter
from lean_search.policy.server_control import PhaseSeconds
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary
from lean_search.rl.fixed_targets import target_config
from lean_search.rl.loop_config import EvaluationTarget, EvaluationValueModel, GrpoLoopConfig
from lean_search.rl.phase_metrics import search_phase_record
from lean_search.rl.statement_sources import FedStatement, StatementSource
from lean_search.rl.training_phase import (
    PhaseOutcome,
    TrainerTimings,
    TrainingPhaseConfig,
    grpo_phase_record,
    label_phase_data,
    publish_phase,
)
from lean_search.rl.tree_store import TreeStore
from lean_search.search import CompletedSearch, tree_record
from lean_search.search.records import from_json_object, to_json

IDLE_SECONDS = 30.0
GIB = 2**30
PHASE_OUTCOME_FILE = "phase.json"


class PhaseStage(StrEnum):
    SAMPLING = "sampling"
    TRAINING = "training"
    PUBLISHING = "publishing"
    EVALUATING = "evaluating"


@dataclass(frozen=True)
class LoopProgress:
    # The phase collecting trees (from 1); while it trains, the next one collects.
    phase: int = 1
    stage: PhaseStage = PhaseStage.SAMPLING
    # Sampling of `phase` so far, kept across restarts; frozen once its pause began.
    sampling_seconds: float = 0.0
    training_seconds: float = 0.0
    publishing_seconds: float = 0.0
    value_gate_passed: bool = False
    # The last value adapter trained, accepted or not: the next value training continues it ("": the published one).
    value_adapter: str = ""
    # μ is on: a value model passed the gate and a value A/B search found the published one better than the reference.
    value_share_on: bool = False
    # The pause of `phase` so far, segment by segment.
    pause: PauseSegments = field(default_factory=PauseSegments)
    # Sampling and training of all finished phases: the clock of the evaluation schedule.
    loop_seconds: float = 0.0
    # Loop seconds when each fixed target last ran; None: never.
    probe_at: float | None = None
    minif2f_at: float | None = None
    held_out_states_at: float | None = None
    value_ab_at: float | None = None


@dataclass(frozen=True)
class PhaseRecord:
    phase: int
    trees: int
    solved_trees: int
    sampling_seconds: float
    training_seconds: float
    publishing_seconds: float
    evaluation_seconds: float
    policy_version: int
    value_accepted: bool
    evaluations: tuple[EvaluationKind, ...]
    finished_at: str
    pause: PauseSegments = field(default_factory=PauseSegments)


@dataclass(frozen=True)
class ReleasedLeanMemory:
    stopped_processes: int
    # Their private (anonymous) memory when they stopped.
    freed_bytes: int


@dataclass(frozen=True)
class TrainingRequest:
    phase: int
    config_text: str
    trees: Path
    run_name: str
    output_directory: Path
    train_value: bool
    # The value model's window: the tree directories of the last phases, this one's included.
    value_trees: tuple[Path, ...] = ()


class TreeSearcher(Protocol):
    async def search(self, problem: Problem) -> CompletedSearch: ...

    async def pause(self) -> None:
        """Returns once no request is in flight; later requests wait until resume."""
        ...

    def resume(self) -> None: ...

    def serving(self, policy_version: int) -> None:
        """The servers now answer with this published version (recorded with every expansion's samples)."""

    async def release_lean_memory(self, above_bytes: int) -> ReleasedLeanMemory:
        """Stops the REPL processes above `above_bytes` of private memory; their proof states replay on next use."""
        ...


class PhaseTrainer(Protocol):
    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        """Trains on the phase's trees; the outcome is also in output_directory/phase.json."""
        ...

    def earlier_jobs(self) -> str | None:
        """What still runs of the training and evaluation jobs of a loop that died without stopping them, if any."""
        ...


class ModelServers(Protocol):
    async def check(self) -> None:
        """Raises when a server does not answer."""
        ...

    async def release(self) -> PhaseSeconds:
        """Frees the training GPUs: their servers drain and sleep; the slowest server's seconds per part."""
        ...

    async def serve(self, version: ModelVersion) -> PhaseSeconds:
        """Every server serves the version: sleeping ones wake with it, running ones swap in place; the slowest
        server's seconds per part."""
        ...

    async def serve_value(self, weights: str) -> None:
        """Every value server serves these merged value weights; the policy servers keep theirs."""
        ...

    async def unhealthy(self) -> list[str]:
        """The names of the servers that do not answer their health check."""
        ...

    async def restart(self, names: Sequence[str], version: ModelVersion) -> None:
        """Stops what is left of these servers and starts them on the version; raises when one does not come up."""
        ...


class Evaluations(Protocol):
    async def evaluate(
        self, kind: EvaluationKind, phase: int, repeat: int, value_model: EvaluationValueModel
    ) -> EvaluationSummary:
        """`repeat` > 0: another independent run of the same version (the probe's noise at the start);
        `value_model`: the one the value servers serve for it."""
        ...


@dataclass(frozen=True)
class GrpoLoopPaths:
    runs_root: Path
    data_root: Path
    checkpoints_root: Path
    name: str

    @property
    def directory(self) -> Path:
        return self.runs_root / self.name

    @property
    def models(self) -> LoopPaths:
        """models/current.json and models/versions.jsonl, as the expert-iteration loop keeps them."""
        return LoopPaths(self.runs_root, self.data_root, self.name)

    @property
    def config(self) -> Path:
        return self.directory / "loop.toml"

    @property
    def progress(self) -> Path:
        return self.directory / "loop_state.json"

    @property
    def trees(self) -> Path:
        return self.directory / "trees"

    @property
    def phases(self) -> Path:
        return self.directory / "phases.jsonl"

    @property
    def training(self) -> Path:
        return self.directory / "training"

    @property
    def requests(self) -> Path:
        return self.directory / "requests"

    @property
    def evaluations(self) -> Path:
        return self.directory / "evaluations"

    @property
    def curriculum(self) -> Path:
        return self.directory / "curriculum.json"

    @property
    def log(self) -> Path:
        return self.directory / "loop.log"

    @property
    def children(self) -> Path:
        """A record per running training or evaluation job, so a restarted loop never starts a second one."""
        return self.directory / "children"

    @property
    def weights(self) -> Path:
        return self.checkpoints_root / self.name / "weights"

    def phase_run_name(self, phase: int) -> str:
        return f"{self.name}_phase_{phase:04d}"

    def phase_checkpoints(self, phase: int) -> Path:
        return self.checkpoints_root / self.phase_run_name(phase)

    def evaluation_directory(
        self, kind: EvaluationKind, version: int, repeat: int = 0, arm: EvaluationValueModel | None = None
    ) -> Path:
        """`arm`: the value A/B's run with that value model."""
        name = f"{kind}_v{version:04d}" + (f"_{arm}" if arm else "") + (f"_repeat{repeat}" if repeat else "")
        return self.evaluations / name


def now() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")


def read_progress(path: Path) -> LoopProgress:
    if not path.exists():
        return LoopProgress()
    return from_json_object(LoopProgress, json.loads(path.read_text(encoding="utf-8")))


def read_phase_outcome(path: Path) -> PhaseOutcome:
    return from_json_object(PhaseOutcome, json.loads(path.read_text(encoding="utf-8")))


def phase_trigger(phase: int) -> str:
    return f"phase {phase}"


def value_adapter_version(versions: list[ModelVersion], adapter: str) -> int:
    """The version that first published the value adapter."""
    return next(version.version for version in versions if version.value_adapter == adapter)


def value_version(versions: list[ModelVersion]) -> int:
    """The version that first published the current value adapter."""
    return value_adapter_version(versions, versions[-1].value_adapter)


def value_published_by(versions: list[ModelVersion], phase: int) -> bool:
    published = [index for index, version in enumerate(versions) if version.trigger == phase_trigger(phase)]
    return bool(published) and versions[published[0]].value_adapter != versions[published[0] - 1].value_adapter


def phase_config_text(
    template: str,
    policy_base_model: str,
    starting_policy_adapter: str,
    current: ModelVersion,
    phase: int,
    value_share: float,
    value_adapter: str | None,
) -> str:
    """The template with the published policy adapter to continue from (on the policy base), the starting policy's
    adapter as the KL reference, μ and per-phase seeds; `value_adapter` is the value adapter to continue (None: the
    value model does not train), which the gate compares with the published one."""
    table = tomllib.loads(template)
    for section in ("reward", "value_targets"):
        table.setdefault(section, {})["value_share"] = value_share
    policy = table["policy"]
    policy["model"] = policy_base_model
    policy["initial_adapter"] = current.policy_adapter
    policy["reference_adapter"] = starting_policy_adapter
    policy.setdefault("optimization", {})["seed"] = phase
    table.setdefault("policy_replay", {})["seed"] = f"grpo-replay/{phase}"
    if value_adapter is None:
        table.pop("value", None)
    else:
        value = table["value"]
        if value_adapter:
            value["initial_adapter"] = value_adapter
        value["published_adapter"] = current.value_adapter
        value.setdefault("optimization", {})["seed"] = phase
    return toml_text(table)


def evaluation_due(target: EvaluationTarget, last: float | None, loop_seconds: float, at_start: bool) -> bool:
    if at_start:
        return target.at_start and last is None
    return target.every_hours > 0 and (last is None or loop_seconds - last >= target.every_hours * 3600)


def last_evaluation(progress: LoopProgress, kind: EvaluationKind) -> float | None:
    match kind:
        case EvaluationKind.PROBE:
            return progress.probe_at
        case EvaluationKind.MINIF2F:
            return progress.minif2f_at
        case EvaluationKind.HELD_OUT_STATES:
            return progress.held_out_states_at
        case EvaluationKind.VALUE_AB:
            return progress.value_ab_at


def evaluated(progress: LoopProgress, kind: EvaluationKind) -> LoopProgress:
    match kind:
        case EvaluationKind.PROBE:
            return dataclasses.replace(progress, probe_at=progress.loop_seconds)
        case EvaluationKind.MINIF2F:
            return dataclasses.replace(progress, minif2f_at=progress.loop_seconds)
        case EvaluationKind.HELD_OUT_STATES:
            return dataclasses.replace(progress, held_out_states_at=progress.loop_seconds)
        case EvaluationKind.VALUE_AB:
            return dataclasses.replace(progress, value_ab_at=progress.loop_seconds)


def request_evaluation(paths: GrpoLoopPaths, kind: EvaluationKind) -> None:
    """The running loop evaluates `kind` at its next phase pause (a milestone)."""
    paths.requests.mkdir(parents=True, exist_ok=True)
    (paths.requests / kind.value).write_text(now(), encoding="utf-8")


def with_trainer_timings(pause: PauseSegments, timings: TrainerTimings, job_seconds: float) -> PauseSegments:
    """The training job's parts; what its own clock did not see is the job's start (and exit)."""
    return dataclasses.replace(
        pause,
        trainer_start_seconds=max(0.0, job_seconds - timings.total_seconds),
        preparation_seconds=timings.preparation_seconds,
        policy_load_seconds=timings.policy_load_seconds,
        compile_seconds=timings.compile_seconds,
        scoring_seconds=timings.scoring_seconds,
        policy_training_seconds=timings.policy_training_seconds,
        value_training_seconds=timings.value_training_seconds,
        gate_seconds=timings.gate_seconds,
        merge_seconds=timings.merge_seconds,
        write_seconds=timings.write_seconds,
    )


def pause_text(pause: PauseSegments) -> str:
    return ", ".join(
        f"{name.removesuffix('_seconds').replace('_', ' ')} {seconds:.0f} s"
        for name, seconds in dataclasses.asdict(pause).items()
    )


def published_time(version: ModelVersion) -> float:
    return datetime.datetime.fromisoformat(version.published_at).timestamp()


def earlier_value_ab_results(paths: GrpoLoopPaths, version: int, published_value_version: int) -> list[ValueAbResult]:
    """The comparisons of the other value A/Bs of this published value model, pooled with this version's."""
    own = paths.evaluation_directory(EvaluationKind.VALUE_AB, version, 0, EvaluationValueModel.PUBLISHED)
    pattern = f"{EvaluationKind.VALUE_AB}_v*_{EvaluationValueModel.PUBLISHED}/comparison.json"
    results = [
        from_json_object(ValueAbResult, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(paths.evaluations.glob(pattern))
        if path.parent != own
    ]
    return [result for result in results if result.published_value_version == published_value_version]


def publish_value_model(paths: LoopPaths, publisher: Publisher, value_adapter: str, trigger: str) -> ModelVersion:
    """The next version: the current policy with this value adapter."""
    current = read_current(paths)
    version = ModelVersion(current.version + 1, current.policy_adapter, value_adapter, now(), trigger)
    prepared = publisher.prepare(version)
    record_published(paths, prepared)
    publisher.prune(prepared)
    return prepared


class GrpoLoop:
    def __init__(
        self,
        config: GrpoLoopConfig,
        paths: GrpoLoopPaths,
        statements: StatementSource,
        searcher: TreeSearcher,
        trainer: PhaseTrainer,
        servers: ModelServers,
        publisher: Publisher,
        evaluations: Evaluations,
        writer: MetricsWriter,
        log: Callable[[str], None],
        phase_template: str,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """`phase_template`: the text of the training phase config (config.training.phase_config)."""
        self.config = config
        self.paths = paths
        self.statements = statements
        self.searcher = searcher
        self.trainer = trainer
        self.servers = servers
        self.publisher = publisher
        self.evaluations = evaluations
        self.writer = writer
        self.log = log
        self.clock = clock
        self.progress = read_progress(paths.progress)
        self.store = TreeStore(paths.trees)
        self.store_lock = asyncio.Lock()
        self.collecting = self.progress.phase
        self.sampling_since: float | None = None
        self.paused = False
        self.loop_state = LoopState.SEARCHING
        self.searches_running = 0
        self.session_started = clock()
        self.session_trees = 0
        self.session_proofs = 0
        self.server_failures: dict[str, int] = {}
        self.session_server_failures = 0
        self.statements_given_up = 0
        # The last searches to end, True for those a server failed.
        self.recent_searches: deque[bool] = deque(maxlen=config.sampling.server_failure_window)
        # One pause of the searches at a time: a phase's, or a check of the servers.
        self.pause_lock = asyncio.Lock()
        self.failure: BaseException | None = None
        # The merged value weights the value servers serve: the published version's, or an evaluation's fixed ones.
        self.served_value_weights = ""
        self.phase_template = phase_template
        from_json_object(TrainingPhaseConfig, tomllib.loads(phase_template))
        self.update_context()

    def save_progress(self, **changes: object) -> None:
        self.progress = dataclasses.replace(self.progress, **changes)
        write_json_atomically(self.paths.progress, self.progress)

    def update_context(self) -> None:
        versions = read_versions(self.paths.models)
        if versions:
            self.writer.update_context(
                phase=self.progress.phase, policy_version=versions[-1].version, value_version=value_version(versions)
            )
        else:
            self.writer.update_context(phase=self.progress.phase)

    def sampling_seconds(self) -> float:
        running = 0.0 if self.sampling_since is None else self.clock() - self.sampling_since
        return self.progress.sampling_seconds + running

    def phase_due(self) -> bool:
        training = self.config.training
        minutes = self.sampling_seconds() / 60
        solved = sum(entry.proved for entry in self.store.phase_entries(self.progress.phase))
        if minutes >= training.max_sampling_minutes:
            return solved >= 1
        return minutes >= training.min_sampling_minutes and solved >= training.min_solved_trees

    async def run(self, stop: asyncio.Event) -> None:
        session = asyncio.create_task(self.stopping_on_failure(self.session(stop), stop))
        try:
            await stop.wait()
        finally:
            # Cancelling also stops a training or evaluation job in flight (`loop_services.run_logged`).
            session.cancel()
            await asyncio.gather(session, return_exceptions=True)
            if self.progress.stage == PhaseStage.SAMPLING:
                self.save_progress(sampling_seconds=self.sampling_seconds())
            self.loop_state = LoopState.STOPPED
            self.write_status()
            self.log(f"Stopped after {self.session_trees:,} trees and {self.session_proofs:,} proofs this session")
        if self.failure is not None:
            raise RuntimeError("The loop stopped on a failure; a restart resumes it") from self.failure

    async def session(self, stop: asyncio.Event) -> None:
        # Waking the servers into the GPU memory of an orphaned training job would fail the wake or the next training.
        earlier = self.trainer.earlier_jobs()
        if earlier is not None:
            raise RuntimeError(earlier)
        await self.servers.check()
        current = read_current(self.paths.models)
        await self.servers.serve(current)
        self.served_value_weights = current.value_weights
        self.searcher.serving(current.version)
        if self.progress.stage != PhaseStage.SAMPLING:
            self.log(f"Finishing phase {self.progress.phase} from {self.progress.stage}")
            self.collecting = self.progress.phase + 1
            await self.finish_phase()
        await self.run_evaluations(self.due_evaluations(at_start=True), self.progress.phase - 1, at_start=True)
        self.sampling_since = self.clock()
        coroutines: list[Coroutine[None, None, None]] = [
            self.work(stop) for _ in range(self.config.sampling.concurrency)
        ]
        coroutines += [self.watch(stop), self.report_status(stop)]
        await asyncio.gather(*(self.stopping_on_failure(coroutine, stop) for coroutine in coroutines))

    async def stopping_on_failure(self, coroutine: Coroutine[None, None, None], stop: asyncio.Event) -> None:
        try:
            await coroutine
        except Exception as error:
            self.log(f"Stopping on {type(error).__name__}: {error}\n{traceback.format_exc()}")
            self.failure = error
            stop.set()

    async def work(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            fed = self.statements.next_statement()
            if fed is None:
                await asyncio.sleep(IDLE_SECONDS)
                continue
            self.searches_running += 1
            try:
                completed = await self.searcher.search(pool_problem(fed.statement))
            except httpx.HTTPError as error:
                self.server_failed(fed, error)
                self.recent_searches.append(True)
                if self.servers_failing():
                    await self.recover_servers()
                else:
                    await asyncio.sleep(self.config.sampling.server_failure_pause_seconds)
                continue
            except BaseException:
                self.statements.abandon(fed.name)
                raise
            finally:
                self.searches_running -= 1
            self.recent_searches.append(False)
            result = completed.result
            if completed.tree is not None:
                # The statement searched: the renamed one when the loop renames hypotheses.
                record = tree_record(completed.tree, completed.tree.root.state.statement, result)
                version = read_current(self.paths.models).version
                async with self.store_lock:
                    await asyncio.to_thread(self.store.add, record, self.collecting, version, fed.difficulty)
            self.statements.record_outcome(fed.name, result.proved)
            self.server_failures.pop(fed.name, None)
            self.session_trees += 1
            self.session_proofs += result.accounting.proofs

    def server_failed(self, fed: FedStatement, error: httpx.HTTPError) -> None:
        """A policy or value server failed the search, which says nothing about the statement: it is fed again."""
        self.session_server_failures += 1
        failures = self.server_failures.get(fed.name, 0) + 1
        if failures <= self.config.sampling.server_failure_retries:
            self.server_failures[fed.name] = failures
            self.statements.retry(fed)
            self.log(f"{fed.name}: {type(error).__name__}: {error}; fed again ({failures} failures)")
            return
        self.server_failures.pop(fed.name, None)
        self.statements_given_up += 1
        self.statements.abandon(fed.name)
        self.log(f"{fed.name}: {type(error).__name__}: {error}; given up after {failures} failures")

    def servers_failing(self) -> bool:
        sampling = self.config.sampling
        failed = sum(self.recent_searches)
        return len(self.recent_searches) == sampling.server_failure_window and (
            failed >= sampling.server_failure_share * sampling.server_failure_window
        )

    async def recover_servers(self) -> None:
        """Pauses the searches and checks the servers: restarts the dead ones, and stops the loop if any stays down
        (stopped is better than idle GPUs until someone looks)."""
        async with self.pause_lock:
            if not self.servers_failing():
                return
            self.log(
                f"{sum(self.recent_searches)} of the last {len(self.recent_searches)} searches failed on a server: "
                "pausing the searches to check the servers"
            )
            self.loop_state = LoopState.PAUSED
            self.write_status()
            await self.searcher.pause()
            down = await self.servers.unhealthy()
            if down and not self.config.sampling.restart_dead_servers:
                raise RuntimeError(f"Servers not answering: {down}; start them (grpo_loop.sh servers), then the loop.")
            if down:
                self.log(f"Servers not answering: {down}; restarting them")
                await self.servers.restart(down, read_current(self.paths.models))
                still_down = await self.servers.unhealthy()
                if still_down:
                    raise RuntimeError(
                        f"Servers {still_down} do not answer after a restart (logs: $LEAN_SEARCH_RUNS/servers/); "
                        "start them (grpo_loop.sh servers), then the loop."
                    )
                self.log(f"Restarted {down}; the searches resume")
            else:
                self.log("Every server answers; the searches resume")
            self.recent_searches.clear()
            self.searcher.resume()
            self.loop_state = LoopState.SEARCHING
            self.write_status()

    async def watch(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(self.config.training.check_seconds)
            for message in self.statements.refresh():
                self.log(message)
            if not stop.is_set() and self.phase_due():
                async with self.pause_lock:
                    await self.run_phase()
            elif self.sampling_since is not None:
                self.save_progress(sampling_seconds=self.sampling_seconds())
                self.sampling_since = self.clock()

    async def report_status(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            self.write_status()
            await asyncio.sleep(self.config.sampling.status_seconds)

    def write_status(self) -> None:
        hours = max(1e-9, (self.clock() - self.session_started) / 3600)
        current = read_current(self.paths.models)
        self.writer.write(
            LoopStatus(
                state=self.loop_state,
                heartbeat_seconds=self.config.sampling.status_seconds,
                searches_running=self.searches_running,
                statements_attempted=len(self.store.entries),
                statements_solved=sum(entry.proved for entry in self.store.entries),
                proofs=sum(entry.proofs for entry in self.store.entries),
                proofs_per_hour=self.session_proofs / hours,
                statements_per_hour=self.session_trees / hours,
                last_publish_time=published_time(current) if current.version else None,
                server_failures=self.session_server_failures,
                statements_given_up=self.statements_given_up,
            )
        )

    async def run_phase(self) -> None:
        phase = self.progress.phase
        sampling = self.sampling_seconds()
        self.collecting = phase + 1
        self.sampling_since = None
        self.loop_state = LoopState.PAUSED
        self.write_status()
        pause_started = self.clock()
        await self.searcher.pause()
        drain_seconds = self.clock() - pause_started
        self.paused = True
        async with self.store_lock:
            # A tree being written when the phase began still lands in this phase's directory.
            entries = self.store.phase_entries(phase)
        self.log(
            f"Phase {phase}: {len(entries)} trees ({sum(entry.proved for entry in entries)} solved) after "
            f"{sampling / 60:.1f} min of sampling; {self.searches_running} searches paused"
        )
        self.save_progress(
            stage=PhaseStage.TRAINING, sampling_seconds=sampling, pause=PauseSegments(drain_seconds=drain_seconds)
        )
        await self.finish_phase()

    async def finish_phase(self) -> None:
        phase = self.progress.phase
        if self.progress.stage == PhaseStage.TRAINING:
            self.loop_state = LoopState.TRAINING
            self.write_status()
            started = self.clock()
            await self.servers.release()
            released = self.clock()
            outcome = await self.train(phase)
            finished = self.clock()
            pause = with_trainer_timings(self.progress.pause, outcome.timings, finished - released)
            self.save_progress(
                stage=PhaseStage.PUBLISHING,
                training_seconds=finished - started,
                pause=dataclasses.replace(pause, server_sleep_seconds=released - started),
            )
        if self.progress.stage == PhaseStage.PUBLISHING:
            self.loop_state = LoopState.PUBLISHING
            self.write_status()
            started = self.clock()
            await self.publish(phase)
            progress = self.progress
            self.save_progress(
                stage=PhaseStage.EVALUATING,
                publishing_seconds=self.clock() - started,
                loop_seconds=progress.loop_seconds + progress.sampling_seconds + progress.training_seconds,
            )
        started = self.clock()
        kinds = self.due_evaluations(at_start=False)
        await self.run_evaluations(kinds, phase)
        self.close_phase(phase, kinds, self.clock() - started)
        if self.paused:
            self.searcher.resume()
            self.paused = False
        self.loop_state = LoopState.SEARCHING
        self.sampling_since = self.clock()
        self.write_status()

    def value_window(self, phase: int) -> tuple[Path, ...]:
        """The tree directories the value model trains on when it is due this phase; none when it is not."""
        training = self.config.training
        if not (training.value_benchmark and training.value_every_phases and phase % training.value_every_phases == 0):
            return ()
        first = max(1, phase - training.value_window_phases + 1)
        return tuple(self.store.phase_directory(number) for number in range(first, phase + 1))

    async def train(self, phase: int) -> PhaseOutcome:
        current = read_current(self.paths.models)
        training = self.config.training
        value_trees = self.value_window(phase)
        value_share = training.value_share_after_gate if self.progress.value_share_on else 0.0
        config_text = phase_config_text(
            self.phase_template,
            self.config.serving.policy_base_model,
            self.config.initial.policy_adapter,
            current,
            phase,
            value_share,
            (self.progress.value_adapter or current.value_adapter) if value_trees else None,
        )
        request = TrainingRequest(
            phase,
            config_text,
            self.store.phase_directory(phase),
            self.paths.phase_run_name(phase),
            self.paths.phase_checkpoints(phase),
            bool(value_trees),
            value_trees,
        )
        labelling = asyncio.create_task(asyncio.to_thread(self.write_search_metrics, phase, config_text))
        outcome = await self.trainer.train(request)
        await labelling
        if outcome.value is not None:
            self.save_progress(value_adapter=outcome.value.adapter)
        self.log(
            f"Phase {phase} trained: {outcome.trees} trees, {outcome.groups} groups"
            + ("" if outcome.value is None else f", value {'accepted' if outcome.value.accepted else 'rejected'}")
        )
        return outcome

    def write_search_metrics(self, phase: int, config_text: str) -> None:
        entries = self.store.phase_entries(phase)
        self.writer.write(self.statements.phase_record(entries))
        records = self.store.records(phase)
        if not records:
            return
        config = from_json_object(TrainingPhaseConfig, tomllib.loads(config_text))
        labelled = label_phase_data(records, config)
        self.writer.write(search_phase_record(records, labelled.statistics))

    async def publish(self, phase: int) -> None:
        outcome = read_phase_outcome(self.paths.phase_checkpoints(phase) / PHASE_OUTCOME_FILE)
        current = read_current(self.paths.models)
        started = self.clock()
        if current.trigger != phase_trigger(phase):
            self.write_training_metrics(outcome, current.version + 1)
            current = await asyncio.to_thread(
                publish_phase, self.paths.models, self.publisher, outcome, phase_trigger(phase)
            )
        published = self.clock()
        served = await self.servers.serve(current)
        self.save_progress(
            pause=dataclasses.replace(
                self.progress.pause,
                publish_seconds=published - started,
                wake_seconds=served.pause + served.weights,
                resume_seconds=served.resume,
            )
        )
        self.served_value_weights = current.value_weights
        self.searcher.serving(current.version)
        if outcome.value is not None and outcome.value.accepted:
            self.log(f"Value model of phase {phase} passed the gate and is published")
            self.save_progress(value_gate_passed=True)
        self.log(f"Published version {current.version}")

    def write_training_metrics(self, outcome: PhaseOutcome, candidate_version: int) -> None:
        if outcome.policy is not None:
            self.writer.write(grpo_phase_record(outcome.policy, self.progress.sampling_seconds, candidate_version - 1))
        if outcome.value is not None and outcome.value.gate is not None:
            gate = outcome.value.gate
            self.writer.write(
                ValueBenchmarkResult(
                    candidate_version=candidate_version,
                    gate_passed=outcome.value.accepted,
                    benchmark=gate.new,
                    training_loss=outcome.value.result.final_pointwise_loss,
                    gate=gate.statistic,
                    published_benchmark=gate.current,
                    trees=outcome.value.trees,
                    diagnostics=outcome.value.diagnostics,
                )
            )

    def value_ab_possible(self) -> bool:
        """The published value model differs from the reference the A/B compares it with."""
        return read_current(self.paths.models).value_adapter != self.config.initial.value_adapter

    def due_evaluations(self, at_start: bool) -> list[EvaluationKind]:
        """The value A/B waits (a request too) until a value model other than the reference is published."""
        due = []
        for kind in EvaluationKind:
            if kind == EvaluationKind.VALUE_AB and not self.value_ab_possible():
                continue
            requested = (self.paths.requests / kind.value).exists()
            target = target_config(self.config.evaluation, kind)
            last = last_evaluation(self.progress, kind)
            if requested or evaluation_due(target, last, self.progress.loop_seconds, at_start):
                due.append(kind)
        return due

    def value_weights(self, value_model: EvaluationValueModel) -> str:
        current = read_current(self.paths.models)
        reference = self.config.initial.value_adapter
        match value_model:
            case EvaluationValueModel.INITIAL if current.value_adapter != reference:
                return self.publisher.kept_value_weights(reference)
            case EvaluationValueModel.INITIAL | EvaluationValueModel.PUBLISHED:
                return current.value_weights

    async def serve_value_model(self, value_model: EvaluationValueModel) -> None:
        weights = await asyncio.to_thread(self.value_weights, value_model)
        if weights != self.served_value_weights:
            self.log(f"Value servers: {value_model} value model ({weights})")
            await self.servers.serve_value(weights)
            self.served_value_weights = weights

    async def evaluate(self, kind: EvaluationKind, phase: int, repeat: int) -> EvaluationSummary:
        value_model = self.config.evaluation.value_model
        await self.serve_value_model(value_model)
        return await self.evaluations.evaluate(kind, phase, repeat, value_model)

    async def run_value_ab(self, phase: int) -> None:
        """Both arms with the policy fixed; μ turns on once the published value model is better than the reference,
        and the reference is published again (μ off) once it is worse."""
        for arm in (EvaluationValueModel.INITIAL, EvaluationValueModel.PUBLISHED):
            await self.serve_value_model(arm)
            summary = await self.evaluations.evaluate(EvaluationKind.VALUE_AB, phase, 0, arm)
        result = summary.value_ab
        assert result is not None, "the published arm compares itself with the reference arm"
        self.log(
            f"Value A/B of version {summary.policy_version}: published value v{result.published_value_version} "
            f"{result.published_solved} vs reference {result.reference_solved} of {result.problems} "
            f"({result.only_published} vs {result.only_reference} solved by one arm only); pooled over "
            f"{result.pooled_runs} runs {result.pooled_only_published} vs {result.pooled_only_reference}, "
            f"p(better) = {result.better_p_value:.3f}, p(worse) = {result.worse_p_value:.3f}"
        )
        if result.worse:
            await self.revert_value_model(result.published_value_version)
        elif result.passed and not self.progress.value_share_on:
            self.log(f"The published value model is better than v0: μ = {self.config.training.value_share_after_gate}")
            self.save_progress(value_share_on=True)

    async def revert_value_model(self, value_version: int) -> None:
        """The reference value model is published again; value training continues from it, with μ off."""
        self.save_progress(value_share_on=False, value_adapter="")
        current = await asyncio.to_thread(
            publish_value_model,
            self.paths.models,
            self.publisher,
            self.config.initial.value_adapter,
            f"value v{value_version} worse than v0 in the A/B",
        )
        await self.servers.serve(current)
        self.served_value_weights = current.value_weights
        self.searcher.serving(current.version)
        self.update_context()
        self.log(f"Value v{value_version} is worse than v0: version {current.version} serves v0's value model, μ off")

    async def run_evaluations(self, kinds: list[EvaluationKind], phase: int, at_start: bool = False) -> None:
        if not kinds:
            return
        # Only between phases or before the workers start: the searches are paused or not running.
        self.loop_state = LoopState.EVALUATING
        self.write_status()
        threshold = int(self.config.evaluation.paused_repl_memory_gib * GIB)
        released = await self.searcher.release_lean_memory(threshold)
        self.log(
            f"Stopped {released.stopped_processes} search REPL processes ({released.freed_bytes / GIB:.1f} GiB) "
            "for the evaluations"
        )
        for kind in kinds:
            if kind == EvaluationKind.VALUE_AB:
                await self.run_value_ab(phase)
                self.mark_evaluated(kind)
                continue
            summaries = [await self.evaluate(kind, phase, repeat) for repeat in range(self.runs(kind, at_start))]
            for repeat, summary in enumerate(summaries):
                self.log(
                    f"Evaluation {kind} of version {summary.policy_version}"
                    + (f" (repeat {repeat})" if repeat else "")
                    + f": {summary.solved}/{summary.problems}, {summary.wall_clock_stops} stopped on the wall clock"
                )
            if len(summaries) > 1:
                solved = [summary.solved for summary in summaries]
                self.log(f"Evaluation {kind} run to run: solved {solved}, difference {max(solved) - min(solved)}")
            self.mark_evaluated(kind)
        await self.serve_value_model(EvaluationValueModel.PUBLISHED)

    def mark_evaluated(self, kind: EvaluationKind) -> None:
        self.progress = evaluated(self.progress, kind)
        self.save_progress()
        (self.paths.requests / kind.value).unlink(missing_ok=True)

    def runs(self, kind: EvaluationKind, at_start: bool) -> int:
        """Independent runs of the version: `baseline_runs` for version 0's baseline, else one."""
        target = target_config(self.config.evaluation, kind)
        baseline = at_start and target.at_start and last_evaluation(self.progress, kind) is None
        return target.baseline_runs if baseline else 1

    def close_phase(self, phase: int, kinds: list[EvaluationKind], evaluation_seconds: float) -> None:
        entries = self.store.phase_entries(phase)
        versions = read_versions(self.paths.models)
        progress = self.progress
        self.writer.write(
            PhaseTiming(
                sampling_seconds=progress.sampling_seconds,
                training_seconds=progress.training_seconds,
                publishing_seconds=progress.publishing_seconds,
                evaluation_seconds=evaluation_seconds,
                trees=len(entries),
                searches_paused=self.searches_running,
                pause=progress.pause,
            )
        )
        self.log(f"Phase {phase} pause: {pause_text(progress.pause)}")
        record = PhaseRecord(
            phase=phase,
            trees=len(entries),
            solved_trees=sum(entry.proved for entry in entries),
            sampling_seconds=progress.sampling_seconds,
            training_seconds=progress.training_seconds,
            publishing_seconds=progress.publishing_seconds,
            evaluation_seconds=evaluation_seconds,
            policy_version=versions[-1].version,
            value_accepted=value_published_by(versions, phase),
            evaluations=tuple(kinds),
            finished_at=now(),
            pause=progress.pause,
        )
        with self.paths.phases.open("a", encoding="utf-8") as handle:
            handle.write(to_json(record) + "\n")
        self.save_progress(
            phase=phase + 1,
            stage=PhaseStage.SAMPLING,
            sampling_seconds=0.0,
            training_seconds=0.0,
            publishing_seconds=0.0,
            pause=PauseSegments(),
        )
        self.collecting = phase + 1
        self.update_context()
