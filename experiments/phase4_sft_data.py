"""Lemma-aware SFT data: traced competition steps with retrieved, annotated lemma lists of length 0-32.

    python experiments/phase4_sft_data.py --config experiments/configs/retrieval/phase4_sft_data.toml \
        --name lemmas_v1 --stage {select,retrieve,annotate,finish} [--device cuda:0] [--processes 8]
    python experiments/phase4_sft_data.py --config ... --name lemmas_v1_15m --stage subsample \
        --from-name lemmas_v1 --token-budget 15000000

select (CPU, minutes): whole proofs per source in a fixed pseudo-random order up to the estimated token budget;
retrieve (GPU or CPU): top-N candidates of the deployed index for every step with a non-empty list;
annotate (Lean, resumable): replay each proof on one REPL, inject premises the step names with some probability,
check the candidates as the search does and keep the best k as prompt lines;
finish (CPU): tokenize, drop over-length examples, write $LEAN_SEARCH_DATA/sft/<name>/{train,validation}.jsonl and
$LEAN_SEARCH_RUNS/phase4_sft_data/summary/<name>.{json,md};
subsample (CPU): a smaller training set from a finished one, each list length keeping its token share.
"""

import argparse
import asyncio
import collections
import dataclasses
import json
import os
import statistics
import time
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import transformers

from lean_search.corpora.records import DataSplit, TracedStep, read_traced_steps, write_jsonl
from lean_search.corpora.tracing import state_before
from lean_search.lean import LeanRepl, LeanReplConfig, LeanReplPool, ProofState, find_forbidden_tokens
from lean_search.policy.prompts import normalize_tactic_block
from lean_search.retrieval.annotation import annotate, lemma_line, order_lemmas
from lean_search.retrieval.config import ApplicabilityConfig, RetrievalConfig
from lean_search.retrieval.premises import (
    MINIF2F_OPEN_NAMESPACES,
    RetrievedPremise,
    read_signatures,
    serialize_goals,
    step_premises,
)
from lean_search.retrieval.provider import load_goal_retriever
from lean_search.retrieval.sft_data import (
    LemmaDataConfig,
    LemmaSftExample,
    ProofUnit,
    inject_step_premises,
    lemma_count_for,
    read_lemma_examples,
    select_proofs,
    stable_fraction,
    step_key,
    subsample_indices,
    tokenize_lemma_example,
    write_lemma_examples,
)
from lean_search.search.records import from_json_object
from lean_search.search.summary import markdown_table
from lean_search.training.sft_data import duplicate_key, length_statistics, sft_example

DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RETRIEVAL_DIRECTORY = DATA_DIRECTORY / "retrieval"
TRACED_DIRECTORY = DATA_DIRECTORY / "traced"
RUN_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase4_sft_data"
# Zero-shot prompt and completion scaffolding around the goals and the step (Qwen3.5-2B tokens).
SCAFFOLD_TOKENS = 105
SPLITS = ("train", "validation")


class Stage(StrEnum):
    SELECT = "select"
    RETRIEVE = "retrieve"
    ANNOTATE = "annotate"
    FINISH = "finish"
    SUBSAMPLE = "subsample"


@dataclass(frozen=True)
class StepCandidates:
    key: str
    premises: tuple[RetrievedPremise, ...]


@dataclass(frozen=True)
class CountRow:
    group: str
    examples: int
    naming_premises: int
    step_premise_shown: int
    injected: int
    shown_closing_mean: float


@dataclass(frozen=True)
class SplitSummary:
    split: str
    annotated: int
    over_length: int
    examples: int
    prompt_tokens_mean: float
    prompt_tokens_p90: int
    prompt_tokens_max: int
    completion_tokens_mean: float
    total_tokens: int
    by_lemma_count: tuple[CountRow, ...]
    by_source: tuple[CountRow, ...]


@dataclass(frozen=True)
class DataSummary:
    name: str
    config: LemmaDataConfig
    applicability: ApplicabilityConfig
    selected_steps: dict[str, int]
    replay_failures: dict[str, int]
    splits: tuple[SplitSummary, ...]
    subsample_of: str = ""
    subsample_token_budget: int = 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--stage", type=Stage, choices=list(Stage), required=True)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--processes", type=int, default=8)
    parser.add_argument("--from-name", help="subsample: the finished data set to subsample")
    parser.add_argument("--token-budget", type=int, help="subsample: training tokens to keep")
    return parser.parse_args()


def work_directory(name: str) -> Path:
    return RETRIEVAL_DIRECTORY / "sft" / name


def proof_order(proof_identifier: str, seed: str) -> float:
    return stable_fraction(seed, "proof order", proof_identifier)


def usable_steps(config: LemmaDataConfig, split: DataSplit) -> dict[str, list[TracedStep]]:
    """Steps by proof: configured sources, no forbidden tokens, each (goals, step) pair once in proof order."""
    by_proof: dict[str, list[TracedStep]] = collections.defaultdict(list)
    for step in read_traced_steps(TRACED_DIRECTORY / f"steps_{split}.jsonl"):
        if step.source in config.sources and not find_forbidden_tokens(normalize_tactic_block(step.step)):
            by_proof[step.proof_identifier].append(step)
    seen: set[bytes] = set()
    kept: dict[str, list[TracedStep]] = {}
    for proof_identifier in sorted(by_proof, key=lambda identifier: proof_order(identifier, config.seed)):
        steps = []
        for step in sorted(by_proof[proof_identifier], key=lambda step: step.step_index):
            key = duplicate_key(
                sft_example(step.source, proof_identifier, step.step_index, step.goals_before, step.step)
            )
            if key not in seen:
                seen.add(key)
                steps.append(step)
        if steps:
            kept[proof_identifier] = steps
    return kept


def proof_units(
    steps_by_proof: dict[str, list[TracedStep]],
    config: LemmaDataConfig,
    tokenizer: transformers.PreTrainedTokenizerBase,
) -> list[ProofUnit]:
    steps = [step for proof in steps_by_proof.values() for step in proof]
    texts = [serialize_goals(step.goals_before) + "\n" + step.step for step in steps]
    lengths = [len(ids) for ids in tokenizer(texts, add_special_tokens=False)["input_ids"]]
    estimate = {
        step_key(step): length
        + SCAFFOLD_TOKENS
        + lemma_count_for(step_key(step), config.lemma_counts, config.seed) * config.estimated_tokens_per_lemma
        for step, length in zip(steps, lengths, strict=True)
    }
    units = []
    for identifier, proof in steps_by_proof.items():
        # Steps too long for the prompt cap would be dropped later; they must not take budget.
        kept = tuple(step for step in proof if estimate[step_key(step)] <= config.max_prompt_tokens)
        if kept:
            units.append(ProofUnit(kept[0].source, identifier, kept, sum(estimate[step_key(step)] for step in kept)))
    return units


def select(config: LemmaDataConfig, directory: Path) -> None:
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.reference_tokenizer)
    train_units = proof_units(usable_steps(config, DataSplit.TRAIN), config, tokenizer)
    by_source: dict[str, list[ProofUnit]] = {source: [] for source in config.sources}
    for unit in train_units:
        by_source[unit.source].append(unit)
    selected = select_proofs(by_source, config.token_budget)
    train = [step for units in selected.values() for unit in units for step in unit.steps]
    validation: list[TracedStep] = []
    for steps in usable_steps(config, DataSplit.VALIDATION).values():
        if len(validation) >= config.validation_examples:
            break
        validation += steps
    for split, steps in (("train", train), ("validation", validation)):
        write_jsonl(directory / f"selection_{split}.jsonl", steps)
        print(f"{split}: {len(steps):,} steps from {len({step.proof_identifier for step in steps}):,} proofs")


def read_selection(directory: Path, split: str) -> list[TracedStep]:
    return list(read_traced_steps(directory / f"selection_{split}.jsonl"))


def retrieve(config: LemmaDataConfig, directory: Path, device: str) -> None:
    retriever = load_goal_retriever(
        RetrievalConfig(
            lemma_count=1, candidate_count=config.candidate_count, retriever=config.retriever, device=device
        )
    )
    for split in SPLITS:
        steps = [
            step
            for step in read_selection(directory, split)
            if lemma_count_for(step_key(step), config.lemma_counts, config.seed) > 0
        ]
        started = time.perf_counter()
        with (directory / f"candidates_{split}.jsonl").open("w", encoding="utf-8") as handle:
            for start in range(0, len(steps), 1024):
                chunk = steps[start : start + 1024]
                retrieved = retriever.retrieve([step.goals_before for step in chunk], config.candidate_count)
                for step, premises in zip(chunk, retrieved, strict=True):
                    record = StepCandidates(step_key(step), premises)
                    handle.write(json.dumps(dataclasses.asdict(record), ensure_ascii=False) + "\n")
        print(f"{split}: candidates for {len(steps):,} steps in {time.perf_counter() - started:.0f} s", flush=True)


def read_candidates(directory: Path, split: str) -> dict[str, tuple[RetrievedPremise, ...]]:
    candidates = {}
    with (directory / f"candidates_{split}.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            fields = json.loads(line)
            candidates[fields["key"]] = tuple(RetrievedPremise(**premise) for premise in fields["premises"])
    return candidates


async def lemma_example(
    repl: LeanRepl,
    step: TracedStep,
    candidates: tuple[RetrievedPremise, ...],
    signatures: dict[str, str],
    config: LemmaDataConfig,
    applicability: ApplicabilityConfig,
) -> LemmaSftExample | None:
    key = step_key(step)
    lemma_count = lemma_count_for(key, config.lemma_counts, config.seed)
    named = step_premises(step.step, signatures, MINIF2F_OPEN_NAMESPACES)
    block = normalize_tactic_block(step.step)
    if lemma_count == 0:
        return LemmaSftExample(
            step.source, step.proof_identifier, step.step_index, step.goals_before, (), block, 0, named
        )
    # A no-op step rebuilds the traced state here; a mismatch means the step cannot be annotated faithfully.
    match (await repl.apply_tactic(state_before(step), "skip")).outcome:
        case ProofState() as state:
            pass
        case _:
            return None
    retrieved_names = {premise.full_name for premise in candidates}
    missing = [RetrievedPremise(name, signatures[name], 0.0) for name in named if name not in retrieved_names]
    injected = 0
    if missing and stable_fraction(config.seed, "inject", key) < config.step_premise_injection:
        candidates = inject_step_premises(candidates, missing, key, config.seed)
        injected = len(missing)
    annotation = await annotate(repl, state, candidates, applicability)
    shown = order_lemmas(annotation.lemmas)[:lemma_count]
    shown_names = {lemma.premise.full_name for lemma in shown}
    return LemmaSftExample(
        step.source,
        step.proof_identifier,
        step.step_index,
        step.goals_before,
        tuple(lemma_line(lemma, config.max_signature_characters) for lemma in shown),
        block,
        lemma_count,
        named,
        sum(name in shown_names for name in named),
        injected,
    )


async def annotate_split(
    config: LemmaDataConfig, directory: Path, split: str, processes: int, signatures: dict[str, str]
) -> int:
    """Appends finished proofs to examples_<split>.jsonl and skips proofs already there; returns replay failures."""
    output = directory / f"examples_{split}.jsonl"
    done = {example.proof_identifier for example in read_lemma_examples(output)} if output.exists() else set()
    by_proof: dict[str, list[TracedStep]] = collections.defaultdict(list)
    for step in read_selection(directory, split):
        if step.proof_identifier not in done:
            by_proof[step.proof_identifier].append(step)
    candidates = read_candidates(directory, split)
    applicability = config.applicability
    queue: asyncio.Queue[list[TracedStep]] = asyncio.Queue()
    for steps in by_proof.values():
        queue.put_nowait(steps)
    failures = 0
    finished = 0
    started = time.monotonic()
    async with LeanReplPool(processes, LeanReplConfig()) as pool:
        await pool.start(sorted({steps[0].header for steps in by_proof.values()}))

        async def worker() -> None:
            nonlocal failures, finished
            while not queue.empty():
                steps = queue.get_nowait()
                examples = []
                async with pool.acquire() as repl:
                    for step in steps:
                        example = await lemma_example(
                            repl, step, candidates.get(step_key(step), ()), signatures, config, applicability
                        )
                        if example is None:
                            failures += 1
                        else:
                            examples.append(example)
                with output.open("a", encoding="utf-8") as handle:
                    for example in examples:
                        handle.write(json.dumps(dataclasses.asdict(example), ensure_ascii=False) + "\n")
                finished += 1
                if finished % 100 == 0:
                    elapsed = time.monotonic() - started
                    print(f"{split}: {finished:,}/{len(by_proof):,} proofs, {elapsed:.0f} s", flush=True)

        await asyncio.gather(*(worker() for _ in range(processes)))
    return failures


def count_rows(examples: Sequence[LemmaSftExample], group_of: Callable[[LemmaSftExample], str]) -> tuple[CountRow, ...]:
    groups: dict[str, list[LemmaSftExample]] = collections.defaultdict(list)
    for example in examples:
        groups[group_of(example)].append(example)
    return tuple(
        CountRow(
            group=group,
            examples=len(members),
            naming_premises=sum(bool(example.step_premises) for example in members),
            step_premise_shown=sum(example.shown_step_premises > 0 for example in members),
            injected=sum(example.injected_step_premises > 0 for example in members),
            shown_closing_mean=statistics.fmean(
                sum("closes the goal" in line for line in example.lemmas) for example in members
            ),
        )
        for group, members in sorted(groups.items())
    )


def tokenized_examples(
    tokenizer: transformers.PreTrainedTokenizerBase, examples: Sequence[LemmaSftExample], config: LemmaDataConfig
) -> tuple[list[LemmaSftExample], list[int], list[int]]:
    """The examples within the length caps, with their prompt and completion token counts."""
    kept: list[LemmaSftExample] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    for example in examples:
        tokenized = tokenize_lemma_example(tokenizer, example)
        if (
            tokenized.prompt_token_count > config.max_prompt_tokens
            or tokenized.completion_token_count > config.max_completion_tokens
        ):
            continue
        kept.append(example)
        prompt_tokens.append(tokenized.prompt_token_count)
        completion_tokens.append(tokenized.completion_token_count)
    return kept, prompt_tokens, completion_tokens


def split_summary(
    split: str,
    annotated: int,
    over_length: int,
    kept: Sequence[LemmaSftExample],
    prompt_tokens: list[int],
    completion_tokens: list[int],
) -> SplitSummary:
    prompt = length_statistics(prompt_tokens)
    return SplitSummary(
        split=split,
        annotated=annotated,
        over_length=over_length,
        examples=len(kept),
        prompt_tokens_mean=prompt.mean,
        prompt_tokens_p90=prompt.p90,
        prompt_tokens_max=prompt.maximum,
        completion_tokens_mean=statistics.fmean(completion_tokens),
        total_tokens=prompt.total + sum(completion_tokens),
        by_lemma_count=count_rows(kept, lambda example: f"{example.lemma_count:02d}"),
        by_source=count_rows(kept, lambda example: example.source),
    )


def write_summary(summary: DataSummary) -> None:
    summary_directory = RUN_DIRECTORY / "summary"
    summary_directory.mkdir(parents=True, exist_ok=True)
    (summary_directory / f"{summary.name}.json").write_text(
        json.dumps(dataclasses.asdict(summary), indent=1, ensure_ascii=False), encoding="utf-8"
    )
    markdown = render_markdown(summary)
    (summary_directory / f"{summary.name}.md").write_text(markdown, encoding="utf-8")
    print(markdown)


def finish(config: LemmaDataConfig, directory: Path, name: str, replay_failures: dict[str, int]) -> None:
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.reference_tokenizer)
    split_summaries = []
    for split in SPLITS:
        annotated = list(read_lemma_examples(directory / f"examples_{split}.jsonl"))
        kept, prompt_tokens, completion_tokens = tokenized_examples(tokenizer, annotated, config)
        write_lemma_examples(DATA_DIRECTORY / "sft" / name / f"{split}.jsonl", kept)
        split_summaries.append(
            split_summary(split, len(annotated), len(annotated) - len(kept), kept, prompt_tokens, completion_tokens)
        )
    write_summary(
        DataSummary(
            name=name,
            config=config,
            applicability=config.applicability,
            selected_steps={split: len(read_selection(directory, split)) for split in SPLITS},
            replay_failures=replay_failures,
            splits=tuple(split_summaries),
        )
    )


def subsample(config: LemmaDataConfig, source_name: str, name: str, token_budget: int) -> None:
    """A smaller training set from a finished one, each list length keeping its token share; validation is kept."""
    tokenizer = transformers.AutoTokenizer.from_pretrained(config.reference_tokenizer)
    split_summaries = []
    for split in SPLITS:
        examples = list(read_lemma_examples(DATA_DIRECTORY / "sft" / source_name / f"{split}.jsonl"))
        kept, prompt_tokens, completion_tokens = tokenized_examples(tokenizer, examples, config)
        over_length = len(examples) - len(kept)
        if split == "train":
            totals = [prompt + completion for prompt, completion in zip(prompt_tokens, completion_tokens, strict=True)]
            chosen = subsample_indices(kept, totals, token_budget, config.seed)
            kept = [kept[index] for index in chosen]
            prompt_tokens = [prompt_tokens[index] for index in chosen]
            completion_tokens = [completion_tokens[index] for index in chosen]
        write_lemma_examples(DATA_DIRECTORY / "sft" / name / f"{split}.jsonl", kept)
        split_summaries.append(split_summary(split, len(examples), over_length, kept, prompt_tokens, completion_tokens))
    write_summary(
        DataSummary(
            name=name,
            config=config,
            applicability=config.applicability,
            selected_steps={},
            replay_failures={},
            splits=tuple(split_summaries),
            subsample_of=source_name,
            subsample_token_budget=token_budget,
        )
    )


def render_markdown(summary: DataSummary) -> str:
    def rows(groups: tuple[CountRow, ...]) -> list[list[str]]:
        return [
            [
                row.group,
                f"{row.examples:,}",
                f"{row.naming_premises / row.examples:.1%}",
                f"{row.step_premise_shown / row.examples:.1%}",
                f"{row.injected / row.examples:.1%}",
                f"{row.shown_closing_mean:.2f}",
            ]
            for row in groups
        ]

    headers = ["Group", "Examples", "Step names a premise", "Named premise shown", "Injected", "Closing lines"]
    config = summary.config
    sections = [
        f"# Lemma-aware SFT data `{summary.name}`",
        f"Traced competition steps (sources {', '.join(config.sources)}), whole proofs in a fixed pseudo-random "
        f"order up to an estimated {config.token_budget:,} tokens with equal source shares. Each step draws its list "
        f"length from {list(config.lemma_counts)}; for a non-empty list the retriever's top "
        f"{config.candidate_count} candidates are checked on the replayed state as in the search "
        f"({', '.join(f'`{tactic}`' for tactic in summary.applicability.tactics)}, "
        f"{summary.applicability.heartbeats:,} heartbeats) and the best k by applicability, then score, are shown. "
        f"With probability {config.step_premise_injection:g}, premises the step names but retrieval missed replace "
        f"low-ranked candidates. Replay failures (dropped): {summary.replay_failures}.",
    ]
    if summary.subsample_of:
        sections.append(
            f"This set subsamples the training split of `{summary.subsample_of}` to about "
            f"{summary.subsample_token_budget:,} tokens: examples in a fixed pseudo-random order, each list length "
            "keeping its share of the tokens. The validation split is the same."
        )
    for split in summary.splits:
        sections += [
            f"## {split.split}",
            f"{split.examples:,} examples ({split.over_length:,} over length dropped), {split.total_tokens:,} tokens; "
            f"prompt mean {split.prompt_tokens_mean:.0f}, p90 {split.prompt_tokens_p90}, max "
            f"{split.prompt_tokens_max}; completion mean {split.completion_tokens_mean:.0f}.",
            markdown_table(["List length", *headers[1:]], rows(split.by_lemma_count)),
            markdown_table(["Source", *headers[1:]], rows(split.by_source)),
        ]
    return "\n\n".join(sections) + "\n"


def main() -> None:
    arguments = parse_arguments()
    config = from_json_object(LemmaDataConfig, tomllib.loads(arguments.config.read_text(encoding="utf-8")))
    directory = work_directory(arguments.name)
    directory.mkdir(parents=True, exist_ok=True)
    failures_path = directory / "replay_failures.json"
    match arguments.stage:
        case Stage.SELECT:
            select(config, directory)
        case Stage.RETRIEVE:
            retrieve(config, directory, arguments.device)
        case Stage.ANNOTATE:
            signatures = {
                signature.full_name: signature.signature
                for signature in read_signatures(RETRIEVAL_DIRECTORY / "signatures.jsonl")
            }
            failures = json.loads(failures_path.read_text()) if failures_path.exists() else {}
            for split in SPLITS:
                count = asyncio.run(annotate_split(config, directory, split, arguments.processes, signatures))
                failures[split] = failures.get(split, 0) + count
                failures_path.write_text(json.dumps(failures))
        case Stage.FINISH:
            failures = json.loads(failures_path.read_text()) if failures_path.exists() else {}
            finish(config, directory, arguments.name, failures)
        case Stage.SUBSAMPLE:
            subsample(config, arguments.from_name, arguments.name, arguments.token_budget)


if __name__ == "__main__":
    main()
