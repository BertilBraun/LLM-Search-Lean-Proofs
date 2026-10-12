"""Latency of retrieval inside the search: encoding miniF2F root goals and searching the premise index.

    python experiments/phase4_retrieval_latency.py --device cpu --threads 4 8 16 [--random-index]

Writes $LEAN_SEARCH_RUNS/phase4_retrieval_latency/summary/latency_<device>.{json,md}. With --random-index the index
is random unit vectors of the deployed shape (before the premise embeddings exist).
"""

import argparse
import dataclasses
import json
import os
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import torch

from lean_search.data import Split, load_minif2f
from lean_search.retrieval.config import DEFAULT_RETRIEVER
from lean_search.retrieval.encoder import TextEncoder
from lean_search.retrieval.index import PremiseIndex, load_premise_index
from lean_search.retrieval.premises import serialize_goals
from lean_search.search.summary import markdown_table

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"]) / "retrieval"
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase4_retrieval_latency"
DEPLOYED_PREMISES = 174_254
BATCH_SIZES = (1, 8, 32)
CANDIDATES = 32


@dataclass(frozen=True)
class LatencyRow:
    device: str
    threads: int
    batch_goals: int
    encode_seconds_per_batch: float
    search_seconds_per_batch: float
    seconds_per_goal: float


@dataclass(frozen=True)
class LatencySummary:
    device: str
    index_premises: int
    random_index: bool
    goal_bytes_mean: float
    goal_bytes_p90: int
    rows: tuple[LatencyRow, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--threads", type=int, nargs="+", default=[8])
    parser.add_argument("--random-index", action="store_true")
    parser.add_argument("--repeats", type=int, default=3)
    return parser.parse_args()


def random_index(device: str) -> PremiseIndex:
    generator = torch.Generator().manual_seed(0)
    embeddings = torch.nn.functional.normalize(torch.randn(DEPLOYED_PREMISES, 1472, generator=generator), dim=1)
    dtype = torch.float32 if device == "cpu" else torch.float16
    names = [str(index) for index in range(DEPLOYED_PREMISES)]
    return PremiseIndex(names, names, embeddings.to(device=device, dtype=dtype))


def synchronize(device: str) -> None:
    if device != "cpu":
        torch.cuda.synchronize()


def measure(
    encoder: TextEncoder, index: PremiseIndex, goals: list[str], batch_goals: int, repeats: int, device: str
) -> tuple[float, float]:
    batches = [goals[start : start + batch_goals] for start in range(0, len(goals), batch_goals)]
    batches = [batch for batch in batches if len(batch) == batch_goals]
    encode_seconds: list[float] = []
    search_seconds: list[float] = []
    for _ in range(repeats):
        for batch in batches:
            started = time.perf_counter()
            queries = encoder.encode(batch)
            synchronize(device)
            encoded = time.perf_counter()
            index.search(queries, CANDIDATES)
            synchronize(device)
            encode_seconds.append(encoded - started)
            search_seconds.append(time.perf_counter() - encoded)
    return statistics.median(encode_seconds), statistics.median(search_seconds)


def render_markdown(summary: LatencySummary) -> str:
    rows = [
        [
            row.threads if row.device == "cpu" else "-",
            row.batch_goals,
            f"{row.encode_seconds_per_batch * 1000:.0f}",
            f"{row.search_seconds_per_batch * 1000:.0f}",
            f"{row.seconds_per_goal * 1000:.0f}",
        ]
        for row in summary.rows
    ]
    index = "a random index of the deployed shape" if summary.random_index else "the deployed index"
    return (
        f"# Retrieval latency on {summary.device}\n\n"
        f"miniF2F-valid root goals (mean {summary.goal_bytes_mean:.0f} bytes, p90 {summary.goal_bytes_p90}), "
        f"{index} ({summary.index_premises:,} premises, top {CANDIDATES}). Medians over batches.\n\n"
        + markdown_table(["Threads", "Goals per batch", "Encode ms", "Search ms", "ms per goal"], rows)
        + "\n"
    )


def main() -> None:
    arguments = parse_arguments()
    goals = [serialize_goals([problem.goal]) for problem in load_minif2f(Split.VALID)]
    index = (
        random_index(arguments.device)
        if arguments.random_index
        else load_premise_index(DATA_DIRECTORY, DEFAULT_RETRIEVER, arguments.device)
    )
    encoder = TextEncoder(DEFAULT_RETRIEVER, arguments.device)
    encoder.encode(goals[:8])
    rows = []
    for threads in arguments.threads if arguments.device == "cpu" else [0]:
        if arguments.device == "cpu":
            torch.set_num_threads(threads)
        for batch_goals in BATCH_SIZES:
            encode, search = measure(encoder, index, goals, batch_goals, arguments.repeats, arguments.device)
            rows.append(
                LatencyRow(arguments.device, threads, batch_goals, encode, search, (encode + search) / batch_goals)
            )
            print(rows[-1], flush=True)
    lengths = sorted(len(goal.encode("utf-8")) for goal in goals)
    summary = LatencySummary(
        device=arguments.device,
        index_premises=len(index),
        random_index=arguments.random_index,
        goal_bytes_mean=statistics.fmean(lengths),
        goal_bytes_p90=lengths[int(0.9 * len(lengths))],
        rows=tuple(rows),
    )
    directory = RUN_DIRECTORY / "summary"
    directory.mkdir(parents=True, exist_ok=True)
    name = f"latency_{arguments.device.replace(':', '')}"
    (directory / f"{name}.json").write_text(json.dumps(dataclasses.asdict(summary), indent=1), encoding="utf-8")
    markdown = render_markdown(summary)
    (directory / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
