"""deployment/probe_runs.sh in the foreground with a stand-in for python (first on the PATH environment.sh builds from
LEAN_SEARCH_ROOT): its checks pass, its run list holds one run, and every command it runs is logged."""

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "probe_runs.sh"
FAKE_PYTHON = """#!/usr/bin/env bash
echo "$*" >> "${FAKE_PYTHON_LOG}"
case "$1 ${2:-}" in
    "experiments/probe_runs.py check") echo experiments/configs/grpo/loop.toml ;;
    "experiments/probe_runs.py next")
        if [[ ! -e "${FAKE_PYTHON_LOG}.next" ]]; then
            touch "${FAKE_PYTHON_LOG}.next"
            printf 'run_directory\\0--name\\0run1\\0'
        fi
        ;;
    "-c "*) echo loop ;;
esac
"""


def probe_evaluations(root: Path, options: list[str]) -> list[str]:
    """The probe_evaluate.py command lines the script ran."""
    interpreter = root / "root" / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True)
    interpreter.write_text(FAKE_PYTHON, encoding="utf-8")
    interpreter.chmod(0o755)
    log = root / "python.log"
    settings = {
        "LEAN_SEARCH_ROOT": str(root / "root"),
        "LEAN_SEARCH_WORKSPACE": str(root / "workspace"),
        "FAKE_PYTHON_LOG": str(log),
        "PROBE_CONCURRENCY": "112",
        "BACKGROUND_CPU_LIST": str(min(os.sched_getaffinity(0))),
    }
    subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "--foreground", *options, "runs.toml"],
        env=os.environ | settings,
        capture_output=True,
        text=True,
        check=True,
    )
    lines = log.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.startswith("experiments/probe_evaluate.py")]


@pytest.mark.parametrize(
    ("options", "command"),
    [
        ([], "experiments/probe_evaluate.py --name run1"),
        (["--allow-other-pinning"], "experiments/probe_evaluate.py --name run1 --allow-other-pinning"),
    ],
    ids=["by default", "with --allow-other-pinning"],
)
def test_the_runs_get_the_allow_other_pinning_option_only_when_given(
    tmp_path: Path, options: list[str], command: str
) -> None:
    assert probe_evaluations(tmp_path, options) == [command]


def test_an_unknown_option_is_refused(tmp_path: Path) -> None:
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), "--allow-other-layout", "runs.toml"],
        env=os.environ | {"LEAN_SEARCH_WORKSPACE": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
