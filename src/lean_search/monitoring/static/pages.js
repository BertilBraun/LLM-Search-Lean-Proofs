// The dashboard's pages as data. A chart is one object here; fields are the dotted column names of a family
// (nested dataclasses and dicts flattened, list items as .0, .1). Every page also lists all columns of its families.
//
// series: {label, field} | {label, fields: [...]} (summed) | {label, mean: "prefix."} | {label, sum: "prefix.", suffix}
//         | {expand: "prefix.", label} (one series per column), optionally {over: "field" | "prefix."} (a ratio)
//         and dashed: true (a threshold, drawn dashed)
// chart:  {title, family, kind: "line" | "stacked" | "bands" | "reliability" | "histogram", x: "time" | "policy_version"
//          | "value_version" | "phase" | a numeric field such as "probe_slot", unit, series, compare (overlay the other
//          runs), baseline (first value as a reference), allTime, thresholds: [{key, label}] (from the config),
//          references: [{value, label, kind}], band: {low, high} (keys), yMin, yMax, wide}
// histogram (latest records): categories, at (the caption's context field, default "phase"),
//          series: [{label, path, family, normalize, detail: {name: key}}]
// reliability (latest records): at, curves: [{label, path, family}] to lists of reliability bins

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

const STRATA = ["easy", "medium", "hard"];

const FIXED = {
  minif2f: {
    title: "miniF2F-valid solved", subtitle: "fixed search budget, by policy version; dashed: control run",
    family: "fixed_targets", x: "policy_version", unit: "count", compare: true, baseline: true, allTime: true,
    series: [{ label: "solved", field: "minif2f_valid_solved" }],
  },
  heldOut: {
    title: "Held-out states, per-sample success", subtitle: "512 states, by policy version",
    family: "fixed_targets", x: "policy_version", unit: "share", compare: true, baseline: true, allTime: true,
    series: [{ label: "success", field: "held_out_success" }, { label: "valid Lean", field: "held_out_valid_rate" }],
  },
  probe: {
    title: "Probe set solve rate",
    subtitle: "16 expansions, value v0; each slot a stratified third, the curve the last three slots (the whole set)",
    family: "fixed_targets", x: "probe_slot", unit: "share", compare: true, allTime: true,
    series: [
      { label: "slot (a third)", field: "probe_solved", over: "probe_problems" },
      { label: "last three slots", field: "probe_rolling_solved", over: "probe_rolling_problems" },
    ],
  },
  probeDifference: {
    title: "Probe set against version 0",
    subtitle: "each slot's solve rate minus version 0's two runs of the same third (the thirds' difficulty cancels), and its mean over the last three slots",
    family: "fixed_targets", x: "probe_slot", unit: "share", compare: true, allTime: true,
    references: [{ value: 0, label: "version 0", kind: "baseline" }],
    series: [
      { label: "slot minus v0", field: "probe_baseline_difference" },
      { label: "last three slots", field: "probe_rolling_baseline_difference" },
    ],
  },
  probeBands: {
    title: "Probe set by difficulty, last three slots", subtitle: "solve rate per stratum over the whole set",
    family: "fixed_targets", x: "probe_slot", unit: "share", compare: true, allTime: true,
    series: STRATA.map((stratum) => ({
      label: stratum, field: `probe_rolling_by_difficulty.${stratum}.solved`, over: `probe_rolling_by_difficulty.${stratum}.attempts`,
    })),
  },
  probeSlotBands: {
    title: "Probe set by difficulty, per slot", subtitle: "solve rate per stratum of each slot's third",
    family: "fixed_targets", x: "probe_slot", unit: "share", allTime: true, dots: true,
    series: STRATA.map((stratum) => ({
      label: stratum, field: `probe_by_difficulty.${stratum}.solved`, over: `probe_by_difficulty.${stratum}.attempts`,
    })),
  },
  probeNoise: {
    title: "Probe run-to-run noise", subtitle: "version 0, each part searched twice: second run minus first, and problems solved by one run only",
    family: "fixed_targets", x: "probe_part", unit: "count", allTime: true, dots: true,
    series: [{ label: "difference", field: "probe_repeat_difference" }, { label: "solved by one run", field: "probe_repeat_discordant" }],
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
    series: [{ label: "clip", field: "clip_fraction" }],
  },
  ratioBySign: {
    title: "Probability ratio by advantage sign",
    subtitle: "to the phase-start policy, per trained token; positive should rise above 1 and negative fall below", family: "grpo", unit: "number",
    series: [1, 2].flatMap((pass) => [
      { label: `pass ${pass} positive`, field: `ratios_by_pass.${pass}.positive.mean_ratio` },
      { label: `pass ${pass} negative`, field: `ratios_by_pass.${pass}.negative.mean_ratio` },
    ]),
  },
  clipBySign: {
    title: "Clip fraction by advantage sign", subtitle: "share of the trained tokens of each sign whose clip binds", family: "grpo", unit: "share",
    series: [1, 2].flatMap((pass) => [
      { label: `pass ${pass} positive`, field: `ratios_by_pass.${pass}.positive.clip_fraction` },
      { label: `pass ${pass} negative`, field: `ratios_by_pass.${pass}.negative.clip_fraction` },
    ]),
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
const DEAD_BIN = VALUE_BINS.length - 1;
const DEAD_TENTHS = Array.from({ length: 10 }, (_, index) => `${index / 10}–${(index + 1) / 10}`);
const ALIVE_STEPS = Array.from({ length: 11 }, (_, index) => `${index + 1}–${index + 2}`);
const SOURCES = [
  { label: "proof graph", key: "proof_graph" },
  { label: "off graph, solved trees", key: "off_graph_solved_trees" },
  { label: "off graph, unsolved trees", key: "off_graph_unsolved_trees" },
];
const PREDICTIONS = [
  ...SOURCES.map(({ label, key }) => ({ label, prefix: `metrics.predictions.${key}` })),
  { label: "never-expanded frontier", prefix: "metrics.frontier" },
];
const predictionSeries = (field, normalize) =>
  PREDICTIONS.map(({ label, prefix }) => ({ label, path: `${prefix}.${field}`, normalize, detail: { states: "states" } }));
const interval = (prefix, label) => [
  { label: `${label} lower`, field: `${prefix}.lower` },
  { label, field: `${prefix}.difference` },
  { label: `${label} upper`, field: `${prefix}.upper` },
];
const ZERO = [{ value: 0, label: "0", kind: "threshold" }];

const VALUE = {
  share: {
    title: "μ in effect", subtitle: "value share of the reward and the value targets; set by hand (grpo_loop.sh value-share)",
    family: "value_phase", x: "phase", unit: "number", allTime: true, yMin: 0,
    series: [{ label: "μ", field: "value_share" }],
  },
  benchmarkPairs: {
    title: "Benchmark: sibling pairs ordered by h", subtitle: "share whose proof-graph child gets the lower h, per served value model; baseline v0",
    family: "value_benchmark", x: "value_version", unit: "share", allTime: true, baseline: true,
    series: [{ label: "pairs ordered by h", field: "pairs.share" }],
  },
  benchmarkVersusV0: {
    title: "Benchmark: gain over v0", subtitle: "pairs ordered by h, minus v0's; 95% paired cluster bootstrap over problems",
    family: "value_benchmark", x: "value_version", unit: "share", allTime: true, references: ZERO,
    series: interval("against_reference", "against v0"),
  },
  benchmarkVersusPrevious: {
    title: "Benchmark: gain over the previous value model", subtitle: "pairs ordered by h, minus the value model served before; 95% interval",
    family: "value_benchmark", x: "value_version", unit: "share", allTime: true, references: ZERO,
    series: interval("against_previous", "against the previous"),
  },
  benchmarkSeparation: {
    title: "Benchmark: dead/live separation and calibration", subtitle: "fresh scores of each served value model",
    family: "value_benchmark", x: "value_version", unit: "number", allTime: true,
    series: [
      { label: "AUC proof graph vs dead ends", field: "metrics.separation.proof_graph_over_dead_end_auc" },
      { label: "Brier, expanded states", field: "calibration.brier_score" },
      { label: "ECE, expanded states", field: "calibration.expected_calibration_error" },
    ],
  },
  benchmarkSteps: {
    title: "Benchmark: remaining steps", subtitle: "proof-graph states: Spearman and mean absolute error",
    family: "value_benchmark", x: "value_version", unit: "number", allTime: true,
    series: [
      { label: "Spearman", field: "metrics.steps.spearman" },
      { label: "MAE", field: "metrics.steps.mean_absolute_error" },
    ],
  },
  arm: {
    title: "Value arm: published minus v0, per value model", subtitle: "one arm per published value model, at the next probe slot: paired solve rate on that slot's third, exact McNemar interval",
    family: "value_arm", x: "slot", unit: "share", allTime: true, references: ZERO, dots: true,
    series: interval("this_slot", "this slot"),
  },
  armPooled: {
    title: "Value arm: pooled difference to v0", subtitle: "over the slots of the published value model and of every value model; exact interval",
    family: "value_arm", x: "slot", unit: "share", allTime: true, references: ZERO,
    series: [...interval("same_value_version", "this value model"), { label: "every value model", field: "all_value_versions.difference" }],
  },
  armTest: {
    title: "Value arm: worse than v0?", subtitle: "one-sided exact McNemar over the published value model's slots; below the line alerts",
    family: "value_arm", x: "slot", unit: "number", allTime: true, yMin: 0, yMax: 1,
    references: [{ value: 0.05, label: "0.05", kind: "threshold" }],
    series: [{ label: "p (worse)", field: "same_value_version.worse_p_value" }, { label: "p (better)", field: "same_value_version.better_p_value" }],
  },
  armSolved: {
    title: "Value arm: problems solved", subtitle: "the slot's third, same policy version", family: "value_arm", x: "slot", unit: "count", allTime: true, dots: true,
    series: [{ label: "published value model", field: "published_solved" }, { label: "v0", field: "reference_solved" }],
  },
  phaseCalibration: {
    title: "Calibration per phase", subtitle: "recorded proof probability against z on the phase's expanded states", family: "value_phase", unit: "number",
    series: [
      { label: "ECE", field: "metrics.calibration.expected_calibration_error" },
      { label: "Brier", field: "metrics.calibration.brier_score" },
    ],
  },
  phaseSteps: {
    title: "Remaining steps per phase", subtitle: "recorded expected steps given alive against the proof graph's exact steps", family: "value_phase", unit: "number",
    series: [
      { label: "Spearman", field: "metrics.steps.spearman" },
      { label: "MAE", field: "metrics.steps.mean_absolute_error" },
    ],
  },
  phaseDead: {
    title: "p_dead per phase: labels and predictions", subtitle: "dead mass of the targets and mean recorded p_dead of the same states",
    family: "value_phase", unit: "share",
    series: SOURCES.flatMap(({ label, key }) => [
      { label: `${label}, label`, field: `metrics.labels.${key}.bins.${DEAD_BIN}` },
      { label: `${label}, predicted`, field: `metrics.predictions.${key}.mean_bins.${DEAD_BIN}` },
    ]),
  },
};

const EXPANSION_BUCKETS = ["1", "2", "3-4", "5-8", "9-16", "17-24", "25-32", "33-48", "49-64", "65+"];
const PROOF_STEP_BUCKETS = ["1", "2", "3", "4-5", "6-8", "9+"];
// A threshold the loop judged the phase against (the `health` family's thresholds.*), drawn dashed.
const limit = (label, field) => ({ label, field: `thresholds.${field}`, dashed: true });

const HEALTH = {
  kl: {
    title: "KL to the starting policy", subtitle: "per token (k3), last pass; dashed: the alert threshold", family: "health", x: "phase", unit: "number",
    series: [{ label: "KL", field: "measured.kl_to_starting_policy" }, limit("max", "max_kl_to_starting_policy")],
  },
  clip: {
    title: "Clip fraction", subtitle: "last pass's trained tokens", family: "health", x: "phase", unit: "share",
    series: [{ label: "clip", field: "measured.clip_fraction" }, limit("max", "max_clip_fraction")],
  },
  distinct: {
    title: "Distinct samples per expansion", subtitle: "of n = 8: blocks (identical ones run once) and texts; a fall is collapse", family: "health", x: "phase", unit: "number",
    series: [
      { label: "blocks", field: "measured.distinct_samples_per_expansion" },
      { label: "texts", field: "measured.distinct_texts_per_expansion" },
      limit("min blocks", "min_distinct_samples_per_expansion"),
    ],
  },
  heldOut: {
    title: "Held-out states", subtitle: "per sample, after the phases they ran; dashed: alert and collapse thresholds (fractions of version 0's; a collapse rolls back)", family: "health", x: "phase", unit: "share",
    series: [
      { label: "valid Lean", field: "measured.held_out_valid_rate" },
      { label: "success", field: "measured.held_out_success" },
      limit("min valid", "min_held_out_valid_rate"),
      limit("collapse", "stop_held_out_valid_rate"),
      limit("min success", "min_held_out_success"),
    ],
  },
  validBlocks: {
    title: "Sampled blocks' valid Lean", subtitle: "share of the phase's policy blocks that ran completely, free every phase; below the dashed line the held-out states run at the next pause", family: "health", x: "phase", unit: "share",
    series: [{ label: "valid", field: "measured.valid_block_rate" }, limit("min", "min_valid_block_rate")],
  },
  explanation: {
    title: "Explanation length", subtitle: "trained samples' explanation tokens; dashed: the band around the first phases", family: "health", x: "phase", unit: "number",
    series: [
      { label: "tokens", field: "measured.mean_explanation_tokens" },
      limit("min", "min_explanation_tokens"),
      limit("max", "max_explanation_tokens"),
    ],
  },
  cutOff: {
    title: "Samples cut off at the token cap", subtitle: "share of policy samples (answers forced), and repetition loops among them", family: "health", x: "phase", unit: "share",
    series: [
      { label: "cut off", field: "measured.cut_off_share" },
      { label: "repetition loops", field: "measured.repetition_loop_share" },
      limit("max cut off", "max_cut_off_share"),
    ],
  },
};

const BUDGET = {
  lateSolves: {
    title: "Solves in the budget's last quarter", subtitle: "share of solved searches (expansions 25-32 of 32); pooled over the last phases against its threshold", family: "budget", x: "phase", unit: "share",
    series: [
      { label: "this phase", field: "late_solve_share" },
      { label: "last phases", field: "recent_late_solve_share" },
      { label: "max", field: "max_late_solve_share", dashed: true },
    ],
  },
  expansions: {
    title: "Expansions to the first proof", subtitle: "share of solved searches per bucket", family: "budget", x: "phase", kind: "stacked",
    series: EXPANSION_BUCKETS.map((bucket) => ({ label: bucket, field: `expansions_to_solve.${bucket}` })),
  },
  meanExpansions: {
    title: "Mean expansions to the first proof", subtitle: "against the budget", family: "budget", x: "phase", unit: "number",
    series: [{ label: "mean", field: "mean_expansions_to_solve" }, { label: "budget", field: "expansion_budget", dashed: true }],
  },
  proofSteps: {
    title: "Proof length of solved searches", subtitle: "top-level tactics of the shortest proof on the proof graph", family: "budget", x: "phase", kind: "stacked",
    series: PROOF_STEP_BUCKETS.map((bucket) => ({ label: bucket, field: `proof_steps.${bucket}` })),
  },
  meanProofSteps: {
    title: "Mean proof length", subtitle: "top-level tactics; should not shrink while harder proofs are still found", family: "budget", x: "phase", unit: "number",
    series: [{ label: "tactics", field: "mean_proof_steps" }],
  },
  difficulty: {
    title: "Difficulty of solved statements", subtitle: "the curriculum's estimate; should rise with the band", family: "budget", x: "phase", unit: "number",
    series: [
      { label: "solved, mean", field: "mean_difficulty_solved" },
      { label: "solved, median", field: "median_difficulty_solved" },
      { label: "solved, p90", field: "p90_difficulty_solved" },
      { label: "searched, mean", field: "mean_difficulty_searched" },
    ],
  },
  groups: {
    title: "Trainable groups per phase", subtitle: "the phase trigger's count (min_trainable_groups) and the solved searches behind it", family: "budget", x: "phase", unit: "count",
    series: [{ label: "trainable groups", field: "trainable_groups" }, { label: "solved searches", field: "solved_trees" }],
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
      { title: "Fixed targets", charts: [FIXED.probeDifference, FIXED.probe, FIXED.minif2f, FIXED.heldOut, FIXED.math] },
      { title: "RL health", charts: [GRPO.kl, GRPO.clip, GRPO.mixed, GRPO.rewards] },
      { title: "Training health", charts: [HEALTH.kl, HEALTH.heldOut, HEALTH.distinct, BUDGET.lateSolves] },
      { title: "Value health", charts: [VALUE.share, VALUE.benchmarkVersusV0, VALUE.armPooled, VALUE.phaseCalibration] },
      { title: "Search behaviour", charts: [SEARCH.samples, SEARCH.noProgress, SEARCH.continuation, SEARCH.loops] },
    ],
  },
  {
    id: "policy",
    title: "Policy / GRPO",
    families: ["grpo"],
    sections: [
      { title: "Stability", charts: [GRPO.kl, GRPO.clip, GRPO.ratioBySign, GRPO.clipBySign, GRPO.sampler, GRPO.samplerByAge, GRPO.currentTokens] },
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
    families: ["value_phase", "value_benchmark", "value_arm", "value_training"],
    sections: [
      { title: "Value share (mu)", charts: [VALUE.share] },
      {
        title: "Benchmark trend (every served value model, scored through the value servers)",
        charts: [
          VALUE.benchmarkPairs,
          VALUE.benchmarkVersusV0,
          VALUE.benchmarkVersusPrevious,
          {
            title: "Pairs behind the benchmark", subtitle: "labelled sibling pairs, their problems, and the independent pairs they are worth (against v0)",
            family: "value_benchmark", x: "value_version", unit: "count", allTime: true,
            series: [
              { label: "pairs", field: "pairs.pairs" },
              { label: "problems", field: "pairs.problems" },
              { label: "effective pairs", field: "against_reference.effective_pairs" },
              { label: "ordered differently from v0", field: "against_reference.discordant_pairs" },
            ],
          },
          VALUE.benchmarkSeparation,
          VALUE.benchmarkSteps,
          {
            title: "Benchmark: sibling pairs by kind", subtitle: "both siblings labelled; never-expanded ones excluded",
            family: "value_benchmark", x: "value_version", unit: "share", allTime: true,
            series: [
              { label: "proof graph over dead end", field: "metrics.ranking.proof_over_dead_end.accuracy" },
              { label: "proof graph over expanded", field: "metrics.ranking.proof_over_expanded.accuracy" },
              { label: "expanded over dead end", field: "metrics.ranking.expanded_over_dead_end.accuracy" },
            ],
          },
        ],
      },
      { title: "Value arm (paired probe slots, published value model vs v0)", charts: [VALUE.arm, VALUE.armPooled, VALUE.armTest, VALUE.armSolved] },
      {
        title: "Per phase, from the training searches (free)",
        charts: [
          VALUE.phaseCalibration,
          VALUE.phaseSteps,
          VALUE.phaseDead,
          {
            title: "Label distribution, latest phase", subtitle: "the phase's value targets per bin (exact steps, unsmoothed), by source", kind: "histogram",
            family: "value_phase", categories: VALUE_BINS,
            series: SOURCES.map(({ label, key }) => ({ label, path: `metrics.labels.${key}.bins`, detail: { targets: "targets", weight: "weight" } })),
          },
          {
            title: "Predicted distribution, latest phase", subtitle: "mean recorded probability per bin of the same states, and of the frontier", kind: "histogram",
            family: "value_phase", categories: VALUE_BINS, series: predictionSeries("mean_bins", false),
          },
          { title: "Predicted p_dead, latest phase", subtitle: "share of states per tenth", kind: "histogram", family: "value_phase", categories: DEAD_TENTHS, series: predictionSeries("dead_histogram", true) },
          { title: "Expected steps given alive, latest phase", subtitle: "share of states per step", kind: "histogram", family: "value_phase", categories: ALIVE_STEPS, series: predictionSeries("alive_steps_histogram", true) },
          {
            title: "Calibration on expanded states", subtitle: "predicted proof probability against z (1 on the proof graph); diagonal = calibrated", kind: "reliability",
            family: "value_phase",
            curves: [
              { label: "served, latest phase", path: "metrics.calibration.bins" },
              { label: "latest served model, benchmark", path: "calibration.bins", family: "value_benchmark" },
            ],
          },
          {
            title: "Benchmark predictions, latest served model", subtitle: "mean probability per bin on every benchmark state", kind: "histogram",
            family: "value_benchmark", at: "value_version", categories: VALUE_BINS,
            series: [{ label: "benchmark", path: "predictions.mean_bins", detail: { states: "states" } }],
          },
        ],
      },
      {
        title: "Retraining (every 4 phases on the last 8 phases' trees)",
        charts: [
          { title: "Value training loss", family: "value_training", x: "phase", unit: "number", allTime: true, series: [{ label: "loss", field: "training_loss" }] },
          { title: "Window trees", family: "value_training", x: "phase", unit: "count", allTime: true, series: [{ label: "trees", field: "trees" }] },
          {
            title: "Label distribution of the latest retrain", subtitle: "the window's targets per bin (smoothed as trained), by source, and the v0 replay", kind: "histogram",
            family: "value_training", categories: VALUE_BINS,
            series: [
              ...SOURCES.map(({ label, key }) => ({ label, path: `labels.${key}.bins`, detail: { targets: "targets", weight: "weight" } })),
              { label: "v0 replay", path: "replay_labels.bins", detail: { targets: "targets", weight: "weight" } },
            ],
          },
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
    id: "training",
    title: "Training",
    families: ["health", "budget"],
    sections: [
      { title: "Health checks", charts: [HEALTH.kl, HEALTH.clip, HEALTH.heldOut, HEALTH.validBlocks, HEALTH.distinct, HEALTH.explanation, HEALTH.cutOff] },
      {
        title: "Search budget",
        charts: [BUDGET.lateSolves, BUDGET.expansions, BUDGET.meanExpansions, BUDGET.proofSteps, BUDGET.meanProofSteps, BUDGET.difficulty, BUDGET.groups],
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
          FIXED.probeDifference,
          FIXED.probe,
          FIXED.probeBands,
          FIXED.probeSlotBands,
          FIXED.probeNoise,
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
              { label: "merge and write", fields: ["pause.merge_seconds", "pause.write_seconds"] },
              { label: "park and handoff", fields: ["pause.park_seconds", "pause.handoff_seconds"] },
              { label: "publish, wake, resume", fields: ["pause.publish_seconds", "pause.wake_seconds", "pause.resume_seconds"] },
            ],
          },
        ],
      },
    ],
  },
];
