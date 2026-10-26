"""The run dashboard: serve a run's metrics, record the node's system usage, or view synthetic demo data.

    python experiments/dashboard.py serve --run-directory $LEAN_SEARCH_RUNS/<run> [--compare control=<dir>] \
        [--host 0.0.0.0] [--port 8600] [--password-file ~/.config/lean-search/dashboard_password] [--config ...]
    python experiments/dashboard.py record-system --run-directory $LEAN_SEARCH_RUNS/<run> --hourly-price 0.8
    python experiments/dashboard.py demo [--output artifacts/dashboard_demo] [--days 3] [--live] [--port 8600]

The dashboard is read-only and open by default. A password is optional: --password-file or the
LEAN_SEARCH_DASHBOARD_PASSWORD environment variable turns on the login; neither is created here. demo writes a
synthetic run and its outcome-only control under --output and serves both.
"""

import argparse
import os
import shutil
import stat
import sys
import threading
import time
from pathlib import Path

from lean_search.monitoring.demo import DemoSchedule, demo_runs, keep_live
from lean_search.monitoring.server import (
    PASSWORD_VARIABLE,
    Authenticator,
    DashboardServer,
    RunSource,
    load_config,
)
from lean_search.monitoring.store import METRICS_DIRECTORY, MetricsWriter
from lean_search.monitoring.system_sampler import LEAN_PROCESS_NAMES, record_system

MINIMUM_PASSWORD_LENGTH = 12


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--run-directory", type=Path, required=True)
    serve.add_argument("--compare", action="append", default=[], help="NAME=DIRECTORY of another run to overlay")
    demo = commands.add_parser("demo")
    demo.add_argument("--output", type=Path, default=Path("artifacts/dashboard_demo"))
    demo.add_argument("--days", type=float, default=3.0)
    demo.add_argument("--live", action="store_true", help="keep appending records in real time")
    for command in (serve, demo):
        command.add_argument("--host", default="127.0.0.1")
        command.add_argument("--port", type=int, default=8600)
        command.add_argument("--password-file", type=Path)
        command.add_argument("--config", type=Path, help="dashboard TOML (title, refresh, alert thresholds)")
        command.add_argument("--secure-cookies", action="store_true", help="always mark the session cookie Secure")
    system = commands.add_parser("record-system")
    system.add_argument("--run-directory", type=Path, required=True)
    system.add_argument("--interval", type=float, default=30.0)
    system.add_argument("--hourly-price", type=float, required=True)
    system.add_argument("--process-name", action="append", help="Lean process names (default: repl, lean)")
    return parser.parse_args()


def read_password(password_file: Path | None) -> str | None:
    if password_file is not None:
        if os.name == "posix" and password_file.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            print(f"warning: {password_file} is readable by others; chmod 600 it", file=sys.stderr)
        password = password_file.read_text(encoding="utf-8").rstrip("\r\n")
        if not password:
            raise SystemExit(f"{password_file} is empty")
    else:
        password = os.environ.get(PASSWORD_VARIABLE, "")
    if not password:
        return None
    if len(password) < MINIMUM_PASSWORD_LENGTH:
        print(f"warning: the dashboard password is shorter than {MINIMUM_PASSWORD_LENGTH} characters", file=sys.stderr)
    return password


def compared_run(text: str) -> RunSource:
    name, separator, directory = text.partition("=")
    if not separator or not name:
        raise SystemExit(f"--compare expects NAME=DIRECTORY, got {text!r}")
    return RunSource(name, Path(directory))


def serve(arguments: argparse.Namespace, runs: list[RunSource]) -> None:
    config = load_config(arguments.config)
    password = read_password(arguments.password_file)
    authenticator = (
        None
        if password is None
        else Authenticator(password, config.session_days * 86400, config.max_failed_logins_per_minute)
    )
    server = DashboardServer((arguments.host, arguments.port), runs, config, authenticator, arguments.secure_cookies)
    names = ", ".join(f"{run.name} ({run.directory})" for run in runs)
    print(f"dashboard on http://{arguments.host}:{server.server_address[1]}/ serving {names}", flush=True)
    server.serve_forever()


def demo(arguments: argparse.Namespace) -> None:
    runs = [RunSource("main", arguments.output / "main"), RunSource("control", arguments.output / "control")]
    for run in runs:
        shutil.rmtree(run.directory / METRICS_DIRECTORY, ignore_errors=True)
    started = time.time()
    generated = demo_runs(
        MetricsWriter(runs[0].directory), MetricsWriter(runs[1].directory), arguments.days, DemoSchedule(), started
    )
    print(f"wrote {arguments.days:g} days of demo metrics in {time.time() - started:.1f} s", flush=True)
    if arguments.live:
        threading.Thread(target=keep_live, args=(generated, 5.0), daemon=True).start()
    serve(arguments, runs)


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "serve":
            run = RunSource(arguments.run_directory.resolve().name, arguments.run_directory)
            serve(arguments, [run, *(compared_run(text) for text in arguments.compare)])
        case "demo":
            demo(arguments)
        case "record-system":
            names = tuple(arguments.process_name or LEAN_PROCESS_NAMES)
            record_system(arguments.run_directory, arguments.interval, arguments.hourly_price, names)


if __name__ == "__main__":
    main()
