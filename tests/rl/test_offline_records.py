"""Every record the offline arm writes and reads back, through JSON as its commands write and read it."""

import dataclasses
import json
from pathlib import Path

import pytest

pytest.importorskip("numpy")

import lean_search  # noqa: E402
from lean_search.corpora.records import StatementRecord  # noqa: E402
from lean_search.lean.text import FORBIDDEN_TOKENS  # noqa: E402
from lean_search.rl.offline_arm import (  # noqa: E402
    PoolProof,
    WalkFingerprint,
    load_offline_arm_config,
    walk_fingerprint,
    walk_settings_text,
)
from lean_search.rl.offline_held_out import FlatReference  # noqa: E402
from lean_search.rl.offline_walk import ProofWalk, WalkBlock, WalkedProof, WalkSettings, WalkStatus  # noqa: E402
from lean_search.search.records import from_json_object, to_json  # noqa: E402
from lean_search.training.sft_data import SftExample  # noqa: E402

CONFIG = Path(__file__).resolve().parents[2] / "experiments/configs/grpo/followup/offline/offline_arm.toml"
SETTINGS = WalkSettings(50_000, 60.0, True, True, True, "", ("exact?",), FORBIDDEN_TOKENS, 5)


def written_and_read[T](record: T, path: Path) -> T:
    """As walk writes walk.json (to_json, a line) and build reads it."""
    path.write_text(to_json(record) + "\n", encoding="utf-8")
    return from_json_object(type(record), json.loads(path.read_text(encoding="utf-8")))


def test_a_walk_fingerprint_round_trips(tmp_path: Path) -> None:
    text = walk_settings_text(SETTINGS, load_offline_arm_config(CONFIG).walk, "Qwen/Qwen3.5-4B", 1024)
    fingerprint = walk_fingerprint(Path(lean_search.__file__).resolve().parent, text, "proofs")
    assert written_and_read(fingerprint, tmp_path / "walk.json") == fingerprint


def test_a_walk_fingerprint_in_the_form_on_the_node_reads() -> None:
    data = {"sources": {"rl/offline_walk.py": "a" * 64}, "settings": "{}", "proofs_sha256": "b" * 64}
    assert from_json_object(WalkFingerprint, data).sources == {"rl/offline_walk.py": "a" * 64}


def test_a_pool_proof_round_trips(tmp_path: Path) -> None:
    statement = StatementRecord("goedel_sft_v2", "s@k", "import Mathlib", "theorem s : True := by", "", "pinned")
    proof = PoolProof("goedel_sft_v2.s@k", statement, 120, 3, ("trivial", "simp"))
    assert written_and_read(proof, tmp_path / "proofs.jsonl") == proof


def test_a_walked_proof_round_trips(tmp_path: Path) -> None:
    blocks = (WalkBlock(("x : ℕ\n⊢ x = x",), "rfl", 1),)
    walked = WalkedProof(
        "p", None, (WalkStatus.BLOCK_FAILED,), ProofWalk(WalkStatus.BLOCK_FAILED, blocks, 1, "e", 1), 2.5
    )
    assert written_and_read(walked, tmp_path / "walks.jsonl") == walked


def test_a_flat_reference_round_trips(tmp_path: Path) -> None:
    reference = FlatReference("test/p#0", (("⊢ a", "⊢ b"), ("⊢ b",)))
    assert written_and_read(reference, tmp_path / "flat_references.jsonl") == reference


def test_an_example_round_trips_as_build_writes_it() -> None:
    example = SftExample("offline_arm", "p", 2, ("⊢ a",), "simp")
    line = json.dumps(dataclasses.asdict(example), ensure_ascii=False)
    assert from_json_object(SftExample, json.loads(line)) == example
