# Lean interaction

Async wrapper around the community Lean REPL in the pinned `lean/` project (see `deployment/README.md`). Everything
runs in one asyncio program; each `LeanRepl` owns one REPL process and serializes its requests, a `LeanReplPool`
hands processes to concurrent searches.

```python
from lean_search.data import Split, load_minif2f
from lean_search.lean import LeanError, LeanReplPool, LeanTimeout, ProofState

problem = load_minif2f(Split.VALID)[0]
async with LeanReplPool(32) as pool:
    await pool.start([problem.header])                       # optional: import the header everywhere up front
    async with pool.acquire() as repl:
        start = await repl.start_proof(problem.formal_statement, problem.header)
        match start.outcome:
            case ProofState() as root: ...                   # root.goals: tuple of pretty-printed goals
            case LeanError() | LeanTimeout(): ...            # statement does not elaborate
        result = await repl.apply_tactic(root, "nlinarith [sq_nonneg (x - y)]")
        block = await repl.apply_block(root, model_output)   # longest valid prefix of top-level tactics
        if block.state.is_proved:
            check = await repl.verify_proof(problem.formal_statement, block.state.proof, problem.header)
```

| Call | Returns |
|---|---|
| `start_proof(statement, header)` | `TacticResult(outcome, elapsed_seconds)`; outcome is the root `ProofState` or `LeanError`/`LeanTimeout` |
| `apply_tactic(state, tactic, heartbeats=None, timeout_seconds=None)` | `TacticResult`; a new `ProofState` (no goals = proved), `LeanError(message)` or `LeanTimeout(message, wall_clock)` |
| `apply_block(state, block, heartbeats=None, timeout_seconds=None)` | `BlockResult(state, applied_tactics, total_tactics, failure, elapsed_seconds)` |
| `verify_proof(statement, proof, header)` | `VerificationResult(verified, problems, axioms, elapsed_seconds)` |
| `memory_usage()`, `proof_state_count`, `restart()`, `load_header(header)` | process health and control |

Semantics:

- Every tactic runs as `lean_search_heartbeats N => tactic` (default `LeanReplConfig.tactic_heartbeats`), a tactic
  defined in the base environment because `set_option maxHeartbeats N in` has no effect on tactics in Lean 4.9.
  Exceeding it is `LeanTimeout(wall_clock=False)`. A wall-clock backstop (`tactic_timeout_seconds`) kills the
  process: `LeanTimeout(wall_clock=True)`.
- A step is a success only if the REPL returns a proof state with no error message and no `sorry`. This REPL version
  returns a proof state, often with no goals, for tactics whose errors were logged rather than thrown (`exact foo`),
  so the error check matters.
- `FORBIDDEN_TOKENS` (`sorry`, `admit`, `native_decide`, `set_option`, `run_tac`, ... see `text.py`) are rejected
  before Lean sees the tactic.
- `ProofState`s are immutable and carry their tactic path. After a restart (memory or proof-state threshold,
  wall-clock kill, crash) or on another process of the pool, a state is transparently rebuilt by replaying its path.
- `split_tactics` splits a block into top-level tactics by indentation relative to its first line; deeper lines,
  and lines starting with `<;>`, `|` or `else`, continue the previous tactic; a `·` bullet takes its indented body.
- `verify_proof` re-elaborates `statement + proof` from scratch in the header environment followed by
  `#print axioms`, and accepts only if there are no errors, no `sorry` and only `propext`, `Classical.choice`,
  `Quot.sound`.
- `ProofState.goal_key` (whitespace-normalized goals) is the de-duplication key.
