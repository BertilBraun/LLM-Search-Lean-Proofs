import shutil
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from lean_search.lean import LeanRepl, LeanReplConfig, ProofState
from lean_search.lean.repl import PROJECT_DIRECTORY, REPL_BINARY
from lean_search.retrieval.annotation import Applicability, LemmaCheck, annotate, check_premise
from lean_search.retrieval.config import ApplicabilityConfig
from lean_search.retrieval.premises import RetrievedPremise

HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
PRODUCT = "theorem product_pos (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : 0 < a * b := by\n"
SQUARE = "theorem square_nonneg (x : ℝ) : 0 ≤ x ^ 2 := by\n"
PI = "theorem pi_positive : (0 : ℝ) < Real.pi := by\n"
TWO_GOALS = "theorem both (a b : ℝ) (ha : 0 < a) (hb : 0 < b) : 0 < a * b ∧ 0 < a := by\n  constructor\n"

lean_is_installed = (PROJECT_DIRECTORY / REPL_BINARY).exists() and shutil.which("lake") is not None
pytestmark = [
    pytest.mark.skipif(not lean_is_installed, reason="needs the Lean REPL (run on the node)"),
    pytest.mark.asyncio(loop_scope="module"),
]


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def repl() -> AsyncIterator[LeanRepl]:
    async with LeanRepl(LeanReplConfig()) as lean_repl:
        await lean_repl.load_header(HEADER)
        yield lean_repl


async def start(repl: LeanRepl, statement: str) -> ProofState:
    theorem, _, steps = statement.partition(":= by\n")
    root = (await repl.start_proof(theorem + ":= by\n", HEADER)).outcome
    assert isinstance(root, ProofState)
    for step in filter(None, (line.strip() for line in steps.splitlines())):
        root = (await repl.apply_tactic(root, step)).outcome
        assert isinstance(root, ProofState)
    return root


def premise(name: str) -> RetrievedPremise:
    return RetrievedPremise(name, f"{name} : True", 1.0)


@pytest.mark.parametrize(
    ("statement", "name", "check"),
    [
        (PI, "Real.pi_pos", LemmaCheck(Applicability.CLOSES, "exact", 0)),
        (SQUARE, "sq_nonneg", LemmaCheck(Applicability.CLOSES, "apply", 0)),
        (PRODUCT, "mul_pos", LemmaCheck(Applicability.LEAVES_GOALS, "apply", 2)),
        (PRODUCT, "mul_comm", LemmaCheck(Applicability.LEAVES_GOALS, "rw", 1)),
        (PRODUCT, "Nat.succ_ne_zero", LemmaCheck(Applicability.NO_MATCH)),
        (PRODUCT, "no_such_lemma_exists", LemmaCheck(Applicability.NO_MATCH)),
        (TWO_GOALS, "mul_pos", LemmaCheck(Applicability.LEAVES_GOALS, "apply", 2)),
    ],
)
async def test_premise_check_on_the_first_goal(repl: LeanRepl, statement: str, name: str, check: LemmaCheck) -> None:
    state = await start(repl, statement)
    assert (await check_premise(repl, state, premise(name), ApplicabilityConfig())).check == check


async def test_checking_stops_at_the_first_closing_tactic(repl: LeanRepl) -> None:
    state = await start(repl, PI)
    lemma = await check_premise(repl, state, premise("Real.pi_pos"), ApplicabilityConfig())
    assert [attempt.tactic for attempt in lemma.tries] == ["exact"]


async def test_annotation_keeps_every_premise_in_retrieval_order(repl: LeanRepl) -> None:
    state = await start(repl, PRODUCT)
    names = ["Nat.succ_ne_zero", "mul_comm", "mul_pos"]
    annotation = await annotate(repl, state, [premise(name) for name in names], ApplicabilityConfig())
    assert [lemma.premise.full_name for lemma in annotation.lemmas] == names


async def test_annotation_leaves_the_proof_state_usable(repl: LeanRepl) -> None:
    state = await start(repl, PRODUCT)
    await annotate(repl, state, [premise("mul_comm"), premise("mul_pos")], ApplicabilityConfig())
    result = await repl.apply_tactic(state, "positivity")
    assert isinstance(result.outcome, ProofState) and result.outcome.is_proved
