/* Hand-rolled SVG charts.
 *
 * No chart library and no CDN: the dashboard reads a brokerage account, so it
 * should run with the network off and load nothing from a third party.
 *
 * Mark specs held constant across every chart here:
 *   bars    <= 24px thick, 4px rounded data-end, square at the baseline
 *   lines   2px, round cap/join
 *   markers r >= 4 with a 2px ring in the surface color
 *   area    the series hue at 10% opacity
 *   grid    hairline, solid, one step off the surface
 *   spacing a 2px surface gap between adjacent marks
 */

const SVG_NS = "http://www.w3.org/2000/svg";

/* ------------------------------------------------------------- formatting */

export const fmt = {
  currency(value, currency = "USD", digits = 0) {
    if (value === null || value === undefined || Number.isNaN(value)) return "--";
    return new Intl.NumberFormat("en-US", {
      style: "currency",
      currency,
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  },

  /** Compact money for stat tiles and axis ticks: $4.2M, -$812K. */
  compact(value, currency = "USD") {
    if (value === null || value === undefined || Number.isNaN(value)) return "--";
    const abs = Math.abs(value);
    const sign = value < 0 ? "-" : "";
    const symbol = fmt.symbolFor(currency);
    if (abs >= 1e9) return `${sign}${symbol}${(abs / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `${sign}${symbol}${(abs / 1e6).toFixed(2)}M`;
    if (abs >= 1e4) return `${sign}${symbol}${Math.round(abs / 1e3)}K`;
    if (abs >= 1e3) return `${sign}${symbol}${(abs / 1e3).toFixed(1)}K`;
    return `${sign}${symbol}${abs.toFixed(0)}`;
  },

  symbolFor(currency) {
    try {
      const parts = new Intl.NumberFormat("en-US", {
        style: "currency",
        currency,
      }).formatToParts(0);
      return parts.find((p) => p.type === "currency")?.value ?? "";
    } catch {
      return `${currency} `;
    }
  },

  signed(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return "--";
    const sign = value > 0 ? "+" : "";
    return `${sign}${value.toFixed(digits)}`;
  },

  pct(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return "--";
    return `${value.toFixed(digits)}%`;
  },

  signedPct(value, digits = 2) {
    if (value === null || value === undefined || Number.isNaN(value)) return "--";
    return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
  },

  number(value, digits = 0) {
    if (value === null || value === undefined || Number.isNaN(value)) return "--";
    return new Intl.NumberFormat("en-US", {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(value);
  },

  date(iso, opts = { month: "short", day: "numeric" }) {
    const d = new Date(`${String(iso).slice(0, 10)}T00:00:00`);
    if (Number.isNaN(d.getTime())) return String(iso);
    return d.toLocaleDateString("en-US", opts);
  },
};

/* ------------------------------------------------------------- primitives */

function el(name, attrs = {}, text) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) {
    if (value !== null && value !== undefined) node.setAttribute(key, String(value));
  }
  if (text !== undefined) node.textContent = text;
  return node;
}

function token(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Round an axis maximum up to a clean 1/2/2.5/5 x 10^n step. */
function niceTicks(min, max, count = 5) {
  if (min === max) {
    min = min === 0 ? 0 : min * 0.95;
    max = max === 0 ? 1 : max * 1.05;
  }
  const raw = (max - min) / count;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.abs(raw) || 1)));
  const norm = raw / mag;
  const step = (norm <= 1 ? 1 : norm <= 2 ? 2 : norm <= 2.5 ? 2.5 : norm <= 5 ? 5 : 10) * mag;
  const lo = Math.floor(min / step) * step;
  const hi = Math.ceil(max / step) * step;
  const ticks = [];
  for (let v = lo; v <= hi + step / 1000; v += step) ticks.push(Number(v.toFixed(10)));
  return { ticks, lo, hi };
}

/**
 * Bar path: square at the baseline, 4px rounded at the data end.
 * `dir` is the direction the bar grows: "right" | "left" | "up".
 */
function barPath(x, y, w, h, dir, r = 4) {
  const radius = Math.max(0, Math.min(r, w / 2, h / 2));
  if (dir === "right") {
    return `M${x},${y} H${x + w - radius} A${radius},${radius} 0 0 1 ${x + w},${y + radius}
            V${y + h - radius} A${radius},${radius} 0 0 1 ${x + w - radius},${y + h} H${x} Z`;
  }
  if (dir === "left") {
    return `M${x + w},${y} H${x + radius} A${radius},${radius} 0 0 0 ${x},${y + radius}
            V${y + h - radius} A${radius},${radius} 0 0 0 ${x + radius},${y + h} H${x + w} Z`;
  }
  // "up": grows from a bottom baseline
  return `M${x},${y + h} V${y + radius} A${radius},${radius} 0 0 1 ${x + radius},${y}
          H${x + w - radius} A${radius},${radius} 0 0 1 ${x + w},${y + radius} V${y + h} Z`;
}

/** Approximate rendered text width, for deciding whether a label fits. */
function textWidth(text, fontSize = 11) {
  return String(text).length * fontSize * 0.58;
}

/* ---------------------------------------------------------------- tooltip */

function attachTooltip(container) {
  let tip = container.querySelector(".tooltip");
  if (!tip) {
    tip = document.createElement("div");
    tip.className = "tooltip";
    tip.setAttribute("role", "status");
    container.appendChild(tip);
  }
  return {
    node: tip,
    show(html, x, y) {
      tip.innerHTML = html;
      tip.dataset.show = "true";
      const bounds = container.getBoundingClientRect();
      const width = tip.offsetWidth;
      // Keep the tooltip inside the card rather than letting it clip.
      let left = x + 14;
      if (left + width > bounds.width - 4) left = x - width - 14;
      tip.style.left = `${Math.max(4, left)}px`;
      tip.style.top = `${Math.max(4, Math.min(y - 12, bounds.height - tip.offsetHeight - 4))}px`;
    },
    hide() {
      hideTooltip(tip);
    },
  };
}

/* An absolutely positioned element still extends the scroll area even at
   opacity 0, so parking it back at the origin is what actually prevents a
   stale tooltip from widening the page. */
function hideTooltip(tip) {
  if (!tip) return;
  tip.dataset.show = "false";
  tip.style.left = "0px";
  tip.style.top = "0px";
}

/** Re-render a chart whenever its container is resized or the theme flips. */
function responsive(container, draw) {
  const run = () => {
    const width = container.clientWidth;
    if (width <= 0) return;
    // A tooltip left open from a previous size would sit at stale coordinates
    // and could stick out past the new container width.
    hideTooltip(container.querySelector(".tooltip"));
    draw(width);
  };
  if (container._vizObserver) container._vizObserver.disconnect();
  const observer = new ResizeObserver(run);
  observer.observe(container);
  container._vizObserver = observer;
  document.addEventListener("themechange", run);
  run();
}

function emptyState(container, message) {
  container.innerHTML = `<p class="empty">${message}</p>`;
}

/* ------------------------------------------------------------- line chart */

/**
 * Single-series time line with an area wash, a crosshair and a tooltip.
 * One series, so no legend box -- the card title names what is plotted.
 */
export function lineChart(container, options) {
  const {
    points = [],
    xKey = "as_of",
    yKey = "nav",
    height = 300,
    currency = "USD",
    valueLabel = "Value",
  } = options;

  if (points.length < 2) {
    emptyState(container, "Not enough history yet. Sync again to build the series.");
    return;
  }

  const tooltip = attachTooltip(container);

  responsive(container, (width) => {
    const surface = token("--surface-1");
    const series = token("--series-1");
    const values = points.map((p) => Number(p[yKey]) || 0);
    const { ticks, lo, hi } = niceTicks(Math.min(...values), Math.max(...values), 5);

    const gutterLeft = 62;
    const pad = { top: 14, right: 16, bottom: 26, left: gutterLeft };
    const plotW = Math.max(10, width - pad.left - pad.right);
    const plotH = Math.max(10, height - pad.top - pad.bottom);

    const xAt = (i) => pad.left + (plotW * i) / (points.length - 1);
    const yAt = (v) => pad.top + plotH - ((v - lo) / (hi - lo || 1)) * plotH;

    const svg = el("svg", {
      viewBox: `0 0 ${width} ${height}`,
      width,
      height,
      role: "img",
      "aria-label": `${valueLabel} from ${points[0][xKey]} to ${points[points.length - 1][xKey]}`,
    });

    // Gridlines + y ticks, recessive.
    for (const t of ticks) {
      const y = yAt(t);
      if (y < pad.top - 1 || y > pad.top + plotH + 1) continue;
      svg.appendChild(
        el("line", {
          x1: pad.left, x2: pad.left + plotW, y1: y, y2: y,
          stroke: token("--grid"), "stroke-width": 1,
        }),
      );
      svg.appendChild(
        el("text", { x: pad.left - 10, y: y + 3.5, "text-anchor": "end", class: "tick" },
          fmt.compact(t, currency)),
      );
    }

    // X ticks: as many as fit without colliding (roughly 74px apart).
    const maxTicks = Math.max(2, Math.min(6, Math.floor(plotW / 74)));
    const step = Math.max(1, Math.ceil(points.length / maxTicks));
    for (let i = 0; i < points.length; i += step) {
      svg.appendChild(
        el("text", { x: xAt(i), y: height - 7, "text-anchor": "middle", class: "tick" },
          fmt.date(points[i][xKey])),
      );
    }

    const linePath = points
      .map((p, i) => `${i === 0 ? "M" : "L"}${xAt(i).toFixed(2)},${yAt(Number(p[yKey]) || 0).toFixed(2)}`)
      .join(" ");

    // Area wash at 10% -- a wash, never a saturated block.
    svg.appendChild(
      el("path", {
        d: `${linePath} L${xAt(points.length - 1)},${pad.top + plotH} L${pad.left},${pad.top + plotH} Z`,
        fill: series, "fill-opacity": 0.1, stroke: "none",
      }),
    );
    svg.appendChild(
      el("path", {
        d: linePath, fill: "none", stroke: series,
        "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round",
      }),
    );

    // End marker: r >= 4 with a 2px ring in the surface color.
    const lastX = xAt(points.length - 1);
    const lastY = yAt(values[values.length - 1]);
    svg.appendChild(
      el("circle", { cx: lastX, cy: lastY, r: 4.5, fill: series, stroke: surface, "stroke-width": 2 }),
    );

    // Hover layer: crosshair + roaming dot.
    const crosshair = el("line", {
      y1: pad.top, y2: pad.top + plotH,
      stroke: token("--axis"), "stroke-width": 1, opacity: 0,
    });
    const hoverDot = el("circle", {
      r: 4.5, fill: series, stroke: surface, "stroke-width": 2, opacity: 0,
    });
    svg.appendChild(crosshair);
    svg.appendChild(hoverDot);

    const hit = el("rect", {
      x: pad.left, y: pad.top, width: plotW, height: plotH, fill: "transparent",
    });
    const first = values[0];

    hit.addEventListener("pointermove", (event) => {
      const box = svg.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * width;
      const idx = Math.max(
        0,
        Math.min(points.length - 1, Math.round(((px - pad.left) / plotW) * (points.length - 1))),
      );
      const point = points[idx];
      const value = Number(point[yKey]) || 0;
      const x = xAt(idx);
      const y = yAt(value);

      crosshair.setAttribute("x1", x);
      crosshair.setAttribute("x2", x);
      crosshair.setAttribute("opacity", 1);
      hoverDot.setAttribute("cx", x);
      hoverDot.setAttribute("cy", y);
      hoverDot.setAttribute("opacity", 1);

      const change = first ? ((value / first - 1) * 100) : 0;
      tooltip.show(
        `<div class="t-title">${fmt.date(point[xKey], { year: "numeric", month: "short", day: "numeric" })}</div>
         <div class="t-row"><span>${valueLabel}</span><span>${fmt.currency(value, currency)}</span></div>
         <div class="t-row"><span>Since start</span><span class="${change >= 0 ? "up" : "down"}">${fmt.signedPct(change)}</span></div>`,
        (x / width) * container.clientWidth,
        (y / height) * height,
      );
    });
    hit.addEventListener("pointerleave", () => {
      crosshair.setAttribute("opacity", 0);
      hoverDot.setAttribute("opacity", 0);
      tooltip.hide();
    });
    svg.appendChild(hit);

    container.querySelector("svg")?.remove();
    container.insertBefore(svg, container.firstChild);
  });
}

/* -------------------------------------------------- horizontal magnitude bars */

/**
 * One measure across named categories. The category name is on the axis, so
 * color carries no identity here -- a single hue is correct, never a cycle.
 */
export function barsH(container, options) {
  const {
    rows = [],
    labelKey = "label",
    valueKey = "value",
    currency = "USD",
    rowHeight = 30,
    maxBar = 24,
    color = "--series-1",
    secondary = (row) => `${fmt.pct(row.weight_pct ?? 0, 1)} of book`,
  } = options;

  if (!rows.length) {
    emptyState(container, "Nothing to show.");
    return;
  }

  const tooltip = attachTooltip(container);

  responsive(container, (width) => {
    const surface = token("--surface-1");
    const hue = token(color);
    const height = rows.length * rowHeight + 8;

    // Reserve gutters: category names on the left, value labels on the right.
    const longestLabel = Math.max(...rows.map((r) => textWidth(r[labelKey], 12)));
    const longestValue = Math.max(
      ...rows.map((r) => textWidth(fmt.compact(r[valueKey], currency), 11)),
    );
    const left = Math.min(Math.max(72, longestLabel + 12), Math.max(90, width * 0.34));
    const right = longestValue + 14;
    const plotW = Math.max(10, width - left - right);
    const max = Math.max(...rows.map((r) => Math.abs(Number(r[valueKey]) || 0)), 1);

    const svg = el("svg", {
      viewBox: `0 0 ${width} ${height}`, width, height,
      role: "img", "aria-label": options.ariaLabel || "Horizontal bar chart",
    });

    rows.forEach((row, i) => {
      const value = Number(row[valueKey]) || 0;
      // A 2px surface gap separates adjacent bars; white does the separating.
      const barH = Math.min(maxBar, rowHeight - 8);
      const y = i * rowHeight + (rowHeight - barH) / 2 + 4;
      const w = Math.max(2, (Math.abs(value) / max) * plotW);

      const group = el("g", { class: "bar-row" });

      group.appendChild(
        el("text", {
          x: left - 10, y: y + barH / 2 + 4, "text-anchor": "end",
          class: "mark-label strong",
        }, row[labelKey]),
      );

      group.appendChild(
        el("path", { d: barPath(left, y, w, barH, "right"), fill: hue }),
      );

      // Value at the tip, outside the bar end -- it can never clip the text.
      group.appendChild(
        el("text", {
          x: left + w + 8, y: y + barH / 2 + 4, class: "mark-label",
        }, fmt.compact(value, currency)),
      );

      const hit = el("rect", {
        x: 0, y: i * rowHeight, width, height: rowHeight, fill: "transparent",
      });
      hit.addEventListener("pointerenter", () => {
        group.querySelector("path").setAttribute("fill-opacity", 0.82);
      });
      hit.addEventListener("pointermove", (event) => {
        const box = svg.getBoundingClientRect();
        tooltip.show(
          `<div class="t-title">${row[labelKey]}</div>
           <div class="t-row"><span>Value</span><span>${fmt.currency(value, currency)}</span></div>
           <div class="t-row"><span>Share</span><span>${secondary(row)}</span></div>`,
          event.clientX - box.left,
          i * rowHeight + rowHeight / 2,
        );
      });
      hit.addEventListener("pointerleave", () => {
        group.querySelector("path").removeAttribute("fill-opacity");
        tooltip.hide();
      });
      group.appendChild(hit);
      svg.appendChild(group);
    });

    // Baseline the bars grow from.
    svg.appendChild(
      el("line", {
        x1: left, x2: left, y1: 2, y2: height - 4,
        stroke: token("--axis"), "stroke-width": 1,
      }),
    );
    void surface;

    container.querySelector("svg")?.remove();
    container.insertBefore(svg, container.firstChild);
  });
}

/* ------------------------------------------------------- diverging P&L bars */

/**
 * Polarity around a zero baseline: gains right in blue, losses left in red,
 * with a neutral gray midline. Sign is carried by position and by a signed
 * value label, so color is never the only channel.
 */
export function divergingBars(container, options) {
  const {
    rows = [],
    labelKey = "symbol",
    valueKey = "unrealized_pnl",
    pctKey = "unrealized_pnl_pct",
    currency = "USD",
    rowHeight = 28,
    maxBar = 20,
  } = options;

  if (!rows.length) {
    emptyState(container, "No open positions to compare.");
    return;
  }

  const tooltip = attachTooltip(container);

  responsive(container, (width) => {
    const pos = token("--pos");
    const neg = token("--neg");
    const height = rows.length * rowHeight + 10;

    const labelW = Math.max(...rows.map((r) => textWidth(r[labelKey], 12)));
    const gutter = Math.min(Math.max(58, labelW + 14), width * 0.22);

    const values = rows.map((r) => Number(r[valueKey]) || 0);
    const maxGain = Math.max(0, ...values);
    const maxLoss = Math.max(0, ...values.map((v) => -v));
    const span = maxGain + maxLoss || 1;

    // Only reserve label room on a side that actually has bars, so a book that
    // is (say) all gains does not leave a third of the canvas empty.
    const labelRoom = textWidth("-$000.0K", 11) + 12;
    const leftLabel = maxLoss > 0 ? labelRoom : 0;
    const rightLabel = maxGain > 0 ? labelRoom : 0;

    const plotW = Math.max(20, width - gutter - leftLabel - rightLabel);
    // One px-per-dollar scale for both arms -- the arms differ in width only
    // because the data does, so bar lengths stay directly comparable.
    const scale = plotW / span;
    const zero = gutter + leftLabel + maxLoss * scale;

    const svg = el("svg", {
      viewBox: `0 0 ${width} ${height}`, width, height,
      role: "img", "aria-label": options.ariaLabel || "Unrealized profit and loss by position",
    });

    // Neutral zero midline -- the diverging midpoint is gray, never a hue.
    svg.appendChild(
      el("line", {
        x1: zero, x2: zero, y1: 2, y2: height - 6,
        stroke: token("--axis"), "stroke-width": 1,
      }),
    );

    rows.forEach((row, i) => {
      const value = Number(row[valueKey]) || 0;
      const gain = value >= 0;
      const barH = Math.min(maxBar, rowHeight - 8);
      const y = i * rowHeight + (rowHeight - barH) / 2 + 4;
      const w = Math.max(2, Math.abs(value) * scale);
      const x = gain ? zero : zero - w;

      const group = el("g");

      group.appendChild(
        el("text", {
          x: gutter - 4, y: y + barH / 2 + 4, "text-anchor": "end",
          class: "mark-label strong",
        }, row[labelKey]),
      );

      group.appendChild(
        el("path", {
          d: barPath(x, y, w, barH, gain ? "right" : "left"),
          fill: gain ? pos : neg,
        }),
      );

      // Signed value outside the tip: the second channel beside color.
      group.appendChild(
        el("text", {
          x: gain ? zero + w + 7 : zero - w - 7,
          y: y + barH / 2 + 4,
          "text-anchor": gain ? "start" : "end",
          class: "mark-label",
        }, `${gain ? "+" : "-"}${fmt.compact(Math.abs(value), currency)}`),
      );

      const hit = el("rect", {
        x: 0, y: i * rowHeight, width, height: rowHeight, fill: "transparent",
      });
      hit.addEventListener("pointerenter", () => {
        group.querySelector("path").setAttribute("fill-opacity", 0.82);
      });
      hit.addEventListener("pointermove", (event) => {
        const box = svg.getBoundingClientRect();
        tooltip.show(
          `<div class="t-title">${row[labelKey]}${row.description ? ` &middot; ${row.description}` : ""}</div>
           <div class="t-row"><span>Unrealized</span><span class="${gain ? "up" : "down"}">${fmt.currency(value, currency)}</span></div>
           <div class="t-row"><span>Return</span><span class="${gain ? "up" : "down"}">${fmt.signedPct(row[pctKey] ?? 0)}</span></div>
           <div class="t-row"><span>Market value</span><span>${fmt.currency(row.market_value ?? 0, currency)}</span></div>`,
          event.clientX - box.left,
          i * rowHeight + rowHeight / 2,
        );
      });
      hit.addEventListener("pointerleave", () => {
        group.querySelector("path").removeAttribute("fill-opacity");
        tooltip.hide();
      });
      group.appendChild(hit);
      svg.appendChild(group);
    });

    container.querySelector("svg")?.remove();
    container.insertBefore(svg, container.firstChild);
  });
}

export const internals = { niceTicks, barPath, textWidth };
