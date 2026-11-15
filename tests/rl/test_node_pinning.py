import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lean_search.rl.node_pinning import (
    PINNING_FILE,
    PinningRecord,
    background_set,
    cpu_list_text,
    parse_cpu_list,
    pinned_as_background,
    pinning_refusals,
    read_pinning,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
BACKGROUND_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "background.sh"
ENVIRONMENT_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "environment.sh"
ALL_CPUS = tuple(range(128))


@pytest.mark.parametrize(
    ("text", "cpus"),
    [("3", (3,)), ("0-3", (0, 1, 2, 3)), ("6,0-1", (0, 1, 6)), ("0-6:3", (0, 3, 6))],
    ids=["one", "range", "unordered", "stride"],
)
def test_a_cpu_list_parses_as_taskset_reads_it(text: str, cpus: tuple[int, ...]) -> None:
    assert parse_cpu_list(text) == cpus


@pytest.mark.parametrize("text", ["", "a", "0-", "1,,2", "5-3", "0-6:0", " 0-3"])
def test_a_malformed_cpu_list_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="CPU"):
        parse_cpu_list(text)


def test_cpus_print_as_their_shortest_list() -> None:
    assert cpu_list_text((48, 49, 50, 144, 146, 147)) == "48-50,144,146-147"


def test_background_sh_pins_the_last_cpus_of_the_host() -> None:
    assert background_set(4, None, 16) == (12, 13, 14, 15)


def test_background_sh_pins_its_cpu_list() -> None:
    assert background_set(None, "48-95,144-191", 192) == (*range(48, 96), *range(144, 192))


def test_background_sh_pins_the_last_32_cpus_when_neither_is_set() -> None:
    assert background_set(None, None, 192) == tuple(range(160, 192))


def test_a_cpu_count_and_a_cpu_list_together_are_refused() -> None:
    with pytest.raises(ValueError, match="not both"):
        background_set(52, "144-191", 192)


def record(
    affinity: tuple[int, ...] = ALL_CPUS,
    background_cpus: int | None = None,
    background_cpu_list: str | None = None,
    server_cpu_list: str | None = None,
) -> PinningRecord:
    return PinningRecord(
        "2026-11-14T00:00:00+00:00", affinity, 128, 61.0, background_cpus, background_cpu_list, server_cpu_list
    )


@pytest.mark.parametrize(
    "pinning", [record(background_cpus=52), record(background_cpu_list="64-115")], ids=["count", "list"]
)
def test_a_pinned_set_below_the_quota_within_the_allowed_cpus_passes(pinning: PinningRecord) -> None:
    assert pinning_refusals(pinning) == []


@pytest.mark.parametrize(
    "pinning", [record(background_cpus=61), record(background_cpu_list="0-29,64-94")], ids=["count", "list"]
)
def test_a_pinned_set_at_the_quota_is_refused(pinning: PinningRecord) -> None:
    assert pinning_refusals(pinning)


@pytest.mark.parametrize(
    "pinning",
    [record(tuple(range(64)), background_cpus=52), record(tuple(range(64)), background_cpu_list="60-70")],
    ids=["count", "list"],
)
def test_a_pinned_set_outside_the_allowed_cpus_is_refused(pinning: PinningRecord) -> None:
    assert pinning_refusals(pinning)


def test_a_server_cpu_list_outside_the_allowed_cpus_is_refused() -> None:
    assert pinning_refusals(record(background_cpus=52, server_cpu_list="0-75,128-130"))


def test_a_server_cpu_list_within_the_allowed_cpus_passes() -> None:
    assert pinning_refusals(record(background_cpus=52, server_cpu_list="0-75")) == []


@pytest.mark.parametrize(
    "pinning", [record(), record(background_cpus=52, background_cpu_list="64-115")], ids=["neither", "both"]
)
def test_a_study_job_needs_exactly_one_pinning_setting(pinning: PinningRecord) -> None:
    assert pinning_refusals(pinning)


@pytest.mark.parametrize(
    ("pinning", "pinned"),
    [
        (record(tuple(range(76, 128)), background_cpus=52), True),
        (record(tuple(range(64, 116)), background_cpu_list="64-115"), True),
        (record(ALL_CPUS, background_cpus=52), False),
        (record(tuple(range(76, 128)), background_cpu_list="64-115"), False),
        (record(tuple(range(76, 128))), False),
    ],
    ids=["pinned by count", "pinned by list", "unpinned", "another set than the list", "neither set"],
)
def test_a_process_counts_as_pinned_only_on_background_shs_set(pinning: PinningRecord, pinned: bool) -> None:
    assert pinned_as_background(pinning) == pinned


def test_a_record_from_before_the_cpu_list_reads_back(tmp_path: Path) -> None:
    old = {
        "recorded_at": "2026-11-14T00:00:00+00:00",
        "affinity": [76, 77],
        "cpu_count": 128,
        "quota_cores": 61.0,
        "background_cpus": 52,
    }
    (tmp_path / PINNING_FILE).write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert read_pinning(tmp_path) == [PinningRecord("2026-11-14T00:00:00+00:00", (76, 77), 128, 61.0, 52)]


AFFINITY_AND_NICENESS = "import os; print(sorted(os.sched_getaffinity(0)), os.nice(0))"


def run_in_background(settings: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BACKGROUND_CPU")}
    return subprocess.run(  # noqa: S603
        ["bash", str(BACKGROUND_SCRIPT), sys.executable, "-c", AFFINITY_AND_NICENESS],
        env=environment | settings,
        capture_output=True,
        text=True,
        check=False,
    )


def test_background_sh_runs_a_job_on_the_last_cpus_at_nice_19() -> None:
    last = (os.cpu_count() or 1) - 1
    assert run_in_background({"BACKGROUND_CPUS": "1"}).stdout == f"[{last}] 19\n"


def test_background_sh_runs_a_job_on_its_cpu_list_at_nice_19() -> None:
    first = min(os.sched_getaffinity(0))
    assert run_in_background({"BACKGROUND_CPU_LIST": str(first)}).stdout == f"[{first}] 19\n"


def test_background_sh_takes_an_empty_setting_as_unset() -> None:
    first = min(os.sched_getaffinity(0))
    assert run_in_background({"BACKGROUND_CPUS": "", "BACKGROUND_CPU_LIST": str(first)}).stdout == f"[{first}] 19\n"


def test_background_sh_refuses_a_cpu_count_and_a_cpu_list_together() -> None:
    assert run_in_background({"BACKGROUND_CPUS": "1", "BACKGROUND_CPU_LIST": "0"}).returncode == 2


def node_checks_pinning(settings: dict[str, str]) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("BACKGROUND_CPU")}
    return subprocess.run(  # noqa: S603
        [sys.executable, str(REPOSITORY_DIRECTORY / "experiments" / "node_checks.py"), "pinning"],
        env=environment | settings,
        capture_output=True,
        text=True,
        check=False,
    )


def test_node_checks_pass_a_cpu_list_within_the_allowed_cpus() -> None:
    assert node_checks_pinning({"BACKGROUND_CPU_LIST": str(min(os.sched_getaffinity(0)))}).returncode == 0


NODE_ENVIRONMENT = """export BACKGROUND_CPU_LIST="${BACKGROUND_CPU_LIST-48-95,144-191}"
export SERVER_CPU_LIST="${SERVER_CPU_LIST-0-47,96-143}"
"""


def cpu_settings_after_environment(directory: Path, settings: dict[str, str]) -> str:
    """BACKGROUND_CPU_LIST and SERVER_CPU_LIST once environment.sh sourced NODE_ENVIRONMENT as the node's file."""
    node_environment = directory / "node_environment.sh"
    node_environment.write_text(NODE_ENVIRONMENT, encoding="utf-8")
    inherited = {key: value for key, value in os.environ.items() if not key.endswith("_CPU_LIST")}
    environment = inherited | {
        "LEAN_SEARCH_WORKSPACE": str(directory),
        "LEAN_SEARCH_NODE_ENVIRONMENT": str(node_environment),
        **settings,
    }
    command = f'source "{ENVIRONMENT_SCRIPT}"; echo "${{BACKGROUND_CPU_LIST}} ${{SERVER_CPU_LIST}}"'
    return subprocess.run(  # noqa: S603
        ["bash", "-c", command], env=environment, capture_output=True, text=True, check=True
    ).stdout


def test_environment_sh_takes_the_cpu_lists_of_the_node_environment(tmp_path: Path) -> None:
    assert cpu_settings_after_environment(tmp_path, {}) == "48-95,144-191 0-47,96-143\n"


def test_a_commands_empty_setting_wins_over_the_node_environment(tmp_path: Path) -> None:
    assert cpu_settings_after_environment(tmp_path, {"BACKGROUND_CPU_LIST": ""}) == " 0-47,96-143\n"
