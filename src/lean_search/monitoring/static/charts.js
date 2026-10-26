// Hand-written SVG charts: line, stacked share, bars and sparklines, with a crosshair tooltip.

const SVG = "http://www.w3.org/2000/svg";
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const TIME_STEPS = [300, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400, 172800, 604800];

export function seriesColor(slot) {
  return `var(--s${(slot % 8) + 1})`;
}

export function svgElement(name, attributes = {}, parent = null) {
  const element = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  if (parent) parent.appendChild(element);
  return element;
}

export function htmlElement(name, className = "", text = null, parent = null) {
  const element = document.createElement(name);
  if (className) element.className = className;
  if (text !== null) element.textContent = text;
  if (parent) parent.appendChild(element);
  return element;
}

function compact(value, digits) {
  const magnitude = Math.abs(value);
  if (magnitude >= 1e9) return (value / 1e9).toFixed(1) + "B";
  if (magnitude >= 1e6) return (value / 1e6).toFixed(1) + "M";
  if (magnitude >= 1e4) return (value / 1e3).toFixed(1) + "K";
  if (magnitude >= 100 || Number.isInteger(value)) return Math.round(value).toLocaleString("en-US");
  return Number(value.toPrecision(digits)).toString();
}

export function formatValue(value, unit = "number") {
  if (value === null || value === undefined || Number.isNaN(value)) return "–";
  switch (unit) {
    case "share":
      return (value * 100).toFixed(Math.abs(value) < 0.1 ? 2 : 1) + "%";
    case "percent":
      return value.toFixed(0) + "%";
    case "dollars":
      return "$" + value.toFixed(2);
    case "seconds":
      if (value < 120) return value.toFixed(value < 10 ? 2 : 1) + " s";
      if (value < 7200) return (value / 60).toFixed(0) + " min";
      return (value / 3600).toFixed(1) + " h";
    case "count":
      return compact(Math.round(value), 3);
    case "gib":
      return value.toFixed(1) + " GiB";
    case "cores":
      return value.toFixed(1);
    default:
      return compact(value, 3);
  }
}

function axisValue(value, unit) {
  if (unit === "share") return (value * 100).toFixed(Math.abs(value) < 0.1 && value !== 0 ? 1 : 0) + "%";
  if (unit === "dollars") return "$" + compact(value, 2);
  if (unit === "seconds") return compact(value, 2) + "s";
  return compact(value, 2);
}

function pad(number) {
  return String(number).padStart(2, "0");
}

export function formatTime(seconds, withDate = true) {
  const date = new Date(seconds * 1000);
  const clock = `${pad(date.getHours())}:${pad(date.getMinutes())}`;
  return withDate ? `${MONTHS[date.getMonth()]} ${date.getDate()} ${clock}` : clock;
}

export function formatAge(seconds) {
  if (seconds < 90) return `${Math.max(0, Math.round(seconds))} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  if (seconds < 172800) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} d`;
}

function niceStep(span, count) {
  const raw = span / Math.max(1, count);
  const power = Math.pow(10, Math.floor(Math.log10(raw)));
  const fraction = raw / power;
  const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 2.5 ? 2.5 : fraction <= 5 ? 5 : 10;
  return nice * power;
}

function niceDomain(low, high, count) {
  if (low === high) {
    const spread = Math.abs(low) * 0.1 || 1;
    low -= spread;
    high += spread;
  }
  const step = niceStep(high - low, count);
  const start = Math.floor(low / step + 1e-9) * step;
  const end = Math.ceil(high / step - 1e-9) * step;
  const decimals = Math.max(0, 1 - Math.floor(Math.log10(step)));
  const ticks = [];
  for (let index = 0; start + index * step <= end + step / 2; index++) {
    ticks.push(Number((start + index * step).toFixed(decimals)));
  }
  return { low: start, high: end, ticks };
}

function timeTicks(low, high, width) {
  const wanted = Math.max(2, Math.floor(width / 90));
  const step = TIME_STEPS.find((candidate) => (high - low) / candidate <= wanted) || TIME_STEPS.at(-1);
  const offset = new Date().getTimezoneOffset() * 60;
  const ticks = [];
  for (let tick = Math.ceil((low - offset) / step) * step + offset; tick <= high; tick += step) ticks.push(tick);
  const daily = step >= 86400;
  return ticks.map((tick) => {
    const date = new Date(tick * 1000);
    const label = daily || (date.getHours() === 0 && date.getMinutes() === 0)
      ? `${MONTHS[date.getMonth()]} ${date.getDate()}`
      : formatTime(tick, false);
    return { value: tick, label };
  });
}

function numberTicks(low, high, width, integers) {
  const domain = niceDomain(low, high, Math.max(2, Math.floor(width / 70)));
  return domain.ticks
    .filter((tick) => tick >= low - 1e-9 && tick <= high + 1e-9 && (!integers || Number.isInteger(tick)))
    .map((tick) => ({ value: tick, label: compact(tick, 2) }));
}

function lineKey(slot, dashed, parent) {
  const key = svgElement("svg", { viewBox: "0 0 16 10" }, parent);
  const line = svgElement("line", { x1: 1, y1: 5, x2: 15, y2: 5, class: "series-line" + (dashed ? " compare" : "") }, key);
  line.style.stroke = seriesColor(slot);
  return key;
}

function boxKey(slot, parent) {
  const key = svgElement("svg", { viewBox: "0 0 16 10" }, parent);
  const box = svgElement("rect", { x: 3, y: 0, width: 10, height: 10, rx: 2 }, key);
  box.style.fill = seriesColor(slot);
  return key;
}

function lastPoint(points) {
  for (let index = points.length - 1; index >= 0; index--) if (points[index].y !== null) return points[index];
  return null;
}

function renderLegend(card, series, unit, boxes) {
  if (series.length < 2 && !series.some((item) => item.dashed)) {
    if (series.length === 1) {
      const last = lastPoint(series[0].points);
      const legend = htmlElement("div", "legend", null, card);
      const item = htmlElement("span", "item", null, legend);
      htmlElement("span", "", "latest ", item);
      htmlElement("b", "", formatValue(last ? last.y : null, unit), item);
    }
    return;
  }
  const legend = htmlElement("div", "legend", null, card);
  for (const item of series) {
    const entry = htmlElement("span", "item", null, legend);
    if (boxes) boxKey(item.slot, entry);
    else lineKey(item.slot, item.dashed, entry);
    htmlElement("span", "", item.label, entry);
    const last = lastPoint(item.points);
    if (last && !item.hideLatest) htmlElement("b", "", formatValue(last.y, unit), entry);
  }
}

export function chartCard(parent, spec) {
  const card = htmlElement("section", "chart" + (spec.wide ? " wide" : ""), null, parent);
  htmlElement("h3", "", spec.title, card);
  if (spec.subtitle) htmlElement("p", "subtitle", spec.subtitle, card);
  return card;
}

function plotHeight(spec) {
  return spec.height || (window.innerWidth < 640 ? 170 : 200);
}

function yLabelWidth(ticks, unit) {
  const longest = Math.max(...ticks.map((tick) => axisValue(tick, unit).length));
  return Math.max(28, longest * 6.6 + 8);
}

function emptyNote(card, text = "No data in this range yet") {
  htmlElement("div", "empty", text, card);
}

function nearestIndex(points, x) {
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (points[middle].x < x) low = middle + 1;
    else high = middle;
  }
  if (low > 0 && Math.abs(points[low - 1].x - x) <= Math.abs(points[low].x - x)) return low - 1;
  return low;
}

function attachHover(card, svg, frame, series, spec, valuesAt) {
  const tooltip = htmlElement("div", "tooltip", null, card);
  tooltip.hidden = true;
  const crosshair = svgElement("line", { class: "crosshair", y1: frame.top, y2: frame.top + frame.height }, svg);
  crosshair.style.visibility = "hidden";
  const markers = series.map((item) => {
    const marker = svgElement("circle", { r: 4, class: "marker" }, svg);
    marker.style.fill = seriesColor(item.slot);
    marker.style.visibility = "hidden";
    return marker;
  });
  const allX = [...new Set(series.flatMap((item) => item.points.map((point) => point.x)))].sort((a, b) => a - b);
  const allPoints = allX.map((x) => ({ x }));
  const hide = () => {
    tooltip.hidden = true;
    crosshair.style.visibility = "hidden";
    markers.forEach((marker) => (marker.style.visibility = "hidden"));
  };
  const show = (event) => {
    const bounds = svg.getBoundingClientRect();
    const viewX = (event.clientX - bounds.left) * (frame.totalWidth / bounds.width);
    if (viewX < frame.left - 8 || viewX > frame.left + frame.width + 8) return hide();
    const x = frame.xInverse(viewX);
    const snapped = allPoints[nearestIndex(allPoints, x)].x;
    const position = frame.xScale(snapped);
    crosshair.setAttribute("x1", position);
    crosshair.setAttribute("x2", position);
    crosshair.style.visibility = "visible";
    tooltip.replaceChildren();
    htmlElement("div", "when", spec.xLabel(snapped), tooltip);
    const rows = valuesAt(snapped);
    rows.forEach((row, index) => {
      const marker = markers[index];
      if (row.y === null || row.y === undefined) {
        marker.style.visibility = "hidden";
        return;
      }
      marker.setAttribute("cx", position);
      marker.setAttribute("cy", frame.yScale(row.plotY ?? row.y));
      marker.style.visibility = "visible";
      const line = htmlElement("div", "row", null, tooltip);
      if (spec.boxes) boxKey(series[index].slot, line);
      else lineKey(series[index].slot, series[index].dashed, line);
      htmlElement("b", "", formatValue(row.y, spec.unit), line);
      htmlElement("span", "", series[index].label, line);
    });
    tooltip.hidden = false;
    const cardBounds = card.getBoundingClientRect();
    const left = bounds.left - cardBounds.left + position / (frame.totalWidth / bounds.width);
    const width = tooltip.offsetWidth;
    const placed = left + 12 + width > cardBounds.width ? left - 12 - width : left + 12;
    tooltip.style.left = `${Math.max(4, placed)}px`;
    tooltip.style.top = `${svg.offsetTop + 8}px`;
  };
  svg.addEventListener("pointermove", show);
  svg.addEventListener("pointerdown", show);
  svg.addEventListener("pointerleave", hide);
}

function drawFrame(svg, frame, yTicks, xTicks, unit) {
  for (const tick of yTicks) {
    const y = frame.yScale(tick);
    svgElement("line", { class: "gridline", x1: frame.left, x2: frame.left + frame.width, y1: y, y2: y }, svg);
    const label = svgElement("text", { x: frame.left - 6, y: y + 4, "text-anchor": "end" }, svgElement("g", { class: "tick" }, svg));
    label.textContent = axisValue(tick, unit);
  }
  const bottom = frame.top + frame.height;
  svgElement("line", { class: "baseline-axis", x1: frame.left, x2: frame.left + frame.width, y1: bottom, y2: bottom }, svg);
  const group = svgElement("g", { class: "tick" }, svg);
  let lastRight = -Infinity;
  for (const tick of xTicks) {
    const x = frame.xScale(tick.value);
    const halfWidth = tick.label.length * 3.3;
    if (x - halfWidth < lastRight + 6 || x - halfWidth < 0 || x + halfWidth > frame.totalWidth) continue;
    const label = svgElement("text", { x, y: bottom + 15, "text-anchor": "middle" }, group);
    label.textContent = tick.label;
    lastRight = x + halfWidth;
  }
}

function frameFor(card, spec, xLow, xHigh, yLow, yHigh) {
  const totalWidth = Math.max(240, card.clientWidth - 24);
  const height = plotHeight(spec);
  const domain = niceDomain(yLow, yHigh, height < 180 ? 3 : 4);
  const left = yLabelWidth(domain.ticks, spec.unit);
  const frame = { left, right: 12, top: 8, bottom: 22, totalWidth, totalHeight: height };
  frame.width = totalWidth - left - frame.right;
  frame.height = height - frame.top - frame.bottom;
  const xSpan = xHigh - xLow || 1;
  frame.xScale = (x) => left + ((x - xLow) / xSpan) * frame.width;
  frame.xInverse = (position) => xLow + ((position - left) / frame.width) * xSpan;
  frame.yScale = (y) => frame.top + frame.height - ((y - domain.low) / (domain.high - domain.low)) * frame.height;
  frame.domain = domain;
  return frame;
}

function xTicksFor(spec, frame, xLow, xHigh) {
  if (spec.xKind === "time") return timeTicks(xLow, xHigh, frame.width);
  return numberTicks(xLow, xHigh, frame.width, spec.xKind === "version");
}

function pathData(points, frame) {
  let data = "";
  let drawing = false;
  for (const point of points) {
    if (point.y === null || point.y === undefined) {
      drawing = false;
      continue;
    }
    data += `${drawing ? "L" : "M"}${frame.xScale(point.x).toFixed(1)},${frame.yScale(point.y).toFixed(1)}`;
    drawing = true;
  }
  return data;
}

// spec: {title, unit, xKind: "time"|"number", xLabel(x), series: [{label, slot, points: [{x, y}], dashed}],
//        references: [{value, label, kind: "baseline"|"threshold"}], band: {low, high}, yMin, yMax, diagonal}
export function lineChart(parent, spec) {
  const card = chartCard(parent, spec);
  const series = spec.series.filter((item) => item.points.some((point) => point.y !== null));
  if (!spec.noLegend) renderLegend(card, series, spec.unit, false);
  if (!series.length) return emptyNote(card), card;
  const xs = series.flatMap((item) => item.points.map((point) => point.x));
  const ys = series.flatMap((item) => item.points.filter((point) => point.y !== null).map((point) => point.y));
  const references = (spec.references || []).filter((reference) => reference.value !== null && reference.value !== undefined);
  ys.push(...references.map((reference) => reference.value));
  if (spec.band) ys.push(spec.band.low, spec.band.high);
  let xLow = Math.min(...xs);
  let xHigh = Math.max(...xs);
  if (xLow === xHigh) {
    xLow -= spec.xKind === "time" ? 1800 : 1;
    xHigh += spec.xKind === "time" ? 1800 : 1;
  }
  const yLow = spec.yMin ?? Math.min(...ys);
  const yHigh = spec.yMax ?? Math.max(...ys);
  const frame = frameFor(card, spec, xLow, xHigh, Math.min(yLow, yHigh), Math.max(yLow, yHigh));
  const svg = svgElement("svg", { class: "plot", viewBox: `0 0 ${frame.totalWidth} ${frame.totalHeight}`, role: "img" }, card);
  svg.setAttribute("aria-label", spec.title);
  drawFrame(svg, frame, frame.domain.ticks, xTicksFor(spec, frame, xLow, xHigh), spec.unit);
  if (spec.band) {
    const top = frame.yScale(spec.band.high);
    svgElement("rect", { class: "target-band", x: frame.left, width: frame.width, y: top, height: frame.yScale(spec.band.low) - top }, svg);
  }
  if (spec.diagonal) {
    svgElement("line", {
      class: "reference-line",
      x1: frame.xScale(frame.domain.low), y1: frame.yScale(frame.domain.low),
      x2: frame.xScale(Math.min(xHigh, frame.domain.high)), y2: frame.yScale(Math.min(xHigh, frame.domain.high)),
    }, svg);
  }
  for (const reference of references) {
    const y = frame.yScale(reference.value);
    const kind = reference.kind === "threshold" ? "threshold" : "reference";
    svgElement("line", { class: `${kind}-line`, x1: frame.left, x2: frame.left + frame.width, y1: y, y2: y }, svg);
    const labelY = y - frame.top < 12 ? y + 11 : y - 3;
    const label = svgElement("text", { class: `${kind}-label`, x: frame.left + frame.width - 2, y: labelY, "text-anchor": "end" }, svg);
    label.textContent = reference.label;
  }
  series.forEach((item) => {
    if (!spec.dots) {
      const path = svgElement("path", { class: "series-line" + (item.dashed ? " compare" : ""), d: pathData(item.points, frame) }, svg);
      path.style.stroke = seriesColor(item.slot);
    }
    const present = item.points.filter((point) => point.y !== null);
    if (present.length <= 40 || item.markers || spec.dots) {
      for (const point of present) {
        const dot = svgElement("circle", { class: "marker", r: item.dashed ? 2.5 : 3, cx: frame.xScale(point.x), cy: frame.yScale(point.y) }, svg);
        dot.style.fill = seriesColor(item.slot);
      }
    }
  });
  const valuesAt = (x) => series.map((item) => {
    const point = item.points[nearestIndex(item.points, x)];
    return point && point.x === x ? point : { y: null };
  });
  attachHover(card, svg, frame, series, spec, valuesAt);
  return card;
}

// Stacked areas of each series' share of the stack total at every x (all series share the same x positions).
export function stackedChart(parent, spec) {
  const card = chartCard(parent, spec);
  const series = spec.series.filter((item) => item.points.some((point) => point.y));
  if (!series.length) return emptyNote(card), card;
  const xs = series[0].points.map((point) => point.x);
  const totals = xs.map((_, index) => series.reduce((sum, item) => sum + (item.points[index].y || 0), 0));
  const shares = series.map((item) => ({
    ...item,
    points: item.points.map((point, index) => ({ x: point.x, y: totals[index] ? (point.y || 0) / totals[index] : null })),
  }));
  renderLegend(card, shares, "share", true);
  let xLow = xs[0];
  let xHigh = xs.at(-1);
  if (xLow === xHigh) {
    xLow -= 1800;
    xHigh += 1800;
  }
  const frame = frameFor(card, { ...spec, unit: "share" }, xLow, xHigh, 0, 1);
  const svg = svgElement("svg", { class: "plot", viewBox: `0 0 ${frame.totalWidth} ${frame.totalHeight}`, role: "img" }, card);
  svg.setAttribute("aria-label", spec.title);
  drawFrame(svg, frame, frame.domain.ticks, xTicksFor(spec, frame, xLow, xHigh), "share");
  const lower = xs.map(() => 0);
  const stacked = shares.map((item) => {
    const bottoms = [...lower];
    item.points.forEach((point, index) => (lower[index] += point.y || 0));
    return { item, bottoms, tops: [...lower] };
  });
  for (const { item, bottoms, tops } of stacked) {
    const upper = xs.map((x, index) => `${frame.xScale(x).toFixed(1)},${frame.yScale(tops[index]).toFixed(1)}`);
    const under = xs.map((x, index) => `${frame.xScale(x).toFixed(1)},${frame.yScale(bottoms[index]).toFixed(1)}`).reverse();
    const area = svgElement("path", { d: `M${upper.join("L")}L${under.join("L")}Z` }, svg);
    area.style.fill = seriesColor(item.slot);
    area.style.stroke = "var(--surface)";
    area.style.strokeWidth = "1";
  }
  const hoverSpec = { ...spec, unit: "share", boxes: true };
  const valuesAt = (x) => {
    const index = nearestIndex(series[0].points, x);
    return stacked.map(({ item, tops }) => ({ y: item.points[index].y, plotY: tops[index] }));
  };
  attachHover(card, svg, frame, shares, hoverSpec, valuesAt);
  return card;
}

// spec: {title, unit, bars: [{label, value, detail}], band: {low, high}, yMax}
export function barChart(parent, spec) {
  const card = chartCard(parent, spec);
  const bars = spec.bars.filter((bar) => bar.value !== null && bar.value !== undefined);
  if (!bars.length) return emptyNote(card), card;
  const values = bars.map((bar) => bar.value);
  const totalWidth = Math.max(240, card.clientWidth - 24);
  const height = plotHeight(spec);
  const domain = niceDomain(0, spec.yMax ?? Math.max(...values), 4);
  const left = yLabelWidth(domain.ticks, spec.unit);
  const frame = { left, right: 8, top: 16, bottom: 22, totalWidth, totalHeight: height };
  frame.width = totalWidth - left - frame.right;
  frame.height = height - frame.top - frame.bottom;
  frame.yScale = (y) => frame.top + frame.height - ((y - domain.low) / (domain.high - domain.low)) * frame.height;
  const slot = frame.width / bars.length;
  frame.xScale = (index) => left + slot * (index + 0.5);
  const svg = svgElement("svg", { class: "plot", viewBox: `0 0 ${totalWidth} ${height}`, role: "img" }, card);
  svg.setAttribute("aria-label", spec.title);
  drawFrame(svg, frame, domain.ticks, bars.map((bar, index) => ({ value: index, label: bar.label })), spec.unit);
  if (spec.band) {
    const top = frame.yScale(spec.band.high);
    svgElement("rect", { class: "target-band", x: left, width: frame.width, y: top, height: frame.yScale(spec.band.low) - top }, svg);
  }
  const barWidth = Math.min(24, slot * 0.6);
  const tooltip = htmlElement("div", "tooltip", null, card);
  tooltip.hidden = true;
  bars.forEach((bar, index) => {
    const x = frame.xScale(index) - barWidth / 2;
    const top = frame.yScale(bar.value);
    const bottom = frame.yScale(0);
    const radius = Math.min(4, barWidth / 2, bottom - top);
    const shape = svgElement("path", {
      class: "bar",
      d: `M${x},${bottom}V${top + radius}Q${x},${top} ${x + radius},${top}H${x + barWidth - radius}Q${x + barWidth},${top} ${x + barWidth},${top + radius}V${bottom}Z`,
    }, svg);
    shape.style.fill = seriesColor(bar.slot ?? 0);
    const label = svgElement("text", { class: "bar-label", x: frame.xScale(index), y: top - 4, "text-anchor": "middle" }, svg);
    label.textContent = formatValue(bar.value, spec.unit);
    const hit = svgElement("rect", { x: frame.xScale(index) - slot / 2, y: frame.top, width: slot, height: frame.height, fill: "transparent" }, svg);
    const show = () => {
      tooltip.replaceChildren();
      htmlElement("div", "when", bar.label, tooltip);
      const row = htmlElement("div", "row", null, tooltip);
      htmlElement("b", "", formatValue(bar.value, spec.unit), row);
      if (bar.detail) htmlElement("span", "", bar.detail, row);
      tooltip.hidden = false;
      const scale = svg.getBoundingClientRect().width / totalWidth;
      const center = frame.xScale(index) * scale;
      tooltip.style.left = `${Math.max(4, Math.min(center - tooltip.offsetWidth / 2, card.clientWidth - tooltip.offsetWidth - 4))}px`;
      tooltip.style.top = `${svg.offsetTop + 4}px`;
    };
    hit.addEventListener("pointerenter", show);
    hit.addEventListener("pointerdown", show);
    hit.addEventListener("pointerleave", () => (tooltip.hidden = true));
  });
  return card;
}

export function sparkline(parent, values, className = "spark") {
  const known = values.filter((value) => value !== null && value !== undefined);
  const svg = svgElement("svg", { class: className, viewBox: "0 0 100 28", preserveAspectRatio: "none" }, parent);
  if (known.length < 2) return svg;
  const low = Math.min(...known);
  const high = Math.max(...known);
  const span = high - low || 1;
  const step = 100 / (values.length - 1);
  const points = values
    .map((value, index) => (value === null || value === undefined ? null : [index * step, 26 - ((value - low) / span) * 24]))
    .filter(Boolean);
  const line = points.map(([x, y], index) => `${index ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join("");
  svgElement("path", { class: "spark-area", d: `${line}L${points.at(-1)[0]},28L${points[0][0]},28Z` }, svg);
  svgElement("path", { class: "spark-line", d: line, "vector-effect": "non-scaling-stroke" }, svg);
  return svg;
}
