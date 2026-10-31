import { PAGES } from "./pages.js";
import {
  barChart,
  chartCard,
  formatAge,
  formatTime,
  formatValue,
  groupedBarChart,
  htmlElement,
  lineChart,
  sparkline,
  stackedChart,
} from "./charts.js";

const RANGES = [
  { label: "6 h", seconds: 6 * 3600 },
  { label: "24 h", seconds: 86400 },
  { label: "3 d", seconds: 3 * 86400 },
  { label: "7 d", seconds: 7 * 86400 },
  { label: "All", seconds: 0 },
];
const THEMES = ["auto", "light", "dark"];
const X_NAMES = {
  policy_version: "policy v",
  value_version: "value v",
  phase: "phase ",
  probe_slot: "slot ",
  slot: "slot ",
  probe_part: "part ",
};

// The probe rating's logits on the Elo scale (400 / ln 10 per logit).
const ELO = 400 / Math.LN10;
const DIFFICULTY_RATE = { sum: "by_difficulty.", suffix: ".solved", over: { sum: "by_difficulty.", suffix: ".attempts" } };

const state = {
  run: null,
  runs: {},
  main: null,
  range: Number(stored("range", "0")),
  theme: stored("theme", "auto"),
  explain: stored("explain", "on") === "on",
  sections: new Map(),
  overview: null,
  data: new Map(),
  openDetails: new Set(),
  timer: null,
  width: window.innerWidth,
  updatedAt: 0,
};

function stored(key, fallback) {
  try {
    return localStorage.getItem(`dashboard.${key}`) ?? fallback;
  } catch {
    return fallback;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(`dashboard.${key}`, value);
  } catch {
    // Private windows may refuse storage; the setting then lasts for this page only.
  }
}

async function fetchJson(url) {
  const response = await fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (response.status === 401) {
    window.location.href = "login";
    throw new Error("authentication required");
  }
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}

function sectionKey(page, section) {
  return `collapsed.${page.id}/${section.title}`;
}

// The reader's choice in this page load first, so that a toggle works where storage refuses writes.
function collapsed(page, section) {
  const key = sectionKey(page, section);
  return (state.sections.get(key) ?? stored(key, section.collapsed ? "yes" : "no")) === "yes";
}

function setCollapsed(page, section, closed) {
  const key = sectionKey(page, section);
  state.sections.set(key, closed ? "yes" : "no");
  store(key, closed ? "yes" : "no");
}

function currentPage() {
  const id = window.location.hash.replace(/^#\/?/, "") || "overview";
  return PAGES.find((page) => page.id === id) || PAGES[0];
}

function otherRuns() {
  return Object.keys(state.runs).filter((name) => name !== state.run);
}

function pointCount() {
  return window.innerWidth < 640 ? 180 : 360;
}

function dataKey(run, family, allTime) {
  return `${run}|${family}|${allTime ? "all" : state.range}`;
}

// The series each row of tiles reads ([family, all time]); their latest records come with the overview.
const TILE_FAMILIES = {
  headline: [["fixed_targets", true]],
  health: [["status", false], ["system", false], ["health", true], ["curriculum", true], ["fixed_targets", true]],
  operations: [["status", false], ["system", false], ["fixed_targets", true]],
};

function wantedSeries(page) {
  const wanted = new Map();
  const add = (run, family, allTime) => {
    if (state.runs[run] && state.runs[run].includes(family)) wanted.set(dataKey(run, family, allTime), { run, family, allTime });
  };
  for (const section of page.sections) {
    if (collapsed(page, section)) continue;
    for (const chart of section.charts || []) {
      if (!chart.family || chart.kind === "versions") continue;
      add(state.run, chart.family, chart.allTime);
      if (chart.compare) otherRuns().forEach((run) => add(run, chart.family, chart.allTime));
    }
    for (const [family, allTime] of TILE_FAMILIES[section.tiles] || []) add(state.run, family, allTime);
    if (section.table) add(state.run, section.table, true);
  }
  page.families.forEach((family) => add(state.run, family, false));
  return wanted;
}

async function loadData(page) {
  const wanted = wantedSeries(page);
  const since = state.range ? state.overview.now - state.range : null;
  const data = new Map();
  await Promise.all(
    [...wanted].map(async ([key, request]) => {
      const query = new URLSearchParams({ run: request.run, family: request.family, points: pointCount() });
      if (since !== null && !request.allTime) query.set("since", since.toFixed(0));
      data.set(key, await fetchJson(`api/series?${query}`));
    }),
  );
  state.data = data;
}

function series(run, family, allTime) {
  return state.data.get(dataKey(run, family, allTime)) || null;
}

function sumOfColumns(data, prefix, suffix = "") {
  const names = Object.keys(data.columns).filter((name) => name.startsWith(prefix) && name.endsWith(suffix));
  return data.time.map((_, index) => {
    let total = null;
    for (const name of names) {
      const value = data.columns[name][index];
      if (value !== null) total = (total || 0) + value;
    }
    return total;
  });
}

// A series spec, a column name, or a prefix ending in "." (summed), as one value per record.
function evaluate(data, spec) {
  if (typeof spec === "string") {
    return spec.endsWith(".") ? sumOfColumns(data, spec) : data.columns[spec] || data.time.map(() => null);
  }
  let values;
  if (spec.field) values = evaluate(data, spec.field);
  else if (spec.fields) {
    const parts = spec.fields.map((name) => evaluate(data, name));
    values = data.time.map((_, index) => {
      const present = parts.map((part) => part[index]).filter((value) => value !== null);
      return present.length ? present.reduce((sum, value) => sum + value, 0) : null;
    });
  } else if (spec.sum) values = sumOfColumns(data, spec.sum, spec.suffix || "");
  else if (spec.mean) {
    const names = Object.keys(data.columns).filter((name) => name.startsWith(spec.mean));
    values = data.time.map((_, index) => {
      const present = names.map((name) => data.columns[name][index]).filter((value) => value !== null);
      return present.length ? present.reduce((sum, value) => sum + value, 0) / present.length : null;
    });
  }
  if (spec.over) {
    const denominator = evaluate(data, spec.over);
    values = values.map((value, index) =>
      value !== null && denominator[index] ? value / denominator[index] : null,
    );
  }
  if (spec.scale) values = values.map((value) => (value === null ? null : value * spec.scale));
  return values;
}

// A version or phase of the line's context, else a numeric field of the record (e.g. a probe slot).
function xValues(data, axis) {
  if (!axis || axis === "time") return data.time;
  return data[axis] || data.columns[axis] || data.time.map(() => null);
}

function points(data, axis, values) {
  const xs = xValues(data, axis);
  const result = xs.map((x, index) => ({ x, y: values[index] })).filter((point) => point.x !== null);
  if (axis && axis !== "time") result.sort((first, second) => first.x - second.x);
  return result;
}

function expandedSpecs(data, spec) {
  if (!spec.expand) return [spec];
  return Object.keys(data.columns)
    .filter((name) => name.startsWith(spec.expand))
    .sort((first, second) => Number(first.slice(spec.expand.length)) - Number(second.slice(spec.expand.length)))
    .map((name) => ({ label: `${spec.label} ${name.slice(spec.expand.length)}`, field: name }));
}

function chartSeries(chart) {
  const main = series(state.run, chart.family, chart.allTime);
  if (!main) return [];
  const specs = chart.series.flatMap((spec) => expandedSpecs(main, spec));
  const result = specs.map((spec, slot) => ({ label: spec.label, slot, dashed: Boolean(spec.dashed), points: points(main, chart.x, evaluate(main, spec)) }));
  if (chart.compare) {
    for (const run of otherRuns()) {
      const other = series(run, chart.family, chart.allTime);
      if (!other) continue;
      specs.forEach((spec, slot) =>
        result.push({ label: `${spec.label} · ${run}`, slot, dashed: true, points: points(other, chart.x, evaluate(other, spec)) }),
      );
    }
  }
  return result;
}

function thresholdValue(key) {
  return state.overview.thresholds[key];
}

function renderChart(parent, chart) {
  const xKind = chart.x && chart.x !== "time" ? "version" : "time";
  const xLabel = xKind === "time" ? (x) => formatTime(x) : (x) => `${X_NAMES[chart.x] || ""}${x}`;
  const band = chart.band ? { low: thresholdValue(chart.band.low), high: thresholdValue(chart.band.high) } : null;
  switch (chart.kind) {
    case "stacked":
      return stackedChart(parent, { ...chart, xKind, xLabel, series: chartSeries(chart) });
    case "bands":
      return barChart(parent, { ...chart, band, bars: latestBands(chart) });
    case "reliability":
      return lineChart(parent, reliabilitySpec(chart));
    case "histogram":
      return groupedBarChart(parent, histogramSpec(chart));
    case "versions": {
      const built = versionSeries(chart);
      const references = [...chartReferences(chart, built), ...latestReferences(chart)];
      return lineChart(parent, { ...chart, xKind, xLabel, band, references, series: built });
    }
    default: {
      const built = chartSeries(chart);
      return lineChart(parent, { ...chart, xKind, xLabel, band, references: chartReferences(chart, built), series: built });
    }
  }
}

function chartReferences(chart, built) {
  const references = [...(chart.references || [])];
  references.push(...(chart.thresholds || []).map((threshold) => ({
    value: thresholdValue(threshold.key),
    label: `${threshold.label} ${formatValue(thresholdValue(threshold.key), chart.unit)}`,
    kind: "threshold",
  })));
  const first = built[0] && built[0].points.find((point) => point.y !== null);
  if (chart.baseline && first) {
    references.push({ value: first.y, label: `baseline ${formatValue(first.y, chart.unit)}`, kind: "baseline" });
  }
  return references;
}

// chart.latestReferences: [{path, label, scale}], lines at numbers of the chart family's latest record, when present.
function latestReferences(chart) {
  const fields = latestFields(chart.family);
  return (chart.latestReferences || [])
    .map((reference) => ({ ...reference, value: fields ? lookup(fields, reference.path) : undefined }))
    .filter((reference) => reference.value !== null && reference.value !== undefined)
    .map((reference) => {
      const value = reference.value * (reference.scale || 1);
      return { value, label: `${reference.label} ${signed(value)}`, kind: "baseline" };
    });
}

// A list field of an object at a budget's position: "last", or an index into the record's budgets.
function budgetValue(entry, spec, budgets) {
  const values = entry[spec.field] || [];
  return values[spec.budget === "last" ? budgets.length - 1 : spec.budget] ?? null;
}

// chart.path: a list of objects in the chart family's latest record, one point per object at its field chart.x.
function versionSeries(chart) {
  const fields = latestFields(chart.family);
  const entries = (fields && lookup(fields, chart.path)) || [];
  const budgets = (fields && fields.budgets) || [];
  return chart.series.map((spec, index) => ({
    label: spec.label,
    slot: spec.slot ?? index,
    dashed: Boolean(spec.dashed),
    points: entries
      .map((entry) => {
        const value = spec.budget === undefined ? lookup(entry, spec.field) : budgetValue(entry, spec, budgets);
        return { x: entry[chart.x], y: value === null || value === undefined ? null : value * (spec.scale || 1) };
      })
      .sort((first, second) => first.x - second.x),
  }));
}

function latestFields(family) {
  const latest = state.overview.latest[family];
  return latest ? latest.fields : null;
}

function latestBands(chart) {
  const fields = latestFields(chart.family);
  if (!fields) return [];
  const outcomes = fields[chart.prefix.replace(/\.$/, "")] || {};
  return Object.entries(outcomes).map(([label, outcome]) => ({
    label,
    value: outcome.attempts ? outcome.solved / outcome.attempts : null,
    detail: `${outcome.solved} / ${outcome.attempts} solved`,
  }));
}

// A dotted path into a latest record's fields; undefined where any part is missing.
function lookup(fields, path) {
  return path.split(".").reduce((value, key) => (value === null || value === undefined ? undefined : value[key]), fields);
}

// "phase 12; " for a chart of a family's latest record, from that record's context (chart.at, default the phase).
function latestCaption(chart, family) {
  const latest = state.overview.latest[family];
  const at = chart.at || "phase";
  return latest && latest[at] !== null && latest[at] !== undefined ? `${X_NAMES[at] || ""}${latest[at]}; ` : "";
}

// chart.curves: [{label, path, family}], each path to a list of reliability bins in the latest record of the curve's
// family (default the chart's).
function reliabilitySpec(chart) {
  const curves = chart.curves;
  const subtitle = `${latestCaption(chart, chart.family)}${chart.subtitle}`;
  const series = curves.map((curve, slot) => {
    const fields = latestFields(curve.family || chart.family);
    const bins = (fields && lookup(fields, curve.path)) || [];
    const known = bins.filter((bin) => bin.mean_predicted !== null && bin.mean_target !== null);
    return { label: curve.label, slot, markers: true, points: known.map((bin) => ({ x: bin.mean_predicted, y: bin.mean_target })) };
  });
  return {
    ...chart,
    subtitle,
    unit: "share",
    xKind: "continuous",
    xLabel: (x) => `predicted ${formatValue(x, "share")}`,
    yMin: 0,
    yMax: 1,
    diagonal: true,
    noLegend: curves.length < 2,
    series,
  };
}

// chart.series: [{label, path, family, normalize, detail: {count, weight}}], each path to a list of numbers (one per
// category) in the latest record of the series' family (default the chart's); `normalize` divides by their sum,
// `detail` names fields shown in the legend.
function histogramSpec(chart) {
  const subtitle = `${latestCaption(chart, chart.family)}${chart.subtitle}`;
  const series = chart.series.map((spec, slot) => {
    const fields = latestFields(spec.family || chart.family);
    const values = (fields && lookup(fields, spec.path)) || [];
    const total = values.reduce((sum, value) => sum + (value || 0), 0);
    const parent = fields && spec.detail ? lookup(fields, spec.path.split(".").slice(0, -1).join(".")) : null;
    const detail = parent ? Object.entries(spec.detail).map(([name, key]) => `${formatValue(parent[key], "number")} ${name}`).join(", ") : null;
    return {
      label: spec.label,
      slot,
      detail,
      values: values.map((value) => (spec.normalize ? (total ? value / total : null) : value)),
    };
  });
  return { ...chart, subtitle, unit: chart.unit || "share", series };
}

function lastValue(values) {
  if (!values) return null;
  for (let index = values.length - 1; index >= 0; index--) if (values[index] !== null) return values[index];
  return null;
}

function firstValue(values) {
  return values ? values.find((value) => value !== null) ?? null : null;
}

function recentMean(values, count) {
  const known = (values || []).filter((value) => value !== null).slice(-count);
  return known.length ? known.reduce((sum, value) => sum + value, 0) / known.length : null;
}

// why: what the value measures and what good looks like; the header's Explain button shows or hides it.
function tile(parent, { label, value, sub, status, spark, why }) {
  const card = htmlElement("div", "tile", null, parent);
  const head = htmlElement("div", "label", null, card);
  if (status) htmlElement("span", `status-icon ${status}`, null, head);
  htmlElement("span", "", label, head);
  htmlElement("div", "value", value, card);
  if (sub) htmlElement("div", "sub", sub, card);
  if (spark) sparkline(card, spark);
  if (why) htmlElement("div", "why", why, card);
}

function signed(value, digits = 0) {
  if (value === null || value === undefined) return "–";
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(digits)}`;
}

// A health measurement against its limit (a maximum or a minimum); null without either.
function limitStatus(value, limit, kind) {
  if (value === null || value === undefined || limit === null || limit === undefined) return null;
  return (kind === "max" ? value > limit : value < limit) ? "warning" : "good";
}

function knownValues(values) {
  return (values || []).filter((value) => value !== null);
}

// A difference with its 95% interval: good above 0, critical below, neutral while the interval holds 0 (no evidence
// either way yet).
function intervalStatus(lower, upper) {
  return lower > 0 ? "good" : upper < 0 ? "critical" : null;
}

function elo(value) {
  return `${signed(value * ELO)} Elo`;
}

function eloInterval(lower, upper) {
  return `95% ${signed(lower * ELO)} to ${signed(upper * ELO)}`;
}

function versionList(versions) {
  return versions.map((version) => `v${version}`).join(", ");
}

// The newest finished probe slot's time, to tell a rating that missed it.
function lastProbeTime(fixed) {
  if (!fixed || !fixed.columns.probe_solved) return null;
  for (let index = fixed.time.length - 1; index >= 0; index--) if (fixed.columns.probe_solved[index] !== null) return fixed.time[index];
  return null;
}

function headlineTiles(parent) {
  const grid = htmlElement("div", "tiles headline", null, parent);
  const latest = state.overview.latest;
  const fixed = series(state.run, "fixed_targets", true);
  const rating = latest.rating ? latest.rating.fields : null;
  if (rating) {
    const anchor = `v${rating.anchor_version}`;
    const probeTime = lastProbeTime(fixed);
    const stale = probeTime !== null && probeTime - latest.rating.time > 1800;
    const rated = `${rating.runs_rated} runs rated${rating.runs_unreadable ? `, ${rating.runs_unreadable} unreadable` : ""}, ${formatAge(state.overview.now - latest.rating.time)} ago${stale ? "; a newer probe slot is not rated yet" : ""}`;
    const pass = rating.latest_pass;
    tile(grid, {
      label: "Strength: the last full probe pass",
      status: stale ? "warning" : pass ? intervalStatus(pass.lower, pass.upper) : null,
      value: pass ? elo(pass.rating) : "–",
      sub: pass
        ? `${versionList(pass.policy_versions)} · ${eloInterval(pass.lower, pass.upper)} · ≈ ${formatValue(pass.projected_solved, "count")} of ${rating.problems} proved (${anchor} ${formatValue(rating.baseline_projected_solved, "count")}) · ${rated}`
        : `no full pass yet: every third needs a run of a version other than ${anchor} · ${rated}`,
      spark: rating.versions.filter((version) => !version.rejected).map((version) => version.rating * ELO),
      why: `The latest run on each third of the probe set (policy with its value model, ${rating.expansion_budget} expansions), pooled: the whole set, rated against ${anchor} at 0. +100 Elo is a 64% chance on a problem ${anchor} proves half the time; ≈ proved is the same on the whole set. Green: above ${anchor} beyond the noise. The line: each version's own rating (one third each, so noisier).`,
    });
    const previous = rating.against_previous;
    tile(grid, {
      label: "Change since the previous pass",
      status: previous ? intervalStatus(previous.lower, previous.upper) : null,
      value: previous ? elo(previous.difference) : "–",
      sub: previous
        ? `against ${versionList(previous.reference.policy_versions)} · ${eloInterval(previous.lower, previous.upper)} · ≈ ${formatValue(previous.reference.projected_solved, "count")} of ${rating.problems} then`
        : "needs two full passes of versions that were not rejected",
      why: "The latest pass against the pass before it, fitted together. This is the trend: green is better beyond the noise, red worse; grey means the two are not distinguishable yet, which is the normal state between passes.",
    });
    if (rating.reward_fix_version !== null) {
      const fix = rating.against_pre_fix;
      tile(grid, {
        label: "Reward fix: against the last pass before it",
        status: fix ? intervalStatus(fix.lower, fix.upper) : null,
        value: fix ? elo(fix.difference) : `${rating.post_fix_parts} of ${rating.parts} thirds`,
        sub: fix
          ? `against ${versionList(fix.reference.policy_versions)} · ${eloInterval(fix.lower, fix.upper)}`
          : `searched by v${rating.reward_fix_version} or later so far; compared once all ${rating.parts} are`,
        why: `The revert rule's test: the latest pass of versions trained with the reward fix (v${rating.reward_fix_version} on) against the last pass of versions before it. Red here, with bare claims not falling or blocks much shorter, means going back to the pre-fix version.`,
      });
    }
  } else {
    tile(grid, { label: "Strength: the last full probe pass", value: "–", sub: "no finished probe run rated yet" });
  }
  const health = latest.health ? latest.health.fields : null;
  if (fixed) {
    const success = knownValues(fixed.columns.held_out_success);
    tile(grid, {
      label: "Policy alone: held-out states",
      status: limitStatus(lastValue(success), health ? health.thresholds.min_held_out_success : null, "min"),
      value: formatValue(lastValue(success), "share"),
      sub: `success per sample · v0 ${formatValue(firstValue(success), "share")}`,
      spark: success,
      why: "512 fixed proof states, one block each, no search and no value model: the policy's step quality, apart from the value model. Good: rising; below the loop's limit warns.",
    });
  }
  const benchmark = latest.value_benchmark ? latest.value_benchmark.fields : null;
  const versus = benchmark ? benchmark.against_reference : null;
  if (versus && versus.difference !== null) {
    tile(grid, {
      label: "Value model: benchmark against v0",
      status: versus.upper < 0 ? "critical" : null,
      value: `${signed(versus.difference * 100, 1)} points`,
      sub: `value v${benchmark.value_version} · 95% ${signed(versus.lower * 100, 1)} to ${signed(versus.upper * 100, 1)} · ${versus.pairs} pairs`,
      why: "Sibling pairs the value model orders right (the proof-graph child first), minus v0's share. Too few pairs to separate small differences: only an interval wholly below 0 means anything, and it turns red.",
    });
  }
}

function healthTiles(parent) {
  const grid = htmlElement("div", "tiles health", null, parent);
  const now = state.overview.now;
  const thresholds = state.overview.thresholds;
  const latest = state.overview.latest;
  const status = latest.status;
  const health = latest.health ? latest.health.fields : null;
  if (status) {
    const alive = now - status.time <= thresholds.stale_heartbeats * status.fields.heartbeat_seconds;
    const published = status.fields.last_publish_time;
    const sincePublish = published === null ? null : now - published;
    const stale = sincePublish !== null && sincePublish > thresholds.max_minutes_since_publish * 60;
    const stopped = health && health.hard_stop;
    const rollback = health && health.rolled_back_to !== null && health.rolled_back_to !== undefined
      ? ` · rolled back to v${health.rolled_back_to} after phase ${health.phase}`
      : "";
    tile(grid, {
      label: "Loop",
      status: !alive || stopped ? "critical" : stale || rollback ? "warning" : "good",
      value: alive ? `${status.fields.state.replace(/^./, (letter) => letter.toUpperCase())}, phase ${status.phase ?? "–"}` : "Silent",
      sub: `policy v${status.policy_version ?? "–"} · published ${sincePublish === null ? "never" : `${formatAge(sincePublish)} ago`}${rollback}${stopped ? " · stopped by the health checks" : ""}`,
      why: `The heartbeat and the last publish: silent, or no publish for ${thresholds.max_minutes_since_publish} min, means the loop is stuck. A rollback or a hard stop of the latest phase shows here too.`,
    });
  } else {
    tile(grid, { label: "Loop", status: "critical", value: "No status", sub: "nothing written yet" });
  }
  const system = series(state.run, "system", false);
  if (system && latest.system) {
    const utilization = evaluate(system, { mean: "gpu_utilization." });
    const recent = recentMean(utilization, 5);
    const fields = latest.system.fields;
    tile(grid, {
      label: "GPUs",
      status: recent === null ? null : recent < thresholds.min_gpu_utilization ? "warning" : "good",
      value: formatValue(recent, "percent"),
      sub: `mean of ${fields.gpu_utilization.length} · spent ${formatValue(fields.cost_so_far, "dollars")} at ${formatValue(fields.hourly_price, "dollars")}/h`,
      spark: utilization,
      why: `Mean utilization of the last samples; below ${thresholds.min_gpu_utilization}% the node is paid for and idle.`,
    });
  }
  const healthSeries = series(state.run, "health", true);
  const fixed = series(state.run, "fixed_targets", true);
  if (fixed && health) {
    const valid = knownValues(fixed.columns.held_out_valid_rate);
    const validNow = lastValue(valid);
    const limits = health.thresholds;
    const below = (limit) => validNow !== null && limit !== null && limit !== undefined && validNow < limit;
    tile(grid, {
      label: "Held-out valid Lean",
      status: validNow === null ? null : below(limits.stop_held_out_valid_rate) ? "critical" : below(limits.min_held_out_valid_rate) ? "warning" : "good",
      value: formatValue(validNow, "share"),
      sub: `v0 ${formatValue(firstValue(valid), "share")} · warns below ${formatValue(limits.min_held_out_valid_rate, "share")}, rolls back below ${formatValue(limits.stop_held_out_valid_rate, "share")}`,
      spark: valid,
      why: "The share of the policy's blocks on the 512 held-out states that run completely in Lean. It is the rollback trigger: below the lower limit the loop publishes the last good version again.",
    });
  }
  if (health) {
    const measured = health.measured;
    const limits = health.thresholds;
    const belowBand = measured.below_band_bare_have_share ?? null;
    const bareHaves = belowBand ?? measured.bare_have_share;
    tile(grid, {
      label: "Bare claims",
      status: limitStatus(bareHaves, limits.max_bare_have_share, "max"),
      value: formatValue(bareHaves, "share"),
      sub: `${belowBand === null ? "all statements" : "statements below the band"}, limit ${formatValue(limits.max_bare_have_share, "share")} · all statements ${formatValue(measured.bare_have_share, "share")}`,
      spark: healthSeries?.columns[belowBand === null ? "measured.bare_have_share" : "measured.below_band_bare_have_share"],
      why: "Blocks opening with a bare `have h : A` that leaves the claim for later: the reward hack of phases 1-10. Judged on the statements below the band, nearest the first phases' difficulty. Good: falling back toward the first phases' share; the limit is 1.5 times it.",
    });
    const belowBandProved = measured.below_band_claim_proved_rate ?? null;
    const proved = belowBandProved ?? measured.claim_proved_rate;
    tile(grid, {
      label: "Claims proved",
      status: limitStatus(proved, limits.min_claim_proved_rate, "min"),
      value: formatValue(proved, "share"),
      sub: `${belowBandProved === null ? "all statements" : "statements below the band"}, limit ${formatValue(limits.min_claim_proved_rate, "share")} · all statements ${formatValue(measured.claim_proved_rate, "share")}`,
      spark: healthSeries?.columns[belowBandProved === null ? "measured.claim_proved_rate" : "measured.below_band_claim_proved_rate"],
      why: "Of the claims blocks leave open, the share proved later in the tree. A small ratio that moves a lot between phases: read the trend. Good: rising, as claims become real steps; below the limit warns.",
    });
    tile(grid, {
      label: "Drift from the start",
      status: limitStatus(measured.kl_to_starting_policy, limits.max_kl_to_starting_policy, "max"),
      value: formatValue(measured.kl_to_starting_policy, "number"),
      sub: `KL per token, limit ${formatValue(limits.max_kl_to_starting_policy, "number")} · phase ${health.phase}`,
      why: "How far training has moved the policy from the version it started from (a penalty in the loss pulls it back). A fast climb, or a climb past the limit, means the policy is leaving what it could do.",
    });
    tile(grid, {
      label: "Valid Lean of sampled blocks",
      status: limitStatus(measured.valid_block_rate, limits.min_valid_block_rate, "min"),
      value: formatValue(measured.valid_block_rate, "share"),
      sub: `limit ${formatValue(limits.min_valid_block_rate, "share")} · measured every phase`,
      spark: healthSeries?.columns["measured.valid_block_rate"],
      why: "The share of the phase's own policy blocks that run completely in Lean, free every phase. A drop means broken output; below the limit the held-out states run at the next pause.",
    });
  }
  const curriculum = latest.curriculum ? latest.curriculum.fields : null;
  const curriculumSeries = series(state.run, "curriculum", true);
  const cohort = curriculum && curriculum.by_origin ? curriculum.by_origin.band : null;
  if (curriculum) {
    const rate = cohort && cohort.attempts ? cohort.solved / cohort.attempts : null;
    const inBand = rate !== null && rate >= thresholds.min_solve_rate && rate <= thresholds.max_solve_rate;
    tile(grid, {
      label: "Curriculum band",
      status: rate === null ? null : inBand ? "good" : "warning",
      value: `${formatValue(curriculum.band_low, "number")}-${formatValue(curriculum.band_high, "number")}`,
      sub: `the band's cohort solved ${formatValue(rate, "share")} · ${formatValue(curriculum.verified_statements, "count")} verified statements`,
      spark: curriculumSeries ? curriculumSeries.columns.band_low : null,
      why: `The difficulty the curriculum feeds; it rises as the policy solves its band (kept at ${formatValue(thresholds.min_solve_rate, "share")}-${formatValue(thresholds.max_solve_rate, "share")} by design, so the rate says little). Not progress on its own: a band climbing while the probe passes do not was the drift of phases 1-10.`,
    });
  }
  const visible = fixed ? knownValues(fixed.columns.math500_visible) : [];
  if (visible.length) {
    const mathNow = lastValue(visible);
    const mathStart = firstValue(visible);
    tile(grid, {
      label: "MATH-500 visible",
      status: mathNow < thresholds.min_math500_visible ? "critical" : mathStart - mathNow > thresholds.max_math500_drop ? "warning" : "good",
      value: formatValue(mathNow, "share"),
      sub: `baseline ${formatValue(mathStart, "share")}; thinking ${formatValue(lastValue(fixed.columns.math500_thinking), "share")}`,
      spark: visible,
      why: "Plain math answers, outside Lean: whether training on proofs makes the model forget what it knew.",
    });
  }
}

function operationsTiles(parent) {
  const grid = htmlElement("div", "tiles", null, parent);
  const latest = state.overview.latest;
  const status = latest.status;
  const statusSeries = series(state.run, "status", false);
  const system = series(state.run, "system", false);
  const fixed = series(state.run, "fixed_targets", true);

  if (status) {
    tile(grid, {
      label: "Proofs per hour",
      value: formatValue(recentMean(statusSeries?.columns.proofs_per_hour, 30), "number"),
      sub: `${formatValue(status.fields.proofs, "count")} proofs in total`,
      spark: statusSeries?.columns.proofs_per_hour,
    });
    tile(grid, {
      label: "Statements per hour",
      value: formatValue(recentMean(statusSeries?.columns.statements_per_hour, 30), "number"),
      sub: `${formatValue(status.fields.statements_solved, "count")} / ${formatValue(status.fields.statements_attempted, "count")} solved`,
      spark: statusSeries?.columns.statements_per_hour,
    });
  } else {
    tile(grid, { label: "Loop", status: "critical", value: "No status", sub: "nothing written yet" });
  }
  if (system && latest.system) {
    const fields = latest.system.fields;
    tile(grid, {
      label: "Lean CPU",
      value: `${formatValue(recentMean(system.columns.lean_cores_used, 5), "cores")} cores`,
      sub: `of ${formatValue(fields.cpu_cores_available, "cores")} available`,
      spark: system.columns.lean_cores_used,
    });
  }
  if (fixed) {
    const solved = fixed.columns.minif2f_valid_solved;
    const current = lastValue(solved);
    const baseline = firstValue(solved);
    const problems = lastValue(fixed.columns.minif2f_valid_problems);
    const delta = current !== null && baseline !== null ? current - baseline : null;
    tile(grid, {
      label: "miniF2F-valid",
      status: delta === null ? null : delta > 0 ? "good" : delta < 0 ? "warning" : null,
      value: current === null ? "–" : `${current} / ${problems}`,
      sub: delta === null ? "" : `baseline ${baseline}, ${delta >= 0 ? "+" : ""}${delta}`,
      spark: solved,
    });
  }
  const valuePhase = latest.value_phase;
  const arm = latest.value_arm;
  if (valuePhase || arm) {
    const pooled = arm ? arm.fields.same_value_version : null;
    const versus = pooled && pooled.difference !== null
      ? `value arms vs v0 ${formatValue(pooled.difference, "share")} [${formatValue(pooled.lower, "share")}, ${formatValue(pooled.upper, "share")}]`
      : "no value arm yet";
    tile(grid, {
      label: "Value model",
      status: arm ? (arm.fields.worse ? "warning" : "good") : null,
      value: `value v${(status && status.value_version) ?? "–"} · μ ${valuePhase ? formatValue(valuePhase.fields.value_share, "number") : "0"}`,
      sub: versus,
    });
  }
}

function renderAlerts(parent) {
  const alerts = state.overview.alerts;
  const list = htmlElement("div", "alerts", null, parent);
  if (!alerts.length) {
    htmlElement("div", "all-clear", "No warnings.", list);
    return;
  }
  for (const alert of alerts) {
    const link = htmlElement("a", `alert ${alert.severity}`, null, list);
    link.href = `#/${alert.page}`;
    htmlElement("span", "badge", alert.severity, link);
    htmlElement("strong", "", alert.title, link);
    htmlElement("span", "detail", alert.detail, link);
  }
}

const TILES = { headline: headlineTiles, health: healthTiles, operations: operationsTiles };

function renderRatingTable(parent) {
  const card = chartCard(parent, { title: "Probe rating by version", wide: true });
  const fields = latestFields("rating");
  if (!fields || !fields.versions.length) {
    htmlElement("div", "empty", "No finished probe run rated yet", card);
    return;
  }
  const table = htmlElement("table", "data-table", null, htmlElement("div", "table-wrap", null, card));
  const anchor = `v${fields.anchor_version}`;
  const columns = [
    ["Policy", (version) => `v${version.policy_version}${version.rejected ? " (rejected)" : ""}`],
    ["Value", (version) => `v${version.value_version}`],
    ["Runs", (version) => String(version.runs)],
    ["Solved", (version) => `${version.solved} / ${version.searches}`],
    ["Wall-clock stops", (version) => String(version.wall_clock_stops)],
    ["Rating (Elo)", (version) => signed(version.rating * ELO)],
    ["95% interval", (version) => `${signed(version.lower * ELO)} to ${signed(version.upper * ELO)}`],
    [`≈ of ${fields.problems}`, (version) => formatValue(version.projected_solved, "count")],
    ...fields.budgets.map((budget, index) => [
      `Within ${budget}`,
      (version) =>
        `${formatValue(version.solved_within[index], "share")}${version.baseline_solved_within ? ` (${anchor} ${formatValue(version.baseline_solved_within[index], "share")})` : ""}`,
    ]),
  ];
  const head = htmlElement("tr", "", null, htmlElement("thead", "", null, table));
  columns.forEach(([name]) => htmlElement("th", "", name, head));
  const body = htmlElement("tbody", "", null, table);
  for (const version of [...fields.versions].reverse()) {
    const row = htmlElement("tr", "", null, body);
    columns.forEach(([, cell]) => htmlElement("td", "", cell(version), row));
  }
  const unreadable = fields.runs_unreadable ? `, ${fields.runs_unreadable} unreadable` : "";
  htmlElement(
    "div",
    "section-note",
    `Against ${anchor} at 0 (≈ ${formatValue(fields.baseline_projected_solved, "count")} of ${fields.problems}); ${fields.runs_rated} runs rated${unreadable}. The fitted difficulties spread ${formatValue(fields.difficulty_spread, "number")} logits; below about 1.5 the ratings run large. Each version searched one third, so its own rating is noisier than a pass's.`,
    card,
  );
}

function renderTable(parent, family) {
  if (family === "rating") return renderRatingTable(parent);
  const data = series(state.run, family, true);
  const card = chartCard(parent, { title: "All evaluations", wide: true });
  if (!data || !data.time.length) {
    htmlElement("div", "empty", "No evaluations yet", card);
    return;
  }
  const wrapper = htmlElement("div", "table-wrap", null, card);
  const table = htmlElement("table", "data-table", null, wrapper);
  const columns = [
    ["Time", (index) => formatTime(data.time[index])],
    ["Policy", (index) => `v${data.policy_version[index] ?? "–"}`],
    ["miniF2F-valid", (index) => formatValue(data.columns.minif2f_valid_solved?.[index], "count")],
    ["Held-out", (index) => formatValue(data.columns.held_out_success?.[index], "share")],
    ["MATH visible", (index) => formatValue(data.columns.math500_visible?.[index], "share")],
    ["MATH thinking", (index) => formatValue(data.columns.math500_thinking?.[index], "share")],
  ];
  const head = htmlElement("tr", "", null, htmlElement("thead", "", null, table));
  columns.forEach(([name]) => htmlElement("th", "", name, head));
  const body = htmlElement("tbody", "", null, table);
  for (let index = data.time.length - 1; index >= 0; index--) {
    const row = htmlElement("tr", "", null, body);
    columns.forEach(([, cell]) => htmlElement("td", "", cell(index), row));
  }
}

function renderAllMetrics(parent, page) {
  const families = page.families.filter((family) => series(state.run, family, false));
  if (!families.length) return;
  for (const family of families) {
    const data = series(state.run, family, false);
    const names = Object.keys(data.columns);
    const details = htmlElement("details", "all-metrics", null, parent);
    htmlElement("summary", "", `All metrics: ${family} (${names.length})`, details);
    const key = `${page.id}/${family}`;
    const fill = () => {
      if (details.querySelector(".metric-grid")) return;
      const grid = htmlElement("div", "metric-grid", null, details);
      for (const name of names) {
        const card = htmlElement("div", "metric", null, grid);
        const label = htmlElement("div", "name", name, card);
        label.title = name;
        htmlElement("div", "latest", formatValue(lastValue(data.columns[name]), "number"), card);
        sparkline(card, data.columns[name]);
      }
    };
    details.addEventListener("toggle", () => {
      if (details.open) {
        state.openDetails.add(key);
        fill();
      } else state.openDetails.delete(key);
    });
    if (state.openDetails.has(key)) {
      details.open = true;
      fill();
    }
  }
}

function render() {
  const page = currentPage();
  const main = document.getElementById("content");
  const height = main.offsetHeight;
  main.style.minHeight = `${height}px`;
  main.replaceChildren();
  document.querySelectorAll("nav.tabs a").forEach((link) => link.classList.toggle("active", link.dataset.page === page.id));
  if (page.id === "overview") renderAlerts(main);
  for (const section of page.sections) {
    const closed = collapsed(page, section);
    const heading = htmlElement("h2", "section", null, main);
    const toggle = htmlElement("button", `section-toggle${closed ? " closed" : ""}`, section.title, heading);
    toggle.type = "button";
    toggle.setAttribute("aria-expanded", String(!closed));
    toggle.addEventListener("click", () => {
      setCollapsed(page, section, !closed);
      if (closed) refresh();
      else render();
    });
    if (closed) continue;
    if (section.note) htmlElement("div", "section-note", section.note, main);
    if (section.tiles) TILES[section.tiles](main);
    if (section.charts) {
      const grid = htmlElement("div", "charts", null, main);
      section.charts.forEach((chart) => renderChart(grid, chart));
    }
    if (section.table) renderTable(htmlElement("div", "charts", null, main), section.table);
  }
  renderAllMetrics(main, page);
  main.style.minHeight = "";
  renderHeader();
}

function renderHeader() {
  const overview = state.overview;
  document.getElementById("title").textContent = overview.title;
  document.title = `${overview.title} · ${currentPage().title}`;
  const status = overview.latest.status;
  const alive = status && overview.now - status.time <= overview.thresholds.stale_heartbeats * status.fields.heartbeat_seconds;
  const pulse = document.getElementById("pulse");
  pulse.className = `pulse ${alive ? "good" : "critical"}`;
  pulse.title = alive ? "loop alive" : "loop silent";
  updateClock();
}

function updateClock() {
  if (!state.updatedAt) return;
  const seconds = (Date.now() - state.updatedAt) / 1000;
  document.getElementById("updated").textContent = `updated ${formatAge(seconds)} ago`;
}

async function refresh() {
  const main = document.getElementById("content");
  main.classList.add("loading");
  try {
    if (!state.run) {
      const runs = await fetchJson("api/runs");
      state.runs = runs.runs;
      state.main = runs.main;
      state.run = runs.main;
      buildRunSelect();
    }
    state.overview = await fetchJson(`api/overview?run=${encodeURIComponent(state.run)}`);
    document.getElementById("logout").hidden = !state.overview.authentication;
    await loadData(currentPage());
    state.updatedAt = Date.now();
    render();
  } catch (error) {
    document.getElementById("updated").textContent = `update failed: ${error.message}`;
  } finally {
    main.classList.remove("loading");
    schedule();
  }
}

function schedule() {
  clearTimeout(state.timer);
  const seconds = state.overview ? state.overview.refresh_seconds : 30;
  state.timer = setTimeout(() => (document.hidden ? schedule() : refresh()), seconds * 1000);
}

function buildRunSelect() {
  const select = document.getElementById("run");
  const names = Object.keys(state.runs);
  select.hidden = names.length < 2;
  select.replaceChildren(...names.map((name) => new Option(name, name, false, name === state.run)));
}

function applyExplain() {
  document.body.classList.toggle("hide-why", !state.explain);
  const button = document.getElementById("explain");
  button.textContent = state.explain ? "Hide explanations" : "Explain";
  button.setAttribute("aria-pressed", String(state.explain));
}

function applyTheme() {
  if (state.theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = state.theme;
  document.getElementById("theme").textContent = { auto: "Auto", light: "Light", dark: "Dark" }[state.theme];
}

function setUp() {
  const nav = document.getElementById("tabs");
  for (const page of PAGES) {
    const link = htmlElement("a", "", page.title, nav);
    link.href = `#/${page.id}`;
    link.dataset.page = page.id;
  }
  const range = document.getElementById("range");
  range.replaceChildren(...RANGES.map((option) => new Option(option.label, option.seconds, false, option.seconds === state.range)));
  range.addEventListener("change", () => {
    state.range = Number(range.value);
    store("range", String(state.range));
    refresh();
  });
  document.getElementById("run").addEventListener("change", (event) => {
    state.run = event.target.value;
    refresh();
  });
  document.getElementById("explain").addEventListener("click", () => {
    state.explain = !state.explain;
    store("explain", state.explain ? "on" : "off");
    applyExplain();
  });
  document.getElementById("theme").addEventListener("click", () => {
    state.theme = THEMES[(THEMES.indexOf(state.theme) + 1) % THEMES.length];
    store("theme", state.theme);
    applyTheme();
  });
  window.addEventListener("hashchange", () => {
    window.scrollTo(0, 0);
    refresh();
  });
  window.addEventListener("resize", () => {
    if (window.innerWidth === state.width || !state.overview) return;
    state.width = window.innerWidth;
    clearTimeout(state.resizeTimer);
    state.resizeTimer = setTimeout(render, 150);
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - state.updatedAt > 10000) refresh();
  });
  setInterval(updateClock, 5000);
  applyTheme();
  applyExplain();
  refresh();
}

setUp();
