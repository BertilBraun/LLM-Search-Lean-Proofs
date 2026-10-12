"""Async driver for one Lean REPL process (leanprover-community/repl) running in the pinned lean/ project."""

import asyncio
import collections
import contextlib
import json
import logging
import os
import re
import signal
import textwrap
import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from lean_search.lean.text import (
    FORBIDDEN_TOKENS,
    auxiliary_statement,
    executed_proof,
    find_forbidden_tokens,
    is_incomplete_input,
    join_tactics,
    lean_string_literal,
    normalize_goal,
    split_header,
    split_tactics,
    theorem_name,
    theorem_with_proof,
    wrap_tactic,
)

PROJECT_DIRECTORY = Path(__file__).resolve().parents[3] / "lean"
REPL_BINARY = Path(".lake/packages/REPL/.lake/build/bin/repl")
STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})

# Tactic-level `set_option maxHeartbeats N in` does not change the heartbeat limit in Lean 4.9, so we define our own.
# It bounds heartbeats, names auxiliary declarations and adds checks; see README.md for why soundness is unaffected.
BASE_ENVIRONMENT_DEFINITIONS = """open Lean Elab Tactic in
elab "lean_search_heartbeats " limit:num " => " tactics:tacticSeq : tactic => do
  let goals ← getGoals
  let previousMessages := (← Core.getMessageLog).unreported.size
  let declName := (← Term.getDeclName?).getD `lean_search_step
  withTheReader Term.Context (fun context => { context with declName? := declName }) <|
    Lean.Core.withCurrHeartbeats <|
      withTheReader Lean.Core.Context (fun context => { context with maxHeartbeats := limit.getNat * 1000 }) do
        evalTactic tactics
        pruneSolvedGoals
  for goal in goals do
    if (← instantiateMVars (mkMVar goal)).hasSorry then
      let messages := (← Core.getMessageLog).unreported.toList.drop previousMessages
      let errors ← (messages.filter (·.severity == .error)).mapM (·.data.toString)
      throwError (String.intercalate "\\n" (errors ++ ["lean_search: the tactic closed a goal with sorry"]))

open Lean Elab Tactic in
elab "lean_search_check_constants" : tactic => do
  let environment ← getEnv
  for goal in ← getGoals do
    goal.withContext do
      let mut expressions := #[← goal.getType]
      for declaration in ← getLCtx do
        expressions := (expressions.push declaration.type).append declaration.value?.toArray
      for expression in expressions do
        for constant in (← instantiateMVars expression).getUsedConstants do
          unless environment.contains constant do
            throwError m!"lean_search: unknown constant {constant}"

open Lean Elab Command in
elab "lean_search_single_command " text:str : command => do
  match Parser.runParserCategory (← getEnv) `command text.getString with
  | .ok _ => pure ()
  | .error message => throwError "lean_search: not exactly one command: {message}"
"""
CHECK_CONSTANTS_TACTIC = "lean_search_check_constants"
# Raised by Lean's runtime for arithmetic on values too large to represent: a function of the tactic's input alone.
DETERMINISTIC_PANICS = frozenset(
    {"Nat.pow exponent is too big", "Nat.shiftl exponent is too big", "Nat.shiftr exponent is too big"}
)
INTERNAL_PANIC_PREFIX = "INTERNAL PANIC: "
INTERNAL_PANIC_EXIT_CODE = 1

_HEARTBEAT_MESSAGES = ("(deterministic) timeout", "maximum number of heartbeats")
_STREAM_LIMIT_BYTES = 1 << 28
_PR_SET_PDEATHSIG = 1
_AXIOMS_PATTERN = re.compile(r"'(?P<name>.+)' depends on axioms: \[(?P<axioms>.*)\]", re.DOTALL)
_NO_AXIOMS_PATTERN = re.compile(r"'(?P<name>.+)' does not depend on any axioms")
_lake_environments: dict[Path, dict[str, str]] = {}
_lake_environment_tasks: dict[Path, asyncio.Task[dict[str, str]]] = {}
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeanReplConfig:
    project_directory: Path = PROJECT_DIRECTORY
    tactic_heartbeats: int = 200_000
    tactic_timeout_seconds: float = 20.0
    command_timeout_seconds: float = 300.0
    replay_timeout_seconds: float = 60.0
    max_anonymous_memory_bytes: int = 2 << 30
    max_proof_states: int = 8_000
    max_data_bytes: int | None = 6 << 30
    forbidden_tokens: frozenset[str] = FORBIDDEN_TOKENS


@dataclass(frozen=True)
class ProofState:
    header: str
    statement: str
    tactics: tuple[str, ...]
    goals: tuple[str, ...]
    repl_proof_state: int
    session: int
    tactic_heartbeats: tuple[int, ...] = ()

    @property
    def is_proved(self) -> bool:
        return not self.goals

    @property
    def goal_key(self) -> tuple[str, ...]:
        return tuple(normalize_goal(goal) for goal in self.goals)

    @property
    def proof(self) -> str:
        return join_tactics(self.tactics)

    @property
    def executed_proof(self) -> str:
        return executed_proof(self.tactics, self.tactic_heartbeats)


@dataclass(frozen=True)
class LeanError:
    message: str
    # The process died in a deterministic Lean runtime panic (see `DETERMINISTIC_PANICS`) and was restarted.
    panic: bool = False


@dataclass(frozen=True)
class LeanTimeout:
    message: str
    wall_clock: bool


class ReplFailureKind(StrEnum):
    CRASHED = "crashed"
    REPLAY_FAILED = "replay_failed"
    REPLAY_MISMATCH = "replay_mismatch"
    RESTART_FAILED = "restart_failed"


@dataclass(frozen=True)
class ReplFailure:
    kind: ReplFailureKind
    message: str


type Outcome = ProofState | LeanError | LeanTimeout | ReplFailure


@dataclass(frozen=True)
class TacticResult:
    outcome: Outcome
    elapsed_seconds: float


@dataclass(frozen=True)
class BlockResult:
    state: ProofState
    applied_tactics: tuple[str, ...]
    total_tactics: int
    failure: LeanError | LeanTimeout | ReplFailure | None
    elapsed_seconds: float


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    problems: tuple[str, ...]
    axioms: tuple[str, ...]
    elapsed_seconds: float
    plain_verified: bool | None = None


@dataclass(frozen=True)
class MemoryUsage:
    resident_bytes: int
    anonymous_bytes: int


class TacticLimits(NamedTuple):
    heartbeats: int
    timeout_seconds: float


class Severity(StrEnum):
    TRACE = "trace"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True)
class ReplMessage:
    severity: Severity
    text: str


@dataclass(frozen=True)
class ReplSorry:
    goal: str
    proof_state: int | None


@dataclass(frozen=True)
class CommandResponse:
    environment: int
    messages: tuple[ReplMessage, ...]
    sorries: tuple[ReplSorry, ...]

    def texts(self, severity: Severity) -> tuple[str, ...]:
        return tuple(message.text for message in self.messages if message.severity is severity)


@dataclass(frozen=True)
class TacticResponse:
    proof_state: int
    goals: tuple[str, ...]
    messages: tuple[ReplMessage, ...]
    sorries: tuple[ReplSorry, ...]

    def texts(self, severity: Severity) -> tuple[str, ...]:
        return tuple(message.text for message in self.messages if message.severity is severity)


@dataclass(frozen=True)
class ReplErrorResponse:
    message: str


@dataclass(frozen=True)
class _Verification:
    problems: tuple[str, ...]
    axioms: tuple[str, ...]


class ReplCrashedError(Exception):
    def __init__(self, message: str, panic: str | None = None) -> None:
        super().__init__(message)
        self.panic = panic


class ReplWallClockTimeoutError(Exception):
    pass


class ReplFailureError(Exception):
    def __init__(self, failure: ReplFailure) -> None:
        super().__init__(failure.message)
        self.failure = failure


class ReplClosedError(Exception):
    pass


def new_session_id() -> int:
    return uuid.uuid4().int


def _parse_messages(payload: dict[str, object]) -> tuple[ReplMessage, ...]:
    match payload.get("messages", []):
        case list(messages):
            return tuple(ReplMessage(Severity(message["severity"]), message["data"]) for message in messages)
        case unexpected:
            raise ValueError(f"Unexpected REPL messages: {unexpected!r}")


def _parse_sorries(payload: dict[str, object]) -> tuple[ReplSorry, ...]:
    match payload.get("sorries", []):
        case list(sorries):
            return tuple(ReplSorry(entry["goal"], entry.get("proofState")) for entry in sorries)
        case unexpected:
            raise ValueError(f"Unexpected REPL sorries: {unexpected!r}")


def parse_command_response(payload: dict[str, object]) -> CommandResponse | ReplErrorResponse:
    match payload:
        case {"env": int(environment)}:
            return CommandResponse(environment, _parse_messages(payload), _parse_sorries(payload))
        case {"message": str(message)}:
            return ReplErrorResponse(message)
        case _:
            raise ValueError(f"Unexpected REPL command response: {json.dumps(payload)[:2000]}")


def parse_tactic_response(payload: dict[str, object]) -> TacticResponse | ReplErrorResponse:
    match payload:
        case {"proofState": int(proof_state), "goals": list(goals)}:
            return TacticResponse(proof_state, tuple(goals), _parse_messages(payload), _parse_sorries(payload))
        case {"message": str(message)}:
            return ReplErrorResponse(message)
        case _:
            raise ValueError(f"Unexpected REPL tactic response: {json.dumps(payload)[:2000]}")


def parse_axioms(response: CommandResponse, name: str) -> tuple[str, ...] | None:
    match response.messages:
        case (ReplMessage(severity=Severity.INFO, text=text),):
            pass
        case _:
            return None
    if (match := _NO_AXIOMS_PATTERN.fullmatch(text)) and match["name"] == name:
        return ()
    if (match := _AXIOMS_PATTERN.fullmatch(text)) and match["name"] == name:
        return tuple(axiom.strip() for axiom in match["axioms"].split(","))
    return None


async def lake_environment(project_directory: Path) -> dict[str, str]:
    if project_directory in _lake_environments:
        return _lake_environments[project_directory]
    task = _lake_environment_tasks.get(project_directory)
    if task is None or task.done():
        task = asyncio.create_task(_read_lake_environment(project_directory))
        _lake_environment_tasks[project_directory] = task
    return await asyncio.shield(task)


async def _read_lake_environment(project_directory: Path) -> dict[str, str]:
    process = await asyncio.create_subprocess_exec(
        "lake",
        "env",
        "env",
        "-0",
        cwd=project_directory,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise RuntimeError(f"`lake env` failed in {project_directory}: {stderr.decode()}")
    entries = (entry.split("=", 1) for entry in stdout.decode().split("\0") if "=" in entry)
    environment = {key: value for key, value in entries}
    _lake_environments[project_directory] = environment
    return environment


def read_memory_usage(process_id: int) -> MemoryUsage:
    fields: dict[str, int] = {}
    try:
        with open(f"/proc/{process_id}/status") as status:
            for line in status:
                key, _, value = line.partition(":")
                if key in ("VmRSS", "RssAnon"):
                    fields[key] = int(value.split()[0]) * 1024
    except FileNotFoundError:  # reaped by the child watcher before asyncio recorded its return code
        pass
    # A crashed process that asyncio has not reaped yet is a zombie without memory lines.
    return MemoryUsage(resident_bytes=fields.get("VmRSS", 0), anonymous_bytes=fields.get("RssAnon", 0))


def _child_process_setup(max_data_bytes: int | None) -> Callable[[], None]:
    # Imported here because `resource` does not exist on Windows, where the package is still imported for tests.
    import ctypes
    import resource

    libc = ctypes.CDLL(None, use_errno=True)
    parent_process_id = os.getpid()

    def setup() -> None:
        if max_data_bytes is not None:
            resource.setrlimit(resource.RLIMIT_DATA, (max_data_bytes, max_data_bytes))
        libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)
        if os.getppid() != parent_process_id:
            os._exit(1)

    return setup


def _failure(message: str) -> LeanError | LeanTimeout:
    message = message.removeprefix("Lean error:\n")
    if any(marker in message for marker in _HEARTBEAT_MESSAGES):
        return LeanTimeout(message, wall_clock=False)
    return LeanError(message)


def deterministic_panic(stderr_lines: Sequence[str], return_code: int | None) -> str | None:
    """The panic message if the process exited through one of `DETERMINISTIC_PANICS`, else None."""
    lines = [line.strip() for line in stderr_lines if line.strip()]
    if return_code != INTERNAL_PANIC_EXIT_CODE or not lines or not lines[-1].startswith(INTERNAL_PANIC_PREFIX):
        return None
    message = lines[-1].removeprefix(INTERNAL_PANIC_PREFIX)
    return message if message in DETERMINISTIC_PANICS else None


def _panic_error(panic: str) -> LeanError:
    return LeanError(f"Lean panic: {panic}", panic=True)


class LeanRepl:
    """One REPL process. Operations are serialized; proof states survive restarts by transparent replay."""

    def __init__(self, config: LeanReplConfig | None = None) -> None:
        self.config = config or LeanReplConfig()
        self.proof_state_count = 0
        self.restart_count = 0
        self._process: asyncio.subprocess.Process | None = None
        self._must_restart = True
        self._closed = False
        self._session = new_session_id()
        self._lock = asyncio.Lock()
        self._import_environments: dict[str, int] = {}
        self._header_environments: dict[str, int] = {}
        self._base_environments: dict[str, int] = {}
        self._header_failures: dict[str, str] = {}
        self._replayed_states: dict[tuple[str, str, tuple[tuple[str, int], ...]], ProofState] = {}
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=40)
        self._stderr_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "LeanRepl":
        await self.start()
        return self

    async def __aexit__(self, *exception_information: object) -> None:
        await self.close()

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None and self._is_running() else None

    @property
    def needs_restart(self) -> bool:
        return not self._is_healthy()

    def memory_usage(self) -> MemoryUsage:
        assert self._process is not None and self._is_running()
        return read_memory_usage(self._process.pid)

    def exceeds_limits(self, fraction: float = 1.0) -> bool:
        if not self._is_running():
            return False
        return (
            self.proof_state_count >= fraction * self.config.max_proof_states
            or self.memory_usage().anonymous_bytes >= fraction * self.config.max_anonymous_memory_bytes
        )

    async def start(self) -> None:
        async with self._lock:
            if not self._is_healthy():
                await self._replace_process()

    async def restart(self) -> None:
        async with self._lock:
            await self._replace_process()

    async def close(self) -> None:
        """Final: later calls raise ReplClosedError instead of starting a process that nothing would close."""
        self._closed = True
        async with self._lock:
            await self._stop_process()

    async def load_header(self, header: str) -> None:
        async with self._lock:
            await self._ensure_healthy()
            await self._base_environment(header)

    async def start_proof(self, statement: str, header: str) -> TacticResult:
        async with self._lock:
            started = time.monotonic()
            outcome = await self._guarded(self._start_proof, statement, header)
            await self._recover()
            return TacticResult(outcome, time.monotonic() - started)

    async def apply_tactic(
        self, state: ProofState, tactic: str, heartbeats: int | None = None, timeout_seconds: float | None = None
    ) -> TacticResult:
        async with self._lock:
            started = time.monotonic()
            limits = self._limits(heartbeats, timeout_seconds)
            outcome = await self._guarded(self._apply_tactic, state, tactic, limits)
            await self._recover()
            return TacticResult(outcome, time.monotonic() - started)

    async def apply_block(
        self, state: ProofState, block: str, heartbeats: int | None = None, timeout_seconds: float | None = None
    ) -> BlockResult:
        async with self._lock:
            started = time.monotonic()
            limits = self._limits(heartbeats, timeout_seconds)
            tactics = split_tactics(block)
            current = state
            applied: list[str] = []
            failure: LeanError | LeanTimeout | ReplFailure | None = (
                None if tactics else LeanError("Empty tactic block.")
            )
            index = 0
            while index < len(tactics) and not current.is_proved:
                outcome = await self._guarded(self._apply_tactic, current, tactics[index], limits)
                match outcome:
                    case ProofState():
                        current = outcome
                        applied.append(tactics[index])
                        index += 1
                    case LeanError(message=message) if is_incomplete_input(message) and index + 1 < len(tactics):
                        tactics[index : index + 2] = [join_tactics(tactics[index : index + 2])]
                    case _:
                        failure = outcome
                        break
            await self._recover()
            return BlockResult(current, tuple(applied), len(tactics), failure, time.monotonic() - started)

    async def verify_proof(self, statement: str, proof: str, header: str) -> VerificationResult:
        async with self._lock:
            started = time.monotonic()
            verification = await self._guarded_verification(statement, header, proof, proof)
            await self._recover()
            return VerificationResult(
                not verification.problems, verification.problems, verification.axioms, time.monotonic() - started
            )

    async def verify_state(self, state: ProofState) -> VerificationResult:
        async with self._lock:
            started = time.monotonic()
            executed = await self._guarded_verification(
                state.statement, state.header, state.executed_proof, state.proof
            )
            plain = await self._guarded_verification(state.statement, state.header, state.proof, state.proof)
            await self._recover()
            return VerificationResult(
                not executed.problems,
                executed.problems,
                executed.axioms,
                time.monotonic() - started,
                plain_verified=not plain.problems,
            )

    async def _guarded[**Parameters](
        self,
        operation: Callable[Parameters, Awaitable[Outcome]],
        *arguments: Parameters.args,
        **keywords: Parameters.kwargs,
    ) -> Outcome:
        try:
            await self._ensure_healthy()
            return await operation(*arguments, **keywords)
        except ReplFailureError as error:
            return error.failure
        except ReplCrashedError as crash:
            return ReplFailure(ReplFailureKind.CRASHED, str(crash))

    async def _guarded_verification(self, statement: str, header: str, proof: str, user_text: str) -> _Verification:
        try:
            await self._ensure_healthy()
            return await self._verify(statement, header, proof, user_text)
        except (ReplFailureError, ReplCrashedError) as error:
            return _Verification((str(error),), ())

    async def _verify(self, statement: str, header: str, proof: str, user_text: str) -> _Verification:
        forbidden = find_forbidden_tokens(user_text, self.config.forbidden_tokens)
        if forbidden:
            return _Verification((f"Forbidden tokens: {', '.join(forbidden)}",), ())
        try:
            name = theorem_name(statement)
            theorem = theorem_with_proof(statement, proof)
            environment = await self._base_environment(header)
            timeout = self.config.command_timeout_seconds
            single = await self._command(
                f"lean_search_single_command {lean_string_literal(theorem)}", environment, timeout
            )
            problems = list(single.texts(Severity.ERROR))
            if problems:
                return _Verification(tuple(problems), ())
            response = await self._command(theorem, environment, timeout)
            problems = list(response.texts(Severity.ERROR))
            if response.sorries:
                problems.append("The proof contains sorry.")
            problems += [text for text in response.texts(Severity.WARNING) if "declaration uses 'sorry'" in text]
            if problems:
                return _Verification(tuple(problems), ())
            axioms = parse_axioms(
                await self._command(f"#print axioms _root_.{name}", response.environment, timeout), name
            )
        except ReplWallClockTimeoutError:
            return _Verification(("Verification exceeded the wall-clock limit.",), ())
        except ValueError as error:
            return _Verification((str(error),), ())
        if axioms is None:
            return _Verification(("The axioms of the theorem were not reported.",), ())
        nonstandard = sorted(set(axioms) - STANDARD_AXIOMS)
        if nonstandard:
            return _Verification((f"Nonstandard axioms: {', '.join(nonstandard)}",), axioms)
        return _Verification((), axioms)

    async def _start_proof(self, statement: str, header: str) -> ProofState | LeanError | LeanTimeout:
        try:
            environment = await self._base_environment(header)
            root = await self._elaborate_statement(statement, header, environment)
            if not isinstance(root, ProofState) or await self._constants_are_known(root):
                return root
            # The REPL gives the root the environment before the statement, which lacks the statement's matchers.
            auxiliary_environment = await self._auxiliary_environment(statement, environment)
            if auxiliary_environment is None:
                return root
            repaired = await self._elaborate_statement(statement, header, auxiliary_environment)
            if isinstance(repaired, ProofState) and await self._constants_are_known(repaired):
                return repaired
            return root
        except ReplWallClockTimeoutError:
            return LeanTimeout("Statement elaboration exceeded the wall-clock limit.", wall_clock=True)
        except ValueError as error:
            return LeanError(str(error))
        except ReplCrashedError as crash:
            if crash.panic is None:
                raise
            return _panic_error(crash.panic)

    async def _elaborate_statement(
        self, statement: str, header: str, environment: int
    ) -> ProofState | LeanError | LeanTimeout:
        command = theorem_with_proof(statement, "sorry")
        response = await self._command(command, environment, self.config.command_timeout_seconds)
        errors = response.texts(Severity.ERROR)
        if errors:
            return _failure("\n".join(errors))
        if len(response.sorries) != 1 or response.sorries[0].proof_state is None:
            return LeanError(f"Expected exactly one sorry in the statement, found {len(response.sorries)}.")
        proof_state = response.sorries[0].proof_state
        self.proof_state_count = max(self.proof_state_count, proof_state + 1)
        return ProofState(header, statement, (), (response.sorries[0].goal,), proof_state, self._session)

    async def _constants_are_known(self, state: ProofState) -> bool:
        response = await self._tactic(
            CHECK_CONSTANTS_TACTIC, state.repl_proof_state, self.config.tactic_timeout_seconds
        )
        match response:
            case ReplErrorResponse():
                return False
            case TacticResponse():
                self.proof_state_count = max(self.proof_state_count, response.proof_state + 1)
                return not response.texts(Severity.ERROR)

    async def _auxiliary_environment(self, statement: str, environment: int) -> int | None:
        command = auxiliary_statement(statement)
        if command is None:
            return None
        response = await self._command(command, environment, self.config.command_timeout_seconds)
        return None if response.texts(Severity.ERROR) else response.environment

    def _limits(self, heartbeats: int | None, timeout_seconds: float | None) -> TacticLimits:
        return TacticLimits(
            self.config.tactic_heartbeats if heartbeats is None else heartbeats,
            self.config.tactic_timeout_seconds if timeout_seconds is None else timeout_seconds,
        )

    async def _apply_tactic(self, state: ProofState, tactic: str, limits: TacticLimits) -> Outcome:
        tactic = textwrap.dedent(tactic).strip("\n").rstrip()
        if not tactic.strip():
            return LeanError("Empty tactic.")
        forbidden = find_forbidden_tokens(tactic, self.config.forbidden_tokens)
        if forbidden:
            return LeanError(f"Forbidden tokens: {', '.join(forbidden)}")
        live_state = await self._live_state(state)
        try:
            return await self._run_tactic(live_state, tactic, limits)
        except ReplWallClockTimeoutError:
            return LeanTimeout("The tactic exceeded the wall-clock limit.", wall_clock=True)
        except ReplCrashedError as crash:
            if crash.panic is None:
                raise
            return _panic_error(crash.panic)

    async def _run_tactic(
        self, state: ProofState, tactic: str, limits: TacticLimits
    ) -> ProofState | LeanError | LeanTimeout:
        response = await self._tactic(
            wrap_tactic(tactic, limits.heartbeats), state.repl_proof_state, limits.timeout_seconds
        )
        match response:
            case ReplErrorResponse(message=message):
                return _failure(message)
            case TacticResponse():
                self.proof_state_count = max(self.proof_state_count, response.proof_state + 1)
        errors = response.texts(Severity.ERROR)
        if errors:
            return _failure("\n".join(errors))
        if response.sorries:
            return LeanError("The tactic introduced sorry.")
        return ProofState(
            state.header,
            state.statement,
            (*state.tactics, tactic),
            response.goals,
            response.proof_state,
            self._session,
            (*state.tactic_heartbeats, limits.heartbeats),
        )

    async def _live_state(self, state: ProofState) -> ProofState:
        if state.session == self._session:
            return state
        steps = tuple(zip(state.tactics, state.tactic_heartbeats, strict=True))
        replayed = await self._replay(state.header, state.statement, steps)
        if replayed.goal_key != state.goal_key:
            raise ReplFailureError(
                ReplFailure(
                    ReplFailureKind.REPLAY_MISMATCH,
                    f"Replaying the proof state gave different goals: {replayed.goals} instead of {state.goals}.",
                )
            )
        return replayed

    async def _replay(self, header: str, statement: str, steps: tuple[tuple[str, int], ...]) -> ProofState:
        key = (header, statement, steps)
        if key in self._replayed_states:
            return self._replayed_states[key]
        try:
            if steps:
                parent = await self._replay(header, statement, steps[:-1])
                tactic, heartbeats = steps[-1]
                limits = TacticLimits(heartbeats, self.config.replay_timeout_seconds)
                outcome = await self._run_tactic(parent, tactic, limits)
            else:
                outcome = await self._start_proof(statement, header)
        except ReplWallClockTimeoutError as timeout:
            raise ReplFailureError(
                ReplFailure(ReplFailureKind.REPLAY_FAILED, "Replaying the proof state exceeded the wall-clock limit.")
            ) from timeout
        match outcome:
            case ProofState():
                self._replayed_states[key] = outcome
                return outcome
            case LeanError(message=message) | LeanTimeout(message=message):
                raise ReplFailureError(
                    ReplFailure(ReplFailureKind.REPLAY_FAILED, f"Replaying the proof state failed: {message}")
                )

    async def _import_environment(self, imports: str) -> int:
        # Every import builds its own copy of the imported environment (~4 GiB for Mathlib), so headers share one.
        if imports not in self._import_environments:
            payload = await self._request({"cmd": imports}, self.config.command_timeout_seconds)
            match self._parse(parse_command_response, payload):
                case ReplErrorResponse(message=message):
                    raise ValueError(f"The header does not elaborate: {message}")
                case CommandResponse() as response if response.texts(Severity.ERROR):
                    raise ValueError(f"The header does not elaborate: {response.texts(Severity.ERROR)}")
                case CommandResponse() as response:
                    self._import_environments[imports] = response.environment
        return self._import_environments[imports]

    async def _header_environment(self, header: str) -> int:
        if header not in self._header_environments:
            imports, commands = split_header(header)
            environment = await self._import_environment(imports)
            if commands.strip():
                response = await self._command(commands, environment, self.config.command_timeout_seconds)
                if response.texts(Severity.ERROR):
                    raise ValueError(f"The header does not elaborate: {response.texts(Severity.ERROR)}")
                environment = response.environment
            self._header_environments[header] = environment
        return self._header_environments[header]

    async def _base_environment(self, header: str) -> int:
        if header in self._header_failures:
            raise ValueError(self._header_failures[header])
        if header not in self._base_environments:
            try:
                environment = await self._header_environment(header)
                response = await self._command(
                    BASE_ENVIRONMENT_DEFINITIONS, environment, self.config.command_timeout_seconds
                )
                if response.texts(Severity.ERROR):
                    raise ValueError(
                        "The header does not elaborate with the search wrapper, which needs Lean itself "
                        f"(`import Mathlib` or `import Lean`): {response.texts(Severity.ERROR)[0][:500]}"
                    )
            except ValueError as error:
                self._header_failures[header] = str(error)
                raise
            self._base_environments[header] = response.environment
        return self._base_environments[header]

    async def _command(self, command: str, environment: int, timeout_seconds: float) -> CommandResponse:
        payload = await self._request({"cmd": command, "env": environment}, timeout_seconds)
        match self._parse(parse_command_response, payload):
            case ReplErrorResponse(message=message):
                self._abandon_process()
                raise ReplCrashedError(f"The Lean REPL rejected a command: {message}")
            case CommandResponse() as response:
                return response

    async def _tactic(
        self, tactic: str, proof_state: int, timeout_seconds: float
    ) -> TacticResponse | ReplErrorResponse:
        payload = await self._request({"tactic": tactic, "proofState": proof_state}, timeout_seconds)
        return self._parse(parse_tactic_response, payload)

    def _parse[Response](self, parser: Callable[[dict[str, object]], Response], payload: dict[str, object]) -> Response:
        try:
            return parser(payload)
        except (ValueError, KeyError, TypeError) as error:
            self._abandon_process()
            raise ReplCrashedError(f"The Lean REPL sent an unexpected response: {error}") from error

    async def _ensure_healthy(self) -> None:
        if self._is_healthy() and not self.exceeds_limits():
            return
        try:
            await self._replace_process()
        except ReplClosedError:
            raise
        except Exception as error:
            logger.exception("Starting the Lean REPL failed")
            raise ReplFailureError(
                ReplFailure(ReplFailureKind.RESTART_FAILED, f"Starting the Lean REPL failed: {error!r}")
            ) from error

    async def _recover(self) -> None:
        if self._is_healthy() or self._closed:
            return
        headers = list(self._base_environments)
        try:
            await self._replace_process()
            for header in headers:
                await self._base_environment(header)
        except Exception:
            logger.exception("Restarting the Lean REPL failed; the next request retries")

    def _is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def _is_healthy(self) -> bool:
        return self._is_running() and not self._must_restart

    async def _replace_process(self) -> None:
        await self._stop_process()
        if self._closed:
            raise ReplClosedError("The Lean REPL was closed.")
        await self._start_process()

    async def _start_process(self) -> None:
        environment = {**os.environ, **await lake_environment(self.config.project_directory)}
        # This REPL version never flushes stdout, so force line buffering.
        process = await asyncio.create_subprocess_exec(
            "stdbuf",
            "-oL",
            self.config.project_directory / REPL_BINARY,
            cwd=self.config.project_directory,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT_BYTES,
            preexec_fn=_child_process_setup(self.config.max_data_bytes),
        )
        if self._process is not None:
            self.restart_count += 1
        self._process = process
        self._session = new_session_id()
        self.proof_state_count = 0
        self._import_environments.clear()
        self._header_environments.clear()
        self._base_environments.clear()
        self._header_failures.clear()
        self._replayed_states.clear()
        self._stderr_tail = collections.deque(maxlen=40)
        self._stderr_task = asyncio.create_task(self._drain_stderr(process, self._stderr_tail))
        self._must_restart = False

    async def _stop_process(self) -> None:
        self._must_restart = True
        if self._process is None:
            return
        if self._is_running():
            assert self._process.stdin is not None
            self._process.stdin.close()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._process.wait(), 10)
        await self._kill_process()

    def _abandon_process(self) -> None:
        self._must_restart = True
        if self._process is not None and self._is_running():
            with contextlib.suppress(ProcessLookupError):
                self._process.kill()

    async def _kill_process(self) -> None:
        assert self._process is not None
        self._abandon_process()
        await self._process.wait()
        if self._stderr_task is not None:
            await self._stderr_task

    @staticmethod
    async def _drain_stderr(process: asyncio.subprocess.Process, tail: collections.deque[str]) -> None:
        assert process.stderr is not None
        async for line in process.stderr:
            tail.append(line.decode(errors="replace"))

    async def _request(self, payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
        if not self._is_healthy():
            raise ReplCrashedError("The Lean REPL process is not running.")
        process = self._process
        assert process is not None and process.stdin is not None
        try:
            process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n\n").encode())
            await process.stdin.drain()
            return await asyncio.wait_for(self._read_response(process), timeout_seconds)
        except TimeoutError as timeout:
            await self._kill_process()
            raise ReplWallClockTimeoutError from timeout
        except (OSError, ValueError, ReplCrashedError) as crash:
            await self._kill_process()
            raise ReplCrashedError(
                f"The Lean REPL process died: {''.join(self._stderr_tail)[-2000:]}",
                deterministic_panic(self._stderr_tail, process.returncode),
            ) from crash
        except BaseException:
            # Cancelled mid-request: the REPL would answer later and desynchronize every following request.
            self._abandon_process()
            raise

    @staticmethod
    async def _read_response(process: asyncio.subprocess.Process) -> dict[str, object]:
        assert process.stdout is not None
        lines: list[bytes] = []
        while True:
            line = await process.stdout.readline()
            if not line:
                raise ReplCrashedError("The Lean REPL closed its output.")
            if line.strip():
                lines.append(line)
            elif lines:
                return json.loads(b"".join(lines))
