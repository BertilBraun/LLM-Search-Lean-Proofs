# LLM-guided proof search in Lean 4

A small language model proposes proof steps, a learned value model estimates how many steps remain, and a
best-first search (A* with a learned heuristic) decides which proof state to expand next. Everything is verified
by Lean. The project measures how much search, retrieval, a value function and cheap training loops improve a
~2B model on miniF2F at fixed compute.

- [`DESIGN.md`](DESIGN.md) — the plan: components, training ladder, ablations, phase status.
- [`results/`](results/) — committed summaries of every experiment.
- [`deployment/`](deployment/) — how the rented GPU node is provisioned and driven.

## Layout

| Path | Contents |
|---|---|
| `src/lean_search/` | The Python package (Lean interaction, search, policy, value, retrieval, training, data). |
| `experiments/` | Entry points, one per experiment; each writes a summary to `results/`. |
| `tests/` | pytest suite; tests that need Lean or a GPU run on the node. |
| `lean/` | The pinned Lean project (toolchain, Mathlib) used by the REPL. |
| `data/` | Small vendored datasets (e.g. miniF2F statements); large data lives on the node. |
| `deployment/` | Node provisioning and remote-execution scripts. |

## Development

Code is edited locally and executed on the node:

```bash
ruff format && ruff check
git commit -am "..."
deployment/deploy.sh
deployment/on_node.sh 'pytest'
```
