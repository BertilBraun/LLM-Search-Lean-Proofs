from collections.abc import Iterator

import pytest

# The CPU layout a node environment or the calling shell may set (deployment/README.md, "Node environment").
CPU_SETTINGS = (
    "BACKGROUND_CPUS",
    "BACKGROUND_CPU_LIST",
    "SERVER_CPU_LIST",
    "TRAINING_CPU_LIST",
    "SERVER_RESERVE_CORES",
)


@pytest.fixture(scope="session", autouse=True)
def without_node_environment(tmp_path_factory: pytest.TempPathFactory) -> Iterator[None]:
    """No test sees the machine's node environment (/workspace/node_environment.sh on a node, which the scripts under
    test would source) or the CPU settings of the shell that runs the tests."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("LEAN_SEARCH_NODE_ENVIRONMENT", str(tmp_path_factory.mktemp("node") / "node_environment.sh"))
        for name in CPU_SETTINGS:
            patch.delenv(name, raising=False)
        yield
