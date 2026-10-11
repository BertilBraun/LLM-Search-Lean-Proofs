"""miniF2F problems as vendored from DeepSeek-Prover-V1.5 (data/minif2f/minif2f.jsonl)."""

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

MINIF2F_PATH = Path(__file__).resolve().parents[3] / "data" / "minif2f" / "minif2f.jsonl"


class Split(StrEnum):
    VALID = "valid"
    TEST = "test"


@dataclass(frozen=True)
class Problem:
    name: str
    split: Split
    header: str
    formal_statement: str
    informal_prefix: str
    goal: str


def load_minif2f(split: Split | None = None, path: Path = MINIF2F_PATH) -> list[Problem]:
    with path.open(encoding="utf-8") as lines:
        rows = [json.loads(line) for line in lines if line.strip()]
    problems = [
        Problem(
            name=row["name"],
            split=Split(row["split"]),
            header=row["header"],
            formal_statement=row["formal_statement"],
            informal_prefix=row["informal_prefix"],
            goal=row["goal"],
        )
        for row in rows
    ]
    return [problem for problem in problems if split is None or problem.split == split]
