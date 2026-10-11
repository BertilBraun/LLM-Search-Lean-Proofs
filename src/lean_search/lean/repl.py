"""Async driver for one Lean REPL process (leanprover-community/repl) running in the pinned lean/ project."""

import asyncio
import collections
import itertools
import json
import os
import textwrap
import time
from dataclasses import dataclass
from pathlib import Path
from typing import NamedTuple

from lean_search.lean.text import (
    find_forbidden_tokens,
    indent,
    join_tactics,
    normalize_goal,
    split_tactics,
    theorem_name,
    theorem_with_proof,
)

PROJECT_DIRECTORY = Path(__file__).resolve().parents[3] / "lean"
REPL_BINARY = Path(".lake/packages/REPL/.lake/build/bin/repl")
STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})

# Tactic-level `set_option maxHeartbeats N in` does not change the heartbeat limit in Lean 4.9, so we define our own.
HEARTBEAT_TACTIC_DEFINITION = """open Lean Elab Tactic in
elab "lean_search_heartbeats " limit:num " => " tactics:tacticSeq : tactic =>
  Lean.Core.withCurrHeartbeats <|
    withTheReader Lean.Core.Context (fun context => { context with maxHeartbeats := limit.getNat * 1000 }) do
      evalTactic tactics
      pruneSolvedGoals"""

_HEARTBEAT_MESSAGES = ("(deterministic) timeout", "maximum number of heartbeats")
_STREAM_LIMIT_BYTES = 1 << 28
_session_counter = itertools.count()
_lake_environments: dict[Path, dict[str, str]] = {}


@dataclass(frozen=True)
class LeanReplConfig:
    project_directory: Path = PROJECT_DIRECTORY
    tactic_heartbeats: int = 200_000
    tactic_timeout_seconds: float = 20.0
    command_timeout_seconds: float = 300.0
    max_anonymous_memory_bytes: int = 2 << 30
    max_proof_states: int = 8_000


@dataclass(frozen=True)
class ProofState:
    header: str
    statement: str
    tactics: tuple[str, ...]
    goals: tuple[str, ...]
    repl_proof_state: int
    session: int

    @property
    def is_proved(self) -> bool:
        return not self.goals

    @property
    def goal_key(self) -> tuple[str, ...]:
        return tuple(normalize_goal(goal) for goal in self.goals)

    @property
    def proof(self) -> str:
        return join_tactics(self.tactics)


@dataclass(frozen=True)
class LeanError:
    message: str


@dataclass(frozen=True)
class LeanTimeout:
    message: str
    wall_clock: bool


type Outcome = ProofState | LeanError | LeanTimeout


@dataclass(frozen=True)
class TacticResult:
    outcome: Outcome
    elapsed_seconds: float


@dataclass(frozen=True)
class BlockResult:
    state: ProofState
    applied_tactics: tuple[str, ...]
    total_tactics: int
    failure: LeanError | LeanTimeout | None
    elapsed_seconds: float


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    problems: tuple[str, ...]
    axioms: tuple[str, ...]
    elapsed_seconds: float


@dataclass(frozen=True)
class MemoryUsage:
    resident_bytes: int
    anonymous_bytes: int


class TacticLimits(NamedTuple):
    heartbeats: int
    timeout_seconds: float


class ReplCrashedError(Exception):
    pass


class ReplWallClockTimeoutError(Exception):
    pass


async def lake_environment(project_directory: Path) -> dict[str, str]:
    if project_directory not in _lake_environments:
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
        _lake_environments[project_directory] = {key: value for key, value in entries}
    return _lake_environments[project_directory]


def read_memory_usage(process_id: int) -> MemoryUsage:
    fields: dict[str, int] = {}
    with open(f"/proc/{process_id}/status") as status:
        for line in status:
            key, _, value = line.partition(":")
            if key in ("VmRSS", "RssAnon"):
                fields[key] = int(value.split()[0]) * 1024
    # A crashed process that asyncio has not reaped yet is a zombie without memory lines.
    return MemoryUsage(resident_bytes=fields.get("VmRSS", 0), anonymous_bytes=fields.get("RssAnon", 0))


def _messages(response: dict, severity: str) -> list[str]:
    return [message["data"] for message in response.get("messages", []) if message["severity"] == severity]


def _failure(message: str) -> LeanError | LeanTimeout:
    message = message.removeprefix("Lean error:\n")
    if any(marker in message for marker in _HEARTBEAT_MESSAGES):
        return LeanTimeout(message, wall_clock=False)
    return LeanError(message)


def _parse_axioms(info_messages: list[str], name: str) -> tuple[str, ...] | None:
    for message in info_messages:
        if message.startswith(f"'{name}' does not depend on any axioms"):
            return ()
        prefix = f"'{name}' depends on axioms: ["
        if message.startswith(prefix):
            return tuple(axiom.strip() for axiom in message.removeprefix(prefix).rstrip().rstrip("]").split(","))
    return None


class LeanRepl:
    """One REPL process. Operations are serialized; proof states survive restarts by transparent replay."""

    def __init__(self, config: LeanReplConfig | None = None) -> None:
        self.config = config or LeanReplConfig()
        self.proof_state_count = 0
        self.restart_count = 0
        self._process: asyncio.subprocess.Process | None = None
        self._session = -1
        self._lock = asyncio.Lock()
        self._header_environments: dict[str, int] = {}
        self._tactic_environments: dict[str, int] = {}
        self._replayed_states: dict[tuple[str, str, tuple[str, ...]], ProofState] = {}
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=40)
        self._stderr_task: asyncio.Task[None] | None = None

    async def __aenter__(self) -> "LeanRepl":
        await self.start()
        return self

    async def __aexit__(self, *exception_information: object) -> None:
        await self.close()

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._is_running() else None

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
            if not self._is_running():
                await self._start_process()

    async def restart(self) -> None:
        async with self._lock:
            await self._stop_process()
            await self._start_process()

    async def close(self) -> None:
        async with self._lock:
            await self._stop_process()

    async def load_header(self, header: str) -> None:
        async with self._lock:
            await self._ensure_healthy()
            await self._tactic_environment(header)

    async def start_proof(self, statement: str, header: str) -> TacticResult:
        async with self._lock:
            started = time.monotonic()
            await self._ensure_healthy()
            outcome = await self._start_proof(statement, header)
            await self._recover_if_dead()
            return TacticResult(outcome, time.monotonic() - started)

    async def apply_tactic(
        self, state: ProofState, tactic: str, heartbeats: int | None = None, timeout_seconds: float | None = None
    ) -> TacticResult:
        async with self._lock:
            started = time.monotonic()
            await self._ensure_healthy()
            outcome = await self._apply_tactic(state, tactic, self._limits(heartbeats, timeout_seconds))
            await self._recover_if_dead()
            return TacticResult(outcome, time.monotonic() - started)

    async def apply_block(
        self, state: ProofState, block: str, heartbeats: int | None = None, timeout_seconds: float | None = None
    ) -> BlockResult:
        async with self._lock:
            started = time.monotonic()
            await self._ensure_healthy()
            limits = self._limits(heartbeats, timeout_seconds)
            tactics = split_tactics(block)
            current = state
            applied: list[str] = []
            failure: LeanError | LeanTimeout | None = None if tactics else LeanError("Empty tactic block.")
            for tactic in tactics:
                if current.is_proved:
                    break
                outcome = await self._apply_tactic(current, tactic, limits)
                if not isinstance(outcome, ProofState):
                    failure = outcome
                    break
                current = outcome
                applied.append(tactic)
            await self._recover_if_dead()
            return BlockResult(current, tuple(applied), len(tactics), failure, time.monotonic() - started)

    async def verify_proof(self, statement: str, proof: str, header: str) -> VerificationResult:
        async with self._lock:
            started = time.monotonic()
            await self._ensure_healthy()
            problems, axioms = await self._verify_proof(statement, proof, header)
            await self._recover_if_dead()
            return VerificationResult(not problems, tuple(problems), axioms, time.monotonic() - started)

    async def _verify_proof(self, statement: str, proof: str, header: str) -> tuple[list[str], tuple[str, ...]]:
        forbidden = find_forbidden_tokens(proof)
        if forbidden:
            return [f"Forbidden tokens: {', '.join(forbidden)}"], ()
        name = theorem_name(statement)
        command = theorem_with_proof(statement, proof) + f"\n\n#print axioms {name}"
        try:
            environment = await self._header_environment(header)
            response = await self._request({"cmd": command, "env": environment}, self.config.command_timeout_seconds)
        except ReplWallClockTimeoutError:
            return ["Verification exceeded the wall-clock limit."], ()
        except ReplCrashedError as crash:
            return [str(crash)], ()
        problems = _messages(response, "error")
        if response.get("sorries"):
            problems.append("The proof contains sorry.")
        problems += [warning for warning in _messages(response, "warning") if "declaration uses 'sorry'" in warning]
        axioms = _parse_axioms(_messages(response, "info"), name)
        if axioms is None:
            problems.append("The axioms of the theorem were not reported.")
            return problems, ()
        nonstandard = sorted(set(axioms) - STANDARD_AXIOMS)
        if nonstandard:
            problems.append(f"Nonstandard axioms: {', '.join(nonstandard)}")
        return problems, axioms

    async def _start_proof(self, statement: str, header: str) -> Outcome:
        try:
            environment = await self._tactic_environment(header)
            command = theorem_with_proof(statement, "sorry")
            response = await self._request({"cmd": command, "env": environment}, self.config.command_timeout_seconds)
        except ReplWallClockTimeoutError:
            return LeanTimeout("Statement elaboration exceeded the wall-clock limit.", wall_clock=True)
        except ReplCrashedError as crash:
            return LeanError(str(crash))
        errors = _messages(response, "error")
        if errors:
            return _failure("\n".join(errors))
        sorries = response.get("sorries", [])
        if len(sorries) != 1:
            return LeanError(f"Expected exactly one sorry in the statement, found {len(sorries)}.")
        proof_state = sorries[0]["proofState"]
        self.proof_state_count = max(self.proof_state_count, proof_state + 1)
        return ProofState(header, statement, (), (sorries[0]["goal"],), proof_state, self._session)

    def _limits(self, heartbeats: int | None, timeout_seconds: float | None) -> TacticLimits:
        return TacticLimits(
            self.config.tactic_heartbeats if heartbeats is None else heartbeats,
            self.config.tactic_timeout_seconds if timeout_seconds is None else timeout_seconds,
        )

    async def _apply_tactic(self, state: ProofState, tactic: str, limits: TacticLimits) -> Outcome:
        tactic = textwrap.dedent(tactic).strip("\n").rstrip()
        if not tactic.strip():
            return LeanError("Empty tactic.")
        forbidden = find_forbidden_tokens(tactic)
        if forbidden:
            return LeanError(f"Forbidden tokens: {', '.join(forbidden)}")
        live_state = await self._live_state(state)
        if not isinstance(live_state, ProofState):
            return live_state
        return await self._run_tactic(live_state, tactic, limits)

    async def _run_tactic(self, state: ProofState, tactic: str, limits: TacticLimits) -> Outcome:
        wrapped = f"lean_search_heartbeats {limits.heartbeats} =>\n{indent(tactic, 2)}"
        try:
            response = await self._request(
                {"tactic": wrapped, "proofState": state.repl_proof_state}, limits.timeout_seconds
            )
        except ReplWallClockTimeoutError:
            return LeanTimeout("The tactic exceeded the wall-clock limit.", wall_clock=True)
        except ReplCrashedError as crash:
            return LeanError(str(crash))
        if "proofState" not in response:
            return _failure(response.get("message", json.dumps(response)))
        self.proof_state_count = max(self.proof_state_count, response["proofState"] + 1)
        errors = _messages(response, "error")
        if errors:
            return _failure("\n".join(errors))
        if response.get("sorries"):
            return LeanError("The tactic introduced sorry.")
        goals = tuple(response["goals"])
        return ProofState(
            state.header, state.statement, (*state.tactics, tactic), goals, response["proofState"], self._session
        )

    async def _live_state(self, state: ProofState) -> Outcome:
        if state.session == self._session:
            return state
        key = (state.header, state.statement, state.tactics)
        if key in self._replayed_states:
            return self._replayed_states[key]
        if state.tactics:
            parent = ProofState(state.header, state.statement, state.tactics[:-1], (), -1, -1)
            live_parent = await self._live_state(parent)
            if not isinstance(live_parent, ProofState):
                return live_parent
            # The tactic succeeded before under some limit, so the replay only keeps the wall-clock backstop.
            replay_limits = TacticLimits(heartbeats=0, timeout_seconds=self.config.command_timeout_seconds)
            outcome = await self._run_tactic(live_parent, state.tactics[-1], replay_limits)
        else:
            outcome = await self._start_proof(state.statement, state.header)
        if not isinstance(outcome, ProofState):
            return LeanError(f"Replaying the proof state failed: {outcome.message}")
        self._replayed_states[key] = outcome
        return outcome

    async def _header_environment(self, header: str) -> int:
        if header not in self._header_environments:
            response = await self._request({"cmd": header}, self.config.command_timeout_seconds)
            errors = _messages(response, "error")
            if errors:
                raise ValueError(f"The header does not elaborate: {errors}")
            self._header_environments[header] = response["env"]
        return self._header_environments[header]

    async def _tactic_environment(self, header: str) -> int:
        if header not in self._tactic_environments:
            environment = await self._header_environment(header)
            response = await self._request(
                {"cmd": HEARTBEAT_TACTIC_DEFINITION, "env": environment}, self.config.command_timeout_seconds
            )
            errors = _messages(response, "error")
            assert not errors, errors
            self._tactic_environments[header] = response["env"]
        return self._tactic_environments[header]

    async def _ensure_healthy(self) -> None:
        if not self._is_running():
            await self._start_process()
        elif self.exceeds_limits():
            await self._stop_process()
            await self._start_process()

    async def _recover_if_dead(self) -> None:
        if self._is_running():
            return
        headers = list(self._tactic_environments)
        await self._start_process()
        for header in headers:
            await self._tactic_environment(header)

    def _is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def _start_process(self) -> None:
        environment = {**os.environ, **await lake_environment(self.config.project_directory)}
        # This REPL version never flushes stdout, so force line buffering.
        self._process = await asyncio.create_subprocess_exec(
            "stdbuf",
            "-oL",
            self.config.project_directory / REPL_BINARY,
            cwd=self.config.project_directory,
            env=environment,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=_STREAM_LIMIT_BYTES,
        )
        if self._session >= 0:
            self.restart_count += 1
        self._session = next(_session_counter)
        self.proof_state_count = 0
        self._header_environments.clear()
        self._tactic_environments.clear()
        self._replayed_states.clear()
        self._stderr_tail.clear()
        self._stderr_task = asyncio.create_task(self._drain_stderr(self._process))

    async def _stop_process(self) -> None:
        if self._process is None:
            return
        if self._is_running():
            assert self._process.stdin is not None
            self._process.stdin.close()
            try:
                await asyncio.wait_for(self._process.wait(), 10)
            except TimeoutError:
                await self._kill_process()
        await self._kill_process()

    async def _kill_process(self) -> None:
        assert self._process is not None
        if self._is_running():
            self._process.kill()
        await self._process.wait()
        if self._stderr_task is not None:
            await self._stderr_task

    async def _drain_stderr(self, process: asyncio.subprocess.Process) -> None:
        assert process.stderr is not None
        async for line in process.stderr:
            self._stderr_tail.append(line.decode(errors="replace"))

    async def _request(self, payload: dict[str, object], timeout_seconds: float) -> dict:
        if not self._is_running():
            raise ReplCrashedError("The Lean REPL process is not running.")
        assert self._process is not None and self._process.stdin is not None
        self._process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n\n").encode())
        try:
            await self._process.stdin.drain()
            return await asyncio.wait_for(self._read_response(), timeout_seconds)
        except TimeoutError as timeout:
            await self._kill_process()
            raise ReplWallClockTimeoutError from timeout
        except (ConnectionError, ReplCrashedError) as crash:
            await self._kill_process()
            raise ReplCrashedError(f"The Lean REPL process died: {''.join(self._stderr_tail)[-2000:]}") from crash

    async def _read_response(self) -> dict:
        assert self._process is not None and self._process.stdout is not None
        lines: list[bytes] = []
        while True:
            line = await self._process.stdout.readline()
            if not line:
                raise ReplCrashedError
            if line.strip():
                lines.append(line)
            elif lines:
                return json.loads(b"".join(lines))
