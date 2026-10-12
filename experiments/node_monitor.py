"""Sample GPU utilization, the cgroup's CPU use and throttling, vLLM counters and finished searches into a JSONL file.

    python experiments/node_monitor.py record --output $LEAN_SEARCH_RUNS/<run>/monitor.jsonl \
        --server-url http://127.0.0.1:8100 --results $LEAN_SEARCH_RUNS/<run>/results.jsonl
    python experiments/node_monitor.py summarize --input .../monitor.jsonl [--start 60 --end 600]

`record` runs until killed. `summarize` averages over a window in seconds since the first sample (default: all).
"""

import argparse
import dataclasses
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pynvml

CPU_STAT = Path("/sys/fs/cgroup/cpu.stat")
METRIC_LINE = re.compile(r"^(vllm:[a-z_]+)(\{[^}]*\})? ([0-9.e+-]+)$")
SUMMED_METRICS = (
    "vllm:generation_tokens_total",
    "vllm:prompt_tokens_total",
    "vllm:request_params_n_sum",
    "vllm:request_params_n_count",
    "vllm:num_requests_running",
    "vllm:num_requests_waiting",
)


@dataclass(frozen=True)
class ServerCounters:
    generation_tokens: float
    prompt_tokens: float
    # Sum and count of `n` over finished requests: policy requests ask for n samples, value requests for one.
    sample_count_sum: float
    request_count: float
    running: float
    waiting: float


@dataclass(frozen=True)
class Sample:
    seconds: float
    unix_time: float
    gpu_utilization: tuple[int, ...]
    gpu_power_watts: tuple[float, ...]
    cpu_usage_seconds: float
    periods: int
    throttled_periods: int
    load_average: float
    servers: tuple[ServerCounters, ...]
    finished_searches: int


@dataclass(frozen=True)
class Summary:
    window_seconds: float
    gpu_utilization: tuple[float, ...]
    gpu_power_watts: tuple[float, ...]
    cpu_cores_used: float
    throttled_fraction: float
    load_average: float
    generated_tokens_per_second: float
    prompt_tokens_per_second: float
    policy_samples_per_second: float
    requests_per_second: float
    running_sequences: float
    waiting_sequences: float
    finished_searches_per_hour: float


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record")
    record.add_argument("--output", type=Path, required=True)
    record.add_argument("--interval", type=float, default=1.0)
    record.add_argument("--server-url", action="append", default=[], help="vLLM server root, without /v1")
    record.add_argument("--results", type=Path, help="results.jsonl whose lines count finished searches")
    summarize = commands.add_parser("summarize")
    summarize.add_argument("--input", type=Path, required=True)
    summarize.add_argument("--start", type=float, default=0.0)
    summarize.add_argument("--end", type=float, default=float("inf"))
    summarize.add_argument("--unix-time", action="store_true", help="--start and --end are Unix times")
    summarize.add_argument("--samples-per-request", type=int, default=16)
    return parser.parse_args()


def read_cpu_stat() -> dict[str, int]:
    return {key: int(value) for key, value in (line.split() for line in CPU_STAT.read_text().splitlines())}


def server_counters(http: httpx.Client, server_url: str) -> ServerCounters:
    totals = dict.fromkeys(SUMMED_METRICS, 0.0)
    for line in http.get(f"{server_url.rstrip('/')}/metrics").text.splitlines():
        match = METRIC_LINE.match(line)
        if match and match.group(1) in totals:
            totals[match.group(1)] += float(match.group(3))
    return ServerCounters(*(totals[name] for name in SUMMED_METRICS))


def count_lines(path: Path | None) -> int:
    if path is None or not path.exists():
        return 0
    with path.open("rb") as handle:
        return sum(1 for _ in handle)


def record(arguments: argparse.Namespace) -> None:
    pynvml.nvmlInit()
    handles = [pynvml.nvmlDeviceGetHandleByIndex(index) for index in range(pynvml.nvmlDeviceGetCount())]
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with httpx.Client(timeout=5.0) as http, arguments.output.open("a", encoding="utf-8") as output:
        while True:
            cpu_stat = read_cpu_stat()
            sample = Sample(
                seconds=time.monotonic() - started,
                unix_time=time.time(),
                gpu_utilization=tuple(pynvml.nvmlDeviceGetUtilizationRates(handle).gpu for handle in handles),
                gpu_power_watts=tuple(pynvml.nvmlDeviceGetPowerUsage(handle) / 1000 for handle in handles),
                cpu_usage_seconds=cpu_stat["usage_usec"] / 1e6,
                periods=cpu_stat["nr_periods"],
                throttled_periods=cpu_stat["nr_throttled"],
                load_average=float(Path("/proc/loadavg").read_text().split()[0]),
                servers=tuple(server_counters(http, url) for url in arguments.server_url),
                finished_searches=count_lines(arguments.results),
            )
            output.write(json.dumps(dataclasses.asdict(sample)) + "\n")
            output.flush()
            time.sleep(max(0.0, arguments.interval - (time.monotonic() - started - sample.seconds)))


def read_samples(path: Path) -> list[Sample]:
    samples = []
    for line in path.read_text(encoding="utf-8").splitlines():
        fields = json.loads(line)
        fields["servers"] = tuple(ServerCounters(**server) for server in fields["servers"])
        fields["gpu_utilization"] = tuple(fields["gpu_utilization"])
        fields["gpu_power_watts"] = tuple(fields["gpu_power_watts"])
        samples.append(Sample(**fields))
    return samples


def summarize(samples: list[Sample], start: float, end: float, samples_per_request: int) -> Summary:
    window = [sample for sample in samples if start <= sample.seconds <= end]
    first, last = window[0], window[-1]
    seconds = last.seconds - first.seconds

    def mean(values: list[float]) -> float:
        return sum(values) / len(values)

    def server_rate(field: str) -> float:
        return (
            sum(
                getattr(last_server, field) - getattr(first_server, field)
                for first_server, last_server in zip(first.servers, last.servers, strict=True)
            )
            / seconds
        )

    request_rate = server_rate("request_count")
    # Policy requests contribute n to the sum of n, value requests 1, so (sum - count) / (n - 1) counts the former.
    policy_request_rate = (server_rate("sample_count_sum") - request_rate) / (samples_per_request - 1)
    gpu_count = len(first.gpu_utilization)
    return Summary(
        window_seconds=seconds,
        gpu_utilization=tuple(mean([sample.gpu_utilization[gpu] for sample in window]) for gpu in range(gpu_count)),
        gpu_power_watts=tuple(mean([sample.gpu_power_watts[gpu] for sample in window]) for gpu in range(gpu_count)),
        cpu_cores_used=(last.cpu_usage_seconds - first.cpu_usage_seconds) / seconds,
        throttled_fraction=(last.throttled_periods - first.throttled_periods) / max(1, last.periods - first.periods),
        load_average=mean([sample.load_average for sample in window]),
        generated_tokens_per_second=server_rate("generation_tokens"),
        prompt_tokens_per_second=server_rate("prompt_tokens"),
        policy_samples_per_second=policy_request_rate * samples_per_request,
        requests_per_second=request_rate,
        running_sequences=mean([sum(server.running for server in sample.servers) for sample in window]),
        waiting_sequences=mean([sum(server.waiting for server in sample.servers) for sample in window]),
        finished_searches_per_hour=(last.finished_searches - first.finished_searches) / seconds * 3600,
    )


def main() -> None:
    arguments = parse_arguments()
    match arguments.command:
        case "record":
            record(arguments)
        case "summarize":
            samples = read_samples(arguments.input)
            if arguments.unix_time:
                samples = [dataclasses.replace(sample, seconds=sample.unix_time) for sample in samples]
            summary = summarize(samples, arguments.start, arguments.end, arguments.samples_per_request)
            print(json.dumps(dataclasses.asdict(summary), indent=1))


if __name__ == "__main__":
    main()
