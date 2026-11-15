import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lean_search.monitoring.cgroup import CpuCounters
from lean_search.rl.node_pinning import (
    PINNING_FILE,
    PinningCheck,
    PinningRecord,
    append_pinning,
    background_set,
    current_pinning,
    layout_differences,
    pinned_as_background,
    pinning_check,
    read_pinning,
    record_session_pinning,
    session_refusals,
)

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
BACKGROUND_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "background.sh"
ALL_CPUS = tuple(range(128))
# A 128-CPU host whose CPU n and n + 64 are the two threads of one core.
SIBLINGS = {cpu: (cpu % 64, cpu % 64 + 64) for cpu in ALL_CPUS}
NODE_ENVIRONMENT = "/workspace/node_environment.sh"
RESERVE_CORES = 8.0


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
    server_cpu_list: str = "0-11,64-75",
    training_cpu_list: str | None = None,
    node_environment: str | None = NODE_ENVIRONMENT,
) -> PinningRecord:
    """A 128-CPU host with a 61-core quota; the background CPUs 76-127 are cores 12-63, the servers' 0-11,64-75."""
    return PinningRecord(
        recorded_at="2026-11-14T00:00:00+00:00",
        affinity=affinity,
        cpu_count=128,
        quota_cores=61.0,
        background_cpus=background_cpus,
        background_cpu_list=background_cpu_list,
        server_cpu_list=server_cpu_list,
        training_cpu_list=training_cpu_list or server_cpu_list,
        allowed_cpu_list="0-127",
        node_environment=node_environment,
    )


def checked(pinning: PinningRecord) -> PinningCheck:
    return pinning_check(pinning, SIBLINGS, RESERVE_CORES)


@pytest.mark.parametrize(
    "pinning",
    [record(background_cpus=52), record(background_cpu_list="40-63,104-127", server_cpu_list="0-39,64-103")],
    ids=["count", "list"],
)
def test_a_layout_on_cores_of_its_own_within_the_quota_and_its_reserve_passes(pinning: PinningRecord) -> None:
    assert checked(pinning) == PinningCheck((), ())


@pytest.mark.parametrize(
    "pinning", [record(background_cpus=61), record(background_cpu_list="12-41,76-106")], ids=["count", "list"]
)
def test_a_background_set_at_the_quota_is_refused(pinning: PinningRecord) -> None:
    assert checked(pinning).refusals


def test_a_background_set_leaving_less_than_the_reserve_beside_it_is_refused() -> None:
    assert len(checked(record(background_cpus=56, server_cpu_list="0-7,64-71")).refusals) == 1


def test_a_smaller_reserve_set_explicitly_lets_the_background_set_pass() -> None:
    pinning = record(background_cpus=56, server_cpu_list="0-7,64-71")
    assert pinning_check(pinning, SIBLINGS, 4.0) == PinningCheck((), ())


def test_an_explicit_reserve_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVER_RESERVE_CORES", "4")
    assert current_pinning().server_reserve_cores == 4.0


def test_the_default_reserve_is_recorded_as_unset() -> None:
    assert current_pinning().server_reserve_cores is None


@pytest.mark.parametrize(
    "pinning",
    [record(tuple(range(64)), background_cpus=52), record(tuple(range(64)), background_cpu_list="60-70")],
    ids=["count", "list"],
)
def test_a_background_set_outside_the_allowed_cpus_is_refused(pinning: PinningRecord) -> None:
    assert checked(pinning).refusals


@pytest.mark.parametrize(
    "pinning",
    [record(background_cpus=52, server_cpu_list="0-11,128-130"), record(background_cpus=52, training_cpu_list="200")],
    ids=["servers", "training"],
)
def test_a_cpu_list_outside_the_allowed_cpus_is_refused(pinning: PinningRecord) -> None:
    assert checked(pinning).refusals


@pytest.mark.parametrize(
    "pinning",
    [
        record(background_cpus=52, server_cpu_list="0-80"),
        record(background_cpus=52, server_cpu_list="0-11,64-75", training_cpu_list="100-110"),
        record(background_cpu_list="104-127", server_cpu_list="0-63"),
    ],
    ids=["servers on Lean's CPUs", "training on Lean's CPUs", "servers on the other threads of Lean's cores"],
)
def test_a_cpu_list_sharing_a_physical_core_with_the_background_set_is_refused(pinning: PinningRecord) -> None:
    assert checked(pinning).refusals


def test_every_allowed_cpu_for_the_servers_without_a_node_environment_is_a_warning_only() -> None:
    check = checked(record(background_cpus=52, server_cpu_list="0-127", node_environment=None))
    assert (check.refusals, len(check.warnings)) == ((), 2)


def test_every_allowed_cpu_for_the_servers_beside_a_node_environment_is_refused() -> None:
    assert checked(record(background_cpus=52, server_cpu_list="0-127")).refusals


@pytest.mark.parametrize(
    "pinning", [record(), record(background_cpus=52, background_cpu_list="64-115")], ids=["neither", "both"]
)
def test_a_study_job_needs_exactly_one_background_setting(pinning: PinningRecord) -> None:
    assert checked(pinning).refusals


def test_a_malformed_server_cpu_list_is_an_error() -> None:
    with pytest.raises(ValueError, match="CPU list"):
        checked(record(background_cpus=52, server_cpu_list="0-11, 64-75"))


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


def test_a_record_from_before_the_cpu_lists_reads_back(tmp_path: Path) -> None:
    old = {
        "recorded_at": "2026-11-14T00:00:00+00:00",
        "affinity": [76, 77],
        "cpu_count": 128,
        "quota_cores": 61.0,
        "background_cpus": 52,
    }
    (tmp_path / PINNING_FILE).write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert read_pinning(tmp_path) == [PinningRecord("2026-11-14T00:00:00+00:00", (76, 77), 128, 61.0, 52)]


def test_a_record_with_its_cpu_counters_reads_back(tmp_path: Path) -> None:
    written = dataclasses.replace(record(background_cpus=52), cpu_counters=CpuCounters(5.0, 179768, 4))
    append_pinning(tmp_path, written)
    assert read_pinning(tmp_path) == [written]


def test_the_current_pinning_records_where_servers_and_training_run() -> None:
    pinning = current_pinning()
    assert (pinning.server_cpu_list, pinning.training_cpu_list) == (pinning.allowed_cpu_list, pinning.allowed_cpu_list)


def test_the_same_layout_differs_in_nothing() -> None:
    assert layout_differences(record(background_cpus=52), record(background_cpus=52)) == []


def test_another_background_list_is_a_layout_difference() -> None:
    first = record(background_cpu_list="104-127")
    assert layout_differences(first, record(background_cpu_list="64-127")) == ["BACKGROUND_CPU_LIST 104-127 -> 64-127"]


def test_a_server_list_a_first_record_lacks_is_no_difference() -> None:
    first = dataclasses.replace(record(background_cpus=52), server_cpu_list=None, training_cpu_list=None)
    assert layout_differences(first, record(background_cpus=52)) == []


def resumed(directory: Path, first: PinningRecord, current: PinningRecord, require_background: bool) -> list[str]:
    append_pinning(directory, first)
    return session_refusals(directory, current, require_background)


def test_a_session_on_the_runs_first_layout_starts(tmp_path: Path) -> None:
    pinning = record(tuple(range(76, 128)), background_cpus=52)
    assert resumed(tmp_path, pinning, pinning, True) == []


def test_a_session_on_another_layout_than_the_runs_first_is_refused(tmp_path: Path) -> None:
    first = record(tuple(range(76, 128)), background_cpus=52)
    assert resumed(tmp_path, first, record(tuple(range(64, 128)), background_cpus=64), True)


def test_a_session_on_another_layout_allowed_by_its_flag_starts(tmp_path: Path) -> None:
    first = record(tuple(range(76, 128)), background_cpus=52)
    current = dataclasses.replace(record(tuple(range(64, 128)), background_cpus=64), other_pinning_allowed=True)
    assert resumed(tmp_path, first, current, True) == []


def test_an_unpinned_session_of_a_run_that_must_be_pinned_is_refused(tmp_path: Path) -> None:
    assert session_refusals(tmp_path, record(ALL_CPUS, background_cpus=52), True)


def test_an_unpinned_first_session_of_a_loop_is_recorded(tmp_path: Path) -> None:
    record_session_pinning(tmp_path, False, False)
    assert len(read_pinning(tmp_path)) == 1


def test_a_refused_session_is_not_recorded(tmp_path: Path) -> None:
    append_pinning(tmp_path, dataclasses.replace(current_pinning(), affinity=(9999,)))
    record_session_pinning(tmp_path, False, False)
    assert len(read_pinning(tmp_path)) == 1


def test_a_session_allowed_on_another_layout_is_recorded_as_such(tmp_path: Path) -> None:
    append_pinning(tmp_path, dataclasses.replace(current_pinning(), affinity=(9999,)))
    record_session_pinning(tmp_path, False, True)
    assert read_pinning(tmp_path)[-1].other_pinning_allowed


AFFINITY_AND_NICENESS = "import os; print(sorted(os.sched_getaffinity(0)), os.nice(0))"


def run_in_background(settings: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["bash", str(BACKGROUND_SCRIPT), sys.executable, "-c", AFFINITY_AND_NICENESS],
        env=os.environ | settings,
        capture_output=True,
        text=True,
        check=False,
    )


def test_background_sh_runs_a_job_on_the_last_cpus_at_its_callers_niceness() -> None:
    last = (os.cpu_count() or 1) - 1
    assert run_in_background({"BACKGROUND_CPUS": "1"}).stdout == f"[{last}] {os.nice(0)}\n"


def test_background_sh_runs_a_job_on_its_cpu_list_at_its_callers_niceness() -> None:
    first = min(os.sched_getaffinity(0))
    assert run_in_background({"BACKGROUND_CPU_LIST": str(first)}).stdout == f"[{first}] {os.nice(0)}\n"


def test_background_sh_takes_an_empty_setting_as_unset() -> None:
    first = min(os.sched_getaffinity(0))
    settings = {"BACKGROUND_CPUS": "", "BACKGROUND_CPU_LIST": str(first)}
    assert run_in_background(settings).stdout == f"[{first}] {os.nice(0)}\n"


def test_background_sh_refuses_a_cpu_count_and_a_cpu_list_together() -> None:
    assert run_in_background({"BACKGROUND_CPUS": "1", "BACKGROUND_CPU_LIST": "0"}).returncode == 2


def test_node_checks_pass_a_cpu_list_within_the_allowed_cpus() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(REPOSITORY_DIRECTORY / "experiments" / "node_checks.py"), "pinning"],
        env=os.environ | {"BACKGROUND_CPU_LIST": str(min(os.sched_getaffinity(0)))},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
