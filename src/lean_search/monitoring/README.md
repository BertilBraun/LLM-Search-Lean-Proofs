# Monitoring

Metrics of a run live in append-only JSONL files, one per family, under `<run>/metrics/<family>.jsonl`. The loop
(`rl/loop.py`) writes them through `MetricsWriter`; the dashboard (`server.py`, `static/`) reads them incrementally and
draws its own SVG charts. Running and exposing it on the node: `deployment/README.md`, section "Dashboard".

## Writing (`store.py`, `families.py`)

```python
writer = MetricsWriter(run_directory, LoopContext(phase=0, policy_version=0, value_version=0), tensorboard=True)
writer.update_context(phase=12, policy_version=12)
writer.write(GrpoPhase(...))
writer.write(SearchPhase(graph=total_statistics(per_tree), failure_tiers=..., ...))
```

Each line is `{"time", "phase", "policy_version", "value_version", "fields"}`; `fields` is `dataclasses.asdict` of
the record. With `tensorboard=True` every numeric field is also logged as the scalar `<family>/<field>` under
`<run>/tensorboard/` (step: Unix seconds), but only when `tensorboard` and `torch` are installed.

| Family | Record | Written | Contents |
|---|---|---|---|
| `status` | `LoopStatus` | every heartbeat | loop state, searches running, statements and proofs (cumulative and per hour), last publish time, heartbeat interval |
| `system` | `SystemUsage` | `record-system`, every 30 s | per-GPU utilization, memory and power; cgroup cores used and available; Lean REPL cores; throttling; memory; hourly price and money spent |
| `fixed_targets` | `FixedTargets` | after evaluations (`grpo_evaluate.py`) | miniF2F-valid solved / problems at the fixed budget, the probe set solved (by difficulty stratum, at its budget), held-out per-sample success, MATH-500 visible and thinking, the evaluation's wall time; version 0 is the baseline |
| `grpo` | `GrpoPhase` | per training phase (`training_phase.grpo_phase_record`) | proof-graph groups, trained groups (non-zero advantage) and their share, trained tactics by credit label, mean local and global reward per known tactic, local share of the advantages, KL to the data-collecting policy, clip fraction, sampler-vs-trainer log-probability difference, forced answers kept, explanation and block length, loss, tokens, training and sampling time |
| `value` | `ValueBenchmarkResult` | per value candidate | `BenchmarkMetrics` (ranking, calibration with reliability bins, separation, steps), gate passed, A/B search solved, loss |
| `search` | `SearchPhase` | per phase | `GraphStatistics` summed over the phase's trees (edge kinds of all / policy / automation edges and policy samples, proof graph, dead ends, value targets by source, tactics by credit label, groups, rewards, proofs with their tactics and blocks, harvest yield, ε-picks), failure tiers, Lean seconds per expansion, forced answers, repetition loops, block length |
| `curriculum` | `CurriculumPhase` | per phase | difficulty band, pool and verified statements, attempts and solved by difficulty band and by stage |
| `timing` | `PhaseTiming` | per phase | sampling, training (the whole job), publishing and evaluation seconds; trees trained on; searches paused |

The reader flattens nested dataclasses and dicts to dotted column names (`graph.policy_samples.no_progress`,
`by_difficulty.2-3.solved`) and lists of numbers to `name.0`, `name.1`; strings and lists of objects are kept only
in the latest line. A field added later reads as missing in older lines, so a new metric is a new field with a
default, or a new dataclass with its own `family`.

## Dashboard (`server.py`, `alerts.py`, `static/`)

- `GET /api/runs`, `/api/overview?run=` (latest line per family, alerts, thresholds), `/api/series?run=&family=
  &points=&since=&fields=` (columns downsampled to at most `points` buckets: mean values, last versions). Everything
  but `/login`, `/healthz` and `/static/*` needs the session cookie or HTTP basic auth.
- Pages and charts are data in `static/pages.js`: a chart names a family, an x axis (time or a version), a unit and
  its series (a column, a sum, a ratio `over` another column or a column prefix, or one series per column of a
  prefix); `compare: true` overlays the other runs (`--compare control=<dir>`) dashed, `baseline: true` draws the
  first value as a reference, `thresholds` read the alert thresholds. Every detail page also lists all columns of
  its families with sparklines, so a new field is visible without touching the frontend.
- Alerts (`alerts.py`, thresholds in `experiments/configs/dashboard/dashboard.toml`): loop silent, no publish,
  no-progress share rising or high, repetition loops, KL and clip fraction high, MATH-500 below its minimum or
  dropping from the baseline, few groups with mixed rewards, GPUs underused, curriculum solve rate off its band,
  value gate failing repeatedly.
