import sys
import time
from pathlib import Path

import pytest

from lean_search.monitoring.gpu_power import GpuPowerQuery, GpuPowerState
from lean_search.rl.probe_evaluation import ProbeCheckpoint, SessionServing, read_sessions, start_session

# nvidia-smi's answer on a node whose host caps the GPUs below their 350 W.
ANSWER = "0, 306.00, 350.00\n1, 350.00, 350.00\n2, 279.00, 350.00\n"
# GPU 1 off the bus: nvidia-smi reports the others and exits non-zero.
ONE_GPU_LOST = "0, 306.00, 350.00\nUnable to determine the device handle for GPU 0000:41:00.0: Unknown Error\n"


def fake_command(directory: Path, body: str) -> tuple[str, ...]:
    """A stand-in for nvidia-smi: a Python script that ignores its arguments and runs `body`."""
    script = directory / "fake_nvidia_smi.py"
    script.write_text(f"import subprocess, sys, time\n{body}\n", encoding="utf-8")
    return (sys.executable, str(script))


def answering(directory: Path, answer: str, status: int = 0) -> tuple[str, ...]:
    return fake_command(directory, f"sys.stdout.write({answer!r})\nsys.exit({status})")


def test_each_gpus_enforced_and_default_limit_is_read(tmp_path: Path) -> None:
    assert GpuPowerQuery(answering(tmp_path, ANSWER))() == (
        GpuPowerState(0, 306.0, 350.0),
        GpuPowerState(1, 350.0, 350.0),
        GpuPowerState(2, 279.0, 350.0),
    )


def test_a_field_the_gpu_does_not_report_is_null_alone(tmp_path: Path) -> None:
    states = GpuPowerQuery(answering(tmp_path, "0, [Not Supported], 350.00\n"))()
    assert states == (GpuPowerState(0, None, 350.0),)


def test_a_gpu_off_the_bus_loses_only_its_own_reading(tmp_path: Path) -> None:
    assert GpuPowerQuery(answering(tmp_path, ONE_GPU_LOST, status=255))() == (GpuPowerState(0, 306.0, 350.0),)


@pytest.mark.parametrize(
    "body",
    [
        "sys.exit(9)",
        "sys.stdout.write('NVIDIA-SMI has failed because it could not communicate with the NVIDIA driver.\\n')",
        "sys.stdout.write('')",
    ],
    ids=["an error", "an answer that does not parse", "no GPU"],
)
def test_a_failed_query_is_null(tmp_path: Path, body: str) -> None:
    assert GpuPowerQuery(fake_command(tmp_path, body))() is None


def test_a_node_without_nvidia_smi_is_null(tmp_path: Path) -> None:
    assert GpuPowerQuery((str(tmp_path / "nvidia-smi"),))() is None


def test_a_query_that_hangs_is_null_after_the_timeout(tmp_path: Path) -> None:
    assert GpuPowerQuery(fake_command(tmp_path, "time.sleep(5)"), timeout_seconds=0.5)() is None


def test_a_hung_query_is_not_waited_for(tmp_path: Path) -> None:
    # A child holding the output pipe outlives the killed query, as an nvidia-smi stuck in the driver would.
    body = "subprocess.Popen(['sleep', '5'])\ntime.sleep(5)"
    query = GpuPowerQuery(fake_command(tmp_path, body), timeout_seconds=0.5)
    started = time.monotonic()
    query()
    assert time.monotonic() - started < 3.0


def test_after_a_hang_the_process_queries_no_more(tmp_path: Path) -> None:
    query = GpuPowerQuery(fake_command(tmp_path, "time.sleep(5)"), timeout_seconds=0.5)
    query()
    query.command = answering(tmp_path, ANSWER)
    assert query() is None


def test_a_probe_session_keeps_the_gpus_at_its_start(tmp_path: Path) -> None:
    checkpoint = ProbeCheckpoint("v0", 0, "/policy", "p" * 64, "/v0", "v" * 64, 0, 0, 0)
    states = GpuPowerQuery(answering(tmp_path, ANSWER))()
    start_session(tmp_path, checkpoint, tmp_path / "results.jsonl", SessionServing(), gpus=states)
    assert read_sessions(tmp_path)[0].gpus == states
