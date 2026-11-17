"""The offline arm's probe run against other runs at equal expansions (experiments/offline_arm.py report).

A run that searched with more expansions counts a statement solved only when its first proof took at most the budget
(`within_budget`), so a token-capped run (step 1's run 4, up to 237 expansions) compares with a 16-expansion one. The
owner's gate: the offline arm passes when the paired 95% interval of its solved share minus run 8's (v35 with value v0)
lies above 0. Runs of different search settings (reasoning, depth weight, wall cap) compare descriptively only.
"""

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from lean_search.rl.arm_comparison import (
    Arm,
    ArmRun,
    Difference,
    common_problems,
    difference,
    pooled,
    run_outcomes,
)
from lean_search.rl.fixed_sets import stratum_order


def within_budget(run: ArmRun, budget: int) -> ArmRun:
    """The run as if every search had stopped after `budget` expansions."""
    outcomes = tuple(
        dataclasses.replace(outcome, proved=False, expansions_to_proof=None)
        if outcome.expansions_to_proof is None or outcome.expansions_to_proof > budget
        else outcome
        for outcome in run.outcomes
    )
    return dataclasses.replace(run, outcomes=outcomes)


def arm_within_budget(arm: Arm, budget: int) -> Arm:
    return Arm(arm.label, tuple(within_budget(run, budget) for run in arm.runs))


@dataclass(frozen=True)
class PairedDifference:
    x: str
    y: str
    budget: int
    overall: Difference
    # Per probe band, in band order.
    strata: tuple[tuple[str, Difference], ...]


def paired_difference(x: Arm, y: Arm, budget: int, seed: int) -> PairedDifference:
    """x minus y on the statements every run searched, each run cut at `budget` expansions, runs of one side pooled
    per statement; the interval as `arm_comparison` stratifies it."""
    x, y = arm_within_budget(x, budget), arm_within_budget(y, budget)
    problems = common_problems([x, y])
    if not problems:
        raise ValueError(f"{x.label} and {y.label} share no searched statement.")
    strata = np.array([outcome.stratum for outcome in run_outcomes(x.runs[0], problems)])
    x_pooled, y_pooled = pooled(x, problems), pooled(y, problems)
    overall = difference(x_pooled, y_pooled, strata, seed)
    by_stratum = tuple(
        (stratum, difference(x_pooled, y_pooled, strata, seed, strata == stratum))
        for stratum in sorted(set(strata.tolist()), key=stratum_order)
    )
    return PairedDifference(x.label, y.label, budget, overall, by_stratum)


def passes_gate(found: PairedDifference) -> bool:
    return found.overall.lower > 0


def difference_text(found: Difference) -> str:
    return f"{100 * found.difference:+.1f} points (95% {100 * found.lower:+.1f} to {100 * found.upper:+.1f})"


def comparison_lines(found: PairedDifference) -> list[str]:
    overall = found.overall
    lines = [
        f"{found.x} minus {found.y}, solved within {found.budget} expansions, {overall.statements} statements: "
        f"{100 * overall.x_solved:.1f}% against {100 * overall.y_solved:.1f}%, {difference_text(overall)}",
        "",
        "| Band | Statements | " + found.x + " | " + found.y + " | Difference (95%) |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {stratum} | {part.statements} | {100 * part.x_solved:.1f}% | {100 * part.y_solved:.1f}% | "
        f"{difference_text(part)} |"
        for stratum, part in found.strata
    ]
    return lines


def gate_report(gate: PairedDifference, descriptive: Sequence[PairedDifference]) -> str:
    verdict = "PASSES" if passes_gate(gate) else "does not pass"
    sections = [
        [
            f"## Gate: {gate.x} against {gate.y} at equal expansions",
            "",
            f"The offline arm {verdict} the owner's gate (the paired 95% interval of {gate.x} minus {gate.y} lies "
            "above 0). The runs differ in their search settings (reasoning, depth weight, wall cap), so the "
            "comparison rule of arm_comparison gives no verdict; the gate is the owner's.",
            "",
            *comparison_lines(gate),
        ]
    ]
    for found in descriptive:
        sections.append(
            [
                f"## Descriptive: {found.x} against {found.y} within {found.budget} expansions",
                "",
                "Other search settings (reasoning, depth weight, token cap or wall cap): the numbers only, no verdict.",
                "",
                *comparison_lines(found),
            ]
        )
    return "\n\n".join("\n".join(section) for section in sections) + "\n"
