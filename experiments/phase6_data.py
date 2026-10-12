"""Build one expert-iteration round's training data from its search trees: policy SFT, DPO pairs and value v1.

    python experiments/phase6_data.py --config experiments/configs/expert_iteration/round_0.toml
    python experiments/phase6_data.py --config ... --runs phase3_astar_v0 phase2_sft_v1_search --statistics-only \
        --summary-run phase6_data_dry_run

Reads the trees of the round config's data.tree_runs (or --runs) under $LEAN_SEARCH_RUNS. Statements held out by hash
(data.held_out_fraction) feed only validation sets.

- Policy SFT: one shortest found proof per statement, its executed steps (goals before, step) in the SFT format,
  de-duplicated, plus traced human steps as data.policy.replay_fraction of the tokens; validation is the traced
  validation split as in SFT. Written to policy_sft/{train,validation,validation_expert_iteration}.jsonl, read by
  experiments/phase2_sft.py through data = "../expert_iteration/round_<index>/policy_sft".
- DPO: at the policy steps of every found proof, the step against failed or dead sibling candidates
  (dpo/{train,validation}.jsonl, for experiments/phase6_dpo.py).
- Value v1: every tree label except the lossless open frontier, exact labels of the pre-filter's automation proofs,
  and the replay data set (value/{train,validation}.jsonl, read by experiments/phase3_value.py through
  data = "../expert_iteration/round_<index>/value").

Data goes to $LEAN_SEARCH_DATA/expert_iteration/round_<index>/; statistics to
$LEAN_SEARCH_RUNS/<summary run>/summary/{summary.json,README.md} (default phase6_round_<index>_data).
--statistics-only writes no data: for trees that must never become training data, such as miniF2F's.
"""

import argparse
import dataclasses
import datetime
import json
import math
import os
import subprocess
import time
from collections import Counter
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import transformers

from lean_search.expert_iteration.config import RoundConfig, RoundDataConfig, load_round_config
from lean_search.expert_iteration.mixing import is_held_out, replay_amount
from lean_search.expert_iteration.pool import problem_source
from lean_search.expert_iteration.preferences import NodePairs, node_pairs
from lean_search.expert_iteration.proofs import (
    EXPERT_ITERATION_SOURCE,
    FoundProof,
    found_proof,
    policy_sft_examples,
    proof_length_histogram,
    shortest_proofs,
)
from lean_search.expert_iteration.value_data import (
    carries_no_loss,
    prefilter_tree_examples,
    value_mixture,
)
from lean_search.search import StepSource, TreeRecord, read_tree
from lean_search.search.summary import markdown_table
from lean_search.training.dpo_data import PreferencePair, deduplicate_pairs, fits, tokenize_pair, write_pairs
from lean_search.training.sft_data import (
    LengthStatistics,
    SourceStatistics,
    SourceStream,
    TokenizedExample,
    deduplicate,
    length_capped_tokenizer,
    length_statistics,
    ordering_key,
    read_traced_examples,
    select_mixture,
    select_validation,
    snapshot_step_files,
    source_statistics,
)
from lean_search.training.sft_data import write_examples as write_sft_examples
from lean_search.value.bins import STEP_BIN_COUNT
from lean_search.value.labels import (
    LabelCounts,
    LabelKind,
    ValueExample,
    label_counts,
    merge_duplicates,
    read_examples,
    tree_examples,
)
from lean_search.value.labels import write_examples as write_value_examples

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
PROOF_LENGTH_BUCKETS = 8
DEPTH_BUCKETS = 17


@dataclass(frozen=True)
class RunTrees:
    run: str
    trees: int
    solved: int
    held_out_trees: int
    held_out_solved: int


@dataclass(frozen=True)
class SourceTrees:
    source: str
    trees: int
    solved: int


@dataclass(frozen=True)
class PolicyDataSummary:
    found_proofs: int
    statements: int
    held_out_statements: int
    proof_lengths: tuple[int, ...]
    # Proofs whose root reaches a proof in fewer edges through duplicate edges than the path the search took.
    shorter_through_duplicates: int
    proof_steps: int
    automation_steps: int
    policy_steps_only: bool
    examples: int
    duplicates: int
    over_length: int
    new_examples: int
    new_tokens: int
    prompt_tokens: LengthStatistics
    completion_tokens: LengthStatistics
    replay_fraction: float
    replay_token_budget: int
    replay: tuple[SourceStatistics, ...]
    replay_examples: int
    replay_tokens: int
    validation_examples: int
    held_out_examples: int


@dataclass(frozen=True)
class RejectionCount:
    rejection: str
    pairs: int


@dataclass(frozen=True)
class PreferenceDataSummary:
    max_pairs_per_node: int
    nodes: int
    nodes_with_pairs: int
    rejectable: int
    rejected_more_likely: int
    pairs_before_deduplication: int
    pairs: int
    over_length: int
    held_out_pairs: int
    by_rejection: tuple[RejectionCount, ...]
    # Nodes with 0, 1, ..., max_pairs_per_node pairs.
    pairs_per_node: tuple[int, ...]
    chosen_completion_tokens: LengthStatistics
    rejected_completion_tokens: LengthStatistics


@dataclass(frozen=True)
class DepthHistograms:
    exact: tuple[int, ...]
    at_least: tuple[int, ...]
    dead: tuple[int, ...]


@dataclass(frozen=True)
class ValueDataSummary:
    all_labels: LabelCounts
    dropped_open: int
    tree_labels: LabelCounts
    tree_depths: DepthHistograms
    tree_states: int
    censored_dropped: int
    prefilter_trees: int
    prefilter_exact: int
    prefilter_states: int
    replay_data: str
    replay_available: int
    replay_states: int
    train: LabelCounts
    train_by_source: dict[str, int]
    validation_tree_states: int
    validation_replay_states: int
    validation: LabelCounts


@dataclass(frozen=True)
class RoundDataSummary:
    round_index: int
    built: str
    git_revision: str
    statistics_only: bool
    runs: tuple[RunTrees, ...]
    sources: tuple[SourceTrees, ...]
    config: RoundDataConfig
    policy: PolicyDataSummary
    preferences: PreferenceDataSummary
    value: ValueDataSummary
    output_directory: str
    seconds: float


@dataclass
class Harvest:
    """Everything the data sets need from the trees, gathered in one pass so each tree is read once."""

    runs: list[RunTrees] = dataclasses.field(default_factory=list)
    trees_by_source: Counter[str] = dataclasses.field(default_factory=Counter)
    solved_by_source: Counter[str] = dataclasses.field(default_factory=Counter)
    proofs: list[FoundProof] = dataclasses.field(default_factory=list)
    held_out_proofs: list[FoundProof] = dataclasses.field(default_factory=list)
    shorter_through_duplicates: int = 0
    node_pairs: list[NodePairs] = dataclasses.field(default_factory=list)
    held_out_pairs: list[PreferencePair] = dataclasses.field(default_factory=list)
    all_labels: list[ValueExample] = dataclasses.field(default_factory=list)
    held_out_labels: list[ValueExample] = dataclasses.field(default_factory=list)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runs", nargs="+", help="overrides data.tree_runs")
    parser.add_argument("--statistics-only", action="store_true", help="write no data sets, only the statistics")
    parser.add_argument("--summary-run", help="run directory for the statistics (default phase6_round_<index>_data)")
    return parser.parse_args()


def git_revision() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_DIRECTORY, capture_output=True, text=True, check=True
    ).stdout.strip()


def log(message: str) -> None:
    print(message, flush=True)


def tree_records(run: str) -> Iterator[TreeRecord]:
    for path in sorted((RUNS_DIRECTORY / run / "trees").glob("*.json.gz")):
        yield read_tree(path)


def harvest(runs: Sequence[str], config: RoundDataConfig) -> Harvest:
    gathered = Harvest()
    for run in runs:
        trees = solved = held_out_trees = held_out_solved = 0
        for record in tree_records(run):
            held_out = is_held_out(record.problem_name, config.seed, config.held_out_fraction)
            source = problem_source(record.problem_name)
            labels = tree_examples(record, source, config.value.labels)
            proof = found_proof(run, record)
            trees += 1
            solved += proof is not None
            held_out_trees += held_out
            held_out_solved += held_out and proof is not None
            gathered.trees_by_source[source] += 1
            gathered.solved_by_source[source] += proof is not None
            if held_out:
                gathered.held_out_labels.extend(label for label in labels if not carries_no_loss(label))
            else:
                gathered.all_labels.extend(labels)
            if proof is None:
                continue
            root_label = labels[0]
            gathered.shorter_through_duplicates += root_label.kind == LabelKind.EXACT and root_label.steps < len(
                proof.steps
            )
            pairs = node_pairs(record, proof, config.preferences)
            if held_out:
                gathered.held_out_proofs.append(proof)
                gathered.held_out_pairs.extend(pair for node in pairs for pair in node.pairs)
            else:
                gathered.proofs.append(proof)
                gathered.node_pairs.extend(pairs)
        gathered.runs.append(RunTrees(run, trees, solved, held_out_trees, held_out_solved))
        log(f"{run}: {trees:,} trees, {solved:,} solved ({held_out_trees:,} held out)")
    return gathered


def tokenized_all(stream: SourceStream) -> list[TokenizedExample]:
    stream.extend_to(math.inf)
    return stream.accepted


def build_policy_data(
    gathered: Harvest,
    config: RoundDataConfig,
    tokenizer: transformers.PreTrainedTokenizerBase,
    output_directory: Path | None,
) -> PolicyDataSummary:
    policy = config.policy
    tokenize = length_capped_tokenizer(tokenizer, policy.max_prompt_tokens, policy.max_completion_tokens)
    proofs = shortest_proofs(gathered.proofs)
    examples = policy_sft_examples(proofs, policy.policy_steps_only)
    new_pool = deduplicate({EXPERT_ITERATION_SOURCE: examples}, config.seed)
    new_stream = SourceStream(new_pool.examples_by_source[EXPERT_ITERATION_SOURCE], tokenize)
    new_examples = tokenized_all(new_stream)
    weights = {source.name: source.weight for source in policy.replay_sources}
    traced = read_traced_examples(snapshot_step_files(DATA_DIRECTORY / "traced"), weights)
    replay_pool = deduplicate(traced.train, config.seed, excluded_keys=new_pool.keys)
    streams = {source: SourceStream(replay_pool.examples_by_source[source], tokenize) for source in weights}
    budget = replay_amount(new_stream.tokens, policy.replay_fraction)
    if budget:
        select_mixture(streams, weights, budget)
    replay = [example for stream in streams.values() for example in stream.accepted]
    validation_pool = deduplicate(traced.validation, config.seed, excluded_keys=new_pool.keys | replay_pool.keys)
    validation = select_validation(
        validation_pool.examples_by_source, policy.validation_examples, policy.validation_seed, tokenize
    )
    held_out = policy_sft_examples(shortest_proofs(gathered.held_out_proofs), policy.policy_steps_only)
    if output_directory is not None:
        train = sorted([*new_examples, *replay], key=lambda example: ordering_key(example.example, config.seed))
        directory = output_directory / "policy_sft"
        write_sft_examples(directory / "train.jsonl", (example.example for example in train))
        write_sft_examples(directory / "validation.jsonl", (example.example for example in validation))
        write_sft_examples(directory / "validation_expert_iteration.jsonl", held_out)
    proof_steps = [step for proof in proofs for step in proof.steps]
    return PolicyDataSummary(
        found_proofs=len(gathered.proofs),
        statements=len(proofs),
        held_out_statements=len({proof.problem_name for proof in gathered.held_out_proofs}),
        proof_lengths=proof_length_histogram(proofs, PROOF_LENGTH_BUCKETS),
        shorter_through_duplicates=gathered.shorter_through_duplicates,
        proof_steps=len(proof_steps),
        automation_steps=sum(step.source == StepSource.AUTOMATION for step in proof_steps),
        policy_steps_only=policy.policy_steps_only,
        examples=len(examples),
        duplicates=new_pool.duplicates_by_source[EXPERT_ITERATION_SOURCE],
        over_length=new_stream.over_length,
        new_examples=len(new_examples),
        new_tokens=new_stream.tokens,
        prompt_tokens=length_statistics([example.prompt_token_count for example in new_examples]),
        completion_tokens=length_statistics([example.completion_token_count for example in new_examples]),
        replay_fraction=policy.replay_fraction,
        replay_token_budget=budget,
        replay=tuple(source_statistics(source, traced, replay_pool, streams[source]) for source in weights),
        replay_examples=len(replay),
        replay_tokens=sum(stream.tokens for stream in streams.values()),
        validation_examples=len(validation),
        held_out_examples=len(held_out),
    )


def build_preference_data(
    gathered: Harvest,
    config: RoundDataConfig,
    tokenizer: transformers.PreTrainedTokenizerBase,
    output_directory: Path | None,
) -> PreferenceDataSummary:
    policy = config.policy
    candidates = [pair for node in gathered.node_pairs for pair in node.pairs]
    unique = deduplicate_pairs(candidates)
    tokenized = [tokenize_pair(tokenizer, pair) for pair in unique]
    kept = [pair for pair in tokenized if fits(pair, policy.max_prompt_tokens, policy.max_completion_tokens)]
    held_out = deduplicate_pairs(gathered.held_out_pairs)
    if output_directory is not None:
        write_pairs(output_directory / "dpo" / "train.jsonl", (pair.pair for pair in kept))
        write_pairs(output_directory / "dpo" / "validation.jsonl", held_out)
    cap = config.preferences.max_pairs_per_node
    pairs_per_node = Counter(len(node.pairs) for node in gathered.node_pairs)
    return PreferenceDataSummary(
        max_pairs_per_node=cap,
        nodes=len(gathered.node_pairs),
        nodes_with_pairs=sum(bool(node.pairs) for node in gathered.node_pairs),
        rejectable=sum(node.rejectable for node in gathered.node_pairs),
        rejected_more_likely=sum(node.rejected_more_likely for node in gathered.node_pairs),
        pairs_before_deduplication=len(candidates),
        pairs=len(kept),
        over_length=len(tokenized) - len(kept),
        held_out_pairs=len(held_out),
        by_rejection=tuple(
            RejectionCount(rejection, count)
            for rejection, count in Counter(pair.pair.rejection for pair in kept).most_common()
        ),
        pairs_per_node=tuple(pairs_per_node[count] for count in range(cap + 1)),
        chosen_completion_tokens=length_statistics([pair.chosen.completion_token_count for pair in kept]),
        rejected_completion_tokens=length_statistics([pair.rejected.completion_token_count for pair in kept]),
    )


def depth_histograms(examples: Sequence[ValueExample]) -> DepthHistograms:
    def histogram(kind: LabelKind) -> tuple[int, ...]:
        counts = [0] * DEPTH_BUCKETS
        for example in examples:
            if example.kind == kind:
                counts[min(example.depth, DEPTH_BUCKETS - 1)] += 1
        return tuple(counts)

    return DepthHistograms(histogram(LabelKind.EXACT), histogram(LabelKind.AT_LEAST), histogram(LabelKind.DEAD))


def build_value_data(gathered: Harvest, config: RoundDataConfig, output_directory: Path | None) -> ValueDataSummary:
    value = config.value
    tree_labels = [label for label in gathered.all_labels if not carries_no_loss(label)]
    prefilter_trees = 0
    prefilter: list[ValueExample] = []
    for run in value.prefilter_runs:
        for record in tree_records(run):
            if is_held_out(record.problem_name, config.seed, config.held_out_fraction):
                continue
            prefilter_trees += 1
            prefilter.extend(prefilter_tree_examples(record, value.labels))
    replay_directory = DATA_DIRECTORY / "value" / value.replay_data
    replay = list(read_examples(replay_directory / "train.jsonl"))
    mixture = value_mixture(tree_labels, prefilter, replay, value, config.seed)
    train_keys = {example.goal_key for example in mixture.train}
    validation_tree = [
        example for example in merge_duplicates(gathered.held_out_labels) if example.goal_key not in train_keys
    ]
    validation_replay = [
        example
        for example in read_examples(replay_directory / "validation.jsonl")
        if example.goal_key not in train_keys
    ]
    validation = merge_duplicates([*validation_tree, *validation_replay])
    if output_directory is not None:
        write_value_examples(output_directory / "value" / "train.jsonl", mixture.train)
        write_value_examples(output_directory / "value" / "validation.jsonl", validation)
    return ValueDataSummary(
        all_labels=label_counts(gathered.all_labels),
        dropped_open=len(gathered.all_labels) - len(tree_labels),
        tree_labels=label_counts(tree_labels),
        tree_depths=depth_histograms(tree_labels),
        tree_states=mixture.tree_states,
        censored_dropped=mixture.censored_dropped,
        prefilter_trees=prefilter_trees,
        prefilter_exact=len(prefilter),
        prefilter_states=mixture.prefilter_states,
        replay_data=value.replay_data,
        replay_available=len(replay),
        replay_states=mixture.replay_states,
        train=label_counts(mixture.train),
        train_by_source=dict(Counter(example.source for example in mixture.train).most_common()),
        validation_tree_states=len(validation_tree),
        validation_replay_states=len(validation_replay),
        validation=label_counts(validation),
    )


def count_cells(counts: Sequence[int]) -> list[str]:
    return [f"{count:,}" for count in counts]


def label_row(name: str, counts: LabelCounts) -> list[str]:
    return [name, f"{counts.examples:,}", f"{counts.exact:,}", f"{counts.at_least:,}", f"{counts.dead:,}"]


def render_markdown(summary: RoundDataSummary) -> str:
    policy = summary.policy
    preferences = summary.preferences
    value = summary.value
    config = summary.config
    run_rows = [
        [run.run, f"{run.trees:,}", f"{run.solved:,}", f"{run.held_out_trees:,}", f"{run.held_out_solved:,}"]
        for run in summary.runs
    ]
    source_rows = [[source.source, f"{source.trees:,}", f"{source.solved:,}"] for source in summary.sources]
    length_names = [str(steps) for steps in range(1, PROOF_LENGTH_BUCKETS)] + [f"{PROOF_LENGTH_BUCKETS}+"]
    replay_rows = [
        [source.source, f"{source.selected:,}", f"{source.total_tokens:,}", f"{source.over_length:,}"]
        for source in policy.replay
        if source.selected
    ]
    bin_names = [str(steps) for steps in range(1, STEP_BIN_COUNT)] + [f"{STEP_BIN_COUNT}+"]
    depth_names = [str(depth) for depth in range(DEPTH_BUCKETS - 1)] + [f"{DEPTH_BUCKETS - 1}+"]
    mode = "statistics only, no data written" if summary.statistics_only else f"data in `{summary.output_directory}`"
    sections = [
        f"# Expert-iteration round {summary.round_index}: training data",
        f"Built {summary.built} (git {summary.git_revision[:10]}, {summary.seconds:.0f} s; {mode}). Statements "
        f"held out by hash ({config.held_out_fraction:.0%}, seed `{config.seed}`) feed only validation sets.",
        markdown_table(["Run", "Trees", "Solved", "Held-out trees", "Held-out solved"], run_rows),
        markdown_table(["Source", "Trees", "Solved"], source_rows),
        "## Policy SFT",
        f"{policy.found_proofs:,} found proofs, one shortest per statement: {policy.statements:,} statements "
        f"({policy.held_out_statements:,} more held out). {policy.shorter_through_duplicates:,} proofs have a shorter "
        f"path through duplicate edges (not used: only the verified path's steps are certain to compose). "
        f"{policy.proof_steps:,} proof steps, {policy.automation_steps:,} by automation"
        f"{' (left out: the sweep tries them anyway)' if policy.policy_steps_only else ''}; {policy.examples:,} "
        f"examples, {policy.duplicates:,} duplicates, {policy.over_length:,} over the length caps: "
        f"**{policy.new_examples:,} new examples, {policy.new_tokens:,} tokens**. Replay of traced human steps: "
        f"{policy.replay_fraction:.0%} of the mixture, {policy.replay_token_budget:,} tokens budgeted, "
        f"**{policy.replay_examples:,} examples, {policy.replay_tokens:,} tokens**. Validation: "
        f"{policy.validation_examples:,} traced validation steps; {policy.held_out_examples:,} held-out proof steps "
        "in `validation_expert_iteration.jsonl`.",
        markdown_table(["Proof steps", *length_names], [["proofs", *count_cells(policy.proof_lengths)]]),
        markdown_table(
            ["New examples", "Mean", "p50", "p90", "p99", "Max"],
            [
                [name, f"{values.mean:.0f}", values.p50, values.p90, values.p99, values.maximum]
                for name, values in (
                    ("prompt tokens", policy.prompt_tokens),
                    ("completion tokens", policy.completion_tokens),
                )
            ],
        ),
        markdown_table(["Replay source", "Examples", "Tokens", "Over length"], replay_rows),
        "## DPO pairs",
        f"At each policy step of a found proof (chosen = the executed on-path step), rejected = sibling policy "
        f"candidates that failed in Lean (error or timeout, never an infrastructure failure) or led into a dead "
        f"subtree, the policy's most likely first, at most {preferences.max_pairs_per_node} per node. "
        f"{preferences.nodes:,} nodes, {preferences.nodes_with_pairs:,} with pairs; {preferences.rejectable:,} "
        f"rejectable siblings before the cap; {preferences.pairs_before_deduplication:,} pairs, "
        f"{preferences.over_length:,} over the length caps: **{preferences.pairs:,} training pairs**, "
        f"{preferences.held_out_pairs:,} held-out validation pairs. In {preferences.rejected_more_likely:,} kept "
        "pairs the policy gave the rejected step the higher log-probability.",
        markdown_table(
            ["Rejection", "Pairs"], [[entry.rejection, f"{entry.pairs:,}"] for entry in preferences.by_rejection]
        ),
        markdown_table(
            ["Pairs per node", *(str(count) for count in range(preferences.max_pairs_per_node + 1))],
            [["nodes", *count_cells(preferences.pairs_per_node)]],
        ),
        f"Completion tokens: chosen mean {preferences.chosen_completion_tokens.mean:.0f} (p90 "
        f"{preferences.chosen_completion_tokens.p90}), rejected mean {preferences.rejected_completion_tokens.mean:.0f} "
        f"(p90 {preferences.rejected_completion_tokens.p90}).",
        "## Value v1",
        f"Tree labels (`value.labels`): exact remaining steps for states that reach the proof, at least 1 + the "
        f"distance to the frontier for censored states, dead for fully expanded states without either. "
        f"{value.dropped_open:,} open-frontier labels (at least 1) carry no loss and are dropped; "
        f"{value.tree_states:,} distinct tree states kept ({value.censored_dropped:,} censored ones dropped by the "
        f"cap of {summary.config.value.max_tree_states:,}; 0 = none). Pre-filter proofs: "
        f"{value.prefilter_exact:,} exact labels from {value.prefilter_trees:,} automation-only trees, "
        f"{value.prefilter_states:,} sampled. Replay of `{value.replay_data}`: {value.replay_states:,} of "
        f"{value.replay_available:,} states.",
        markdown_table(
            ["Labels", "Examples", "Exact", "At least", "Dead"],
            [
                label_row("all tree labels", value.all_labels),
                label_row("kept tree labels", value.tree_labels),
                label_row("train (merged with replay)", value.train),
                label_row("validation", value.validation),
            ],
        ),
        markdown_table(
            ["Kept tree labels", *bin_names],
            [
                ["exact", *count_cells(value.tree_labels.exact_bins)],
                ["at least", *count_cells(value.tree_labels.at_least_bins)],
            ],
        ),
        markdown_table(
            ["Depth", *depth_names],
            [
                ["exact", *count_cells(value.tree_depths.exact)],
                ["at least", *count_cells(value.tree_depths.at_least)],
                ["dead", *count_cells(value.tree_depths.dead)],
            ],
        ),
        f"Validation: {value.validation_tree_states:,} held-out tree states and {value.validation_replay_states:,} "
        f"replay validation states, none also in train.",
    ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    started = time.perf_counter()
    round_config: RoundConfig = load_round_config(arguments.config)
    config = round_config.data
    runs = tuple(arguments.runs or config.tree_runs)
    output_directory = (
        None if arguments.statistics_only else DATA_DIRECTORY / "expert_iteration" / round_config.data_name
    )
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.policy.reference_tokenizer)
    gathered = harvest(runs, config)
    policy = build_policy_data(gathered, config, tokenizer, output_directory)
    log(f"Policy SFT: {policy.new_examples:,} new and {policy.replay_examples:,} replay examples")
    preferences = build_preference_data(gathered, config, tokenizer, output_directory)
    log(f"DPO: {preferences.pairs:,} pairs")
    value = build_value_data(gathered, config, output_directory)
    log(f"Value: {value.train.examples:,} train and {value.validation.examples:,} validation states")
    summary = RoundDataSummary(
        round_index=round_config.index,
        built=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        git_revision=git_revision(),
        statistics_only=arguments.statistics_only,
        runs=tuple(gathered.runs),
        sources=tuple(
            SourceTrees(source, count, gathered.solved_by_source[source])
            for source, count in sorted(gathered.trees_by_source.items())
        ),
        config=config,
        policy=policy,
        preferences=preferences,
        value=value,
        output_directory=str(output_directory) if output_directory else "",
        seconds=time.perf_counter() - started,
    )
    summary_json = json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False)
    markdown = render_markdown(summary)
    if output_directory is not None:
        (output_directory / "summary.json").write_text(summary_json, encoding="utf-8")
    summary_directory = RUNS_DIRECTORY / (arguments.summary_run or f"{round_config.run_name}_data") / "summary"
    summary_directory.mkdir(parents=True, exist_ok=True)
    (summary_directory / "summary.json").write_text(summary_json, encoding="utf-8")
    (summary_directory / "README.md").write_text(markdown, encoding="utf-8")
    log(markdown)


if __name__ == "__main__":
    main()
