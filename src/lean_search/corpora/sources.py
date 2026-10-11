import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

PIN_ENVIRONMENT = "lean4:v4.9.0-rc1 + Mathlib 2f65ba7f (DeepSeek-Prover-V1.5 environment)"
LEAN_WORKBOOK_HEADER = (
    "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 400000\n\nopen BigOperators Real Nat Topology Rat\n"
)
_THEOREM_NAME = re.compile(r"^[^\S\n]*(?:@\[[^\]\n]*\][^\S\n]*)?(theorem|lemma)\s+([^\s(\[{⦃:]+)", re.MULTILINE)
_COMMENT_BEFORE_DECLARATION = re.compile(r"/--?((?:(?!-/).)*)-/\s*(?:@\[[^\]\n]*\]\s*)?(?:theorem|lemma)\b", re.DOTALL)
_LEAN_CODE_BLOCK = re.compile(r"```lean4?\n(.*?)```", re.DOTALL)
_PARQUET_BATCH_ROWS = 4096


@dataclass(frozen=True)
class RawProof:
    source: str
    statement_identifier: str
    theorem_name: str | None
    lean_text: str
    informal_statement: str


@dataclass(frozen=True)
class RawStatement:
    source: str
    identifier: str
    theorem_name: str | None
    lean_text: str
    informal_statement: str


@dataclass(frozen=True)
class ProofShard:
    source: str
    path: Path


@dataclass(frozen=True)
class ProofSource:
    name: str
    repository: str
    lean_version_hint: str
    matches_pinned_environment: bool
    statement_identifiers_unique: bool
    sampled_for_tracing: bool
    shards: Callable[[Path], list[ProofShard]]
    read: Callable[[ProofShard], Iterator[RawProof]]


@dataclass(frozen=True)
class StatementSource:
    name: str
    repository: str
    lean_version_hint: str
    read: Callable[[Path], Iterator[RawStatement]]


def theorem_name(lean_text: str) -> str | None:
    declarations = _THEOREM_NAME.findall(lean_text)
    # Auxiliary lemmas usually precede the main theorem, so the last `theorem` wins over any `lemma`.
    theorems = [name for keyword, name in declarations if keyword == "theorem"]
    names = theorems or [name for _, name in declarations]
    return names[-1] if names else None


def comment_before_declaration(lean_text: str) -> str:
    comments = _COMMENT_BEFORE_DECLARATION.findall(lean_text)
    return comments[-1].strip() if comments else ""


def _iterate_parquet_rows(path: Path, columns: list[str]) -> Iterator[dict]:
    parquet_file = pq.ParquetFile(path)
    for batch in parquet_file.iter_batches(batch_size=_PARQUET_BATCH_ROWS, columns=columns):
        yield from batch.to_pylist()


def _parquet_shards(source: str, directory: Path) -> list[ProofShard]:
    return [ProofShard(source, path) for path in sorted(directory.glob("*.parquet"))]


def _code_after_fence(prompt: str) -> str:
    return prompt.split("```lean4\n", 1)[1]


def _strip_sorry_suffix(statement_text: str) -> str:
    return re.sub(r":=\s*by\s+sorry\s*$", ":= by", statement_text.rstrip())


def _indent(text: str, columns: int) -> str:
    return "\n".join(" " * columns + line if line.strip() else line for line in text.split("\n"))


def read_goedel_lean_workbook_proofs(shard: ProofShard) -> Iterator[RawProof]:
    for row in _iterate_parquet_rows(shard.path, ["problem_id", "full_proof"]):
        text = row["full_proof"]
        yield RawProof(shard.source, row["problem_id"], row["problem_id"], text, comment_before_declaration(text))


def read_deepseek_prover_v1(shard: ProofShard) -> Iterator[RawProof]:
    with shard.path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            text = row["header"] + row["formal_statement"] + row["formal_proof"]
            yield RawProof(shard.source, row["name"], row["name"], text, "")


def disproved_lean_workbook_names(raw_directory: Path) -> frozenset[str]:
    rows = _iterate_parquet_rows(raw_directory / "lean_workbook" / "wkbk_1009.parquet", ["id", "status"])
    return frozenset(row["id"] for row in rows if row["status"] == "disproved")


def read_lean_workbook_proofs(shard: ProofShard) -> Iterator[RawProof]:
    disproved = disproved_lean_workbook_names(shard.path.parent.parent)
    for row in json.loads(shard.path.read_text(encoding="utf-8")):
        name = theorem_name(row["formal_statement"])
        if not row["proof"] or name in disproved:
            continue
        statement = _strip_sorry_suffix(row["formal_statement"])
        informal = row["natural_language_statement"] or ""
        for proof in row["proof"]:
            text = f"{LEAN_WORKBOOK_HEADER}\n{statement}\n{_indent(proof, 2)}"
            yield RawProof(shard.source, name, name, text, informal)


def read_numinamath_lean_kimina_proofs(shard: ProofShard) -> Iterator[RawProof]:
    for row in _iterate_parquet_rows(shard.path, ["uuid", "formal_statement", "formal_proof", "problem"]):
        if row["formal_proof"]:
            name = theorem_name(row["formal_statement"])
            yield RawProof(shard.source, row["uuid"], name, row["formal_proof"], row["problem"] or "")


def read_numinamath_lean_human_proofs(shard: ProofShard) -> Iterator[RawProof]:
    columns = ["uuid", "formal_statement", "formal_ground_truth", "ground_truth_type", "problem"]
    for row in _iterate_parquet_rows(shard.path, columns):
        if row["ground_truth_type"] == "complete":
            name = theorem_name(row["formal_statement"])
            yield RawProof(shard.source, row["uuid"], name, row["formal_ground_truth"], row["problem"] or "")


def _read_stp_proofs(shard: ProofShard, tag: str) -> Iterator[RawProof]:
    for row in _iterate_parquet_rows(shard.path, ["prompt", "target", "tag"]):
        if row["tag"] != tag:
            continue
        text = _code_after_fence(row["prompt"]) + row["target"]
        name = theorem_name(text)
        yield RawProof(shard.source, name or "", name, text, "")


def read_stp_statement_proofs(shard: ProofShard) -> Iterator[RawProof]:
    yield from _read_stp_proofs(shard, "['statement']")


def read_stp_conjecture_proofs(shard: ProofShard) -> Iterator[RawProof]:
    yield from _read_stp_proofs(shard, "['conjecture']")


def _final_lean_block(message: str) -> str | None:
    blocks = _LEAN_CODE_BLOCK.findall(message)
    return blocks[-1] if blocks else None


def read_goedel_sft_v2_proofs(shard: ProofShard) -> Iterator[RawProof]:
    for row in _iterate_parquet_rows(shard.path, ["messages"]):
        messages = row["messages"]
        prompt_code = _final_lean_block(messages[0]["content"])
        proof_code = _final_lean_block(messages[-1]["content"])
        if messages[-1]["role"] != "assistant" or prompt_code is None or proof_code is None:
            continue
        name = theorem_name(prompt_code)
        if "import " in proof_code:
            text = proof_code
        else:
            declaration = re.search(r"^(?:theorem|lemma)\b", prompt_code, re.MULTILINE)
            header = prompt_code[: declaration.start()] if declaration else ""
            text = header + proof_code
        yield RawProof(shard.source, name or "", name, text, "")


def read_leanabell_proofs(shard: ProofShard) -> Iterator[RawProof]:
    with shard.path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            text = _code_after_fence(row["prompt"]) + row["output"].split("```", 1)[0]
            name = theorem_name(text)
            yield RawProof(shard.source, name or "", name, text, comment_before_declaration(text))


PROOF_SOURCES = (
    ProofSource(
        name="goedel_lean_workbook_proofs",
        repository="Goedel-LM/Lean-workbook-proofs",
        lean_version_hint=PIN_ENVIRONMENT,
        matches_pinned_environment=True,
        sampled_for_tracing=False,
        statement_identifiers_unique=True,
        shards=lambda raw: _parquet_shards("goedel_lean_workbook_proofs", raw / "goedel_lean_workbook_proofs" / "data"),
        read=read_goedel_lean_workbook_proofs,
    ),
    ProofSource(
        name="stp_lean_workbook",
        repository="kfdong/STP_Lean_0320 (tag statement)",
        lean_version_hint=PIN_ENVIRONMENT,
        matches_pinned_environment=True,
        sampled_for_tracing=False,
        statement_identifiers_unique=False,
        shards=lambda raw: _parquet_shards("stp_lean_workbook", raw / "stp_lean_0320" / "data"),
        read=read_stp_statement_proofs,
    ),
    ProofSource(
        name="stp_conjectures",
        repository="kfdong/STP_Lean_0320 (tag conjecture)",
        lean_version_hint=PIN_ENVIRONMENT,
        matches_pinned_environment=True,
        sampled_for_tracing=True,
        statement_identifiers_unique=False,
        shards=lambda raw: _parquet_shards("stp_conjectures", raw / "stp_lean_0320" / "data"),
        read=read_stp_conjecture_proofs,
    ),
    ProofSource(
        name="goedel_sft_v2",
        repository="Goedel-LM/SFT_dataset_v2",
        lean_version_hint=PIN_ENVIRONMENT,
        matches_pinned_environment=True,
        sampled_for_tracing=True,
        statement_identifiers_unique=False,
        shards=lambda raw: _parquet_shards("goedel_sft_v2", raw / "goedel_sft_v2" / "data"),
        read=read_goedel_sft_v2_proofs,
    ),
    ProofSource(
        name="deepseek_prover_v1",
        repository="deepseek-ai/DeepSeek-Prover-V1",
        lean_version_hint="not stated (DeepSeek-Prover-V1, May 2024; same header as DeepSeek-Prover-V1.5)",
        matches_pinned_environment=False,
        sampled_for_tracing=False,
        statement_identifiers_unique=True,
        shards=lambda raw: [ProofShard("deepseek_prover_v1", raw / "deepseek_prover_v1" / "dataset.jsonl")],
        read=read_deepseek_prover_v1,
    ),
    ProofSource(
        name="lean_workbook",
        repository="internlm/Lean-Workbook",
        lean_version_hint="lean4:v4.8.0-rc1 + Mathlib v4.8.0-rc1",
        matches_pinned_environment=False,
        sampled_for_tracing=False,
        statement_identifiers_unique=True,
        shards=lambda raw: [ProofShard("lean_workbook", raw / "lean_workbook" / "lean_workbook.json")],
        read=read_lean_workbook_proofs,
    ),
    ProofSource(
        name="leanabell_sft",
        repository="stoney0062/Leanabell-Prover-Traindata-SFT",
        lean_version_hint="not stated (DeepSeek-Prover-V1.5 prompt format)",
        matches_pinned_environment=False,
        sampled_for_tracing=True,
        statement_identifiers_unique=False,
        shards=lambda raw: [ProofShard("leanabell_sft", raw / "leanabell_sft" / "traindata_sft_without_cot.jsonl")],
        read=read_leanabell_proofs,
    ),
    ProofSource(
        name="numinamath_lean_kimina",
        repository="AI-MO/NuminaMath-LEAN (formal_proof)",
        lean_version_hint="Mathlib v4.15.0 (Lean v4.15.0)",
        matches_pinned_environment=False,
        sampled_for_tracing=False,
        statement_identifiers_unique=True,
        shards=lambda raw: _parquet_shards("numinamath_lean_kimina", raw / "numinamath_lean" / "data"),
        read=read_numinamath_lean_kimina_proofs,
    ),
    ProofSource(
        name="numinamath_lean_human",
        repository="AI-MO/NuminaMath-LEAN (formal_ground_truth)",
        lean_version_hint="Mathlib v4.15.0 (Lean v4.15.0)",
        matches_pinned_environment=False,
        sampled_for_tracing=False,
        statement_identifiers_unique=True,
        shards=lambda raw: _parquet_shards("numinamath_lean_human", raw / "numinamath_lean" / "data"),
        read=read_numinamath_lean_human_proofs,
    ),
)


def read_lean_workbook_statements(raw_directory: Path) -> Iterator[RawStatement]:
    disproved = disproved_lean_workbook_names(raw_directory)
    rows = json.loads((raw_directory / "lean_workbook" / "lean_workbook.json").read_text(encoding="utf-8"))
    for row in rows:
        name = theorem_name(row["formal_statement"])
        if name in disproved:
            continue
        text = f"{LEAN_WORKBOOK_HEADER}\n{row['formal_statement']}"
        yield RawStatement("lean_workbook", name, name, text, row["natural_language_statement"] or "")


def read_goedel_pset_statements(raw_directory: Path) -> Iterator[RawStatement]:
    for path in sorted((raw_directory / "goedel_pset_v1" / "data").glob("*.parquet")):
        for row in _iterate_parquet_rows(path, ["problem_id", "formal_statement", "informal_statement"]):
            text = row["formal_statement"]
            yield RawStatement(
                "goedel_pset_v1", row["problem_id"], theorem_name(text), text, row["informal_statement"] or ""
            )


def read_numinamath_lean_statements(raw_directory: Path) -> Iterator[RawStatement]:
    for path in sorted((raw_directory / "numinamath_lean" / "data").glob("*.parquet")):
        for row in _iterate_parquet_rows(path, ["uuid", "formal_statement", "problem"]):
            text = row["formal_statement"]
            yield RawStatement("numinamath_lean", row["uuid"], theorem_name(text), text, row["problem"] or "")


def read_kimina_promptset_statements(raw_directory: Path) -> Iterator[RawStatement]:
    path = raw_directory / "kimina_prover_promptset" / "data" / "train-00000-of-00001.parquet"
    for row in _iterate_parquet_rows(path, ["statement_id", "formal_statement", "natural_language", "name"]):
        text = row["formal_statement"]
        yield RawStatement(
            "kimina_prover_promptset", row["statement_id"], row["name"], text, row["natural_language"] or ""
        )


STATEMENT_SOURCES = (
    StatementSource(
        "lean_workbook",
        "internlm/Lean-Workbook",
        "lean4:v4.8.0-rc1 + Mathlib v4.8.0-rc1",
        read_lean_workbook_statements,
    ),
    StatementSource(
        "goedel_pset_v1",
        "Goedel-LM/Goedel-Pset-v1",
        "compiled with `sorry` in the Goedel-Prover environment (" + PIN_ENVIRONMENT + ")",
        read_goedel_pset_statements,
    ),
    StatementSource(
        "numinamath_lean",
        "AI-MO/NuminaMath-LEAN",
        "Mathlib v4.15.0 (Lean v4.15.0)",
        read_numinamath_lean_statements,
    ),
    StatementSource(
        "kimina_prover_promptset",
        "AI-MO/Kimina-Prover-Promptset",
        "Mathlib v4.15.0 (derived from NuminaMath-LEAN)",
        read_kimina_promptset_statements,
    ),
)
