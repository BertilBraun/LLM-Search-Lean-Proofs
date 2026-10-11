import argparse
import dataclasses
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from lean_search.corpora.decontamination import DecontaminationThresholds
from lean_search.corpora.download import directory_size, download_all
from lean_search.corpora.pipeline import LengthDistribution, PipelineSummary, run_pipeline
from lean_search.corpora.records import (
    FileImports,
    PremiseRecord,
    PremiseReference,
    ProofRecord,
    StatementRecord,
    TacticExample,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = Path(os.environ["LEAN_SEARCH_DATA"])
SUMMARY_DIRECTORY = Path(os.environ["LEAN_SEARCH_RUNS"]) / "phase2_data_inventory" / "summary"

THRESHOLDS = DecontaminationThresholds(
    formal_ngram=0.35,
    shared_conclusion_formal_ngram=0.25,
    minimum_conclusion_tokens=5,
    informal_ngram=0.20,
)


@dataclass(frozen=True)
class InventoryEntry:
    category: str
    repository: str
    items: str
    fields: str
    lean_version: str
    license: str
    full_proofs: str
    decision: str


INVENTORY = (
    InventoryEntry(
        "proofs",
        "Goedel-LM/Lean-workbook-proofs",
        "29,750 proofs",
        "problem_id, full_proof",
        "Goedel-Prover environment: Lean v4.9.0-rc1 + Mathlib 2f65ba7f (DeepSeek-Prover-V1.5 fork)",
        "MIT (LICENSE file)",
        "yes (whole files)",
        "selected",
    ),
    InventoryEntry(
        "proofs",
        "kfdong/STP_Lean_0320",
        "3,262,558 rows; 809,535 distinct prompts (conjecture 2,751,225 / statement 404,412 / mathlib 106,921 rows)",
        "prompt, target, weight, iteration, tag",
        "STP setup script: Lean 4.9.0-rc1 + xinhjBrant/mathlib4 (DeepSeek fork)",
        "MIT",
        "yes (statement + tactic block)",
        "selected (conjecture and statement tags; mathlib tag is conjecture-generation data)",
    ),
    InventoryEntry(
        "proofs",
        "kfdong/STP_Lean",
        "1,738,754 rows",
        "prompt, target, weight, iteration, tag",
        "as STP_Lean_0320",
        "MIT",
        "yes",
        "skipped (superseded by STP_Lean_0320)",
    ),
    InventoryEntry(
        "proofs",
        "kfdong/STP_Lean_SFT",
        "235,430 train + 4,096 eval",
        "prompt, target",
        "as STP; eval split is Mathlib file completion",
        "not stated",
        "yes",
        "skipped (SFT warm-up mix, overlaps STP and Mathlib)",
    ),
    InventoryEntry(
        "proofs",
        "Goedel-LM/SFT_dataset_v2",
        "1,745,010 chats",
        "messages (proof plan + Lean code, self-correction rounds)",
        "Goedel-Prover-V2: Lean 4.9 + Mathlib 2f65ba7f",
        "apache-2.0",
        "yes (final lean4 code block of the last assistant turn)",
        "selected",
    ),
    InventoryEntry(
        "proofs",
        "Goedel-LM/RL_dataset_V2",
        "98,632 prompts",
        "subset, messages",
        "as Goedel-Prover-V2",
        "apache-2.0",
        "no (RL prompts)",
        "skipped",
    ),
    InventoryEntry(
        "proofs",
        "deepseek-ai/DeepSeek-Prover-V1",
        "27,503 proofs",
        "name, split, formal_statement, goal, header, formal_proof",
        "not stated",
        "other (deepseek-license; LICENSE file in the repo is empty)",
        "yes",
        "selected",
    ),
    InventoryEntry(
        "proofs + statements",
        "internlm/Lean-Workbook",
        "140,214 statements (57,321 + 82,893 plus); 12,823 with 223,156 proofs; wkbk_1009: 25,214 one-step rows",
        "natural_language_statement, answer, tags, formal_statement, split, proof[]",
        "Lean v4.8.0-rc1 + Mathlib v4.8.0-rc1",
        "apache-2.0",
        "yes (tactic blocks, no header)",
        "selected (proofs and statement pool; 6,229 disproved ids dropped)",
    ),
    InventoryEntry(
        "proofs + statements",
        "AI-MO/NuminaMath-LEAN",
        "104,155 statements; 31,634 Kimina-Prover proofs; 9,475 complete human proofs",
        "uuid, problem, formal_statement, formal_ground_truth, ground_truth_type, formal_proof, rl_data, ...",
        "Mathlib v4.15.0 (version mismatch)",
        "apache-2.0",
        "yes",
        "selected (proofs lowest priority; statement pool)",
    ),
    InventoryEntry(
        "statements",
        "AI-MO/Kimina-Prover-Promptset",
        "24,418 rows (7,228 distinct statements)",
        "statement_id, natural_language, formal_statement, source, name",
        "Mathlib v4.15.0 (derived from NuminaMath-LEAN)",
        "apache-2.0 (README)",
        "no",
        "selected (statement pool)",
    ),
    InventoryEntry(
        "statements",
        "Goedel-LM/Goedel-Pset-v1",
        "1,732,594 statements",
        "problem_id, formal_statement, informal_statement",
        "compiled with sorry in the Goedel-Prover environment (Lean 4.9)",
        "MIT (LICENSE file)",
        "no",
        "selected (statement pool)",
    ),
    InventoryEntry(
        "proofs",
        "stoney0062/Leanabell-Prover-Traindata-SFT",
        "218,988 proofs",
        "prompt, output",
        "not stated (DeepSeek-Prover-V1.5 prompt format)",
        "apache-2.0",
        "yes (with explanatory comments)",
        "selected (low priority, provenance unclear)",
    ),
    InventoryEntry(
        "proofs",
        "FrenzyMath/Herald_proofs",
        "44,553 proofs",
        "id, name, formal_theorem, informal_theorem, formal_proof, informal_proof, commented_proof, header",
        "Lean v4.11.0",
        "apache-2.0",
        "yes",
        "skipped (Mathlib-internal theorems with per-file headers and variables)",
    ),
    InventoryEntry(
        "proofs",
        "iiis-lean/NuminaMath-LEAN-Sol",
        "81,311 rows",
        "NuminaMath-LEAN fields + NL solution",
        "Mathlib v4.15.0",
        "apache-2.0",
        "yes",
        "skipped (same proofs as NuminaMath-LEAN)",
    ),
    InventoryEntry(
        "proofs",
        "iiis-lean/lean-math-formal-corpus",
        "2,877 rows",
        "benchmark statements and proofs",
        "v4.9.0 / v4.15.0 / v4.27.0 configs",
        "not stated",
        "partly",
        "excluded (contains miniF2F and other benchmarks)",
    ),
    InventoryEntry(
        "proofs",
        "LukeBailey181/minif2f_proofnet_lean_workbook_deepseek_prover_sols",
        "small",
        "solutions per benchmark split",
        "not stated",
        "not stated",
        "yes",
        "excluded (contains miniF2F solutions)",
    ),
    InventoryEntry(
        "traced transitions",
        "HyperCactus0/LeanTransitionCorpus",
        "14.8 GB, 51,134 files",
        "state before/after, tactic, Syntax/Expr trees, premises, provenance",
        "Mathlib 29dcec07 (sources: DeepSeek-Prover-V1, Goedel workbook, Numina, Mathlib, OProofs)",
        "apache-2.0 (packaging)",
        "per-step only",
        "skipped (traced in a different environment; we trace ourselves)",
    ),
    InventoryEntry(
        "traced transitions",
        "banach1729/goedel-workbook-lean427",
        "29,750 proofs, 60,341 tactic pairs",
        "Lean files + tactic_pairs.jsonl",
        "Lean v4.27.0",
        "apache-2.0",
        "yes",
        "skipped (version mismatch)",
    ),
    InventoryEntry(
        "mathlib",
        "LeanDojo Benchmark 4 v10 (Zenodo 12740403)",
        "122,517 theorems (random and novel_premises splits 118,517/2,000/2,000), corpus.jsonl premises",
        "traced_tactics (state_before, tactic, annotated premises, state_after), corpus premises and imports",
        "Mathlib 29dcec07 (2024-07-01, lean4:v4.10.0-rc1); closest LeanDojo release to the pin",
        "CC BY 2.0",
        "per-step only",
        "selected (zenodo.org is reachable from the node)",
    ),
    InventoryEntry(
        "mathlib",
        "l3lab/ntp-mathlib",
        "307,049 examples (7.8 GB)",
        "state, srcUpToTactic, nextTactic, declUpToTactic, declId, decl, file_tag",
        "Mathlib cf8e23a6, lean4:v4.4.0",
        "not stated",
        "per-step only",
        "skipped (older Mathlib, no premise annotations)",
    ),
    InventoryEntry(
        "mathlib",
        "internlm/Lean-Github",
        "29k theorems from 100+ repositories",
        "lean-github.parquet",
        "mixed",
        "apache-2.0",
        "per-step",
        "skipped (not Mathlib premises)",
    ),
    InventoryEntry(
        "mathlib",
        "ScalableMath/Lean-STaR-base / Lean-STaR-plus",
        "82 MB / 62 MB JSON",
        "state, thought, tactic",
        "not stated",
        "not stated (no dataset card)",
        "per-step only",
        "skipped",
    ),
    InventoryEntry(
        "mathlib",
        "mathlib-initiative/mathlib-tactics",
        "1M-10M tactic invocations",
        "goal states and tactics (lean_scout)",
        "Mathlib d13f23b7 (2026)",
        "apache-2.0",
        "per-step only",
        "skipped (version mismatch)",
    ),
    InventoryEntry(
        "mathlib",
        "FrenzyMath/state_tactic_pairs",
        "56,407 pairs",
        "state, tactic",
        "not stated (REAL-Prover)",
        "apache-2.0",
        "per-step only",
        "skipped (no premises)",
    ),
)

SCHEMA_FILES = (
    (ProofRecord, "proofs/<source>.jsonl, proofs/selected_for_tracing.jsonl"),
    (StatementRecord, "statements/<pool>.jsonl, statements/merged.jsonl"),
    (TacticExample, "mathlib/tactics_<split strategy>_<split>.jsonl"),
    (PremiseReference, "nested in TacticExample.premises"),
    (PremiseRecord, "mathlib/premises.jsonl"),
    (FileImports, "mathlib/file_imports.jsonl"),
)

LEAN_VERSION_NOTES = (
    "Our pin (lean/lean-toolchain) is Lean v4.9.0-rc1 with Mathlib d1d1e4b7 (2024-06-12), the upstream parent of "
    "the DeepSeek-Prover-V1.5 Mathlib fork commit 2f65ba7f, which Goedel-Prover (V1 and V2) and STP also pin.",
    "Goedel workbook proofs, STP_Lean_0320 and Goedel SFT v2 come from provers run in that environment.",
    "Lean Workbook proofs were found under Lean v4.8.0-rc1, one release older than the pin.",
    "DeepSeek-Prover-V1 and Leanabell do not state their Lean version.",
    "NuminaMath-LEAN and the Kimina prompt set target Mathlib v4.15.0, six Lean releases newer than the pin; "
    "their replay rate is unknown until they are traced.",
    "LeanDojo Benchmark 4 v10 traces Mathlib 29dcec07 (2024-07-01, Lean v4.10.0-rc1), 19 days newer than the "
    "pinned Mathlib; premises added in that window do not exist in our environment.",
    "Every proof is replayed in the pinned environment during tracing, so version drift costs coverage, not "
    "correctness.",
)


def _distribution_row(name: str, distribution: LengthDistribution) -> str:
    percentiles = distribution.percentiles
    return (
        f"| {name} | {distribution.count:,} | {distribution.mean} | {percentiles.get('p50', 0):.0f} | "
        f"{percentiles.get('p90', 0):.0f} | {percentiles.get('p99', 0):.0f} | {distribution.maximum:,} |"
    )


def _histogram_line(distribution: LengthDistribution) -> str:
    return ", ".join(f"{bucket}: {count:,}" for bucket, count in distribution.histogram.items())


def render_markdown(summary: PipelineSummary, raw_sizes: dict[str, int], normalized_sizes: dict[str, int]) -> str:
    lines = ["# Phase 2 data inventory", ""]
    lines += ["## Inventory (verified on hf-mirror.com, GitHub and Zenodo)", ""]
    lines += ["| Category | Dataset | Items | Fields | Lean / Mathlib | License | Full proofs | Decision |"]
    lines += ["|---|---|---|---|---|---|---|---|"]
    for entry in INVENTORY:
        lines.append(
            f"| {entry.category} | {entry.repository} | {entry.items} | {entry.fields} | {entry.lean_version} | "
            f"{entry.license} | {entry.full_proofs} | {entry.decision} |"
        )
    lines += ["", "## Downloads (`$LEAN_SEARCH_DATA/raw`)", "", "| Directory | Size (MB) |", "|---|---|"]
    lines += [f"| {name} | {size / 1e6:,.0f} |" for name, size in sorted(raw_sizes.items())]
    lines += [f"| **total** | {sum(raw_sizes.values()) / 1e6:,.0f} |", ""]
    lines += ["## Proof corpora (`$LEAN_SEARCH_DATA/normalized/proofs`)", ""]
    lines += [
        "| Source | Raw | Rejected | Exact duplicates | Decontaminated proofs | Statements | "
        f"Over cap ({summary.proofs_per_statement}) | Kept proofs | Pinned env |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for source in summary.proof_sources:
        rejected = sum(source.rejections.values())
        removed = sum(source.decontamination_removed_proofs.values())
        lines.append(
            f"| {source.name} | {source.raw_items:,} | {rejected:,} | {source.exact_duplicates_removed:,} | "
            f"{removed:,} | {source.statements:,} | {source.removed_by_statement_cap:,} | {source.kept_proofs:,} | "
            f"{'yes' if source.matches_pinned_environment else 'no'} |"
        )
    merged = summary.merged_proofs
    selected = summary.selected_for_tracing
    lines += [
        "",
        f"Merged across sources (priority {' > '.join(merged.sources_in_priority_order)}, at most "
        f"{summary.proofs_per_statement} distinct proofs per statement): **{merged.proofs:,} proofs of "
        f"{merged.statements:,} statements**.",
        "",
        f"Selected for tracing (`proofs/selected_for_tracing.jsonl`, budget {summary.tracing_budget:,}): every merged "
        "proof from the non-sampled sources, then one proof each for further statements of the sampled sources "
        f"in hash order until the budget is reached: **{selected.proofs:,} proofs of {selected.statements:,} "
        "statements** ("
        + ", ".join(f"{source}: {count:,}" for source, count in selected.proofs_by_source.items())
        + ").",
        "",
        "Rejection reasons per source:",
        "",
    ]
    for source in summary.proof_sources:
        reasons = ", ".join(f"{reason}: {count:,}" for reason, count in source.rejections.items()) or "none"
        lines.append(f"- {source.name}: {reasons}")
    lines += ["", "### Proof length (kept proofs)", ""]
    lines += ["| Source | Proofs | Mean top-level tactics | p50 | p90 | p99 | Max |", "|---|---|---|---|---|---|---|"]
    for source in summary.proof_sources:
        lines.append(_distribution_row(source.name, source.top_level_tactics))
    lines.append(_distribution_row("merged", merged.top_level_tactics))
    lines.append(_distribution_row("selected for tracing", selected.top_level_tactics))
    lines += ["", "| Source | Proofs | Mean characters | p50 | p90 | p99 | Max |", "|---|---|---|---|---|---|---|"]
    for source in summary.proof_sources:
        lines.append(_distribution_row(source.name, source.proof_characters))
    lines.append(_distribution_row("merged", merged.proof_characters))
    lines.append(_distribution_row("selected for tracing", selected.proof_characters))
    lines += ["", "Top-level tactic histograms:", ""]
    for source in summary.proof_sources:
        lines.append(f"- {source.name}: {_histogram_line(source.top_level_tactics)}")
    lines.append(f"- merged: {_histogram_line(merged.top_level_tactics)}")
    lines.append(f"- selected for tracing: {_histogram_line(selected.top_level_tactics)}")
    lines += ["", "## Statement pools (`$LEAN_SEARCH_DATA/normalized/statements`)", ""]
    lines += [
        "| Pool | Raw | Rejected | Duplicates | Decontaminated | Kept |",
        "|---|---|---|---|---|---|",
    ]
    for pool in summary.statement_sources:
        lines.append(
            f"| {pool.name} | {pool.raw_items:,} | {sum(pool.rejections.values()):,} | "
            f"{pool.exact_duplicates_removed:,} | {sum(pool.decontamination_removed.values()):,} | "
            f"{pool.kept_statements:,} |"
        )
    lines += [
        "",
        f"Merged pool (`statements/merged.jsonl`, deduplicated across pools): **{summary.merged_statements:,}**.",
    ]
    thresholds = summary.thresholds
    lines += [
        "",
        "## Decontamination against miniF2F ("
        + ", ".join(f"{split}: {count}" for split, count in summary.reference_problems.items())
        + " problems)",
        "",
        "A statement is removed (with all its proofs) when any rule fires against any miniF2F problem:",
        "",
        "1. `exact`: identical token sequence after stripping comments, the declaration keyword and name, and the "
        "`:= by ...` suffix.",
        "2. `name`: the theorem is named after a miniF2F problem, possibly with a non-digit suffix "
        "(`amc12a_2021_p12_6`). Most such hits in STP conjectures and Goedel SFT v2 reuse the benchmark name for "
        "unrelated content (formal similarity below 0.1); they are removed anyway so that no training statement "
        "carries a miniF2F problem name.",
        f"3. `formal_ngram`: Jaccard similarity of token 5-grams ≥ {thresholds.formal_ngram}, after renaming bound "
        "variables to `v0, v1, ...` in order of appearance and collapsing every hypothesis name (`h...`) to `h`.",
        f"4. `shared_conclusion`: identical anonymized conclusion of at least {thresholds.minimum_conclusion_tokens} "
        f"tokens and 5-gram Jaccard ≥ {thresholds.shared_conclusion_formal_ngram}.",
        f"5. `informal_ngram`: Jaccard of lower-cased word 4-grams of the informal statement ≥ "
        f"{thresholds.informal_ngram} (where a source has one; miniF2F's `Show that it is ...` suffix is ignored).",
        "6. `propagated`: the same canonical statement was removed from a statement pool by rules 1-5.",
        "",
        "Thresholds come from reading samples per similarity band: formal 5-gram scores of 0.30-0.35 were unrelated "
        "statements sharing binder boilerplate; 0.35-0.40 were mostly unrelated but included reformulated miniF2F "
        "problems (e.g. `∀ x > 0, ∀ y > 0` against `∀ x y, 0 < x → 0 < y →`); 0.40-0.50 were about half "
        "reformulations or variants; everything above 0.6 was a copy. Equal conclusions recover reformulated "
        "hypotheses down to 0.25 (e.g. `imo_1964_p2` with triangle inequalities written as `a + b > c`). Informal "
        "4-gram scores of 0.20-0.25 still contained the same competition problem (e.g. `imo_1982_p1`), next to "
        "false positives from formula-heavy texts. We accept those false positives in exchange for recall.",
        "",
        "| Source | exact | name | formal_ngram | shared_conclusion | informal_ngram | propagated |",
        "|---|---|---|---|---|---|---|",
    ]
    kinds = ("exact", "name", "formal_ngram", "shared_conclusion", "informal_ngram", "propagated")
    for source in summary.proof_sources:
        counts = source.decontamination_removed_statements
        lines.append(
            f"| {source.name} (statements) | " + " | ".join(f"{counts.get(kind, 0):,}" for kind in kinds) + " |"
        )
    for pool in summary.statement_sources:
        counts = pool.decontamination_removed
        lines.append(f"| {pool.name} (pool) | " + " | ".join(f"{counts.get(kind, 0):,}" for kind in kinds) + " |")
    lines += [
        "",
        "Removed statements are listed in `normalized/decontamination/{proofs,statements}_<source>.jsonl`; every "
        "statement with formal similarity ≥ 0.3 or informal similarity ≥ 0.18 is listed in "
        "`normalized/decontamination/near_misses.jsonl` for review.",
    ]
    mathlib = summary.mathlib
    lines += ["", f"## Mathlib state/tactic/premise data ({mathlib.source})", ""]
    lines += ["| Split | Tactic examples | With premise annotations |", "|---|---|---|"]
    for split, count in mathlib.tactic_examples.items():
        lines.append(f"| {split} | {count:,} | {mathlib.tactic_examples_with_premises[split]:,} |")
    lines += ["", f"Premises: {mathlib.premises:,} in {mathlib.files:,} files (`mathlib/premises.jsonl`).", ""]
    lines += ["## Normalized schema (`lean_search.corpora.records`)", ""]
    for record_type, files in SCHEMA_FILES:
        fields = ", ".join(f"`{field.name}`" for field in dataclasses.fields(record_type))
        lines.append(f"- `{record_type.__name__}` ({files}): {fields}")
    lines += [
        "",
        "`formal_statement` runs from the declaration keyword to `:= by`; `tactic_proof` is the dedented tactic block "
        "after it, comments removed; `ProofRecord.top_level_tactics()` splits it at the block's own column (a "
        "line-based heuristic: "
        "continuation lines, bullets, `<;>` chains and `calc` steps stay with their tactic). A tracer runs `header`, "
        "opens `formal_statement` with `sorry` to get the initial state, then replays the tactics one at a time.",
        "",
    ]
    lines += ["## Normalized output sizes", "", "| File | Size (MB) |", "|---|---|"]
    lines += [f"| {name} | {size / 1e6:,.1f} |" for name, size in sorted(normalized_sizes.items())]
    lines += ["", "## Lean version notes", ""]
    lines += [f"- {note}" for note in LEAN_VERSION_NOTES]
    return "\n".join(lines) + "\n"


def minif2f_candidates(raw_directory: Path) -> tuple[Path, ...]:
    return (REPOSITORY_ROOT / "data" / "minif2f" / "minif2f.jsonl", raw_directory / "minif2f" / "minif2f.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description="Download, normalize and decontaminate the Lean proof corpora.")
    parser.add_argument("--raw-directory", type=Path, default=DATA_DIRECTORY / "raw")
    parser.add_argument("--output-directory", type=Path, default=DATA_DIRECTORY / "normalized")
    parser.add_argument("--summary-directory", type=Path, default=SUMMARY_DIRECTORY)
    parser.add_argument("--minif2f", type=Path, default=None, help="default: data/minif2f, else the raw download")
    parser.add_argument("--workers", type=int, default=int(os.environ.get("LEAN_SEARCH_CPU_COUNT", "8")))
    parser.add_argument("--download", action="store_true")
    arguments = parser.parse_args()

    if arguments.download:
        download_all(arguments.raw_directory)
    minif2f = arguments.minif2f or next(path for path in minif2f_candidates(arguments.raw_directory) if path.exists())
    started = time.time()
    summary = run_pipeline(arguments.raw_directory, arguments.output_directory, minif2f, THRESHOLDS, arguments.workers)
    raw_sizes = {path.name: directory_size(path) for path in arguments.raw_directory.iterdir() if path.is_dir()}
    normalized_sizes = {
        str(path.relative_to(arguments.output_directory)): path.stat().st_size
        for path in arguments.output_directory.rglob("*.jsonl")
    }
    arguments.summary_directory.mkdir(parents=True, exist_ok=True)
    report = {
        "pipeline": dataclasses.asdict(summary),
        "inventory": [dataclasses.asdict(entry) for entry in INVENTORY],
        "raw_sizes_bytes": raw_sizes,
        "normalized_sizes_bytes": normalized_sizes,
        "lean_version_notes": list(LEAN_VERSION_NOTES),
        "minif2f_path": str(minif2f),
        "seconds": round(time.time() - started),
    }
    (arguments.summary_directory / "summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (arguments.summary_directory / "summary.md").write_text(
        render_markdown(summary, raw_sizes, normalized_sizes), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
