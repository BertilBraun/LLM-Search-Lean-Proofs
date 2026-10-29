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
| `status` | `LoopStatus` | every heartbeat | loop state, searches running, statements and proofs (cumulative and per hour), last publish time, heartbeat interval, searches a server failed and statements dropped after repeated failures (this session) |
| `system` | `SystemUsage` | `record-system`, every 30 s | per-GPU utilization, memory and power; cgroup cores used and available; Lean REPL cores; throttling; memory used, the limit and what is available; private memory of the Lean REPLs (total, p90) and the vLLM processes; size and free space of the fullest filesystem of the run and its checkpoints; hourly price and money spent |
| `fixed_targets` | `FixedTargets` | after evaluations (`grpo_evaluate.py`) | miniF2F-valid solved / problems at the fixed budget, the probe set solved (by difficulty stratum, at its budget), held-out per-sample success, MATH-500 visible and thinking, the evaluation's wall time, searches stopped on the wall clock; a probe slot's part (`probe_slot`, `probe_part`) and the last three slots together (`probe_rolling_*`, the whole set); a repeated run's solved, difference and discordant problems against the first run (`probe_repeat_*`, per part); version 0 is the baseline |
| `grpo` | `GrpoPhase` | per training phase (`training_phase.grpo_phase_record`) | proof-graph groups, trained groups (non-zero advantage) and their share, trained tactics by credit label, mean local and global reward per known tactic, local share of the advantages, KL to the data-collecting policy, clip fraction, mean probability ratio and clip fraction of the positive- and negative-advantage tokens per pass, sampler-vs-trainer log-probability difference (overall and by sampling age: the version trained from minus the version that sampled), forced answers kept, explanation and block length, loss, tokens, training and sampling time |
| `value_phase` | `ValuePhase` | per phase (the loop, from the phase's labelled trees) | μ in effect; `PhaseValueMetrics`: the value targets' label distribution per bin by source and tree outcome (exact steps unsmoothed), the serving model's recorded predictions of the same states and of the never-expanded frontier (mean per bin, p_dead and expected-steps histograms), calibration on expanded states (reliability bins, ECE, Brier), remaining-steps MAE and Spearman on proof-graph states |
| `value_training` | `ValueTraining` | per value retrain | the value version that publishes it, window trees, loss, the window's label distribution per bin by source (smoothed as trained) and the v0 replay's |
| `value_benchmark` | `ValueBenchmarkTrend` | per value model served for the first time (the loop scores the benchmark through the value servers) | share of labelled sibling pairs ordered by h (`PairShare`), the `PairStatistic` against v0 and against the previous value model (difference, paired cluster bootstrap interval, problems, pairs, effective and discordant pairs), `BenchmarkMetrics` (ranking, calibration with reliability bins, separation, steps), predicted distribution and calibration on expanded states, scoring seconds |
| `value_arm` | `ValueArmResult` | per value arm (`grpo_evaluate.py --value-arm`) | slot and part, solved with v0 and with the published value model, and `PairedDifference`s (runs, problems, problems solved by one arm only, the paired solve-rate difference with its exact McNemar interval, one-sided p-values) for this slot and pooled over the same published value model and over every one; worse (the alert) |
| `search` | `SearchPhase` | per phase | `GraphStatistics` summed over the phase's trees (edge kinds of all / policy / automation edges and policy samples, proof graph, dead ends, value targets by source, tactics by credit label, groups, rewards, proofs with their tactics and blocks, harvest yield, ε-picks), failure tiers, Lean seconds per expansion, forced answers, repetition loops, block length |
| `curriculum` | `CurriculumPhase` | per phase | difficulty band, pool and verified statements, attempts and solved by difficulty band and by stage |
| `timing` | `PhaseTiming` | per phase | sampling, training (the whole job), publishing and evaluation seconds; trees trained on; searches paused; the pause segment by segment (`pause.*`: drain, server sleep, trainer start, preparation, policy load, compile, scoring, policy and value training, merge, write, publish, wake, resume; `rl/README.md`, "Timing") |

The reader flattens nested dataclasses and dicts to dotted column names (`graph.policy_samples.no_progress`,
`by_difficulty.2-3.solved`) and lists of numbers to `name.0`, `name.1`; strings and lists of objects are kept only
in the latest line. A field added later reads as missing in older lines, so a new metric is a new field with a
default, or a new dataclass with its own `family`.

## Dashboard (`server.py`, `alerts.py`, `static/`)

- `GET /api/runs`, `/api/overview?run=` (latest line per family, alerts, thresholds), `/api/series?run=&family=
  &points=&since=&fields=` (columns downsampled to at most `points` buckets: mean values, last versions). Everything
  but `/login`, `/healthz` and `/static/*` needs the session cookie or HTTP basic auth.
- Pages and charts are data in `static/pages.js`: a chart names a family, an x axis (time, a version, the phase or a
  numeric field such as `probe_slot`), a unit and its series (a column, a sum, a ratio `over` another column or a
  column prefix, or one series per column of a prefix); `compare: true` overlays the other runs (`--compare
  control=<dir>`) dashed, `baseline: true` draws the first value as a reference, `thresholds` read the alert
  thresholds, `references` are fixed lines. A `histogram` chart draws lists of numbers from a family's latest record
  as grouped bars per category (`series: [{label, path, family, normalize}]`), a `reliability` chart lists of
  reliability bins (`curves: [{label, path, family}]`; a series or curve may read another family's latest record).
  Every detail page also
  lists all columns of its families with sparklines, so a new field is visible without touching the frontend.
- Alerts (`alerts.py`, thresholds in `experiments/configs/dashboard/dashboard.toml`): loop silent, no publish,
  no-progress share rising or high, repetition loops, KL and clip fraction high, MATH-500 below its minimum or
  dropping from the baseline, few groups with mixed rewards, GPUs underused, curriculum solve rate off its band,
  the published value model worse than v0 in its value arms, host memory low, disk almost full, searches failing on a server.
