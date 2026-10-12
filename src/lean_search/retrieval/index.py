"""Precomputed premise embeddings and top-k search over the premises that exist in the pinned environment."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import torch

from lean_search.retrieval.premises import RetrievedPremise, read_signatures

NAMES_FILE = "names.txt"
EMBEDDINGS_FILE = "embeddings.npy"


def embeddings_directory(data_directory: Path, retriever: str) -> Path:
    return data_directory / "embeddings" / retriever.replace("/", "--")


def write_embeddings(directory: Path, names: Sequence[str], embeddings: torch.Tensor) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / NAMES_FILE).write_text("\n".join(names) + "\n", encoding="utf-8")
    np.save(directory / EMBEDDINGS_FILE, embeddings.to(torch.float16).cpu().numpy())


def read_embeddings(directory: Path) -> tuple[list[str], torch.Tensor]:
    names = (directory / NAMES_FILE).read_text(encoding="utf-8").splitlines()
    return names, torch.from_numpy(np.load(directory / EMBEDDINGS_FILE))


class PremiseIndex:
    def __init__(self, names: Sequence[str], signatures: Sequence[str], embeddings: torch.Tensor) -> None:
        self.names = tuple(names)
        self.signatures = tuple(signatures)
        self.embeddings = embeddings

    def __len__(self) -> int:
        return len(self.names)

    def search(self, queries: torch.Tensor, count: int) -> list[tuple[RetrievedPremise, ...]]:
        scores = queries.to(self.embeddings.dtype) @ self.embeddings.T
        top = scores.float().topk(min(count, len(self.names)), dim=1)
        return [
            tuple(
                RetrievedPremise(self.names[index], self.signatures[index], score)
                for score, index in zip(row_scores, row_indices, strict=True)
            )
            for row_scores, row_indices in zip(top.values.tolist(), top.indices.tolist(), strict=True)
        ]


def load_premise_index(data_directory: Path, retriever: str, device: str) -> PremiseIndex:
    """The premises with a signature in the pinned environment; float32 on the CPU, float16 on a GPU."""
    names, embeddings = read_embeddings(embeddings_directory(data_directory, retriever))
    signatures = {
        signature.full_name: signature.signature for signature in read_signatures(data_directory / "signatures.jsonl")
    }
    rows = [row for row, name in enumerate(names) if name in signatures]
    dtype = torch.float32 if device == "cpu" else torch.float16
    return PremiseIndex(
        [names[row] for row in rows],
        [signatures[names[row]] for row in rows],
        embeddings[rows].to(device=device, dtype=dtype),
    )
