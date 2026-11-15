import sys
from pathlib import Path

import pytest

from lean_search.monitoring.gpu_power import GpuPowerState, gpu_power_states
from lean_search.rl.probe_evaluation import ProbeCheckpoint, SessionServing, read_sessions, start_session

# nvidia-smi's answer on a node whose host caps the four GPUs below their 350 W.
ANSWER = "0, 306.00, 350.00, 1695, 9751\n1, 350.00, 350.00, 1710, 9751\n2, 279.00, 350.00, 1605, 9751\n"


def fake_command(directory: Path, body: str) -> tuple[str, ...]:
    """A stand-in for nvidia-smi: a Python script that ignores its arguments and runs `body`."""
    script = directory / "fake_nvidia_smi.py"
    script.write_text(f"import sys, time\n{body}\n", encoding="utf-8")
    return (sys.executable, str(script))


def answering(directory: Path, answer: str) -> tuple[str, ...]:
    return fake_command(directory, f"sys.stdout.write({answer!r})")


def test_each_gpus_enforced_and_default_limit_and_clocks_are_read(tmp_path: Path) -> None:
    assert gpu_power_states(answering(tmp_path, ANSWER))[2] == GpuPowerState(2, 279.0, 350.0, 1605.0, 9751.0)


def test_every_gpu_is_read(tmp_path: Path) -> None:
    assert [state.gpu for state in gpu_power_states(answering(tmp_path, ANSWER))] == [0, 1, 2]


def test_a_field_the_gpu_does_not_report_is_null_alone(tmp_path: Path) -> None:
    states = gpu_power_states(answering(tmp_path, "0, [N/A], 350.00, 1695, 9751\n"))
    assert states == (GpuPowerState(0, None, 350.0, 1695.0, 9751.0),)


@pytest.mark.parametrize(
    "body",
    [
        "sys.exit(9)",
        "time.sleep(5)",
        "sys.stdout.write('NVIDIA-SMI has failed because it could not communicate with the NVIDIA driver.\\n')",
        "sys.stdout.write('')",
    ],
    ids=["an error", "no answer within the timeout", "an answer that does not parse", "no GPU"],
)
def test_a_failed_query_is_null(tmp_path: Path, body: str) -> None:
    assert gpu_power_states(fake_command(tmp_path, body), timeout_seconds=1.0) is None


def test_a_node_without_nvidia_smi_is_null(tmp_path: Path) -> None:
    assert gpu_power_states((str(tmp_path / "nvidia-smi"),)) is None


def test_a_probe_session_keeps_the_gpus_at_its_start(tmp_path: Path) -> None:
    checkpoint = ProbeCheckpoint("v0", 0, "/policy", "p" * 64, "/v0", "v" * 64, 0, 0, 0)
    states = gpu_power_states(answering(tmp_path, ANSWER))
    start_session(tmp_path, checkpoint, tmp_path / "results.jsonl", SessionServing(), gpus=states)
    assert read_sessions(tmp_path)[0].gpus == states
