import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from failing_search import FAILURE_MESSAGE

from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY

FAILING_SEARCH = Path(__file__).with_name("failing_search.py")

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None


@pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)")
def test_a_failing_search_ends_its_program_promptly_with_the_error() -> None:
    # The other search used to restart its REPL after the pool closed; asyncio's shutdown hung cancelling that start.
    completed = subprocess.run([sys.executable, str(FAILING_SEARCH)], capture_output=True, text=True, timeout=120)
    assert completed.stderr.rstrip().splitlines()[-1] == f"RuntimeError: {FAILURE_MESSAGE}"
