import pytest

from lean_search.retrieval.environment import NameCheck, parse_signature_dump
from lean_search.retrieval.premises import (
    compact_signature,
    serialize_premise,
    split_signature,
    strip_leandojo_goal_count,
    strip_universe_parameters,
)

ADD_COMM = "add_comm {G : Type u_1} [AddCommMagma G] (a b : G) : a + b = b + a"
MUL_POS = "mul_pos {α : Type u_1} [Mul α] [Zero α] {a b : α} (ha : 0 < a) (hb : 0 < b) : 0 < a * b"


@pytest.mark.parametrize(
    ("full_name", "code", "serialized"),
    [
        (
            "Nat.sub_le",
            "@[simp] theorem sub_le (n m : Nat) : n - m ≤ n",
            "@[simp] theorem <a>Nat.sub_le</a> (n m : Nat) : n - m ≤ n",
        ),
        ("foo", "theorem _root_.foo : True", "theorem <a>foo</a> : True"),
        ("List.get?_eq", "theorem get?_eq : x", "theorem <a>List.get?_eq</a> : x"),
        ("Nat.gcd_self", "theorem other : True", "theorem other : True"),
    ],
)
def test_premises_are_serialized_like_reprover(full_name: str, code: str, serialized: str) -> None:
    assert serialize_premise(full_name, code) == serialized


def test_leandojo_goal_count_is_stripped() -> None:
    assert strip_leandojo_goal_count("2 goals\nx : ℕ\n⊢ x = x\n\n⊢ True") == "x : ℕ\n⊢ x = x\n\n⊢ True"


def test_universe_parameters_are_stripped() -> None:
    assert strip_universe_parameters("add_comm.{u_1} {G : Type u_1} : G", "add_comm") == "add_comm {G : Type u_1} : G"


def test_signature_splits_into_binders_and_conclusion() -> None:
    assert split_signature(ADD_COMM, "add_comm") == (
        ("{G : Type u_1}", "[AddCommMagma G]", "(a b : G)"),
        "a + b = b + a",
    )


def test_nested_brackets_stay_in_one_binder() -> None:
    signature = "foo (f : ℕ → (ℕ × ℕ)) {s : Set ℕ} (h : s = {x | f x = (x, x)}) : True"
    assert split_signature(signature, "foo") == (
        ("(f : ℕ → (ℕ × ℕ))", "{s : Set ℕ}", "(h : s = {x | f x = (x, x)})"),
        "True",
    )


@pytest.mark.parametrize(
    ("signature", "compact"),
    [
        (ADD_COMM, "add_comm (a b : G) : a + b = b + a"),
        (MUL_POS, "mul_pos {a b : α} (ha : 0 < a) (hb : 0 < b) : 0 < a * b"),
        ("Nat.add_comm (n m : ℕ) : n + m = m + n", "Nat.add_comm (n m : ℕ) : n + m = m + n"),
        ("Real.pi : ℝ", "Real.pi : ℝ"),
    ],
)
def test_compact_signature_drops_instances_and_type_variables(signature: str, compact: str) -> None:
    assert compact_signature(signature, signature.split(" ")[0], 1000) == compact


def test_unparsable_signature_is_kept() -> None:
    assert compact_signature("«weird name» : True", "weird", 1000) == "«weird name» : True"


def test_long_signature_is_cut_with_an_ellipsis() -> None:
    assert compact_signature("foo (a : ℕ) : a = a + 0 + 0 + 0", "foo", 20) == "foo (a : ℕ) : a = …"


def test_signature_dump_is_parsed() -> None:
    lines = [
        "add_comm\t1\tadd_comm.{u_1} {G : Type u_1}\n",
        "gone\t0\t\n",
        "broken\t1\t<error: failed>\n",
    ]
    assert list(parse_signature_dump(lines)) == [
        NameCheck("add_comm", True, "add_comm {G : Type u_1}"),
        NameCheck("gone", False, ""),
        NameCheck("broken", True, ""),
    ]
