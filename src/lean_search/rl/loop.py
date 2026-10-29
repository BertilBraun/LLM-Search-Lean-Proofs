"""The search-tree GRPO loop: search curriculum statements, label the finished trees, pause, train, publish, resume.

`concurrency` workers search statements from the statement source with the published models; every finished tree is
written to the tree store under the phase collecting at that moment. A phase starts once enough sampling produced
enough solved trees and runs these stages, each recorded in loop_state.json so a restarted loop finishes the stage a
crash interrupted (searches cut off by the crash are lost and their statements fed again where the source allows):

pause       every policy and value request waits at the gate; searches keep their trees and REPL states in place
training    the servers on the training GPU sleep; the training job (grpo_phase.py) labels the phase's trees and
            trains the policy (GRPO) and, when due, the value model, gated on the held-out benchmark; meanwhile the
            loop labels the same trees for the search and curriculum metrics
publishing  version k + 1 (the new policy adapter, the new value adapter only if it passed the gate) is merged and
            recorded; every server swaps to it in place, the sleeping ones wake with it; μ turns on with the first
            value model that passed the gate
evaluating  the fixed targets that are due (by loop hours, at the start, or requested) run as separate jobs while
            the searches stay paused
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
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
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
    write_json_atomically,
)
from lean_search.expert_iteration.toml_text import toml_text
from lean_search.monitoring.families import LoopState, LoopStatus, PhaseTiming, ValueBenchmarkResult
from lean_search.monitoring.store import MetricsWriter
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary
from lean_search.rl.loop_config import EvaluationTarget, GrpoLoopConfig
from lean_search.rl.phase_metrics import search_phase_record
from lean_search.rl.statement_sources import StatementSource
from lean_search.rl.training_phase import (
    PhaseOutcome,
    TrainingPhaseConfig,
    grpo_phase_record,
    label_phase_data,
    publish_phase,
)
from lean_search.rl.tree_store import TreeStore
from lean_search.search import CompletedSearch, tree_record
from lean_search.search.records import from_json_object, to_json

IDLE_SECONDS = 30.0
FAILURE_PAUSE_SECONDS = 5.0
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
    # Sampling and training of all finished phases: the clock of the evaluation schedule.
    loop_seconds: float = 0.0
    # Loop seconds when each fixed target last ran; None: never.
    probe_at: float | None = None
    minif2f_at: float | None = None
    held_out_states_at: float | None = None


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


@dataclass(frozen=True)
class TrainingRequest:
    phase: int
    config_text: str
    trees: Path
    run_name: str
    output_directory: Path
    train_value: bool


class TreeSearcher(Protocol):
    async def search(self, problem: Problem) -> CompletedSearch: ...

    async def pause(self) -> None:
        """Returns once no request is in flight; later requests wait until resume."""
        ...

    def resume(self) -> None: ...


class PhaseTrainer(Protocol):
    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        """Trains on the phase's trees; the outcome is also in output_directory/phase.json."""
        ...


class ModelServers(Protocol):
    async def check(self) -> None:
        """Raises when a server does not answer."""
        ...

    async def release(self) -> None:
        """Frees the training GPU: its servers sleep."""
        ...

    async def serve(self, version: ModelVersion) -> None:
        """Every server serves the version: sleeping ones wake with it, running ones swap in place."""
        ...


class Evaluations(Protocol):
    async def evaluate(self, kind: EvaluationKind, phase: int) -> EvaluationSummary: ...


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
    def weights(self) -> Path:
        return self.checkpoints_root / self.name / "weights"

    def phase_run_name(self, phase: int) -> str:
        return f"{self.name}_phase_{phase:04d}"

    def phase_checkpoints(self, phase: int) -> Path:
        return self.checkpoints_root / self.phase_run_name(phase)

    def evaluation_directory(self, kind: EvaluationKind, version: int) -> Path:
        return self.evaluations / f"{kind}_v{version:04d}"


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


def value_version(versions: list[ModelVersion]) -> int:
    """The version that first published the current value adapter."""
    current = versions[-1].value_adapter
    return next(version.version for version in versions if version.value_adapter == current)


def value_published_by(versions: list[ModelVersion], phase: int) -> bool:
    published = [index for index, version in enumerate(versions) if version.trigger == phase_trigger(phase)]
    return bool(published) and versions[published[0]].value_adapter != versions[published[0] - 1].value_adapter


def phase_config_text(template: str, current: ModelVersion, phase: int, value_share: float, train_value: bool) -> str:
    """The template with the published adapters to continue from, μ and a per-phase shuffle; no value part unless due."""
    table = tomllib.loads(template)
    for section in ("reward", "value_targets"):
        table.setdefault(section, {})["value_share"] = value_share
    policy = table["policy"]
    policy["initial_adapter"] = current.policy_adapter
    policy.setdefault("optimization", {})["seed"] = phase
    if train_value:
        if current.value_adapter:
            table["value"]["initial_adapter"] = current.value_adapter
    else:
        table.pop("value", None)
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


def evaluated(progress: LoopProgress, kind: EvaluationKind) -> LoopProgress:
    match kind:
        case EvaluationKind.PROBE:
            return dataclasses.replace(progress, probe_at=progress.loop_seconds)
        case EvaluationKind.MINIF2F:
            return dataclasses.replace(progress, minif2f_at=progress.loop_seconds)
        case EvaluationKind.HELD_OUT_STATES:
            return dataclasses.replace(progress, held_out_states_at=progress.loop_seconds)


def evaluation_target(config: GrpoLoopConfig, kind: EvaluationKind) -> EvaluationTarget:
    match kind:
        case EvaluationKind.PROBE:
            return config.evaluation.probe
        case EvaluationKind.MINIF2F:
            return config.evaluation.minif2f
        case EvaluationKind.HELD_OUT_STATES:
            return config.evaluation.held_out_states


def request_evaluation(paths: GrpoLoopPaths, kind: EvaluationKind) -> None:
    """The running loop evaluates `kind` at its next phase pause (a milestone)."""
    paths.requests.mkdir(parents=True, exist_ok=True)
    (paths.requests / kind.value).write_text(now(), encoding="utf-8")


def published_time(version: ModelVersion) -> float:
    return datetime.datetime.fromisoformat(version.published_at).timestamp()


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
        self.failure: BaseException | None = None
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
        await self.servers.check()
        await self.servers.serve(read_current(self.paths.models))
        if self.progress.stage != PhaseStage.SAMPLING:
            self.log(f"Finishing phase {self.progress.phase} from {self.progress.stage}")
            self.collecting = self.progress.phase + 1
            await self.finish_phase()
        await self.run_evaluations(self.due_evaluations(at_start=True), self.progress.phase - 1)
        self.sampling_since = self.clock()
        coroutines: list[Coroutine[None, None, None]] = [
            self.work(stop) for _ in range(self.config.sampling.concurrency)
        ]
        coroutines += [self.watch(stop), self.report_status(stop)]
        tasks = [asyncio.create_task(self.stopping_on_failure(coroutine, stop)) for coroutine in coroutines]
        try:
            await stop.wait()
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.progress.stage == PhaseStage.SAMPLING:
                self.save_progress(sampling_seconds=self.sampling_seconds())
            self.loop_state = LoopState.STOPPED
            self.write_status()
            self.log(f"Stopped after {self.session_trees:,} trees and {self.session_proofs:,} proofs this session")
        if self.failure is not None:
            raise RuntimeError("The loop stopped on a failure; a restart resumes it") from self.failure

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
                self.statements.abandon(fed.name)
                self.log(f"{fed.name}: {type(error).__name__}: {error}; abandoned")
                await asyncio.sleep(FAILURE_PAUSE_SECONDS)
                continue
            except BaseException:
                self.statements.abandon(fed.name)
                raise
            finally:
                self.searches_running -= 1
            result = completed.result
            if completed.tree is not None:
                record = tree_record(completed.tree, fed.statement.formal_statement, result)
                version = read_current(self.paths.models).version
                async with self.store_lock:
                    await asyncio.to_thread(self.store.add, record, self.collecting, version, fed.difficulty)
            self.statements.record_outcome(fed.name, result.proved)
            self.session_trees += 1
            self.session_proofs += result.accounting.proofs

    async def watch(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(self.config.training.check_seconds)
            for message in self.statements.refresh():
                self.log(message)
            if self.phase_due():
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
            )
        )

    async def run_phase(self) -> None:
        phase = self.progress.phase
        sampling = self.sampling_seconds()
        self.collecting = phase + 1
        self.sampling_since = None
        self.loop_state = LoopState.PAUSED
        self.write_status()
        await self.searcher.pause()
        self.paused = True
        entries = self.store.phase_entries(phase)
        self.log(
            f"Phase {phase}: {len(entries)} trees ({sum(entry.proved for entry in entries)} solved) after "
            f"{sampling / 60:.1f} min of sampling; {self.searches_running} searches paused"
        )
        self.save_progress(stage=PhaseStage.TRAINING, sampling_seconds=sampling)
        await self.finish_phase()

    async def finish_phase(self) -> None:
        phase = self.progress.phase
        if self.progress.stage == PhaseStage.TRAINING:
            self.loop_state = LoopState.TRAINING
            self.write_status()
            started = self.clock()
            await self.servers.release()
            await self.train(phase)
            self.save_progress(stage=PhaseStage.PUBLISHING, training_seconds=self.clock() - started)
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

    async def train(self, phase: int) -> None:
        current = read_current(self.paths.models)
        training = self.config.training
        train_value = bool(
            training.value_benchmark and training.value_every_phases and phase % training.value_every_phases == 0
        )
        value_share = training.value_share_after_gate if self.progress.value_gate_passed else 0.0
        config_text = phase_config_text(self.phase_template, current, phase, value_share, train_value)
        request = TrainingRequest(
            phase,
            config_text,
            self.store.phase_directory(phase),
            self.paths.phase_run_name(phase),
            self.paths.phase_checkpoints(phase),
            train_value,
        )
        labelling = asyncio.create_task(asyncio.to_thread(self.write_search_metrics, phase, config_text))
        outcome = await self.trainer.train(request)
        await labelling
        self.log(
            f"Phase {phase} trained: {outcome.trees} trees, {outcome.groups} groups"
            + ("" if outcome.value is None else f", value {'accepted' if outcome.value.accepted else 'rejected'}")
        )

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
        if current.trigger != phase_trigger(phase):
            self.write_training_metrics(outcome, current.version + 1)
            current = await asyncio.to_thread(
                publish_phase, self.paths.models, self.publisher, outcome, phase_trigger(phase)
            )
        await self.servers.serve(current)
        if outcome.value is not None and outcome.value.accepted and not self.progress.value_gate_passed:
            self.log(f"Value model of phase {phase} passed the gate: μ = {self.config.training.value_share_after_gate}")
            self.save_progress(value_gate_passed=True)
        self.log(f"Published version {current.version}")

    def write_training_metrics(self, outcome: PhaseOutcome, candidate_version: int) -> None:
        if outcome.policy is not None:
            self.writer.write(grpo_phase_record(outcome.policy, self.progress.sampling_seconds))
        if outcome.value is not None and outcome.value.gate is not None:
            self.writer.write(
                ValueBenchmarkResult(
                    candidate_version=candidate_version,
                    gate_passed=outcome.value.accepted,
                    benchmark=outcome.value.gate.new,
                    training_loss=outcome.value.result.final_pointwise_loss,
                )
            )

    def due_evaluations(self, at_start: bool) -> list[EvaluationKind]:
        due = []
        for kind in EvaluationKind:
            requested = (self.paths.requests / kind.value).exists()
            target = evaluation_target(self.config, kind)
            last = last_evaluation(self.progress, kind)
            if requested or evaluation_due(target, last, self.progress.loop_seconds, at_start):
                due.append(kind)
        return due

    async def run_evaluations(self, kinds: list[EvaluationKind], phase: int) -> None:
        if not kinds:
            return
        self.loop_state = LoopState.EVALUATING
        self.write_status()
        if not self.paused and self.sampling_since is not None:
            await self.searcher.pause()
            self.paused = True
        for kind in kinds:
            summary = await self.evaluations.evaluate(kind, phase)
            self.log(f"Evaluation {kind} of version {summary.policy_version}: {summary.solved}/{summary.problems}")
            self.progress = evaluated(self.progress, kind)
            self.save_progress()
            (self.paths.requests / kind.value).unlink(missing_ok=True)

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
            )
        )
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
        )
        with self.paths.phases.open("a", encoding="utf-8") as handle:
            handle.write(to_json(record) + "\n")
        self.save_progress(
            phase=phase + 1,
            stage=PhaseStage.SAMPLING,
            sampling_seconds=0.0,
            training_seconds=0.0,
            publishing_seconds=0.0,
        )
        self.collecting = phase + 1
        self.update_context()
