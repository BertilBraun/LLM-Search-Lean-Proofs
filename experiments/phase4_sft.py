"""Train the lemma-aware policy adapter on data from phase4_sft_data.py with the Phase 2 trainer and report.

    torchrun --nproc-per-node 2 experiments/phase4_sft.py --config experiments/configs/retrieval/phase4_sft.toml \
        --run-name phase4_sft_lemmas

The config is a Phase 2 SFT config whose `data` names a lemma data set; `initial_adapter` continues the SFT v2
adapter. Outputs as phase2_sft.py: $LEAN_SEARCH_RUNS/<run>/summary/ and $LEAN_SEARCH_CHECKPOINTS/<run>/adapter.
"""

import dataclasses
import datetime
import importlib.util
import json
import os
import time

import phase2_sft
import transformers

from lean_search.retrieval.sft_data import read_lemma_examples, tokenize_lemma_example
from lean_search.training.sft import (
    EvaluationRecord,
    FineTuningMethod,
    SftRunSummary,
    StepRecord,
    distributed_context,
    train,
)


def main() -> None:
    # Variable-length micro-batches otherwise fragment the cache allocator into OOM.
    os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")
    arguments = phase2_sft.parse_arguments()
    started = datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds")
    config = phase2_sft.load_config(arguments)
    context = distributed_context()
    run_directory = phase2_sft.RUNS_DIRECTORY / arguments.run_name
    trained_directory = phase2_sft.CHECKPOINTS_DIRECTORY / arguments.run_name / "adapter"
    assert config.optimization.method == FineTuningMethod.LORA and not config.merge
    if context.is_main:
        (run_directory / "summary").mkdir(parents=True, exist_ok=True)
        for name in ("steps.jsonl", "evaluations.jsonl"):
            (run_directory / name).unlink(missing_ok=True)
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.model)
    tokenization_start = time.perf_counter()
    data_directory = phase2_sft.DATA_DIRECTORY / config.data
    train_examples, validation_examples = (
        [
            tokenize_lemma_example(tokenizer, example)
            for example in read_lemma_examples(data_directory / f"{split}.jsonl")
        ]
        for split in ("train", "validation")
    )
    tokenization_seconds = time.perf_counter() - tokenization_start
    if context.is_main:
        print(f"Tokenized {len(train_examples):,} train examples in {tokenization_seconds:.0f} s", flush=True)

    def on_step(record: StepRecord) -> None:
        phase2_sft.append_json_line(run_directory / "steps.jsonl", record)
        print(json.dumps(dataclasses.asdict(record)), flush=True)

    def on_evaluation(record: EvaluationRecord) -> None:
        phase2_sft.append_json_line(run_directory / "evaluations.jsonl", record)
        print(f"evaluation step {record.step}: loss {record.validation_loss:.4f}", flush=True)

    result = train(
        config, tokenizer, train_examples, validation_examples, context, trained_directory, on_step, on_evaluation
    )
    if not context.is_main:
        return
    summary = SftRunSummary(
        run_name=arguments.run_name,
        started=started,
        git_revision=phase2_sft.git_revision(),
        config=config,
        world_size=context.world_size,
        flash_linear_attention=importlib.util.find_spec("fla") is not None,
        train_examples=len(train_examples),
        train_tokens=sum(example.token_count for example in train_examples),
        validation_examples=len(validation_examples),
        tokenization_seconds=tokenization_seconds,
        result=result,
        trained_model_directory=str(trained_directory),
        merged_directory="",
        merge_seconds=0.0,
    )
    (run_directory / "summary" / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = phase2_sft.render_markdown(summary)
    (run_directory / "summary" / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown, flush=True)


if __name__ == "__main__":
    main()
