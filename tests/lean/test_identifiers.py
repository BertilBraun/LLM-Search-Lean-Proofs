import pytest

from lean_search.lean.identifiers import (
    EnvironmentNames,
    IdentifierChecker,
    NameRepairer,
    NameScope,
    UnknownNames,
    lean_unknown_names,
    name_scope,
    namespace_members,
    parse_environment_names,
    shared_name_repairer,
    tokenize,
    unknown_names,
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


REPAIRER = NameRepairer(namespace_members(NAMES), 0.85)


def test_unknown_names_reach_the_rejection() -> None:
    unknown = first_unknown("rw [Nat.succ_le_iff', Nat.foo]")
    assert unknown is not None and unknown.rejection.names == ("Nat.succ_le_iff'", "Nat.foo")


def test_close_name_of_the_same_namespace_replaces_an_unknown_one() -> None:
    assert REPAIRER.replacement("Nat.succ_le_iff'", SCOPE.namespaces) == "Nat.succ_le_iff"


def test_field_after_the_repaired_name_is_kept() -> None:
    assert REPAIRER.replacement("Nat.prime_twoo.le", SCOPE.namespaces) == "Nat.prime_two.le"


def test_namespace_opened_by_the_header_is_searched() -> None:
    assert REPAIRER.replacement("Prime.two_lee", SCOPE.namespaces) == "Prime.two_le"


def test_name_without_a_namespace_is_not_repaired() -> None:
    assert REPAIRER.replacement("add_comn", SCOPE.namespaces) is None


def test_name_far_from_every_constant_is_not_repaired() -> None:
    assert REPAIRER.replacement("Nat.log_mul", SCOPE.namespaces) is None


def test_repaired_block_replaces_every_occurrence() -> None:
    repaired = REPAIRER.repaired("rw [Nat.prime_twoo]\nexact Nat.prime_twoo", ("Nat.prime_twoo",), SCOPE.namespaces)
    assert repaired is not None and repaired.text == "rw [Nat.prime_two]\nexact Nat.prime_two"


def test_block_with_one_unrepairable_name_is_not_repaired() -> None:
    repaired = REPAIRER.repaired(
        "rw [Nat.prime_twoo, Nat.log_mul]", ("Nat.prime_twoo", "Nat.log_mul"), SCOPE.namespaces
    )
    assert repaired is None


def test_name_inside_a_comment_is_left_alone() -> None:
    repaired = REPAIRER.repaired("simp [Nat.prime_twoo] -- Nat.prime_twoo", ("Nat.prime_twoo",), SCOPE.namespaces)
    assert repaired is not None and repaired.text == "simp [Nat.prime_two] -- Nat.prime_twoo"


@pytest.mark.parametrize(
    ("message", "names"),
    [
        ("unknown identifier 'Finset.sum_Iio_succ'", ("Finset.sum_Iio_succ",)),
        ("unknown constant 'pow_le_pow_left''\nmore", ("pow_le_pow_left'",)),
        ("linarith failed to find a contradiction", ()),
    ],
)
def test_lean_messages_name_their_unknown_constants(message: str, names: tuple[str, ...]) -> None:
    assert lean_unknown_names(message) == names


def test_one_repairer_is_shared_per_environment_and_threshold() -> None:
    assert shared_name_repairer(NAMES, 0.85) is shared_name_repairer(NAMES, 0.85)


def test_repeated_lookup_gives_the_cached_replacement() -> None:
    repairer = NameRepairer(namespace_members(NAMES), 0.85)
    repairer.replacement("Nat.succ_le_iff'", SCOPE.namespaces)
    assert repairer.replacement("Nat.succ_le_iff'", SCOPE.namespaces) == "Nat.succ_le_iff"


@pytest.mark.parametrize(
    ("message", "names"),
    [
        (UnknownNames(0, ("Nat.foo'", "Nat.bar")).rejection.message, ("Nat.foo'", "Nat.bar")),
        ("unknown constant 'Nat.card_fin'\nunknown constant 'Nat.card_insert'", ("Nat.card_fin", "Nat.card_insert")),
    ],
)
def test_recorded_failures_name_their_unknown_names(message: str, names: tuple[str, ...]) -> None:
    assert unknown_names(message) == names
