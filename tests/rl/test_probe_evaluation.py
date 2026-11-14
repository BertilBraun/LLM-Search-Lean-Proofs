import asyncio
import dataclasses
import json
import os
import subprocess
import sys
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fake_vllm import FakeVllmServer

from lean_search.data import Problem, Split
from lean_search.expert_iteration.loop_config import ServerEndpoint, ServingConfig
from lean_search.policy.config import StepLogProbability
from lean_search.policy.serving_lock import (
    ServingBusyError,
    exit_while_served,
    lock_holder,
    serving_lock,
    serving_lock_path,
)
from lean_search.rl.evaluation import EvaluationKind, EvaluationProblem, EvaluationSummary
from lean_search.rl.loop_config import EvaluationTarget, load_loop_config
from lean_search.rl.probe_evaluation import (
    NO_VALUE_VERSION,
    AutomationConstant,
    ProbeCheckpoint,
    ProbeEvaluationConfig,
    ProbeRunStart,
    RunEnvironment,
    ServedWeights,
    StratumStops,
    ValueFreePriority,
    adapter_digest,
    anchor_problem,
    default_value_version,
    discard_spoiled_results,
    keep_merges,
    mark_spoiled,
    probe_run_config,
    remove_stale_merges,
    resolve_value_adapter,
    run_directory,
    run_identity,
    run_record,
    running_loops,
    serve_checkpoint,
    start_session,
    stops_by_stratum,
)
from lean_search.search import Accounting, PriorityKind, RunConfig, SearchResult, StopReason, load_run_config
from lean_search.search.records import from_json_object, to_json

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPOSITORY_DIRECTORY / "experiments/configs/grpo/followup/probe_evaluation.toml"
CONFIG = from_json_object(ProbeEvaluationConfig, tomllib.loads(CONFIG_PATH.read_text(encoding="utf-8")))
LOOP = load_loop_config(REPOSITORY_DIRECTORY / CONFIG.loop_config)
TEMPLATE = load_run_config(REPOSITORY_DIRECTORY / CONFIG.search_config)
TARGET = EvaluationTarget(16, 7200.0, 32)
ROW_2 = ValueFreePriority(
    1.0, StepLogProbability.COMPLETION, (AutomationConstant(StepLogProbability.COMPLETION, -2.8, calibrated=True),)
)
BLOCK_SUM = ValueFreePriority(
    1.0, StepLogProbability.BLOCK_SUM, (AutomationConstant(StepLogProbability.BLOCK_SUM, -5.0, calibrated=True),)
)


def checkpoint(
    arm: str = "v0", policy_digest: str = "p" * 64, value_adapter: str = "/v0", value_digest: str = "v" * 64
) -> ProbeCheckpoint:
    return ProbeCheckpoint(arm, 0, "/policy", policy_digest, value_adapter, value_digest, 0, 0, 0)


def searched(
    expansions: int = 16, wall_seconds: float = 7200.0, value_free: ValueFreePriority | None = None
) -> RunConfig:
    target = EvaluationTarget(expansions, wall_seconds, 32)
    return probe_run_config(TEMPLATE, LOOP.serving, target, value_free, False)


START = ProbeRunStart(
    run_identity(checkpoint(), searched()),
    False,
    checkpoint(),
    "search.toml",
    "c" * 64,
    56,
    7200.0,
    16,
    "probe.jsonl",
    "",
)
ENVIRONMENT = RunEnvironment("node", "leanprover/lean4:v4.9.0", "0.11.0", "2.8.0")


@pytest.mark.parametrize(("value", "adapter"), [("none", ""), ("v0", "/v0"), ("/value/adapter", "/value/adapter")])
def test_the_value_choice_names_its_adapter(value: str, adapter: str) -> None:
    assert resolve_value_adapter(value, "/v0") == adapter


def test_a_relative_value_adapter_path_is_made_absolute() -> None:
    assert Path(resolve_value_adapter("value/adapter", "/v0")).is_absolute()


@pytest.mark.parametrize(("value", "version"), [("none", NO_VALUE_VERSION), ("v0", 0), ("/value/adapter", None)])
def test_the_value_choice_has_a_default_label_unless_given_by_path(value: str, version: int | None) -> None:
    assert default_value_version(value) == version


def test_without_a_value_model_the_search_asks_no_value_server() -> None:
    assert probe_run_config(TEMPLATE, LOOP.serving, TARGET, ROW_2, False).value.model == ""


def test_completion_steps_with_minus_2_8_reproduce_row_2s_search() -> None:
    config = probe_run_config(TEMPLATE, LOOP.serving, TARGET, ROW_2, False)
    expected = dataclasses.replace(
        TEMPLATE.priority,
        kind=PriorityKind.CUMULATIVE_LOG_PROBABILITY,
        length_exponent=1.0,
        automation_log_probability=-2.8,
    )
    assert (config.priority, config.policy.step_log_probability) == (expected, StepLogProbability.COMPLETION)


def test_a_value_free_run_carries_its_step_log_probability_into_the_policy() -> None:
    config = probe_run_config(TEMPLATE, LOOP.serving, TARGET, BLOCK_SUM, False)
    assert config.policy.step_log_probability == StepLogProbability.BLOCK_SUM


def test_a_value_free_run_takes_the_automation_constant_of_its_setting() -> None:
    assert (
        probe_run_config(TEMPLATE, LOOP.serving, TARGET, BLOCK_SUM, False).priority.automation_log_probability == -5.0
    )


def test_a_setting_without_its_own_automation_constant_is_refused() -> None:
    without = dataclasses.replace(ROW_2, step_log_probability=StepLogProbability.BLOCK_MEAN)
    with pytest.raises(ValueError, match="No automation constant"):
        probe_run_config(TEMPLATE, LOOP.serving, TARGET, without, False)


def test_a_placeholder_automation_constant_is_refused() -> None:
    placeholder = ValueFreePriority(
        1.0, StepLogProbability.BLOCK_SUM, (AutomationConstant(StepLogProbability.BLOCK_SUM, -5.65, calibrated=False),)
    )
    with pytest.raises(ValueError, match="placeholder"):
        probe_run_config(TEMPLATE, LOOP.serving, TARGET, placeholder, False)


def test_the_shipped_value_free_search_waits_for_its_block_sum_calibration() -> None:
    with pytest.raises(ValueError, match="placeholder"):
        probe_run_config(TEMPLATE, LOOP.serving, TARGET, CONFIG.value_free_priority, False)


def test_the_identity_names_the_step_log_probability() -> None:
    assert "steps block_sum" in run_identity(
        checkpoint(value_adapter="", value_digest=""), searched(value_free=BLOCK_SUM)
    )


def test_with_a_value_model_the_search_asks_the_value_servers() -> None:
    value = probe_run_config(TEMPLATE, LOOP.serving, TARGET, None, False).value
    assert value.server_urls == tuple(server.url for server in LOOP.serving.value_servers)


def test_with_a_value_model_the_search_keeps_the_templates_priority() -> None:
    assert probe_run_config(TEMPLATE, LOOP.serving, TARGET, None, False).priority == TEMPLATE.priority


def test_the_probe_searches_at_its_budget_wall_cap_and_concurrency() -> None:
    config = probe_run_config(TEMPLATE, LOOP.serving, TARGET, None, False)
    assert (config.search.max_expansions, config.search.max_wall_seconds, config.lean.concurrency) == (16, 7200.0, 32)


def test_a_run_with_its_own_search_config_keeps_that_configs_budget() -> None:
    template = dataclasses.replace(TEMPLATE, search=dataclasses.replace(TEMPLATE.search, max_expansions=1024))
    assert probe_run_config(template, LOOP.serving, TARGET, None, True).search.max_expansions == 1024


def test_the_probe_searches_without_harvesting_or_exploration() -> None:
    search = probe_run_config(TEMPLATE, LOOP.serving, TARGET, None, False).search
    assert (search.harvest.enabled, search.exploration.enabled) == (False, False)


def test_a_run_lies_where_the_probe_rating_looks(tmp_path: Path) -> None:
    assert run_directory(tmp_path, "arm_a_phase_08").name.startswith("probe_")


@pytest.mark.parametrize(
    "other",
    [checkpoint(arm="A"), checkpoint(policy_digest="q" * 64), checkpoint(value_adapter="", value_digest="")],
    ids=["another arm", "another policy", "no value model"],
)
def test_checkpoints_that_differ_have_different_identities(other: ProbeCheckpoint) -> None:
    assert run_identity(other, searched()) != START.identity


@pytest.mark.parametrize(
    "config",
    [searched(expansions=1024), searched(wall_seconds=14400.0), searched(value_free=ROW_2)],
    ids=["another budget", "a doubled cap", "another search"],
)
def test_one_checkpoint_searched_otherwise_has_another_identity(config: RunConfig) -> None:
    assert run_identity(checkpoint(), config) != START.identity


@pytest.mark.parametrize(
    ("policy_digest", "value_digest", "problems"),
    [("q" * 64, "v" * 64, 0), ("p" * 64, "w" * 64, 0), ("p" * 64, "v" * 64, 200)],
    ids=["another policy", "another value model", "a pilot"],
)
def test_only_v0_with_value_v0_on_the_whole_probe_can_be_the_anchor(
    policy_digest: str, value_digest: str, problems: int
) -> None:
    other = dataclasses.replace(checkpoint(policy_digest=policy_digest, value_digest=value_digest), problems=problems)
    assert anchor_problem(other, "p" * 64, "v" * 64, own_search=False) is not None


def test_v0_with_value_v0_at_the_standard_settings_is_the_anchor() -> None:
    assert anchor_problem(checkpoint(), "p" * 64, "v" * 64, own_search=False) is None


def test_another_file_beside_the_adapter_leaves_its_digest(tmp_path: Path) -> None:
    (tmp_path / "adapter_model.safetensors").write_bytes(b"weights")
    (tmp_path / "adapter_config.json").write_text("{}", encoding="utf-8")
    first = adapter_digest(tmp_path)
    (tmp_path / "notes.txt").write_text("evaluated", encoding="utf-8")
    assert adapter_digest(tmp_path) == first


def test_a_rewritten_adapter_file_changes_the_digest(tmp_path: Path) -> None:
    (tmp_path / "adapter_model.safetensors").write_bytes(b"first")
    first = adapter_digest(tmp_path)
    (tmp_path / "adapter_model.safetensors").write_bytes(b"second")
    assert adapter_digest(tmp_path) != first


def summary(problems: int, stops: int) -> EvaluationSummary:
    return EvaluationSummary(
        EvaluationKind.PROBE, "probe_x", 0, 0, problems, 0, (), 16, 0, 0, 0.0, 0.0, "", "", 0, 0, stops
    )


@pytest.mark.parametrize(("stops", "accepted"), [(19, True), (20, False), (21, False)])
def test_a_run_is_accepted_only_strictly_below_the_wall_clock_stop_share(stops: int, accepted: bool) -> None:
    assert run_record(START, ENVIRONMENT, summary(2000, stops), (), 0.01).accepted == accepted


def test_the_shipped_acceptance_rule_is_under_one_percent() -> None:
    assert CONFIG.max_wall_clock_stop_share == 0.01


def result(name: str, stop_reason: StopReason) -> SearchResult:
    return SearchResult(name, stop_reason == StopReason.PROVED, stop_reason, None, (), (), Accounting(), None, 0, 1)


def test_wall_clock_stops_are_counted_per_stratum() -> None:
    problems = [
        EvaluationProblem(Problem(f"s.t{number}", Split.VALID, "", "", "", ""), stratum)
        for number, stratum in enumerate(["0-499", "0-499", "4500+"])
    ]
    results = [
        result("s.t0", StopReason.WALL_CLOCK_BUDGET),
        result("s.t1", StopReason.PROVED),
        result("s.t2", StopReason.WALL_CLOCK_BUDGET),
    ]
    assert stops_by_stratum(problems, results) == (StratumStops("0-499", 2, 1), StratumStops("4500+", 1, 1))


def test_a_live_loop_process_is_found(tmp_path: Path) -> None:
    (tmp_path / "arm_a").mkdir()
    (tmp_path / "arm_a" / "loop.pid").write_text(str(os.getpid()), encoding="utf-8")
    assert running_loops(tmp_path).running == (f"arm_a (pid {os.getpid()})",)


def test_a_loop_whose_process_ended_is_not_running(tmp_path: Path) -> None:
    ended = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    (tmp_path / "arm_a").mkdir()
    (tmp_path / "arm_a" / "loop.pid").write_text(ended.stdout.strip(), encoding="utf-8")
    assert running_loops(tmp_path).running == ()


def test_an_empty_loop_pid_counts_as_not_running(tmp_path: Path) -> None:
    (tmp_path / "arm_a").mkdir()
    (tmp_path / "arm_a" / "loop.pid").write_text("", encoding="utf-8")
    assert running_loops(tmp_path).running == ()


def test_an_empty_loop_pid_is_reported(tmp_path: Path) -> None:
    (tmp_path / "arm_a").mkdir()
    (tmp_path / "arm_a" / "loop.pid").write_text("", encoding="utf-8")
    assert len(running_loops(tmp_path).notes) == 1


def test_a_held_lock_names_its_holder(tmp_path: Path) -> None:
    with serving_lock(tmp_path / "serving.lock"):
        assert lock_holder(tmp_path / "serving.lock") == str(os.getpid())


def test_a_command_that_swaps_weights_exits_while_the_node_lock_is_held(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEAN_SEARCH_CHECKPOINTS", str(tmp_path))
    with serving_lock(serving_lock_path(tmp_path)), pytest.raises(SystemExit, match="holds the model servers"):
        exit_while_served("publish_weights.py")


def test_a_released_lock_has_no_holder(tmp_path: Path) -> None:
    with serving_lock(tmp_path / "serving.lock"):
        pass
    assert lock_holder(tmp_path / "serving.lock") is None


def write_results(path: Path, names: list[str]) -> None:
    with path.open("a", encoding="utf-8") as handle:
        for name in names:
            handle.write(json.dumps({"problem_name": name}) + "\n")


def spoiled_run(tmp_path: Path) -> Path:
    """Two results of a clean session, then a session a loop spoiled after two more."""
    results = tmp_path / "results.jsonl"
    start_session(tmp_path, checkpoint(), results)
    write_results(results, ["s.a", "s.b"])
    spoiled = start_session(tmp_path, checkpoint(), results)
    write_results(results, ["s.c", "s.d"])
    mark_spoiled(tmp_path, spoiled)
    return results


def test_a_spoiled_sessions_results_are_discarded_on_resume(tmp_path: Path) -> None:
    results = spoiled_run(tmp_path)
    discard_spoiled_results(tmp_path, results, tmp_path / "trees")
    assert [json.loads(line)["problem_name"] for line in results.read_text().splitlines()] == ["s.a", "s.b"]


def test_a_discarded_session_is_not_discarded_twice(tmp_path: Path) -> None:
    results = spoiled_run(tmp_path)
    discard_spoiled_results(tmp_path, results, tmp_path / "trees")
    start_session(tmp_path, checkpoint(), results)
    write_results(results, ["s.c"])
    assert discard_spoiled_results(tmp_path, results, tmp_path / "trees") == 0


def test_a_merge_left_by_a_dead_run_is_removed(tmp_path: Path) -> None:
    (tmp_path / "left").mkdir()
    remove_stale_merges(tmp_path)
    assert not (tmp_path / "left").exists()


def test_a_kept_merge_stays(tmp_path: Path) -> None:
    (tmp_path / "kept").mkdir()
    keep_merges([tmp_path / "kept"])
    remove_stale_merges(tmp_path)
    assert (tmp_path / "kept").exists()


def test_a_second_holder_of_the_serving_lock_is_refused(tmp_path: Path) -> None:
    with (
        serving_lock(tmp_path / "serving.lock"),
        pytest.raises(ServingBusyError),
        serving_lock(tmp_path / "serving.lock"),
    ):
        pass


@dataclass(frozen=True)
class ServeHistory:
    served: tuple[ServedWeights, ...]
    policy_reloads: tuple[tuple[str, ...], ...]
    value_reloads: tuple[str, ...]
    merged_contents: tuple[str, ...]


@pytest.fixture(scope="module")
def history(tmp_path_factory: pytest.TempPathFactory) -> Iterator[ServeHistory]:
    """Three runs on fake servers: policy and value, then no value model, then the first checkpoint again with its
    policy adapter rewritten at the same path in between."""
    root = tmp_path_factory.mktemp("serve")
    policy_servers = [FakeVllmServer(), FakeVllmServer()]
    value_server = FakeVllmServer()
    serving = ServingConfig(
        "policy-base",
        "value-base",
        tuple(ServerEndpoint(f"policy-gpu{index}", index, server.url) for index, server in enumerate(policy_servers)),
        (ServerEndpoint("value-gpu0", 0, value_server.url),),
    )
    merged: list[str] = []

    def merge(base_model: str, adapter: Path, output: Path) -> None:
        content = (adapter / "adapter_model.safetensors").read_text(encoding="utf-8")
        merged.append(content)
        output.mkdir(parents=True)
        (output / "model.safetensors").write_text(f"{base_model} + {content}", encoding="utf-8")

    policy, value = root / "policy", root / "value"
    for directory, content in ((policy, "policy one"), (value, "value one")):
        directory.mkdir()
        (directory / "adapter_model.safetensors").write_text(content, encoding="utf-8")

    def run(value_adapter: Path | None) -> ServedWeights:
        chosen = ProbeCheckpoint(
            "A",
            8,
            str(policy),
            adapter_digest(policy),
            str(value_adapter or ""),
            adapter_digest(value_adapter) if value_adapter else "",
            0,
            8,
            1 if value_adapter else NO_VALUE_VERSION,
        )
        return asyncio.run(serve_checkpoint(serving, chosen, root / "weights", merge))

    first = run(value)
    second = run(None)
    (policy / "adapter_model.safetensors").write_text("policy two", encoding="utf-8")
    third = run(value)
    yield ServeHistory(
        (first, second, third),
        tuple(tuple(server.state.reloads) for server in policy_servers),
        tuple(value_server.state.reloads),
        tuple(merged),
    )
    for server in (*policy_servers, value_server):
        server.close()


def test_every_policy_server_loads_each_runs_policy(history: ServeHistory) -> None:
    expected = tuple(str(served.policy) for served in history.served)
    assert history.policy_reloads == (expected, expected)


def test_a_run_without_a_value_model_leaves_the_value_servers_alone(history: ServeHistory) -> None:
    first, _, third = history.served
    assert history.value_reloads == (str(first.value), str(third.value))


def test_an_adapter_rewritten_at_the_same_path_is_merged_and_served_anew(history: ServeHistory) -> None:
    first, _, third = history.served
    assert third.policy != first.policy


def test_an_unchanged_adapter_is_merged_once(history: ServeHistory) -> None:
    assert history.merged_contents == ("policy one", "value one", "policy two")


def test_the_served_merge_holds_the_rewritten_adapter(history: ServeHistory) -> None:
    assert (history.served[2].policy / "model.safetensors").read_text(encoding="utf-8") == "policy-base + policy two"


def test_the_run_start_reads_back(tmp_path: Path) -> None:
    (tmp_path / "checkpoint.json").write_text(to_json(START), encoding="utf-8")
    loaded = from_json_object(ProbeRunStart, json.loads((tmp_path / "checkpoint.json").read_text(encoding="utf-8")))
    assert loaded == START
