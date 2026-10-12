"""Offline recall@k of the retriever: LeanDojo novel-premises states and traced competition steps.

    python experiments/phase4_recall.py --device cuda:0

Modes: `all` ranks every LeanDojo premise; `accessible` only those the theorem can import or that precede it in its
file (ReProver's protocol); `deployed` ranks the search's index (LeanDojo premises that exist in the pinned
environment plus the added environment theorems; gold premises restricted to existing ones). `competition` uses
traced validation-split competition steps whose text names an indexed premise (the step's named premises are gold),
ranked against the deployed index. Writes
$LEAN_SEARCH_RUNS/<run-name>/summary/{summary.json,README.md} (default phase4_recall); --retriever evaluates a
fine-tuned encoder directory whose premises phase4_embed_premises.py has embedded.
"""

import argparse
import dataclasses
import json
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import torch

from lean_search.corpora.records import (
    PremiseRecord,
    TacticExample,
    read_file_imports,
    read_premise_records,
    read_tactic_examples,
    read_traced_steps,
)
from lean_search.retrieval.config import DEFAULT_RETRIEVER
from lean_search.retrieval.encoder import TextEncoder
from lean_search.retrieval.index import embeddings_directory, read_embeddings
from lean_search.retrieval.premises import (
    MINIF2F_OPEN_NAMESPACES,
    read_signatures,
    serialize_goals,
    step_premises,
    strip_leandojo_goal_count,
)
from lean_search.retrieval.recall import RankedExample, RecallSummary, summarize_recall, transitive_imports
from lean_search.search.summary import markdown_table

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
MATHLIB_DIRECTORY = DATA_DIRECTORY / "normalized" / "mathlib"
RETRIEVAL_DIRECTORY = DATA_DIRECTORY / "retrieval"
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
KS = (1, 4, 8, 10, 16, 32, 64)
QUERY_CHUNK = 256


@dataclass(frozen=True)
class Query:
    state: str
    gold: frozenset[str]
    file_path: str
    line: int


@dataclass(frozen=True)
class ModeResult:
    mode: str
    split: str
    summary: RecallSummary
    seconds: float


type MaskFunction = Callable[[Sequence[Query]], torch.Tensor]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--retriever", default=DEFAULT_RETRIEVER, help="Hugging Face name or encoder directory")
    parser.add_argument("--run-name", default="phase4_recall")
    parser.add_argument("--limit", type=int, help="queries per split, for a quick run")
    return parser.parse_args()


def leandojo_queries(examples: Sequence[TacticExample], corpus: set[str]) -> list[Query]:
    queries = []
    for example in examples:
        gold = frozenset(premise.full_name for premise in example.premises) & corpus
        if gold:
            queries.append(
                Query(
                    strip_leandojo_goal_count(example.state_before), gold, example.file_path, example.theorem_start_line
                )
            )
    return queries


def competition_queries(existing: set[str]) -> list[Query]:
    queries = []
    for step in read_traced_steps(DATA_DIRECTORY / "traced" / "steps_validation.jsonl"):
        gold = frozenset(step_premises(step.step, existing, MINIF2F_OPEN_NAMESPACES))
        if gold:
            queries.append(Query(serialize_goals(step.goals_before), gold, "", 0))
    return queries


def rank(
    queries: Sequence[Query],
    encoder: TextEncoder,
    names: Sequence[str],
    embeddings: torch.Tensor,
    mask: MaskFunction | None,
) -> list[RankedExample]:
    examples = []
    for start in range(0, len(queries), QUERY_CHUNK):
        chunk = queries[start : start + QUERY_CHUNK]
        scores = encoder.encode([query.state for query in chunk]).to(embeddings.dtype) @ embeddings.T
        if mask is not None:
            scores = scores.masked_fill(~mask(chunk), float("-inf"))
        top = scores.float().topk(max(KS), dim=1).indices.tolist()
        examples += [
            RankedExample(query.gold, tuple(names[index] for index in row))
            for query, row in zip(chunk, top, strict=True)
        ]
    return examples


def accessible_mask_function(premises: Sequence[PremiseRecord], device: str) -> MaskFunction:
    imports = {
        record.file_path: record.imports for record in read_file_imports(MATHLIB_DIRECTORY / "file_imports.jsonl")
    }
    closure = transitive_imports(imports)
    file_ids = {file_path: index for index, file_path in enumerate(imports)}
    premise_files = torch.tensor([file_ids.get(premise.file_path, -1) for premise in premises], device=device)
    premise_lines = torch.tensor([premise.start_line for premise in premises], device=device)
    file_masks: dict[str, torch.Tensor] = {}

    def file_mask(file_path: str) -> torch.Tensor:
        if file_path not in file_masks:
            mask = torch.zeros(len(file_ids) + 1, dtype=torch.bool, device=device)
            mask[[file_ids[imported] for imported in closure.get(file_path, ())]] = True
            file_masks[file_path] = mask
        return file_masks[file_path]

    def mask(queries: Sequence[Query]) -> torch.Tensor:
        rows = []
        for query in queries:
            own = file_ids.get(query.file_path, -2)
            imported = file_mask(query.file_path)[premise_files]
            rows.append(imported | ((premise_files == own) & (premise_lines < query.line)))
        return torch.stack(rows)

    return mask


def render_markdown(results: Sequence[ModeResult], query_counts: dict[str, int], retriever: str) -> str:
    headers = ["Mode", "Split", "States", "Gold/state", *[f"R@{k}" for k in KS], "Hit@8", "Hit@32", "MRR"]
    rows = []
    for result in results:
        summary = result.summary
        by_k = {row.k: row for row in summary.at_k}
        rows.append(
            [
                result.mode,
                result.split,
                f"{summary.examples:,}",
                f"{summary.mean_gold_premises:.2f}",
                *[f"{by_k[k].recall:.3f}" for k in KS],
                f"{by_k[8].hit_rate:.3f}",
                f"{by_k[32].hit_rate:.3f}",
                f"{summary.mean_reciprocal_rank:.3f}",
            ]
        )
    counts = ", ".join(f"{name}: {count:,}" for name, count in query_counts.items())
    return (
        "# Offline recall of the ReProver retriever\n\n"
        f"`{retriever}`, premise embeddings in float16. R@k: mean fraction of a state's gold premises in the "
        "top k (ReProver's metric); Hit@k: states with at least one gold premise in the top k. States with at least "
        f"one gold premise: {counts}.\n\n" + markdown_table(headers, rows) + "\n"
    )


def main() -> None:
    arguments = parse_arguments()
    all_names, stored = read_embeddings(embeddings_directory(RETRIEVAL_DIRECTORY, arguments.retriever))
    all_embeddings = stored.to(device=arguments.device, dtype=torch.float16)
    premise_by_name: dict[str, PremiseRecord] = {}
    for record in read_premise_records(MATHLIB_DIRECTORY / "premises.jsonl"):
        premise_by_name.setdefault(record.full_name, record)
    leandojo_rows = [row for row, name in enumerate(all_names) if name in premise_by_name]
    names = [all_names[row] for row in leandojo_rows]
    embeddings = all_embeddings[leandojo_rows]
    existing = {signature.full_name for signature in read_signatures(RETRIEVAL_DIRECTORY / "signatures.jsonl")}
    deployed_rows = [row for row, name in enumerate(all_names) if name in existing]
    deployed_names = [all_names[row] for row in deployed_rows]
    deployed_embeddings = all_embeddings[deployed_rows]
    encoder = TextEncoder(arguments.retriever, arguments.device, torch.bfloat16)
    accessible = accessible_mask_function([premise_by_name[name] for name in names], arguments.device)
    corpus = set(names)
    results: list[ModeResult] = []
    query_counts: dict[str, int] = {}
    for split in ("val", "test"):
        examples = list(read_tactic_examples(MATHLIB_DIRECTORY / f"tactics_novel_premises_{split}.jsonl"))
        queries = leandojo_queries(examples, corpus)[: arguments.limit]
        query_counts[f"novel_premises/{split}"] = len(queries)
        deployed_queries = [
            dataclasses.replace(query, gold=query.gold & existing) for query in queries if query.gold & existing
        ]
        for mode, mode_queries, mode_names, mode_embeddings, mask in (
            ("all", queries, names, embeddings, None),
            ("accessible", queries, names, embeddings, accessible),
            ("deployed", deployed_queries, deployed_names, deployed_embeddings, None),
        ):
            started = time.perf_counter()
            ranked = rank(mode_queries, encoder, mode_names, mode_embeddings, mask)
            results.append(
                ModeResult(mode, f"novel_premises/{split}", summarize_recall(ranked, KS), time.perf_counter() - started)
            )
            print(results[-1], flush=True)
    queries = competition_queries(existing)[: arguments.limit]
    query_counts["competition/validation"] = len(queries)
    started = time.perf_counter()
    ranked = rank(queries, encoder, deployed_names, deployed_embeddings, None)
    results.append(
        ModeResult("competition", "traced/validation", summarize_recall(ranked, KS), time.perf_counter() - started)
    )
    directory = RUNS_DIRECTORY / arguments.run_name / "summary"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps([dataclasses.asdict(result) for result in results], indent=1), encoding="utf-8"
    )
    markdown = render_markdown(results, query_counts, arguments.retriever)
    (directory / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
