from pathlib import Path

import pytest

from lean_search.corpora.records import (
    DataSplit,
    ProofRecord,
    TraceStatus,
    read_traced_proofs,
    read_traced_steps,
    write_jsonl,
)
from lean_search.corpora.tracing import (
    FOREIGN_HEADER_BATCH_SIZE,
    TracingLimits,
    TracingShard,
    assign_split,
    attempt_status,
    imports_nothing,
    is_parse_error,
    plan_batches,
    plan_shards,
    start_failure_trace,
    state_before,
    traced_steps,
)
from lean_search.lean import LeanError, LeanTimeout, ProofState, ReplFailure, ReplFailureKind

HEADER = "import Mathlib"
OTHER_HEADER = "import Mathlib\nopen Real"
STATEMENT = "theorem two_steps (a : ℕ) (h : a = 2) : a + 1 = 3 := by"
LIMITS = TracingLimits(heartbeats=200_000, timeout_seconds=20.0)


def record(source: str, number: int, header: str = HEADER) -> ProofRecord:
    return ProofRecord(
        source=source,
        identifier=f"{source}/0/{number}",
        statement_identifier=f"statement_{number}",
        header=header,
        formal_statement=STATEMENT,
        tactic_proof="subst h\nrfl",
        lean_version_hint="hint",
    )


def state(tactics: tuple[str, ...], goals: tuple[str, ...]) -> ProofState:
    return ProofState(HEADER, STATEMENT, tactics, goals, len(tactics), 1, (LIMITS.heartbeats,) * len(tactics))


RECORD = record("deepseek_prover_v1", 1)
ROOT = state((), ("a : ℕ\nh : a = 2\n⊢ a + 1 = 3",))
SUBSTITUTED = state(("subst h",), ("⊢ 2 + 1 = 3",))
PROVED = state(("subst h", "rfl"), ())
AFTER_NO_OP = state(("subst h", "rfl", "all_goals simp"), ())
STEPS = traced_steps(RECORD, DataSplit.TRAIN, (ROOT, SUBSTITUTED, PROVED), (0.1, 0.2))


def test_remaining_steps_count_down_to_one_at_the_last_step() -> None:
    assert [step.remaining_steps for step in STEPS] == [2, 1]


def test_every_step_records_the_total_step_count() -> None:
    assert {step.total_steps for step in STEPS} == {2}


def test_step_records_the_goals_before_and_after() -> None:
    assert (STEPS[1].goals_before, STEPS[1].goals_after) == (SUBSTITUTED.goals, ())


def test_step_text_is_the_executed_tactic() -> None:
    assert [step.step for step in STEPS] == ["subst h", "rfl"]


def test_step_records_the_steps_before_it() -> None:
    assert STEPS[1].previous_steps == ("subst h",)


def test_steps_after_the_goals_are_closed_are_dropped() -> None:
    steps = traced_steps(RECORD, DataSplit.TRAIN, (ROOT, SUBSTITUTED, PROVED, AFTER_NO_OP), (0.1, 0.2, 0.3))
    assert [step.remaining_steps for step in steps] == [2, 1]


def test_state_before_rebuilds_the_path_of_the_state() -> None:
    rebuilt = state_before(STEPS[1])
    assert (rebuilt.tactics, rebuilt.goals, rebuilt.tactic_heartbeats) == (
        SUBSTITUTED.tactics,
        SUBSTITUTED.goals,
        SUBSTITUTED.tactic_heartbeats,
    )


def test_renamed_copies_of_a_validation_statement_are_validation() -> None:
    template = "theorem {name} (x : ℕ) : x + {number} = {number} + x := by"
    number = next(
        number
        for number in range(10_000)
        if assign_split(template.format(name="first", number=number)) is DataSplit.VALIDATION
    )
    assert assign_split(template.format(name="second", number=number)) is DataSplit.VALIDATION


def test_about_two_percent_of_statements_are_validation() -> None:
    splits = [assign_split(f"theorem t (x : ℕ) : x + {number} = {number} + x := by") for number in range(20_000)]
    assert 0.015 < splits.count(DataSplit.VALIDATION) / len(splits) < 0.025


@pytest.mark.parametrize(
    ("failure", "last_state", "status"),
    [
        (None, PROVED, TraceStatus.COMPLETE),
        (None, SUBSTITUTED, TraceStatus.GOALS_REMAINING),
        (LeanError("no goals to be solved"), PROVED, TraceStatus.CLOSED_EARLY),
        (LeanError("linarith failed to find a contradiction"), SUBSTITUTED, TraceStatus.STEP_ERROR),
        (LeanTimeout("(deterministic) timeout", wall_clock=False), SUBSTITUTED, TraceStatus.TIMEOUT),
        (ReplFailure(ReplFailureKind.CRASHED, "died"), SUBSTITUTED, TraceStatus.REPL_FAILURE),
    ],
)
def test_attempt_status(
    failure: LeanError | LeanTimeout | ReplFailure | None, last_state: ProofState, status: TraceStatus
) -> None:
    assert attempt_status(failure, last_state) is status


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (LeanError("<input>:2:31: unexpected end of input"), True),
        (LeanError("<input>:2:2: expected '{' or tactic"), True),
        (LeanError("linarith failed to find a contradiction"), False),
        (LeanTimeout("<input>:1:1: (deterministic) timeout", wall_clock=False), False),
        (None, False),
    ],
)
def test_is_parse_error(failure: LeanError | LeanTimeout | None, expected: bool) -> None:
    assert is_parse_error(failure) is expected


@pytest.mark.parametrize(
    ("failure", "status"),
    [
        (LeanError("unknown identifier 'x'"), TraceStatus.START_FAILURE),
        (ReplFailure(ReplFailureKind.RESTART_FAILED, "no process"), TraceStatus.REPL_FAILURE),
    ],
)
def test_start_failure_status(failure: LeanError | ReplFailure, status: TraceStatus) -> None:
    assert start_failure_trace(RECORD, failure, 0.5, LIMITS).proof.status is status


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("", True),
        ("set_option maxHeartbeats 500000", True),
        ("import Mathlib", False),
        ("import Mathlib\nopen Real", False),
    ],
)
def test_imports_nothing(header: str, expected: bool) -> None:
    assert imports_nothing(header) is expected


def test_start_failure_yields_no_training_steps() -> None:
    assert start_failure_trace(RECORD, LeanError("unknown identifier 'x'"), 0.5, LIMITS).steps == ()


def test_traced_steps_round_trip_through_json_lines(tmp_path: Path) -> None:
    write_jsonl(tmp_path / "steps.jsonl", STEPS)
    assert tuple(read_traced_steps(tmp_path / "steps.jsonl")) == STEPS


def test_traced_proofs_round_trip_through_json_lines(tmp_path: Path) -> None:
    proof = start_failure_trace(RECORD, LeanError("unknown identifier 'x'"), 0.5, LIMITS).proof
    write_jsonl(tmp_path / "proofs.jsonl", [proof])
    assert list(read_traced_proofs(tmp_path / "proofs.jsonl")) == [proof]


SELECTION = [
    *(record("stp_conjectures", number) for number in range(3)),
    *(record("deepseek_prover_v1", number) for number in range(5)),
    *(record("goedel_lean_workbook_proofs", number) for number in range(2)),
    *(record("goedel_lean_workbook_proofs", number, OTHER_HEADER) for number in range(2, 10)),
]
SHARDS = plan_shards(SELECTION, pilot_size=2, shard_size=3)


def test_plan_excludes_stp_conjectures() -> None:
    assert "stp_conjectures" not in {shard.source for shard in SHARDS}


def test_plan_follows_the_trace_order() -> None:
    assert list(dict.fromkeys(shard.source for shard in SHARDS)) == [
        "goedel_lean_workbook_proofs",
        "deepseek_prover_v1",
    ]


def test_plan_puts_pilot_size_proofs_of_each_source_in_the_pilot() -> None:
    pilot_proofs = [len(shard.records) for shard in SHARDS if shard.name.startswith("pilot")]
    assert pilot_proofs == [2, 2]


def test_plan_respects_the_shard_size() -> None:
    assert max(len(shard.records) for shard in SHARDS) == 3


def test_plan_keeps_every_proof_of_the_traced_sources() -> None:
    assert sum(len(shard.records) for shard in SHARDS) == 15


def test_main_shards_start_with_the_most_frequent_header() -> None:
    first_main = next(shard for shard in SHARDS if shard.name == "main_0000")
    assert first_main.records[0].header == OTHER_HEADER


def test_unknown_source_is_rejected() -> None:
    with pytest.raises(ValueError, match="tracing position"):
        plan_shards([record("unknown_source", 0)], pilot_size=1, shard_size=1)


MIXED_SHARD = TracingShard(
    "goedel_lean_workbook_proofs",
    "main_0000",
    (
        *(record("goedel_lean_workbook_proofs", number) for number in range(3)),
        *(
            record("goedel_lean_workbook_proofs", number, OTHER_HEADER)
            for number in range(3, 4 + FOREIGN_HEADER_BATCH_SIZE)
        ),
    ),
)


def test_preloaded_header_proofs_are_traced_one_per_batch() -> None:
    batches = plan_batches(MIXED_SHARD, preloaded_header=HEADER)
    assert [len(batch.records) for batch in batches if batch.header == HEADER] == [1, 1, 1]


def test_foreign_header_proofs_share_batches_up_to_the_cap() -> None:
    batches = plan_batches(MIXED_SHARD, preloaded_header=HEADER)
    assert [len(batch.records) for batch in batches if batch.header == OTHER_HEADER] == [FOREIGN_HEADER_BATCH_SIZE, 1]
