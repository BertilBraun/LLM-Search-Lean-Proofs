"""Compare finished SFT runs side by side (validation loss, exact match, throughput) and collect their summaries."""

import argparse
import json
import os
import shutil
from pathlib import Path

from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table
from lean_search.training.sft import FineTuningMethod, SftRunSummary

RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
COPIED_FILES = ("steps.jsonl", "evaluations.jsonl")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-name", required=True, help="run directory that receives summary/sft_runs.md")
    parser.add_argument("--runs", nargs="+", required=True)
    return parser.parse_args()


def load_summary(run_name: str) -> SftRunSummary:
    text = (RUNS_DIRECTORY / run_name / "summary" / "summary.json").read_text(encoding="utf-8")
    return from_json_object(SftRunSummary, json.loads(text))


def method_label(summary: SftRunSummary) -> str:
    match summary.config.optimization.method:
        case FineTuningMethod.LORA:
            return f"LoRA r{summary.config.lora.rank}"
        case FineTuningMethod.FULL:
            return "full"


def comparison_table(summaries: list[SftRunSummary]) -> str:
    rows = []
    for summary in summaries:
        result = summary.result
        first, final = result.evaluations[0], result.evaluations[-1]
        rows.append(
            [
                summary.run_name,
                f"`{summary.config.model}`",
                method_label(summary),
                f"{summary.config.optimization.learning_rate:g}",
                f"{result.tokens:,}",
                f"{result.steps:,}",
                f"{result.training_seconds / 60:.0f}",
                f"{result.tokens_per_second:,.0f}",
                f"{result.peak_memory_gib:.1f}",
                f"{first.validation_loss:.4f} → {final.validation_loss:.4f}",
                f"{first.teacher_forced_exact_match:.1%} → {final.teacher_forced_exact_match:.1%}",
                f"{first.generation_exact_match:.1%} → {final.generation_exact_match:.1%}",
            ]
        )
    return markdown_table(
        [
            "Run",
            "Model",
            "Method",
            "Learning rate",
            "Tokens",
            "Steps",
            "Minutes",
            "Tokens/s",
            "Peak GiB",
            "Validation loss",
            "Teacher-forced exact match",
            "Generation exact match",
        ],
        rows,
    )


def curve_table(summaries: list[SftRunSummary]) -> str:
    steps = sorted({evaluation.step for summary in summaries for evaluation in summary.result.evaluations})
    losses = {
        summary.run_name: {evaluation.step: evaluation.validation_loss for evaluation in summary.result.evaluations}
        for summary in summaries
    }
    rows = [
        [
            step,
            *(
                f"{losses[summary.run_name][step]:.4f}" if step in losses[summary.run_name] else ""
                for summary in summaries
            ),
        ]
        for step in steps
    ]
    return markdown_table(["Step", *(summary.run_name for summary in summaries)], rows)


def main() -> None:
    arguments = parse_arguments()
    summaries = [load_summary(run_name) for run_name in arguments.runs]
    output_directory = RUNS_DIRECTORY / arguments.report_name / "summary"
    for summary in summaries:
        run_directory = output_directory / "runs" / summary.run_name
        run_directory.mkdir(parents=True, exist_ok=True)
        source = RUNS_DIRECTORY / summary.run_name
        shutil.copyfile(source / "summary" / "README.md", run_directory / "README.md")
        shutil.copyfile(source / "summary" / "summary.json", run_directory / "summary.json")
        for name in COPIED_FILES:
            shutil.copyfile(source / name, run_directory / name)
    data_names = sorted({summary.config.data for summary in summaries})
    sections = [
        "# SFT runs",
        f"Data: {', '.join(f'`{name}`' for name in data_names)}. Arrows go from the evaluation before training to the "
        "final one. Validation loss is the mean completion-token loss on held-out steps; teacher-forced exact match "
        "counts steps whose every target token is the argmax; generation exact match compares greedy generations "
        "with the normalized target. Per-run details under `runs/`.",
        comparison_table(summaries),
        "## Validation loss during training",
        curve_table(summaries),
    ]
    markdown = "\n\n".join(sections) + "\n"
    (output_directory / "sft_runs.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
