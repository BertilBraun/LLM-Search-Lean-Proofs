"""Each GPU's power limits and clocks from nvidia-smi: the host caps the GPUs' power below nominal and the caps drift
(e.g. 306 / 350 / 279 / 330 W on one node), so a run's record holds them at its start and end. None where the query
fails or its answer does not parse; a field the GPU does not report ([N/A]) is None on its own."""

import subprocess
from collections.abc import Sequence
from dataclasses import dataclass

QUERY_FIELDS = ("index", "enforced.power.limit", "power.default_limit", "clocks.sm", "clocks.mem")
QUERY_TIMEOUT_SECONDS = 10.0
NVIDIA_SMI = ("nvidia-smi",)


@dataclass(frozen=True)
class GpuPowerState:
    gpu: int
    enforced_power_limit_watts: float | None
    default_power_limit_watts: float | None
    sm_clock_mhz: float | None
    memory_clock_mhz: float | None


def reported(text: str) -> float | None:
    try:
        return float(text)
    except ValueError:
        return None


def parsed_states(output: str) -> tuple[GpuPowerState, ...] | None:
    states = []
    for line in output.splitlines():
        if not line.strip():
            continue
        fields = [field.strip() for field in line.split(",")]
        if len(fields) != len(QUERY_FIELDS) or not fields[0].isdigit():
            return None
        states.append(GpuPowerState(int(fields[0]), *(reported(field) for field in fields[1:])))
    return tuple(states) or None


def gpu_power_states(
    command: Sequence[str] = NVIDIA_SMI, timeout_seconds: float = QUERY_TIMEOUT_SECONDS
) -> tuple[GpuPowerState, ...] | None:
    """Every GPU's enforced and default power limit and current SM and memory clocks; None on a node where the query
    fails (no nvidia-smi, an error, no answer within the timeout)."""
    arguments = [*command, f"--query-gpu={','.join(QUERY_FIELDS)}", "--format=csv,noheader,nounits"]
    try:
        completed = subprocess.run(arguments, capture_output=True, text=True, timeout=timeout_seconds, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return parsed_states(completed.stdout)
