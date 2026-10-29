// The dashboard's pages as data. A chart is one object here; fields are the dotted column names of a family
// (nested dataclasses and dicts flattened, list items as .0, .1). Every page also lists all columns of its families.
//
// series: {label, field} | {label, fields: [...]} (summed) | {label, mean: "prefix."} | {label, sum: "prefix.", suffix}
//         | {expand: "prefix.", label} (one series per column), optionally {over: "field" | "prefix."} (a ratio)
// chart:  {title, family, kind: "line" | "stacked" | "bands" | "reliability" | "histogram", x: "time" | "policy_version"
//          | ..., unit, series, compare (overlay the other runs), baseline (first value as a reference), allTime,
//          thresholds: [{key, label}] (from the config), references: [{value, label, kind}], band: {low, high} (keys),
//          yMin, yMax, wide}
// histogram (the family's latest record): categories, series: [{label, path, normalize, detail: {name: key}}]
// reliability (the family's latest record): curves: [{label, path}] to lists of reliability bins

const SAMPLES = "graph.policy_samples.";
const EDGE_GROUPS = (prefix) => [
  { label: "Lean error", fields: [`${prefix}lean_error`, `${prefix}forbidden`, `${prefix}infrastructure_failure`, `${prefix}unverified_proof`] },
  { label: "Timeout", fields: [`${prefix}heartbeat_timeout`, `${prefix}wall_clock_timeout`] },
  { label: "New state", field: `${prefix}new_state` },
  { label: "No progress", fields: [`${prefix}no_progress`, `${prefix}back_to_ancestor`] },
  { label: "Sibling state", field: `${prefix}sibling_state` },
  { label: "Transposition", field: `${prefix}transposition` },
  { label: "Repeat", field: `${prefix}repeat` },
];

const TACTIC_LABELS = (prefix) => [
  { label: "Proof graph", field: `${prefix}proof_graph` },
  { label: "Off graph", field: `${prefix}off_graph` },
  { label: "Unknown", field: `${prefix}unknown` },
  { label: "No progress", field: `${prefix}no_progress` },
  { label: "Redundant hypothesis", field: `${prefix}redundant_hypothesis` },
  { label: "Failing", field: `${prefix}failing` },
  { label: "Masked", field: `${prefix}masked` },
];

const FIXED = {
  minif2f: {
    title: "miniF2F-valid solved", subtitle: "fixed search budget, by policy version; dashed: control run",
    family: "fixed_targets", x: "policy_version", unit: "count", compare: true, baseline: true, allTime: true,
    series: [{ label: "solved", field: "minif2f_valid_solved" }],
  },
  heldOut: {
    title: "Held-out states, per-sample success", subtitle: "512 states, by policy version",
    family: "fixed_targets", x: "policy_version", unit: "share", compare: true, baseline: true, allTime: true,
    series: [{ label: "success", field: "held_out_success" }],
  },
  probe: {
    title: "Probe set solved", subtitle: "held-out pool statements at 16 expansions, by policy version",
    family: "fixed_targets", x: "policy_version", unit: "count", compare: true, baseline: true, allTime: true,
    series: [{ label: "solved", field: "probe_solved" }],
  },
  probeBands: {
    title: "Probe set by difficulty", subtitle: "solve rate per stratum, by policy version",
    family: "fixed_targets", x: "policy_version", unit: "share", compare: true, allTime: true,
    series: ["easy", "medium", "hard"].map((stratum) => ({
      label: stratum, field: `probe_by_difficulty.${stratum}.solved`, over: `probe_by_difficulty.${stratum}.attempts`,
    })),
  },
  math: {
    title: "MATH-500 retention", subtitle: "by policy version",
    family: "fixed_targets", x: "policy_version", unit: "share", allTime: true,
    thresholds: [{ key: "min_math500_visible", label: "minimum visible" }],
    series: [{ label: "visible", field: "math500_visible" }, { label: "thinking", field: "math500_thinking" }],
  },
};

const GRPO = {
  kl: {
    title: "KL to the data-collecting policy", family: "grpo", unit: "number",
    thresholds: [{ key: "max_kl", label: "max" }], series: [{ label: "KL", field: "kl_to_behaviour_policy" }],
  },
  clip: {
    title: "Clip fraction", family: "grpo", unit: "share",
    thresholds: [{ key: "max_clip_fraction", label: "max" }], series: [{ label: "clip", field: "clip_fraction" }],
  },
  mixed: {
    title: "Groups trained", subtitle: "share of proof-graph groups with a non-zero advantage", family: "grpo", unit: "share",
    thresholds: [{ key: "min_mixed_group_share", label: "min" }], compare: true,
    series: [{ label: "trained", field: "mixed_reward_group_share" }],
  },
  rewards: {
    title: "Mean reward per known tactic, local vs global", family: "grpo", unit: "number",
    series: [{ label: "local (λ·L)", field: "mean_local_reward" }, { label: "global ((1 − λ)·G + δ·progress)", field: "mean_global_reward" }],
  },
  tactics: {
    title: "Trained tactics by credit label", subtitle: "share of the trained groups' tactics", family: "grpo", kind: "stacked",
    series: TACTIC_LABELS("tactics."),
  },
  sampler: {
    title: "Sampler vs trainer log-probabilities", subtitle: "per sampled token, before the first update", family: "grpo", unit: "number",
    series: [
      { label: "mean |difference|", field: "sampler_absolute_log_probability_difference" },
      { label: "mean difference", field: "sampler_log_probability_difference" },
      { label: "KL (k3)", field: "sampler_kl" },
    ],
  },
  samplerByAge: {
    title: "Sampler vs trainer by sampling age",
    subtitle: "mean |difference| per token; age: the version trained from minus the version that sampled", family: "grpo", unit: "number",
    series: [0, 1, 2].map((age) => ({ label: `age ${age}`, field: `sampler_by_age.${age}.mean_absolute_difference` })),
  },
  currentTokens: {
    title: "Tokens sampled by the version trained from", subtitle: "share of the tokens with a recorded version (age 0)", family: "grpo", unit: "share",
    series: [{ label: "age 0", field: "sampler_by_age.0.tokens", over: { sum: "sampler_by_age.", suffix: ".tokens" } }],
  },
};

const SEARCH = {
  samples: {
    title: "Policy samples by outcome", subtitle: "share of samples per phase", family: "search", kind: "stacked",
    series: EDGE_GROUPS(SAMPLES),
  },
  noProgress: {
    title: "No-progress share", subtitle: "policy samples; a rise hints at reward hacking", family: "search",
    unit: "share", compare: true, thresholds: [{ key: "max_no_progress_share", label: "max" }],
    series: [{ label: "no progress", fields: [`${SAMPLES}no_progress`, `${SAMPLES}back_to_ancestor`], over: SAMPLES }],
  },
  blocks: {
    title: "Block length", subtitle: "tactics per policy sample: written, and accepted by Lean", family: "search", unit: "number",
    compare: true,
    series: [
      { label: "tactics", field: "graph.blocks.tactics", over: "graph.blocks.samples" },
      { label: "valid tactics", field: "graph.blocks.valid_tactics", over: "graph.blocks.samples" },
    ],
  },
  continuation: {
    title: "Continuing after a valid tactic", subtitle: "a steady fall in continuing means shrinking blocks", family: "search",
    unit: "share", compare: true,
    series: [
      { label: "continues", field: "graph.blocks.continued_tactics", over: "graph.blocks.valid_tactics" },
      { label: "next tactic fails", field: "graph.blocks.later_failing", over: "graph.blocks.continued_tactics" },
      { label: "next tactic without progress", field: "graph.blocks.later_no_progress", over: "graph.blocks.continued_tactics" },
    ],
  },
  loops: {
    title: "Forced answers and repetition loops", subtitle: "per policy sample", family: "search", unit: "share",
    thresholds: [{ key: "max_repetition_loop_share", label: "max loops" }],
    series: [
      { label: "forced at the cap", field: "forced_answers", over: SAMPLES },
      { label: "repetition loops", field: "repetition_loops", over: SAMPLES },
    ],
  },
};

const VALUE_BINS = ["1", "2", "3", "4", "5", "6", "7", "8+", "dead"];
const DEAD_TENTHS = Array.from({ length: 10 }, (_, index) => `${index / 10}–${(index + 1) / 10}`);
const ALIVE_STEPS = Array.from({ length: 11 }, (_, index) => `${index + 1}–${index + 2}`);
const PREDICTIONS = [
  { label: "candidate, benchmark", prefix: "diagnostics.benchmark_candidate" },
  { label: "published, benchmark", prefix: "diagnostics.benchmark_published" },
  { label: "served, expanded", prefix: "diagnostics.phase_expanded" },
  { label: "served, frontier", prefix: "diagnostics.phase_frontier" },
];
const predictionSeries = (field, normalize) =>
  PREDICTIONS.map(({ label, prefix }) => ({ label, path: `${prefix}.${field}`, normalize, detail: { states: "states" } }));

const VALUE = {
  gate: {
    title: "Gate: gain in sibling pairs ordered by h",
    subtitle: "candidate minus published, share of pairs whose proof-graph child gets the lower h; 95% interval over problems, passes above 0",
    family: "value", x: "phase", unit: "number", allTime: true,
    references: [{ value: 0, label: "0", kind: "threshold" }],
    series: [
      { label: "lower bound", field: "gate.lower" },
      { label: "difference", field: "gate.difference" },
      { label: "upper bound", field: "gate.upper" },
    ],
  },
  abSolved: {
    title: "Value A/B search", subtitle: "probe problems solved, policy fixed: published value model vs v0",
    family: "value_ab", x: "policy_version", unit: "count", allTime: true,
    series: [{ label: "published", field: "published_solved" }, { label: "v0", field: "reference_solved" }],
  },
  ranking: {
    title: "Value benchmark: ranking and separation", family: "value", unit: "share",
    series: [
      { label: "pairwise", field: "benchmark.ranking.pairwise_accuracy" },
      { label: "top", field: "benchmark.ranking.top_accuracy" },
      { label: "proof vs dead AUC", field: "benchmark.separation.proof_graph_over_dead_end_auc" },
    ],
  },
  calibration: {
    title: "Calibration error", subtitle: "Lean anchors (proof graph, dead ends)", family: "value", unit: "number",
    series: [
      { label: "ECE", field: "benchmark.calibration.anchor_expected_calibration_error" },
      { label: "Brier", field: "benchmark.calibration.anchor_brier_score" },
    ],
  },
};

const DIFFICULTY_RATE = { label: "solve rate", sum: "by_difficulty.", suffix: ".solved", over: { sum: "by_difficulty.", suffix: ".attempts" } };

export const PAGES = [
  {
    id: "overview",
    title: "Overview",
    families: [],
    sections: [
      { title: "Status", tiles: "overview" },
      { title: "Fixed targets", charts: [FIXED.probe, FIXED.minif2f, FIXED.heldOut, FIXED.math] },
      { title: "RL health", charts: [GRPO.kl, GRPO.clip, GRPO.mixed, GRPO.rewards] },
      { title: "Value health", charts: [VALUE.gate, VALUE.abSolved] },
      { title: "Search behaviour", charts: [SEARCH.samples, SEARCH.noProgress, SEARCH.continuation, SEARCH.loops] },
    ],
  },
  {
    id: "policy",
    title: "Policy / GRPO",
    families: ["grpo"],
    sections: [
      { title: "Stability", charts: [GRPO.kl, GRPO.clip, GRPO.sampler, GRPO.samplerByAge, GRPO.currentTokens] },
      {
        title: "Signal",
        charts: [
          GRPO.mixed,
          GRPO.tactics,
          GRPO.rewards,
          {
            title: "Local share of the advantages", subtitle: "of the summed |tactic advantage|; λ = 0.15", family: "grpo", unit: "share",
            compare: true, series: [{ label: "local", field: "local_advantage_share" }],
          },
        ],
      },
      {
        title: "Outputs and training",
        charts: [
          { title: "Explanation length", family: "grpo", unit: "number", compare: true, series: [{ label: "tokens", field: "mean_explanation_tokens" }] },
          { title: "Block length", subtitle: "top-level tactics per sample", family: "grpo", unit: "number", compare: true, series: [{ label: "tactics", field: "mean_block_tactics" }] },
          { title: "Policy loss", family: "grpo", unit: "number", series: [{ label: "loss", field: "policy_loss" }] },
          {
            title: "Forced answers kept", subtitle: "share of trained sequences; the inserted text is masked", family: "grpo", unit: "share",
            series: [{ label: "forced", field: "forced_answers_kept", over: "sequences" }],
          },
          {
            title: "Training vs sampling time per phase", subtitle: "decides one or two passes", family: "grpo", unit: "seconds",
            series: [{ label: "training", field: "training_seconds" }, { label: "sampling", field: "sampling_seconds" }],
          },
          {
            title: "Groups per phase", family: "grpo", unit: "count",
            series: [{ label: "groups", field: "groups" }, { label: "trained", field: "groups_trained" }],
          },
        ],
      },
    ],
  },
  {
    id: "value",
    title: "Value",
    families: ["value", "value_ab"],
    sections: [
      {
        title: "Gate and A/B search",
        charts: [
          VALUE.gate,
          {
            title: "Pairs behind the gate", subtitle: "labelled sibling pairs, their problems, and the independent pairs they are worth",
            family: "value", x: "phase", unit: "count", allTime: true,
            series: [
              { label: "pairs", field: "gate.pairs" },
              { label: "effective pairs", field: "gate.effective_pairs" },
              { label: "problems", field: "gate.problems" },
              { label: "pairs ordered differently", field: "gate.discordant_pairs" },
            ],
          },
          {
            title: "Pairs ordered by h", subtitle: "share whose proof-graph child gets the lower h", family: "value", x: "phase", unit: "share", allTime: true,
            series: [{ label: "candidate", field: "gate.candidate_accuracy" }, { label: "published", field: "gate.current_accuracy" }],
          },
          { title: "Gate passed", subtitle: "1 = published", family: "value", x: "phase", unit: "number", dots: true, yMin: 0, yMax: 1, allTime: true, series: [{ label: "passed", field: "gate_passed" }] },
          VALUE.abSolved,
          {
            title: "A/B: problems solved by one arm only", subtitle: "the paired test's evidence", family: "value_ab", x: "policy_version", unit: "count", allTime: true,
            series: [{ label: "published only", field: "only_published" }, { label: "v0 only", field: "only_reference" }],
          },
          {
            title: "A/B: exact McNemar test", subtitle: "this run two-sided; one-sided better and worse pooled over the A/Bs of the published model", family: "value_ab", x: "policy_version", unit: "number", allTime: true, yMin: 0, yMax: 1,
            references: [{ value: 0.05, label: "0.05", kind: "threshold" }],
            series: [{ label: "p", field: "p_value" }, { label: "p (better)", field: "better_p_value" }, { label: "p (worse)", field: "worse_p_value" }],
          },
        ],
      },
      {
        title: "Labels and predictions of the latest retrain",
        charts: [
          {
            title: "Label distribution", subtitle: "weighted mean target per bin, by source", kind: "histogram", family: "value", categories: VALUE_BINS,
            series: [
              { label: "proof graph", path: "diagnostics.labels.proof_graph.bins", detail: { targets: "targets", weight: "weight" } },
              { label: "off graph, solved trees", path: "diagnostics.labels.off_graph_solved_trees.bins", detail: { targets: "targets", weight: "weight" } },
              { label: "off graph, unsolved trees", path: "diagnostics.labels.off_graph_unsolved_trees.bins", detail: { targets: "targets", weight: "weight" } },
              { label: "v0 replay", path: "diagnostics.labels.replay.bins", detail: { targets: "targets", weight: "weight" } },
            ],
          },
          { title: "Predicted bins", subtitle: "mean probability per bin", kind: "histogram", family: "value", categories: VALUE_BINS, series: predictionSeries("mean_bins", false) },
          { title: "Predicted p_dead", subtitle: "share of states per tenth", kind: "histogram", family: "value", categories: DEAD_TENTHS, series: predictionSeries("dead_histogram", true) },
          { title: "Expected steps given alive", subtitle: "share of states per step", kind: "histogram", family: "value", categories: ALIVE_STEPS, series: predictionSeries("alive_steps_histogram", true) },
          {
            title: "Calibration on expanded states", subtitle: "predicted proof probability against z (1 on the proof graph); diagonal = calibrated", kind: "reliability", family: "value",
            curves: [
              { label: "candidate, benchmark", path: "diagnostics.benchmark_candidate_calibration.bins" },
              { label: "served, phase", path: "diagnostics.phase_calibration.bins" },
            ],
          },
        ],
      },
      {
        title: "Benchmark diagnostics (not pass criteria)",
        charts: [
          {
            title: "Sibling pairs ranked correctly", subtitle: "both siblings labelled; never-expanded ones excluded",
            family: "value", unit: "share",
            series: [
              { label: "proof graph over all", field: "benchmark.ranking.pairwise_accuracy" },
              { label: "proof graph over dead end", field: "benchmark.ranking.proof_over_dead_end.accuracy" },
              { label: "proof graph over expanded", field: "benchmark.ranking.proof_over_expanded.accuracy" },
              { label: "expanded over dead end", field: "benchmark.ranking.expanded_over_dead_end.accuracy" },
            ],
          },
          {
            title: "Dead / live separation", subtitle: "AUC against dead ends", family: "value", unit: "share",
            series: [
              { label: "proof graph", field: "benchmark.separation.proof_graph_over_dead_end_auc" },
              { label: "every expanded", field: "benchmark.separation.expanded_over_dead_end_auc" },
            ],
          },
          VALUE.calibration,
          { title: "Calibration of the latest candidate", subtitle: "Lean anchors; diagonal = calibrated", kind: "reliability" },
          {
            title: "Remaining-steps error", subtitle: "mean absolute error on proof-graph states", family: "value", unit: "number",
            series: [{ label: "MAE", field: "benchmark.steps.mean_absolute_error" }],
          },
          {
            title: "Remaining-steps ranking", subtitle: "Spearman on proof-graph states", family: "value", unit: "number",
            series: [{ label: "Spearman", field: "benchmark.steps.spearman" }],
          },
          { title: "Value training loss", family: "value", unit: "number", series: [{ label: "loss", field: "training_loss" }] },
        ],
      },
      {
        title: "Targets from the search graphs",
        charts: [
          {
            title: "Value targets by source", family: "search", kind: "stacked",
            series: [
              { label: "proof graph", field: "graph.proof_graph_targets" },
              { label: "off graph", field: "graph.off_graph_targets" },
              { label: "expanded, capped", field: "graph.expanded_without_target" },
            ],
          },
          {
            title: "Subtree behind off-graph targets", subtitle: "mean expanded nodes, the node included", family: "search", unit: "number",
            series: [{ label: "expanded nodes", field: "graph.off_graph_subtree_sizes.total_size", over: "graph.off_graph_targets" }],
          },
          {
            title: "Never-expanded children", subtitle: "per searched tree", family: "search", unit: "number",
            series: [{ label: "never expanded", field: "graph.never_expanded_nodes", over: "graph.trees" }],
          },
        ],
      },
    ],
  },
  {
    id: "search",
    title: "Search / Lean",
    families: ["search"],
    sections: [
      {
        title: "Edges",
        charts: [
          SEARCH.samples,
          { title: "All edges by kind", subtitle: "policy and automation sweep", family: "search", kind: "stacked", series: EDGE_GROUPS("graph.edges.") },
          { title: "Automation sweep edges", family: "search", kind: "stacked", series: EDGE_GROUPS("graph.automation_edges.") },
          SEARCH.noProgress,
          {
            title: "Policy tactics by credit label", subtitle: "every policy sample's tactics", family: "search", kind: "stacked",
            series: TACTIC_LABELS("graph.policy_tactics."),
          },
        ],
      },
      {
        title: "Failures",
        charts: [
          {
            title: "Failure tiers", subtitle: "per policy sample", family: "search", unit: "share",
            series: [
              { label: "malformed", field: "failure_tiers.malformed", over: SAMPLES },
              { label: "invalid in the state", field: "failure_tiers.invalid_in_state", over: SAMPLES },
              { label: "valid but failing", field: "failure_tiers.valid_but_failing", over: SAMPLES },
              { label: "timeout", field: "failure_tiers.timeout", over: SAMPLES },
            ],
          },
          SEARCH.loops,
          {
            title: "Repeats of failed sweep tactics", subtitle: "per policy sample", family: "search", unit: "share",
            series: [{ label: "repeats", field: "graph.repeats_of_failed_automation", over: SAMPLES }],
          },
        ],
      },
      {
        title: "Throughput and proofs",
        charts: [
          { title: "Lean seconds per expansion", family: "search", unit: "seconds", compare: true, series: [{ label: "Lean", field: "lean_seconds_per_expansion" }] },
          {
            title: "Searches solved", family: "search", unit: "share", compare: true,
            series: [{ label: "solved", field: "graph.solved_trees", over: "graph.trees" }],
          },
          SEARCH.blocks,
          SEARCH.continuation,
          {
            title: "Proof graph beyond the found proofs", subtitle: "per solved search", family: "search", unit: "number",
            series: [
              { label: "off-path proof-graph nodes", field: "graph.off_path_proof_graph_nodes", over: "graph.solved_trees" },
              { label: "transpositions into it", field: "graph.transpositions_into_proof_graph", over: "graph.solved_trees" },
            ],
          },
          {
            title: "Dead ends", subtitle: "share of expanded nodes", family: "search", unit: "share", compare: true,
            series: [{ label: "dead ends", field: "graph.dead_ends", over: "graph.expanded_nodes" }],
          },
        ],
      },
      {
        title: "Proofs and harvesting",
        charts: [
          {
            title: "Proof length", subtitle: "per found proof", family: "search", unit: "number", compare: true,
            series: [
              { label: "tactics", field: "graph.proof_tactics", over: "graph.proofs" },
              { label: "blocks", field: "graph.proof_blocks", over: "graph.proofs" },
            ],
          },
          {
            title: "Proofs per solved problem", family: "search", unit: "number",
            series: [{ label: "proofs", field: "graph.proofs", over: "graph.solved_trees" }],
          },
          {
            title: "Proof-graph nodes", subtitle: "share of all nodes", family: "search", unit: "share",
            series: [{ label: "proof graph", field: "graph.proof_graph_nodes", over: "graph.nodes" }],
          },
          {
            title: "Harvest yield", subtitle: "per expansion after the first proof", family: "search", unit: "number",
            series: [
              { label: "proofs", field: "graph.harvest_proofs", over: "graph.harvest_expansions" },
              { label: "proof-graph nodes", field: "graph.harvest_proof_graph_nodes", over: "graph.harvest_expansions" },
            ],
          },
          {
            title: "ε-picks", subtitle: "share of expansions drawn among the top 8", family: "search", unit: "share",
            series: [{ label: "explored", field: "graph.exploration_expansions", over: "graph.expanded_nodes" }],
          },
        ],
      },
    ],
  },
  {
    id: "curriculum",
    title: "Curriculum",
    families: ["curriculum"],
    sections: [
      {
        title: "Solve rate",
        charts: [
          {
            title: "Solve rate per phase", subtitle: "target band shaded", family: "curriculum", unit: "share",
            band: { low: "min_solve_rate", high: "max_solve_rate" }, compare: true, series: [DIFFICULTY_RATE],
          },
          {
            title: "Solve rate by difficulty, latest phase", family: "curriculum", kind: "bands", unit: "share",
            prefix: "by_difficulty.", band: { low: "min_solve_rate", high: "max_solve_rate" },
          },
          { title: "Solve rate by stage, latest phase", family: "curriculum", kind: "bands", unit: "share", prefix: "by_stage." },
          {
            title: "Difficulty band", family: "curriculum", unit: "number",
            series: [{ label: "low", field: "band_low" }, { label: "high", field: "band_high" }],
          },
          { title: "Verified statements", family: "curriculum", unit: "count", series: [{ label: "verified", field: "verified_statements" }, { label: "pool", field: "pool_statements" }] },
        ],
      },
    ],
  },
  {
    id: "evaluations",
    title: "Evaluations",
    families: ["fixed_targets"],
    sections: [
      {
        title: "Fixed targets",
        charts: [
          FIXED.probe,
          FIXED.probeBands,
          FIXED.minif2f,
          FIXED.heldOut,
          { ...FIXED.math, compare: true, series: [{ label: "visible", field: "math500_visible" }] },
          { ...FIXED.math, title: "MATH-500 thinking", thresholds: [], compare: true, series: [{ label: "thinking", field: "math500_thinking" }] },
        ],
      },
      { title: "Table", table: "fixed_targets" },
    ],
  },
  {
    id: "system",
    title: "System",
    families: ["system", "status", "timing"],
    sections: [
      {
        title: "GPUs",
        charts: [
          { title: "GPU utilization", family: "system", unit: "percent", wide: true, yMin: 0, yMax: 100, series: [{ expand: "gpu_utilization.", label: "GPU" }] },
          { title: "GPU memory used", family: "system", unit: "gib", yMin: 0, series: [{ expand: "gpu_memory_used_gib.", label: "GPU" }] },
          { title: "GPU power", family: "system", unit: "number", yMin: 0, series: [{ expand: "gpu_power_watts.", label: "GPU" }] },
        ],
      },
      {
        title: "CPU and memory",
        charts: [
          {
            title: "CPU cores", family: "system", unit: "cores", yMin: 0,
            series: [
              { label: "available", field: "cpu_cores_available" },
              { label: "all processes", field: "cpu_cores_used" },
              { label: "Lean REPLs", field: "lean_cores_used" },
            ],
          },
          { title: "CPU throttled", subtitle: "share of cgroup periods", family: "system", unit: "share", series: [{ label: "throttled", field: "cpu_throttled_fraction" }] },
          { title: "Memory used", family: "system", unit: "gib", series: [{ label: "anonymous", field: "memory_used_gib" }] },
          {
            title: "Disk", subtitle: "the fullest filesystem of the run and its checkpoints", family: "system", unit: "gib", yMin: 0,
            series: [{ label: "size", field: "disk_total_gib" }, { label: "free", field: "disk_free_gib" }],
          },
          { title: "Cost so far", family: "system", unit: "dollars", series: [{ label: "spent", field: "cost_so_far" }] },
        ],
      },
      {
        title: "Loop throughput",
        charts: [
          { title: "Proofs per hour", family: "status", unit: "number", compare: true, series: [{ label: "proofs", field: "proofs_per_hour" }] },
          { title: "Statements per hour", family: "status", unit: "number", series: [{ label: "statements", field: "statements_per_hour" }] },
          { title: "Searches running", family: "status", unit: "count", series: [{ label: "searches", field: "searches_running" }] },
          {
            title: "Phase time", subtitle: "share of each phase: sampling, then the pause (training, publishing, evaluations)", family: "timing", kind: "stacked", unit: "seconds",
            series: [
              { label: "sampling", field: "sampling_seconds" },
              { label: "training", field: "training_seconds" },
              { label: "publishing", field: "publishing_seconds" },
              { label: "evaluations", field: "evaluation_seconds" },
            ],
          },
          {
            title: "Pause segments", subtitle: "share of each phase's pause before its evaluations", family: "timing", kind: "stacked", unit: "seconds", wide: true,
            series: [
              { label: "drain and sleep", fields: ["pause.drain_seconds", "pause.server_sleep_seconds"] },
              { label: "trainer start", field: "pause.trainer_start_seconds" },
              { label: "preparation", field: "pause.preparation_seconds" },
              { label: "load and compile", fields: ["pause.policy_load_seconds", "pause.compile_seconds"] },
              { label: "scoring", field: "pause.scoring_seconds" },
              { label: "policy training", field: "pause.policy_training_seconds" },
              { label: "value training", field: "pause.value_training_seconds" },
              { label: "gate", field: "pause.gate_seconds" },
              { label: "merge and write", fields: ["pause.merge_seconds", "pause.write_seconds"] },
              { label: "publish, wake, resume", fields: ["pause.publish_seconds", "pause.wake_seconds", "pause.resume_seconds"] },
            ],
          },
        ],
      },
    ],
  },
];
