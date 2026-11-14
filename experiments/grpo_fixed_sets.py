"""The GRPO loop's held-out sets: choose the probe and gate statements, rename statements, build the value benchmark.

    python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/fixed_sets.toml select
    python experiments/grpo_fixed_sets.py --config ... select-overfit       # the overfit test's 300 statements
    python experiments/grpo_fixed_sets.py --config experiments/configs/grpo/followup/probe_v2.toml \
        select-by-characters --training-data $LEAN_SEARCH_DATA/sft $LEAN_SEARCH_DATA/reasoning $LEAN_SEARCH_DATA/value
    python experiments/grpo_fixed_sets.py --config ... gate-benchmark \
        --search-config experiments/configs/grpo/gate_search.toml --run-name grpo_gate_search \
        --output grpo_gate/benchmark.json.gz [--renamings grpo/renamings.jsonl] [--problems 24]
    python experiments/grpo_fixed_sets.py --config ... rename \
        --rewrite-config experiments/configs/data_rewrite/rewrite_visible_student_v2.toml \
        --sources probe gate pool minif2f --output grpo/renamings.jsonl

select (once, CPU only) writes $LEAN_SEARCH_DATA/grpo/fixed_sets/{probe,gate}.jsonl: verified pool v3 statements,
easy / medium / hard by the curriculum's difficulty estimate, the same number per stratum, disjoint; the loop's
curriculum never feeds them. It refuses to overwrite existing sets (they are fixed for the whole run).

select-by-characters (once, CPU only, a config of `CharacterStrataConfig`) writes the follow-up's probe v2: per band of
the shortest known proof's characters its count, in a seeded hash order, after dropping statements of the existing fixed
sets, statements of the held-out states, and those whose root state is a near-duplicate of a root state in the training
data (every *.jsonl under --training-data: the SFT, reasoning and value data, the published dataset's sft_data/). It
prints the drops per band and writes them beside the set (<output>.selection.json).

gate-benchmark (once, ~1-2 h with the starting policy served, no value model) searches the gate set by log-probability
best-first (value-free, so no value model chose its labels) into $LEAN_SEARCH_RUNS/<run-name>/ and builds the value
benchmark from those trees into $LEAN_SEARCH_RUNS/<output>, the loop's `evaluation.value_benchmark.path`. Resumable.
--problems N takes only the first N (strata in turn): a quick test of the command.

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
from dataclasses import dataclass
from pathlib import Path

from lean_search.data import Problem, Split, load_minif2f
from lean_search.data_rewrite.model_namer import open_namer
from lean_search.data_rewrite.rewrite import RewriteConfig
from lean_search.expert_iteration.known_proofs import read_verified
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.lean.identifiers import environment_names
from lean_search.reasoning.records import read_records
from lean_search.reasoning.states import ReasoningState
from lean_search.rl.evaluation import EvaluationPaths, EvaluationProblem, search_problem_set
from lean_search.rl.fixed_sets import (
    CharacterStrataConfig,
    Exclusions,
    FixedSetsConfig,
    HeldOutStatement,
    StratumDraw,
    candidates,
    character_candidates,
    read_fixed_set,
    same_statements,
    select_by_characters,
    select_fixed_sets,
    select_overfit_set,
    stratum_order,
    validate_character_strata,
    write_fixed_set,
)
from lean_search.rl.fixed_targets import first_problems_by_stratum
from lean_search.rl.renaming import read_renamings, rename_problems, write_renamings
from lean_search.rl.training_overlap import near_training_duplicates, training_root_states
from lean_search.search import TreeRecord, load_run_config, read_tree
from lean_search.search.graph_labels import label_graph
from lean_search.search.records import from_json_object, to_json
from lean_search.search.summary import markdown_table
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
    by_characters = commands.add_parser("select-by-characters")
    by_characters.add_argument(
        "--training-data", type=Path, nargs="+", required=True, help="directories of the training data's JSONL files"
    )
    gate = commands.add_parser("gate-benchmark")
    gate.add_argument("--search-config", type=Path, required=True)
    gate.add_argument("--run-name", required=True)
    gate.add_argument("--output", required=True, help="under $LEAN_SEARCH_RUNS")
    gate.add_argument("--renamings", nargs="*", default=[], help="renaming files under $LEAN_SEARCH_DATA")
    gate.add_argument(
        "--problems", type=int, default=0, help="only the first N of the gate set, strata in turn (a smoke test)"
    )
    rename = commands.add_parser("rename")
    rename.add_argument("--rewrite-config", type=Path, required=True)
    rename.add_argument("--sources", nargs="+", choices=SOURCES, required=True)
    rename.add_argument("--output", required=True, help="under $LEAN_SEARCH_DATA")
    return parser.parse_args()


def load_config(path: Path) -> FixedSetsConfig:
    return from_json_object(FixedSetsConfig, tomllib.loads(path.read_text(encoding="utf-8")))


def composition(statements: list[HeldOutStatement]) -> str:
    counts = Counter(str(statement.stratum) for statement in statements)
    sources = Counter(statement.statement.source for statement in statements)
    strata = {stratum: counts[stratum] for stratum in sorted(counts, key=stratum_order)}
    return f"{len(statements)} statements, strata {strata}, sources {dict(sorted(sources.items()))}"


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


@dataclass(frozen=True)
class CharacterSelectionRecord:
    training_data: tuple[str, ...]
    training_root_states: int
    held_out_states: int
    near_duplicate_threshold: float
    strata: tuple[StratumDraw, ...]


def load_character_strata(path: Path) -> CharacterStrataConfig:
    config = from_json_object(CharacterStrataConfig, tomllib.loads(path.read_text(encoding="utf-8")))
    validate_character_strata(config)
    return config


def select_characters(config: CharacterStrataConfig, training_data: list[Path]) -> None:
    output = DATA_DIRECTORY / config.output
    if output.exists():
        raise SystemExit(f"{output} exists: the held-out sets are fixed once chosen.")
    verified, _ = read_verified(DATA_DIRECTORY / config.curriculum.verified)
    found = character_candidates(verified, config)
    fixed = {statement.name for path in config.excluded_sets for statement in read_fixed_set(DATA_DIRECTORY / path)}
    states_file = config.held_out_states_file
    states = read_records(RUNS_DIRECTORY / states_file, ReasoningState) if states_file else []
    roots = training_root_states(training_data)
    exclusions = Exclusions(
        fixed_sets=frozenset(fixed),
        held_out_states=same_statements(found, [state.step.formal_statement for state in states]),
        near_training_duplicates=near_training_duplicates(found, roots, config.near_duplicate_threshold),
    )
    selection = select_by_characters(found, config, exclusions)
    write_fixed_set(output, selection.statements)
    record = CharacterSelectionRecord(
        tuple(str(path) for path in training_data),
        len(roots),
        len(states),
        config.near_duplicate_threshold,
        selection.strata,
    )
    output.with_name(output.name.removesuffix(".jsonl") + ".selection.json").write_text(
        to_json(record), encoding="utf-8"
    )
    rows = [
        [
            draw.stratum,
            draw.candidates,
            draw.in_fixed_sets,
            draw.held_out_states,
            draw.near_training_duplicates,
            draw.chosen,
        ]
        for draw in selection.strata
    ]
    headers = ["characters", "usable", "in fixed sets", "held-out states", "near training data", "chosen"]
    print(markdown_table(headers, rows))
    print(f"{len(roots):,} distinct root states in the training data, {len(states)} held-out states")
    print(f"probe v2: {composition(list(selection.statements))} -> {output}")


def labelled_tree(record: TreeRecord) -> LabelledTree:
    labels = label_graph(record)
    targets = value_targets(record, labels, recorded_estimates(record, RemainingStepsReadout()), ValueTargetConfig())
    return LabelledTree(record, labels, targets)


async def gate_benchmark(config: FixedSetsConfig, arguments: argparse.Namespace) -> None:
    search_config = load_run_config(arguments.search_config)
    if search_config.value.model:
        raise SystemExit("The gate's trees come from a search without a value model (no circular labels).")
    problems = [
        EvaluationProblem(statement.problem, statement.stratum)
        for statement in read_fixed_set(DATA_DIRECTORY / config.gate_set)
    ]
    problems = first_problems_by_stratum(problems, arguments.problems) if arguments.problems else problems
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
    match arguments.command:
        case "select":
            select(load_config(arguments.config))
        case "select-overfit":
            select_overfit(load_config(arguments.config))
        case "select-by-characters":
            select_characters(load_character_strata(arguments.config), arguments.training_data)
        case "gate-benchmark":
            asyncio.run(gate_benchmark(load_config(arguments.config), arguments))
        case "rename":
            asyncio.run(rename(load_config(arguments.config), arguments))


if __name__ == "__main__":
    main()
