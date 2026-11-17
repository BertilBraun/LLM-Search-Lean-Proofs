"""Measurement: bounded variants of `nlinarith` against the policy's own calls. `nlinarith` adds, after linarith's
preprocessing, a proof of `0 ≤ t²` for every square subterm and the product of every pair of comparisons (hypotheses,
hint terms, the negated goal, those squares), so its linear program grows quadratically with the comparisons. Each
variant keeps linarith, its simplex oracle and the squares, and multiplies fewer pairs:

- `full`: every pair, as `nlinarith` (a check that the reimplementation matches it);
- `linear`: no products;
- `goal_hints`: pairs with the negated goal or a hint term as a factor;
- `degree`: pairs whose product has polynomial degree at most max(2, the negated goal's degree);
- `cap8`: the pairs among the first 8 comparisons ranked negated goal, hint terms, hypotheses, squares.

A variant's proof is its own text (`lean_search_nlinarith <variant> [hints]`, defined in VARIANT_DEFINITIONS): the
kernel checks the term it builds like any other, so a proof found by one verifies wherever the definitions are in the
environment. Its products are a subset of nlinarith's, so plain `nlinarith [hints]` has a certificate too, but may take
longer to find it.

    deployment/background.sh python experiments/analysis/nlinarith_variants.py \
        --run /workspace/runs/probe_evaluations/probe_step1_run4_no_reasoning_T \
        --steps <lean_overhead.py output>/steps.jsonl.gz --probe-set /workspace/data/grpo/fixed_sets/probe_v2.jsonl \
        --output /workspace/runs/search_efficiency/nlinarith --processes 32

Jobs: the policy's single `nlinarith [...]` tactics of the run (plain form: no `!`, config or `only`), drawn per
stratum of comparisons (hint terms + comparison hypotheses + negated goal, as lean_overhead.py counts them) and
recorded outcome. Each job rebuilds the tactic's state in a fresh REPL whose base environment has the variant
definitions, then runs the original text and every variant in a seeded random order, each at the search's 50k
heartbeats and 60 s wall clock. Writes jobs.jsonl, records.jsonl (resumable) and summary.md; --summary-only rebuilds
the summary.
"""

import argparse
import asyncio
import collections
import dataclasses
import gzip
import json
import random
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lean_search.lean import LeanError, LeanRepl, LeanReplConfig, LeanTimeout, ProofState, ReplFailure
from lean_search.lean import repl as repl_module
from lean_search.lean.hypotheses import has_inaccessible_names, renaming_tactic
from lean_search.lean.plans import TacticPlan, plain_plan, plan_block
from lean_search.lean.text import normalize_goal
from lean_search.search import StepSource, TreeRecord, read_tree

POLICY_HEARTBEATS = 50_000
BUILD_HEARTBEATS = 200_000
BUILD_TIMEOUT_SECONDS = 120.0
SAMPLE_INTERVAL_SECONDS = 0.25
BUCKETS = ((0, 6), (7, 12), (13, 16), (17, 1_000_000))
OUTCOMES = ("success", "error", "heartbeat_timeout", "wall_clock_timeout")
VARIANTS = ("full", "linear", "goal_hints", "degree", "cap8")
ORIGINAL = "original"
# The tactic succeeded: it closed every goal, or the goal it ran on while others stay open (a block step).
SUCCESSES = frozenset({"success", "open_goals"})
_PLAIN_NLINARITH = re.compile(r"nlinarith(?P<hints>\s*\[.*\])?\s*", re.DOTALL)

VARIANT_DEFINITIONS = """
open Lean Elab Tactic Meta Linarith in
partial def leanSearchDegree (e : Expr) : Nat :=
  match e.numeral? with
  | some _ => 0
  | none =>
    match e.getAppFnArgs with
    | (``HAdd.hAdd, #[_, _, _, _, a, b]) => max (leanSearchDegree a) (leanSearchDegree b)
    | (``HSub.hSub, #[_, _, _, _, a, b]) => max (leanSearchDegree a) (leanSearchDegree b)
    | (``HMul.hMul, #[_, _, _, _, a, b]) => leanSearchDegree a + leanSearchDegree b
    | (``HDiv.hDiv, #[_, _, _, _, a, b]) => leanSearchDegree a + leanSearchDegree b
    | (``HPow.hPow, #[_, _, _, _, a, n]) => n.numeral?.getD 1 * leanSearchDegree a
    | (``Neg.neg, #[_, _, a]) => leanSearchDegree a
    | _ => 1

open Lean Elab Tactic Meta Linarith in
def leanSearchProduct (first : Ineq × Expr) (second : Ineq × Expr) : MetaM Expr :=
  match first, second with
  | (Ineq.eq, a), (_, b) => mkAppM ``Linarith.zero_mul_eq #[a, b]
  | (_, a), (Ineq.eq, b) => mkAppM ``Linarith.mul_zero_eq #[a, b]
  | (Ineq.lt, a), (Ineq.lt, b) => mkAppM ``mul_pos_of_neg_of_neg #[a, b]
  | (Ineq.lt, a), (Ineq.le, b) => do
      let a ← mkAppM ``le_of_lt #[a]
      mkAppM ``mul_nonneg_of_nonpos_of_nonpos #[a, b]
  | (Ineq.le, a), (Ineq.lt, b) => do
      let b ← mkAppM ``le_of_lt #[b]
      mkAppM ``mul_nonneg_of_nonpos_of_nonpos #[a, b]
  | (Ineq.le, a), (Ineq.le, b) => mkAppM ``mul_nonneg_of_nonpos_of_nonpos #[a, b]

open Lean Elab Tactic Meta Linarith in
def leanSearchTryProduct (first : Ineq × Expr) (second : Ineq × Expr) : MetaM (Option Expr) := do
  try
    return some (← leanSearchProduct first second)
  catch _ =>
    return none

open Lean Elab Tactic Meta Linarith in
def leanSearchParse (proof : Expr) : MetaM (Ineq × Nat) := do
  try
    let (strength, term) ← parseCompAndExpr (← inferType proof)
    return (strength, leanSearchDegree term)
  catch _ =>
    return (Ineq.lt, 1)

structure LeanSearchComparison where
  strength : Linarith.Ineq
  proof : Lean.Expr
  degree : Nat
  rank : Nat
  deriving Inhabited

open Lean Elab Tactic Meta Linarith in
def leanSearchProducts (variant : Name) (hints : List Expr) : GlobalPreprocessor where
  name := "lean_search bounded products"
  transform ls := do
    let squares ← ls.foldrM (fun h s => do findSquares s (← instantiateMVars (← inferType h))) Lean.HashSet.empty
    let squareProofs ← squares.foldM (fun proofs (⟨e, isSquare⟩ : Expr × Bool) =>
      ((do
        let p ← mkAppM (if isSquare then ``sq_nonneg else ``mul_self_nonneg) #[e]
        pure (p :: proofs)) <|> pure proofs)) ([] : List Expr)
    let squareProofs ← compWithZero.globalize.transform squareProofs
    let goal? := (← getLCtx).lastDecl.map (·.fvarId)
    let mut comparisons : Array LeanSearchComparison := #[]
    for (proof, index) in (squareProofs ++ ls).zip (List.range (squareProofs.length + ls.length)) do
      let (strength, degree) ← leanSearchParse proof
      let isGoal := goal?.any proof.containsFVar
      let isHint := hints.any (·.occurs proof)
      let group := if isGoal then 0 else if isHint then 1 else if index < squareProofs.length then 3 else 2
      comparisons := comparisons.push ⟨strength, proof, degree, group * 100000 + index⟩
    let goalDegree := comparisons.foldl (fun d c => if c.rank < 100000 then max d c.degree else d) 2
    let ranks := (comparisons.map (·.rank)).qsort (· < ·)
    let capRank := if ranks.size ≥ 8 then ranks[7]! else 1000000000
    let keep (a b : LeanSearchComparison) : Bool :=
      match variant with
      | `full => true
      | `linear => false
      | `goal_hints => a.rank < 200000 || b.rank < 200000
      | `degree => a.degree + b.degree ≤ goalDegree
      | `cap8 => a.rank ≤ capRank && b.rank ≤ capRank
      | _ => false
    let mut products : Array Expr := #[]
    for i in [:comparisons.size] do
      for j in [i:comparisons.size] do
        let a := comparisons[i]!
        let b := comparisons[j]!
        if keep a b then
          if let some product ← leanSearchTryProduct (a.strength, a.proof) (b.strength, b.proof) then
            products := products.push product
    let productProofs ← compWithZero.globalize.transform products.toList
    return squareProofs ++ ls ++ productProofs

syntax (name := leanSearchNlinarith) "lean_search_nlinarith " ident (" [" term,* "]")? : tactic

open Lean Elab Tactic Meta Linarith in
elab_rules : tactic
  | `(tactic| lean_search_nlinarith $variant:ident $[[$args,*]]?) => withMainContext do
    let args ← ((args.map (Syntax.TSepArray.getElems)).getD {}).mapM (elabLinarithArg `nlinarith)
    let extras : GlobalBranchingPreprocessor := leanSearchProducts variant.getId args.toList
    let config : LinarithConfig := { preprocessors := some (defaultPreprocessors ++ [extras]) }
    commitIfNoEx do liftMetaFinishingTactic <| Linarith.linarith false args.toList config
"""


@dataclass(frozen=True)
class Job:
    problem_name: str
    edge_id: int
    parent_id: int
    tactic_index: int
    text: str
    comparisons: int
    bucket: str
    recorded_outcome: str
    recorded_seconds: float
    net_seconds: float


@dataclass(frozen=True)
class Run:
    variant: str
    outcome: str
    wall_seconds: float
    cpu_seconds: float
    message: str


@dataclass(frozen=True)
class Measurement:
    job: Job
    state_built: bool
    runs: tuple[Run, ...]


@dataclass(frozen=True)
class Population:
    """Policy nlinarith steps of the run per (bucket, recorded outcome), and their net Lean seconds."""

    counts: dict[tuple[str, str], int]
    seconds: dict[tuple[str, str], float]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--steps", type=Path, required=True)
    parser.add_argument("--probe-set", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--processes", type=int, default=32)
    parser.add_argument("--per-stratum", default="success=30,error=20,heartbeat_timeout=13,wall_clock_timeout=12")
    parser.add_argument("--cap-seconds", type=float, default=60.0)
    parser.add_argument("--seed", type=int, default=20261117)
    parser.add_argument("--summary-only", action="store_true")
    return parser.parse_args()


def bucket_name(comparisons: int) -> str:
    for low, high in BUCKETS:
        if low <= comparisons <= high:
            return f"{low}+" if high >= 1_000_000 else f"{low}-{high}"
    raise AssertionError(comparisons)


def plain_hints(text: str) -> str | None:
    """The hint list (with its brackets, or empty) of a plain `nlinarith [...]` tactic, else None."""
    match = _PLAIN_NLINARITH.fullmatch(text.strip())
    if match is None:
        return None
    hints = (match["hints"] or "").strip()
    depth = 0
    for position, character in enumerate(hints):
        depth += (character in "([{⟨") - (character in ")]}⟩")
        if depth == 0 and position < len(hints) - 1:
            return None
    return hints


def variant_text(variant: str, original: str) -> str:
    if variant == ORIGINAL:
        return original
    hints = plain_hints(original)
    assert hints is not None
    return f"lean_search_nlinarith {variant} {hints}".rstrip()


def read_population(steps: Path) -> tuple[Population, dict[tuple[str, str], list[dict[str, object]]]]:
    counts: collections.Counter[tuple[str, str]] = collections.Counter()
    seconds: collections.Counter[tuple[str, str]] = collections.Counter()
    rows: dict[tuple[str, str], list[dict[str, object]]] = collections.defaultdict(list)
    with gzip.open(steps, "rt", encoding="utf-8") as lines:
        for line in lines:
            row = json.loads(line)
            if row["source"] != "policy" or row["tactic_name"] != "nlinarith" or row["outcome"] not in OUTCOMES:
                continue
            key = (bucket_name(row["comparisons"]), row["outcome"])
            counts[key] += 1
            seconds[key] += max(0.0, row["recorded_seconds"] - row["replay_seconds"] - row["restart_seconds"])
            rows[key].append(row)
    return Population(dict(counts), dict(seconds)), rows


def select_jobs(
    arguments: argparse.Namespace, rows: dict[tuple[str, str], list[dict[str, object]]], names: set[str]
) -> tuple[list[Job], dict[str, TreeRecord]]:
    quotas = {outcome: int(count) for outcome, count in (item.split("=") for item in arguments.per_stratum.split(","))}
    generator = random.Random(arguments.seed)
    trees: dict[str, TreeRecord] = {}
    jobs: list[Job] = []
    for key in sorted(rows):
        candidates = [row for row in rows[key] if row["problem_name"] in names]
        generator.shuffle(candidates)
        chosen = 0
        for row in candidates:
            if chosen >= quotas[key[1]]:
                break
            name = str(row["problem_name"])
            if name not in trees:
                trees[name] = read_tree(arguments.run / "trees" / f"{name}.json.gz", texts=False)
            edge = trees[name].edges[int(row["edge_id"])]
            text = edge.executed_tactics[int(row["tactic_index"])].text
            if plain_hints(text) is None:
                continue
            net = max(
                0.0, float(row["recorded_seconds"]) - float(row["replay_seconds"]) - float(row["restart_seconds"])
            )
            jobs.append(
                Job(
                    name,
                    int(row["edge_id"]),
                    int(row["parent_id"]),
                    int(row["tactic_index"]),
                    text.strip(),
                    int(row["comparisons"]),
                    key[0],
                    key[1],
                    float(row["recorded_seconds"]),
                    net,
                )
            )
            chosen += 1
    print(f"{len(jobs)} jobs from {len(trees)} trees", flush=True)
    return jobs, trees


def process_cpu_seconds(process_id: int) -> float | None:
    try:
        fields = Path(f"/proc/{process_id}/stat").read_text().rsplit(")", 1)[1].split()
    except OSError:
        return None
    return (int(fields[11]) + int(fields[12])) / 100


def same_goals(state: ProofState, goals: Sequence[str]) -> bool:
    return [normalize_goal(goal) for goal in state.goals] == [normalize_goal(goal) for goal in goals]


def step_plan(source: StepSource, text: str) -> TacticPlan:
    return plain_plan(text) if source == StepSource.AUTOMATION else plan_block(text, flatten=True)


async def named(repl: LeanRepl, state: ProofState) -> ProofState:
    tactic = renaming_tactic(state.goals)
    if tactic is None:
        return state
    result = await repl.apply_tactic(state, tactic)
    match result.outcome:
        case ProofState() as renamed if not has_inaccessible_names(renamed.goals):
            return renamed
        case _:
            return state


async def node_state(repl: LeanRepl, record: TreeRecord, header: str, node_id: int) -> ProofState | None:
    path = [node_id]
    while (parent := record.nodes[path[-1]].parent_id) is not None:
        path.append(parent)
    start = await repl.start_proof(record.statement, header)
    if not isinstance(start.outcome, ProofState):
        return None
    state = await named(repl, start.outcome)
    for step_node_id in reversed(path[:-1]):
        node = record.nodes[step_node_id]
        assert node.step is not None and node.source is not None
        result = await repl.apply_block(
            state, step_plan(node.source, node.step), BUILD_HEARTBEATS, BUILD_TIMEOUT_SECONDS
        )
        if result.failure is not None and not result.applied_tactics:
            return None
        state = result.state if result.state.is_proved else await named(repl, result.state)
    return state if same_goals(state, record.nodes[node_id].goals) else None


async def tactic_state(repl: LeanRepl, record: TreeRecord, header: str, job: Job) -> ProofState | None:
    state = await node_state(repl, record, header, job.parent_id)
    if state is None:
        return None
    edge = record.edges[job.edge_id]
    for piece in edge.executed_tactics[: job.tactic_index]:
        result = await repl.apply_tactic(state, piece.text, BUILD_HEARTBEATS, BUILD_TIMEOUT_SECONDS)
        if not isinstance(result.outcome, ProofState):
            return None
        state = result.outcome
    expected = record.nodes[job.parent_id].goals if job.tactic_index == 0 else edge.tactic_goals[job.tactic_index - 1]
    return state if same_goals(state, expected) else None


def outcome_name(outcome: object) -> str:
    match outcome:
        case ProofState(goals=()):
            return "success"
        case ProofState():
            return "open_goals"
        case LeanTimeout(wall_clock=True):
            return "wall_clock_timeout"
        case LeanTimeout():
            return "heartbeat_timeout"
        case LeanError(panic=True):
            return "panic"
        case LeanError():
            return "error"
        case ReplFailure():
            return "repl_failure"
        case _:
            raise AssertionError(outcome)


def first_line(outcome: object) -> str:
    match outcome:
        case LeanError(message=message) | LeanTimeout(message=message) | ReplFailure(message=message):
            return message.split("\n")[0][:200]
        case _:
            return ""


async def timed_run(repl: LeanRepl, state: ProofState, variant: str, text: str, cap_seconds: float) -> Run:
    """The variant's outcome, wall seconds and the process's CPU seconds (up to its kill, if it was killed)."""
    await repl.apply_tactic(state, "skip", BUILD_HEARTBEATS, BUILD_TIMEOUT_SECONDS)
    process_id = repl.process_id
    assert process_id is not None
    restarts_before = repl.restart_count
    cpu_before = process_cpu_seconds(process_id) or 0.0
    last_cpu = cpu_before
    started = time.monotonic()
    task = asyncio.ensure_future(repl.apply_tactic(state, text, POLICY_HEARTBEATS, cap_seconds))
    while not task.done():
        await asyncio.wait({task}, timeout=SAMPLE_INTERVAL_SECONDS)
        if repl.restart_count == restarts_before and (sampled := process_cpu_seconds(process_id)) is not None:
            last_cpu = sampled
    result = task.result()
    wall = time.monotonic() - started
    if repl.restart_count == restarts_before and (sampled := process_cpu_seconds(process_id)) is not None:
        last_cpu = sampled
    return Run(variant, outcome_name(result.outcome), wall, last_cpu - cpu_before, first_line(result.outcome))


async def measure(job: Job, record: TreeRecord, header: str, config: LeanReplConfig, seed: int) -> Measurement:
    order = [ORIGINAL, *VARIANTS]
    random.Random(f"{seed}:{job.problem_name}:{job.edge_id}").shuffle(order)
    async with LeanRepl(config) as repl:
        state = await tactic_state(repl, record, header, job)
        if state is None:
            return Measurement(job, False, ())
        runs = [
            await timed_run(repl, state, variant, variant_text(variant, job.text), config.tactic_timeout_seconds)
            for variant in order
        ]
    return Measurement(job, True, tuple(sorted(runs, key=lambda run: [ORIGINAL, *VARIANTS].index(run.variant))))


def job_key(job: Job) -> tuple[str, int, int]:
    return (job.problem_name, job.edge_id, job.tactic_index)


async def run_all(
    jobs: list[Job], trees: dict[str, TreeRecord], headers: dict[str, str], arguments: argparse.Namespace
) -> None:
    config = LeanReplConfig(
        tactic_timeout_seconds=arguments.cap_seconds,
        replay_timeout_seconds=max(arguments.cap_seconds, BUILD_TIMEOUT_SECONDS),
        forbidden_tokens=frozenset(),
    )
    semaphore = asyncio.Semaphore(arguments.processes)
    output = arguments.output / "records.jsonl"
    done = {job_key(measurement.job) for measurement in read_measurements(output)} if output.exists() else set()
    remaining = [job for job in jobs if job_key(job) not in done]
    print(f"{len(remaining)} jobs to run ({len(done)} done)", flush=True)

    async def one(job: Job) -> None:
        async with semaphore:
            try:
                measurement = await measure(
                    job, trees[job.problem_name], headers[job.problem_name], config, arguments.seed
                )
            except Exception as error:  # noqa: BLE001 - a measurement records what broke and goes on
                measurement = Measurement(job, False, (Run("exception", "exception", 0.0, 0.0, repr(error)[:200]),))
            with output.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(dataclasses.asdict(measurement), ensure_ascii=False) + "\n")
            line = ", ".join(f"{run.variant}:{run.outcome} {run.cpu_seconds:.1f}s" for run in measurement.runs)
            print(f"{job.bucket} {job.recorded_outcome} {job.problem_name} edge {job.edge_id}: {line}", flush=True)

    await asyncio.gather(*(one(job) for job in remaining))


def read_measurements(path: Path) -> list[Measurement]:
    measurements = []
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        runs = tuple(Run(**run) for run in row["runs"])
        measurements.append(Measurement(Job(**row["job"]), row["state_built"], runs))
    return measurements


@dataclass
class Tally:
    jobs: int = 0
    seconds: float = 0.0
    successes: int = 0
    kept: int = 0
    lost: int = 0
    gained: int = 0
    wall_clock_timeouts: int = 0


def tallies(measurements: Sequence[Measurement]) -> dict[tuple[str, str], dict[str, Tally]]:
    """Per stratum and variant; successes kept, lost and gained against the original text's own re-run."""
    result: dict[tuple[str, str], dict[str, Tally]] = collections.defaultdict(lambda: collections.defaultdict(Tally))
    for measurement in measurements:
        if not measurement.state_built:
            continue
        runs = {run.variant: run for run in measurement.runs}
        original = runs[ORIGINAL].outcome in SUCCESSES
        key = (measurement.job.bucket, measurement.job.recorded_outcome)
        for variant, run in runs.items():
            tally = result[key][variant]
            success = run.outcome in SUCCESSES
            tally.jobs += 1
            tally.seconds += run.wall_seconds
            tally.successes += success
            tally.kept += success and original
            tally.lost += original and not success
            tally.gained += success and not original
            tally.wall_clock_timeouts += run.outcome == "wall_clock_timeout"
    return result


def summary(measurements: Sequence[Measurement], population: Population | None) -> str:
    built = [measurement for measurement in measurements if measurement.state_built]
    lines = [
        "# Bounded nlinarith variants",
        "",
        f"{len(measurements)} jobs, {len(built)} with their state rebuilt. Each cell: successes (kept / lost / gained "
        "against the original text re-run here) and mean wall seconds per call (a wall-clock stop includes its "
        "restart).",
        "",
    ]
    table = tallies(measurements)
    variants = [ORIGINAL, *VARIANTS]
    lines += [
        "| comparisons | recorded | n | " + " | ".join(variants) + " |",
        "|---|---|---|" + "---|" * len(variants),
    ]
    for key in sorted(
        table, key=lambda key: ([bucket_name(low) for low, _ in BUCKETS].index(key[0]), OUTCOMES.index(key[1]))
    ):
        cells = []
        for variant in variants:
            tally = table[key][variant]
            mean = tally.seconds / max(tally.jobs, 1)
            if variant == ORIGINAL:
                cells.append(f"{tally.successes} / {mean:.1f}s")
            else:
                cells.append(f"{tally.successes} ({tally.kept}/{tally.lost}/{tally.gained}) / {mean:.1f}s")
        lines.append(f"| {key[0]} | {key[1]} | {table[key][ORIGINAL].jobs} | " + " | ".join(cells) + " |")
    if population is not None:
        lines += ["", *weighted_lines(table, population, variants)]
    return "\n".join(lines) + "\n"


def weighted_lines(
    table: dict[tuple[str, str], dict[str, Tally]], population: Population, variants: list[str]
) -> list[str]:
    """Scaled to the run's policy nlinarith calls: each stratum's mean seconds and success rate times its count."""
    lines = [
        "## Scaled to the run's policy nlinarith calls (strata weighted by their counts)",
        "",
        "| variant | hours | of the original's | successes | kept | lost | gained |",
        "|---|---|---|---|---|---|---|",
    ]
    totals: dict[str, list[float]] = {variant: [0.0, 0.0, 0.0, 0.0, 0.0] for variant in variants}
    for key, by_variant in table.items():
        count = population.counts.get(key, 0)
        for variant in variants:
            tally = by_variant[variant]
            if not tally.jobs:
                continue
            weight = count / tally.jobs
            values = totals[variant]
            values[0] += tally.seconds * weight
            values[1] += tally.successes * weight
            values[2] += tally.kept * weight
            values[3] += tally.lost * weight
            values[4] += tally.gained * weight
    original_seconds = totals[ORIGINAL][0] or 1.0
    for variant in variants:
        seconds, successes, kept, lost, gained = totals[variant]
        lines.append(
            f"| {variant} | {seconds / 3600:.1f} | {seconds / original_seconds:.0%} | {successes:,.0f} | {kept:,.0f} | "
            f"{lost:,.0f} | {gained:,.0f} |"
        )
    recorded = sum(population.seconds.values()) / 3600
    lines += [
        "",
        f"The run recorded {recorded:.1f} h of net Lean time in these calls ({sum(population.counts.values()):,}).",
    ]
    return lines


def main() -> None:
    arguments = parse_arguments()
    arguments.output.mkdir(parents=True, exist_ok=True)
    population, rows = read_population(arguments.steps)
    if not arguments.summary_only:
        repl_module.BASE_ENVIRONMENT_DEFINITIONS += VARIANT_DEFINITIONS
        entries = [json.loads(line) for line in arguments.probe_set.read_text(encoding="utf-8").splitlines()]
        statements = {f"{entry['statement']['source']}.{entry['statement']['identifier']}": entry for entry in entries}
        headers = {name: entry["statement"]["header"] for name, entry in statements.items()}
        jobs, trees = select_jobs(arguments, rows, set(headers))
        (arguments.output / "jobs.jsonl").write_text(
            "".join(json.dumps(dataclasses.asdict(job), ensure_ascii=False) + "\n" for job in jobs), encoding="utf-8"
        )
        asyncio.run(run_all(jobs, trees, headers, arguments))
    text = summary(read_measurements(arguments.output / "records.jsonl"), population)
    (arguments.output / "summary.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
