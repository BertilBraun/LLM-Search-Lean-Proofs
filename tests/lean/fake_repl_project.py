"""A Lean project directory whose REPL binary is fake_repl.py, for process tests without Lean (Linux only)."""

import dataclasses
import json
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from lean_search.lean import repl as repl_module
from lean_search.lean.repl import REPL_BINARY, LeanReplConfig

HEADER = "import Lean\n"
STATEMENT = "theorem t : True := by\n"
needs_linux = pytest.mark.skipif(sys.platform == "win32", reason="REPL processes need Linux (stdbuf, rlimits)")


@dataclass(frozen=True)
class FakeReplProject:
    config: LeanReplConfig
    log: Path

    def requests(self, kind: str) -> list[str]:
        """The texts of every `cmd` or `tactic` request any fake process received, in order."""
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [
            json.loads(text) for _, logged_kind, text in (line.split("\t") for line in lines) if logged_kind == kind
        ]

    def process_ids(self) -> set[int]:
        if not self.log.exists():
            return set()
        return {int(line.split("\t")[0]) for line in self.log.read_text(encoding="utf-8").splitlines()}


def fake_repl_project(
    directory: Path, monkeypatch: pytest.MonkeyPatch, import_seconds: float = 0.0, timeout_seconds: float = 1.0
) -> FakeReplProject:
    binary = directory / REPL_BINARY
    binary.parent.mkdir(parents=True)
    script = Path(__file__).with_name("fake_repl.py")
    binary.write_text(f"#!/bin/sh\nexec {sys.executable} {script}\n", encoding="utf-8")
    binary.chmod(binary.stat().st_mode | stat.S_IXUSR)
    log = directory / "requests.tsv"
    monkeypatch.setenv("FAKE_REPL_LOG", str(log))
    monkeypatch.setenv("FAKE_REPL_IMPORT_SECONDS", str(import_seconds))
    monkeypatch.setitem(repl_module._lake_environments, directory, {})
    config = dataclasses.replace(
        LeanReplConfig(project_directory=directory),
        tactic_timeout_seconds=timeout_seconds,
        replay_timeout_seconds=timeout_seconds,
        command_timeout_seconds=30.0,
    )
    return FakeReplProject(config, log)
