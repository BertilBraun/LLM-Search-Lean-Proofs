"""deployment/offline_chain.sh against stand-ins for every command it runs (tests/rl/study_chain_fakes/, shared with the
step-2 driver's test), restarted as supervisord would after any exit but 0: the order of its steps, its resume after a
kill at each step, its stops, the HOLD after the matched subset and the pool subset on the owner's word."""

import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from lean_search.rl.offline_arm import load_offline_arm_config

REPOSITORY = Path(__file__).resolve().parents[2]
SCRIPT = REPOSITORY / "deployment" / "offline_chain.sh"
FAKES = Path(__file__).resolve().parent / "study_chain_fakes"
CONFIG = REPOSITORY / "experiments/configs/grpo/followup/offline/offline_arm.toml"
DEPLOYMENT_FAKES = (
    "environment.sh",
    "fake_common.sh",
    "grpo_loop.sh",
    "stop_model.sh",
    "background.sh",
    "probe_runs.sh",
)
SIDE_LINES = ("taskset ", "torchrun ", "trained ")
RATES = ("5e-5", "1e-4")


@dataclass(frozen=True)
class Node:
    root: Path

    @property
    def state(self) -> Path:
        return self.root / "state"

    @property
    def scenario(self) -> Path:
        return self.root / "scenario"

    @property
    def study_state(self) -> Path:
        """Step 2's driver's state directory, which the offline driver must find idle."""
        return self.root / "study_state"

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

    def chain_log(self) -> str:
        return (self.state / "chain.log").read_text(encoding="utf-8")

    def release_pool(self) -> None:
        """The owner's word for the pool subset, as the operations note says to give it."""
        (self.state / "run_pool").touch()
        (self.state / "HOLD").rename(self.state / "HOLD.after_matched")


def executable(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o755)


def make_node(root: Path) -> Node:
    node = Node(root)
    repository = root / "repository"
    for name in DEPLOYMENT_FAKES:
        executable(FAKES / name, repository / "deployment" / name)
    executable(FAKES / "python", repository / ".venv" / "bin" / "python")
    for name in ("taskset", "nvidia-smi"):
        executable(FAKES / name, root / "bin" / name)
    node.scenario.mkdir(parents=True)
    (node.workspace / "checkpoints" / "data_rewrite_sft_numbered" / "adapter").mkdir(parents=True)
    node.state.mkdir()
    return node


def start(node: Node, script: Path = SCRIPT) -> int:
    environment = os.environ | {
        "OFFLINE_CHAIN_STATE": str(node.state),
        "STUDY_CHAIN_STATE": str(node.study_state),
        "OFFLINE_CHAIN_REPOSITORY": str(node.root / "repository"),
        "OFFLINE_CHAIN_START_SECONDS": "0",
        "OFFLINE_CHAIN_POLL_SECONDS": "0",
        "FAKE_REPOSITORY": str(node.root / "repository"),
        "FAKE_WORKSPACE": str(node.workspace),
        "FAKE_BIN": str(node.root / "bin"),
        "FAKE_SCENARIO": str(node.scenario),
        "FAKE_LOG": str(node.log),
    }
    result = subprocess.run(  # noqa: S603
        ["bash", str(script)], env=environment, start_new_session=True, timeout=300, check=False
    )
    return result.returncode


def supervise(node: Node, limit: int = 12) -> list[int]:
    codes = [start(node)]
    while codes[-1] != 0 and len(codes) < limit:
        codes.append(start(node))
    return codes


def held_out_steps(name: str) -> list[str]:
    return ["grpo_loop.sh servers", f"held_out_evaluate.py {name}", "learning_rate_step.py check-held-out"]


def evaluation_steps(subset: str, rate: str) -> list[str]:
    return [
        f"offline_arm.py probe-list {subset} {rate}",
        f"probe_runs.sh PROBE_CONCURRENCY=112 runs_{subset}.toml",
        f"probe_compare.py pair offline_arm_{subset}",
        f"offline_arm.py report {subset}",
    ]


DATA_STEPS = [
    "offline_arm.py download HF_HUB_OFFLINE=unset HF_HUB_DISABLE_XET=1",
    "offline_arm.py prepare",
    "offline_arm.py walk",
    "offline_arm.py walk",
    "offline_arm.py build",
    "offline_arm.py flat-references",
    "offline_arm.py held-out-config",
]
MATCHED_STEPS = [
    "stop_model.sh --all",
    "dry run matched 5e-5",
    *(f"train matched {rate}" for rate in RATES),
    *held_out_steps("offline_v0_no_reasoning"),
    *(step for rate in RATES for step in held_out_steps(f"offline_arm_matched_{rate}")),
    "offline_arm.py rank matched v0 offline_v0_no_reasoning",
    *evaluation_steps("matched", "5e-5"),
    "stop_model.sh --all",
]
POOL_STEPS = [
    "stop_model.sh --all",
    "dry run pool 5e-5",
    "train pool 5e-5",
    *held_out_steps("offline_arm_pool_5e-5"),
    *evaluation_steps("pool", "5e-5"),
    "stop_model.sh --all",
]


@pytest.fixture
def node(tmp_path: Path) -> Node:
    return make_node(tmp_path)


@pytest.fixture
def finished(tmp_path: Path) -> Node:
    """A node whose driver ran through the matched subset to its HOLD."""
    node = make_node(tmp_path)
    assert supervise(node) == [0]
    return node


@pytest.fixture
def pool_finished(finished: Node) -> Node:
    """The same node after the owner's word and the pool subset."""
    finished.release_pool()
    assert supervise(finished) == [0]
    return finished


def test_a_clean_run_takes_the_data_and_matched_steps_in_order(finished: Node) -> None:
    assert finished.steps() == [*DATA_STEPS, *MATCHED_STEPS]


def test_the_matched_subset_ends_in_a_hold_waiting_for_the_owners_word(finished: Node) -> None:
    assert "waits for the owner's word" in (finished.state / "HOLD").read_text(encoding="utf-8")


def test_the_hold_says_the_servers_are_stopped(finished: Node) -> None:
    assert (finished.state / "HOLD").read_text(encoding="utf-8").rstrip().endswith("the servers are stopped")


def test_a_start_after_the_hold_runs_nothing(finished: Node) -> None:
    before = finished.lines()
    assert (start(finished), finished.lines()) == (0, before)


def test_the_pool_subset_runs_after_the_owners_word(pool_finished: Node) -> None:
    assert pool_finished.steps() == [*DATA_STEPS, *MATCHED_STEPS, *POOL_STEPS]


def test_the_pool_subset_ends_in_the_final_hold(pool_finished: Node) -> None:
    assert "the offline arm is done" in (pool_finished.state / "HOLD").read_text(encoding="utf-8")


def test_the_pool_subset_trains_only_at_the_rate_the_matched_subset_chose(node: Node) -> None:
    node.set("chosen_rate", "1e-4")
    supervise(node)
    node.release_pool()
    supervise(node)
    assert [line for line in node.lines() if line.startswith("train pool")] == ["train pool 1e-4"]


def test_the_matched_probe_run_takes_the_chosen_rates_adapter(node: Node) -> None:
    node.set("chosen_rate", "1e-4")
    supervise(node)
    adapter = node.workspace / "checkpoints" / "offline_arm_matched_1e-4" / "adapter"
    assert f'policy_adapter = "{adapter}"' in (node.state / "runs_matched.toml").read_text(encoding="utf-8")


def test_every_training_runs_on_the_four_gpus_offline(pool_finished: Node) -> None:
    launches = {line for line in pool_finished.lines() if line.startswith("torchrun ")}
    assert launches == {"torchrun on CUDA_VISIBLE_DEVICES=0,1,2,3 HF_HUB_OFFLINE=1"}


def test_every_training_runs_on_the_training_cpus(pool_finished: Node) -> None:
    assert {line for line in pool_finished.lines() if line.startswith("taskset ")} == {"taskset 0-47,96-143"}


def test_the_first_steps_throughput_reaches_the_chain_log(finished: Node) -> None:
    assert "training matched_5e-5, throughput: " in finished.chain_log()


def test_every_held_out_run_samples_with_the_no_reasoning_loop_config(pool_finished: Node) -> None:
    configs = {
        path.read_text(encoding="utf-8").strip()
        for path in (pool_finished.workspace / "runs" / "held_out_evaluations").glob("*/loop_config.txt")
    }
    assert configs == {str(pool_finished.state / "held_out_loop.toml")}


def test_the_servers_for_held_out_runs_start_from_the_no_reasoning_loop_config(pool_finished: Node) -> None:
    configs = set((pool_finished.workspace / "servers_loop_configs").read_text(encoding="utf-8").split())
    assert configs == {str(pool_finished.state / "held_out_loop.toml")}


def test_v0s_held_out_run_is_shared_by_both_subsets(pool_finished: Node) -> None:
    assert sum(line == "held_out_evaluate.py offline_v0_no_reasoning" for line in pool_finished.lines()) == 1


KILL_POINTS = [
    "download",
    "walk",
    "build",
    "flat_references",
    "train_matched_5e-5",
    "held_out_offline_v0_no_reasoning",
    "rank_matched",
    "probe",
    "report",
]
POOL_KILL_POINTS = ["train_pool_5e-5", "held_out_offline_arm_pool_5e-5", "probe", "report"]


def killed(node: Node, point: str) -> list[int]:
    node.set(f"kill_{point}")
    return supervise(node)


def killed_in_pool(node: Node, point: str) -> list[int]:
    supervise(node)
    node.release_pool()
    return killed(node, point)


@pytest.mark.parametrize("point", KILL_POINTS)
def test_every_kill_point_is_reached_and_kills_the_driver(node: Node, point: str) -> None:
    assert killed(node, point)[0] == -9


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_is_resumed_to_the_hold(node: Node, point: str) -> None:
    assert killed(node, point)[-1] == 0 and (node.state / "HOLD").exists()


@pytest.mark.parametrize("point", KILL_POINTS)
def test_a_kill_at_any_step_trains_every_rate_to_its_end_once(node: Node, point: str) -> None:
    killed(node, point)
    trained = sorted(line.removeprefix("trained ") for line in node.lines() if line.startswith("trained "))
    assert trained == sorted(f"offline_arm_matched_{rate}" for rate in RATES)


@pytest.mark.parametrize("point", POOL_KILL_POINTS)
def test_a_kill_in_the_pool_subset_is_resumed_to_the_final_hold(node: Node, point: str) -> None:
    killed_in_pool(node, point)
    assert "the offline arm is done" in (node.state / "HOLD").read_text(encoding="utf-8")


@pytest.mark.parametrize("point", [*KILL_POINTS, *POOL_KILL_POINTS])
def test_a_kill_never_evaluates_a_missing_adapter_or_overwrites_an_output(node: Node, point: str) -> None:
    if point in POOL_KILL_POINTS:
        killed_in_pool(node, point)
    else:
        killed(node, point)
    assert [line for line in node.lines() if line.startswith(("MISSING", "OUTPUT EXISTS"))] == []


def test_a_training_killed_midway_restarts_into_a_fresh_output(node: Node) -> None:
    killed(node, "train_matched_5e-5")
    assert len(list((node.workspace / "checkpoints").glob("offline_arm_matched_5e-5.interrupted_*"))) == 1


def test_a_training_that_finished_before_failing_at_its_teardown_is_kept(node: Node) -> None:
    node.set("fail_after_train_matched_1e-4", "1")
    supervise(node)
    assert sum(line == "train matched 1e-4" for line in node.lines()) == 1


def test_a_start_after_the_detached_data_steps_records_the_walk_before_building(node: Node) -> None:
    for name in ("download", "prepare", "walk"):
        (node.state / f"done_{name}").touch()
    (node.state / "timings.tsv").write_text("download\t1\t2\nprepare\t2\t3\nwalk\t3\t4\n", encoding="utf-8")
    supervise(node)
    assert node.steps()[:2] == ["offline_arm.py walk", "offline_arm.py build"]


@pytest.fixture
def data_steps_process(node: Node) -> Iterator[subprocess.Popen[bytes]]:
    process = subprocess.Popen(["bash", "-c", "exec -a offline_data_steps.sh sleep 60"])  # noqa: S603, S607
    (node.state / "data_steps.pid").write_text(f"{process.pid}\n", encoding="utf-8")
    yield process
    process.kill()
    process.wait()


def test_live_detached_data_steps_stop_the_driver(node: Node, data_steps_process: subprocess.Popen[bytes]) -> None:
    assert (supervise(node), node.lines()) == ([0], [])


def test_live_detached_data_steps_are_named_in_the_stop(
    node: Node, data_steps_process: subprocess.Popen[bytes]
) -> None:
    supervise(node)
    assert "detached data steps" in node.stopped()


def test_a_pid_file_naming_another_process_does_not_stop_the_driver(node: Node) -> None:
    (node.state / "data_steps.pid").write_text(f"{os.getpid()}\n", encoding="utf-8")
    assert supervise(node) == [0] and (node.state / "HOLD").exists()


def test_a_pid_file_naming_a_finished_process_leaves_no_error_in_the_log(node: Node) -> None:
    (node.state / "data_steps.pid").write_text("999999999\n", encoding="utf-8")
    supervise(node)
    assert "No such file" not in node.chain_log()


def test_a_driver_without_its_helpers_stops_instead_of_restarting(node: Node, tmp_path: Path) -> None:
    lonely = tmp_path / "lonely" / "offline_chain.sh"
    executable(SCRIPT, lonely)
    assert (start(node, lonely), "no chain_helpers.sh" in node.stopped()) == (0, True)


def older_helpers(directory: Path) -> None:
    """chain_helpers.sh as it was before other_chain_idle, beside a driver's copy."""
    text = (REPOSITORY / "deployment" / "chain_helpers.sh").read_text(encoding="utf-8")
    start = text.index("other_chain_idle() {")
    end = text.index("\n}\n", start) + 3
    (directory / "chain_helpers.sh").write_text(text[:start] + text[end:], encoding="utf-8")


def test_a_driver_beside_older_helpers_stops_before_anything_runs(node: Node, tmp_path: Path) -> None:
    driver = tmp_path / "older" / "offline_chain.sh"
    executable(SCRIPT, driver)
    older_helpers(driver.parent)
    assert (start(node, driver), "chain_helpers.sh is older than the driver" in node.stopped(), node.lines()) == (
        0,
        True,
        [],
    )


def test_a_failing_walk_is_retried_by_the_next_start(node: Node) -> None:
    node.set("fail_walk", "2")
    assert supervise(node) == [1, 1, 0]


def test_a_walk_failing_three_times_stops_the_chain(node: Node) -> None:
    node.set("fail_walk", "3")
    supervise(node)
    assert "step walk failed 3 times" in node.stopped()


@pytest.mark.parametrize(
    ("scenario", "content", "stop"),
    [
        ("dry_run_exit_matched", "1", "the dry run of matched failed"),
        ("dry_run_exit_matched", "3", "would not fit the host's memory"),
        ("fail_rank_matched", "1", "the ranking of matched failed"),
        ("fail_probe_list", "1", "probe-list failed for matched"),
        ("fail_probe_compare", "1", "probe_compare.py failed for matched"),
        ("fail_report", "1", "the report of matched failed"),
        ("probe_exit", "3", "rejected"),
        ("probe_exit", "4", "kept dying"),
        ("fail_stop", "1", "stop_model.sh refused"),
        ("gpu_memory", "0, 1\n1, 9000\n2, 1\n3, 1\n", "the GPUs stay in use"),
    ],
)
def test_a_failed_check_stops_the_chain_with_its_reason(node: Node, scenario: str, content: str, stop: str) -> None:
    node.set(scenario, content)
    supervise(node)
    assert stop in node.stopped()


def test_a_probe_run_that_failed_otherwise_is_resumed(node: Node) -> None:
    node.set("probe_exit", "1")
    assert supervise(node) == [1, 0]


def assignment(text: str, name: str) -> str:
    found = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
    assert found is not None
    return found.group(1)


def test_the_drivers_arm_name_is_the_configs() -> None:
    assert assignment(SCRIPT.read_text(encoding="utf-8"), "arm") == load_offline_arm_config(CONFIG).name


def test_the_drivers_rates_are_the_configs() -> None:
    rates = assignment(SCRIPT.read_text(encoding="utf-8"), "rates").strip("()").split()
    assert tuple(rates) == load_offline_arm_config(CONFIG).learning_rates


def test_the_drivers_v0_adapter_is_the_configs_starting_adapter() -> None:
    adapter = assignment(SCRIPT.read_text(encoding="utf-8"), "v0_adapter").strip('"')
    expected = load_offline_arm_config(CONFIG).initial_policy_adapter
    assert adapter.replace("${LEAN_SEARCH_CHECKPOINTS}", "/workspace/checkpoints") == expected


def test_the_drivers_gate_run_is_the_reports() -> None:
    script = (REPOSITORY / "experiments" / "offline_arm.py").read_text(encoding="utf-8")
    assert f'GATE_RUN = "{assignment(SCRIPT.read_text(encoding="utf-8"), "gate_run")}"' in script


def test_a_retried_training_logs_its_own_attempts_throughput(node: Node) -> None:
    node.set("fail_train_matched_5e-5", "1")
    supervise(node)
    lines = [line for line in node.chain_log().splitlines() if "training matched_5e-5, throughput: " in line]
    assert '"attempt": 2' in lines[-1]


def study_chain_running(node: Node, marker: str = "") -> None:
    """Step 2's driver has started; `marker` (HOLD or STOPPED) where it stands."""
    node.study_state.mkdir(exist_ok=True)
    (node.study_state / "chain.log").write_text("driver start\n", encoding="utf-8")
    if marker:
        (node.study_state / marker).write_text("held\n", encoding="utf-8")


def test_a_running_step_2_stops_the_offline_chain_before_any_server_or_gpu_action(node: Node) -> None:
    study_chain_running(node)
    supervise(node)
    assert ("the study chain" in node.stopped(), node.steps()) == (True, DATA_STEPS)


@pytest.mark.parametrize("marker", ["HOLD", "STOPPED"])
def test_step_2_at_hold_or_stopped_lets_the_offline_chain_run(node: Node, marker: str) -> None:
    study_chain_running(node, marker)
    assert supervise(node) == [0] and node.steps() == [*DATA_STEPS, *MATCHED_STEPS]


def test_a_prepared_but_unstarted_step_2_does_not_stop_the_offline_chain(node: Node) -> None:
    node.study_state.mkdir()
    (node.study_state / "mode.toml").write_text("", encoding="utf-8")
    assert supervise(node) == [0] and node.steps() == [*DATA_STEPS, *MATCHED_STEPS]


def test_the_o1_switch_while_step_2_runs_stops_the_offline_chain(finished: Node) -> None:
    study_chain_running(finished)
    finished.release_pool()
    supervise(finished)
    assert ("the study chain" in finished.stopped(), finished.steps()) == (True, [*DATA_STEPS, *MATCHED_STEPS])
