"""serve_model.sh's records of a running server under $LEAN_SEARCH_RUNS/servers/: <name>.pid (the process group of
its vLLM, deployment/server_pid.sh), trusted only when that process is a vLLM started for the server about when the
file was written (a pid reused after a reboot or by another job is not); <name>.swapped, written before the tooling
swaps or sleeps the server in place and removed by serve_model.sh at a start."""

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# A pid file is written right after its process starts.
START_SLACK_SECONDS = 60.0


def pid_file(servers_directory: Path, name: str) -> Path:
    return servers_directory / f"{name}.pid"


def swapped_marker(servers_directory: Path, name: str) -> Path:
    return servers_directory / f"{name}.swapped"


def mark_swapped(servers_directory: Path, name: str) -> None:
    """Before an in-place sleep or swap: from here on the server may hold other weights than it started from."""
    servers_directory.mkdir(parents=True, exist_ok=True)
    swapped_marker(servers_directory, name).write_text("swapped or slept in place since its start\n", encoding="utf-8")


def command_line(process_id: int) -> list[str] | None:
    try:
        raw = Path(f"/proc/{process_id}/cmdline").read_bytes()
    except OSError:
        return None
    return [argument.decode(errors="replace") for argument in raw.split(b"\0") if argument]


def process_start_time(process_id: int) -> float | None:
    """Seconds since the epoch."""
    try:
        stat = Path(f"/proc/{process_id}/stat").read_text(encoding="utf-8")
        boot = Path("/proc/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    # The fields after the command name, which may hold spaces; the start time is the 22nd field of the line.
    start_ticks = int(stat.rsplit(")", 1)[1].split()[19])
    boot_time = next(int(line.split()[1]) for line in boot.splitlines() if line.startswith("btime"))
    return boot_time + start_ticks / os.sysconf("SC_CLK_TCK")


def is_server_command(arguments: Sequence[str], name: str) -> bool:
    """`vllm serve <weights> --served-model-name <name> ...` as serve_model.sh starts it."""
    names = [arguments[index + 1] for index in range(len(arguments) - 1) if arguments[index] == "--served-model-name"]
    return any(Path(argument).name == "vllm" for argument in arguments[:2]) and "serve" in arguments and name in names


@dataclass(frozen=True)
class ServerProcess:
    process_id: int
    arguments: tuple[str, ...]

    @property
    def weights(self) -> Path:
        """The weights directory it was started from, loaded or loading."""
        return Path(self.arguments[self.arguments.index("serve") + 1])


def server_process(servers_directory: Path, name: str) -> ServerProcess | None:
    """The process its pid file names, when that is a live vLLM started for `name` about when the file was written."""
    path = pid_file(servers_directory, name)
    try:
        text = path.read_text(encoding="utf-8").strip()
        written = path.stat().st_mtime
    except OSError:
        return None
    if not text.isdigit():
        return None
    process_id = int(text)
    arguments = command_line(process_id)
    started = process_start_time(process_id)
    if arguments is None or started is None or not is_server_command(arguments, name):
        return None
    return ServerProcess(process_id, tuple(arguments)) if abs(written - started) <= START_SLACK_SECONDS else None
