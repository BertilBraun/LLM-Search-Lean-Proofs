"""Embed every premise (LeanDojo's and the added environment theorems) with the ReProver retriever and serialization.

    python experiments/phase4_embed_premises.py --device cuda:0 [--dtype bfloat16] [--limit N]

Writes $LEAN_SEARCH_DATA/retrieval/embeddings/<retriever>/{names.txt,embeddings.npy} (float16, unit norm) and
$LEAN_SEARCH_RUNS/phase4_embed_premises/summary/{summary.json,README.md}. With --limit only that many premises are
embedded and nothing is written except the summary (a throughput probe).
"""

import argparse
import dataclasses
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

import torch

from lean_search.corpora.records import read_premise_records
from lean_search.retrieval.config import DEFAULT_RETRIEVER
from lean_search.retrieval.encoder import TextEncoder
from lean_search.retrieval.index import embeddings_directory, write_embeddings
from lean_search.retrieval.premises import serialize_premise

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
PREMISE_PATHS = (
    DATA_DIRECTORY / "normalized" / "mathlib" / "premises.jsonl",
    DATA_DIRECTORY / "retrieval" / "environment_premises.jsonl",
)
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase4_embed_premises"
DTYPES = {"float32": torch.float32, "bfloat16": torch.bfloat16}
CHECK_SAMPLE = 1024


@dataclass(frozen=True)
class EmbeddingSummary:
    retriever: str
    device: str
    dtype: str
    premises: int
    serialized_bytes: int
    seconds: float
    premises_per_second: float
    # Cosine similarity of a sample against float32 embeddings of the same texts.
    float32_cosine_mean: float
    float32_cosine_min: float
    written: bool


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--dtype", choices=list(DTYPES), default="bfloat16")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--max-batch-tokens", type=int, default=65_536)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    premises: dict[str, str] = {}
    for path in PREMISE_PATHS:
        for record in read_premise_records(path):
            premises.setdefault(record.full_name, serialize_premise(record.full_name, record.code))
    names = list(premises)[: arguments.limit]
    texts = [premises[name] for name in names]
    encoder = TextEncoder(DEFAULT_RETRIEVER, arguments.device, DTYPES[arguments.dtype])
    started = time.perf_counter()
    embeddings = encoder.encode(texts, arguments.max_batch_tokens)
    if arguments.device != "cpu":
        torch.cuda.synchronize()
    seconds = time.perf_counter() - started
    sample = list(range(0, len(texts), max(1, len(texts) // CHECK_SAMPLE)))[:CHECK_SAMPLE]
    reference = TextEncoder(DEFAULT_RETRIEVER, arguments.device, torch.float32).encode(
        [texts[index] for index in sample]
    )
    cosine = (reference * embeddings[sample]).sum(dim=1)
    written = arguments.limit is None
    if written:
        write_embeddings(embeddings_directory(DATA_DIRECTORY / "retrieval", DEFAULT_RETRIEVER), names, embeddings)
    summary = EmbeddingSummary(
        retriever=DEFAULT_RETRIEVER,
        device=arguments.device,
        dtype=arguments.dtype,
        premises=len(names),
        serialized_bytes=sum(len(text.encode("utf-8")) for text in texts),
        seconds=seconds,
        premises_per_second=len(names) / seconds,
        float32_cosine_mean=cosine.mean().item(),
        float32_cosine_min=cosine.min().item(),
        written=written,
    )
    directory = RUN_DIRECTORY / "summary"
    directory.mkdir(parents=True, exist_ok=True)
    name = "summary" if written else f"probe_{arguments.device.replace(':', '')}_{arguments.dtype}"
    (directory / f"{name}.json").write_text(json.dumps(dataclasses.asdict(summary), indent=1), encoding="utf-8")
    markdown = (
        f"# Premise embeddings\n\n`{summary.retriever}` on {summary.device} in {summary.dtype}: {summary.premises:,} "
        f"premises ({summary.serialized_bytes:,} serialized bytes) in {summary.seconds:.0f} s "
        f"({summary.premises_per_second:,.0f} premises/s). Cosine to float32 on {len(sample)} sampled premises: "
        f"mean {summary.float32_cosine_mean:.5f}, min {summary.float32_cosine_min:.5f}.\n"
    )
    (directory / f"{name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
