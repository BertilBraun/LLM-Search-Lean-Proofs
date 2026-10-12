# Lean interaction

Async wrapper around the community Lean REPL in the pinned `lean/` project (see `deployment/README.md`). Everything
runs in one asyncio program; each `LeanRepl` owns one REPL process and serializes its requests, a `LeanReplPool`
hands processes to concurrent searches.

```python
from lean_search.data import Split, load_minif2f
from lean_search.lean import LeanError, LeanReplPool, LeanTimeout, ProofState, ReplFailure

problem = load_minif2f(Split.VALID)[0]
async with LeanReplPool(32) as pool:
    await pool.start([problem.header])                       # optional: import the header everywhere up front
    async with pool.acquire() as repl:
        start = await repl.start_proof(problem.formal_statement, problem.header)
        match start.outcome:
            case ProofState() as root: ...                   # root.goals: tuple of pretty-printed goals
            case LeanError() | LeanTimeout(): ...            # statement does not elaborate
            case ReplFailure(): ...                          # infrastructure failure, not the statement's fault
        result = await repl.apply_tactic(root, "nlinarith [sq_nonneg (x - y)]")
        block = await repl.apply_block(root, model_output)   # longest valid prefix of top-level tactics
        if block.state.is_proved:
            check = await repl.verify_state(block.state)     # the proof exactly as the search executed it
```

| Call | Returns |
|---|---|
| `start_proof(statement, header)` | `TacticResult(outcome, elapsed_seconds)`; outcome is the root `ProofState`, `LeanError` (also for a header that does not elaborate or lacks Lean), `LeanTimeout` or `ReplFailure` |
| `apply_tactic(state, tactic, heartbeats=None, timeout_seconds=None)` | `TacticResult`; a new `ProofState` (no goals = proved), `LeanError(message, panic)`, `LeanTimeout(message, wall_clock)` or `ReplFailure(kind, message)` |
| `apply_block(state, block, heartbeats=None, timeout_seconds=None)` | `BlockResult(state, applied_tactics, total_tactics, failure, elapsed_seconds)`; `failure` is `LeanError \| LeanTimeout \| ReplFailure \| None` |
| `verify_state(state)` | `VerificationResult(verified, problems, axioms, elapsed_seconds, plain_verified)`: `verified` checks the steps as executed, `plain_verified` the unwrapped text |
| `verify_proof(statement, proof, header)` | `VerificationResult` for a plain proof text (`plain_verified` is `None`) |
| `memory_usage()`, `proof_state_count`, `needs_restart`, `restart()`, `load_header(header)` | process health and control |

## Outcomes

- `LeanError` and `LeanTimeout` are the candidate's own result: Lean rejected the tactic, or it exceeded its heartbeat
  limit (`wall_clock=False`) or the wall-clock backstop (`wall_clock=True`, the process is killed and restarted).
  `LeanError(panic=True)` (message `Lean panic: ...`) means the tactic killed the process with a deterministic runtime
  panic (see below); the process was restarted.
- `ReplFailure(kind, message)` is never the candidate's fault and must not become a negative training label. Kinds
  (`ReplFailureKind`): `CRASHED` (the process died or broke the protocol, including the per-process memory cap),
  `REPLAY_FAILED` (rebuilding the parent state failed or timed out), `REPLAY_MISMATCH` (the rebuilt parent has different
  goals than recorded) and `RESTART_FAILED` (the process could not be started).
- Which deaths are the tactic's fault: Lean's runtime aborts the whole process (`INTERNAL PANIC: <message>`, exit code
  1) instead of throwing a catchable error in a few places. Only the arithmetic panics in `DETERMINISTIC_PANICS`
  (`Nat.pow`, `Nat.shiftl`, `Nat.shiftr` "exponent is too big", e.g. `simp_all` or `rfl` on `amc12a_2008_p15`
  evaluating `2 ^ (2008 ^ 2 + 2 ^ 2008)`) count: they depend only on the values the tactic computes with, not on
  memory limits, load or timing, so a retry panics again. They count only when the candidate's own tactic (or the
  statement in `start_proof`) was running, the panic is the last stderr line and the exit code is 1. Everything else
  stays `ReplFailure(CRASHED)`: `INTERNAL PANIC: out of memory`, `GNU MP: Cannot allocate memory` and `std::bad_alloc`
  (all from the memory cap), stack overflows, signals (OOM killer, external kills), panics while replaying a parent and
  unknown messages.
- A step is a success only if the REPL returns a proof state with no error message, no `sorry` and no goal closed by a
  term containing `sorryAx`. This REPL version returns a proof state, often with no goals, for tactics whose errors
  were logged rather than thrown (`exact foo`), and `apply?`, `hint` and `slim_check` close goals with `sorryAx`
  without any error, so both checks matter.

## Tactic execution

- Every tactic runs as `lean_search_heartbeats N => tactic` (default `LeanReplConfig.tactic_heartbeats`), a tactic
  defined in the base environment (header + `BASE_ENVIRONMENT_DEFINITIONS`) because `set_option maxHeartbeats N in` has
  no effect on tactics in Lean 4.9. The wrapper records the goals, runs the tactic with `maxHeartbeats := N`, prunes
  solved goals, and throws if a recorded goal's instantiated assignment contains `sorryAx`. A goal assigned a term with
  fresh metavariables (`refine ⟨?_, ?_⟩`) passes. The thrown message is the errors the tactic logged (usually why the
  term became `sorry`, e.g. `unknown identifier 'foo'`) followed by `lean_search: the tactic closed a goal with sorry`;
  if a logged error is a heartbeat error, the step is a `LeanTimeout`.
- The REPL's tactic mode has no declaration name, so tactics that create auxiliary matchers (`intro ⟨a, b⟩`,
  `fun ⟨a, b⟩ => …`, `let ⟨a, b⟩ := h`, `match h with …`) used to fail with "auxiliary declaration cannot be created
  when declaration name is not available". When no name is set, the wrapper runs the tactic with the declaration name
  `lean_search_step`; matchers get fresh names (`lean_search_step.match_1`, `_2`, ...) from the environment of the
  proof state, which later steps and replays inherit. Inside a theorem (verification) the theorem's own name is kept.
- The REPL also gives a statement's root proof state the environment from before the statement, which lacks the
  matchers the statement itself created (`{(x, y) | x = y}` elaborates to `test_set.match_1`): steps failed with
  `unknown constant 'X.match_1'` and goals printed as `@X.match_1 (fun x => Prop) x fun x y => x = y`. `start_proof`
  therefore checks the root with `lean_search_check_constants` (every constant of the goals must exist in the
  environment); if one is missing, it first elaborates `theorem X.lean_search_auxiliaries binders : (type) → True`,
  which adds the statement's matchers but proves only `True`, and elaborates the statement on top of it, where Lean's
  matcher cache reuses them. The repaired root is used only if it passes the check; otherwise the old root is kept.
- `FORBIDDEN_TOKENS` (`text.py`) are rejected before Lean sees the text: `sorry`-like closers and unsound
  evaluation (`native_decide`, `ofReduceBool`, ...), metaprogramming and limits (`run_tac`, `set_option`, `sleep`,
  ...), our own syntax and names (`lean_search_heartbeats`, `lean_search_step`, `lean_search_auxiliaries`, ...), and
  suggestion tactics (`apply?`, `exact?`, `rw?`, `hint`, `slim_check`, `aesop?`, `simp?`,
  `simp_all?`, `dsimp?` and their `?!` forms, `rw_search`, `library_search`, `observe`). `says` (runs only its
  second tactic) and `decide!` (not in Lean 4.9) are not on the list. `LeanReplConfig.forbidden_tokens` overrides the
  set (the tests use it to reach the deeper checks).
- Tokens inside comments do not count (`nlinarith -- no sorry needed` is fine). `lex` mirrors Lean's comment rules
  exactly: nested `/- -/` where a plain `/-` skips its next character, `--` to the end of the line, `"..."` strings
  with escapes. Wherever Lean might lex differently (char literals, raw or interpolated strings, `«»`, backticks,
  comment or string starts glued to symbols) it reports `exact = False` and the whole raw text is searched instead,
  so hiding a token from the filter needs a lexer disagreement that the fallback does not cover. String contents are
  always searched.
- `split_tactics` splits a block into top-level tactics by indentation relative to its first code line (spaces and
  tabs both count; Lean itself rejects tabs). A line continues the previous tactic if it is more indented, starts
  inside an unclosed bracket, block comment or string, follows a line ending in `<;>`, `,`, `:=`, `=>`, `↦`, `<|`,
  `by`, `with`, `then`, `else`, `do`, `from`, `fun` or `calc`, or starts with `<;>`, `<|>`, `|`, a closing bracket,
  `:=`, `_` (calc steps), `else`, `then` or `with`. Comment-only lines between tactics are dropped; a `·` bullet takes
  its indented body. If a piece still fails with `unexpected end of input` or `unterminated comment`, `apply_block`
  merges it with the next piece and retries; `total_tactics` counts the merged pieces.

## Proof states and replay

- `ProofState`s are immutable and carry their tactic path and the heartbeat limit each step ran with
  (`tactic_heartbeats`, parallel to `tactics`). After a restart (memory or proof-state threshold, wall-clock kill,
  crash, cancellation), on another process of the pool, or after unpickling in another Python process, a state is
  rebuilt by replaying its path with the recorded limits (`replay_timeout_seconds` as the wall-clock backstop). The
  replayed goals must equal the recorded ones (`goal_key`), otherwise the call returns `ReplFailure(REPLAY_MISMATCH)`.
- Session ids are random (uuid4), so a state from another process or `LeanRepl` is never mistaken for a live one.
- `ProofState.goal_key` (whitespace-normalized goals) is the de-duplication key; `proof` is the plain tactic text,
  `executed_proof` the text with every step wrapped in its heartbeat limit.
- Replay is deterministic, but only for identical commands before it: Lean's fresh-name counters depend on everything
  elaborated earlier in the chain (header, `BASE_ENVIRONMENT_DEFINITIONS`), and the runtime of heavy steps is chaotic
  in them. One `nlinarith` step takes 16.4 s with the old base definitions, 98 s after appending an unrelated
  one-line theorem, and over 150 s with the current ones; its goals never change. Large rational arithmetic is not
  counted in heartbeats, so such steps can flip between success and the wall-clock backstop whenever the base
  definitions change (4 of 500 sampled traced proofs did when they last changed). `?m.N` numbers in goals shift too
  (13 of 267k traced steps show one).

## Verification

`verify_state` and `verify_proof` re-elaborate the theorem from scratch in the base environment with three separate
REPL commands, and accept only if all pass:

1. `lean_search_single_command "<theorem text>"` parses the text with Lean's own parser and fails unless it is exactly
   one command, so a proof cannot end the theorem early and run further commands (`#exit`, notation or macros that
   could change how step 3 parses).
2. The theorem itself: no error, no `sorry`, no `declaration uses 'sorry'` warning.
3. `#print axioms _root_.<name>` on the environment returned by step 2. Only this response is parsed, and it must be
   a single info message naming the theorem, so `trace` output inside the proof cannot spoof it. Accepted axioms:
   `propext`, `Classical.choice`, `Quot.sound`.

`verify_state` checks the steps wrapped exactly as the search executed them (`state.executed_proof`), so a step that
behaved differently without its heartbeat limit (`try simp` that times out inside `try`) cannot make a found proof
fail, and reports in `plain_verified` whether the unwrapped text also verifies. Soundness does not depend on the
wrapper: it is a tactic that only lowers `maxHeartbeats` for its body, supplies a declaration name when none is set
(never the case inside a theorem, so not during verification), and adds checks that can make it fail; it adds no
declarations or axioms itself and assigns no goal, so the elaborated term is the one its body produces, which the
kernel checks when the theorem is added and step 3 audits for axioms. Verification also never sees the step-mode
helpers: it starts from the base environment, without `X.lean_search_auxiliaries` (which only proves `True` anyway)
or the `lean_search_step.match_N` matchers of executed steps. A crash during verification is reported as a problem
(`verified = False`).

## Processes

- A wall-clock backstop (`tactic_timeout_seconds`, `command_timeout_seconds`) kills the process. Any other exception
  while a request is in flight (cancellation of the calling task, an unreadable or oversized response) also kills it
  and marks it for restart before the exception propagates, so a late answer can never be read as the answer to a
  later request.
- `elapsed_seconds` is wall-clock time inside the process lock, including any restart: a kill restarts the process and
  re-imports its headers (about 3.5 s) before the call returns; a threshold restart (default 2 GiB private memory or
  8000 proof states) and replays are charged to the call that triggers them.
- Headers: each distinct set of `import` lines is imported once per process; the rest of a header (`open`,
  `set_option`, helper definitions) is elaborated as a command on top of it, and the wrapper definitions on top of
  that, each cached per header. A second header with the same imports costs about 0.6 s and 0.01 GiB instead of a
  second import of Mathlib (7–12 s and 3.9 GiB of private memory). A header that does not elaborate, or lacks Lean
  itself (no imports: the wrapper needs `import Lean` or Mathlib), makes `start_proof` return a `LeanError` starting
  with `The header does not elaborate` and `verify_*` report it as a problem; the failure is cached per process, so a
  bad header is not re-imported for every statement. `load_header` raises `ValueError` for such headers.
- Each REPL runs with `RLIMIT_DATA = max_data_bytes` (default 6 GiB; it counts private memory, not the shared `.olean`
  mappings, and a REPL holds about 0.25 GiB after `import Mathlib`), so a runaway tactic crashes its own process
  (`ReplFailure(CRASHED)`) instead of the node. `PR_SET_PDEATHSIG` kills REPLs when the orchestrating process dies
  (strictly: when the thread that started them exits, so start them from the event-loop thread).
- `lake env` runs once per project directory and Python process, shared by concurrent starts.
- The pool restarts a process before reusing it if the `acquire` body raised (including cancellation), if the process
  needs a restart, or if it is past `restart_fraction` of its limits. Restarts run in the background with
  `restart_attempts` tries and exponential backoff; the slot always returns to the pool, and a REPL that still cannot
  start reports `ReplFailure(RESTART_FAILED)` from its calls instead of hanging `acquire`.
- Closing is final, so nothing the pool started outlives it: `LeanRepl.close()` stops the process and later calls raise
  `ReplClosedError` instead of starting a new one; `LeanReplPool.close()` cancels and awaits its restarts, schedules
  none afterwards and closes every REPL, so a task still using one fails on its next call. A REPL start left running
  after the program's main coroutine fails can hang `asyncio.run`'s shutdown for good (Python 3.12 never finishes a
  process start cancelled together with its pipe-connection task), so `search_problems` also cancels and awaits the
  other searches when one fails.
