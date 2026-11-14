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
import filecmp
import hashlib
import importlib.metadata
import json
import math
import os
import re
import shutil
import socket
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig, SwapMethod
from lean_search.expert_iteration.serving import write_json_atomically
from lean_search.policy.config import StepLogProbability
from lean_search.policy.rotation import RequestFailures
from lean_search.policy.server_control import is_healthy, is_sleeping
from lean_search.policy.server_processes import server_process, swapped_marker
from lean_search.rl.evaluation import EvaluationProblem, EvaluationSummary, SearchFailure, ServerRecoveryError
from lean_search.rl.loop_config import EvaluationTarget
from lean_search.rl.loop_services import (
    CHECK_GOALS,
    EVERY_RECORD,
    ServedWeightsOn,
    ServerStart,
    check_policy_server,
    live_children,
    put_weights,
    unhealthy_servers,
    weights_start_command,
)
from lean_search.rl.search_models import evaluation_run_config, run_config_text, served_run_config
from lean_search.rl.search_options import without_search_options
from lean_search.search import PriorityKind, RunConfig, SearchResult, StopReason
from lean_search.search.records import from_json_object, to_json
from lean_search.value.estimator import open_value_estimator

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
class AutomationConstant:
    """An automation step's log-probability for one step log-probability setting: on the scale of the policy's step
    values, so each setting needs its own (policy/README.md, "Candidate log-probability")."""

    step_log_probability: StepLogProbability
    automation_log_probability: float
    # False: a placeholder until the calibration on 200 pool statements outside every held-out set fills it in; a
    # value-free run refuses it.
    calibrated: bool


@dataclass(frozen=True)
class ValueFreePriority:
    """The value-free search of the design's Q4 (row 2's, experiments/configs/phase2_sft_v2_search.toml): best-first by
    the path's mean step log-probability per block; the search config's other priority settings are kept. The policy's
    step log-probability and the automation constant calibrated for it are set together."""

    length_exponent: float = 1.0
    step_log_probability: StepLogProbability = StepLogProbability.COMPLETION
    # Row 2's: the median whole-completion log-probability of the samples that made progress (-2.79).
    automation_constants: tuple[AutomationConstant, ...] = (
        AutomationConstant(StepLogProbability.COMPLETION, -2.8, calibrated=True),
    )

    def automation_log_probability(self) -> float:
        """Raises ValueError when the setting has no constant, or only a placeholder."""
        constants = [
            constant
            for constant in self.automation_constants
            if constant.step_log_probability == self.step_log_probability
        ]
        if not constants:
            raise ValueError(f"No automation constant for step_log_probability = {self.step_log_probability!r}.")
        if not constants[0].calibrated:
            raise ValueError(
                f"The automation constant for step_log_probability = {self.step_log_probability!r} is a placeholder "
                f"({constants[0].automation_log_probability}): calibrate it first."
            )
        return constants[0].automation_log_probability


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
    # A statement whose search a server failed is searched again at most this often; a server that died is started
    # again from the merges at most this often a run (evaluation.ToleratedSearches).
    server_failure_retries: int = 3
    max_server_restarts: int = 3


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


def run_identity(checkpoint: ProbeCheckpoint, run_config: RunConfig) -> str:
    """What `probe_rating` pools runs by: two runs of one identity are repeats of one checkpoint searched alike (the
    search config, budget, wall cap, concurrency and step log-probability all inside the run config's digest)."""
    search = run_config.search
    return (
        f"{checkpoint.label}/steps {run_config.policy.step_log_probability}/search "
        f"{run_config_sha256(run_config)[:12]} ({search.max_expansions} expansions, {search.max_wall_seconds:g} s cap)"
    )


def anchor_problem(
    checkpoint: ProbeCheckpoint, v0_policy_digest: str, v0_value_digest: str, own_search: bool
) -> str | None:
    """Why the checkpoint cannot be the rating's anchor (v0's policy and value v0 by content, the whole probe at the
    standard settings); None when it can."""
    if checkpoint.policy_digest != v0_policy_digest:
        return "its policy adapter is not the loop config's starting adapter"
    if checkpoint.value_digest != v0_value_digest:
        return "its value adapter is not value v0"
    if checkpoint.problems or own_search:
        return "it runs a pilot or its own search config"
    return None


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
class SessionServing:
    """How the session's weights reached the servers: put on by `swap` (in place, or the servers restarted from the
    merges), or already held (the servers started from byte-identical weights and never swapped since); `restarted`:
    the servers started again after a failure, the session beginning then."""

    swap: SwapMethod = SwapMethod.IN_PLACE
    swapped: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()
    restarted: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeSession:
    session: str
    # results.jsonl lines when the session started; the weights it served.
    results_before: int
    policy_digest: str
    value_digest: str
    # A loop started beside it: its results may come from another checkpoint.
    spoiled: bool = False
    serving: SessionServing = field(default_factory=SessionServing)
    started_at: str = ""


@dataclass(frozen=True)
class ServerRestart:
    at: str
    servers: tuple[str, ...]


@dataclass(frozen=True)
class RetriedStatement:
    problem_name: str
    failed_searches: int


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
    # Below the wall-clock stop share and no statement left without a result.
    accepted: bool
    sessions: tuple[ProbeSession, ...] = ()
    # No session put weights on any server: they all held the run's from their start.
    swap_skipped: bool = False
    server_restarts: tuple[ServerRestart, ...] = ()
    # Statements searched again after a server failed their search, and those left without a result.
    retried_statements: tuple[RetriedStatement, ...] = ()
    dropped_statements: tuple[str, ...] = ()


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
    template's), harvesting, exploration and search options off. With `value_free` no value model, the value-free
    priority and the policy's step log-probability with its automation constant (ValueError for a placeholder); the
    template's other priority settings are kept."""
    if value_free is not None:
        priority = dataclasses.replace(
            template.priority,
            kind=PriorityKind.CUMULATIVE_LOG_PROBABILITY,
            length_exponent=value_free.length_exponent,
            automation_log_probability=value_free.automation_log_probability(),
        )
        template = dataclasses.replace(
            template,
            policy=dataclasses.replace(template.policy, step_log_probability=value_free.step_log_probability),
            value=dataclasses.replace(template.value, model=""),
            priority=priority,
        )
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


class ServersDownError(RuntimeError):
    pass


# Lines a vLLM server logs at its first in-place reload (once per process), at every wake and at a sleep: a further
# sign, next to the tooling's own <name>.swapped, that it no longer holds what it started from. Read only on the vLLM
# version they were checked on; on another, every server counts as swapped.
SWAP_MARKERS = (
    "Reloading weights inplace",
    "wake up the engine with tags",
    "seconds to fall asleep",
    "Sleep mode freed",
)
SWAP_MARKERS_VLLM = "0.31.0"
API_SERVER_PROCESS = re.compile(r"\(APIServer pid=(\d+)\)")
# What makes merged weights the same for serving: compared byte for byte.
SERVED_FILES = ("config.json", "*.safetensors")


def holds_start_weights(servers_directory: Path, name: str, vllm_version: str) -> bool:
    """Whether the server provably holds the weights it started from: its pid file names a vLLM started for it
    (server_processes), the tooling never slept or swapped it in place since (no <name>.swapped), and its log is that
    process's and shows no sleep, wake or reload (on the vLLM version the lines were checked on). Anything unknown:
    False."""
    process = server_process(servers_directory, name)
    log = servers_directory / f"{name}.log"
    if process is None or swapped_marker(servers_directory, name).exists() or not log.exists():
        return False
    if vllm_version != SWAP_MARKERS_VLLM:
        return False
    text = log.read_text(encoding="utf-8", errors="replace")
    started_by = API_SERVER_PROCESS.search(text)
    return (
        started_by is not None
        and int(started_by.group(1)) == process.process_id
        and not any(marker in text for marker in SWAP_MARKERS)
    )


def same_served_weights(first: Path, second: Path) -> bool:
    def names(directory: Path) -> list[str]:
        return sorted({file.name for pattern in SERVED_FILES for file in directory.glob(pattern) if file.is_file()})

    files = names(first)
    return (
        bool(files)
        and files == names(second)
        and all(filecmp.cmp(first / name, second / name, shallow=False) for name in files)
    )


async def served_model_root(server_url: str) -> Path:
    """The directory the server started from (vLLM's /v1/models `root`)."""
    async with httpx.AsyncClient(timeout=30.0) as http:
        response = await http.get(f"{server_url.rstrip('/')}/models")
        response.raise_for_status()
        return Path(response.json()["data"][0]["root"])


async def answers_awake(server_url: str) -> bool:
    """/health answers and the server is not asleep (its weights discarded by a level-2 sleep)."""
    if not await is_healthy(server_url):
        return False
    try:
        return not await is_sleeping(server_url)
    except httpx.HTTPError:
        return False


async def already_serves(servers_directory: Path, server: ServerEndpoint, weights: Path, vllm_version: str) -> bool:
    """The server is awake, never slept or swapped since it started, and started from weights byte-identical to
    `weights`."""
    if not await answers_awake(server.url) or not holds_start_weights(servers_directory, server.name, vllm_version):
        return False
    root = await served_model_root(server.url)
    return await asyncio.to_thread(same_served_weights, root, weights)


@dataclass(frozen=True)
class ServedWeights:
    policy: Path
    # None: the value servers were left as they were (no value model).
    value: Path | None
    # The servers the weights were put on by the swap method, and those that already held them.
    swap: SwapMethod = SwapMethod.IN_PLACE
    swapped: tuple[str, ...] = ()
    skipped: tuple[str, ...] = ()

    def assignments(self, serving: ServingConfig) -> list[ServedWeightsOn]:
        """The weights each server the run needs serves."""
        policy = [ServedWeightsOn(server, str(self.policy)) for server in serving.policy_servers]
        value = (
            [] if self.value is None else [ServedWeightsOn(server, str(self.value)) for server in serving.value_servers]
        )
        return [*policy, *value]


# Checks the servers answer the way the search needs, from the weights assigned (`verify_served`); the second argument
# names the servers just started from their weights (or found holding byte-identical ones), whose answer may become
# the weights' reference. Raises ServersUnsoundError.
Verify = Callable[[Sequence[ServedWeightsOn], frozenset[str]], Awaitable[None]]


class ServersUnsoundError(RuntimeError):
    pass


async def check_started_from(assignments: Sequence[ServedWeightsOn]) -> None:
    """A server just started must report its assigned weights as its root (and not be another process on its port)."""
    for assigned in assignments:
        root = await served_model_root(assigned.server.url)
        if root.resolve() != Path(assigned.weights).resolve():
            raise ServersUnsoundError(f"{assigned.server.name} serves {root}, not {assigned.weights}")


async def serve_checkpoint(
    serving: ServingConfig,
    checkpoint: ProbeCheckpoint,
    weights_root: Path,
    merge: Merge,
    servers_directory: Path,
    verify: Verify,
    log: Callable[[str], None],
) -> ServedWeights:
    """Merges the adapters (or reuses their merges) and puts them on the servers the run needs by `serving.swap`,
    except on a server that provably already serves byte-identical weights it started from
    (`holds_start_weights`); then `verify`. In place, every server needed must answer first (ServersDownError); a
    restart starts a server that is down."""
    needed = [*serving.policy_servers, *(serving.value_servers if checkpoint.value_adapter else ())]
    down = await unhealthy_servers(needed)
    if down and serving.swap == SwapMethod.IN_PLACE:
        raise ServersDownError(f"Servers not answering: {down}; start them (deployment/grpo_loop.sh servers).")
    policy = await asyncio.to_thread(
        merged_weights,
        serving.policy_base_model,
        Path(checkpoint.policy_adapter),
        checkpoint.policy_digest,
        weights_root,
        merge,
    )
    value = None
    if checkpoint.value_adapter:
        value = await asyncio.to_thread(
            merged_weights,
            serving.value_base_model,
            Path(checkpoint.value_adapter),
            checkpoint.value_digest,
            weights_root,
            merge,
        )
    served = ServedWeights(policy, value, serving.swap)
    assignments = served.assignments(serving)
    vllm_version = package_version("vllm")
    held = [
        assigned.server.name not in down
        and await already_serves(servers_directory, assigned.server, Path(assigned.weights), vllm_version)
        for assigned in assignments
    ]
    to_put = [assigned for assigned, holds in zip(assignments, held, strict=True) if not holds]
    skipped = tuple(assigned.server.name for assigned, holds in zip(assignments, held, strict=True) if holds)
    if to_put:
        await put_weights(serving, to_put, servers_directory, log)
    fresh = set(skipped)
    if serving.swap == SwapMethod.RESTART:
        await check_started_from(to_put)
        fresh |= {assigned.server.name for assigned in to_put}
    await verify(assignments, frozenset(fresh))
    return dataclasses.replace(served, swapped=tuple(assigned.server.name for assigned in to_put), skipped=skipped)


@dataclass(frozen=True)
class TokenLogProbability:
    token: str
    log_probability: float


@dataclass(frozen=True)
class WeightsFingerprint:
    """The top next tokens of the fixed prompts, as one vLLM server answered them right after it started from the
    weights (or was found holding byte-identical ones): the reference every later start or swap of them is held to."""

    prompts: tuple[tuple[TokenLogProbability, ...], ...]
    server: str
    vllm: str


FINGERPRINT_FILE = "fingerprint.json"
FINGERPRINT_PROMPTS = (
    "theorem add_comm_example (a b : ℕ) : a + b = b + a := by\n",
    "x : ℝ\nh₀ : 3 * x + 2 = 11\n⊢ x = 3\n",
    "Lean 4 tactic proof:\n",
)
FINGERPRINT_TOKENS = 5
# Two servers of one bf16 checkpoint differ by kernel and batch order only, far below what a training phase moves.
# NOT YET MEASURED on the node (the report's node commands): widen it if two fresh starts of one merge disagree.
FINGERPRINT_TOLERANCE = 0.05


async def server_fingerprint(server_url: str, model: str) -> tuple[tuple[TokenLogProbability, ...], ...]:
    body = {
        "model": model,
        "prompt": list(FINGERPRINT_PROMPTS),
        "max_tokens": 1,
        "temperature": 1.0,
        "top_p": 1.0,
        "seed": 0,
        "logprobs": FINGERPRINT_TOKENS,
        "return_tokens_as_token_ids": True,
    }
    async with httpx.AsyncClient(timeout=120.0) as http:
        response = await http.post(f"{server_url.rstrip('/')}/completions", json=body)
        response.raise_for_status()
    choices = sorted(response.json()["choices"], key=lambda choice: choice["index"])
    return tuple(
        tuple(
            TokenLogProbability(token, log_probability)
            for token, log_probability in sorted(
                choice["logprobs"]["top_logprobs"][0].items(), key=lambda item: -item[1]
            )
        )
        for choice in choices
    )


def fingerprints_agree(
    reference: tuple[tuple[TokenLogProbability, ...], ...], observed: tuple[tuple[TokenLogProbability, ...], ...]
) -> bool:
    """The same most likely token for every prompt, and the log-probabilities of the tokens both list within the
    tolerance, all but one of the top tokens shared."""
    for expected, answered in zip(reference, observed, strict=True):
        expected_by_token = {entry.token: entry.log_probability for entry in expected}
        answered_by_token = {entry.token: entry.log_probability for entry in answered}
        shared = expected_by_token.keys() & answered_by_token.keys()
        if expected[0].token != answered[0].token or len(shared) < len(expected) - 1:
            return False
        if any(abs(expected_by_token[token] - answered_by_token[token]) > FINGERPRINT_TOLERANCE for token in shared):
            return False
    return True


def read_fingerprint(weights: Path) -> WeightsFingerprint | None:
    path = weights / FINGERPRINT_FILE
    if not path.exists():
        return None
    return from_json_object(WeightsFingerprint, json.loads(path.read_text(encoding="utf-8")))


async def check_fingerprints(
    run_config: RunConfig,
    assignments: Sequence[ServedWeightsOn],
    fresh: frozenset[str],
    vllm_version: str,
    log: Callable[[str], None],
) -> None:
    """Every server's answer to the fixed prompts against its weights' reference (<merge>/fingerprint.json). Without
    one, the first server just started from the weights (or found holding them) writes it; without such a server
    (swapped in place only), the servers of one weights directory are held to each other."""
    by_weights: dict[str, list[ServedWeightsOn]] = {}
    for assigned in assignments:
        by_weights.setdefault(assigned.weights, []).append(assigned)
    for weights, group in by_weights.items():
        model = (
            run_config.policy.model if group[0].server.url in run_config.policy.server_urls else run_config.value.model
        )
        answers = {assigned.server.name: await server_fingerprint(assigned.server.url, model) for assigned in group}
        reference = read_fingerprint(Path(weights))
        if reference is None:
            starter = next((assigned.server.name for assigned in group if assigned.server.name in fresh), None)
            if starter is None:
                starter = group[0].server.name
                log(f"No fingerprint of {weights} and no server started from it: its servers are held to {starter}")
            else:
                write_json_atomically(
                    Path(weights) / FINGERPRINT_FILE, WeightsFingerprint(answers[starter], starter, vllm_version)
                )
                log(f"Fingerprint of {weights} taken from {starter}, just started from it")
            reference = WeightsFingerprint(answers[starter], starter, vllm_version)
        for name, answer in answers.items():
            if not fingerprints_agree(reference.prompts, answer):
                raise ServersUnsoundError(
                    f"{name} answers the fixed prompts unlike {reference.server}, the reference of {weights}: it holds "
                    f"other weights ({answer} against {reference.prompts})"
                )


async def verify_served(
    run_config: RunConfig,
    log: Callable[[str], None],
    assignments: Sequence[ServedWeightsOn],
    fresh: frozenset[str],
) -> None:
    """Every server answers /health awake; each policy server one search request with usable blocks whose tokens
    decode to their text, each value server one state with most of its next-token mass on the bins; and every server
    the fixed prompts as its weights' reference does (`check_fingerprints`)."""
    servers = [assigned.server for assigned in assignments]
    awake = await asyncio.gather(*(answers_awake(server.url) for server in servers))
    down = [server.name for server, up in zip(servers, awake, strict=True) if not up]
    if down:
        raise ServersUnsoundError(f"Servers {down} do not answer awake after their weights were put on them.")
    for server in servers:
        if server.url in run_config.policy.server_urls:
            check = await check_policy_server(run_config.policy, server.url)
            if not (check.tokens_recorded and check.tokens_decode_to_text and check.usable_blocks):
                raise ServersUnsoundError(f"{server.name}: the policy's answer lacks what the search needs: {check}")
        if run_config.value.model and server.url in run_config.value.server_urls:
            value = dataclasses.replace(run_config.value, server_urls=(server.url,))
            async with open_value_estimator(value) as estimator:
                (probabilities,) = (await estimator.score_states([CHECK_GOALS])).states
            mass = sum(probabilities)
            if not (math.isfinite(mass) and mass >= MINIMUM_BIN_MASS):
                raise ServersUnsoundError(f"{server.name}: the value model puts {mass:.3f} on its bins")
    await check_fingerprints(run_config, assignments, fresh, package_version("vllm"), log)


# A trained value model answers with a bin token; a broken load spreads its mass elsewhere.
MINIMUM_BIN_MASS = 0.5


@dataclass(frozen=True)
class DeathRule:
    """When a server counts as dead: this many server errors in a row on its requests (it answers /health but not its
    requests), or every one of `health_probes` /health checks `probe_interval_seconds` apart failing (or finding it
    asleep): one slow /health under load is no death."""

    failing_requests: int = 5
    health_probes: int = 3
    probe_interval_seconds: float = 10.0


class ProbeServers:
    """The servers a probe run searches with (the ServerRecovery of `evaluation.ToleratedSearches`): a dead one
    (`DeathRule`) is started again from the run's merges by serve_model.sh (its pid file; no in-place swap), checked
    to report its merge as its root, verified, and the restart recorded as a new session."""

    def __init__(
        self,
        serving: ServingConfig,
        served: ServedWeights,
        checkpoint: ProbeCheckpoint,
        directory: Path,
        results: Path,
        verify: Verify,
        start: Callable[[Sequence[ServerStart]], Awaitable[None]],
        request_failures: RequestFailures,
        rule: DeathRule,
    ) -> None:
        self.serving = serving
        self.assignments = served.assignments(serving)
        self.checkpoint = checkpoint
        self.directory = directory
        self.results = results
        self.verify = verify
        self.start = start
        self.request_failures = request_failures
        self.rule = rule

    async def is_dead(self, server: ServerEndpoint) -> bool:
        if self.request_failures.streak(server.url) >= self.rule.failing_requests:
            return True
        for probe in range(self.rule.health_probes):
            if probe:
                await asyncio.sleep(self.rule.probe_interval_seconds)
            if await answers_awake(server.url):
                return False
        return True

    async def dead_servers(self) -> tuple[str, ...]:
        servers = [assigned.server for assigned in self.assignments]
        verdicts = await asyncio.gather(*(self.is_dead(server) for server in servers))
        return tuple(server.name for server, dead in zip(servers, verdicts, strict=True) if dead)

    async def restart(self, names: Sequence[str]) -> None:
        restarted = [assigned for assigned in self.assignments if assigned.server.name in names]
        starts = [
            ServerStart(assigned.server, weights_start_command(self.serving, assigned.server, assigned.weights))
            for assigned in restarted
        ]
        try:
            await self.start(starts)
            await check_started_from(restarted)
            await self.verify(restarted, frozenset(names))
        except (RuntimeError, httpx.HTTPError) as error:
            raise ServerRecoveryError(
                f"Restarting {list(names)} failed: {error} (logs: $LEAN_SEARCH_RUNS/servers/)"
            ) from error
        for assigned in restarted:
            self.request_failures.succeeded(assigned.server.url)
        serving = SessionServing(SwapMethod.RESTART, restarted=tuple(names))
        start_session(self.directory, self.checkpoint, self.results, serving)


def merges_in_use(servers_directory: Path, serving: ServingConfig) -> set[Path]:
    """The weights directories the servers' trusted processes started from, loaded or still loading: never deleted."""
    processes = [server_process(servers_directory, server.name) for server in serving.servers]
    return {process.weights.resolve() for process in processes if process is not None}


def remove_merges(directories: Sequence[Path], in_use: set[Path]) -> list[Path]:
    """The merges and any half-written ones beside them, except those a server runs from; returns those kept."""
    kept = []
    for directory in directories:
        if directory.resolve() in in_use:
            kept.append(directory)
            continue
        shutil.rmtree(directory, ignore_errors=True)
        shutil.rmtree(directory.with_name(directory.name + ".tmp"), ignore_errors=True)
    return kept


def keep_merges(directories: Sequence[Path]) -> None:
    for directory in directories:
        (directory / KEPT_MARKER).write_text("kept by --keep-merge\n", encoding="utf-8")


def remove_stale_merges(weights_root: Path, in_use: set[Path]) -> list[Path]:
    """Under the serving lock, nobody else merges: every merge not kept on purpose, and that no server runs from, is a
    dead run's."""
    stale = [
        directory
        for directory in sorted(weights_root.glob("*"))
        if directory.is_dir() and not (directory / KEPT_MARKER).exists() and directory.resolve() not in in_use
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


def start_session(directory: Path, checkpoint: ProbeCheckpoint, results: Path, serving: SessionServing) -> ProbeSession:
    count = len(results.read_text(encoding="utf-8").splitlines()) if results.exists() else 0
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    session = ProbeSession(
        f"{started} pid {os.getpid()}",
        count,
        checkpoint.policy_digest,
        checkpoint.value_digest,
        serving=serving,
        started_at=started,
    )
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


def dropped_statements(problems: Sequence[EvaluationProblem], results: Sequence[SearchResult]) -> tuple[str, ...]:
    """The problems without a result once the run ended: given up after repeated server failures."""
    finished = {result.problem_name for result in results}
    return tuple(problem.problem.name for problem in problems if problem.problem.name not in finished)


def retried_statements(failures: Sequence[SearchFailure]) -> tuple[RetriedStatement, ...]:
    counts: dict[str, int] = {}
    for failure in failures:
        counts[failure.problem_name] = max(counts.get(failure.problem_name, 0), failure.failures)
    return tuple(RetriedStatement(name, count) for name, count in counts.items())


def run_record(
    start: ProbeRunStart,
    environment: RunEnvironment,
    summary: EvaluationSummary,
    by_stratum: tuple[StratumStops, ...],
    max_share: float,
    sessions: Sequence[ProbeSession] = (),
    failures: Sequence[SearchFailure] = (),
    dropped: tuple[str, ...] = (),
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
        accepted=share < max_share and not dropped,
        sessions=tuple(sessions),
        swap_skipped=bool(sessions)
        and not any(session.serving.swapped or session.serving.restarted for session in sessions),
        server_restarts=tuple(
            ServerRestart(session.started_at, session.serving.restarted)
            for session in sessions
            if session.serving.restarted
        ),
        retried_statements=retried_statements(failures),
        dropped_statements=dropped,
    )
