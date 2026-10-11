import hashlib
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from huggingface_hub import snapshot_download


@dataclass(frozen=True)
class HuggingFaceDataset:
    name: str
    repository: str
    revision: str


@dataclass(frozen=True)
class ArchiveDownload:
    name: str
    url: str
    file_name: str
    md5: str | None


HUGGING_FACE_DATASETS = (
    HuggingFaceDataset(
        "goedel_lean_workbook_proofs", "Goedel-LM/Lean-workbook-proofs", "b731852af8d8ab11498fda27bce9020738c01c59"
    ),
    HuggingFaceDataset("stp_lean_0320", "kfdong/STP_Lean_0320", "8759699c72a373a49497cde1341a4a94c3845b2f"),
    HuggingFaceDataset("goedel_sft_v2", "Goedel-LM/SFT_dataset_v2", "da71b450f771880ea314a8860532ee26bf494753"),
    HuggingFaceDataset(
        "deepseek_prover_v1", "deepseek-ai/DeepSeek-Prover-V1", "1ee889f608fb12ba3596757ee91a60acd663ea81"
    ),
    HuggingFaceDataset("lean_workbook", "internlm/Lean-Workbook", "2e066e310b2c6d2c27616927ae131f82901c8f1c"),
    HuggingFaceDataset(
        "leanabell_sft", "stoney0062/Leanabell-Prover-Traindata-SFT", "1f1faf82920cb8590dc5c8c091dd46ba91a133bf"
    ),
    HuggingFaceDataset("numinamath_lean", "AI-MO/NuminaMath-LEAN", "51fa67f1f647ae1ecd81eef9f19306aa8a7b3a94"),
    HuggingFaceDataset(
        "kimina_prover_promptset", "AI-MO/Kimina-Prover-Promptset", "3009c548d90160d0f5e963d72238610c6732f812"
    ),
    HuggingFaceDataset("goedel_pset_v1", "Goedel-LM/Goedel-Pset-v1", "79fc4fbe87b4c694a941bc63ad92dc38d39d41db"),
)

ARCHIVE_DOWNLOADS = (
    ArchiveDownload(
        "leandojo_benchmark_4_v10",
        "https://zenodo.org/records/12740403/files/leandojo_benchmark_4.tar.gz?download=1",
        "leandojo_benchmark_4.tar.gz",
        "25e1ee60cd8925b9d2e8673ddcc34b4c",
    ),
    ArchiveDownload(
        "minif2f",
        "https://raw.githubusercontent.com/deepseek-ai/DeepSeek-Prover-V1.5/main/datasets/minif2f.jsonl",
        "minif2f.jsonl",
        None,
    ),
)


def _md5(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download_archive(archive: ArchiveDownload, raw_directory: Path) -> Path:
    directory = raw_directory / archive.name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / archive.file_name
    if not path.exists():
        urllib.request.urlretrieve(archive.url, path)
    if archive.md5 is not None and _md5(path) != archive.md5:
        raise ValueError(f"checksum mismatch for {path}")
    if path.suffixes[-2:] == [".tar", ".gz"]:
        extracted = directory / "extracted"
        if not extracted.exists():
            with tarfile.open(path) as archive_file:
                archive_file.extractall(extracted, filter="data")
    return path


def download_all(raw_directory: Path) -> None:
    for dataset in HUGGING_FACE_DATASETS:
        snapshot_download(
            repo_id=dataset.repository,
            repo_type="dataset",
            revision=dataset.revision,
            local_dir=raw_directory / dataset.name,
        )
    for archive in ARCHIVE_DOWNLOADS:
        download_archive(archive, raw_directory)


def directory_size(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file() and ".cache" not in path.parts)
