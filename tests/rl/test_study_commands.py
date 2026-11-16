"""experiments/learning_rate_step.py and experiments/followup_arm.py as the study driver runs them, in a workspace under
the test's directory."""

import dataclasses
import hashlib
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from loop_fakes import zero  # noqa: E402

from lean_search.rl.evaluation import EvaluationSummary  # noqa: E402
from lean_search.search.records import to_json  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
VISIBLE = REPOSITORY / "experiments/configs/grpo/followup/modes/visible.toml"
NO_REASONING = REPOSITORY / "experiments/configs/grpo/followup/modes/no_reasoning.toml"
NO_REASONING_SEARCH = REPOSITORY / "experiments/configs/grpo/search/no_reasoning_student_v2.toml"
SHARED_SAMPLING = REPOSITORY / "experiments/configs/grpo/followup/shared_sampling.toml"
SUMMARY = to_json(dataclasses.replace(zero(EvaluationSummary), dropped=()))


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


def test_check_mode_names_the_search_configs_sha256(tmp_path: Path) -> None:
    digest = hashlib.sha256((REPOSITORY / "experiments/configs/grpo/search/visible_student_v2.toml").read_bytes())
    result = command(tmp_path, "learning_rate_step.py", "check-mode", "--mode", str(VISIBLE))
    assert result.stdout.splitlines()[1] == f"search config sha256 {digest.hexdigest()}"


def test_the_no_reasoning_mode_is_accepted_and_described(tmp_path: Path) -> None:
    result = command(tmp_path, "learning_rate_step.py", "check-mode", "--mode", str(NO_REASONING))
    assert result.stdout.startswith("no visible reasoning, 32 expansions per training search")


def mode_with_search(tmp_path: Path, search_text: str) -> Path:
    """A mode naming a search config written under the test's directory (an absolute path)."""
    search = tmp_path / "search.toml"
    search.write_text(search_text, encoding="utf-8")
    mode = tmp_path / "mode.toml"
    mode.write_text(f'[sampling]\nsearch_config = "{search.as_posix()}"\nmax_expansions = 32\n', encoding="utf-8")
    return mode


def test_a_mode_whose_search_caps_its_tokens_is_refused(tmp_path: Path) -> None:
    capped = NO_REASONING_SEARCH.read_text(encoding="utf-8").replace(
        "max_depth = 64\n", "max_depth = 64\nmax_generated_tokens = 26804\n"
    )
    result = command(tmp_path, "learning_rate_step.py", "check-mode", "--mode", str(mode_with_search(tmp_path, capped)))
    assert (result.returncode, "an evaluation config" in result.stderr) == (1, True)


@pytest.mark.parametrize(("dropped", "status"), [("[]", 0), ('["state_7"]', 1)], ids=["complete", "dropped"])
def test_a_held_out_run_is_complete_only_without_dropped_states(tmp_path: Path, dropped: str, status: int) -> None:
    run = tmp_path / "lean_search_runs" / "held_out_evaluations" / "held_out_step2_A_5e-5"
    run.mkdir(parents=True)
    (run / "summary.json").write_text(SUMMARY.replace('"dropped": []', f'"dropped": {dropped}'), encoding="utf-8")
    assert command(tmp_path, "learning_rate_step.py", "check-held-out", "--name", "step2_A_5e-5").returncode == status


def filled_arm(tmp_path: Path) -> Path:
    arm = tmp_path / "A.toml"
    text = (REPOSITORY / "experiments/configs/grpo/followup/arms/A.toml").read_text(encoding="utf-8")
    arm.write_text(text.replace('"PLACEHOLDER: step 2\'s learning rate for A"', "5e-5"), encoding="utf-8")
    return arm


def start_configs(tmp_path: Path, kind: str, overlay: Path, mode: Path) -> subprocess.CompletedProcess:
    output = tmp_path / "followup_configs"
    arguments = ("--kind", kind, "--mode", str(mode), "--arm", str(overlay), "--output", str(output))
    return command(tmp_path, "followup_arm.py", *arguments)


def test_an_arm_in_the_shared_runs_mode_is_accepted(tmp_path: Path) -> None:
    start_configs(tmp_path, "shared sampling", SHARED_SAMPLING, VISIBLE)
    assert start_configs(tmp_path, "arm", filled_arm(tmp_path), VISIBLE).returncode == 0


def test_an_arm_in_another_mode_than_the_shared_run_is_refused(tmp_path: Path) -> None:
    start_configs(tmp_path, "shared sampling", SHARED_SAMPLING, VISIBLE)
    result = start_configs(tmp_path, "arm", filled_arm(tmp_path), NO_REASONING)
    assert "the arms must sample in the mode their learning rates were chosen in" in result.stderr


def test_an_arm_whose_search_config_changed_since_the_shared_run_is_refused(tmp_path: Path) -> None:
    visible_search = (REPOSITORY / "experiments/configs/grpo/search/visible_student_v2.toml").read_text(
        encoding="utf-8"
    )
    mode = mode_with_search(tmp_path, visible_search)
    start_configs(tmp_path, "shared sampling", SHARED_SAMPLING, mode)
    (tmp_path / "search.toml").write_text(visible_search.replace("temperature = 0.8", "temperature = 0.7"), "utf-8")
    result = start_configs(tmp_path, "arm", filled_arm(tmp_path), mode)
    assert "the arms must sample in the mode their learning rates were chosen in" in result.stderr
