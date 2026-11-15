"""deployment/environment.sh sourcing the node environment file: its settings, a command's own value winning, no CPU
list default of its own, and a broken file stopping the calling script with the file's name."""

import os
import subprocess
from pathlib import Path

import pytest

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[2]
ENVIRONMENT_SCRIPT = REPOSITORY_DIRECTORY / "deployment" / "environment.sh"
NODE_ENVIRONMENT = """export BACKGROUND_CPU_LIST="${BACKGROUND_CPU_LIST-48-95,144-191}"
export SERVER_CPU_LIST="${SERVER_CPU_LIST-0-47,96-143}"
"""
CPU_SETTINGS = 'echo "${BACKGROUND_CPU_LIST:-} ${SERVER_CPU_LIST:-}"'


def sourced(
    directory: Path, node_environment: str | None, settings: dict[str, str], command: str = CPU_SETTINGS
) -> subprocess.CompletedProcess[str]:
    """`command` in a script that sources environment.sh under set -euo pipefail, with `node_environment` as the node's
    file (none when None)."""
    path = directory / "node_environment.sh"
    if node_environment is not None:
        path.write_text(node_environment, encoding="utf-8")
    environment = os.environ | {
        "LEAN_SEARCH_WORKSPACE": str(directory),
        "LEAN_SEARCH_NODE_ENVIRONMENT": str(path),
        **settings,
    }
    script = f'set -euo pipefail; source "{ENVIRONMENT_SCRIPT}"; {command}'
    return subprocess.run(["bash", "-c", script], env=environment, capture_output=True, text=True, check=False)  # noqa: S603


def test_environment_sh_takes_the_cpu_lists_of_the_node_environment(tmp_path: Path) -> None:
    assert sourced(tmp_path, NODE_ENVIRONMENT, {}).stdout == "48-95,144-191 0-47,96-143\n"


def test_a_commands_empty_setting_wins_over_the_node_environment(tmp_path: Path) -> None:
    assert sourced(tmp_path, NODE_ENVIRONMENT, {"BACKGROUND_CPU_LIST": ""}).stdout == " 0-47,96-143\n"


def test_without_a_node_environment_no_cpu_list_is_set(tmp_path: Path) -> None:
    assert sourced(tmp_path, None, {}).stdout == " \n"


def test_the_node_environments_path_is_exported(tmp_path: Path) -> None:
    result = sourced(tmp_path, NODE_ENVIRONMENT, {}, 'bash -c "echo \\$LEAN_SEARCH_NODE_ENVIRONMENT"')
    assert result.stdout == f"{tmp_path / 'node_environment.sh'}\n"


@pytest.mark.parametrize(
    "node_environment",
    ['export SERVER_CPU_LIST="0-47\n', "export SERVER_CPU_LIST=0-47\nfalse\nexport BACKGROUND_CPU_LIST=48-95\n"],
    ids=["syntax error", "failing command"],
)
def test_a_broken_node_environment_stops_the_script_naming_it(tmp_path: Path, node_environment: str) -> None:
    result = sourced(tmp_path, node_environment, {})
    assert (result.returncode, result.stdout, str(tmp_path / "node_environment.sh") in result.stderr) == (1, "", True)


def test_a_relative_node_environment_path_stops_the_script(tmp_path: Path) -> None:
    result = sourced(tmp_path, None, {"LEAN_SEARCH_NODE_ENVIRONMENT": "node_environment.sh"})
    assert (result.returncode, "absolute" in result.stderr) == (1, True)
