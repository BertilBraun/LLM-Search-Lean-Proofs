"""experiments/learning_rate_step.py and experiments/followup_arm.py as the study driver runs them, in a workspace under
the test's directory."""

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("numpy")

REPOSITORY = Path(__file__).resolve().parents[2]
VISIBLE = REPOSITORY / "experiments/configs/grpo/followup/modes/visible.toml"
SHARED_SAMPLING = REPOSITORY / "experiments/configs/grpo/followup/shared_sampling.toml"


def command(tmp_path: Path, script: str, *arguments: str) -> subprocess.CompletedProcess:
    workspace = {name: str(tmp_path / name.lower()) for name in ("LEAN_SEARCH_RUNS", "LEAN_SEARCH_DATA")}
    workspace["LEAN_SEARCH_CHECKPOINTS"] = str(tmp_path / "checkpoints")
    return subprocess.run(  # noqa: S603
        [sys.executable, str(REPOSITORY / "experiments" / script), *arguments],
        env=os.environ | workspace,
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_visible_mode_is_accepted_and_described(tmp_path: Path) -> None:
    result = command(tmp_path, "learning_rate_step.py", "check-mode", "--mode", str(VISIBLE))
    assert result.stdout.startswith("visible reasoning, 32 expansions per training search")


def test_a_mode_whose_search_config_is_missing_is_refused(tmp_path: Path) -> None:
    mode = tmp_path / "mode.toml"
    mode.write_text('[sampling]\nsearch_config = "experiments/none.toml"\nmax_expansions = 32\n', encoding="utf-8")
    result = command(tmp_path, "learning_rate_step.py", "check-mode", "--mode", str(mode))
    assert (result.returncode, "experiments/none.toml" in result.stderr) == (1, True)


def test_the_configs_are_written_again_unchanged_on_a_restart(tmp_path: Path) -> None:
    arguments = ("write-configs", "--output", str(tmp_path / "configs"), "--shared-run", "followup_shared_sampling")
    first = command(tmp_path, "learning_rate_step.py", *arguments)
    second = command(tmp_path, "learning_rate_step.py", *arguments)
    assert (first.returncode, second.returncode, len(list((tmp_path / "configs").iterdir()))) == (0, 0, 13)


def test_configs_changed_since_the_step_began_are_refused(tmp_path: Path) -> None:
    arguments = ("write-configs", "--output", str(tmp_path / "configs"), "--shared-run", "followup_shared_sampling")
    command(tmp_path, "learning_rate_step.py", *arguments)
    (tmp_path / "configs" / "A_5e-5.toml").write_text("changed", encoding="utf-8")
    assert "written once" in command(tmp_path, "learning_rate_step.py", *arguments).stderr


def test_a_dry_run_log_without_steps_is_refused(tmp_path: Path) -> None:
    log = tmp_path / "dry_run.log"
    log.write_text("Continuing v0's adapter /a: 0 expert-iteration examples, 0 steps on 4 GPUs\n", encoding="utf-8")
    assert command(tmp_path, "learning_rate_step.py", "check-dry-run", "--log", str(log)).returncode == 1


def test_the_shared_sampling_run_searches_as_its_mode_says(tmp_path: Path) -> None:
    mode = tmp_path / "mode.toml"
    search = "experiments/configs/grpo/gate_search.toml"
    mode.write_text(f'[sampling]\nsearch_config = "{search}"\nmax_expansions = 74\n', encoding="utf-8")
    output = tmp_path / "followup_configs"
    arguments = (
        "--kind",
        "shared sampling",
        "--mode",
        str(mode),
        "--arm",
        str(SHARED_SAMPLING),
        "--output",
        str(output),
    )
    loop_config = Path(command(tmp_path, "followup_arm.py", *arguments).stdout.strip())
    sampling = tomllib.loads(loop_config.read_text(encoding="utf-8"))["sampling"]
    assert (sampling["search_config"], sampling["max_expansions"]) == (search, 74)


def test_an_arm_without_a_mode_is_refused(tmp_path: Path) -> None:
    arguments = ("--kind", "shared sampling", "--arm", str(SHARED_SAMPLING), "--output", str(tmp_path))
    assert command(tmp_path, "followup_arm.py", *arguments).returncode == 2
