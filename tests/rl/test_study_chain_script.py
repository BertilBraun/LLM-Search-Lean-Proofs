"""deployment/study_chain.sh against stand-ins for every command it runs (tests/rl/study_chain_fakes/: the checkout's
python, the deployment scripts, taskset and nvidia-smi), restarted as supervisord would after any exit but 0: the
order of its steps, its resume after a kill at each step, its stops, and a start after its HOLD. The plan files are the
real experiments/learning_rate_step.py ones (`plan_files`, `round_config_text`)."""

import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip("numpy")

from lean_search.rl.learning_rate_step import (  # noqa: E402
    STEP_VARIANTS,
    PlanPaths,
    RoundKind,
    Signal,
    StudyTemplates,
    plan_files,
    rank_arguments,
    round_config_text,
)

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "deployment" / "study_chain.sh"
FAKES = Path(__file__).resolve().parent / "study_chain_fakes"
CONFIGS = REPOSITORY / "experiments/configs/grpo"
SHARED_RUN = "followup_shared_sampling"
DEPLOYMENT_FAKES = ("environment.sh", "fake_common.sh", "arm_loop.sh", "grpo_loop.sh", "stop_model.sh", "background.sh")
# Lines the background builds and the trainers' wrappers add between the steps.
SIDE_LINES = ("taskset ", "torchrun ", "build ", "trained ")


def toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


TEMPLATES = StudyTemplates(
    toml(CONFIGS / "followup/base.toml"),
    toml(CONFIGS / "phase.toml"),
    toml(CONFIGS / "followup/expert_iteration.toml"),
    {signal: toml(CONFIGS / f"followup/arms/{signal}.toml") for signal in Signal},
)


@dataclass(frozen=True)
class Node:
    """The test's node: the stand-in checkout, workspace, driver state and scenario."""

    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def scenario(self) -> Path:
        return self.root / "scenario"

    @property
    def workspace(self) -> Path:
        return self.root / "workspace"

    @property
    def log(self) -> Path:
        return self.root / "commands.log"

    def set(self, name: str, text: str = "") -> None:
        (self.scenario / name).write_text(text, encoding="utf-8")

    def lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []

    def steps(self) -> list[str]:
        return [line for line in self.lines() if not line.startswith(SIDE_LINES)]

    def stopped(self) -> str:
        return (self.state / "STOPPED").read_text(encoding="utf-8")


def executable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755)


def make_node(root: Path, mode: bool = True) -> Node:
    node = Node(root)
    repository = root / "repository"
    for name in DEPLOYMENT_FAKES:
        executable(FAKES / name, repository / "deployment" / name)
    executable(FAKES / "python", repository / ".venv" / "bin" / "python")
    for name in ("taskset", "nvidia-smi"):
        executable(FAKES / name, root / "bin" / name)
    configs = node.scenario / "configs"
    configs.mkdir(parents=True)
    checkpoints = node.workspace / "checkpoints"
    v0_adapter = checkpoints / "v0" / "adapter"
    v0_adapter.mkdir(parents=True)
    paths = PlanPaths(
        node.state / "configs",
        checkpoints,
        node.workspace / "runs",
        SHARED_RUN,
        str(v0_adapter),
        node.workspace / "data" / "lean.jsonl",
        node.workspace / "data" / "math.jsonl",
    )
    plan = plan_files(paths)
    for name, text in (("rounds.tsv", plan.rounds), ("builds.tsv", plan.builds), ("held_out.tsv", plan.held_out)):
        (configs / name).write_text(text, encoding="utf-8")
    for variant in STEP_VARIANTS:
        text = round_config_text(variant, TEMPLATES, SHARED_RUN)
        (configs / f"{variant.label}.toml").write_text(text, encoding="utf-8")
    for signal in Signal:
        node.set(f"rank_{signal}.arguments", "\n".join(rank_arguments(signal)) + "\n")
    node.state.mkdir()
    if mode:
        shutil.copyfile(CONFIGS / "followup/modes/visible.toml", node.state / "mode.toml")
    return node


def environment(node: Node, extra: dict[str, str] | None = None) -> dict[str, str]:
    return (
        os.environ
        | {
            "STUDY_CHAIN_STATE": str(node.state),
            "STUDY_CHAIN_REPOSITORY": str(node.root / "repository"),
            "STUDY_CHAIN_START_SECONDS": "0",
            "STUDY_CHAIN_POLL_SECONDS": "0",
            "FAKE_REPOSITORY": str(node.root / "repository"),
            "FAKE_WORKSPACE": str(node.workspace),
            "FAKE_BIN": str(node.root / "bin"),
            "FAKE_SCENARIO": str(node.scenario),
            "FAKE_LOG": str(node.log),
        }
        | (extra or {})
    )


def start(node: Node, extra: dict[str, str] | None = None) -> int:
    """One start of the driver, in a process group of its own (a fake's kill takes the whole group)."""
    result = subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT)], env=environment(node, extra), start_new_session=True, timeout=300, check=False
    )
    return result.returncode


def supervise(node: Node, extra: dict[str, str] | None = None, limit: int = 12) -> list[int]:
    """Starts until an exit 0, as supervisord does with autorestart=unexpected and exitcodes=0."""
    codes = [start(node, extra)]
    while codes[-1] != 0 and len(codes) < limit:
        codes.append(start(node, extra))
    return codes


def held_out_steps(name: str) -> list[str]:
    return ["grpo_loop.sh servers", f"held_out_evaluate.py {name}", "learning_rate_step.py check-held-out"]


def expected_steps(node: Node) -> list[str]:
    mode = node.state / "mode.toml"
    steps = [
        "learning_rate_step.py check-mode",
        "learning_rate_step.py write-configs",
        "stop_model.sh --all",
        f"arm_loop.sh --kind shared sampling --mode {mode} experiments/configs/grpo/followup/shared_sampling.toml",
        "slice_trees.py",
        *held_out_steps("step2_v0"),
        "stop_model.sh --all",
    ]
    steps += [
        f"grpo_phase.py {variant.run_name} part policy trees slice_4"
        for variant in STEP_VARIANTS
        if variant.kind == RoundKind.GRPO
    ]
    for build in ("step2_C_w1", "step2_C_w4"):
        steps += [f"dry run {build}", "learning_rate_step.py check-dry-run"]
    steps += [f"train {variant.run_name}" for variant in STEP_VARIANTS if variant.kind == RoundKind.EXPERT_ITERATION]
    for variant in STEP_VARIANTS:
        steps += held_out_steps(variant.run_name)
    steps += held_out_steps("step2_v0_end")
    for signal in Signal:
        steps += ["learning_rate_step.py rank-arguments", f"rank_learning_rates.py {signal}"]
    return [*steps, "learning_rate_step.py report", "stop_model.sh --all"]


@pytest.fixture
def node(tmp_path: Path) -> Node:
    return make_node(tmp_path)


@pytest.fixture
def finished(tmp_path: Path) -> Node:
    """A node whose driver ran the whole step once without trouble."""
    node = make_node(tmp_path)
    assert supervise(node) == [0]
    return node


def test_a_clean_run_takes_the_steps_in_order(finished: Node) -> None:
    assert finished.steps() == expected_steps(finished)


def test_a_clean_run_ends_in_hold(finished: Node) -> None:
    assert (finished.state / "HOLD").read_text(encoding="utf-8").split(" ", 1)[1].startswith("step 2 done")


def test_the_hold_says_the_servers_are_stopped(finished: Node) -> None:
    assert (finished.state / "HOLD").read_text(encoding="utf-8").rstrip().endswith("the servers are stopped")


def test_a_clean_run_writes_no_stopped(finished: Node) -> None:
    assert not (finished.state / "STOPPED").exists()


def test_both_expert_iteration_builds_end_before_the_first_dry_run(finished: Node) -> None:
    lines = finished.lines()
    builds = [index for index, line in enumerate(lines) if line.startswith("build ")]
    assert (len(builds), max(builds) < lines.index("dry run step2_C_w1")) == (2, True)


def test_every_round_trains_on_the_four_gpus_offline(finished: Node) -> None:
    launches = {line for line in finished.lines() if line.startswith("torchrun ")}
    assert launches == {"torchrun on CUDA_VISIBLE_DEVICES=0,1,2,3 HF_HUB_OFFLINE=1"}


def test_every_round_runs_on_the_training_cpus(finished: Node) -> None:
    assert {line for line in finished.lines() if line.startswith("taskset ")} == {"taskset 0-47,96-143"}


def test_the_report_comes_with_the_hold(finished: Node) -> None:
    assert (finished.state / "learning_rates_report.md").exists()


def test_a_start_after_hold_runs_nothing(finished: Node) -> None:
    before = finished.lines()
    assert (start(finished), finished.lines()) == (0, before)


def test_a_start_after_hold_says_why_it_does_nothing(finished: Node) -> None:
    start(finished)
    last = (finished.state / "chain.log").read_text(encoding="utf-8").splitlines()[-1]
    assert "HOLD present" in last


KILL_POINTS = [
    "sampling",
    "slices",
    "held_out_step2_v0",
    "round_step2_A_5e-5",
    "build_step2_C_w4",
    "dry_run_step2_C_w1",
    "round_step2_C_w1_1e-4",
    "held_out_step2_B2_2e-5",
    "rank_B2",
    "report",
]


def killed(node: Node, point: str) -> list[int]:
    node.set(f"kill_{point}")
    return supervise(node)


@pytest.mark.parametrize("point", KILL_POINTS)
def test_every_kill_point_is_reached_and_kills_the_driver(node: Node, point: str) -> None:
    assert killed(node, point)[0] == -9


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_is_resumed_by_the_next_start(node: Node, point: str) -> None:
    assert killed(node, point)[-1] == 0 and (node.state / "HOLD").exists()


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_trains_every_round_to_its_end_once(node: Node, point: str) -> None:
    killed(node, point)
    trained = [line.removeprefix("trained ") for line in node.lines() if line.startswith("trained ")]
    assert sorted(trained) == sorted(variant.run_name for variant in STEP_VARIANTS)


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_never_evaluates_a_missing_adapter_or_trains_on_missing_data(node: Node, point: str) -> None:
    killed(node, point)
    assert [line for line in node.lines() if line.startswith("MISSING")] == []


@pytest.mark.parametrize(
    ("point", "run"), [("round_step2_A_5e-5", "step2_A_5e-5"), ("round_step2_C_w1_1e-4", "step2_C_w1_1e-4")]
)
def test_a_round_killed_mid_training_restarts_into_a_fresh_output(node: Node, point: str, run: str) -> None:
    killed(node, point)
    aside = list((node.workspace / "checkpoints").glob(f"{run}.interrupted_*"))
    assert len(aside) == 1


def test_a_slicing_killed_midway_is_moved_aside_before_slicing_again(node: Node) -> None:
    killed(node, "slices")
    assert len(list((node.workspace / "runs" / SHARED_RUN).glob("slices.interrupted_*"))) == 1


def test_a_dead_sampling_loop_is_started_again_through_arm_loop(node: Node) -> None:
    node.set("fail_dead_loop", "1")
    supervise(node)
    assert sum(line.startswith("arm_loop.sh ") for line in node.lines()) == 2


def test_a_failing_round_is_retried_by_the_next_start(node: Node) -> None:
    node.set("fail_round_step2_A_2e-5", "2")
    assert supervise(node) == [1, 1, 0] and (node.state / "HOLD").exists()


def test_a_round_failing_three_times_stops_the_chain(node: Node) -> None:
    node.set("fail_round_step2_A_2e-5", "3")
    assert (supervise(node), node.stopped().split(" ", 1)[1]) == ([1, 1, 1, 0], "step round_A_2e-5 failed 3 times\n")


def test_a_health_stop_of_the_shared_sampling_stops_the_chain(node: Node) -> None:
    node.set("health_stop")
    supervise(node)
    assert "stopped on its health check" in node.stopped()


def test_without_a_mode_nothing_starts(tmp_path: Path) -> None:
    node = make_node(tmp_path, mode=False)
    assert (supervise(node), node.lines()) == ([0], [])


def test_without_a_mode_the_chain_says_where_the_mode_goes(tmp_path: Path) -> None:
    node = make_node(tmp_path, mode=False)
    supervise(node)
    assert "no sampling mode: copy the chosen mode" in node.stopped()


def test_a_refused_mode_stops_the_chain_before_anything_runs(node: Node) -> None:
    node.set("mode_refused")
    supervise(node)
    assert (node.steps(), "is refused" in node.stopped()) == (["learning_rate_step.py check-mode"], True)


def test_a_mode_changed_after_the_step_began_stops_the_chain(node: Node) -> None:
    node.set("kill_slices")
    start(node)
    mode = node.state / "mode.toml"
    mode.write_text(mode.read_text(encoding="utf-8").replace("= 32", "= 64"), encoding="utf-8")
    supervise(node)
    assert "differs from the mode the step began with" in node.stopped()


def test_servers_that_kept_dying_in_a_held_out_run_stop_the_chain(node: Node) -> None:
    node.set("fail_held_out_step2_A_1e-4", "1")
    node.set("exit_held_out_step2_A_1e-4", "4")
    supervise(node)
    assert "held-out run step2_A_1e-4: the servers kept dying" in node.stopped()


def test_gpu_memory_in_use_stops_the_chain_before_training_though_no_process_is_listed(node: Node) -> None:
    node.set("gpu_memory", "0, 1\n1, 20480\n2, 1\n3, 1\n")
    supervise(node)
    assert ("GPU 1 20480 MiB" in node.stopped(), any(line.startswith("grpo_phase") for line in node.lines())) == (
        True,
        False,
    )


def test_gpus_reading_their_idle_memory_are_free(node: Node) -> None:
    node.set("gpu_memory", "0, 1\n1, 1\n2, 99\n3, 1\n")
    assert supervise(node) == [0]


def test_a_gpu_count_other_than_four_stops_the_chain(node: Node) -> None:
    node.set("gpu_memory", "0, 1\n1, 1\n2, 1\n")
    supervise(node)
    assert "reads not 4 GPUs" in node.stopped()


def test_a_held_out_run_leaving_states_without_a_tree_is_resumed_by_the_next_start(node: Node) -> None:
    node.set("fail_complete_held_out_step2_A_5e-5", "1")
    supervise(node)
    assert node.lines().count("held_out_evaluate.py step2_A_5e-5") == 2


def test_a_held_out_run_leaving_states_without_a_tree_is_not_done_until_complete(node: Node) -> None:
    node.set("fail_complete_held_out_step2_A_5e-5", "1")
    assert supervise(node) == [1, 0] and (node.state / "HOLD").exists()


def test_the_slicing_waits_for_the_finished_loops_process_to_exit(node: Node) -> None:
    node.set("live_loop")
    assert (supervise(node), "SLICED BESIDE A LIVE LOOP" in node.lines()) == ([0], False)


def test_a_live_sampling_loop_is_not_started_again(node: Node) -> None:
    node.set("live_loop")
    supervise(node)
    assert sum(line.startswith("arm_loop.sh ") for line in node.lines()) == 1


def test_arm_loop_failing_three_times_stops_the_chain(node: Node) -> None:
    node.set("fail_sampling", "3")
    assert (supervise(node), node.stopped().split(" ", 1)[1]) == ([0], "step s1_sampling_start failed 3 times\n")


def test_arm_loop_failing_twice_is_tried_again_by_the_driver(node: Node) -> None:
    node.set("fail_sampling", "2")
    assert supervise(node) == [0] and (node.state / "HOLD").exists()


def test_a_background_build_alive_across_a_restart_is_waited_for_not_started_again(node: Node) -> None:
    node.set("slow_build_step2_C_w1", "3")
    node.set("fail_round_step2_A_2e-5", "1")
    codes = supervise(node)
    assert (codes, node.lines().count("build step2_C_w1")) == ([1, 0], 1)


def test_a_background_build_that_failed_is_built_again_before_c_trains(node: Node) -> None:
    node.set("fail_build_step2_C_w1", "1")
    supervise(node)
    lines = node.lines()
    assert (
        lines.count("build step2_C_w1"),
        lines.index("dry run step2_C_w1") > lines.index("failed at build_step2_C_w1"),
    ) == (2, True)


def test_servers_failing_to_start_before_a_held_out_run_are_retried(node: Node) -> None:
    node.set("fail_servers", "1")
    assert supervise(node) == [1, 0] and (node.state / "HOLD").exists()


def test_a_round_finished_before_its_driver_died_is_kept_not_trained_again(node: Node) -> None:
    node.set("kill_after_round_step2_A_5e-5")
    supervise(node)
    aside = list((node.workspace / "checkpoints").glob("step2_A_5e-5.interrupted_*"))
    assert (node.lines().count("trained step2_A_5e-5"), aside) == (1, [])


def test_a_search_config_changed_after_the_step_began_stops_the_chain(node: Node) -> None:
    node.set("kill_slices")
    start(node)
    node.set("search_config_changed")
    supervise(node)
    assert "or its search config differs" in node.stopped()


def test_the_servers_left_up_at_the_end_are_stopped_before_hold(node: Node) -> None:
    node.set("fail_stop", "0")
    supervise(node)
    assert node.steps()[-1] == "stop_model.sh --all"


def test_a_dry_run_planning_no_step_stops_the_chain_before_c_trains(node: Node) -> None:
    node.set("dry_run_steps", "0")
    supervise(node)
    assert ("dry run of step2_C_w1" in node.stopped(), any(line.startswith("train ") for line in node.lines())) == (
        True,
        False,
    )


def test_a_server_stop_refused_stops_the_chain(node: Node) -> None:
    node.set("fail_stop", "1")
    supervise(node)
    assert "stop_model.sh refused" in node.stopped()


def test_background_cpus_beside_the_cpu_lists_stop_the_chain(node: Node) -> None:
    supervise(node, {"FAKE_BACKGROUND_CPUS": "32"})
    assert "the CPU layout must come from the node environment" in node.stopped()


def test_a_start_after_stopped_runs_nothing(node: Node) -> None:
    node.set("health_stop")
    supervise(node)
    before = node.lines()
    assert (start(node), node.lines()) == (0, before)
