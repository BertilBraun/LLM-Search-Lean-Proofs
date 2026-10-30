"""The GRPO loop's production boundaries: Lean searches with the served models, the training job, the vLLM servers,
the evaluation jobs, the value benchmark's scoring through the value servers, the servers' start commands and the
first-hour check of a policy server's responses."""

import asyncio
import contextlib
import json
import os
import shlex
import shutil
import signal
import statistics
import sys
import time
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.data import Problem
from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig
from lean_search.expert_iteration.loop_search import PauseGate
from lean_search.expert_iteration.serving import MergedPublisher, ModelVersion, write_json_atomically
from lean_search.lean import FORBIDDEN_TOKENS, LeanReplConfig, LeanReplPool
from lean_search.monitoring.system_sampler import (
    CGROUP,
    LEAN_PROCESS_NAMES,
    PROC,
    GpuReader,
    host_memory,
    percentile_90,
)
from lean_search.policy.client import PolicyClient
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import load_tokenizer
from lean_search.policy.prompts import parse_samples, render_prompt, stop_sequences
from lean_search.policy.server_control import (
    PhaseSeconds,
    is_healthy,
    is_sleeping,
    release_gpu,
    restore_gpu,
)
from lean_search.rl.evaluation import (
    EvaluationKind,
    EvaluationPaths,
    EvaluationRun,
    EvaluationSummary,
    read_search_progress,
    read_summary,
)
from lean_search.rl.fixed_targets import baseline_concurrency, baseline_jobs, target_config
from lean_search.rl.host_memory import HostMemoryTerms, budget_conditions, budget_text
from lean_search.rl.loop import (
    GIB,
    PHASE_OUTCOME_FILE,
    GrpoLoopPaths,
    ReleasedLeanMemory,
    TrainingRequest,
    read_phase_outcome,
)
from lean_search.rl.loop_config import GrpoLoopConfig, LoopTrainingConfig
from lean_search.rl.renaming import StatementRenamings, search_problem
from lean_search.rl.search_models import SearchModels, open_search_models
from lean_search.rl.trainer_channel import TrainerChannel, TrainerCommand, TrainerCommandKind
from lean_search.rl.training_phase import PhaseOutcome
from lean_search.search import CompletedSearch, RunConfig
from lean_search.search.records import from_json_object
from lean_search.training.resident import HostDirectories
from lean_search.value.benchmark import BenchmarkScores, ValueBenchmark
from lean_search.value.benchmark_scoring import score_benchmark
from lean_search.value.config import ValueConfig
from lean_search.value.estimator import open_value_estimator

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[3]
# The GRPO trainer compares the sampler's log-probabilities with its own at the sampling temperature.
POLICY_SERVER_ARGUMENTS = "--logprobs-mode processed_logprobs"
CHECK_GOALS = ("x : ℝ\nh₀ : 3 * x + 2 = 11\n⊢ x = 3",)
# A stopped job's process group gets SIGTERM, then SIGKILL after this long.
CHILD_STOP_SECONDS = 30.0
JOB_MARKER_VARIABLE = "LEAN_SEARCH_LOOP_JOB"
# The job records under children/: the per-phase training job's, the persistent trainer's and the evaluations'.
EVERY_RECORD = "**/*.pid"


class LeanTreeSearcher:
    """One search per REPL of the pool, with the served models behind the pause gate."""

    def __init__(
        self,
        config: RunConfig,
        pool: LeanReplPool,
        models: SearchModels,
        gate: PauseGate,
        renamings: StatementRenamings | None,
    ) -> None:
        self.config = config
        self.pool = pool
        self.models = models
        self.gate = gate
        self.renamings = renamings

    async def search(self, problem: Problem) -> CompletedSearch:
        async with self.pool.acquire() as repl:
            return await search_problem(
                problem,
                repl,
                self.models.expander,
                self.models.priority_function,
                self.config.search,
                self.renamings,
            )

    async def pause(self) -> None:
        await self.gate.pause()

    def resume(self) -> None:
        self.gate.resume()

    def serving(self, policy_version: int) -> None:
        self.gate.policy_version = policy_version

    async def release_lean_memory(self, above_bytes: int) -> ReleasedLeanMemory:
        stopped = await self.pool.stop_processes(above_bytes)
        return ReleasedLeanMemory(len(stopped), sum(usage.anonymous_bytes for usage in stopped))

    async def stop_idle_repls(self, keep_running: int) -> ReleasedLeanMemory:
        stopped = await self.pool.stop_idle_processes(keep_running)
        return ReleasedLeanMemory(len(stopped), sum(usage.anonymous_bytes for usage in stopped))


@contextlib.asynccontextmanager
async def open_tree_searcher(
    config: RunConfig, headers: Sequence[str], renamings: StatementRenamings | None
) -> AsyncIterator[LeanTreeSearcher]:
    """A REPL for each concurrent search (`config.lean.pool_size`), the headers imported up front."""
    gate = PauseGate()
    async with (
        open_search_models(config, gate) as models,
        LeanReplPool(config.lean.pool_size, LeanReplConfig(), config.lean.restart_fraction) as pool,
    ):
        await pool.start(headers)
        yield LeanTreeSearcher(config, pool, models, gate, renamings)


@dataclass(frozen=True)
class ChildProcess:
    process_id: int
    # Clock ticks after boot when the process started, so a reused process id is not taken for the child.
    start_ticks: int
    command: str
    # JOB_MARKER_VARIABLE's value in the environment of every process of the job, which finds the processes that left
    # its group (torchrun starts each worker in a session of its own).
    marker: str = ""


@dataclass(frozen=True)
class LiveJob:
    record: ChildProcess
    # The running processes with the job's marker: the one the loop started and everything it started.
    process_ids: tuple[int, ...]


def running_start_ticks(process_id: int) -> int | None:
    """The process's start time, or None once it ended (zombies included)."""
    try:
        text = Path(f"/proc/{process_id}/stat").read_text()
    except FileNotFoundError:
        return None
    fields = text[text.rindex(")") + 2 :].split()
    return None if fields[0] == "Z" else int(fields[19])


def marked_processes(marker: str) -> list[int]:
    """The running processes with this job marker in their environment."""
    entry = f"{JOB_MARKER_VARIABLE}={marker}".encode()
    process_ids = []
    for path in Path("/proc").glob("[0-9]*/environ"):
        try:
            environment = path.read_bytes()
        except OSError:
            continue
        if entry in environment.split(b"\0"):
            process_ids.append(int(path.parent.name))
    return process_ids


def live_children(directory: Path, pattern: str = "*.pid") -> list[LiveJob]:
    """Recorded jobs that still run: the process the loop started, or any process carrying the job's marker."""
    children = [from_json_object(ChildProcess, json.loads(path.read_text())) for path in directory.glob(pattern)]
    jobs = [LiveJob(child, tuple(marked_processes(child.marker))) for child in children]
    return [
        job for job in jobs if job.process_ids or running_start_ticks(job.record.process_id) == job.record.start_ticks
    ]


def signal_group(process_id: int, signal_number: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process_id, signal_number)


def signal_processes(process_ids: Sequence[int], signal_number: signal.Signals) -> None:
    for process_id in process_ids:
        with contextlib.suppress(ProcessLookupError):
            os.kill(process_id, signal_number)


async def stop_job(process: asyncio.subprocess.Process, marker: str) -> None:
    """SIGTERM to the job's group and every process with its marker; SIGKILL to what is left after the timeout."""
    deadline = time.monotonic() + CHILD_STOP_SECONDS
    signal_group(process.pid, signal.SIGTERM)
    signal_processes(marked_processes(marker), signal.SIGTERM)
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(process.wait(), CHILD_STOP_SECONDS)
    while marked_processes(marker) and time.monotonic() < deadline:
        await asyncio.sleep(0.1)
    # Its own children (Lean REPLs, data loader workers, torchrun's workers) may outlive it.
    signal_group(process.pid, signal.SIGKILL)
    signal_processes(marked_processes(marker), signal.SIGKILL)
    await process.wait()


def earlier_jobs_text(running: Sequence[LiveJob]) -> str:
    return (
        f"Jobs of an earlier loop still run: {running}; stop them (kill -TERM each of process_ids, torchrun's workers "
        "included) before restarting."
    )


async def run_logged(arguments: Sequence[str], log_path: Path, environment: dict[str, str], record_path: Path) -> None:
    """The job in its own process group, recorded in `record_path` until it and every process carrying its marker
    ended; cancelling, or its own end, stops whatever of the job is left."""
    # A job recorded beside it still running means an earlier loop died without stopping it.
    running = live_children(record_path.parent)
    if running:
        raise RuntimeError(earlier_jobs_text(running))
    log_path.parent.mkdir(parents=True, exist_ok=True)
    marker = f"{record_path.stem}-{uuid.uuid4().hex}"
    with log_path.open("ab") as log_file:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=REPOSITORY_DIRECTORY,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            env=environment | {JOB_MARKER_VARIABLE: marker},
            start_new_session=True,
        )
        try:
            start_ticks = running_start_ticks(process.pid)
            if start_ticks is not None:
                child = ChildProcess(process.pid, start_ticks, shlex.join(arguments), marker)
                write_json_atomically(record_path, child)
            return_code = await process.wait()
        finally:
            # After a SIGKILLed torchrun its workers live on outside its group.
            await stop_job(process, marker)
            if process.returncode is not None:
                record_path.unlink(missing_ok=True)
    if return_code:
        raise RuntimeError(f"{shlex.join(arguments)} failed; see {log_path}")


def training_launcher(config: LoopTrainingConfig) -> list[str]:
    """The command prefix, then one process, or torchrun with a rank per training GPU."""
    launcher = [sys.executable]
    if len(config.gpus) > 1:
        launcher += ["-m", "torch.distributed.run", "--standalone", f"--nproc-per-node={len(config.gpus)}"]
    return [*shlex.split(config.command_prefix), *launcher]


def replay_arguments(paths: GrpoLoopPaths, config: LoopTrainingConfig) -> list[str]:
    arguments = []
    for option, relative in (
        ("--lean-replay", config.lean_replay),
        ("--math-replay", config.math_replay),
        ("--value-replay", config.value_replay),
    ):
        if relative:
            arguments += [option, str(paths.data_root / relative)]
    return arguments


def training_environment(paths: GrpoLoopPaths, config: LoopTrainingConfig) -> dict[str, str]:
    return os.environ | {
        "CUDA_VISIBLE_DEVICES": ",".join(str(gpu) for gpu in config.gpus),
        "LEAN_SEARCH_CHECKPOINTS": str(paths.checkpoints_root),
        "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
    }


def write_phase_config(paths: GrpoLoopPaths, request: TrainingRequest) -> Path:
    """Written to a temporary file and renamed: a persistent job's rank may be reading the earlier text."""
    config_path = paths.training / f"phase_{request.phase:04d}.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = config_path.with_name(config_path.name + ".tmp")
    temporary.write_text(request.config_text, encoding="utf-8")
    os.replace(temporary, config_path)
    return config_path


class SubprocessTrainer:
    """experiments/grpo_phase.py on the training GPUs, one job per phase: one process, or a torchrun rank per GPU."""

    def __init__(self, paths: GrpoLoopPaths, config: LoopTrainingConfig) -> None:
        self.paths = paths
        self.config = config

    def earlier_jobs(self) -> str | None:
        running = live_children(self.paths.children, EVERY_RECORD)
        return earlier_jobs_text(running) if running else None

    def arguments(self, request: TrainingRequest, config_path: Path) -> list[str]:
        arguments = [
            *training_launcher(self.config),
            "experiments/grpo_phase.py",
            "--config",
            str(config_path),
            "--trees",
            str(request.trees),
            "--run-name",
            request.run_name,
            "--merge-adapters",
            *replay_arguments(self.paths, self.config),
        ]
        if request.train_value:
            arguments += ["--value-trees", *(str(directory) for directory in request.value_trees)]
        return arguments

    async def prepare(self, request: TrainingRequest) -> None:
        """The phase's job reads and labels its trees when it starts."""

    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        config_path = write_phase_config(self.paths, request)
        log_path = self.paths.training / f"phase_{request.phase:04d}.log"
        arguments = self.arguments(request, config_path)
        environment = training_environment(self.paths, self.config)
        await run_logged(arguments, log_path, environment, self.paths.children / "training.pid")
        return read_phase_outcome(request.output_directory / PHASE_OUTCOME_FILE)


class TrainerDiedError(RuntimeError):
    pass


class PersistentTrainer:
    """experiments/grpo_trainer.py: one training job for the whole loop, a rank per training GPU, that keeps its
    models between phases and takes the loop's commands through files (`trainer_channel.py`).

    It starts with the first `prepare` (at the start of sampling, so that its start and model building overlap the
    searches) or `train`; its record lies in children/persistent/, apart from the evaluation jobs', which start while
    it runs. A job that dies is started again at the next command; one that dies during a `train` is started again and
    trains the phase once more, and a second death fails the phase as a failed per-phase job would. Leaving the
    context sends `stop`, stops whatever is left and removes the parked weights from host memory; the job also stops
    by itself, between commands, once the loop's process is gone.
    """

    def __init__(
        self,
        paths: GrpoLoopPaths,
        config: LoopTrainingConfig,
        arguments: Sequence[str],
        environment: dict[str, str],
        host: HostDirectories,
        log: Callable[[str], None],
        poll_seconds: float = 0.5,
        stop_seconds: float = 60.0,
    ) -> None:
        self.paths = paths
        self.config = config
        self.arguments = list(arguments)
        self.environment = environment
        self.host = host
        self.log = log
        self.poll_seconds = poll_seconds
        self.stop_seconds = stop_seconds
        self.channel = TrainerChannel(paths.training / "trainer")
        self.record_path = paths.children / "persistent" / "training.pid"
        self.job: asyncio.Task[None] | None = None
        self.sequence = 0
        self.starts = 0
        # Seconds of the `train`s answered so far, of value phases (True) and the others.
        self.train_seconds: dict[bool, list[float]] = {False: [], True: []}
        # The running job answered a `train`: its models are built and its layers compiled.
        self.trained_in_job = False

    def earlier_jobs(self) -> str | None:
        running = live_children(self.paths.children, EVERY_RECORD)
        return earlier_jobs_text(running) if running else None

    def running(self) -> bool:
        return self.job is not None and not self.job.done()

    def start(self) -> None:
        self.channel.clear()
        self.sequence = 0
        self.starts += 1
        self.trained_in_job = False
        log_path = self.paths.training / "trainer.log"
        self.job = asyncio.create_task(run_logged(self.arguments, log_path, self.environment, self.record_path))
        self.job.add_done_callback(self.job_ended)
        self.log(f"Persistent trainer started (start {self.starts}; log {log_path})")

    def job_ended(self, job: asyncio.Task[None]) -> None:
        if job.cancelled():
            return
        error = job.exception()
        self.log(f"Persistent trainer ended: {error or 'stopped'}")

    def ensure_running(self) -> None:
        if not self.running():
            if self.starts:
                self.log("Persistent trainer not running; starting it again")
            self.start()

    async def wait_for(self, condition: Callable[[], bool], what: str, deadline: float) -> None:
        """Polls until `condition` holds; raises TrainerDiedError when the job ends first, or stops the job and raises
        it once the monotonic clock passes `deadline` (a hung job: the collectives' own timeout is an hour)."""
        assert self.job is not None
        while not condition():
            done, _ = await asyncio.wait({self.job}, timeout=self.poll_seconds)
            if done and not condition():
                raise TrainerDiedError(
                    f"the persistent trainer ended while {what}; see {self.paths.training}/trainer.log"
                )
            if time.monotonic() > deadline and not condition():
                await self.stop_job()
                raise TrainerDiedError(
                    f"the persistent trainer did not answer in time while {what}, so it was stopped; see "
                    f"{self.paths.training}/trainer.log"
                )

    def train_timeout_seconds(self, request: TrainingRequest) -> float:
        """A job's first phase (model building, compilation) gets `first_train_timeout_minutes`; later ones
        `train_timeout_factor` times the median of the earlier phases of the same kind, at least
        `train_timeout_minimum_minutes`."""
        config = self.config
        earlier = self.train_seconds[request.train_value]
        if not self.trained_in_job or not earlier:
            return config.first_train_timeout_minutes * 60
        return max(config.train_timeout_minimum_minutes * 60, config.train_timeout_factor * statistics.median(earlier))

    def send(self, kind: TrainerCommandKind, request: TrainingRequest | None = None) -> int:
        self.sequence += 1
        if request is None:
            self.channel.send(TrainerCommand(self.sequence, kind))
            return self.sequence
        command = TrainerCommand(
            self.sequence,
            kind,
            phase=request.phase,
            config=str(write_phase_config(self.paths, request)),
            trees=str(request.trees),
            value_trees=tuple(str(directory) for directory in request.value_trees),
            output_directory=str(request.output_directory),
        )
        self.channel.send(command)
        return self.sequence

    async def prepare(self, request: TrainingRequest) -> None:
        self.ensure_running()
        self.send(TrainerCommandKind.PREPARE, request)

    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        try:
            try:
                return await self.train_once(request)
            except TrainerDiedError as died:
                self.log(f"Phase {request.phase}: {died}; starting it again to train the phase once more")
            try:
                return await self.train_once(request)
            except TrainerDiedError as again:
                raise RuntimeError(f"Phase {request.phase} failed twice: {again}") from again
        except asyncio.CancelledError:
            # A job cut off mid-phase holds the GPUs; the phase reruns after a restart.
            await self.stop_job()
            raise

    async def train_once(self, request: TrainingRequest) -> PhaseOutcome:
        self.ensure_running()
        timeout = self.train_timeout_seconds(request)
        started = time.monotonic()
        deadline = started + timeout
        await self.wait_for(lambda: self.channel.ready() is not None, "starting", deadline)
        sequence = self.send(TrainerCommandKind.TRAIN, request)
        what = f"training phase {request.phase} (timeout {timeout / 60:.0f} min)"
        await self.wait_for(lambda: self.channel.reply_to(sequence) is not None, what, deadline)
        self.train_seconds[request.train_value].append(time.monotonic() - started)
        self.trained_in_job = True
        return read_phase_outcome(request.output_directory / PHASE_OUTCOME_FILE)

    async def stop_job(self) -> None:
        if self.job is not None:
            self.job.cancel()
            await asyncio.gather(self.job, return_exceptions=True)

    async def close(self) -> None:
        if self.running():
            self.send(TrainerCommandKind.STOP)
            assert self.job is not None
            await asyncio.wait({self.job}, timeout=self.stop_seconds)
        await self.stop_job()
        await asyncio.to_thread(shutil.rmtree, self.host.parked, True)


def persistent_trainer_arguments(paths: GrpoLoopPaths, config: GrpoLoopConfig) -> list[str]:
    training = config.training
    arguments = [
        *training_launcher(training),
        "experiments/grpo_trainer.py",
        "--channel",
        str(paths.training / "trainer"),
        "--host-directory",
        str(config.host_directory()),
        "--loop-process-id",
        str(os.getpid()),
        "--loop-start-ticks",
        str(running_start_ticks(os.getpid())),
        *replay_arguments(paths, training),
    ]
    return arguments


@contextlib.asynccontextmanager
async def open_trainer(
    paths: GrpoLoopPaths, config: GrpoLoopConfig, log: Callable[[str], None]
) -> AsyncIterator[SubprocessTrainer | PersistentTrainer]:
    """The persistent trainer with `[training] persistent`, else one job per phase."""
    if not config.training.persistent:
        yield SubprocessTrainer(paths, config.training)
        return
    arguments = persistent_trainer_arguments(paths, config)
    environment = training_environment(paths, config.training)
    host = HostDirectories(config.host_directory())
    trainer = PersistentTrainer(paths, config.training, arguments, environment, host, log)
    try:
        yield trainer
    finally:
        await trainer.close()


def slowest(seconds: Sequence[PhaseSeconds]) -> PhaseSeconds:
    """Per part, the longest of the servers handled at once."""
    return PhaseSeconds(
        max((part.pause for part in seconds), default=0.0),
        max((part.weights for part in seconds), default=0.0),
        max((part.resume for part in seconds), default=0.0),
    )


@dataclass(frozen=True)
class ServerStart:
    server: ServerEndpoint
    command: str


def serve_command(
    serving: ServingConfig, publisher: MergedPublisher, version: ModelVersion, server: ServerEndpoint
) -> str:
    """The server's start command for the version; policy servers report the tempered log-probabilities."""
    command = publisher.serve_command(version, server)
    return f"{command} {POLICY_SERVER_ARGUMENTS}" if server in serving.policy_servers else command


async def start_server(start: ServerStart) -> None:
    """Stops what is left of the server, then starts it; serve_model.sh returns once it answers."""
    name = start.server.name
    for command in (f"deployment/stop_model.sh {name}", start.command):
        process = await asyncio.create_subprocess_exec("bash", "-c", command, cwd=REPOSITORY_DIRECTORY)
        if await process.wait():
            raise RuntimeError(f"Starting {name} failed ({command}); see $LEAN_SEARCH_RUNS/servers/{name}.log")


async def start_servers(starts: Sequence[ServerStart]) -> None:
    """The servers of one GPU one after another (each sizes itself by the memory the others left), the GPUs in
    parallel."""
    by_gpu: dict[int, list[ServerStart]] = {}
    for start in starts:
        by_gpu.setdefault(start.server.gpu, []).append(start)

    async def start_in_turn(group: Sequence[ServerStart]) -> None:
        for start in group:
            await start_server(start)

    outcomes = await asyncio.gather(*(start_in_turn(group) for group in by_gpu.values()), return_exceptions=True)
    failures = [str(outcome) for outcome in outcomes if isinstance(outcome, BaseException)]
    if failures:
        raise RuntimeError("; ".join(failures))


class VllmServers:
    """The merged policy and value servers: in-place weight swaps, sleep on the training GPUs."""

    def __init__(self, serving: ServingConfig, released: Sequence[ServerEndpoint], publisher: MergedPublisher) -> None:
        self.serving = serving
        self.released = tuple(released)
        self.publisher = publisher

    async def check(self) -> None:
        down = await self.unhealthy()
        if down:
            raise RuntimeError(f"Servers not answering: {down}; start them (grpo_loop.py start-servers).")

    async def unhealthy(self) -> list[str]:
        healthy = await asyncio.gather(*(is_healthy(server.url) for server in self.serving.servers))
        return [server.name for server, up in zip(self.serving.servers, healthy, strict=True) if not up]

    async def restart(self, names: Sequence[str], version: ModelVersion) -> None:
        await start_servers(
            [
                ServerStart(server, serve_command(self.serving, self.publisher, version, server))
                for server in self.serving.servers
                if server.name in names
            ]
        )

    async def release(self) -> PhaseSeconds:
        return slowest(await asyncio.gather(*(release_gpu(server.url) for server in self.released)))

    async def serve(self, version: ModelVersion) -> PhaseSeconds:
        return slowest(
            await asyncio.gather(
                *(
                    self.serve_weights(server, self.publisher.weights(version, server))
                    for server in self.serving.servers
                )
            )
        )

    async def serve_value(self, weights: str) -> None:
        await asyncio.gather(*(self.serve_weights(server, weights) for server in self.serving.value_servers))

    async def serve_weights(self, server: ServerEndpoint, weights: str) -> PhaseSeconds:
        # An in-place reload needs ~1.2 GiB beyond the KV cache, more than a GPU shared by two servers keeps free.
        if not await is_sleeping(server.url):
            await release_gpu(server.url)
        return await restore_gpu(server.url, Path(weights))


class SubprocessEvaluations:
    """experiments/grpo_evaluate.py as its own process, each recorded apart (version 0's baselines run at once); it
    writes the fixed_targets line, the summary and its progress."""

    def __init__(self, paths: GrpoLoopPaths, command_prefix: str, current_version: Callable[[], int]) -> None:
        self.paths = paths
        self.command_prefix = command_prefix
        self.current_version = current_version
        self.running: dict[EvaluationRun, EvaluationPaths] = {}

    def searches_in_flight(self, run: EvaluationRun) -> int | None:
        progress = read_search_progress(self.running[run].progress) if run in self.running else None
        return None if progress is None else progress.searches_in_flight

    async def evaluate(self, run: EvaluationRun, phase: int) -> EvaluationSummary:
        directory = self.paths.evaluation_directory(run, self.current_version())
        arguments = [
            *shlex.split(self.command_prefix),
            sys.executable,
            "experiments/grpo_evaluate.py",
            "--loop-directory",
            str(self.paths.directory),
            "--target",
            run.kind.value,
            "--phase",
            str(phase),
            "--repeat",
            str(run.repeat),
        ]
        if run.slot is not None:
            arguments += ["--slot", str(run.slot)]
        if run.value_arm:
            arguments.append("--value-arm")
        if run.concurrency:
            arguments += ["--concurrency", str(run.concurrency)]
        log_path = directory.with_name(directory.name + ".log")
        record_path = self.paths.children / "evaluations" / directory.name / "evaluation.pid"
        self.running[run] = EvaluationPaths(directory)
        try:
            await run_logged(arguments, log_path, dict(os.environ), record_path)
        finally:
            del self.running[run]
        return read_summary(directory / "summary.json")


class ServedValueScorer:
    """The value benchmark through the value servers, as the search scores its states."""

    def __init__(self, config: ValueConfig) -> None:
        self.config = config

    async def score(self, benchmark: ValueBenchmark) -> BenchmarkScores:
        async with open_value_estimator(self.config) as estimator:
            return await score_benchmark(estimator, benchmark)


def directory_bytes(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def evaluation_repls(config: GrpoLoopConfig) -> int:
    """The most Lean REPLs while evaluating (the searches' in-flight REPLs above the limit aside, which stop once their
    search ends): at a pause or before sampling the evaluations' own; beside sampling also the searches', at least
    the floor's, the others' idle processes stopped."""
    evaluation = config.evaluation
    targets = (evaluation.probe, evaluation.minif2f, evaluation.held_out_states)
    paused = max(target.concurrency for target in targets)
    baselines = sum(
        baseline_concurrency(config, kind) * baseline_jobs(evaluation, kind)
        for kind in EvaluationKind
        if target_config(evaluation, kind).at_start
    )
    if not evaluation.beside_sampling:
        return max(paused, baselines)
    floor = config.sampling.min_concurrency_beside_evaluations
    beside = max(config.sampling.concurrency, floor + max(evaluation.probe.concurrency, evaluation.minif2f.concurrency))
    return max(evaluation.held_out_states.concurrency, baselines, beside)


def host_memory_text(config: GrpoLoopConfig | None = None) -> str:
    """The node's memory as the system sampler reads it (cgroup limit, available, Lean REPLs, vLLM); with the loop's
    config also what the persistent trainer keeps in its host directory (a tmpfs: parked weights, merges handed to the
    servers) and the budget's conditions on these measurements (`host_memory.budget_conditions`)."""
    memory = host_memory(CGROUP, PROC, LEAN_PROCESS_NAMES)
    text = (
        f"{memory.available_bytes / GIB:.1f} of {memory.total_bytes / GIB:.1f} GiB available; "
        f"{len(memory.lean_private_bytes)} Lean processes {sum(memory.lean_private_bytes) / GIB:.1f} GiB private, "
        f"vLLM {memory.vllm_private_bytes / GIB:.1f} GiB private"
    )
    if config is None:
        return text
    host = HostDirectories(config.host_directory())
    terms = HostMemoryTerms(
        total=memory.total_bytes / GIB,
        repl_p90=percentile_90(memory.lean_private_bytes) / GIB,
        vllm=memory.vllm_private_bytes / GIB,
        parked=directory_bytes(host.parked) / GIB,
        handoff=directory_bytes(host.handoff) / GIB,
    )
    conditions = budget_conditions(
        terms, config.sampling.concurrency, evaluation_repls(config), len(config.training.gpus)
    )
    return (
        f"{text}; persistent trainer {terms.parked:.1f} GiB parked, {terms.handoff:.1f} GiB handed off; "
        f"{budget_text(conditions)} (training ranks and merges not measured)"
    )


def gpu_memory_text(config: GrpoLoopConfig) -> str:
    """Each training GPU's free memory before its servers wake, beside what their shares take back once awake (each
    sleeping server still holds ~0.8 GiB of it): the persistent trainer's CUDA context and NCCL buffers, or a stray
    process, show as the difference."""
    usage = GpuReader().usage()
    if not usage.memory_total_gib:
        return "not measured (no NVML)"
    parts = []
    for gpu in config.training.gpus:
        total = usage.memory_total_gib[gpu]
        shares = sum(server.memory_share for server in config.serving.servers if server.gpu == gpu)
        parts.append(
            f"GPU {gpu} {total - usage.memory_used_gib[gpu]:.1f} of {total:.1f} GiB free, its servers' shares "
            f"{shares * total:.1f} GiB"
        )
    return "; ".join(parts)


def serve_commands(config: GrpoLoopConfig, publisher: MergedPublisher, version: ModelVersion) -> list[str]:
    return [serve_command(config.serving, publisher, version, server) for server in config.serving.servers]


@dataclass(frozen=True)
class ServerCheck:
    server_url: str
    samples: int
    usable_blocks: int
    finish_reasons: tuple[str, ...]
    mean_tokens: float
    # Every sample carries token ids and one log-probability each, and its tokens decode to its text (plus the
    # end of turn or stop string the text omits).
    tokens_recorded: bool
    tokens_decode_to_text: bool
    mean_token_log_probability: float
    first_text: str


async def check_policy_server(config: PolicyConfig, server_url: str) -> ServerCheck:
    """One live request the way the search sends it, and what the search and the trainer need from the answer."""
    tokenizer = load_tokenizer(config.tokenizer)
    prompt = render_prompt(
        tokenizer,
        CHECK_GOALS,
        few_shot=config.few_shot,
        thinking=config.thinking,
        thinking_instruction=config.thinking_instruction,
        visible=config.visible_reasoning,
    )
    async with PolicyClient(server_url, config.model, timeout_seconds=config.request_timeout_seconds) as client:
        generation = await client.generate(
            prompt,
            sample_count=config.sample_count,
            max_tokens=config.max_tokens,
            temperature=config.temperature,
            top_p=config.top_p,
            stop=stop_sequences(config.thinking, config.visible_reasoning),
        )
    samples = generation.samples
    parsed = parse_samples(
        samples, thinking=config.thinking, forbidden_tokens=FORBIDDEN_TOKENS, visible=config.visible_reasoning
    )
    log_probabilities = [value for sample in samples for value in sample.tokens.log_probabilities if value is not None]
    return ServerCheck(
        server_url=server_url,
        samples=len(samples),
        usable_blocks=sum(candidate.sample_count for candidate in parsed.candidates),
        finish_reasons=tuple(sample.finish_reason for sample in samples),
        mean_tokens=statistics.fmean(sample.token_count for sample in samples) if samples else 0.0,
        tokens_recorded=all(
            sample.tokens.token_ids and len(sample.tokens.token_ids) == len(sample.tokens.log_probabilities)
            for sample in samples
        ),
        tokens_decode_to_text=all(
            tokenizer.decode(list(sample.tokens.token_ids), skip_special_tokens=False).startswith(sample.text)
            for sample in samples
        ),
        mean_token_log_probability=statistics.fmean(log_probabilities) if log_probabilities else 0.0,
        first_text=samples[0].text if samples else "",
    )
