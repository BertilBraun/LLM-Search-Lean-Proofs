"""What the rewrite kept and dropped (per reason), and what a built data set holds (examples per chunk length)."""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from lean_search.data_rewrite.chunks import REST_OF_PROOF
from lean_search.data_rewrite.dataset import BuildConfig, BuiltData, ChunkExample
from lean_search.data_rewrite.naming import NameChange, NameSource
from lean_search.data_rewrite.records import (
    ChunkExplanation,
    ExampleStatus,
    ExplanationOutcome,
    NamedStatus,
    ProofStatus,
    RewrittenExample,
    RewrittenProof,
)
from lean_search.data_rewrite.replay import has_nested_have_proof
from lean_search.lean.text import split_tactics
from lean_search.search.summary import markdown_table
from lean_search.training.sft_data import LengthStatistics, length_statistics

MESSAGES_PER_REASON = 3


@dataclass(frozen=True)
class ReasonCount:
    reason: str
    count: int
    # A few of Lean's messages for this reason.
    messages: tuple[str, ...] = ()


@dataclass(frozen=True)
class NameStatistics:
    changes: int
    by_model: int
    by_rules: int
    model_rejections: tuple[ReasonCount, ...]


@dataclass(frozen=True)
class ExplanationStatistics:
    chunks: int
    outcomes: tuple[ReasonCount, ...]
    # Explained after the first reply was rejected.
    explained_on_retry: int
    # Every rejected reply per reason, with a few of the rejected texts.
    rejected_replies: tuple[ReasonCount, ...]
    characters: LengthStatistics


@dataclass(frozen=True)
class BlockLengthCount:
    tactics: str
    before: int
    after: int


@dataclass(frozen=True)
class RewriteSummary:
    run_name: str
    proofs: int
    proofs_flattened: int
    proof_status: tuple[ReasonCount, ...]
    proof_status_of_flattened: tuple[ReasonCount, ...]
    named_proof_status: tuple[ReasonCount, ...]
    original_checks: int
    original_checks_verified: int
    kept_original_tactics: int
    kept_flat_tactics: int
    # Kept proofs with a tactic still holding a nested `have … := by` proof (the build drops chunks containing it).
    kept_with_nested_have: int
    examples: int
    examples_flattened: int
    example_status: tuple[ReasonCount, ...]
    named_example_status: tuple[ReasonCount, ...]
    # Replay (non-reasoning) examples of the reasoning data, replaced by chunk examples.
    replaced_replay_examples: int
    names: NameStatistics
    lean_hours: float
    # The teacher's explanations of chunks for the visible mode; None before the explain pass.
    explanations: ExplanationStatistics | None = None


@dataclass(frozen=True)
class TokenStatistics:
    part: str
    prompt: LengthStatistics
    completion: LengthStatistics


@dataclass(frozen=True)
class BuildSummary:
    name: str
    variant: str
    config: BuildConfig
    usable_proofs: int
    usable_examples: int
    chunk_candidates: int
    duplicate_chunks: int
    dropped_starts: tuple[ReasonCount, ...]
    train_examples: int
    train_chunks: int
    train_visible_chunks: int
    train_reasoning: int
    validation_chunks: int
    validation_visible_chunks: int
    validation_reasoning: int
    # Of the train examples: plain non-visible chunk examples, fallbacks included.
    non_visible_share: float
    train_chunks_by_drawn_length: tuple[ReasonCount, ...]
    train_chunks_by_tactics: tuple[ReasonCount, ...]
    # Chunks planned for the visible mode (train and validation): explained or why they stayed non-visible.
    explanation_outcomes: tuple[ReasonCount, ...]
    explanation_rejections: tuple[ReasonCount, ...]
    explanation_characters: LengthStatistics
    # Train visible-mode examples per tactics in the block: the reasoning examples alone, then with the chunks.
    visible_block_tactics: tuple[BlockLengthCount, ...]
    tokens: tuple[TokenStatistics, ...]


def reason_counts(reasons: Iterable[tuple[str, str]]) -> tuple[ReasonCount, ...]:
    """(reason, message) pairs counted per reason, most common first, with a few messages each."""
    counts: Counter[str] = Counter()
    messages: dict[str, list[str]] = {}
    for reason, message in reasons:
        counts[reason] += 1
        kept = messages.setdefault(reason, [])
        if message and len(kept) < MESSAGES_PER_REASON:
            kept.append(message)
    return tuple(ReasonCount(reason, count, tuple(messages[reason])) for reason, count in counts.most_common())


def name_statistics(changes: Sequence[NameChange]) -> NameStatistics:
    return NameStatistics(
        changes=len(changes),
        by_model=sum(change.source is NameSource.MODEL for change in changes),
        by_rules=sum(change.source is NameSource.RULES for change in changes),
        model_rejections=reason_counts(
            (str(change.rejection), "") for change in changes if change.rejection is not None
        ),
    )


def explanation_statistics(explanations: Sequence[ChunkExplanation]) -> ExplanationStatistics:
    explained = [record for record in explanations if record.outcome is ExplanationOutcome.EXPLAINED]
    return ExplanationStatistics(
        chunks=len(explanations),
        outcomes=reason_counts((str(record.outcome), "") for record in explanations),
        explained_on_retry=sum(bool(record.rejected) for record in explained),
        rejected_replies=reason_counts(
            (str(rejected.rejection), rejected.text) for record in explanations for rejected in record.rejected
        ),
        characters=length_statistics([len(record.named) for record in explained]),
    )


def rewrite_summary(
    run_name: str,
    proofs: Sequence[RewrittenProof],
    examples: Sequence[RewrittenExample],
    replaced_replay_examples: int,
    explanations: Sequence[ChunkExplanation] = (),
) -> RewriteSummary:
    kept = [proof for proof in proofs if proof.status is ProofStatus.KEPT]
    kept_examples = [example for example in examples if example.status is ExampleStatus.KEPT]
    checked = [proof for proof in kept if proof.named.original_verified is not None]
    renamed_changes = [
        change
        for named in [proof.named for proof in kept] + [example.named for example in kept_examples]
        if named.status is NamedStatus.RENAMED
        for change in (*named.statement_changes, *named.have_changes)
    ]
    return RewriteSummary(
        run_name=run_name,
        proofs=len(proofs),
        proofs_flattened=sum(proof.flattened for proof in proofs),
        proof_status=reason_counts((proof.status, proof.message) for proof in proofs),
        proof_status_of_flattened=reason_counts((proof.status, "") for proof in proofs if proof.flattened),
        named_proof_status=reason_counts((proof.named.status, proof.named.message) for proof in kept),
        original_checks=len(checked),
        original_checks_verified=sum(bool(proof.named.original_verified) for proof in checked),
        kept_original_tactics=sum(proof.original_tactics for proof in kept),
        kept_flat_tactics=sum(len(proof.tactics) for proof in kept),
        kept_with_nested_have=sum(has_nested_have_proof(proof.tactics) for proof in kept),
        examples=len(examples),
        examples_flattened=sum(example.flattened for example in examples),
        example_status=reason_counts((example.status, example.message) for example in examples),
        named_example_status=reason_counts((example.named.status, example.named.message) for example in kept_examples),
        replaced_replay_examples=replaced_replay_examples,
        names=name_statistics(renamed_changes),
        lean_hours=round(
            (sum(proof.lean_seconds for proof in proofs) + sum(example.lean_seconds for example in examples)) / 3600,
            2,
        ),
        explanations=explanation_statistics(explanations) if explanations else None,
    )


def length_label(tactics: int) -> str:
    return "rest" if tactics == REST_OF_PROOF else str(tactics)


def tactics_bucket(tactics: int) -> int:
    return min(tactics, 8)


def tactics_label(bucket: int) -> str:
    return "8+" if bucket == 8 else str(bucket)


def chunk_length_counts(chunks: Sequence[ChunkExample]) -> tuple[tuple[ReasonCount, ...], tuple[ReasonCount, ...]]:
    drawn = Counter(chunk.drawn for chunk in chunks)
    actual = Counter(tactics_bucket(chunk.tactics) for chunk in chunks)
    return (
        tuple(ReasonCount(length_label(length), drawn[length]) for length in sorted(drawn, key=lambda n: n or 99)),
        tuple(ReasonCount(tactics_label(length), actual[length]) for length in sorted(actual)),
    )


def visible_block_tactics(data: BuiltData) -> tuple[BlockLengthCount, ...]:
    before = Counter(
        tactics_bucket(len(split_tactics(example.tactic_block))) for example in data.train_reasoning if example.visible
    )
    after = before + Counter(tactics_bucket(chunk.tactics) for chunk in data.train_chunks if chunk.explanation)
    return tuple(BlockLengthCount(tactics_label(bucket), before[bucket], after[bucket]) for bucket in sorted(after))


def build_summary(name: str, config: BuildConfig, data: BuiltData, tokens: Sequence[TokenStatistics]) -> BuildSummary:
    by_drawn, by_tactics = chunk_length_counts(data.train_chunks)
    explained = [chunk for chunk in data.train_chunks if chunk.explanation]
    return BuildSummary(
        name=name,
        variant=str(config.variant),
        config=config,
        usable_proofs=data.usable_proofs,
        usable_examples=data.usable_examples,
        chunk_candidates=data.chunk_candidates,
        duplicate_chunks=data.duplicate_chunks,
        dropped_starts=reason_counts((str(reason), "") for reason in data.dropped_starts.elements()),
        train_examples=len(data.train),
        train_chunks=len(data.train_chunks),
        train_visible_chunks=len(explained),
        train_reasoning=len(data.train) - len(data.train_chunks),
        validation_chunks=len(data.validation_chunks),
        validation_visible_chunks=sum(bool(chunk.explanation) for chunk in data.validation_chunks),
        validation_reasoning=len(data.validation) - len(data.validation_chunks),
        non_visible_share=(len(data.train_chunks) - len(explained)) / max(len(data.train), 1),
        train_chunks_by_drawn_length=by_drawn,
        train_chunks_by_tactics=by_tactics,
        explanation_outcomes=reason_counts((str(outcome), "") for outcome in data.explanation_outcomes.elements()),
        explanation_rejections=reason_counts(
            (str(rejection), "") for rejection in data.explanation_rejections.elements()
        ),
        explanation_characters=length_statistics([len(chunk.explanation) for chunk in explained]),
        visible_block_tactics=visible_block_tactics(data),
        tokens=tuple(tokens),
    )


def _rows(counts: Sequence[ReasonCount], total: int) -> list[list[object]]:
    return [
        [entry.reason, entry.count, f"{entry.count / max(total, 1):.1%}", " / ".join(entry.messages)[:240]]
        for entry in counts
    ]


def render_rewrite_summary(summary: RewriteSummary) -> str:
    names = summary.names
    kept_proofs = next((entry.count for entry in summary.proof_status if entry.reason == "kept"), 0)
    kept_examples = next((entry.count for entry in summary.example_status if entry.reason == "kept"), 0)
    headers = ["reason", "count", "share", "example messages"]
    sections = [
        f"# Data rewrite `{summary.run_name}`",
        f"{summary.proofs:,} proofs ({summary.proofs_flattened:,} with nested `have … := by` proofs flattened) and "
        f"{summary.examples:,} reasoning examples ({summary.examples_flattened:,} flattened); "
        f"{summary.replaced_replay_examples:,} replay examples of the reasoning data are replaced by chunk examples. "
        f"Lean time {summary.lean_hours:.2f} h.",
        "## Proofs (numbered)",
        markdown_table(headers, _rows(summary.proof_status, summary.proofs)),
        "Of the flattened proofs: "
        + ", ".join(f"{entry.reason} {entry.count:,}" for entry in summary.proof_status_of_flattened)
        + f". Kept proofs: {summary.kept_original_tactics:,} top-level tactics before flattening, "
        f"{summary.kept_flat_tactics:,} after; {summary.kept_with_nested_have:,} keep a tactic with a nested proof "
        "flattening refused (the build drops the chunks containing it).",
        "## Proofs (named, among the kept)",
        markdown_table(headers, _rows(summary.named_proof_status, kept_proofs)),
        f"Checked against the original statement with `rename'`: {summary.original_checks_verified:,} of "
        f"{summary.original_checks:,} verify.",
        "## Reasoning examples (numbered)",
        markdown_table(headers, _rows(summary.example_status, summary.examples)),
        "## Reasoning examples (named, among the kept)",
        markdown_table(headers, _rows(summary.named_example_status, kept_examples)),
        "## Names",
        f"{names.changes:,} renamed hypotheses in the renamed items: {names.by_model:,} named by the model, "
        f"{names.by_rules:,} by the rules"
        + (
            "; model proposals rejected: "
            + ", ".join(f"{entry.reason} {entry.count:,}" for entry in names.model_rejections)
            if names.model_rejections
            else ""
        )
        + ".",
    ]
    if summary.explanations is not None:
        sections += render_explanation_statistics(summary.explanations)
    return "\n\n".join(sections) + "\n"


def characters_line(characters: LengthStatistics) -> str:
    return (
        f"mean {characters.mean:.0f}, p50 {characters.p50:,}, p90 {characters.p90:,}, p99 {characters.p99:,}, "
        f"max {characters.maximum:,} characters"
    )


def render_explanation_statistics(statistics: ExplanationStatistics) -> list[str]:
    return [
        "## Chunk explanations (teacher, for the visible mode)",
        markdown_table(["outcome", "count", "share", ""], _rows(statistics.outcomes, statistics.chunks)),
        f"{statistics.explained_on_retry:,} explained on the retry. Accepted explanations: "
        f"{characters_line(statistics.characters)}.",
        markdown_table(
            ["rejected reply", "count", "share of chunks", "example texts"],
            _rows(statistics.rejected_replies, statistics.chunks),
        ),
    ]


def render_build_summary(summary: BuildSummary) -> str:
    config = summary.config
    lengths = ", ".join(f"{length_label(length.tactics)} (weight {length.weight:g})" for length in config.chunk_lengths)
    token_rows = [
        [
            entry.part,
            entry.prompt.count,
            f"{entry.prompt.mean:.0f}",
            f"{entry.completion.mean:.0f}",
            entry.completion.p50,
            entry.completion.p90,
            entry.completion.maximum,
        ]
        for entry in summary.tokens
    ]
    sections = [
        f"# Rewritten SFT data `{summary.name}` ({summary.variant} hypotheses)",
        f"From rewrite run `{config.rewrite_run}`: {summary.usable_proofs:,} flat proofs and "
        f"{summary.usable_examples:,} reasoning examples usable in both naming variants. Per start state one chunk "
        f"length is drawn from {lengths}; a chunk that does not fit ({config.max_prompt_tokens} prompt, "
        f"{config.max_completion_tokens} completion tokens of `{config.tokenizer}`, no forbidden tokens, in both "
        f"variants) falls back to the next shorter length. {summary.chunk_candidates:,} chunks, "
        f"{summary.duplicate_chunks:,} duplicates dropped; start states without a fitting chunk: "
        + (", ".join(f"{entry.reason} {entry.count:,}" for entry in summary.dropped_starts) or "none")
        + ".",
        markdown_table(
            ["part", "examples"],
            [
                ["train chunk examples, non-visible", summary.train_chunks - summary.train_visible_chunks],
                ["train chunk examples, visible (teacher's explanation)", summary.train_visible_chunks],
                ["train reasoning examples", summary.train_reasoning],
                [
                    "validation chunk examples, non-visible (listed first)",
                    summary.validation_chunks - summary.validation_visible_chunks,
                ],
                ["validation chunk examples, visible", summary.validation_visible_chunks],
                ["validation reasoning examples", summary.validation_reasoning],
            ],
        ),
        f"Non-visible share of the train examples: {summary.non_visible_share:.1%} (configured "
        f"{config.non_visible_share:.1%}; chunks whose explanation was not accepted stay non-visible).",
        "## Chunks planned for the visible mode",
        markdown_table(
            ["outcome", "chunks", "share", ""],
            _rows(summary.explanation_outcomes, sum(entry.count for entry in summary.explanation_outcomes)),
        ),
        "Rejected teacher replies: "
        + (", ".join(f"{entry.reason} {entry.count:,}" for entry in summary.explanation_rejections) or "none")
        + f". Explanations of the train visible chunks: {characters_line(summary.explanation_characters)}.",
        "## Train visible-mode examples per tactics in the block",
        markdown_table(
            ["tactics", "reasoning examples", "share", "with visible chunks", "share"],
            [
                [
                    entry.tactics,
                    entry.before,
                    f"{entry.before / max(sum(row.before for row in summary.visible_block_tactics), 1):.1%}",
                    entry.after,
                    f"{entry.after / max(sum(row.after for row in summary.visible_block_tactics), 1):.1%}",
                ]
                for entry in summary.visible_block_tactics
            ],
        ),
        "## Train chunk examples per drawn length",
        markdown_table(
            ["drawn length", "examples"],
            [[entry.reason, entry.count] for entry in summary.train_chunks_by_drawn_length],
        ),
        "## Train chunk examples per tactics in the completion",
        markdown_table(
            ["tactics", "examples"], [[entry.reason, entry.count] for entry in summary.train_chunks_by_tactics]
        ),
        "## Tokens",
        markdown_table(
            ["part", "examples", "prompt mean", "completion mean", "completion p50", "p90", "max"], token_rows
        ),
    ]
    return "\n\n".join(sections) + "\n"
