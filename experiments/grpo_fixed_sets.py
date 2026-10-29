"""The GRPO loop's held-out sets: choose the probe and value-gate statements, rename statements, build the gate.

    python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml select
    python experiments/grpo_fixed_sets.py --config ... select-overfit       # the overfit test's 300 statements
    python experiments/grpo_fixed_sets.py --config ... gate-benchmark \
        --search-config experiments/configs/grpo/gate_search.toml --run-name grpo_gate_search \
        --output grpo_gate/benchmark.json.gz [--renamings grpo/renamings.jsonl]
    python experiments/grpo_fixed_sets.py --config ... rename \
        --rewrite-config experiments/configs/data_rewrite/rewrite_visible_student_v2.toml \
        --sources probe gate pool minif2f --output grpo/renamings.jsonl

select (once, CPU only) writes $LEAN_SEARCH_DATA/grpo/fixed_sets/{probe,gate}.jsonl: verified pool v3 statements,
easy / medium / hard by the curriculum's difficulty estimate, the same number per stratum, disjoint; the loop's
curriculum never feeds them. It refuses to overwrite existing sets (they are fixed for the whole run).

gate-benchmark (once, ~1-2 h with the starting policy served, no value model) searches the gate set by log-probability
best-first (value-free, so no value model chose its labels) into $LEAN_SEARCH_RUNS/<run-name>/ and builds the value
benchmark from those trees into $LEAN_SEARCH_RUNS/<output>, the loop's `training.value_benchmark`. Resumable.

rename (only for a starting policy trained on descriptive names; the naming A/B's named arm) renames the statements'
numbered hypotheses with the data rewrite's namer and NamingConfig (its [namer] server, or rules when its model is
empty) and writes the renamings the loop, the evaluations and the gate search read ([renaming] in the loop config).
"""

import argparse
import asyncio
import dataclasses
import json
import os
import tomllib
from collections import Counter
from pathlib import Path

from lean_search.data import Problem, Split, load_minif2f
from lean_search.data_rewrite.model_namer import open_namer
from lean_search.data_rewrite.rewrite import RewriteConfig
from lean_search.expert_iteration.known_proofs import read_verified
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.lean.identifiers import environment_names
from lean_search.rl.evaluation import EvaluationPaths, EvaluationProblem, search_problem_set
from lean_search.rl.fixed_sets import (
    FixedSetsConfig,
    HeldOutStatement,
    candidates,
    read_fixed_set,
    select_fixed_sets,
    select_overfit_set,
    write_fixed_set,
)
from lean_search.rl.renaming import read_renamings, rename_problems, write_renamings
from lean_search.search import TreeRecord, load_run_config, read_tree
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import from_json_object
from lean_search.value.benchmark import (
    BenchmarkConfig,
    LabelledTree,
    TreeSource,
    benchmark_composition,
    build_benchmark,
    conflict_message,
    guidance_conflicts,
    search_provenance,
    write_benchmark,
)
from lean_search.value.graph_targets import RemainingStepsReadout, ValueTargetConfig, recorded_estimates, value_targets

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
SOURCES = ("probe", "gate", "pool", "minif2f")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("select")
    commands.add_parser("select-overfit")
    gate = commands.add_parser("gate-benchmark")
    gate.add_argument("--search-config", type=Path, required=True)
    gate.add_argument("--run-name", required=True)
    gate.add_argument("--output", required=True, help="under $LEAN_SEARCH_RUNS")
    gate.add_argument("--renamings", nargs="*", default=[], help="renaming files under $LEAN_SEARCH_DATA")
    rename = commands.add_parser("rename")
    rename.add_argument("--rewrite-config", type=Path, required=True)
    rename.add_argument("--sources", nargs="+", choices=SOURCES, required=True)
    rename.add_argument("--output", required=True, help="under $LEAN_SEARCH_DATA")
    return parser.parse_args()


def load_config(path: Path) -> FixedSetsConfig:
    return from_json_object(FixedSetsConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def composition(statements: list[HeldOutStatement]) -> str:
    counts = Counter(statement.stratum.value for statement in statements)
    sources = Counter(statement.statement.source for statement in statements)
    return (
        f"{len(statements)} statements, strata {dict(sorted(counts.items()))}, sources {dict(sorted(sources.items()))}"
    )


def select(config: FixedSetsConfig) -> None:
    probe_path = DATA_DIRECTORY / config.probe_set
    gate_path = DATA_DIRECTORY / config.gate_set
    if probe_path.exists() or gate_path.exists():
        raise SystemExit(f"{probe_path} or {gate_path} exists: the held-out sets are fixed once chosen.")
    verified, _ = read_verified(DATA_DIRECTORY / config.curriculum.verified)
    sets = select_fixed_sets(verified, config)
    write_fixed_set(probe_path, sets.probe)
    write_fixed_set(gate_path, sets.gate)
    print(f"probe: {composition(list(sets.probe))} -> {probe_path}")
    print(f"gate: {composition(list(sets.gate))} -> {gate_path}")


def select_overfit(config: FixedSetsConfig) -> None:
    path = DATA_DIRECTORY / config.overfit_set
    if path.exists():
        raise SystemExit(f"{path} exists: the overfit set is fixed once chosen.")
    held_out = read_fixed_set(DATA_DIRECTORY / config.probe_set) + read_fixed_set(DATA_DIRECTORY / config.gate_set)
    verified, _ = read_verified(DATA_DIRECTORY / config.curriculum.verified)
    chosen = select_overfit_set(verified, config, {statement.name for statement in held_out})
    write_fixed_set(path, chosen)
    print(f"overfit: {composition(list(chosen))} -> {path}")


def labelled_tree(record: TreeRecord) -> LabelledTree:
    labels = label_graph(record)
    targets = value_targets(record, labels, recorded_estimates(record, RemainingStepsReadout()), ValueTargetConfig())
    return LabelledTree(record, labels, targets)


async def gate_benchmark(config: FixedSetsConfig, arguments: argparse.Namespace) -> None:
    search_config = load_run_config(arguments.search_config)
    if search_config.value.model:
        raise SystemExit("The gate's trees come from a search without a value model (no circular labels).")
    problems = [
        EvaluationProblem(statement.problem, statement.stratum.value)
        for statement in read_fixed_set(DATA_DIRECTORY / config.gate_set)
    ]
    paths = EvaluationPaths(RUNS_DIRECTORY / arguments.run_name)
    renamings = read_renamings([DATA_DIRECTORY / path for path in arguments.renamings]) if arguments.renamings else None
    results = await search_problem_set(
        problems, search_config, paths, lambda message: print(message, flush=True), renamings
    )
    print(f"gate search: {sum(result.proved for result in results)}/{len(results)} solved")
    records = [read_tree(path) for path in sorted(paths.trees.glob("*.json.gz"))]
    provenance = search_provenance(arguments.run_name, paths.config.read_text(encoding="utf-8"), records)
    conflicts = guidance_conflicts([provenance], None)
    if conflicts:
        raise SystemExit("\n".join(conflict_message(source) for source in conflicts))
    benchmark_config = BenchmarkConfig()
    benchmark = build_benchmark(
        [TreeSource(provenance, tuple(labelled_tree(record) for record in records))], benchmark_config
    )
    output = RUNS_DIRECTORY / arguments.output
    write_benchmark(output, benchmark)
    print(json.dumps(dataclasses.asdict(benchmark_composition(benchmark, benchmark_config)), indent=1))
    print(f"benchmark of {len(benchmark.states)} states -> {output}")


def source_problems(config: FixedSetsConfig, source: str) -> list[Problem]:
    match source:
        case "probe":
            return [statement.problem for statement in read_fixed_set(DATA_DIRECTORY / config.probe_set)]
        case "gate":
            return [statement.problem for statement in read_fixed_set(DATA_DIRECTORY / config.gate_set)]
        case "pool":
            verified, _ = read_verified(DATA_DIRECTORY / config.curriculum.verified)
            return [statement.problem for statement in candidates(verified, config)]
        case "minif2f":
            return load_minif2f(Split.VALID)
        case _:
            raise ValueError(f"Unknown source {source}")


async def rename(config: FixedSetsConfig, arguments: argparse.Namespace) -> None:
    rewrite = from_json_object(RewriteConfig, tomllib.loads(arguments.rewrite_config.read_text(encoding="utf-8")))
    problems = list(
        {problem.name: problem for source in arguments.sources for problem in source_problems(config, source)}.values()
    )
    header = Counter(problem.header for problem in problems).most_common(1)[0][0]
    async with LeanReplPool(1, LeanReplConfig()) as pool:
        await pool.start([header])
        async with pool.acquire() as repl:
            names = await environment_names(repl, header)
    reserved = frozenset(name for name in names.constants if "." not in name) | names.keywords
    async with open_namer(rewrite.namer, rewrite.naming) as namer:
        renamed = await rename_problems(problems, namer, rewrite.naming, reserved)
    count = write_renamings(DATA_DIRECTORY / arguments.output, renamed)
    changed = sum(bool(item.renaming.changes) for item in renamed)
    print(f"{count} statements, {changed} with renamed hypotheses -> {DATA_DIRECTORY / arguments.output}")


def main() -> None:
    arguments = parse_arguments()
    config = load_config(arguments.config)
    match arguments.command:
        case "select":
            select(config)
        case "select-overfit":
            select_overfit(config)
        case "gate-benchmark":
            asyncio.run(gate_benchmark(config, arguments))
        case "rename":
            asyncio.run(rename(config, arguments))


if __name__ == "__main__":
    main()
