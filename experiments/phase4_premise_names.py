"""Check which LeanDojo premises exist in the pinned environment and record their signatures for the prompt.

    python experiments/phase4_premise_names.py [--shards 4]

Also adds the environment's hand-written theorems that LeanDojo's corpus lacks (`to_additive` and `alias` lemmas such
as `add_comm` and `mul_pos`), with code synthesized from their signatures. Writes
$LEAN_SEARCH_DATA/retrieval/{signatures.jsonl,environment_premises.jsonl} and
$LEAN_SEARCH_RUNS/phase4_premise_names/summary/{summary.json,README.md}.
"""

import argparse
import collections
import dataclasses
import json
import os
import statistics
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from lean_search.corpora.records import PremiseRecord, read_premise_records, read_traced_steps, write_jsonl
from lean_search.lean.repl import PROJECT_DIRECTORY
from lean_search.retrieval.environment import (
    EnvironmentConstant,
    NameCheck,
    constant_dump_script,
    existing_signatures,
    missing_theorems,
    parse_constant_dump,
    parse_signature_dump,
    signature_dump_script,
)
from lean_search.retrieval.premises import (
    ENVIRONMENT_SOURCE,
    MINIF2F_OPEN_NAMESPACES,
    compact_signature,
    step_premises,
    synthesized_code,
    write_signatures,
)
from lean_search.search.summary import markdown_table

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
PREMISES_PATH = DATA_DIRECTORY / "normalized" / "mathlib" / "premises.jsonl"
RETRIEVAL_DIRECTORY = DATA_DIRECTORY / "retrieval"
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase4_premise_names"
COMPACT_CHARACTERS = 100_000
MISSING_EXAMPLES = 40


@dataclass(frozen=True)
class GroupCount:
    group: str
    premises: int
    missing: int


@dataclass(frozen=True)
class LengthSummary:
    mean: float
    p50: int
    p90: int
    p99: int
    maximum: int


@dataclass(frozen=True)
class NameCheckSummary:
    premises: int
    existing: int
    missing: int
    print_errors: int
    shards: int
    seconds: float
    by_kind: tuple[GroupCount, ...]
    by_library: tuple[GroupCount, ...]
    signature_characters: LengthSummary
    compact_signature_characters: LengthSummary
    missing_examples: tuple[str, ...]
    environment_theorems: int
    added_theorems: int
    # Theorem names that traced validation-split competition steps mention, and those in LeanDojo's corpus.
    competition_theorem_mentions: int
    competition_mentions_in_leandojo: int
    added_examples: tuple[str, ...]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--shards", type=int, default=4)
    return parser.parse_args()


def library(file_path: str) -> str:
    parts = file_path.split("/")
    if parts[0] == ".lake" and len(parts) > 2:
        return parts[2]
    return parts[0]


def length_summary(values: list[int]) -> LengthSummary:
    ordered = sorted(values)
    return LengthSummary(
        mean=statistics.fmean(ordered),
        p50=ordered[len(ordered) // 2],
        p90=ordered[int(0.9 * len(ordered))],
        p99=ordered[int(0.99 * len(ordered))],
        maximum=ordered[-1],
    )


def group_counts(
    premises: list[PremiseRecord], checks: dict[str, NameCheck], key: Callable[[PremiseRecord], str]
) -> tuple[GroupCount, ...]:
    totals: collections.Counter[str] = collections.Counter()
    missing: collections.Counter[str] = collections.Counter()
    for premise in premises:
        group = key(premise)
        totals[group] += 1
        missing[group] += not checks[premise.full_name].exists
    return tuple(GroupCount(group, count, missing[group]) for group, count in totals.most_common())


def competition_mentions(theorems: set[str], leandojo_names: set[str]) -> tuple[int, int]:
    mentions: collections.Counter[str] = collections.Counter()
    for step in read_traced_steps(DATA_DIRECTORY / "traced" / "steps_validation.jsonl"):
        mentions.update(step_premises(step.step, theorems, MINIF2F_OPEN_NAMESPACES))
    return sum(mentions.values()), sum(count for name, count in mentions.items() if name in leandojo_names)


def dump_constants(work_directory: Path) -> list[EnvironmentConstant]:
    work_directory.mkdir(parents=True, exist_ok=True)
    script_path = work_directory / "constants.lean"
    output_path = work_directory / "constants.tsv"
    script_path.write_text(constant_dump_script(output_path), encoding="utf-8")
    subprocess.run(["lake", "env", "lean", str(script_path)], cwd=PROJECT_DIRECTORY, check=True)
    return list(parse_constant_dump(output_path.read_text(encoding="utf-8").splitlines()))


def run_shards(names: list[str], shard_count: int, work_directory: Path) -> list[NameCheck]:
    work_directory.mkdir(parents=True, exist_ok=True)
    processes = []
    outputs = []
    for shard in range(shard_count):
        names_path = work_directory / f"names_{shard}.txt"
        output_path = work_directory / f"signatures_{shard}.tsv"
        script_path = work_directory / f"dump_{shard}.lean"
        names_path.write_text("\n".join(names[shard::shard_count]) + "\n", encoding="utf-8")
        script_path.write_text(signature_dump_script(names_path, output_path), encoding="utf-8")
        log = (work_directory / f"dump_{shard}.log").open("w", encoding="utf-8")
        processes.append(
            subprocess.Popen(
                ["lake", "env", "lean", str(script_path)], cwd=PROJECT_DIRECTORY, stdout=log, stderr=subprocess.STDOUT
            )
        )
        outputs.append(output_path)
    for process in processes:
        if process.wait() != 0:
            raise RuntimeError(f"A signature dump failed; see the logs in {work_directory}")
    checks: list[NameCheck] = []
    for output in outputs:
        checks.extend(parse_signature_dump(output.read_text(encoding="utf-8").splitlines()))
    return checks


def render_markdown(summary: NameCheckSummary) -> str:
    def group_rows(groups: tuple[GroupCount, ...]) -> list[list[str]]:
        return [
            [group.group, f"{group.premises:,}", f"{group.missing:,}", f"{group.missing / group.premises:.1%}"]
            for group in groups
        ]

    def length_row(name: str, lengths: LengthSummary) -> list[str]:
        return [name, f"{lengths.mean:.0f}", str(lengths.p50), str(lengths.p90), str(lengths.p99), str(lengths.maximum)]

    examples = ", ".join(f"`{name}`" for name in summary.missing_examples)
    sections = [
        "# Premise names in the pinned environment",
        f"LeanDojo Benchmark 4 v10 (Mathlib `29dcec07`) lists {summary.premises:,} premises. In our pinned "
        f"environment (Mathlib `d1d1e4b7`, `import Mathlib`) **{summary.existing:,} exist** and "
        f"**{summary.missing:,} ({summary.missing / summary.premises:.1%}) do not**. Names are compared as "
        "`Name.toString` against every constant of the environment; existing ones are printed with "
        f"`PrettyPrinter.ppSignature` ({summary.print_errors} failed to print and are dropped). "
        f"{summary.shards} Lean processes, {summary.seconds:.0f} s.",
        "## By library",
        markdown_table(["Library", "Premises", "Missing", "Share"], group_rows(summary.by_library)),
        "## By LeanDojo kind",
        markdown_table(["Kind", "Premises", "Missing", "Share"], group_rows(summary.by_kind)),
        "## Signature length (characters)",
        "Full: `ppSignature` on one line without universe parameters. Compact (the prompt's form): instance "
        "arguments and implicit type variables dropped.",
        markdown_table(
            ["Form", "Mean", "p50", "p90", "p99", "Max"],
            [
                length_row("full", summary.signature_characters),
                length_row("compact", summary.compact_signature_characters),
            ],
        ),
        f"Missing examples: {examples}.",
        "## Theorems LeanDojo lacks",
        f"The environment has {summary.environment_theorems:,} non-internal theorems. LeanDojo's corpus misses the "
        "ones that no source declaration introduces (`to_additive` translations, `alias`es, generated lemmas), "
        "among them common competition lemmas: `add_comm`, `mul_pos`, `mul_nonneg`, `Finset.sum_range_succ`, "
        f"`abs_of_nonneg`, `sub_nonneg`. Of the {summary.competition_theorem_mentions:,} theorem names that traced "
        "validation-split competition steps mention, "
        f"{1 - summary.competition_mentions_in_leandojo / summary.competition_theorem_mentions:.0%} are such theorems. "
        "Excluding compiler-generated companions (`proof_N`, `eq_N`, `match_N`, "
        "`sizeOf_spec`, `inj`, `injEq`) and metaprogramming namespaces (Lean, Mathlib, Aesop, Std, Batteries, ...), "
        f"**{summary.added_theorems:,} theorems are added** to the retrieval corpus with code `theorem <signature>` "
        f"synthesized from Lean's signature. Examples: {', '.join(f'`{name}`' for name in summary.added_examples)}.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    started = time.perf_counter()
    premises = list(read_premise_records(PREMISES_PATH))
    names = list(dict.fromkeys(premise.full_name for premise in premises))
    constants = dump_constants(RETRIEVAL_DIRECTORY / "environment")
    added = missing_theorems(constants, set(names))
    checks = run_shards(names + added, arguments.shards, RETRIEVAL_DIRECTORY / "environment")
    by_name = {check.full_name: check for check in checks}
    signatures = list(existing_signatures(checks))
    write_signatures(RETRIEVAL_DIRECTORY / "signatures.jsonl", signatures)
    added_premises = [
        PremiseRecord(ENVIRONMENT_SOURCE, name, "", 0, "theorem", synthesized_code(by_name[name].signature))
        for name in added
        if by_name[name].signature
    ]
    write_jsonl(RETRIEVAL_DIRECTORY / "environment_premises.jsonl", added_premises)
    missing = [name for name in names if not by_name[name].exists]
    theorems = {constant.full_name for constant in constants if constant.kind == "theorem"}
    mentions, mentions_in_leandojo = competition_mentions(theorems, set(names))
    summary = NameCheckSummary(
        premises=len(names),
        existing=len(names) - len(missing),
        missing=len(missing),
        print_errors=sum(by_name[name].exists and not by_name[name].signature for name in names),
        shards=arguments.shards,
        seconds=time.perf_counter() - started,
        by_kind=group_counts(premises, by_name, lambda premise: premise.kind),
        by_library=group_counts(premises, by_name, lambda premise: library(premise.file_path)),
        signature_characters=length_summary([len(signature.signature) for signature in signatures]),
        compact_signature_characters=length_summary(
            [
                len(compact_signature(signature.signature, signature.full_name, COMPACT_CHARACTERS))
                for signature in signatures
            ]
        ),
        missing_examples=tuple(missing[:: max(1, len(missing) // MISSING_EXAMPLES)][:MISSING_EXAMPLES]),
        environment_theorems=len(theorems),
        added_theorems=len(added_premises),
        competition_theorem_mentions=mentions,
        competition_mentions_in_leandojo=mentions_in_leandojo,
        added_examples=tuple(
            premise.full_name for premise in added_premises[:: max(1, len(added_premises) // MISSING_EXAMPLES)]
        )[:MISSING_EXAMPLES],
    )
    summary_directory = RUN_DIRECTORY / "summary"
    summary_directory.mkdir(parents=True, exist_ok=True)
    (summary_directory / "summary.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(summary)
    (summary_directory / "README.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
