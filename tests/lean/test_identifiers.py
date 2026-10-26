import pytest

from lean_search.lean.identifiers import (
    EnvironmentNames,
    IdentifierChecker,
    NameScope,
    UnknownNames,
    name_scope,
    parse_environment_names,
    tokenize,
)

HEADER = (
    "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 400000\n\nopen BigOperators Real Nat Topology Rat\n\n"
)
STATEMENT = "theorem t (a b : ℕ) (h₀ : a = 2) : a + b = 2 + b := by\n"
GOALS = ("a b : ℕ\nh₀ : a = 2\n⊢ a + b = 2 + b",)
NAMES = parse_environment_names(
    "import Mathlib",
    [
        "constant\ttheorem\tadd_comm",
        "constant\ttheorem\tNat.succ_le_iff",
        "constant\ttheorem\tNat.prime_two",
        "constant\ttheorem\tNat.Prime.two_le",
        "constant\ttheorem\tReal.sqrt_nonneg",
        "constant\tdef\tNat.factorial",
        "constant\tinductive\tNat",
        "constant\tconstructor\tOr.inl",
        "constant\tdef\tFinset.range",
        "alias\tExported.name",
        "alias\ttrue",
        "constant\ttheorem\tNat.ModEq.refl",
        "token\t[MOD",
        "leading\ttactic\tcase",
        "constant\ttheorem\trfl",
        "token\thave",
        "leading\ttactic\trw",
        "leading\ttactic\trefine",
        "token\tat",
        "token\tℝ",
        "token\tfun",
        "leading\ttactic\tsimp",
        "leading\ttactic\tnlinarith",
        "leading\ttactic\tlinarith",
        "leading\ttactic\texact",
        "leading\ttactic\tintro",
        "leading\ttactic\tobtain",
        "leading\ttactic\trcases",
        "leading\ttactic\tsubst",
        "leading\ttactic\tby_cases",
        "leading\ttactic\tconv",
        "leading\ttactic\tinduction",
    ],
)
SCOPE = NameScope(("", "BigOperators", "Real", "Nat", "Topology", "Rat"), frozenset())


def first_unknown(*tactics: str, goals: tuple[str, ...] = GOALS) -> UnknownNames | None:
    return IdentifierChecker(NAMES).first_unknown(tactics, goals, SCOPE)


@pytest.mark.parametrize(
    ("tactics", "expected"),
    [
        (("simp only [h₀, h₂] at h₄",), UnknownNames(0, ("h₂", "h₄"))),
        (("subst h₀", "nlinarith [Nat.card_fin]"), UnknownNames(1, ("Nat.card_fin",))),
        (("exact sq_nonneg' a",), UnknownNames(0, ("sq_nonneg'",))),
        (("simp [a!]",), UnknownNames(0, ("a!",))),
        (("exact (fun k hk => |k|) (abs_mystery a)",), UnknownNames(0, ("abs_mystery",))),
    ],
)
def test_names_that_exist_nowhere_are_reported(tactics: tuple[str, ...], expected: UnknownNames) -> None:
    assert first_unknown(*tactics) == expected


@pytest.mark.parametrize(
    "tactics",
    [
        ("simp [h₀, add_comm]",),
        ("nlinarith [Nat.succ_le_iff, succ_le_iff, sqrt_nonneg a]",),
        ("exact Nat.prime_two.two_le",),
        ("simp [Nat.factorial.eq_1]",),
        ("exact h₀.symm",),
        ("intro x y\nexact x",),
        ("obtain ⟨x, hx⟩ := h₀", "exact hx"),
        ("rcases h₀ with ⟨x, hx⟩ | ⟨y, hy⟩\nexact hy",),
        ("have key : a = 2 := h₀", "exact key"),
        ("exact fun x hx => hx",),
        ("exact ∀ x ∈ Finset.range a, x = x",),
        ("exact Or.inl rfl",),
        ("exact Exported.name",),
        ("simp (config := { decide := true }) at h₀",),
        ("by_cases a = 2", "exact h"),
        ("induction b with\n| zero => simp\n| succ n ih => exact ih",),
        ("exact (h₀).symm.le",),
        ("exact this",),
        ("refine ⟨?_, ?left⟩",),
        ("rw [_root_.add_comm]",),
        ("conv => lhs; rw [mystery]",),
        ("exact «weird name»",),
        ("rw [x✝]",),
        ("try simp [mystery]",),
        ("all_goals exact mystery",),
        ("simp <;> exact mystery",),
        ("case h₁.a.a",),
        ("exact Nat.ModEq.refl a [MOD 3]",),
        ("exact Nat.factorial.mystery",),
    ],
)
def test_names_that_may_exist_are_accepted(tactics: tuple[str, ...]) -> None:
    assert first_unknown(*tactics) is None


def test_names_bound_later_in_the_block_do_not_cover_earlier_tactics() -> None:
    assert first_unknown("exact hx", "obtain ⟨x, hx⟩ := h₀") == UnknownNames(0, ("hx",))


def test_inaccessible_hypotheses_are_not_in_the_context() -> None:
    assert first_unknown("exact h", goals=("h✝ : True\n⊢ True",)) == UnknownNames(0, ("h",))


def test_tokenizer_joins_dotted_names_but_not_field_indices() -> None:
    assert [token.text for token in tokenize("exact h.1.le") if token.is_identifier] == ["exact", "h", "le"]


def test_name_scope_reads_the_opened_namespaces() -> None:
    assert name_scope(HEADER, STATEMENT) == NameScope(
        ("", "BigOperators", "Real", "Nat", "Topology", "Rat"), frozenset()
    )


def test_name_scope_adds_the_theorems_namespaces() -> None:
    scope = name_scope("import Mathlib\n", "theorem Foo.Bar.t : True := by\n")
    assert scope is not None and scope.namespaces == ("", "Foo", "Foo.Bar")


def test_name_scope_adds_header_declarations() -> None:
    scope = name_scope("import Mathlib\n\nnoncomputable def helper : ℕ := 7\n", STATEMENT)
    assert scope is not None and scope.declared == frozenset({"helper"})


@pytest.mark.parametrize(
    "header",
    [
        "import Mathlib\nnamespace Foo\n",
        'import Mathlib\nnotation "ψ" => 3\n',
        "import Mathlib\nopen Real hiding pi\n",
        "import Mathlib\nvariable (x : ℕ)\n",
    ],
)
def test_headers_the_check_does_not_model_disable_it(header: str) -> None:
    assert name_scope(header, STATEMENT) is None


def test_parsed_names_keep_the_inductive_types_apart() -> None:
    assert NAMES.types == frozenset({"Nat"})


def test_environment_names_hold_keywords_of_every_category() -> None:
    assert isinstance(NAMES, EnvironmentNames) and {"simp", "at", "ℝ"} <= NAMES.keywords
