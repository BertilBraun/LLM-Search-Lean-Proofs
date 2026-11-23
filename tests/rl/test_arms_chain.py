"""The arms driver's logic (src/lean_search/rl/arms_chain.py) on loop run directories in the loop's real record formats
(tests/rl/arms_chain_runs.py), and the PC's adapter fetch (deployment/pull_arm_adapters.sh)."""

import json
import os
import shutil
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

pytest.importorskip("torch")

from arms_chain_runs import (  # noqa: E402
    UPDATES,
    FakeRun,
    close_phase,
    finish,
    initialize,
    log,
    metric_line,
    publish,
    round_record,
    stop_on_health,
    train,
    whole_run,
)

from lean_search.expert_iteration.toml_text import toml_text  # noqa: E402
from lean_search.rl.arms_chain import (  # noqa: E402
    ANCHOR_RUNS,
    MANIFEST_FILE,
    PROBE_EVALUATION_CONFIG,
    SMOKE_PHASE_GENERATED_TOKENS,
    SmokeRun,
    adapter_phases,
    arm_report,
    comparisons,
    final_checkpoint,
    health_report,
    manifest_holds,
    probe_list_text,
    pull_adapters,
    smoke_checks,
    smoke_overlay,
    smoke_report,
)
from lean_search.rl.loop_config import parse_loop_config  # noqa: E402
from lean_search.rl.probe_run_list import read_run_list, run_refusals  # noqa: E402
from lean_search.rl.study_configs import OverlayKind, leaf_keys, overlay_configs  # noqa: E402

REPOSITORY = Path(__file__).resolve().parents[2]
CONFIGS = REPOSITORY / "experiments/configs/grpo"
PULL_SCRIPT = REPOSITORY / "deployment" / "pull_arm_adapters.sh"


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def arm_overlay(arm: str) -> dict:
    return toml(CONFIGS / f"followup/arms/{arm}.toml")


def leaves(table: dict) -> dict[str, object]:
    found = {}
    for key in leaf_keys(table):
        value: object = table
        for part in key.split("."):
            assert isinstance(value, dict)
            value = value[part]
        found[key] = value
    return found


def changed_keys(overlay: dict, arm: str) -> set[str]:
    before, after = leaves(overlay), leaves(smoke_overlay(overlay, arm))
    return {key for key in before.keys() | after.keys() if before.get(key) != after.get(key)}


BUDGET_KEYS = {
    "loop.name",
    "loop.training.phase_generated_tokens",
    "loop.training.max_phases",
    "loop.training.value_every_phases",
}


@pytest.mark.parametrize("arm", ["C", "D"])
def test_a_smoke_overlay_differs_from_its_arm_only_in_name_budget_phase_count_and_value_interval(arm: str) -> None:
    assert changed_keys(arm_overlay(arm), arm) == BUDGET_KEYS


def test_a_smoke_overlay_brings_a_longer_round_interval_within_its_one_phase() -> None:
    every_fourth = {
        "loop": {"training": {"policy_update": "grpo_and_expert_iteration", "expert_iteration_every_phases": 4}}
    }
    assert changed_keys(every_fourth, "D") == BUDGET_KEYS | {"loop.training.expert_iteration_every_phases"}


def smoke_loop(arm: str) -> dict:
    configs = overlay_configs(
        OverlayKind.SMOKE,
        smoke_overlay(arm_overlay(arm), arm),
        toml(CONFIGS / "followup/base.toml"),
        toml(CONFIGS / "phase.toml"),
        "/configs/phase.toml",
        toml(CONFIGS / "followup/expert_iteration.toml"),
        "/configs/expert_iteration.toml",
    )
    return configs.loop


@pytest.mark.parametrize("arm", ["C", "D"])
def test_a_smoke_overlay_makes_a_one_phase_loop_with_a_round_and_a_value_training_at_its_phase(arm: str) -> None:
    training = parse_loop_config(toml_text(smoke_loop(arm))).training
    assert (
        training.max_phases,
        training.phase_generated_tokens,
        training.expert_iteration_every_phases,
        training.value_every_phases,
    ) == (1, SMOKE_PHASE_GENERATED_TOKENS, 1, 1)


def test_the_smoke_phase_is_half_an_arms_phase() -> None:
    base = toml(CONFIGS / "followup/base.toml")
    assert base["training"]["phase_generated_tokens"] == SMOKE_PHASE_GENERATED_TOKENS * 2


@pytest.mark.parametrize("arm", ["C", "D"])
def test_a_smoke_runs_name_is_not_its_arms(arm: str) -> None:
    assert smoke_loop(arm)["name"] == f"followup_smoke_{arm}"


def test_a_smoke_overlay_is_refused_as_an_arm() -> None:
    with pytest.raises(ValueError, match="changes only"):
        overlay_configs(
            OverlayKind.ARM,
            smoke_overlay(arm_overlay("C"), "C"),
            toml(CONFIGS / "followup/base.toml"),
            toml(CONFIGS / "phase.toml"),
            "/configs/phase.toml",
            toml(CONFIGS / "followup/expert_iteration.toml"),
            "/configs/expert_iteration.toml",
        )


@pytest.fixture
def finished_arm(tmp_path: Path) -> FakeRun:
    run = FakeRun(tmp_path / "runs", tmp_path / "checkpoints", "followup_C", UPDATES["C"])
    whole_run(run, 16)
    return run


@pytest.fixture
def stopped_arm(tmp_path: Path) -> FakeRun:
    """Collapsed at phase 3; version 2 the last good one."""
    run = FakeRun(tmp_path / "runs", tmp_path / "checkpoints", "followup_A", UPDATES["A"])
    initialize(run)
    for phase in (1, 2, 3):
        train(run, phase)
        version = publish(run, phase)
        close_phase(run, phase, version.version, valid=0.3 if phase == 3 else 0.6, alert=phase == 3)
    stop_on_health(run, 3, 2)
    return run


def test_a_finished_arms_final_checkpoint_is_its_last_phase_with_its_value_model(finished_arm: FakeRun) -> None:
    checkpoint = final_checkpoint(finished_arm.directory)
    assert checkpoint is not None
    assert (checkpoint.phase, checkpoint.value_version, checkpoint.version.value_adapter) == (
        16,
        16,
        str(finished_arm.phase_directory(16) / "value" / "adapter"),
    )


def test_a_finished_c_arm_is_evaluated_with_its_last_rounds_adapter(finished_arm: FakeRun) -> None:
    checkpoint = final_checkpoint(finished_arm.directory)
    assert checkpoint is not None and checkpoint.version.policy_adapter.endswith("phase_0016/expert_iteration/adapter")


def test_a_stopped_arms_final_checkpoint_is_its_last_good_version(stopped_arm: FakeRun) -> None:
    checkpoint = final_checkpoint(stopped_arm.directory)
    assert checkpoint is not None and (checkpoint.phase, checkpoint.stopped_at_phase, checkpoint.value_version) == (
        2,
        3,
        2,
    )


def test_an_arm_stopped_with_version_0_as_its_last_good_one_has_no_checkpoint(tmp_path: Path) -> None:
    run = FakeRun(tmp_path / "runs", tmp_path / "checkpoints", "followup_A", "grpo")
    initialize(run)
    train(run, 1)
    publish(run, 1)
    stop_on_health(run, 1, 0)
    assert final_checkpoint(run.directory) is None


def test_a_finished_arms_adapters_are_phase_8_and_16(finished_arm: FakeRun) -> None:
    assert adapter_phases(finished_arm.directory) == [8, 16]


def test_a_stopped_arm_before_phase_8_pulls_its_last_good_phase_only(stopped_arm: FakeRun) -> None:
    assert adapter_phases(stopped_arm.directory) == [2]


def test_the_pulled_adapters_are_policy_and_value_of_both_phases(finished_arm: FakeRun, tmp_path: Path) -> None:
    pulled = pull_adapters(finished_arm.directory, tmp_path / "adapters" / "C")
    assert [(adapter.phase, adapter.model) for adapter in pulled] == [
        (8, "policy"),
        (8, "value"),
        (16, "policy"),
        (16, "value"),
    ]


def test_a_pulled_adapter_is_a_copy_of_the_retained_one(finished_arm: FakeRun, tmp_path: Path) -> None:
    output = tmp_path / "adapters" / "C"
    pull_adapters(finished_arm.directory, output)
    source = finished_arm.phase_directory(16) / "expert_iteration" / "adapter" / "adapter_model.safetensors"
    assert (output / "phase_0016" / "policy" / "adapter_model.safetensors").read_bytes() == source.read_bytes()


def test_the_pulled_adapters_manifest_holds(finished_arm: FakeRun, tmp_path: Path) -> None:
    output = tmp_path / "adapters" / "C"
    pull_adapters(finished_arm.directory, output)
    assert manifest_holds(output)


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum")
def test_the_manifest_checks_with_sha256sum(finished_arm: FakeRun, tmp_path: Path) -> None:
    output = tmp_path / "adapters" / "C"
    pull_adapters(finished_arm.directory, output)
    result = subprocess.run(["sha256sum", "--quiet", "-c", MANIFEST_FILE], cwd=output, check=False)  # noqa: S607
    assert result.returncode == 0


def test_pulling_again_keeps_a_complete_copy(finished_arm: FakeRun, tmp_path: Path) -> None:
    output = tmp_path / "adapters" / "C"
    first = pull_adapters(finished_arm.directory, output)
    assert pull_adapters(finished_arm.directory, output) == first


def test_a_copy_whose_files_changed_is_refused(finished_arm: FakeRun, tmp_path: Path) -> None:
    output = tmp_path / "adapters" / "C"
    pull_adapters(finished_arm.directory, output)
    (output / "phase_0008" / "value" / "adapter_model.safetensors").write_bytes(b"changed")
    with pytest.raises(ValueError, match="does not match"):
        pull_adapters(finished_arm.directory, output)


def written_list(run: FakeRun, tmp_path: Path, arm: str = "C") -> Path:
    checkpoint = final_checkpoint(run.directory)
    assert checkpoint is not None
    path = tmp_path / f"runs_{arm}.toml"
    path.write_text(probe_list_text(arm, checkpoint), encoding="utf-8")
    return path


def test_the_probe_list_is_one_run_of_the_final_checkpoint_with_its_value_model(
    finished_arm: FakeRun, tmp_path: Path
) -> None:
    (run,) = read_run_list(written_list(finished_arm, tmp_path)).runs
    assert (run.name, run.phase, run.value, run.value_version) == (
        "arm_C_phase16_run1",
        16,
        str(finished_arm.phase_directory(16) / "value" / "adapter"),
        16,
    )


def test_the_probe_run_starts_longest_expected_search_first_at_the_anchors_settings(
    finished_arm: FakeRun, tmp_path: Path
) -> None:
    (run,) = read_run_list(written_list(finished_arm, tmp_path)).runs
    assert (run.config, run.search_config, run.problems) == (PROBE_EVALUATION_CONFIG, "", 0)


def test_the_probe_list_passes_the_launchers_checks(finished_arm: FakeRun, tmp_path: Path) -> None:
    (run,) = read_run_list(written_list(finished_arm, tmp_path)).runs
    assert run_refusals(run, REPOSITORY, 112) == []


def test_a_stopped_arms_probe_run_says_where_it_stopped(stopped_arm: FakeRun, tmp_path: Path) -> None:
    (run,) = read_run_list(written_list(stopped_arm, tmp_path, "A")).runs
    assert (run.name, "stopped at phase 3" in run.purpose) == ("arm_A_phase2_run1", True)


def test_the_first_arm_is_compared_with_the_anchors_and_run_7() -> None:
    found = comparisons("A", "arm_A_phase16_run1", [])
    assert [(item.file_name, item.y_runs) for item in found] == [
        ("A_against_anchors.txt", ANCHOR_RUNS),
        ("A_against_run7.txt", ("step1_run7_v35_value_final",)),
    ]


def test_a_later_arm_is_also_compared_with_each_other_arms_run() -> None:
    found = comparisons("D", "arm_D_phase16_run1", [("A", "arm_A_phase16_run1"), ("C", "arm_C_phase16_run1")])
    assert [item.y_label for item in found] == ["v0 anchors", "v35 value final", "arm A", "arm C"]


def test_the_health_report_names_the_stop_and_its_alert(stopped_arm: FakeRun) -> None:
    report = health_report("A", stopped_arm.directory)
    assert "last good version 2" in report and "held_out_valid_lean" in report


def test_the_report_of_an_arm_without_a_probe_run_says_so(stopped_arm: FakeRun, tmp_path: Path) -> None:
    report = arm_report("A", stopped_arm.directory, None, [], tmp_path / "adapters" / "A")
    assert "No probe run" in report and "stopped on its health rule at phase 3" in report


def test_the_report_lists_every_phase(finished_arm: FakeRun, tmp_path: Path) -> None:
    report = arm_report("C", finished_arm.directory, tmp_path / "probe_arm_C", ["C_against_anchors.txt"], tmp_path)
    assert all(f"| {phase} |" in report for phase in range(1, 17))


READING = "{time}\t1\ttraining\t{gpu}\t{used}\t24576\t{shared}\t74448896\n"


def smoke_run(
    tmp_path: Path, arm: str, used: int = 20_000, shared: int = 30 * 2**20, killed: bool = False, value_every: int = 1
) -> SmokeRun:
    """A smoke run as the loop and the driver leave it (its phase trains the value model too); D killed while
    publishing and started again."""
    run = FakeRun(tmp_path / "runs", tmp_path / "checkpoints", f"followup_smoke_{arm}", UPDATES[arm], value_every)
    run.directory.mkdir(parents=True)
    log(run, f"Loop {run.name}: version 0")
    initialize(run)
    train(run, 1)
    kill = None
    if killed:
        time.sleep(0.05)
        kill = tmp_path / "kill.json"
        record = {"killed_at": time.time(), "pid": 4242, "phase": 1, "stage": "publishing", "stage_seconds": 31}
        kill.write_text(json.dumps(record), encoding="utf-8")
        log(run, f"Loop {run.name}: version 0")
    publish(run, 1)
    close_phase(run, 1, 1)
    finish(run, 1)
    readings = tmp_path / f"readings_{arm}.tsv"
    lines = [
        READING.format(time=1000 + step, gpu=gpu, used=used, shared=shared) for step in range(3) for gpu in range(4)
    ]
    readings.write_text("".join(lines), encoding="utf-8")
    return SmokeRun(arm, run.directory, run.phase_directory(1), readings, kill)


def failed_gates(run: SmokeRun) -> list[str]:
    return [check.name for check in smoke_checks(run) if check.gate and not check.passed]


def test_a_healthy_c_smoke_run_passes_every_gate(tmp_path: Path) -> None:
    assert failed_gates(smoke_run(tmp_path, "C")) == []


def test_a_healthy_d_smoke_run_killed_and_resumed_passes_every_gate(tmp_path: Path) -> None:
    assert failed_gates(smoke_run(tmp_path, "D", killed=True)) == []


def test_a_skipped_round_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "C")
    (run.run_directory / "metrics" / "expert_iteration.jsonl").unlink()
    metric_line(
        FakeRun(tmp_path / "runs", tmp_path / "checkpoints", run.run_directory.name, "x"), 1, round_record(True)
    )
    assert failed_gates(run) == ["round trained"]


def test_a_round_skipped_for_too_few_examples_says_so_with_its_count(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "C")
    (run.run_directory / "metrics" / "expert_iteration.jsonl").unlink()
    metric_line(
        FakeRun(tmp_path / "runs", tmp_path / "checkpoints", run.run_directory.name, "x"), 1, round_record(True)
    )
    (check,) = [check for check in smoke_checks(run) if check.name == "round trained"]
    assert check.detail.startswith("skipped: too few examples") and "0 training examples" in check.detail


def test_a_trained_round_reports_its_example_count(tmp_path: Path) -> None:
    (check,) = [check for check in smoke_checks(smoke_run(tmp_path, "C")) if check.name == "round trained"]
    assert "300 training examples from 40 solved trees" in check.detail


def test_a_phase_without_a_value_training_fails_the_smoke_test(tmp_path: Path) -> None:
    assert failed_gates(smoke_run(tmp_path, "D", killed=True, value_every=2)) == ["value model trained in the phase"]


def test_a_round_recorded_twice_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "C")
    metric_line(FakeRun(tmp_path / "runs", tmp_path / "checkpoints", run.run_directory.name, "x"), 1, round_record())
    assert failed_gates(run) == ["round trained"]


def test_gpu_memory_near_the_cards_size_while_training_is_a_reading_not_a_failure(tmp_path: Path) -> None:
    assert failed_gates(smoke_run(tmp_path, "C", used=24_500)) == []


def test_the_training_peaks_are_reported(tmp_path: Path) -> None:
    (check,) = [
        check
        for check in smoke_checks(smoke_run(tmp_path, "C", used=24_500))
        if check.name.startswith("GPU memory while")
    ]
    assert "GPU 3 24,500 MiB" in check.detail


def test_shared_memory_near_full_fails_the_smoke_test(tmp_path: Path) -> None:
    assert failed_gates(smoke_run(tmp_path, "C", shared=70_000_000)) == ["/dev/shm"]


def test_too_little_gpu_memory_before_the_wake_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "C")
    log_path = run.run_directory / "loop.log"
    log_path.write_text(log_path.read_text(encoding="utf-8").replace("23.1 of", "20.0 of"), encoding="utf-8")
    assert failed_gates(run) == ["GPU memory before the wake"]


def test_an_out_of_memory_line_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "C")
    trainer_log = run.run_directory / "training" / "trainer.log"
    trainer_log.parent.mkdir(parents=True)
    trainer_log.write_text("torch.OutOfMemoryError: CUDA out of memory\n", encoding="utf-8")
    assert failed_gates(run) == ["no out-of-memory"]


def test_a_phase_trained_again_after_the_kill_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "D", killed=True)
    outcome = run.phase_directory / "phase.json"
    later = time.time() + 60
    os.utime(outcome, (later, later))
    assert failed_gates(run) == ["nothing trained or built again"]


def test_a_missing_kill_record_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "D", killed=True)
    assert run.kill is not None
    run.kill.unlink()
    assert failed_gates(run) == ["killed while publishing"]


def test_a_smoke_loop_that_never_restarted_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "D", killed=True)
    log_path = run.run_directory / "loop.log"
    lines = log_path.read_text(encoding="utf-8").splitlines()
    first = next(index for index, line in enumerate(lines) if "Loop followup_smoke_D: version" in line)
    log_path.write_text("\n".join(lines[: first + 1] + [line for line in lines[first + 1 :] if "Loop " not in line]))
    assert failed_gates(run) == ["restarted"]


def test_a_second_version_for_the_phase_fails_the_smoke_test(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "C")
    publish(FakeRun(tmp_path / "runs", tmp_path / "checkpoints", run.run_directory.name, UPDATES["C"]), 1)
    assert "one version for the phase" in failed_gates(run)


def test_the_smoke_report_passes_only_when_every_gate_passes(tmp_path: Path) -> None:
    good = smoke_run(tmp_path / "good", "C")
    bad = smoke_run(tmp_path / "bad", "C", shared=70_000_000)
    passed, report = smoke_report([(good, smoke_checks(good)), (bad, smoke_checks(bad))])
    assert (passed, "FAILED" in report.splitlines()[0]) == (False, True)


def test_the_smoke_report_says_where_the_kill_lands() -> None:
    _, report = smoke_report([])
    assert "before the version is recorded" in report and "not review AS's M1 point" in report


def test_the_smoke_report_lists_what_it_leaves_to_the_real_arms() -> None:
    _, report = smoke_report([])
    assert all(item in report for item in ("AS 5", "AT 6", "AS 2", "AT 1", "4-phase window"))


def test_a_missed_kill_brings_the_recipe_to_repeat_the_smoke_run(tmp_path: Path) -> None:
    run = smoke_run(tmp_path, "D", killed=True)
    assert run.kill is not None
    run.kill.unlink()
    _, report = smoke_report([(run, smoke_checks(run))])
    assert "To repeat followup_smoke_D" in report


def test_a_stop_with_no_healthy_version_says_evaluate_is_not_possible(tmp_path: Path) -> None:
    run = FakeRun(tmp_path / "runs", tmp_path / "checkpoints", "followup_A", "grpo")
    initialize(run)
    train(run, 1)
    version = publish(run, 1)
    close_phase(run, 1, version.version, valid=0.3, alert=True)
    stop_on_health(run, 1, 0)
    assert "`evaluate` is not possible: no healthy version" in health_report("A", run.directory)


def test_a_reports_comparisons_are_called_provisional(finished_arm: FakeRun, tmp_path: Path) -> None:
    report = arm_report("C", finished_arm.directory, None, ["C_against_anchors.txt"], tmp_path)
    assert "provisional" in report


def test_the_report_names_the_checkouts_the_loop_started_from(finished_arm: FakeRun, tmp_path: Path) -> None:
    report = arm_report("C", finished_arm.directory, None, [], tmp_path, ["2026-11-19T10:00:00Z 0e04599"])
    assert "2026-11-19T10:00:00Z 0e04599" in report


def test_the_log_lines_the_checks_read_are_still_the_loops() -> None:
    sources = "".join(
        (REPOSITORY / name).read_text(encoding="utf-8")
        for name in (
            "src/lean_search/rl/loop.py",
            "src/lean_search/rl/loop_services.py",
            "src/lean_search/rl/expert_iteration_rounds.py",
            "experiments/grpo_loop.py",
        )
    )
    expected = [
        "GPU memory before the wake: ",
        "GiB free, its servers' shares \"",
        "Expert-iteration round of phase {phase}, built in ",
        "Loop {config.name}: version",
    ]
    assert [text for text in expected if text not in sources] == []


def node_side(tmp_path: Path, finished_arm: FakeRun) -> tuple[Path, Path]:
    """The node's adapters directory and the live pull's copy of its manifests."""
    node_adapters = tmp_path / "node" / "adapters"
    pull_adapters(finished_arm.directory, node_adapters / "C")
    live = tmp_path / "live" / "runs" / "arms_chain" / "adapters" / "C"
    live.mkdir(parents=True)
    shutil.copyfile(node_adapters / "C" / MANIFEST_FILE, live / MANIFEST_FILE)
    return node_adapters, tmp_path / "live"


def fetch(node_adapters: Path, live: Path, target: Path) -> int:
    environment = os.environ | {"NODE_SSH": "bash -c", "NODE_ADAPTERS": str(node_adapters)}
    result = subprocess.run(  # noqa: S603
        ["bash", str(PULL_SCRIPT), str(live), str(target)], env=environment, check=False, capture_output=True
    )
    return result.returncode


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum")
def test_the_pc_fetches_an_arms_adapters_once_their_manifest_arrived(finished_arm: FakeRun, tmp_path: Path) -> None:
    node_adapters, live = node_side(tmp_path, finished_arm)
    target = tmp_path / "pc"
    assert (fetch(node_adapters, live, target), (target / "C" / "verified").exists()) == (0, True)


@pytest.mark.skipif(shutil.which("sha256sum") is None, reason="no sha256sum")
def test_the_pc_refuses_a_fetch_that_does_not_match_the_manifest(finished_arm: FakeRun, tmp_path: Path) -> None:
    node_adapters, live = node_side(tmp_path, finished_arm)
    (node_adapters / "C" / "phase_0008" / "policy" / "adapter_model.safetensors").write_bytes(b"torn")
    target = tmp_path / "pc"
    assert (fetch(node_adapters, live, target), (target / "C").exists()) == (1, False)
