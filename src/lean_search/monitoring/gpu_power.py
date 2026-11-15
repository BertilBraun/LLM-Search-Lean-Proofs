"""Each GPU's enforced and default power limit from nvidia-smi: the host caps the GPUs' power below nominal and the caps
drift (e.g. 306 / 350 / 279 / 330 W on one node), so a run's record holds them at its start and end.

The query never blocks its caller beyond the timeout: an nvidia-smi stuck in the driver survives SIGKILL, so on a
timeout it is killed and left unwaited, and the process queries no more (`GpuPowerQuery.hung`). A line that does not
parse (a GPU off the bus) loses only that GPU; no GPU read, or a query that fails, is None."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

QUERY_FIELDS = ("index", "enforced.power.limit", "power.default_limit")
QUERY_TIMEOUT_SECONDS = 10.0
NVIDIA_SMI = ("nvidia-smi",)


@dataclass(frozen=True)
class GpuPowerState:
    gpu: int
    enforced_power_limit_watts: float | None
    default_power_limit_watts: float | None


def reported(text: str) -> float | None:
    """A field the GPU does not report ([N/A], [Not Supported]) is None."""
    try:
        return float(text)
    except ValueError:
        return None


def parsed_states(output: str) -> tuple[GpuPowerState, ...] | None:
    states = []
    for line in output.splitlines():
        fields = [field.strip() for field in line.split(",")]
        if len(fields) == len(QUERY_FIELDS) and fields[0].isdigit():
            states.append(GpuPowerState(int(fields[0]), reported(fields[1]), reported(fields[2])))
    return tuple(states) or None


class GpuPowerQuery:
    def __init__(self, command: Sequence[str] = NVIDIA_SMI, timeout_seconds: float = QUERY_TIMEOUT_SECONDS) -> None:
        self.command = tuple(command)
        self.timeout_seconds = timeout_seconds
        # Set by the first query that did not answer in time: every later one returns None at once.
        self.hung = False

    def __call__(self) -> tuple[GpuPowerState, ...] | None:
        if self.hung:
            return None
        arguments = [*self.command, f"--query-gpu={','.join(QUERY_FIELDS)}", "--format=csv,noheader,nounits"]
        try:
            process = subprocess.Popen(  # noqa: S603
                arguments, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True
            )
        except OSError:
            return None
        try:
            output, _ = process.communicate(timeout=self.timeout_seconds)
        except subprocess.TimeoutExpired:
            self.hung = True
            process.kill()
            return None
        # A failing GPU makes nvidia-smi exit non-zero while it still reports the others.
        return parsed_states(output)


gpu_power_states = GpuPowerQuery()
