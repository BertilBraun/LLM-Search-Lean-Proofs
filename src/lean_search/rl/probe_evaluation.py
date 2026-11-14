"""A probe evaluation of any checkpoint outside a loop (experiments/probe_evaluate.py): a policy adapter with a value
adapter, value v0 or no value model, over the probe set with a given search config, concurrency and wall cap.

The run's directory holds what a loop's probe run holds (results.jsonl, summary.json, trees, config.toml),
checkpoint.json (the checkpoint, the search settings and their identity, which `probe_rating` pools runs by, and
whether the run is the rating's anchor), sessions.jsonl (one line per session: the results it started from and the
weights it served; a session spoiled by a loop that started beside it is discarded on resume) and, once finished,
run.json: the share of searches stopped on the wall clock against the maximum, in total and per stratum, and where it
ran. `probe_rating.finished_probe_runs` rates only runs whose run.json says accepted.

The servers are the loop config's, already running; every session merges the adapters (once per content: a digest of
their weight and config files) and swaps them into the servers in place, as the loop does at a publish, so a resumed
run never searches with what the servers held before. One run at a time holds the servers (the node's serving lock,
`policy.serving_lock`), never while a loop runs (`running_loops`).
"""

import asyncio
import dataclasses
import datetime
import hashlib
import importlib.metadata
import json
import os
import shutil
import socket
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lean_search.expert_iteration.loop_config import ServingConfig
from lean_search.policy.server_control import is_healthy, is_sleeping, release_gpu, restore_gpu
from lean_search.rl.evaluation import EvaluationProblem, EvaluationSummary
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.loop_services import EVERY_RECORD, live_children
from lean_search.rl.search_models import evaluation_run_config, run_config_text, served_run_config
from lean_search.rl.search_options import without_search_options
from lean_search.search import PriorityKind, RunConfig, SearchResult, StopReason
from lean_search.search.records import from_json_object, to_json

# The value version recorded for a run without a value model.
NO_VALUE_VERSION = -1
MERGED_MARKER = "merged_from.txt"
# A merge kept after its run (--keep-merge); any other merge left by a dead run is removed at the next start.
KEPT_MARKER = "kept.txt"
# The files that make an adapter: what its digest covers.
ADAPTER_FILES = ("adapter_config.json", "*.safetensors")
# An adapter's merge into a base model's weights at a directory (lean_search.policy.adapters.merge_adapter).
Merge = Callable[[str, Path, Path], None]


@dataclass(frozen=True)
class ValueFreePriority:
    """The value-free search of the design's Q4 (row 2's, experiments/configs/phase2_sft_v2_search.toml): best-first by
    the path's mean step log-probability per block; the search config's other priority settings are kept."""

    length_exponent: float = 1.0
    # An automation step's log-probability: row 2's median over the samples that made progress (-2.79), until the
    # study calibrates it on 200 pool statements outside every held-out set.
    automation_log_probability: float = -2.8


@dataclass(frozen=True)
class ProbeEvaluationConfig:
    # A loop config: its [serving] (the servers, their model names and base models) and [initial] value_adapter (v0).
    loop_config: str
    # The search template; harvesting, exploration and search options are off. The budget rule: a run given
    # --search-config searches at that file's own max_expansions, every other run at `probe.max_expansions`.
    search_config: str
    # Under $LEAN_SEARCH_DATA.
    probe_set: str = "grpo/fixed_sets/probe_v2.jsonl"
    probe: EvaluationTarget = field(default_factory=lambda: EvaluationTarget(16, 7200.0, 56))
    value_free_priority: ValueFreePriority = field(default_factory=ValueFreePriority)
    # A run is accepted only with a smaller share of searches stopped on the wall clock (strictly below).
    max_wall_clock_stop_share: float = 0.01
    # Under $LEAN_SEARCH_RUNS the runs (probe_<name>/), under $LEAN_SEARCH_CHECKPOINTS the merges.
    output: str = "probe_evaluations"


@dataclass(frozen=True)
class ProbeCheckpoint:
    # The series it belongs to (e.g. "v0", "A", "step2_B2_5e-5") and its phase in it (0 for v0).
    arm: str
    phase: int
    policy_adapter: str
    policy_digest: str
    # Empty: no value model, the search best-first on the policy's log-probabilities.
    value_adapter: str
    value_digest: str
    # The first this many problems of the probe set, strata in turn (a pilot); 0: all.
    problems: int
    # The rating's labels: the phase, and -1 / 0 / given for the value model.
    policy_version: int
    value_version: int

    @property
    def label(self) -> str:
        value = f"value {self.value_digest[:12]}" if self.value_digest else "no value model"
        pilot = f"/first {self.problems}" if self.problems else ""
        return f"{self.arm}/phase {self.phase}/policy {self.policy_digest[:12]}/{value}{pilot}"


def run_identity(checkpoint: ProbeCheckpoint, run_config_sha256: str, max_expansions: int, wall_seconds: float) -> str:
    """What `probe_rating` pools runs by: two runs of one identity are repeats of one checkpoint searched alike (the
    search config, budget, wall cap and concurrency all inside the run config's digest)."""
    return f"{checkpoint.label}/search {run_config_sha256[:12]} ({max_expansions} expansions, {wall_seconds:g} s cap)"


@dataclass(frozen=True)
class ProbeRunStart:
    identity: str
    # The rating's anchor (`probe_rating`): v0's policy with value v0 at the standard settings, named explicitly.
    anchor: bool
    checkpoint: ProbeCheckpoint
    search_config: str
    # sha256 of the run config as searched (served, at the probe's budget, cap and concurrency).
    run_config_sha256: str
    concurrency: int
    max_wall_seconds: float
    max_expansions: int
    probe_set: str
    probe_set_sha256: str


@dataclass(frozen=True)
class StratumStops:
    stratum: str
    problems: int
    wall_clock_stops: int


@dataclass(frozen=True)
class RunEnvironment:
    hostname: str
    lean_toolchain: str
    vllm: str
    torch: str


@dataclass(frozen=True)
class ProbeRunRecord:
    start: ProbeRunStart
    environment: RunEnvironment
    problems: int
    solved: int
    wall_clock_stops: int
    wall_clock_stop_share: float
    wall_clock_stops_by_stratum: tuple[StratumStops, ...]
    max_wall_clock_stop_share: float
    accepted: bool


def adapter_digest(directory: Path) -> str:
    """sha256 over the adapter's weight and config files (name and content): a file rewritten in place changes it,
    another file in the directory does not."""
    digest = hashlib.sha256()
    files = sorted({file for pattern in ADAPTER_FILES for file in directory.glob(pattern) if file.is_file()})
    for path in files:
        digest.update(path.name.encode() + b"\0")
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        digest.update(b"\0")
    return digest.hexdigest()


def resolve_value_adapter(value: str, value_v0_adapter: str) -> str:
    """`--value`: "none", "v0" (the loop config's starting value adapter) or an adapter's path."""
    match value:
        case "none":
            return ""
        case "v0":
            return value_v0_adapter
        case _:
            return str(Path(value).absolute())


def default_value_version(value: str) -> int | None:
    """None for an adapter's path: its label must be given."""
    match value:
        case "none":
            return NO_VALUE_VERSION
        case "v0":
            return 0
        case _:
            return None


def probe_run_config(
    template: RunConfig,
    serving: ServingConfig,
    target: EvaluationTarget,
    value_free: ValueFreePriority | None,
    template_budget: bool,
) -> RunConfig:
    """The template on the servers at the probe's wall cap and REPLs (and budget, unless `template_budget`: then the
    template's), harvesting, exploration and search options off. With `value_free` no value model and the value-free
    priority; the template's other priority settings are kept."""
    if value_free is not None:
        priority = dataclasses.replace(
            template.priority,
            kind=PriorityKind.CUMULATIVE_LOG_PROBABILITY,
            length_exponent=value_free.length_exponent,
            automation_log_probability=value_free.automation_log_probability,
        )
        template = dataclasses.replace(template, value=dataclasses.replace(template.value, model=""), priority=priority)
    if template_budget:
        target = dataclasses.replace(target, max_expansions=template.search.max_expansions)
    return evaluation_run_config(served_run_config(without_search_options(template), serving), target)


def run_config_sha256(config: RunConfig) -> str:
    return hashlib.sha256(run_config_text(config).encode()).hexdigest()


def run_directory(runs_root: Path, name: str) -> Path:
    """`probe_` first, so that `probe_rating.finished_probe_runs(runs_root)` finds it."""
    return runs_root / f"probe_{name}"


def merge_directory(weights_root: Path, base_model: str, digest: str) -> Path:
    return weights_root / hashlib.sha256(f"{base_model}\n{digest}".encode()).hexdigest()[:24]


def checkpoint_merges(serving: ServingConfig, checkpoint: ProbeCheckpoint, weights_root: Path) -> list[Path]:
    """Where the checkpoint's merges go, whether or not they exist yet."""
    merges = [merge_directory(weights_root, serving.policy_base_model, checkpoint.policy_digest)]
    if checkpoint.value_adapter:
        merges.append(merge_directory(weights_root, serving.value_base_model, checkpoint.value_digest))
    return merges


def merged_weights(base_model: str, adapter: Path, digest: str, weights_root: Path, merge: Merge) -> Path:
    """The adapter merged into the base once per base and content: an adapter rewritten in place is merged again."""
    directory = merge_directory(weights_root, base_model, digest)
    if not (directory / MERGED_MARKER).exists():
        temporary = directory.with_name(directory.name + ".tmp")
        shutil.rmtree(temporary, ignore_errors=True)
        merge(base_model, adapter, temporary)
        (temporary / MERGED_MARKER).write_text(f"{adapter}\n{digest}\n", encoding="utf-8")
        shutil.rmtree(directory, ignore_errors=True)
        os.replace(temporary, directory)
    return directory


async def swap_weights(server_url: str, weights: Path) -> None:
    # An in-place reload needs ~1.2 GiB beyond the KV cache, more than a GPU shared by two servers keeps free.
    if not await is_sleeping(server_url):
        await release_gpu(server_url)
    await restore_gpu(server_url, weights)


class ServersDownError(RuntimeError):
    pass


@dataclass(frozen=True)
class ServedWeights:
    policy: Path
    # None: the value servers were left as they were (no value model).
    value: Path | None


async def serve_checkpoint(
    serving: ServingConfig, checkpoint: ProbeCheckpoint, weights_root: Path, merge: Merge
) -> ServedWeights:
    """Merges the adapters (or reuses their merges) and swaps them into the running servers; raises ServersDownError
    when a server needed does not answer."""
    needed = [*serving.policy_servers, *(serving.value_servers if checkpoint.value_adapter else ())]
    healthy = await asyncio.gather(*(is_healthy(server.url) for server in needed))
    down = [server.name for server, up in zip(needed, healthy, strict=True) if not up]
    if down:
        raise ServersDownError(f"Servers not answering: {down}; start them (deployment/grpo_loop.sh servers).")
    policy = await asyncio.to_thread(
        merged_weights,
        serving.policy_base_model,
        Path(checkpoint.policy_adapter),
        checkpoint.policy_digest,
        weights_root,
        merge,
    )
    await asyncio.gather(*(swap_weights(server.url, policy) for server in serving.policy_servers))
    if not checkpoint.value_adapter:
        return ServedWeights(policy, None)
    value = await asyncio.to_thread(
        merged_weights,
        serving.value_base_model,
        Path(checkpoint.value_adapter),
        checkpoint.value_digest,
        weights_root,
        merge,
    )
    await asyncio.gather(*(swap_weights(server.url, value) for server in serving.value_servers))
    return ServedWeights(policy, value)


def remove_merges(directories: Sequence[Path]) -> None:
    """The merges and any half-written ones beside them."""
    for directory in directories:
        shutil.rmtree(directory, ignore_errors=True)
        shutil.rmtree(directory.with_name(directory.name + ".tmp"), ignore_errors=True)


def keep_merges(directories: Sequence[Path]) -> None:
    for directory in directories:
        (directory / KEPT_MARKER).write_text("kept by --keep-merge\n", encoding="utf-8")


def remove_stale_merges(weights_root: Path) -> list[Path]:
    """Under the serving lock, nobody else merges: every merge not kept on purpose is a dead run's."""
    stale = [
        directory
        for directory in sorted(weights_root.glob("*"))
        if directory.is_dir() and not (directory / KEPT_MARKER).exists()
    ]
    for directory in stale:
        shutil.rmtree(directory, ignore_errors=True)
    return stale


@dataclass(frozen=True)
class LoopActivity:
    running: tuple[str, ...]
    # loop.pid files that could not be read, treated as not running (no live job of that loop).
    notes: tuple[str, ...]


def running_loops(runs_root: Path) -> LoopActivity:
    """The loops under `runs_root` whose process (loop.pid) or a job they started (children/) still runs."""
    running = []
    notes = []
    for pid_file in sorted(runs_root.glob("*/loop.pid")):
        try:
            process_id = pid_file.read_text(encoding="utf-8").strip()
        except OSError:
            process_id = ""
        if not process_id.isdigit():
            notes.append(f"{pid_file} is empty or unreadable: treated as not running (no live job checked below)")
        elif Path(f"/proc/{process_id}").exists():
            running.append(f"{pid_file.parent.name} (pid {process_id})")
    for children in sorted(runs_root.glob("*/children")):
        jobs = live_children(children, EVERY_RECORD)
        if jobs:
            running.append(f"{children.parent.name}'s jobs {[job.process_ids for job in jobs]}")
    return LoopActivity(tuple(running), tuple(notes))


@dataclass(frozen=True)
class ProbeSession:
    session: str
    # results.jsonl lines when the session started; the weights it served.
    results_before: int
    policy_digest: str
    value_digest: str
    # A loop started beside it: its results may come from another checkpoint.
    spoiled: bool = False


SESSIONS_FILE = "sessions.jsonl"


def read_sessions(directory: Path) -> list[ProbeSession]:
    path = directory / SESSIONS_FILE
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()
    return [from_json_object(ProbeSession, json.loads(line)) for line in lines if line.strip()]


def append_session(directory: Path, session: ProbeSession) -> None:
    with (directory / SESSIONS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(to_json(session) + "\n")


def start_session(directory: Path, checkpoint: ProbeCheckpoint, results: Path) -> ProbeSession:
    count = len(results.read_text(encoding="utf-8").splitlines()) if results.exists() else 0
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    session = ProbeSession(f"{started} pid {os.getpid()}", count, checkpoint.policy_digest, checkpoint.value_digest)
    append_session(directory, session)
    return session


def mark_spoiled(directory: Path, session: ProbeSession) -> None:
    append_session(directory, dataclasses.replace(session, spoiled=True))


def discard_spoiled_results(directory: Path, results: Path, trees: Path) -> int:
    """Cuts results.jsonl back to where the first spoiled session started (its trees and the summary go too) and
    forgets the sessions from there on; returns the results discarded."""
    sessions = read_sessions(directory)
    spoiled = [session.results_before for session in sessions if session.spoiled]
    if not spoiled:
        return 0
    cut_at = min(spoiled)
    lines = results.read_text(encoding="utf-8").splitlines(keepends=True) if results.exists() else []
    for line in lines[cut_at:]:
        (trees / f"{json.loads(line)['problem_name']}.json.gz").unlink(missing_ok=True)
    results.write_text("".join(lines[:cut_at]), encoding="utf-8")
    (directory / "summary.json").unlink(missing_ok=True)
    kept = [session for session in sessions if session.results_before < cut_at and not session.spoiled]
    (directory / SESSIONS_FILE).write_text("".join(to_json(session) + "\n" for session in kept), encoding="utf-8")
    return len(lines) - cut_at


def package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def run_environment(lean_project: Path) -> RunEnvironment:
    toolchain = lean_project / "lean-toolchain"
    return RunEnvironment(
        hostname=socket.gethostname(),
        lean_toolchain=toolchain.read_text(encoding="utf-8").strip() if toolchain.exists() else "unknown",
        vllm=package_version("vllm"),
        torch=package_version("torch"),
    )


def stops_by_stratum(
    problems: Sequence[EvaluationProblem], results: Sequence[SearchResult]
) -> tuple[StratumStops, ...]:
    stopped = {result.problem_name for result in results if result.stop_reason == StopReason.WALL_CLOCK_BUDGET}
    strata: dict[str, list[int]] = {}
    for problem in problems:
        counts = strata.setdefault(problem.stratum, [0, 0])
        counts[0] += 1
        counts[1] += problem.problem.name in stopped
    return tuple(StratumStops(stratum, *counts) for stratum, counts in strata.items())


def run_record(
    start: ProbeRunStart,
    environment: RunEnvironment,
    summary: EvaluationSummary,
    by_stratum: tuple[StratumStops, ...],
    max_share: float,
) -> ProbeRunRecord:
    share = summary.wall_clock_stops / summary.problems
    return ProbeRunRecord(
        start=start,
        environment=environment,
        problems=summary.problems,
        solved=summary.solved,
        wall_clock_stops=summary.wall_clock_stops,
        wall_clock_stop_share=share,
        wall_clock_stops_by_stratum=by_stratum,
        max_wall_clock_stop_share=max_share,
        accepted=share < max_share,
    )
