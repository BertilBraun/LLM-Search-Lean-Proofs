import dataclasses
import json
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from functools import cache
from multiprocessing import Pool
from pathlib import Path

from lean_search.corpora import leandojo
from lean_search.corpora.decontamination import (
    ContaminationIndex,
    ContaminationMatch,
    DecontaminationThresholds,
    MatchKind,
    ReferenceProblem,
    SimilarityAssessment,
    canonical_statement,
)
from lean_search.corpora.normalize import (
    Rejection,
    normalize_proof,
    normalize_statement,
    normalized_proof_text,
    short_hash,
)
from lean_search.corpora.records import ProofRecord, StatementRecord, write_jsonl
from lean_search.corpora.sources import (
    PROOF_SOURCES,
    STATEMENT_SOURCES,
    ProofShard,
    ProofSource,
    RawProof,
    RawStatement,
    StatementSource,
)

PROOFS_PER_STATEMENT = 3
TRACING_BUDGET = 300_000
REVIEW_FORMAL_FLOOR = 0.3
REVIEW_INFORMAL_FLOOR = 0.18
STATEMENT_CHUNK_SIZE = 5000
TACTIC_COUNT_BUCKETS = ((1, 1), (2, 2), (3, 3), (4, 5), (6, 10), (11, 20), (21, 50), (51, None))
CHARACTER_BUCKETS = ((0, 50), (51, 100), (101, 200), (201, 500), (501, 1000), (1001, 2000), (2001, 5000), (5001, None))


@dataclass(frozen=True)
class DecontaminationSettings:
    references: tuple[ReferenceProblem, ...]
    thresholds: DecontaminationThresholds


@dataclass(frozen=True)
class ProofShardTask:
    shard: ProofShard
    shard_number: int
    read: Callable[[ProofShard], Iterator[RawProof]]
    lean_version_hint: str
    statement_identifiers_unique: bool
    decontamination: DecontaminationSettings


@dataclass(frozen=True)
class StatementChunkTask:
    raw_statements: tuple[RawStatement, ...]
    lean_version_hint: str
    decontamination: DecontaminationSettings


@dataclass(frozen=True)
class NormalizedProof:
    record: ProofRecord
    statement_key: str
    proof_key: str
    top_level_tactic_count: int
    assessment: SimilarityAssessment
    contamination: ContaminationMatch | None


@dataclass(frozen=True)
class NormalizedStatement:
    record: StatementRecord
    statement_key: str
    assessment: SimilarityAssessment
    contamination: ContaminationMatch | None


@dataclass
class ProofShardResult:
    raw_count: int = 0
    rejections: Counter[str] = field(default_factory=Counter)
    duplicates_within_shard: int = 0
    proofs: list[NormalizedProof] = field(default_factory=list)


@dataclass
class StatementChunkResult:
    raw_count: int = 0
    rejections: Counter[str] = field(default_factory=Counter)
    statements: list[NormalizedStatement] = field(default_factory=list)


@dataclass(frozen=True)
class RemovedStatement:
    source: str
    identifier: str
    formal_statement: str
    reference_name: str
    reference_split: str
    kind: str
    similarity: float
    removed_items: int


@dataclass(frozen=True)
class NearMiss:
    source: str
    identifier: str
    formal_statement: str
    informal_statement: str
    best_formal_similarity: float
    best_formal_reference: str
    best_informal_similarity: float
    best_informal_reference: str
    removed_as: str


@dataclass(frozen=True)
class LengthDistribution:
    count: int
    mean: float
    percentiles: dict[str, float]
    maximum: int
    histogram: dict[str, int]


@dataclass(frozen=True)
class ProofSourceSummary:
    name: str
    repository: str
    lean_version_hint: str
    matches_pinned_environment: bool
    raw_items: int
    rejections: dict[str, int]
    after_validity_filters: int
    exact_duplicates_removed: int
    after_deduplication: int
    decontamination_removed_proofs: dict[str, int]
    decontamination_removed_statements: dict[str, int]
    after_decontamination: int
    statements: int
    statements_with_more_proofs_than_cap: int
    removed_by_statement_cap: int
    kept_proofs: int
    top_level_tactics: LengthDistribution
    proof_characters: LengthDistribution


@dataclass(frozen=True)
class StatementSourceSummary:
    name: str
    repository: str
    lean_version_hint: str
    raw_items: int
    rejections: dict[str, int]
    after_validity_filters: int
    exact_duplicates_removed: int
    after_deduplication: int
    decontamination_removed: dict[str, int]
    kept_statements: int


@dataclass(frozen=True)
class ProofCollectionSummary:
    sources_in_priority_order: tuple[str, ...]
    statements: int
    proofs: int
    proofs_by_source: dict[str, int]
    top_level_tactics: LengthDistribution
    proof_characters: LengthDistribution


@dataclass(frozen=True)
class MathlibSummary:
    source: str
    tactic_examples: dict[str, int]
    tactic_examples_with_premises: dict[str, int]
    premises: int
    files: int


@dataclass(frozen=True)
class PipelineSummary:
    proofs_per_statement: int
    thresholds: DecontaminationThresholds
    reference_problems: dict[str, int]
    proof_sources: list[ProofSourceSummary]
    merged_proofs: ProofCollectionSummary
    tracing_budget: int
    selected_for_tracing: ProofCollectionSummary
    statement_sources: list[StatementSourceSummary]
    merged_statements: int
    mathlib: MathlibSummary


@cache
def _contamination_index(settings: DecontaminationSettings) -> ContaminationIndex:
    return ContaminationIndex(settings.references, settings.thresholds)


def statement_key(formal_statement: str) -> str:
    return short_hash(canonical_statement(formal_statement))


def normalize_proof_shard(task: ProofShardTask) -> ProofShardResult:
    index = _contamination_index(task.decontamination)
    result = ProofShardResult()
    seen_pairs: set[tuple[str, str]] = set()
    assessments: dict[tuple[str, str], SimilarityAssessment] = {}
    for row_number, raw in enumerate(task.read(task.shard)):
        result.raw_count += 1
        identifier = f"{task.shard.source}/{task.shard_number}/{row_number}"
        normalized = normalize_proof(raw, identifier, task.lean_version_hint, task.statement_identifiers_unique)
        if isinstance(normalized, Rejection):
            result.rejections[normalized.value] += 1
            continue
        key = statement_key(normalized.formal_statement)
        proof_key = short_hash(normalized_proof_text(normalized.tactic_proof))
        if (key, proof_key) in seen_pairs:
            result.duplicates_within_shard += 1
            continue
        seen_pairs.add((key, proof_key))
        assessment_key = (key, raw.informal_statement)
        if assessment_key not in assessments:
            assessments[assessment_key] = index.assess(normalized.formal_statement, raw.informal_statement)
        assessment = assessments[assessment_key]
        tactic_count = len(normalized.top_level_tactics())
        result.proofs.append(NormalizedProof(normalized, key, proof_key, tactic_count, assessment, assessment.match))
    return result


def normalize_statement_chunk(task: StatementChunkTask) -> StatementChunkResult:
    index = _contamination_index(task.decontamination)
    result = StatementChunkResult()
    for raw in task.raw_statements:
        result.raw_count += 1
        normalized = normalize_statement(raw, task.lean_version_hint)
        if isinstance(normalized, Rejection):
            result.rejections[normalized.value] += 1
            continue
        assessment = index.assess(normalized.formal_statement, raw.informal_statement)
        key = statement_key(normalized.formal_statement)
        result.statements.append(NormalizedStatement(normalized, key, assessment, assessment.match))
    return result


def _bucket_label(low: int, high: int | None) -> str:
    if high is None:
        return f"{low}+"
    return str(low) if low == high else f"{low}-{high}"


def length_distribution(values: list[int], buckets: tuple[tuple[int, int | None], ...]) -> LengthDistribution:
    if not values:
        return LengthDistribution(0, 0.0, {}, 0, {})
    ordered = sorted(values)
    percentiles = {
        f"p{percent}": float(ordered[min(len(ordered) - 1, len(ordered) * percent // 100)])
        for percent in (10, 25, 50, 75, 90, 99)
    }
    histogram = {
        _bucket_label(low, high): sum(1 for value in values if value >= low and (high is None or value <= high))
        for low, high in buckets
    }
    return LengthDistribution(len(values), round(statistics.fmean(values), 2), percentiles, ordered[-1], histogram)


def _deterministic_order(proof: NormalizedProof) -> str:
    return short_hash(proof.statement_key + proof.proof_key)


def cap_proofs_per_statement(proofs: Iterable[NormalizedProof], cap: int) -> tuple[list[NormalizedProof], int]:
    by_statement: dict[str, list[NormalizedProof]] = defaultdict(list)
    for proof in proofs:
        by_statement[proof.statement_key].append(proof)
    kept: list[NormalizedProof] = []
    over_cap = 0
    for statement_proofs in by_statement.values():
        statement_proofs.sort(key=_deterministic_order)
        over_cap += len(statement_proofs) > cap
        for proof in statement_proofs[:cap]:
            record = dataclasses.replace(proof.record, distinct_proofs_for_statement=len(statement_proofs))
            kept.append(dataclasses.replace(proof, record=record))
    return kept, over_cap


def merge_proof_sources(
    kept_by_source: dict[str, list[NormalizedProof]], priority: tuple[str, ...], cap: int
) -> list[NormalizedProof]:
    by_statement: dict[str, list[NormalizedProof]] = defaultdict(list)
    for source_name in priority:
        for proof in kept_by_source[source_name]:
            by_statement[proof.statement_key].append(proof)
    merged: list[NormalizedProof] = []
    for statement_proofs in by_statement.values():
        distinct: dict[str, NormalizedProof] = {}
        for proof in statement_proofs:
            distinct.setdefault(proof.proof_key, proof)
        for proof in list(distinct.values())[:cap]:
            record = dataclasses.replace(proof.record, distinct_proofs_for_statement=len(distinct))
            merged.append(dataclasses.replace(proof, record=record))
    return merged


def select_for_tracing(
    merged: list[NormalizedProof], fully_included_sources: frozenset[str], budget: int
) -> list[NormalizedProof]:
    selected = [proof for proof in merged if proof.record.source in fully_included_sources]
    covered = {proof.statement_key for proof in selected}
    first_sampled_proof: dict[str, NormalizedProof] = {}
    for proof in merged:
        if proof.statement_key not in covered:
            first_sampled_proof.setdefault(proof.statement_key, proof)
    sampled_keys = sorted(first_sampled_proof, key=short_hash)[: max(0, budget - len(selected))]
    return selected + [first_sampled_proof[key] for key in sampled_keys]


def summarize_collection(proofs: list[NormalizedProof], priority: tuple[str, ...]) -> ProofCollectionSummary:
    return ProofCollectionSummary(
        sources_in_priority_order=priority,
        statements=len({proof.statement_key for proof in proofs}),
        proofs=len(proofs),
        proofs_by_source=dict(Counter(proof.record.source for proof in proofs)),
        top_level_tactics=length_distribution([proof.top_level_tactic_count for proof in proofs], TACTIC_COUNT_BUCKETS),
        proof_characters=length_distribution([len(proof.record.tactic_proof) for proof in proofs], CHARACTER_BUCKETS),
    )


def _removed_statements(
    source_name: str, items: Iterable[tuple[str, str, str, ContaminationMatch]]
) -> list[RemovedStatement]:
    grouped: dict[str, list[tuple[str, str, ContaminationMatch]]] = defaultdict(list)
    for key, identifier, formal_statement, match in items:
        grouped[key].append((identifier, formal_statement, match))
    removed = []
    for entries in grouped.values():
        identifier, formal_statement, match = entries[0]
        removed.append(
            RemovedStatement(
                source=source_name,
                identifier=identifier,
                formal_statement=formal_statement,
                reference_name=match.reference_name,
                reference_split=match.reference_split,
                kind=match.kind.value,
                similarity=round(match.similarity, 4),
                removed_items=len(entries),
            )
        )
    return removed


def _near_miss(
    source_name: str,
    identifier: str,
    record_statement: str,
    informal_statement: str,
    assessment: SimilarityAssessment,
    contamination: ContaminationMatch | None,
) -> NearMiss | None:
    if (
        assessment.best_formal_similarity < REVIEW_FORMAL_FLOOR
        and assessment.best_informal_similarity < REVIEW_INFORMAL_FLOOR
    ):
        return None
    return NearMiss(
        source=source_name,
        identifier=identifier,
        formal_statement=record_statement,
        informal_statement=informal_statement,
        best_formal_similarity=round(assessment.best_formal_similarity, 4),
        best_formal_reference=assessment.best_formal_reference,
        best_informal_similarity=round(assessment.best_informal_similarity, 4),
        best_informal_reference=assessment.best_informal_reference,
        removed_as=contamination.kind.value if contamination else "",
    )


def _propagated(match: ContaminationMatch) -> ContaminationMatch:
    return dataclasses.replace(match, kind=MatchKind.PROPAGATED)


def process_proof_source(
    source: ProofSource,
    raw_directory: Path,
    output_directory: Path,
    decontamination: DecontaminationSettings,
    contaminated_statements: dict[str, ContaminationMatch],
    pool: Pool,
) -> tuple[ProofSourceSummary, list[NormalizedProof], list[NearMiss]]:
    tasks = [
        ProofShardTask(
            shard,
            shard_number,
            source.read,
            source.lean_version_hint,
            source.statement_identifiers_unique,
            decontamination,
        )
        for shard_number, shard in enumerate(source.shards(raw_directory))
    ]
    combined = ProofShardResult()
    for shard_result in pool.imap_unordered(normalize_proof_shard, tasks):
        combined.raw_count += shard_result.raw_count
        combined.rejections.update(shard_result.rejections)
        combined.duplicates_within_shard += shard_result.duplicates_within_shard
        combined.proofs.extend(shard_result.proofs)
    after_validity = len(combined.proofs) + combined.duplicates_within_shard

    # One flagged copy of a statement (e.g. via its informal text) removes every proof of that statement.
    statement_contamination: dict[str, ContaminationMatch] = {}
    for proof in combined.proofs:
        if proof.contamination is not None:
            statement_contamination.setdefault(proof.statement_key, proof.contamination)
    unique: dict[tuple[str, str], NormalizedProof] = {}
    for proof in sorted(combined.proofs, key=lambda proof: proof.record.identifier):
        if proof.contamination is None and proof.statement_key in statement_contamination:
            proof = dataclasses.replace(proof, contamination=statement_contamination[proof.statement_key])
        elif proof.contamination is None and proof.statement_key in contaminated_statements:
            proof = dataclasses.replace(proof, contamination=_propagated(contaminated_statements[proof.statement_key]))
        unique.setdefault((proof.statement_key, proof.proof_key), proof)
    deduplicated = list(unique.values())

    contaminated = [proof for proof in deduplicated if proof.contamination is not None]
    clean = [proof for proof in deduplicated if proof.contamination is None]
    removed_statements = _removed_statements(
        source.name,
        (
            (proof.statement_key, proof.record.statement_identifier, proof.record.formal_statement, proof.contamination)
            for proof in contaminated
        ),
    )
    write_jsonl(output_directory / "decontamination" / f"proofs_{source.name}.jsonl", removed_statements)
    near_misses_by_statement: dict[str, NearMiss] = {}
    for proof in deduplicated:
        if proof.statement_key not in near_misses_by_statement:
            near_miss = _near_miss(
                source.name,
                proof.record.statement_identifier,
                proof.record.formal_statement,
                "",
                proof.assessment,
                proof.contamination,
            )
            if near_miss is not None:
                near_misses_by_statement[proof.statement_key] = near_miss

    kept, over_cap = cap_proofs_per_statement(clean, PROOFS_PER_STATEMENT)
    kept.sort(key=lambda proof: proof.record.identifier)
    write_jsonl(output_directory / "proofs" / f"{source.name}.jsonl", (proof.record for proof in kept))

    summary = ProofSourceSummary(
        name=source.name,
        repository=source.repository,
        lean_version_hint=source.lean_version_hint,
        matches_pinned_environment=source.matches_pinned_environment,
        raw_items=combined.raw_count,
        rejections=dict(sorted(combined.rejections.items())),
        after_validity_filters=after_validity,
        exact_duplicates_removed=after_validity - len(deduplicated),
        after_deduplication=len(deduplicated),
        decontamination_removed_proofs=dict(Counter(proof.contamination.kind.value for proof in contaminated)),
        decontamination_removed_statements=dict(Counter(removed.kind for removed in removed_statements)),
        after_decontamination=len(clean),
        statements=len({proof.statement_key for proof in clean}),
        statements_with_more_proofs_than_cap=over_cap,
        removed_by_statement_cap=len(clean) - len(kept),
        kept_proofs=len(kept),
        top_level_tactics=length_distribution([proof.top_level_tactic_count for proof in kept], TACTIC_COUNT_BUCKETS),
        proof_characters=length_distribution([len(proof.record.tactic_proof) for proof in kept], CHARACTER_BUCKETS),
    )
    return summary, kept, list(near_misses_by_statement.values())


def _statement_chunks(
    source: StatementSource, raw_directory: Path, decontamination: DecontaminationSettings
) -> Iterator[StatementChunkTask]:
    chunk: list[RawStatement] = []
    for raw in source.read(raw_directory):
        chunk.append(raw)
        if len(chunk) == STATEMENT_CHUNK_SIZE:
            yield StatementChunkTask(tuple(chunk), source.lean_version_hint, decontamination)
            chunk = []
    if chunk:
        yield StatementChunkTask(tuple(chunk), source.lean_version_hint, decontamination)


@dataclass
class StatementSourceResult:
    source: StatementSource
    raw_count: int
    rejections: Counter[str]
    after_validity: int
    deduplicated: list[NormalizedStatement]


def assess_statement_source(
    source: StatementSource, raw_directory: Path, decontamination: DecontaminationSettings, pool: Pool
) -> StatementSourceResult:
    raw_count = 0
    rejections: Counter[str] = Counter()
    statements: list[NormalizedStatement] = []
    for chunk_result in pool.imap(normalize_statement_chunk, _statement_chunks(source, raw_directory, decontamination)):
        raw_count += chunk_result.raw_count
        rejections.update(chunk_result.rejections)
        statements.extend(chunk_result.statements)
    unique: dict[str, NormalizedStatement] = {}
    for statement in statements:
        kept = unique.get(statement.statement_key)
        if kept is None or (kept.contamination is None and statement.contamination is not None):
            unique[statement.statement_key] = statement
    return StatementSourceResult(source, raw_count, rejections, len(statements), list(unique.values()))


def write_statement_source(
    result: StatementSourceResult,
    output_directory: Path,
    contaminated_statements: dict[str, ContaminationMatch],
) -> tuple[StatementSourceSummary, list[NormalizedStatement], list[NearMiss]]:
    statements = [
        dataclasses.replace(statement, contamination=_propagated(contaminated_statements[statement.statement_key]))
        if statement.contamination is None and statement.statement_key in contaminated_statements
        else statement
        for statement in result.deduplicated
    ]
    contaminated = [statement for statement in statements if statement.contamination is not None]
    clean = [statement for statement in statements if statement.contamination is None]
    name = result.source.name
    write_jsonl(
        output_directory / "decontamination" / f"statements_{name}.jsonl",
        _removed_statements(
            name,
            (
                (statement.statement_key, statement.record.identifier, statement.record.formal_statement, match)
                for statement in contaminated
                if (match := statement.contamination) is not None
            ),
        ),
    )
    write_jsonl(output_directory / "statements" / f"{name}.jsonl", (statement.record for statement in clean))
    near_misses = [
        near_miss
        for statement in statements
        if (
            near_miss := _near_miss(
                name,
                statement.record.identifier,
                statement.record.formal_statement,
                statement.record.informal_statement,
                statement.assessment,
                statement.contamination,
            )
        )
        is not None
    ]
    summary = StatementSourceSummary(
        name=name,
        repository=result.source.repository,
        lean_version_hint=result.source.lean_version_hint,
        raw_items=result.raw_count,
        rejections=dict(sorted(result.rejections.items())),
        after_validity_filters=result.after_validity,
        exact_duplicates_removed=result.after_validity - len(statements),
        after_deduplication=len(statements),
        decontamination_removed=dict(Counter(statement.contamination.kind.value for statement in contaminated)),
        kept_statements=len(clean),
    )
    return summary, clean, near_misses


def process_mathlib(benchmark_directory: Path, output_directory: Path) -> MathlibSummary:
    examples: dict[str, int] = {}
    with_premises: dict[str, int] = {}
    for strategy in leandojo.SPLIT_STRATEGIES:
        for split in leandojo.SPLITS:
            split_examples = list(leandojo.tactic_examples(benchmark_directory, strategy, split))
            path = output_directory / "mathlib" / f"tactics_{strategy}_{split}.jsonl"
            examples[f"{strategy}/{split}"] = write_jsonl(path, split_examples)
            with_premises[f"{strategy}/{split}"] = sum(1 for example in split_examples if example.premises)
    premises = write_jsonl(
        output_directory / "mathlib" / "premises.jsonl", leandojo.premise_records(benchmark_directory)
    )
    files = write_jsonl(output_directory / "mathlib" / "file_imports.jsonl", leandojo.file_imports(benchmark_directory))
    return MathlibSummary(leandojo.SOURCE, examples, with_premises, premises, files)


def read_reference_problems(minif2f_path: Path) -> tuple[ReferenceProblem, ...]:
    problems = []
    with minif2f_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            problems.append(
                ReferenceProblem(row["name"], row["split"], row["formal_statement"], row["informal_prefix"])
            )
    return tuple(problems)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_pipeline(
    raw_directory: Path,
    output_directory: Path,
    minif2f_path: Path,
    thresholds: DecontaminationThresholds,
    worker_count: int,
) -> PipelineSummary:
    references = read_reference_problems(minif2f_path)
    decontamination = DecontaminationSettings(references, thresholds)
    contaminated_statements: dict[str, ContaminationMatch] = {}
    near_misses: list[NearMiss] = []
    with Pool(worker_count) as pool:
        statement_results = [
            assess_statement_source(source, raw_directory, decontamination, pool) for source in STATEMENT_SOURCES
        ]
        for result in statement_results:
            for statement in result.deduplicated:
                if statement.contamination is not None:
                    contaminated_statements.setdefault(statement.statement_key, statement.contamination)
        proof_summaries: list[ProofSourceSummary] = []
        kept_by_source: dict[str, list[NormalizedProof]] = {}
        for source in PROOF_SOURCES:
            summary, kept, source_near_misses = process_proof_source(
                source, raw_directory, output_directory, decontamination, contaminated_statements, pool
            )
            proof_summaries.append(summary)
            kept_by_source[source.name] = kept
            near_misses.extend(source_near_misses)

    statement_summaries: list[StatementSourceSummary] = []
    merged_statements: dict[str, StatementRecord] = {}
    for result in statement_results:
        summary, clean, source_near_misses = write_statement_source(result, output_directory, contaminated_statements)
        statement_summaries.append(summary)
        near_misses.extend(source_near_misses)
        for statement in clean:
            merged_statements.setdefault(statement.statement_key, statement.record)
    write_jsonl(output_directory / "statements" / "merged.jsonl", merged_statements.values())

    priority = tuple(source.name for source in PROOF_SOURCES)
    merged = merge_proof_sources(kept_by_source, priority, PROOFS_PER_STATEMENT)
    fully_included = frozenset(source.name for source in PROOF_SOURCES if not source.sampled_for_tracing)
    selected = select_for_tracing(merged, fully_included, TRACING_BUDGET)
    write_jsonl(output_directory / "proofs" / "selected_for_tracing.jsonl", (proof.record for proof in selected))
    near_misses.sort(key=lambda near_miss: -max(near_miss.best_formal_similarity, near_miss.best_informal_similarity))
    write_jsonl(output_directory / "decontamination" / "near_misses.jsonl", near_misses)

    mathlib = process_mathlib(
        raw_directory / "leandojo_benchmark_4_v10" / "extracted" / "leandojo_benchmark_4", output_directory
    )
    summary = PipelineSummary(
        proofs_per_statement=PROOFS_PER_STATEMENT,
        thresholds=thresholds,
        reference_problems=dict(Counter(reference.split for reference in references)),
        proof_sources=proof_summaries,
        merged_proofs=summarize_collection(merged, priority),
        tracing_budget=TRACING_BUDGET,
        selected_for_tracing=summarize_collection(selected, priority),
        statement_sources=statement_summaries,
        merged_statements=len(merged_statements),
        mathlib=mathlib,
    )
    _write_json(output_directory / "pipeline_summary.json", dataclasses.asdict(summary))
    return summary
