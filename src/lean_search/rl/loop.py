"""The search-tree GRPO loop: search curriculum statements, label the finished trees, pause, train, publish, resume.

`concurrency` workers search statements from the statement source with the published models; every finished tree is
written to the tree store under the phase collecting at that moment, with its summary (`tree_summary.py`: the groups
the policy would train on, budget and health signals). A phase starts once enough sampling produced enough trainable
groups and runs these stages, each recorded in loop_state.json so a restarted loop finishes the stage a
crash interrupted (searches cut off by the crash are lost and their statements fed again where the source allows):

pause       every policy and value request waits at the gate; searches keep their trees and REPL states in place
training    the paused searches' REPL processes stop to free host memory and the servers on the training GPUs sleep;
            the training job (grpo_phase.py, data-parallel over those GPUs) labels the phase's trees, trains the
            policy (GRPO) with the μ set for the run (`set_value_share`, 0 until set) and, every
            `value_every_phases`, the value model on the window of recent phases' trees, and merges the new adapters on
            the GPUs; meanwhile the loop labels the phase's trees for the search, curriculum and value metrics
publishing  version k + 1 (the new policy adapter and a new value adapter): with the persistent job's merges in host
            memory the sleeping servers wake with them (the others swap in place), the searches resume unless
            evaluations are due, and the version is recorded once the merges are on disk; otherwise it is recorded
            with the job's merges (or merged on the CPU) first, then served
evaluating  the fixed targets that are due (by loop hours, at the start, or requested) run as separate jobs while
            the searches stay paused, after the paused searches' REPL processes stopped to free host memory; the value
            servers serve the evaluations' fixed value model meanwhile. The probe runs one part of its set per slot;
            every other slot also runs its part with the published value model (the value arm), paired with the slot's
            run, which only reports (and alerts when the published model is worse than the reference); then the
            phase's budget signals and health checks (`health_checks.py`), whose hard stop ends the loop here
resume      the searches continue with the new weights; a newly served value model scores the value benchmark through
            the value servers meanwhile, a trend against v0 and the value model before it

The boundaries to the outside (the searches with Lean and vLLM, the training job, the vLLM servers, the evaluation
jobs) are protocols; `loop_services.py` holds the production implementations.
"""

import asyncio
import dataclasses
import datetime
import json
import shutil
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
from lean_search.expert_iteration.loop_config import ServingConfig
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
from lean_search.monitoring.families import (
    LoopState,
    LoopStatus,
    PauseSegments,
    PhaseTiming,
    ValueArmResult,
    ValueBenchmarkTrend,
    ValuePhase,
    ValueTraining,
)
from lean_search.monitoring.store import MetricsWriter
from lean_search.policy.adapters import handed_off_weights
from lean_search.policy.server_control import PhaseSeconds
from lean_search.rl.advantages import CreditMode
from lean_search.rl.budget_signals import budget_phase_record
from lean_search.rl.evaluation import EvaluationKind, EvaluationRun, EvaluationSummary, read_summary, value_arm_text
from lean_search.rl.fixed_targets import target_config
from lean_search.rl.health_checks import (
    append_health,
    health_stop_text,
    held_out_rates,
    last_good_version,
    measurements,
    phase_health,
    read_health_history,
    read_health_stop,
    write_health_stop,
)
from lean_search.rl.loop_config import EvaluationTarget, EvaluationValueModel, GrpoLoopConfig
from lean_search.rl.phase_metrics import search_phase_record
from lean_search.rl.retention import kept_adapters, prune_phase_adapters
from lean_search.rl.statement_sources import FedStatement, StatementSource
from lean_search.rl.training_phase import (
    PhaseOutcome,
    TrainerTimings,
    TrainingPhaseConfig,
    grpo_phase_record,
    label_phase_data,
    next_version,
    publish_phase,
)
from lean_search.rl.tree_store import TreeStore
from lean_search.rl.tree_summary import tree_summary
from lean_search.rl.value_trends import (
    VersionScores,
    benchmark_trend,
    earlier_scores,
    keep_scores,
    scores_path,
    trend_text,
)
from lean_search.search import CompletedSearch, tree_record
from lean_search.search.records import from_json_object, to_json
from lean_search.training.resident import HostDirectories
from lean_search.value.benchmark import BenchmarkScores, ValueBenchmark
from lean_search.value.bins import Readout
from lean_search.value.diagnostics import phase_value_metrics

IDLE_SECONDS = 30.0
GIB = 2**30
PHASE_OUTCOME_FILE = "phase.json"
DEFAULT_READOUT = Readout()


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
    # The last value adapter trained: the next value training continues it ("": the published one).
    value_adapter: str = ""
    # μ of the last phase that trained.
    value_share: float = 0.0
    # The pause of `phase` so far, segment by segment.
    pause: PauseSegments = field(default_factory=PauseSegments)
    # Sampling and training of all finished phases: the clock of the evaluation schedule.
    loop_seconds: float = 0.0
    # Loop seconds when each fixed target last ran; None: never.
    probe_at: float | None = None
    minif2f_at: float | None = None
    held_out_states_at: float | None = None
    # Probe slots run so far: the next slot's number (its part: slot % probe_parts).
    probe_slots: int = 0


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
    # The phase trained a value model, published with its version.
    value_published: bool
    evaluations: tuple[EvaluationKind, ...]
    finished_at: str
    pause: PauseSegments = field(default_factory=PauseSegments)
    value_share: float = 0.0


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
    async def prepare(self, request: TrainingRequest) -> None:
        """Sampling of the phase began: a trainer may read and label its trees as they arrive (CPU only)."""
        ...

    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        """Trains on the phase's trees; the outcome is also in output_directory/phase.json. A persistent trainer also
        leaves the new adapters merged in host memory (`adapters.handoff_directory`)."""
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
    async def evaluate(self, run: EvaluationRun, phase: int) -> EvaluationSummary:
        """The run with what the servers serve: the current version, and the evaluations' fixed value model or, for a
        value arm, the published one."""
        ...


class ValueScorer(Protocol):
    async def score(self, benchmark: ValueBenchmark) -> BenchmarkScores:
        """Fresh scores of every benchmark state by the value model the value servers serve now."""
        ...


@dataclass(frozen=True)
class ValueBenchmarkScoring:
    benchmark: ValueBenchmark
    scorer: ValueScorer


@dataclass(frozen=True)
class ValueShareSetting:
    value_share: float
    set_at: str


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
    def health(self) -> Path:
        """Each phase's health check (`PhaseHealth`), read back for the first phases' reference and the last good
        version."""
        return self.directory / "health.jsonl"

    @property
    def health_stop(self) -> Path:
        """Present after the health check's hard stop; the loop refuses to start until it is cleared."""
        return self.directory / "health_stop.json"

    @property
    def children(self) -> Path:
        """A record per running training or evaluation job, so a restarted loop never starts a second one."""
        return self.directory / "children"

    @property
    def value_share(self) -> Path:
        """μ for the phases to come, set by `grpo_loop.py set-value-share` and read when each phase trains."""
        return self.directory / "value_share.json"

    @property
    def value_benchmark(self) -> Path:
        """The value benchmark's fresh scores per value version."""
        return self.directory / "value_benchmark"

    @property
    def weights(self) -> Path:
        return self.checkpoints_root / self.name / "weights"

    def phase_run_name(self, phase: int) -> str:
        return f"{self.name}_phase_{phase:04d}"

    def phase_checkpoints(self, phase: int) -> Path:
        return self.checkpoints_root / self.phase_run_name(phase)

    def evaluation_directory(self, run: EvaluationRun, version: int) -> Path:
        slot = "" if run.slot is None else f"_slot{run.slot:04d}"
        arm = "_value_arm" if run.value_arm else ""
        repeat = f"_repeat{run.repeat}" if run.repeat else ""
        return self.evaluations / f"{run.kind}{slot}_v{version:04d}{arm}{repeat}"

    def probe_slot_directory(self, slot: int) -> Path | None:
        """The slot's run with the evaluations' value model (not a repeat or a value arm), whatever version ran it."""
        found = sorted(self.evaluations.glob(f"{EvaluationKind.PROBE}_slot{slot:04d}_v[0-9][0-9][0-9][0-9]"))
        return found[-1] if found else None


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
    value model does not train)."""
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


def evaluated(progress: LoopProgress, kind: EvaluationKind) -> LoopProgress:
    match kind:
        case EvaluationKind.PROBE:
            return dataclasses.replace(progress, probe_at=progress.loop_seconds)
        case EvaluationKind.MINIF2F:
            return dataclasses.replace(progress, minif2f_at=progress.loop_seconds)
        case EvaluationKind.HELD_OUT_STATES:
            return dataclasses.replace(progress, held_out_states_at=progress.loop_seconds)


def request_evaluation(paths: GrpoLoopPaths, kind: EvaluationKind) -> None:
    """The running loop evaluates `kind` at its next phase pause (a milestone)."""
    paths.requests.mkdir(parents=True, exist_ok=True)
    (paths.requests / kind.value).write_text(now(), encoding="utf-8")


def set_value_share(paths: GrpoLoopPaths, value_share: float) -> None:
    """μ for every phase from the next one to train on (the running loop reads it then); 0 turns it off."""
    if not 0 <= value_share <= 1:
        raise ValueError(f"μ must lie in [0, 1], not {value_share}.")
    paths.directory.mkdir(parents=True, exist_ok=True)
    write_json_atomically(paths.value_share, ValueShareSetting(value_share, now()))


def read_value_share(paths: GrpoLoopPaths) -> float:
    if not paths.value_share.exists():
        return 0.0
    return from_json_object(ValueShareSetting, json.loads(paths.value_share.read_text(encoding="utf-8"))).value_share


def with_trainer_timings(pause: PauseSegments, timings: TrainerTimings, job_seconds: float) -> PauseSegments:
    """The training job's parts; what its own clock did not see is the job's start (and exit), to which a persistent
    job's model building in this phase belongs."""
    return dataclasses.replace(
        pause,
        trainer_start_seconds=max(0.0, job_seconds - timings.total_seconds) + timings.build_seconds,
        preparation_seconds=timings.preparation_seconds,
        policy_load_seconds=timings.policy_load_seconds,
        compile_seconds=timings.compile_seconds,
        unpark_seconds=timings.unpark_seconds,
        park_seconds=timings.park_seconds,
        scoring_seconds=timings.scoring_seconds,
        policy_training_seconds=timings.policy_training_seconds,
        value_training_seconds=timings.value_training_seconds,
        merge_seconds=timings.merge_seconds,
        write_seconds=timings.write_seconds,
        handoff_seconds=timings.handoff_seconds,
    )


def handed_off_version(
    version: ModelVersion, current: ModelVersion, handoff_root: Path, serving: ServingConfig
) -> ModelVersion | None:
    """The version as the servers can load it from the merges the persistent job left in host memory (a model that
    did not change from the current version's weights); None when a new model's merge is not there."""
    policy = (
        Path(current.policy_weights)
        if version.policy_adapter == current.policy_adapter
        else handed_off_weights(handoff_root, serving.policy_base_model, version.policy_adapter)
    )
    value = (
        Path(current.value_weights)
        if version.value_adapter == current.value_adapter
        else handed_off_weights(handoff_root, serving.value_base_model, version.value_adapter)
    )
    if policy is None or value is None:
        return None
    return dataclasses.replace(version, policy_weights=str(policy), value_weights=str(value))


def pause_text(pause: PauseSegments) -> str:
    return ", ".join(
        f"{name.removesuffix('_seconds').replace('_', ' ')} {seconds:.0f} s"
        for name, seconds in dataclasses.asdict(pause).items()
    )


def published_time(version: ModelVersion) -> float:
    return datetime.datetime.fromisoformat(version.published_at).timestamp()


def unmeasured_host_memory() -> str:
    return "not measured"


def earlier_value_arm_results(paths: GrpoLoopPaths, own: Path) -> list[ValueArmResult]:
    """The comparisons of every other value arm, to pool with this one."""
    pattern = f"{EvaluationKind.PROBE}_slot*_value_arm/comparison.json"
    return [
        from_json_object(ValueArmResult, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(paths.evaluations.glob(pattern))
        if path.parent != own
    ]


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
        host_memory: Callable[[], str] = unmeasured_host_memory,
        value_readout: Readout = DEFAULT_READOUT,
        value_benchmark: ValueBenchmarkScoring | None = None,
    ) -> None:
        """`phase_template`: the text of the training phase config (config.training.phase_config); `host_memory`
        describes the node's memory for the log at the pause's stage boundaries; `value_readout`: A*'s readout of the
        value bins, for the value metrics; `value_benchmark`: scored by every newly served value model."""
        self.config = config
        self.value_readout = value_readout
        self.value_benchmark = value_benchmark
        # The value benchmark's scoring in flight, during sampling.
        self.scoring: asyncio.Task[None] | None = None
        self.host_memory = host_memory
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
        # The version the servers serve: ahead of models/current.json while handed-off weights are written to disk.
        self.served_version = 0
        # Merged weights the persistent training job left in host memory for the servers.
        self.handoff_root = HostDirectories(config.host_directory()).handoff
        # The loop's own labelling of the phase's trees for the search metrics, from the training on.
        self.search_metrics: asyncio.Task[None] | None = None
        self.phase_template = phase_template
        template = from_json_object(TrainingPhaseConfig, tomllib.loads(phase_template))
        # What the phase trigger counts trainable groups with.
        self.reward_config = template.reward
        self.credit = CreditMode.PER_TACTIC if template.policy is None else template.policy.data.credit
        self.stop: asyncio.Event | None = None
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
        groups = self.trainable_groups(self.progress.phase)
        if minutes >= training.max_sampling_minutes:
            return groups >= 1
        return minutes >= training.min_sampling_minutes and groups >= training.min_trainable_groups

    def trainable_groups(self, phase: int) -> int:
        return sum(entry.summary.trainable_groups for entry in self.store.phase_entries(phase))

    async def run(self, stop: asyncio.Event) -> None:
        self.stop = stop
        session = asyncio.create_task(self.stopping_on_failure(self.session(stop), stop))
        try:
            await stop.wait()
        finally:
            # Cancelling also stops a training or evaluation job in flight (`loop_services.run_logged`).
            session.cancel()
            if self.scoring is not None:
                self.scoring.cancel()
            await asyncio.gather(session, *([] if self.scoring is None else [self.scoring]), return_exceptions=True)
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
        health_stop = read_health_stop(self.paths.health_stop)
        if health_stop is not None:
            raise RuntimeError(health_stop_text(health_stop))
        await asyncio.to_thread(self.clear_stale_handoff)
        await self.servers.check()
        current = read_current(self.paths.models)
        await self.servers.serve(current)
        self.served_value_weights = current.value_weights
        self.served_version = current.version
        self.searcher.serving(current.version)
        if self.progress.stage != PhaseStage.SAMPLING:
            self.log(f"Finishing phase {self.progress.phase} from {self.progress.stage}")
            self.collecting = self.progress.phase + 1
            await self.finish_phase()
            if stop.is_set():
                return
        await self.run_evaluations(self.due_evaluations(at_start=True), self.progress.phase - 1, at_start=True)
        await self.prepare_training()
        self.schedule_benchmark_scoring()
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
                summary = await asyncio.to_thread(
                    tree_summary, record, self.reward_config, self.credit, self.config.sampling.max_expansions
                )
                async with self.store_lock:
                    await asyncio.to_thread(
                        self.store.add, record, self.collecting, self.served_version, fed.difficulty, summary
                    )
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
        await self.finish_benchmark_scoring()
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
            f"Phase {phase}: {len(entries)} trees ({sum(entry.proved for entry in entries)} solved, "
            f"{self.trainable_groups(phase)} trainable groups) after {sampling / 60:.1f} min of sampling; "
            f"{self.searches_running} searches paused"
        )
        self.save_progress(
            stage=PhaseStage.TRAINING, sampling_seconds=sampling, pause=PauseSegments(drain_seconds=drain_seconds)
        )
        await self.log_host_memory("at the pause")
        await self.finish_phase()
        assert self.stop is not None
        if not self.stop.is_set():
            await self.prepare_training()

    async def finish_phase(self) -> None:
        phase = self.progress.phase
        if self.progress.stage == PhaseStage.TRAINING:
            self.loop_state = LoopState.TRAINING
            self.write_status()
            started = self.clock()
            await self.release_lean_memory(self.config.training.paused_repl_memory_gib, "the training job")
            await self.servers.release()
            released = self.clock()
            await self.log_host_memory("before training")
            outcome = await self.train(phase)
            finished = self.clock()
            await self.log_host_memory("after training")
            pause = with_trainer_timings(self.progress.pause, outcome.timings, finished - released)
            progress = self.progress
            # The evaluation clock includes this phase from here on, so that the evaluations due are known before
            # the searches may resume early.
            self.save_progress(
                stage=PhaseStage.PUBLISHING,
                training_seconds=finished - started,
                pause=dataclasses.replace(pause, server_sleep_seconds=released - started),
                loop_seconds=progress.loop_seconds + progress.sampling_seconds + finished - started,
            )
        resumed_early = False
        if self.progress.stage == PhaseStage.PUBLISHING:
            self.loop_state = LoopState.PUBLISHING
            self.write_status()
            started = self.clock()
            durable = await self.publish(phase)
            publishing_seconds = self.clock() - started
            if durable is not None:
                if not self.due_evaluations(at_start=False):
                    self.resume_searches()
                    resumed_early = True
                    await self.log_host_memory("after the early resume, the handoff not yet on disk")
                await durable
            self.save_progress(stage=PhaseStage.EVALUATING, publishing_seconds=publishing_seconds)
            await self.log_host_memory("after publishing")
        started = self.clock()
        # Searches that resumed early leave a request made since then to the next pause.
        kinds = [] if resumed_early else self.due_evaluations(at_start=False)
        await self.run_evaluations(kinds, phase)
        evaluation_seconds = self.clock() - started
        if self.search_metrics is not None:
            await self.search_metrics
            self.search_metrics = None
        hard_stop = await asyncio.to_thread(self.check_health, phase, kinds)
        self.close_phase(phase, kinds, evaluation_seconds)
        if hard_stop:
            assert self.stop is not None
            self.stop.set()
            return
        self.resume_searches()
        # Only now: the version is recorded, so the scoring is of the value version the servers serve.
        self.schedule_benchmark_scoring()

    def resume_searches(self) -> None:
        if self.paused:
            self.searcher.resume()
            self.paused = False
            self.sampling_since = self.clock()
        self.loop_state = LoopState.SEARCHING
        self.write_status()

    def schedule_benchmark_scoring(self) -> None:
        """Scores the value benchmark through the value servers while the searches run, once per value version."""
        if self.value_benchmark is None or self.scoring is not None:
            return
        version = value_version(read_versions(self.paths.models))
        if not scores_path(self.paths.value_benchmark, version).exists():
            self.scoring = asyncio.create_task(self.score_value_benchmark(self.value_benchmark, version))

    async def finish_benchmark_scoring(self) -> None:
        """Waits for the scoring in flight before anything changes what the value servers serve."""
        if self.scoring is not None:
            scoring, self.scoring = self.scoring, None
            await scoring

    async def score_value_benchmark(self, scoring: ValueBenchmarkScoring, version: int) -> None:
        started = self.clock()
        try:
            scores = await scoring.scorer.score(scoring.benchmark)
        except httpx.HTTPError as error:
            self.log(
                f"Scoring the value benchmark with value v{version} failed ({type(error).__name__}: {error}); "
                "it is scored again after the next phase"
            )
            return
        trend = await asyncio.to_thread(
            self.benchmark_trend, scoring.benchmark, version, scores, self.clock() - started
        )
        self.writer.write(trend)
        self.log(trend_text(trend))

    def benchmark_trend(
        self, benchmark: ValueBenchmark, version: int, scores: BenchmarkScores, seconds: float
    ) -> ValueBenchmarkTrend:
        """Keeps the scores, then compares them with v0's and with those of the value version scored before."""
        directory = self.paths.value_benchmark
        keep_scores(directory, version, scores)
        reference = value_adapter_version(read_versions(self.paths.models), self.config.initial.value_adapter)
        reference_scores, previous_scores = earlier_scores(directory, version, reference)
        return benchmark_trend(
            benchmark,
            VersionScores(version, scores),
            reference_scores,
            previous_scores,
            self.value_readout,
            self.config.evaluation.value_benchmark,
            seconds,
        )

    async def release_lean_memory(self, threshold_gib: float, purpose: str) -> None:
        released = await self.searcher.release_lean_memory(int(threshold_gib * GIB))
        self.log(
            f"Stopped {released.stopped_processes} search REPL processes ({released.freed_bytes / GIB:.1f} GiB) "
            f"for {purpose}"
        )

    async def log_host_memory(self, moment: str) -> None:
        self.log(f"Host memory {moment}: {await asyncio.to_thread(self.host_memory)}")

    def check_health(self, phase: int, kinds: Sequence[EvaluationKind]) -> bool:
        """Writes the phase's budget and health lines and logs the alerts; True when the loop must stop (then
        health_stop.json names the last good version)."""
        health = self.config.health
        budget = budget_phase_record(self.store.entries, phase, health.late_solve_phases, health.max_late_solve_share)
        self.writer.write(budget)
        current = read_current(self.paths.models)
        outcome_path = self.paths.phase_checkpoints(phase) / PHASE_OUTCOME_FILE
        outcome = read_phase_outcome(outcome_path) if outcome_path.exists() else None
        held_out = None
        if EvaluationKind.HELD_OUT_STATES in kinds:
            held_out = held_out_rates(self.held_out_summary(current.version))
        version_zero_path = self.held_out_summary_path(0)
        version_zero = held_out_rates(read_summary(version_zero_path)) if version_zero_path.exists() else None
        measured = measurements(outcome, self.store.phase_entries(phase), held_out)
        history = read_health_history(self.paths.health)
        record = phase_health(phase, current.version, measured, history, version_zero, budget, health)
        append_health(self.paths.health, record)
        self.writer.write(record)
        for alert in record.alerts:
            self.log(f"Health of phase {phase} ({alert.severity}, {alert.check}): {alert.detail}")
        if not record.alerts:
            self.log(f"Health of phase {phase}: no alerts")
        if not record.hard_stop:
            return False
        self.log(health_stop_text(write_health_stop(self.paths.health_stop, record)))
        return True

    def held_out_summary_path(self, version: int) -> Path:
        return self.paths.evaluation_directory(EvaluationRun(EvaluationKind.HELD_OUT_STATES), version) / "summary.json"

    def held_out_summary(self, version: int) -> EvaluationSummary:
        return read_summary(self.held_out_summary_path(version))

    def value_window(self, phase: int) -> tuple[Path, ...]:
        """The tree directories the value model trains on when it is due this phase; none when it is not."""
        training = self.config.training
        if not (training.value_every_phases and phase % training.value_every_phases == 0):
            return ()
        first = max(1, phase - training.value_window_phases + 1)
        return tuple(self.store.phase_directory(number) for number in range(first, phase + 1))

    def training_request(self, phase: int, value_share: float) -> TrainingRequest:
        """The phase's training as the published version, μ and the value schedule define it. The version and the
        schedule change only between phases; μ (value_share.json) is read again when the phase starts training, and a
        persistent job that prepared the phase with another μ prepares it again."""
        current = read_current(self.paths.models)
        value_trees = self.value_window(phase)
        config_text = phase_config_text(
            self.phase_template,
            self.config.serving.policy_base_model,
            self.config.initial.policy_adapter,
            current,
            phase,
            value_share,
            (self.progress.value_adapter or current.value_adapter) if value_trees else None,
        )
        return TrainingRequest(
            phase,
            config_text,
            self.store.phase_directory(phase),
            self.paths.phase_run_name(phase),
            self.paths.phase_checkpoints(phase),
            bool(value_trees),
            value_trees,
        )

    async def prepare_training(self) -> None:
        """Sampling of the phase begins: the trainer may read and label its trees as they arrive."""
        phase = self.progress.phase
        await self.trainer.prepare(self.training_request(phase, read_value_share(self.paths)))

    async def train(self, phase: int) -> PhaseOutcome:
        value_share = read_value_share(self.paths)
        if value_share != self.progress.value_share:
            self.log(f"μ = {value_share} from phase {phase} on ({self.paths.value_share})")
            self.save_progress(value_share=value_share)
        request = self.training_request(phase, value_share)
        # Awaited only before the phase closes: the publish need not wait for the loop's own labelling.
        self.search_metrics = asyncio.create_task(
            asyncio.to_thread(self.write_search_metrics, phase, request.config_text)
        )
        outcome = await self.trainer.train(request)
        if outcome.value is not None:
            self.save_progress(value_adapter=outcome.value.adapter)
        self.log(
            f"Phase {phase} trained with μ = {value_share}: {outcome.trees} trees, {outcome.groups} groups"
            + ("" if outcome.value is None else f", a value model on {outcome.value.trees} trees")
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
        metrics = phase_value_metrics(labelled.trees, self.value_readout)
        self.writer.write(ValuePhase(config.reward.value_share, metrics))

    async def publish(self, phase: int) -> asyncio.Task[None] | None:
        """Serves version k + 1. When the persistent job left its merges in host memory the servers load those, and
        the returned task writes them to disk and only then records the version; otherwise the version is recorded
        first (the job's GPU merges moved into place, else merged on the CPU), then served. A restart after the
        servers loaded the merges but before the record finds them in host memory again, or merges on the CPU."""
        outcome = read_phase_outcome(self.paths.phase_checkpoints(phase) / PHASE_OUTCOME_FILE)
        current = read_current(self.paths.models)
        started = self.clock()
        handed_off = None
        if current.trigger != phase_trigger(phase):
            self.write_training_metrics(outcome, current.version + 1)
            candidate = next_version(current, outcome, phase_trigger(phase))
            handed_off = handed_off_version(candidate, current, self.handoff_root, self.config.serving)
            if handed_off is None:
                current = await asyncio.to_thread(
                    publish_phase, self.paths.models, self.publisher, outcome, phase_trigger(phase)
                )
        if handed_off is None:
            # Also after a restart that found the version recorded but host memory not yet cleared.
            await asyncio.to_thread(self.recorded)
        served_version = current if handed_off is None else handed_off
        published = self.clock()
        served = await self.servers.serve(served_version)
        self.save_progress(
            pause=dataclasses.replace(
                self.progress.pause,
                publish_seconds=published - started,
                wake_seconds=served.pause + served.weights,
                resume_seconds=served.resume,
            )
        )
        self.served_value_weights = served_version.value_weights
        self.served_version = served_version.version
        self.searcher.serving(served_version.version)
        value = "" if outcome.value is None else f" with the value model of phase {phase}"
        source = " from host memory" if handed_off else ""
        self.log(f"Published version {served_version.version}{value}{source}")
        return None if handed_off is None else asyncio.create_task(self.record_durably(phase, outcome))

    async def record_durably(self, phase: int, outcome: PhaseOutcome) -> None:
        """The handed-off merges copied to disk (a temporary directory renamed once complete), then the version
        recorded and older weights and adapters pruned, then host memory cleared."""
        started = self.clock()
        current = await asyncio.to_thread(
            publish_phase, self.paths.models, self.publisher, outcome, phase_trigger(phase)
        )
        await self.log_host_memory("after the durable write, before clearing the handoff")
        await asyncio.to_thread(self.recorded)
        self.served_value_weights = current.value_weights
        seconds = self.clock() - started
        self.save_progress(pause=dataclasses.replace(self.progress.pause, durable_write_seconds=seconds))
        self.log(f"Version {current.version} written to disk and recorded in {seconds:.0f} s")

    def recorded(self) -> None:
        """After a version's record: older adapters pruned, the merges handed off in host memory cleared."""
        self.prune_adapters()
        shutil.rmtree(self.handoff_root, ignore_errors=True)

    def clear_stale_handoff(self) -> None:
        """At the start: merges in host memory that this restart will not serve, i.e. all of them unless the
        interrupted phase's version awaits its record (then only partly written ones)."""
        if not self.handoff_root.exists():
            return
        awaiting = self.progress.stage == PhaseStage.PUBLISHING and read_current(
            self.paths.models
        ).trigger != phase_trigger(self.progress.phase)
        stale = [path for path in self.handoff_root.iterdir() if not awaiting or path.name.endswith(".tmp")]
        for path in stale:
            shutil.rmtree(path, ignore_errors=True)
        if stale:
            self.log(f"Cleared {len(stale)} stale merges from host memory ({self.handoff_root})")

    def prune_adapters(self) -> None:
        """Deletes the phase adapters of versions older than the retention that nothing uses any more."""
        retention = self.config.retention
        if not retention.adapter_versions:
            return
        versions = read_versions(self.paths.models)
        # The health check's rollback target stays, however old.
        good = versions[last_good_version(read_health_history(self.paths.health))]
        kept = kept_adapters(versions, retention.adapter_versions, [self.progress.value_adapter, good.policy_adapter])
        phases = (self.paths.phase_checkpoints(number) for number in range(1, self.progress.phase + 1))
        removed = prune_phase_adapters(phases, kept)
        if removed:
            self.log(f"Deleted {len(removed)} adapter directories of old phases: {[str(path) for path in removed]}")

    def write_training_metrics(self, outcome: PhaseOutcome, candidate_version: int) -> None:
        if outcome.policy is not None:
            self.writer.write(grpo_phase_record(outcome.policy, self.progress.sampling_seconds, candidate_version - 1))
        if outcome.value is not None:
            value = outcome.value
            self.writer.write(
                ValueTraining(
                    value_version=candidate_version,
                    trees=value.trees,
                    training_loss=value.result.final_pointwise_loss,
                    labels=value.labels,
                    replay_labels=value.replay_labels,
                )
            )

    def due_evaluations(self, at_start: bool) -> list[EvaluationKind]:
        due = []
        for kind in EvaluationKind:
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

    async def evaluate(self, run: EvaluationRun, phase: int) -> EvaluationSummary:
        value_model = EvaluationValueModel.PUBLISHED if run.value_arm else self.config.evaluation.value_model
        await self.serve_value_model(value_model)
        return await self.evaluations.evaluate(run, phase)

    def value_arm_due(self, slot: int) -> bool:
        """Every `every_slots`-th slot, while the published value model is not the evaluations' fixed reference."""
        evaluation = self.config.evaluation
        every = evaluation.value_arm.every_slots
        return (
            every > 0
            and slot % every == 0
            and evaluation.value_model == EvaluationValueModel.INITIAL
            and read_current(self.paths.models).value_adapter != self.config.initial.value_adapter
        )

    async def run_probe(self, phase: int, baseline: bool) -> None:
        """The next slot: its part of the probe set. Version 0's baseline runs every part not yet run, each
        `baseline_runs` times (independent runs: the run-to-run noise). A slot due a value arm then searches its part
        again with the published value model."""
        evaluation = self.config.evaluation
        runs = evaluation.probe.baseline_runs if baseline else 1
        first = self.progress.probe_slots
        last = evaluation.probe_parts - 1 if baseline else first
        solved_by_run = [0] * runs
        while self.progress.probe_slots <= last:
            slot = self.progress.probe_slots
            summaries = [
                await self.evaluate(EvaluationRun(EvaluationKind.PROBE, slot, repeat), phase) for repeat in range(runs)
            ]
            self.log_summaries(f"probe slot {slot} (part {slot % evaluation.probe_parts})", summaries)
            solved_by_run = [total + summary.solved for total, summary in zip(solved_by_run, summaries, strict=True)]
            if self.value_arm_due(slot):
                await self.run_value_arm(slot, phase)
            self.save_progress(probe_slots=slot + 1)
        if runs > 1 and self.progress.probe_slots > first:
            self.log(f"Probe baseline run to run over slots {first}-{last}: solved {solved_by_run}")

    async def run_value_arm(self, slot: int, phase: int) -> None:
        summary = await self.evaluate(EvaluationRun(EvaluationKind.PROBE, slot, value_arm=True), phase)
        result = summary.value_arm
        assert result is not None, "the value arm compares itself with the slot's run"
        self.log(value_arm_text(result))
        if result.worse:
            self.log(
                f"Alert: value v{result.published_value_version} is worse than v0 in its value arms "
                f"(p = {result.same_value_version.worse_p_value:.3f}); nothing changes on its own"
            )

    def log_summaries(self, name: str, summaries: list[EvaluationSummary]) -> None:
        for repeat, summary in enumerate(summaries):
            self.log(
                f"Evaluation {name} of version {summary.policy_version}"
                + (f" (repeat {repeat})" if repeat else "")
                + f": {summary.solved}/{summary.problems}, {summary.wall_clock_stops} stopped on the wall clock"
            )
        if len(summaries) > 1:
            solved = [summary.solved for summary in summaries]
            self.log(f"Evaluation {name} run to run: solved {solved}, difference {max(solved) - min(solved)}")

    async def run_evaluations(self, kinds: list[EvaluationKind], phase: int, at_start: bool = False) -> None:
        if not kinds:
            return
        await self.finish_benchmark_scoring()
        # Only between phases or before the workers start: the searches are paused or not running.
        self.loop_state = LoopState.EVALUATING
        self.write_status()
        await self.release_lean_memory(self.config.evaluation.paused_repl_memory_gib, "the evaluations")
        await self.log_host_memory("before the evaluations")
        for kind in kinds:
            baseline = self.baseline(kind, at_start)
            match kind:
                case EvaluationKind.PROBE:
                    await self.run_probe(phase, baseline)
                case EvaluationKind.MINIF2F | EvaluationKind.HELD_OUT_STATES:
                    runs = target_config(self.config.evaluation, kind).baseline_runs if baseline else 1
                    summaries = [
                        await self.evaluate(EvaluationRun(kind, repeat=repeat), phase) for repeat in range(runs)
                    ]
                    self.log_summaries(str(kind), summaries)
            self.mark_evaluated(kind)
        await self.serve_value_model(EvaluationValueModel.PUBLISHED)

    def mark_evaluated(self, kind: EvaluationKind) -> None:
        self.progress = evaluated(self.progress, kind)
        self.save_progress()
        (self.paths.requests / kind.value).unlink(missing_ok=True)

    def baseline(self, kind: EvaluationKind, at_start: bool) -> bool:
        """Version 0's baseline before the first phase: `baseline_runs` independent runs (of every probe part)."""
        target = target_config(self.config.evaluation, kind)
        return at_start and target.at_start and last_evaluation(self.progress, kind) is None

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
            value_published=value_published_by(versions, phase),
            evaluations=tuple(kinds),
            finished_at=now(),
            pause=progress.pause,
            value_share=progress.value_share,
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
