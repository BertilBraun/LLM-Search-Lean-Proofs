"""Search throughput of a run config under load: concurrent run_search.py processes for a fixed window, monitored.

    python experiments/search_throughput.py --config experiments/configs/phase3_astar_v0_sft_v2.toml \
        --name concurrency_120 --set lean.pool_size=120 --set lean.concurrency=120 [--processes 2] \
        [--duration 420 --warmup 120] --server-url http://127.0.0.1:8100 --server-url http://127.0.0.1:8101

Each process searches miniF2F-valid under $LEAN_SEARCH_RUNS/search_throughput/<name>/<index>/; after `--duration`
seconds they are stopped and the monitor (experiments/node_monitor.py) is summarized from `--warmup` until fewer
problems are left than search slots.
"""

import argparse
import dataclasses
import json
import os
import signal
import subprocess
import sys
import time
import tomllib
from pathlib import Path

from node_monitor import read_samples, summarize

from lean_search.data import Split, load_minif2f

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "search_throughput"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--set", action="append", default=[], help="section.key=value, a TOML value")
    parser.add_argument("--processes", type=int, default=1)
    parser.add_argument("--duration", type=float, default=420.0)
    parser.add_argument("--warmup", type=float, default=120.0)
    parser.add_argument("--server-url", action="append", default=[], help="vLLM server root for the monitor")
    return parser.parse_args()


def override(text: str, setting: str) -> str:
    """Sets `section.key = value` in TOML text, replacing the key's line or adding it under the section header."""
    name, value = setting.split("=", 1)
    section, key = name.rsplit(".", 1)
    lines = text.splitlines()
    header = lines.index(f"[{section}]")
    end = next((index for index in range(header + 1, len(lines)) if lines[index].startswith("[")), len(lines))
    for index in range(header + 1, end):
        if lines[index].split("=", 1)[0].strip() == key:
            lines[index] = f"{key} = {value}"
            return "\n".join(lines) + "\n"
    lines.insert(header + 1, f"{key} = {value}")
    return "\n".join(lines) + "\n"


def process_cpu_seconds(pid: int) -> float:
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return (int(fields[11]) + int(fields[12])) / os.sysconf("SC_CLK_TCK")


def main() -> None:
    arguments = parse_arguments()
    directory = RUNS_DIRECTORY / arguments.name
    directory.mkdir(parents=True, exist_ok=False)
    text = arguments.config.read_text(encoding="utf-8")
    for setting in arguments.set:
        text = override(text, setting)
    config_path = directory / "config.toml"
    config_path.write_text(text, encoding="utf-8")
    problem_count = len(load_minif2f(Split.VALID))
    concurrency = tomllib.loads(text)["lean"]["concurrency"]
    monitor = subprocess.Popen(
        [sys.executable, str(Path(__file__).parent / "node_monitor.py"), "record"]
        + ["--output", str(directory / "monitor.jsonl")]
        + [argument for url in arguments.server_url for argument in ("--server-url", url)]
        + [
            argument
            for index in range(arguments.processes)
            for argument in ("--results", str(directory / str(index) / "results.jsonl"))
        ]
    )
    searches = [
        subprocess.Popen(
            [sys.executable, str(REPOSITORY_DIRECTORY / "experiments" / "run_search.py")]
            + ["--config", str(config_path), "--split", "valid"]
            + ["--run-name", f"search_throughput/{arguments.name}/{index}"],
            stdout=(directory / f"search_{index}.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        for index in range(arguments.processes)
    ]
    time.sleep(arguments.duration)
    orchestrator_cpu_seconds = [process_cpu_seconds(search.pid) for search in searches]
    for search in searches:
        os.killpg(search.pid, signal.SIGTERM)
    monitor.terminate()
    for process in [*searches, monitor]:
        process.wait()
    samples = read_samples(directory / "monitor.jsonl")
    # Once fewer problems are left than search slots, the slots empty out: the window ends there.
    drained = arguments.processes * (problem_count - concurrency)
    end = min([sample.seconds for sample in samples if sample.finished_searches >= drained] + [arguments.duration])
    summary = summarize(samples, arguments.warmup, end, 16)
    report = {
        "name": arguments.name,
        "settings": arguments.set,
        "processes": arguments.processes,
        "concurrency_per_process": concurrency,
        "orchestrator_cpu_cores": [seconds / arguments.duration for seconds in orchestrator_cpu_seconds],
    }
    report |= dataclasses.asdict(summary)
    (directory / "summary.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
