"""Compare the list-length arms of the retrieval ablation (ladder row 3) on the same problems.

    python experiments/phase4_ablation_report.py --run-name phase4_ablation \
        --runs phase4_lemmas_00 phase4_lemmas_04 phase4_lemmas_08 phase4_lemmas_16 phase4_lemmas_32

Reads each run's config.toml, results.jsonl and policy.json under $LEAN_SEARCH_RUNS; writes
$LEAN_SEARCH_RUNS/<run-name>/summary/{summary.json,README.md}. The first run is the reference for paired counts.
"""

import argparse
import dataclasses
import json
import os
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.policy.expander import PolicyStatistics
from lean_search.search import SearchResult, load_run_config, read_results
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table

RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
EXPANSION_BUDGETS = (1, 4, 16, 64)


@dataclass(frozen=True)
class ArmOutcome:
    run: str
    lemma_count: int
    problems: int
    solved: int
    solved_within_expansions: tuple[int, ...]
    only_this_arm: int
    only_reference: int
    mean_expansions: float
    prompt_tokens_per_expansion: float
    generated_tokens_per_expansion: float
    search_lean_seconds_per_expansion: float
    annotation_lean_seconds_per_expansion: float
    retrieval_seconds_per_expansion: float
    closing_lemmas_shown_per_expansion: float
    mean_wall_seconds: float


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run-name", required=True)
    parser.add_argument("--runs", nargs="+", required=True)
    return parser.parse_args()


def solved_names(results: Sequence[SearchResult]) -> set[str]:
    return {result.problem_name for result in results if result.proved}


def arm_outcome(run: str, results: Sequence[SearchResult], reference: Sequence[SearchResult]) -> ArmOutcome:
    config = load_run_config(RUNS_DIRECTORY / run / "config.toml")
    policy = from_json_object(
        PolicyStatistics, json.loads((RUNS_DIRECTORY / run / "policy.json").read_text(encoding="utf-8"))
    )
    accountings = [result.accounting for result in results]
    expansions = sum(accounting.expansions for accounting in accountings)
    lemmas = policy.lemmas
    lemma_expansions = max(1, lemmas.expansions) if lemmas else 1
    solved = solved_names(results)
    return ArmOutcome(
        run=run,
        lemma_count=config.policy.retrieval.lemma_count,
        problems=len(results),
        solved=len(solved),
        solved_within_expansions=tuple(
            sum(result.solved_at is not None and result.solved_at.expansions <= budget for result in results)
            for budget in EXPANSION_BUDGETS
        ),
        only_this_arm=len(solved - solved_names(reference)),
        only_reference=len(solved_names(reference) - solved),
        mean_expansions=expansions / len(results),
        prompt_tokens_per_expansion=sum(accounting.prompt_tokens for accounting in accountings) / expansions,
        generated_tokens_per_expansion=sum(accounting.generated_tokens for accounting in accountings) / expansions,
        search_lean_seconds_per_expansion=sum(accounting.lean_seconds for accounting in accountings) / expansions,
        annotation_lean_seconds_per_expansion=lemmas.annotation_lean_seconds / lemma_expansions if lemmas else 0.0,
        retrieval_seconds_per_expansion=lemmas.retrieval_seconds / lemma_expansions if lemmas else 0.0,
        closing_lemmas_shown_per_expansion=lemmas.shown_closing / lemma_expansions if lemmas else 0.0,
        mean_wall_seconds=statistics.fmean(accounting.wall_seconds for accounting in accountings),
    )


def render_markdown(arms: Sequence[ArmOutcome]) -> str:
    rows = [
        [
            arm.lemma_count,
            f"{arm.solved}/{arm.problems}",
            *[str(count) for count in arm.solved_within_expansions],
            f"+{arm.only_this_arm} / -{arm.only_reference}",
            f"{arm.mean_expansions:.1f}",
            f"{arm.prompt_tokens_per_expansion:.0f}",
            f"{arm.generated_tokens_per_expansion:.0f}",
            f"{arm.search_lean_seconds_per_expansion:.2f}",
            f"{arm.annotation_lean_seconds_per_expansion:.2f}",
            f"{arm.retrieval_seconds_per_expansion * 1000:.0f}",
            f"{arm.closing_lemmas_shown_per_expansion:.2f}",
            f"{arm.mean_wall_seconds:.0f}",
        ]
        for arm in arms
    ]
    headers = [
        "List length",
        "Solved",
        *[f"≤{budget} exp." for budget in EXPANSION_BUDGETS],
        f"vs {arms[0].lemma_count}",
        "Expansions",
        "Prompt tok/exp.",
        "Generated tok/exp.",
        "Search Lean s/exp.",
        "Check Lean s/exp.",
        "Retrieval ms/exp.",
        "Closing lemmas shown/exp.",
        "Wall s",
    ]
    return (
        "# Retrieval ablation: lemma-list length\n\n"
        "Same problems, adapter and budget in every arm; only the list length differs. `vs` counts problems solved "
        "only by the arm and only by the reference arm. Search Lean seconds exclude the applicability check, which is "
        "listed separately; retrieval time is the wait for the shared encoder.\n\n"
        + markdown_table(headers, rows)
        + "\n"
    )


def main() -> None:
    arguments = parse_arguments()
    results = {run: read_results(RUNS_DIRECTORY / run / "results.jsonl") for run in arguments.runs}
    reference = results[arguments.runs[0]]
    arms = [arm_outcome(run, results[run], reference) for run in arguments.runs]
    directory = RUNS_DIRECTORY / arguments.run_name / "summary"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "summary.json").write_text(
        json.dumps([dataclasses.asdict(arm) for arm in arms], indent=1), encoding="utf-8"
    )
    markdown = render_markdown(arms)
    (directory / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
