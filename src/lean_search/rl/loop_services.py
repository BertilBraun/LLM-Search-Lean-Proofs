"""The GRPO loop's production boundaries: Lean searches with the served models, the training job, the vLLM servers,
the evaluation jobs, the servers' start commands and the first-hour check of a policy server's responses."""

import asyncio
import contextlib
import json
import os
import shlex
import signal
import statistics
import sys
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.data import Problem
from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig
from lean_search.expert_iteration.loop_search import PauseGate
from lean_search.expert_iteration.serving import MergedPublisher, ModelVersion, write_json_atomically
from lean_search.lean import FORBIDDEN_TOKENS, LeanReplConfig, LeanReplPool
from lean_search.policy.client import PolicyClient
from lean_search.policy.config import PolicyConfig
from lean_search.policy.expander import load_tokenizer
from lean_search.policy.prompts import parse_samples, render_prompt, stop_sequences
from lean_search.policy.server_control import is_healthy, is_sleeping, publish_weights, release_gpu, restore_gpu
from lean_search.rl.evaluation import EvaluationKind, EvaluationSummary, read_summary
from lean_search.rl.loop import (
    PHASE_OUTCOME_FILE,
    GrpoLoopPaths,
    ReleasedLeanMemory,
    TrainingRequest,
    read_phase_outcome,
)
from lean_search.rl.loop_config import GrpoLoopConfig, LoopTrainingConfig
from lean_search.rl.renaming import StatementRenamings, search_problem
from lean_search.rl.search_models import SearchModels, open_search_models
from lean_search.rl.training_phase import PhaseOutcome
from lean_search.search import CompletedSearch, RunConfig
from lean_search.search.records import from_json_object

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[3]
# The GRPO trainer compares the sampler's log-probabilities with its own at the sampling temperature.
POLICY_SERVER_ARGUMENTS = "--logprobs-mode processed_logprobs"
CHECK_GOALS = ("x : ℝ\nh₀ : 3 * x + 2 = 11\n⊢ x = 3",)
# A stopped job's process group gets SIGTERM, then SIGKILL after this long.
CHILD_STOP_SECONDS = 30.0


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

    async def release_lean_memory(self, above_bytes: int) -> ReleasedLeanMemory:
        stopped = await self.pool.stop_processes(above_bytes)
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


def running_start_ticks(process_id: int) -> int | None:
    """The process's start time, or None once it ended (zombies included)."""
    try:
        text = Path(f"/proc/{process_id}/stat").read_text()
    except FileNotFoundError:
        return None
    fields = text[text.rindex(")") + 2 :].split()
    return None if fields[0] == "Z" else int(fields[19])


def live_children(directory: Path) -> list[ChildProcess]:
    children = [from_json_object(ChildProcess, json.loads(path.read_text())) for path in directory.glob("*.pid")]
    return [child for child in children if running_start_ticks(child.process_id) == child.start_ticks]


def signal_group(process_id: int, signal_number: signal.Signals) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process_id, signal_number)


async def stop_process_group(process: asyncio.subprocess.Process) -> None:
    signal_group(process.pid, signal.SIGTERM)
    try:
        await asyncio.wait_for(process.wait(), CHILD_STOP_SECONDS)
    except TimeoutError:
        signal_group(process.pid, signal.SIGKILL)
        await process.wait()
    # Its own children (Lean REPLs, data loader workers) share the group and may outlive it.
    signal_group(process.pid, signal.SIGKILL)


async def run_logged(arguments: Sequence[str], log_path: Path, environment: dict[str, str], record_path: Path) -> None:
    """The job in its own process group, recorded in `record_path` until it ends; cancelling stops the group."""
    # A job recorded beside it still running means an earlier loop died without stopping it.
    running = live_children(record_path.parent)
    if running:
        raise RuntimeError(
            f"Jobs of an earlier loop still run: {running}; stop them (kill -TERM -<process_id>) before restarting."
        )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log_file:
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=REPOSITORY_DIRECTORY,
            stdout=log_file,
            stderr=asyncio.subprocess.STDOUT,
            env=environment,
            start_new_session=True,
        )
        try:
            start_ticks = running_start_ticks(process.pid)
            if start_ticks is not None:
                write_json_atomically(record_path, ChildProcess(process.pid, start_ticks, shlex.join(arguments)))
            return_code = await process.wait()
        except BaseException:
            await stop_process_group(process)
            raise
        finally:
            if process.returncode is not None:
                record_path.unlink(missing_ok=True)
    if return_code:
        raise RuntimeError(f"{shlex.join(arguments)} failed; see {log_path}")


class SubprocessTrainer:
    """experiments/grpo_phase.py on the training GPU, one process per phase."""

    def __init__(self, paths: GrpoLoopPaths, config: LoopTrainingConfig) -> None:
        self.paths = paths
        self.config = config

    def arguments(self, request: TrainingRequest, config_path: Path) -> list[str]:
        arguments = [
            *shlex.split(self.config.command_prefix),
            sys.executable,
            "experiments/grpo_phase.py",
            "--config",
            str(config_path),
            "--trees",
            str(request.trees),
            "--run-name",
            request.run_name,
        ]
        for option, relative in (
            ("--lean-replay", self.config.lean_replay),
            ("--math-replay", self.config.math_replay),
            ("--value-replay", self.config.value_replay),
        ):
            if relative:
                arguments += [option, str(self.paths.data_root / relative)]
        if request.train_value:
            arguments += ["--value-benchmark", str(self.paths.runs_root / self.config.value_benchmark)]
        return arguments

    async def train(self, request: TrainingRequest) -> PhaseOutcome:
        config_path = self.paths.training / f"phase_{request.phase:04d}.toml"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(request.config_text, encoding="utf-8")
        environment = os.environ | {
            "CUDA_VISIBLE_DEVICES": str(self.config.gpu),
            "LEAN_SEARCH_CHECKPOINTS": str(self.paths.checkpoints_root),
            "PYTORCH_CUDA_ALLOC_CONF": "expandable_segments:True",
        }
        log_path = self.paths.training / f"phase_{request.phase:04d}.log"
        arguments = self.arguments(request, config_path)
        await run_logged(arguments, log_path, environment, self.paths.children / "training.pid")
        return read_phase_outcome(request.output_directory / PHASE_OUTCOME_FILE)


class VllmServers:
    """The merged policy and value servers: in-place weight swaps, sleep on the training GPU."""

    def __init__(self, serving: ServingConfig, released: Sequence[ServerEndpoint], publisher: MergedPublisher) -> None:
        self.serving = serving
        self.released = tuple(released)
        self.publisher = publisher

    async def check(self) -> None:
        healthy = await asyncio.gather(*(is_healthy(server.url) for server in self.serving.servers))
        down = [server.name for server, up in zip(self.serving.servers, healthy, strict=True) if not up]
        if down:
            raise RuntimeError(f"Servers not answering: {down}; start them (grpo_loop.py serve-commands).")

    async def release(self) -> None:
        await asyncio.gather(*(release_gpu(server.url) for server in self.released))

    async def serve(self, version: ModelVersion) -> None:
        await asyncio.gather(*(self.serve_one(server, version) for server in self.serving.servers))

    async def serve_one(self, server: ServerEndpoint, version: ModelVersion) -> None:
        weights = Path(self.publisher.weights(version, server))
        if await is_sleeping(server.url):
            await restore_gpu(server.url, weights)
        else:
            await publish_weights(server.url, weights)


class SubprocessEvaluations:
    """experiments/grpo_evaluate.py as its own process; it writes the fixed_targets line and the summary."""

    def __init__(self, paths: GrpoLoopPaths, command_prefix: str, current_version: Callable[[], int]) -> None:
        self.paths = paths
        self.command_prefix = command_prefix
        self.current_version = current_version

    async def evaluate(self, kind: EvaluationKind, phase: int, repeat: int) -> EvaluationSummary:
        version = self.current_version()
        directory = self.paths.evaluation_directory(kind, version, repeat)
        arguments = [
            *shlex.split(self.command_prefix),
            sys.executable,
            "experiments/grpo_evaluate.py",
            "--loop-directory",
            str(self.paths.directory),
            "--target",
            kind.value,
            "--phase",
            str(phase),
            "--repeat",
            str(repeat),
        ]
        log_path = directory.with_name(directory.name + ".log")
        await run_logged(arguments, log_path, dict(os.environ), self.paths.children / "evaluation.pid")
        return read_summary(directory / "summary.json")


def serve_commands(config: GrpoLoopConfig, publisher: MergedPublisher, version: ModelVersion) -> list[str]:
    """Each server's start command for the version; policy servers report the tempered log-probabilities."""
    return [
        publisher.serve_command(version, server)
        + (f" {POLICY_SERVER_ARGUMENTS}" if server in config.serving.policy_servers else "")
        for server in config.serving.servers
    ]


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
