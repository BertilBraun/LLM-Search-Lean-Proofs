"""Stand-ins for the processes serve_model.sh starts: a script named `vllm` that sleeps, started as
`python <dir>/vllm serve <weights> --served-model-name <name>`, with its pid file written right after its start as
serve_model.sh writes it, and its log's first line naming it as the API server."""

import contextlib
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

FAKE_VLLM = "import time\ntime.sleep(600)\n"


FAKE_VLLM_SERVER = """import http.server, sys

class Health(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *arguments):
        pass

http.server.HTTPServer(("127.0.0.1", int(sys.argv[sys.argv.index("--port") + 1])), Health).serve_forever()
"""


def fake_vllm_server_executable(directory: Path) -> Path:
    """An executable `vllm` that answers /health on its --port, for serve_model.sh (LEAN_SEARCH_VLLM_EXECUTABLE): it
    runs as `python <dir>/vllm serve ...`, as vLLM's CLI does."""
    script = directory / "bin" / "vllm"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(f"#!{sys.executable}\n{FAKE_VLLM_SERVER}", encoding="utf-8")
    script.chmod(0o755)
    return script


def fake_vllm_script(directory: Path) -> Path:
    script = directory / "bin" / "vllm"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(FAKE_VLLM, encoding="utf-8")
    return script


@contextlib.contextmanager
def fake_server_process(servers_directory: Path, name: str, weights: Path, log: str = "") -> Iterator[int]:
    """A live `vllm serve` stand-in for `name` with its pid file and log (`log`'s {pid} filled in); stopped by its pid
    afterwards."""
    script = fake_vllm_script(servers_directory.parent)
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, str(script), "serve", str(weights), "--served-model-name", name],
        # Its own process group, as serve_model.sh's setsid gives vLLM: stop_model.sh signals the group.
        start_new_session=True,
    )
    servers_directory.mkdir(parents=True, exist_ok=True)
    (servers_directory / f"{name}.pid").write_text(f"{process.pid}\n", encoding="utf-8")
    (servers_directory / f"{name}.log").write_text(log.format(pid=process.pid), encoding="utf-8")
    try:
        yield process.pid
    finally:
        process.kill()
        process.wait()


def age_file(path: Path, seconds: float) -> None:
    written = path.stat().st_mtime - seconds
    os.utime(path, (written, written))
