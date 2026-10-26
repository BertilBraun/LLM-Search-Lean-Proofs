// The dashboard's pages as data. A chart is one object here; fields are the dotted column names of a family
// (nested dataclasses and dicts flattened, list items as .0, .1). Every page also lists all columns of its families.
//
// series: {label, field} | {label, fields: [...]} (summed) | {label, mean: "prefix."} | {label, sum: "prefix.", suffix}
//         | {expand: "prefix.", label} (one series per column), optionally {over: "field" | "prefix."} (a ratio)
// chart:  {title, family, kind: "line" | "stacked" | "bands" | "reliability", x: "time" | "policy_version" | ...,
//          unit, series, compare (overlay the other runs), baseline (first value as a reference), allTime,
//          thresholds: [{key, label}] (from the config), band: {low, high} (keys), yMin, yMax, wide}

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
    title: "Groups with mixed rewards", subtitle: "groups that carry a signal", family: "grpo", unit: "share",
    thresholds: [{ key: "min_mixed_group_share", label: "min" }], compare: true,
    series: [{ label: "mixed", field: "mixed_reward_group_share" }],
  },
  rewards: {
    title: "Mean reward, local vs global", family: "grpo", unit: "number",
    series: [{ label: "local", field: "mean_local_reward" }, { label: "global (β·G)", field: "mean_global_reward" }],
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
  loops: {
    title: "Forced answers and repetition loops", subtitle: "per policy sample", family: "search", unit: "share",
    thresholds: [{ key: "max_repetition_loop_share", label: "max loops" }],
    series: [
      { label: "forced at the cap", field: "forced_answers", over: SAMPLES },
      { label: "repetition loops", field: "repetition_loops", over: SAMPLES },
    ],
  },
};

const VALUE = {
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
      { title: "Fixed targets", charts: [FIXED.minif2f, FIXED.heldOut, FIXED.math] },
      { title: "RL health", charts: [GRPO.kl, GRPO.clip, GRPO.mixed, GRPO.rewards] },
      { title: "Value health", charts: [VALUE.ranking, VALUE.calibration] },
      { title: "Search behaviour", charts: [SEARCH.samples, SEARCH.noProgress, SEARCH.loops] },
    ],
  },
  {
    id: "policy",
    title: "Policy / GRPO",
    families: ["grpo"],
    sections: [
      { title: "Stability", charts: [GRPO.kl, GRPO.clip] },
      {
        title: "Signal",
        charts: [
          GRPO.mixed,
          {
            title: "Mixed groups, dense vs outcome-only rewards", subtitle: "same searched groups", family: "search", unit: "share",
            series: [
              { label: "dense", field: "graph.groups_with_mixed_rewards", over: "graph.groups" },
              { label: "outcome only", field: "graph.outcome_groups_with_mixed_rewards", over: "graph.groups" },
            ],
          },
          GRPO.rewards,
          {
            title: "Local reward earned off the proof graph", subtitle: "share of positive local reward", family: "grpo", unit: "share",
            compare: true, series: [{ label: "off proof graph", field: "off_proof_graph_local_reward_share" }],
          },
        ],
      },
      {
        title: "Outputs and training",
        charts: [
          { title: "Explanation length", family: "grpo", unit: "number", compare: true, series: [{ label: "tokens", field: "mean_explanation_tokens" }] },
          { title: "Block length", subtitle: "top-level tactics per sample", family: "grpo", unit: "number", compare: true, series: [{ label: "tactics", field: "mean_block_tactics" }] },
          { title: "Policy loss", family: "grpo", unit: "number", series: [{ label: "loss", field: "policy_loss" }] },
          { title: "Training time per phase", family: "grpo", unit: "seconds", series: [{ label: "training", field: "training_seconds" }] },
          { title: "Groups per phase", family: "grpo", unit: "count", series: [{ label: "groups", field: "groups" }, { label: "samples", field: "group_samples" }] },
        ],
      },
    ],
  },
  {
    id: "value",
    title: "Value",
    families: ["value"],
    sections: [
      {
        title: "Benchmark",
        charts: [
          {
            title: "Proof-graph state ranked above its siblings", family: "value", unit: "share",
            series: [
              { label: "all", field: "benchmark.ranking.pairwise_accuracy" },
              { label: "over dead end", field: "benchmark.ranking.over_dead_end_accuracy" },
              { label: "over expanded", field: "benchmark.ranking.over_expanded_accuracy" },
              { label: "over never expanded", field: "benchmark.ranking.over_never_expanded_accuracy" },
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
          {
            title: "A/B search, value swapped", subtitle: "miniF2F-valid solved, policy fixed", family: "value", unit: "count",
            series: [{ label: "candidate", field: "ab_solved_candidate" }, { label: "current", field: "ab_solved_current" }],
          },
          { title: "Gate passed", subtitle: "1 = published", family: "value", unit: "number", dots: true, yMin: 0, yMax: 1, series: [{ label: "passed", field: "gate_passed" }] },
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
              { label: "dead end", field: "graph.dead_end_targets" },
              { label: "averaged", field: "graph.averaged_targets" },
              { label: "expanded, no target", field: "graph.expanded_without_target" },
            ],
          },
          {
            title: "Subtree behind averaged targets", subtitle: "mean expanded descendants", family: "search", unit: "number",
            series: [{ label: "descendants", field: "graph.averaged_descendants.total_size", over: "graph.averaged_targets" }],
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
          { title: "Block length", subtitle: "top-level tactics per block", family: "search", unit: "number", series: [{ label: "tactics", field: "mean_block_tactics" }] },
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
    families: ["system", "status"],
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
          { title: "Cost so far", family: "system", unit: "dollars", series: [{ label: "spent", field: "cost_so_far" }] },
        ],
      },
      {
        title: "Loop throughput",
        charts: [
          { title: "Proofs per hour", family: "status", unit: "number", compare: true, series: [{ label: "proofs", field: "proofs_per_hour" }] },
          { title: "Statements per hour", family: "status", unit: "number", series: [{ label: "statements", field: "statements_per_hour" }] },
          { title: "Searches running", family: "status", unit: "count", series: [{ label: "searches", field: "searches_running" }] },
        ],
      },
    ],
  },
];
