from collections.abc import Iterator
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def runs_directory(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    """$LEAN_SEARCH_RUNS for the session: the swap marks `server_control` writes go there, not to the machine's."""
    runs = tmp_path_factory.mktemp("runs")
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LEAN_SEARCH_RUNS", str(runs))
        yield runs
