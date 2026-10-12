"""Fine-tune the ReProver retriever on traced competition steps that name a premise of the deployed index.

    python experiments/phase4_retriever_finetune.py \
        --config experiments/configs/retrieval/phase4_retriever_finetune.toml \
        --stage data           # CPU: examples from the traced train split (+ LeanDojo novel-premises train states)
    python experiments/phase4_retriever_finetune.py --config ... --stage mine --device cuda:0
                                # hard negatives: the current retriever's top candidates that are not gold
    [torchrun --nproc-per-node 2] experiments/phase4_retriever_finetune.py --config ... --stage train

Positives are the premises a step names, negatives the other queries' premises in the batch plus mined hard
negatives; the loss is ReProver's (squared error between cosine similarity and the 0/1 label). Writes
$LEAN_SEARCH_DATA/retrieval/finetune/, $LEAN_SEARCH_CHECKPOINTS/phase4_retriever_finetune/encoder and
$LEAN_SEARCH_RUNS/phase4_retriever_finetune/summary/. Evaluate afterwards with phase4_embed_premises.py and
phase4_recall.py (--retriever <encoder directory>).
"""

import argparse
import dataclasses
import json
import os
import statistics
import time
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import torch

from lean_search.corpora.records import read_premise_records, read_tactic_examples, read_traced_steps
from lean_search.retrieval.encoder import TextEncoder
from lean_search.retrieval.finetune import (
    RetrieverEvaluation,
    RetrieverExample,
    RetrieverFinetuneConfig,
    RetrieverStepRecord,
    RetrieverTrainingResult,
    competition_examples,
    in_fixed_order,
    leandojo_examples,
    read_retriever_examples,
    train_retriever,
    with_hard_negatives,
    write_retriever_examples,
)
from lean_search.retrieval.index import load_premise_index
from lean_search.retrieval.premises import read_signatures, serialize_premise
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table
from lean_search.training.sft import distributed_context

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RETRIEVAL_DIRECTORY = DATA_DIRECTORY / "retrieval"
WORK_DIRECTORY = RETRIEVAL_DIRECTORY / "finetune"
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase4_retriever_finetune"
CHECKPOINT_DIRECTORY = Path(os.environ["LEAN_SEARCH_CHECKPOINTS"]) / "phase4_retriever_finetune"
PREMISE_PATHS = (
    DATA_DIRECTORY / "normalized" / "mathlib" / "premises.jsonl",
    RETRIEVAL_DIRECTORY / "environment_premises.jsonl",
)


class Stage(StrEnum):
    DATA = "data"
    MINE = "mine"
    TRAIN = "train"


@dataclass(frozen=True)
class DataCounts:
    split: str
    origin: str
    available: int
    selected: int
    mean_gold: float


@dataclass(frozen=True)
class FinetuneSummary:
    config: RetrieverFinetuneConfig
    data: tuple[DataCounts, ...]
    world_size: int
    result: RetrieverTrainingResult
    encoder_directory: str


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--stage", type=Stage, choices=list(Stage), required=True)
    parser.add_argument("--device", default="cuda:0")
    return parser.parse_args()


def deployed_names() -> set[str]:
    return {signature.full_name for signature in read_signatures(RETRIEVAL_DIRECTORY / "signatures.jsonl")}


def premise_texts(names: set[str]) -> dict[str, str]:
    texts: dict[str, str] = {}
    for path in PREMISE_PATHS:
        for record in read_premise_records(path):
            if record.full_name in names and record.full_name not in texts:
                texts[record.full_name] = serialize_premise(record.full_name, record.code)
    return texts


def counts(split: str, origin: str, available: int, selected: list[RetrieverExample]) -> DataCounts:
    mean_gold = statistics.fmean(len(example.gold) for example in selected) if selected else 0.0
    return DataCounts(split, origin, available, len(selected), mean_gold)


def build_data(config: RetrieverFinetuneConfig) -> None:
    known = deployed_names()
    seed = config.data.seed
    competition = in_fixed_order(
        competition_examples(read_traced_steps(DATA_DIRECTORY / "traced" / "steps_train.jsonl"), known), seed
    )
    mathlib = in_fixed_order(
        leandojo_examples(
            read_tactic_examples(DATA_DIRECTORY / "normalized" / "mathlib" / "tactics_novel_premises_train.jsonl"),
            known,
        ),
        seed,
    )
    validation = in_fixed_order(
        competition_examples(read_traced_steps(DATA_DIRECTORY / "traced" / "steps_validation.jsonl"), known), seed
    )
    train = competition[: config.data.max_competition_examples] + mathlib[: config.data.max_leandojo_examples]
    write_retriever_examples(WORK_DIRECTORY / "train.jsonl", in_fixed_order(train, seed))
    write_retriever_examples(WORK_DIRECTORY / "validation.jsonl", validation)
    rows = [
        counts("train", "competition", len(competition), competition[: config.data.max_competition_examples]),
        counts("train", "leandojo", len(mathlib), mathlib[: config.data.max_leandojo_examples]),
        counts("validation", "competition", len(validation), validation),
    ]
    (WORK_DIRECTORY / "data_counts.json").write_text(json.dumps([dataclasses.asdict(row) for row in rows], indent=1))
    for row in rows:
        print(row)


def mine(config: RetrieverFinetuneConfig, device: str) -> None:
    encoder = TextEncoder(config.base_model, device, torch.bfloat16)
    index = load_premise_index(RETRIEVAL_DIRECTORY, config.base_model, device)
    for split in ("train", "validation"):
        started = time.perf_counter()
        examples = list(read_retriever_examples(WORK_DIRECTORY / f"{split}.jsonl"))
        mined = []
        for start in range(0, len(examples), 1024):
            chunk = examples[start : start + 1024]
            retrieved = index.search(encoder.encode([example.query for example in chunk]), config.data.mined_candidates)
            mined += [
                with_hard_negatives(example, [premise.full_name for premise in premises])
                for example, premises in zip(chunk, retrieved, strict=True)
            ]
        write_retriever_examples(WORK_DIRECTORY / f"{split}_mined.jsonl", mined)
        gold_in_top = statistics.fmean(len(example.hard_negatives) < config.data.mined_candidates for example in mined)
        print(
            f"{split}: {len(mined):,} examples mined in {time.perf_counter() - started:.0f} s; "
            f"a gold premise in the top {config.data.mined_candidates}: {gold_in_top:.1%}",
            flush=True,
        )


def render_markdown(summary: FinetuneSummary) -> str:
    training = summary.config.training
    result = summary.result
    data_rows = [
        [row.split, row.origin, f"{row.available:,}", f"{row.selected:,}", f"{row.mean_gold:.2f}"]
        for row in summary.data
    ]
    evaluation_rows = [
        [
            evaluation.step,
            f"{evaluation.loss:.4f}",
            f"{evaluation.mean_reciprocal_rank:.3f}",
            f"{evaluation.top_one:.3f}",
        ]
        for evaluation in result.evaluations
    ]
    return (
        "\n\n".join(
            [
                "# Retriever fine-tuning",
                f"`{summary.config.base_model}` fine-tuned with ReProver's loss (squared error between cosine "
                f"similarity and the 0/1 label) on batches of {training.batch_examples} queries per GPU on "
                f"{summary.world_size} GPU(s), each with one sampled positive and {training.hard_negatives} hard "
                f"negatives from the base retriever's top {summary.config.data.mined_candidates}; every premise in "
                f"a batch scores every query. Learning rate {training.learning_rate:g}, warmup "
                f"{training.warmup_fraction:g}, cosine to {training.minimum_learning_rate_ratio:g}; {result.steps:,} "
                f"steps ({result.examples:,} queries) in {result.training_seconds / 60:.1f} min, peak "
                f"{result.peak_memory_gib:.1f} GiB. Encoder: `{summary.encoder_directory}`.",
                markdown_table(["Split", "Origin", "Available", "Used", "Gold per example"], data_rows),
                "Validation (traced validation-split competition steps; ranks among each validation batch's premises, "
                "a proxy until the premises are re-embedded):",
                markdown_table(["Step", "Loss", "In-batch MRR", "In-batch top-1"], evaluation_rows),
            ]
        )
        + "\n"
    )


def train(config: RetrieverFinetuneConfig) -> None:
    context = distributed_context()
    examples = list(read_retriever_examples(WORK_DIRECTORY / "train_mined.jsonl"))
    validation = list(read_retriever_examples(WORK_DIRECTORY / "validation_mined.jsonl"))
    texts = premise_texts(deployed_names())
    encoder_directory = CHECKPOINT_DIRECTORY / "encoder"
    if context.is_main:
        (RUN_DIRECTORY / "summary").mkdir(parents=True, exist_ok=True)
        (RUN_DIRECTORY / "steps.jsonl").unlink(missing_ok=True)

    def on_step(record: RetrieverStepRecord) -> None:
        with (RUN_DIRECTORY / "steps.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(dataclasses.asdict(record)) + "\n")
        if record.step % 50 == 0:
            print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: RetrieverEvaluation) -> None:
        print(f"evaluation {record}", flush=True)

    result = train_retriever(
        config.base_model,
        examples,
        validation,
        texts,
        config.training,
        context,
        encoder_directory,
        on_step,
        on_evaluation,
    )
    if not context.is_main:
        return
    data = tuple(DataCounts(**row) for row in json.loads((WORK_DIRECTORY / "data_counts.json").read_text()))
    summary = FinetuneSummary(config, data, context.world_size, result, str(encoder_directory))
    (RUN_DIRECTORY / "summary" / "summary.json").write_text(json.dumps(dataclasses.asdict(summary), indent=1))
    markdown = render_markdown(summary)
    (RUN_DIRECTORY / "summary" / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


def main() -> None:
    arguments = parse_arguments()
    config = from_json_object(RetrieverFinetuneConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    WORK_DIRECTORY.mkdir(parents=True, exist_ok=True)
    match arguments.stage:
        case Stage.DATA:
            build_data(config)
        case Stage.MINE:
            mine(config, arguments.device)
        case Stage.TRAIN:
            train(config)


if __name__ == "__main__":
    main()
