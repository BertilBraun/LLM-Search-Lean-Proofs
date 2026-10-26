import { PAGES } from "./pages.js";
import {
  barChart,
  chartCard,
  formatAge,
  formatTime,
  formatValue,
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
const X_NAMES = { policy_version: "policy v", value_version: "value v", phase: "phase " };

const state = {
  run: null,
  runs: {},
  main: null,
  range: Number(stored("range", "0")),
  theme: stored("theme", "auto"),
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

function wantedSeries(page) {
  const wanted = new Map();
  const add = (run, family, allTime) => {
    if (state.runs[run] && state.runs[run].includes(family)) wanted.set(dataKey(run, family, allTime), { run, family, allTime });
  };
  for (const section of page.sections) {
    for (const chart of section.charts || []) {
      if (!chart.family) continue;
      add(state.run, chart.family, chart.allTime);
      if (chart.compare) otherRuns().forEach((run) => add(run, chart.family, chart.allTime));
    }
    if (section.tiles) ["status", "system"].forEach((family) => add(state.run, family, false));
    if (section.tiles) ["fixed_targets", "value"].forEach((family) => add(state.run, family, true));
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

function xValues(data, axis) {
  return axis && axis !== "time" ? data[axis] : data.time;
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
  const result = specs.map((spec, slot) => ({ label: spec.label, slot, points: points(main, chart.x, evaluate(main, spec)) }));
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
    default: {
      const built = chartSeries(chart);
      const references = (chart.thresholds || []).map((threshold) => ({
        value: thresholdValue(threshold.key),
        label: `${threshold.label} ${formatValue(thresholdValue(threshold.key), chart.unit)}`,
        kind: "threshold",
      }));
      const first = built[0] && built[0].points.find((point) => point.y !== null);
      if (chart.baseline && first) {
        references.push({ value: first.y, label: `baseline ${formatValue(first.y, chart.unit)}`, kind: "baseline" });
      }
      return lineChart(parent, { ...chart, xKind, xLabel, band, references, series: built });
    }
  }
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

function reliabilitySpec(chart) {
  const fields = latestFields("value");
  const bins = fields ? fields.benchmark.calibration.anchor_bins : [];
  const known = bins.filter((bin) => bin.mean_predicted !== null && bin.mean_target !== null);
  const subtitle = fields ? `candidate v${fields.candidate_version}; ${chart.subtitle}` : chart.subtitle;
  return {
    ...chart,
    subtitle,
    unit: "share",
    xKind: "continuous",
    xLabel: (x) => `predicted ${formatValue(x, "share")}`,
    yMin: 0,
    yMax: 1,
    diagonal: true,
    noLegend: true,
    series: [{ label: "observed", slot: 0, markers: true, points: known.map((bin) => ({ x: bin.mean_predicted, y: bin.mean_target })) }],
  };
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

function tile(parent, { label, value, sub, status, spark }) {
  const card = htmlElement("div", "tile", null, parent);
  const head = htmlElement("div", "label", null, card);
  if (status) htmlElement("span", `status-icon ${status}`, null, head);
  htmlElement("span", "", label, head);
  htmlElement("div", "value", value, card);
  if (sub) htmlElement("div", "sub", sub, card);
  if (spark) sparkline(card, spark);
}

function overviewTiles(parent) {
  const grid = htmlElement("div", "tiles", null, parent);
  const now = state.overview.now;
  const thresholds = state.overview.thresholds;
  const latest = state.overview.latest;
  const status = latest.status;
  const statusSeries = series(state.run, "status", false);
  const system = series(state.run, "system", false);
  const fixed = series(state.run, "fixed_targets", true);
  const value = series(state.run, "value", true);

  if (status) {
    const age = now - status.time;
    const alive = age <= thresholds.stale_heartbeats * status.fields.heartbeat_seconds;
    tile(grid, {
      label: "Loop",
      status: alive ? "good" : "critical",
      value: alive ? status.fields.state.replace(/^./, (letter) => letter.toUpperCase()) : "Silent",
      sub: `status ${formatAge(age)} ago`,
    });
    tile(grid, {
      label: "Phase",
      value: status.phase === null ? "–" : `Phase ${status.phase}`,
      sub: `policy v${status.policy_version ?? "–"} · value v${status.value_version ?? "–"}`,
    });
    const published = status.fields.last_publish_time;
    const sincePublish = published === null ? null : now - published;
    tile(grid, {
      label: "Since publish",
      status: sincePublish === null ? null : sincePublish > thresholds.max_minutes_since_publish * 60 ? "warning" : "good",
      value: sincePublish === null ? "never" : formatAge(sincePublish),
      sub: published === null ? "" : formatTime(published),
    });
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
  if (system) {
    const utilization = evaluate(system, { mean: "gpu_utilization." });
    const recent = recentMean(utilization, 5);
    const fields = latest.system.fields;
    tile(grid, {
      label: "GPU utilization",
      status: recent === null ? null : recent < thresholds.min_gpu_utilization ? "warning" : "good",
      value: formatValue(recent, "percent"),
      sub: `mean of ${fields.gpu_utilization.length} GPUs`,
      spark: utilization,
    });
    tile(grid, {
      label: "Lean CPU",
      value: `${formatValue(recentMean(system.columns.lean_cores_used, 5), "cores")} cores`,
      sub: `of ${formatValue(fields.cpu_cores_available, "cores")} available`,
      spark: system.columns.lean_cores_used,
    });
    tile(grid, {
      label: "Spent",
      value: formatValue(fields.cost_so_far, "dollars"),
      sub: `${formatValue(fields.hourly_price, "dollars")} per hour`,
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
    const heldOut = fixed.columns.held_out_success;
    tile(grid, {
      label: "Held-out states",
      value: formatValue(lastValue(heldOut), "share"),
      sub: `per sample; baseline ${formatValue(firstValue(heldOut), "share")}`,
      spark: heldOut,
    });
    const visible = fixed.columns.math500_visible;
    const mathNow = lastValue(visible);
    const mathStart = firstValue(visible);
    const mathStatus = mathNow === null ? null
      : mathNow < thresholds.min_math500_visible ? "critical"
      : mathStart - mathNow > thresholds.max_math500_drop ? "warning" : "good";
    tile(grid, {
      label: "MATH-500 visible",
      status: mathStatus,
      value: formatValue(mathNow, "share"),
      sub: `baseline ${formatValue(mathStart, "share")}; thinking ${formatValue(lastValue(fixed.columns.math500_thinking), "share")}`,
      spark: visible,
    });
  }
  if (value) {
    const passed = (value.columns.gate_passed || []).filter((item) => item !== null);
    const recent = passed.slice(-5);
    const last = passed.at(-1);
    tile(grid, {
      label: "Value gate",
      status: last === undefined ? null : last ? "good" : "warning",
      value: last === undefined ? "–" : last ? "Passed" : "Failed",
      sub: `${recent.filter(Boolean).length} of the last ${recent.length} passed`,
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

function renderTable(parent, family) {
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
    htmlElement("h2", "section", section.title, main);
    if (section.tiles) overviewTiles(main);
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
  refresh();
}

setUp();
