import json
from collections.abc import Iterator
from pathlib import Path

from lean_search.corpora.records import FileImports, PremiseRecord, PremiseReference, TacticExample

SOURCE = "leandojo_benchmark_4_v10"
SPLIT_STRATEGIES = ("random", "novel_premises")
SPLITS = ("train", "val", "test")


def tactic_examples(benchmark_directory: Path, split_strategy: str, split: str) -> Iterator[TacticExample]:
    theorems = json.loads((benchmark_directory / split_strategy / f"{split}.json").read_text(encoding="utf-8"))
    for theorem in theorems:
        for tactic_index, traced in enumerate(theorem["traced_tactics"]):
            annotated_text, provenances = traced["annotated_tactic"]
            yield TacticExample(
                source=SOURCE,
                identifier=f"{theorem['full_name']}#{tactic_index}",
                split=f"{split_strategy}/{split}",
                file_path=theorem["file_path"],
                theorem_full_name=theorem["full_name"],
                theorem_start_line=theorem["start"][0],
                tactic_index=tactic_index,
                state_before=traced["state_before"],
                tactic=traced["tactic"],
                annotated_tactic=annotated_text,
                state_after=traced["state_after"],
                premises=tuple(
                    PremiseReference(provenance["full_name"], provenance["def_path"]) for provenance in provenances
                ),
            )


def premise_records(benchmark_directory: Path) -> Iterator[PremiseRecord]:
    with (benchmark_directory / "corpus.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            corpus_file = json.loads(line)
            for premise in corpus_file["premises"]:
                yield PremiseRecord(
                    source=SOURCE,
                    full_name=premise["full_name"],
                    file_path=corpus_file["path"],
                    start_line=premise["start"][0],
                    kind=premise["kind"],
                    code=premise["code"],
                )


def file_imports(benchmark_directory: Path) -> Iterator[FileImports]:
    with (benchmark_directory / "corpus.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            corpus_file = json.loads(line)
            yield FileImports(source=SOURCE, file_path=corpus_file["path"], imports=tuple(corpus_file["imports"]))
