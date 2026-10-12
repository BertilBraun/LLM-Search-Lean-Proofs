"""Pool v3 for the loop's curriculum: statements with a known formal proof that no training used, verified lazily.

    python experiments/phase6_pool_v3.py --config experiments/configs/expert_iteration/pool_v3.toml \
        --step select | deduplicate | verify [--limit N] [--sample N] [--loop-config LOOP] | report

select: groups the normalized (decontaminated) proof corpora by canonical statement, drops statements whose proofs
were selected for tracing (SFT v1/v2, the value data and everything derived from traced proofs) and writes the
statements easiest first by their shortest proof, with up to `proofs_per_statement` shortest proofs each, to
$LEAN_SEARCH_DATA/expert_iteration/pool_v3/candidates.jsonl, plus per-corpus counts.

deduplicate: clusters near-duplicate statements (the same problem formalized several ways) by MinHash/LSH over
normalized token 5-grams (near_duplicates.py) and keeps the easiest member of each cluster, without proved
negations of conjectures (`drop_negations`); the full list moves to candidates_all.jsonl. dedup.json holds the counts
per source before and after and sample pairs per similarity bin.

verify (CPU only; run it niced): compiles each candidate's proofs in our Lean environment, shortest first, until one
passes, in candidate order and in batches, keeping `verification.lead` usable statements ahead of what the loop
(--loop-config) has started; appends to verified.jsonl, resumably. Also records the root goals and whether the loop's
automation tactics alone close the root (automation-trivial statements stay out of the curriculum). --limit verifies
N candidates and stops; --sample verifies a seeded random sample of N candidates into sample_verified.jsonl instead,
to estimate the pass rate per source.

report: per source, the statements available, verified, automation-trivial and failing, into
$LEAN_SEARCH_RUNS/phase6_pool_v3/summary/{summary.json,README.md}.
"""

import argparse
import asyncio
import dataclasses
import datetime
import hashlib
import heapq
import json
import os
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import numpy

from lean_search.corpora.decontamination import anonymized_statement_tokens, jaccard_similarity, token_ngrams
from lean_search.corpora.pipeline import statement_key
from lean_search.corpora.records import read_proof_records
from lean_search.expert_iteration.known_proofs import (
    KnownProofPoolConfig,
    KnownProofStatement,
    StatementProofs,
    VerifiedStatement,
    add_proof,
    easiest_first,
    is_negation,
    load_known_proof_pool_config,
    read_candidates,
    read_verified,
    verify_statement,
    write_records,
)
from lean_search.expert_iteration.loop_config import load_loop_config
from lean_search.expert_iteration.near_duplicates import MinHasher, SimilarPair, clusters, similar_pairs
from lean_search.expert_iteration.serving import LoopPaths
from lean_search.expert_iteration.shards import all_attempts
from lean_search.lean import LeanReplConfig, LeanReplPool
from lean_search.search import load_run_config
from lean_search.search.records import to_json
from lean_search.search.summary import markdown_table

REPOSITORY_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
RUNS_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"])
POOL_DIRECTORY = DATA_DIRECTORY / "expert_iteration" / "pool_v3"
SUMMARY_DIRECTORY = RUNS_DIRECTORY / "phase6_pool_v3" / "summary"
SAMPLE_SEED = "pool-v3-sample"


class Step(StrEnum):
    SELECT = "select"
    DEDUPLICATE = "deduplicate"
    VERIFY = "verify"
    REPORT = "report"


@dataclass
class CorpusCounts:
    name: str
    pooled: bool
    proofs: int = 0
    excluded_proofs: int = 0
    # Distinct statements with a proof from this corpus, outside training and inside it.
    statements: int = 0
    excluded_statements: int = 0
    # Statements no earlier corpus in the config has.
    new_statements: int = 0


@dataclass(frozen=True)
class SourceAvailability:
    source: str
    # Pooled statements whose shortest kept proof comes from this source (each statement counted once).
    candidates: int
    median_shortest_tactics: float


@dataclass(frozen=True)
class SelectionSummary:
    finished_at: str
    candidates: int
    duplicate_names_dropped: int
    corpora: tuple[CorpusCounts, ...]
    sources: tuple[SourceAvailability, ...]


@dataclass(frozen=True)
class VerificationCounts:
    source: str
    attempted: int
    verified: int
    automation_solved: int
    load_failed: int
    usable: int
    median_tactics: float | None
    mean_seconds: float


def log(message: str) -> None:
    print(f"{datetime.datetime.now(datetime.UTC).isoformat(timespec='seconds')} {message}", flush=True)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--step", type=Step, choices=list(Step), required=True)
    parser.add_argument("--limit", type=int, help="verify N candidates and stop")
    parser.add_argument("--sample", type=int, help="verify a seeded random sample of N candidates instead")
    parser.add_argument("--loop-config", type=Path, help="keep the lead ahead of this loop's started statements")
    return parser.parse_args()


def excluded_keys(config: KnownProofPoolConfig) -> frozenset[str]:
    cache = POOL_DIRECTORY / "excluded_statement_keys.txt"
    if cache.exists():
        return frozenset(cache.read_text(encoding="utf-8").split())
    keys = {
        statement_key(proof.formal_statement)
        for path in config.excluded_proofs
        for proof in read_proof_records(DATA_DIRECTORY / path)
    }
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(sorted(keys)) + "\n", encoding="utf-8")
    return frozenset(keys)


def first_per_name(statements: Sequence[KnownProofStatement]) -> tuple[list[KnownProofStatement], int]:
    seen: set[str] = set()
    kept = []
    for statement in statements:
        if statement.name not in seen:
            seen.add(statement.name)
            kept.append(statement)
    return kept, len(statements) - len(kept)


def select(config: KnownProofPoolConfig) -> None:
    excluded = excluded_keys(config)
    log(f"{len(excluded):,} statements excluded (proofs selected for tracing)")
    groups: dict[str, StatementProofs] = {}
    earlier: set[str] = set()
    corpora = []
    for corpus in config.corpora:
        counts = CorpusCounts(corpus.name, corpus.pooled)
        keys: set[str] = set()
        excluded_seen: set[str] = set()
        for record in read_proof_records(DATA_DIRECTORY / corpus.path):
            key = statement_key(record.formal_statement)
            if key in excluded:
                counts.excluded_proofs += 1
                excluded_seen.add(key)
                continue
            counts.proofs += 1
            keys.add(key)
            if corpus.pooled:
                add_proof(groups, key, record, config.proofs_per_statement)
        counts.statements = len(keys)
        counts.excluded_statements = len(excluded_seen)
        counts.new_statements = len(keys - earlier)
        earlier |= keys
        corpora.append(counts)
        log(f"{corpus.name}: {counts}")
    candidates, dropped = first_per_name(easiest_first(groups))
    write_records(POOL_DIRECTORY / "candidates.jsonl", candidates)
    by_source: dict[str, list[int]] = defaultdict(list)
    for candidate in candidates:
        by_source[candidate.proofs[0].source].append(candidate.proofs[0].top_level_tactics)
    summary = SelectionSummary(
        finished_at=datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
        candidates=len(candidates),
        duplicate_names_dropped=dropped,
        corpora=tuple(corpora),
        sources=tuple(
            SourceAvailability(source, len(tactics), statistics.median(tactics))
            for source, tactics in sorted(by_source.items())
        ),
    )
    (POOL_DIRECTORY / "selection.json").write_text(to_json(summary), encoding="utf-8")
    log(f"{len(candidates):,} candidates ({dropped} duplicate names dropped)")


@dataclass(frozen=True)
class SourceDeduplication:
    source: str
    before: int
    # Representatives of their near-duplicate cluster, then without negations.
    distinct: int
    after: int


@dataclass(frozen=True)
class PairSample:
    estimated_jaccard: float
    exact_jaccard: float
    first: str
    second: str


@dataclass(frozen=True)
class DeduplicationSummary:
    threshold: float
    before: int
    after: int
    largest_clusters: tuple[int, ...]
    sources: tuple[SourceDeduplication, ...]
    samples: tuple[PairSample, ...]


def similarity_bin(similarity: float) -> int:
    return min(int(similarity * 10), 9)


def deduplicate(config: KnownProofPoolConfig) -> None:
    all_candidates = POOL_DIRECTORY / "candidates_all.jsonl"
    if not all_candidates.exists():
        (POOL_DIRECTORY / "candidates.jsonl").rename(all_candidates)
    hasher = MinHasher()
    sources: list[str] = []
    negations: set[int] = set()
    signatures = []
    for index, candidate in enumerate(read_candidates(all_candidates)):
        sources.append(candidate.statement.source)
        if config.drop_negations and is_negation(candidate.statement):
            negations.add(index)
        signatures.append(hasher.signature(candidate.statement.formal_statement))
    log(f"{len(signatures):,} signatures")
    pairs = similar_pairs(numpy.stack(signatures))
    representatives = clusters(len(signatures), pairs, config.near_duplicate_jaccard)
    log(f"{len(pairs):,} candidate pairs, {len(set(representatives)):,} clusters")
    generator = random.Random(SAMPLE_SEED)
    by_bin: dict[int, list[SimilarPair]] = defaultdict(list)
    for pair in pairs:
        by_bin[similarity_bin(pair.estimated_jaccard)].append(pair)
    sampled = [pair for bin_pairs in by_bin.values() for pair in generator.sample(bin_pairs, min(8, len(bin_pairs)))]
    wanted = {index for pair in sampled for index in (pair.first, pair.second)}
    statements: dict[int, str] = {}
    kept = 0
    with (POOL_DIRECTORY / "candidates.jsonl").open("w", encoding="utf-8") as output:
        for index, candidate in enumerate(read_candidates(all_candidates)):
            if index in wanted:
                statements[index] = candidate.statement.formal_statement
            if representatives[index] == index and index not in negations:
                output.write(to_json(candidate) + "\n")
                kept += 1
    before = Counter(sources)
    distinct = Counter(source for index, source in enumerate(sources) if representatives[index] == index)
    after = Counter(
        source for index, source in enumerate(sources) if representatives[index] == index and index not in negations
    )
    sizes = Counter(representatives)
    summary = DeduplicationSummary(
        threshold=config.near_duplicate_jaccard,
        before=len(sources),
        after=kept,
        largest_clusters=tuple(size for _, size in sizes.most_common(10)),
        sources=tuple(
            SourceDeduplication(source, before[source], distinct[source], after[source]) for source in sorted(before)
        ),
        samples=tuple(
            PairSample(
                pair.estimated_jaccard,
                jaccard_similarity(
                    token_ngrams(anonymized_statement_tokens(statements[pair.first])),
                    token_ngrams(anonymized_statement_tokens(statements[pair.second])),
                ),
                statements[pair.first],
                statements[pair.second],
            )
            for pair in sorted(sampled, key=lambda pair: pair.estimated_jaccard)
        ),
    )
    (POOL_DIRECTORY / "dedup.json").write_text(to_json(summary), encoding="utf-8")
    log(f"{kept:,} of {len(sources):,} candidates kept")


def sample_candidates(path: Path, count: int) -> list[KnownProofStatement]:
    """The `count` candidates with the smallest seeded hashes of their names, in candidate order."""
    # A min-heap of inverted hashes keeps the largest kept hash on top.
    kept: list[tuple[bytes, int, KnownProofStatement]] = []
    for index, candidate in enumerate(read_candidates(path)):
        digest = hashlib.sha256(f"{SAMPLE_SEED}/{candidate.name}".encode()).digest()
        inverted = bytes(255 - byte for byte in digest)
        if len(kept) < count:
            heapq.heappush(kept, (inverted, index, candidate))
        elif inverted > kept[0][0]:
            heapq.heapreplace(kept, (inverted, index, candidate))
    return [candidate for _, _, candidate in sorted(kept, key=lambda entry: entry[1])]


def started_statements(loop_config: Path | None) -> set[str]:
    if loop_config is None:
        return set()
    config = load_loop_config(loop_config)
    paths = LoopPaths(RUNS_DIRECTORY, DATA_DIRECTORY, config.name)
    return {attempt.problem_name for attempt in all_attempts(paths.shards)}


def usable_unstarted(verified: Sequence[VerifiedStatement], started: set[str]) -> int:
    return sum(record.verified and not record.automation_solved and record.name not in started for record in verified)


def batches(
    candidates: Iterator[KnownProofStatement], done: set[str], size: int
) -> Iterator[list[KnownProofStatement]]:
    batch: list[KnownProofStatement] = []
    for candidate in candidates:
        if candidate.name in done:
            continue
        batch.append(candidate)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


async def verify(config: KnownProofPoolConfig, limit: int | None, sample: int | None, loop_config: Path | None) -> None:
    settings = config.verification
    output = POOL_DIRECTORY / ("sample_verified.jsonl" if sample else "verified.jsonl")
    verified, _ = read_verified(output)
    done = {record.name for record in verified}
    candidates = (
        iter(sample_candidates(POOL_DIRECTORY / "candidates.jsonl", sample))
        if sample
        else read_candidates(POOL_DIRECTORY / "candidates.jsonl")
    )
    automation = load_run_config(REPOSITORY_DIRECTORY / settings.automation_config).automation.tactics
    repl_config = LeanReplConfig(command_timeout_seconds=settings.command_timeout_seconds)
    remaining = limit if limit is not None else sample
    async with LeanReplPool(settings.concurrency, repl_config, settings.restart_fraction) as pool:
        for batch in batches(candidates, done, settings.batch):
            if remaining is not None and remaining <= 0:
                break
            batch = batch if remaining is None else batch[:remaining]
            while remaining is None and usable_unstarted(verified, started_statements(loop_config)) >= settings.lead:
                await asyncio.sleep(settings.check_seconds)

            async def one(candidate: KnownProofStatement) -> VerifiedStatement:
                async with pool.acquire() as repl:
                    return await verify_statement(repl, candidate, automation, settings.automation_timeout_seconds)

            results = await asyncio.gather(*(one(candidate) for candidate in batch))
            with output.open("a", encoding="utf-8") as handle:
                handle.writelines(to_json(result) + "\n" for result in results)
            verified.extend(results)
            if remaining is not None:
                remaining -= len(batch)
            passed = sum(result.verified for result in results)
            usable = usable_unstarted(verified, set())
            log(f"{len(verified):,} done: batch {passed}/{len(results)} verified, {usable:,} usable in all")


def verification_counts(records: Sequence[VerifiedStatement]) -> list[VerificationCounts]:
    by_source: dict[str, list[VerifiedStatement]] = defaultdict(list)
    for record in records:
        by_source[record.statement.source].append(record)
    counts = []
    for source, group in sorted(by_source.items()):
        verified = [record for record in group if record.verified]
        usable = [record for record in verified if not record.automation_solved]
        counts.append(
            VerificationCounts(
                source=source,
                attempted=len(group),
                verified=len(verified),
                automation_solved=sum(record.automation_solved for record in verified),
                load_failed=sum(record.load_failed for record in group),
                usable=len(usable),
                median_tactics=statistics.median(record.proof_tactics for record in usable) if usable else None,
                mean_seconds=statistics.fmean(record.seconds for record in group),
            )
        )
    return counts


def verification_rows(counts: Sequence[VerificationCounts]) -> list[list[object]]:
    return [
        [
            entry.source,
            f"{entry.attempted:,}",
            f"{entry.verified:,} ({entry.verified / entry.attempted:.0%})",
            f"{entry.automation_solved:,}",
            f"{entry.load_failed:,}",
            f"{entry.usable:,}",
            "–" if entry.median_tactics is None else f"{entry.median_tactics:g}",
            f"{entry.mean_seconds:.1f}",
        ]
        for entry in counts
    ]


def report() -> None:
    selection = json.loads((POOL_DIRECTORY / "selection.json").read_text(encoding="utf-8"))
    deduplication = json.loads((POOL_DIRECTORY / "dedup.json").read_text(encoding="utf-8"))
    verified, _ = read_verified(POOL_DIRECTORY / "verified.jsonl")
    sample, _ = read_verified(POOL_DIRECTORY / "sample_verified.jsonl")
    failures = Counter(record.failures[0] for record in [*verified, *sample] if not record.verified and record.failures)
    headers = [
        "Source",
        "Attempted",
        "Verified",
        "Automation-trivial",
        "Load failures",
        "Usable",
        "Median tactics",
        "s",
    ]
    markdown = "\n\n".join(
        [
            "# Pool v3: statements with known proofs",
            "Normalized (decontaminated) proof corpora grouped by canonical statement; statements whose proofs were "
            "selected for tracing (every training set derives from those) are excluded. Candidates are ordered "
            "easiest first by their shortest proof (top-level tactics, then characters).",
            "## Corpora",
            markdown_table(
                ["Corpus", "Pooled", "Proofs", "Statements", "New statements", "Excluded statements"],
                [
                    [
                        corpus["name"],
                        "yes" if corpus["pooled"] else "counted only",
                        f"{corpus['proofs']:,}",
                        f"{corpus['statements']:,}",
                        f"{corpus['new_statements']:,}",
                        f"{corpus['excluded_statements']:,}",
                    ]
                    for corpus in selection["corpora"]
                ],
            ),
            "## Near duplicates and negations",
            "MinHash/LSH over normalized token 5-grams; one statement per cluster at estimated Jaccard >= "
            f"{deduplication['threshold']} (sample pairs per similarity bin in dedup.json), the easiest kept; then "
            f"proved negations of conjectures dropped. {deduplication['before']:,} -> {deduplication['after']:,} "
            "statements.",
            markdown_table(
                ["Source", "Before", "Distinct", "Without negations"],
                [
                    [entry["source"], f"{entry['before']:,}", f"{entry['distinct']:,}", f"{entry['after']:,}"]
                    for entry in deduplication["sources"]
                ],
            ),
            f"## Candidates ({selection['candidates']:,} before deduplication)",
            "Each statement once, under the source of its shortest proof.",
            markdown_table(
                ["Source", "Candidates", "Median shortest proof (tactics)"],
                [
                    [source["source"], f"{source['candidates']:,}", f"{source['median_shortest_tactics']:g}"]
                    for source in selection["sources"]
                ],
            ),
            "## Verification sample (seeded random candidates)",
            markdown_table(headers, verification_rows(verification_counts(sample))),
            "## Verified for the curriculum (easiest first)",
            markdown_table(headers, verification_rows(verification_counts(verified))),
            "## Most common first failure",
            markdown_table(["Failure", "Statements"], [[text, count] for text, count in failures.most_common(10)]),
        ]
    )
    SUMMARY_DIRECTORY.mkdir(parents=True, exist_ok=True)
    (SUMMARY_DIRECTORY / "README.md").write_text(markdown + "\n", encoding="utf-8")
    summary = {
        "selection": selection,
        "sample": [dataclasses.asdict(entry) for entry in verification_counts(sample)],
        "verified": [dataclasses.asdict(entry) for entry in verification_counts(verified)],
    }
    (SUMMARY_DIRECTORY / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(markdown)


def main() -> None:
    arguments = parse_arguments()
    config = load_known_proof_pool_config(arguments.config)
    match arguments.step:
        case Step.SELECT:
            select(config)
        case Step.DEDUPLICATE:
            deduplicate(config)
        case Step.VERIFY:
            asyncio.run(verify(config, arguments.limit, arguments.sample, arguments.loop_config))
        case Step.REPORT:
            report()


if __name__ == "__main__":
    main()
