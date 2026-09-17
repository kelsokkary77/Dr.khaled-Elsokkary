import { fmt, lineChart, barsH, divergingBars } from "./charts.js";

const state = {
  data: null,
  currency: "USD",
  navRange: "6M",
  allocationDim: "by_asset_class",
  positionSort: { key: "market_value", dir: "desc" },
  views: {}, // chartId -> "chart" | "table"
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

/* ------------------------------------------------------------------ theme */

/* localStorage can throw (private mode, blocked site data) and can come back
   empty, so every access is guarded and the page renders fine without it. */
function readStored(key, fallback) {
  try {
    return localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeStored(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch {
    /* per-viewer convenience only -- never required for correctness */
  }
}

function applyTheme(theme) {
  if (theme === "auto") {
    document.documentElement.removeAttribute("data-theme");
  } else {
    document.documentElement.setAttribute("data-theme", theme);
  }
  $("#theme-toggle").textContent =
    theme === "dark" ? "Dark" : theme === "light" ? "Light" : "Auto";
  document.dispatchEvent(new Event("themechange"));
}

function initTheme() {
  let theme = readStored("ibkr.theme", "auto");
  applyTheme(theme);
  $("#theme-toggle").addEventListener("click", () => {
    theme = theme === "auto" ? "light" : theme === "light" ? "dark" : "auto";
    writeStored("ibkr.theme", theme);
    applyTheme(theme);
  });
}

/* ------------------------------------------------------------------- data */

async function loadDashboard({ refresh = false } = {}) {
  setBusy(true);
  try {
    if (refresh) {
      const syncRes = await fetch("/api/sync", { method: "POST" });
      const syncBody = await syncRes.json();
      if (!syncRes.ok || syncBody.error) {
        showError(syncBody.error || `Sync failed (HTTP ${syncRes.status})`);
        return;
      }
    }
    const res = await fetch("/api/dashboard");
    const body = await res.json();
    if (!res.ok || body.error) {
      showError(body.error || `Could not load data (HTTP ${res.status})`);
      return;
    }
    state.data = body;
    state.currency = body.base_currency || "USD";
    clearError();
    render();
  } catch (err) {
    showError(`Could not reach the dashboard server: ${err.message}`);
  } finally {
    setBusy(false);
  }
}

function setBusy(busy) {
  const btn = $("#sync");
  btn.disabled = busy;
  btn.textContent = busy ? "Syncing..." : "Sync now";
}

function showError(message) {
  const box = $("#error");
  box.innerHTML = `<span class="icon">&#9888;</span><div><strong>Sync problem.</strong> ${escapeHtml(message)}</div>`;
  box.hidden = false;
}

function clearError() {
  $("#error").hidden = true;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]),
  );
}

/* ----------------------------------------------------------------- render */

function render() {
  const d = state.data;
  if (!d) return;
  renderHeader(d);
  renderWarnings(d);
  renderHero(d);
  renderNav(d);
  renderAllocation(d);
  renderHoldings(d);
  renderPnl(d);
  renderPositionsTable(d);
  renderCashTable(d);
  renderTradesTable(d);
  renderFooter(d);
}

function renderHeader(d) {
  const account = d.summary.account_id
    ? `${d.summary.account_id}${d.summary.account_alias ? ` · ${d.summary.account_alias}` : ""}`
    : "No account";
  $("#chip-account").textContent = account;

  const live = d.provider !== "demo";
  const dot = $("#chip-provider .dot");
  dot.className = `dot ${live ? "live" : "demo"}`;
  $("#chip-provider .txt").textContent =
    d.provider === "demo"
      ? "Sample data"
      : d.provider === "flex"
        ? "Flex Web Service"
        : "Client Portal (live)";

  const fetched = d.fetched_at ? new Date(d.fetched_at) : null;
  $("#chip-sync").textContent = fetched
    ? `Synced ${fetched.toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}`
    : "Never synced";
}

function renderWarnings(d) {
  const box = $("#warnings");
  const items = d.warnings || [];
  if (!items.length) {
    box.hidden = true;
    return;
  }
  box.innerHTML =
    `<span class="icon">&#9432;</span><div>${items.map(escapeHtml).join("<br>")}</div>`;
  box.hidden = false;
}

function renderHero(d) {
  const s = d.summary;
  const c = state.currency;
  $("#hero-nav").textContent = fmt.currency(s.net_liquidation, c);

  const delta = $("#hero-delta");
  const up = s.day_change >= 0;
  delta.className = `delta ${up ? "up" : "down"}`;
  delta.textContent = s.day_change
    ? `${up ? "▲" : "▼"} ${fmt.currency(Math.abs(s.day_change), c)} (${fmt.signedPct(s.day_change_pct)}) vs prior close`
    : "";

  const pnlUp = s.unrealized_pnl >= 0;
  const tiles = [
    { label: "Securities", value: fmt.currency(s.securities_gross_value, c),
      note: `${d.concentration.position_count} positions` },
    { label: "Cash", value: fmt.currency(s.total_cash, c),
      note: `${d.cash.length} ${d.cash.length === 1 ? "currency" : "currencies"}` },
    { label: "Unrealized P&L", value: fmt.currency(s.unrealized_pnl, c),
      note: `${pnlUp ? "Gain" : "Loss"} on open positions`, cls: pnlUp ? "up" : "down" },
    { label: "Realized P&L", value: fmt.currency(s.realized_pnl, c),
      note: "From closed trades", cls: s.realized_pnl >= 0 ? "up" : "down" },
    { label: "Top 5 weight", value: fmt.pct(d.concentration.top5_pct, 1),
      note: `Behaves like ${fmt.number(d.concentration.effective_holdings, 1)} equal positions` },
    { label: "Max drawdown", value: fmt.pct(d.nav.max_drawdown_pct, 1),
      note: d.nav.max_drawdown_date ? `Trough ${fmt.date(d.nav.max_drawdown_date)}` : "",
      cls: "down" },
  ];

  $("#tiles").innerHTML = tiles
    .map(
      (t) => `<div class="tile">
        <div class="label">${t.label}</div>
        <div class="value ${t.cls || ""}">${t.value}</div>
        <div class="delta">${t.note || ""}</div>
      </div>`,
    )
    .join("");
}

/* -------------------------------------------------------------- NAV chart */

const RANGE_DAYS = { "1M": 30, "3M": 91, "6M": 182, "1Y": 365, ALL: Infinity };

function navPointsForRange(d) {
  const points = d.nav.points || [];
  const days = RANGE_DAYS[state.navRange] ?? Infinity;
  if (!Number.isFinite(days) || !points.length) return points;
  const cutoff = new Date();
  cutoff.setDate(cutoff.getDate() - days);
  const filtered = points.filter((p) => new Date(`${p.as_of.slice(0, 10)}T00:00:00`) >= cutoff);
  // Never render a one-point line; fall back to the full series.
  return filtered.length >= 2 ? filtered : points;
}

function renderNav(d) {
  const points = navPointsForRange(d);
  const n = d.nav;

  $("#nav-sub").textContent = n.observations
    ? `${n.observations} observations · ${fmt.signedPct(n.total_return_pct)} total · ${fmt.pct(n.volatility_annualized_pct, 1)} annualized volatility`
    : "";

  if (state.views.nav === "table") {
    renderTableView("#nav-chart", ["Date", "NAV", "Cash", "Securities"],
      points.slice().reverse().map((p) => [
        fmt.date(p.as_of, { year: "numeric", month: "short", day: "numeric" }),
        fmt.currency(p.nav, state.currency),
        fmt.currency(p.cash, state.currency),
        fmt.currency(p.securities, state.currency),
      ]));
    return;
  }

  lineChart($("#nav-chart"), {
    points,
    height: 300,
    currency: state.currency,
    valueLabel: "Net liquidation",
  });
}

/* ------------------------------------------------------------- allocation */

const DIM_LABEL = {
  by_asset_class: "asset class",
  by_sector: "sector",
  by_currency: "currency",
  by_country: "country",
};

function renderAllocation(d) {
  const rows = (d.allocation[state.allocationDim] || []).slice(0, 12);
  $("#alloc-sub").textContent = `${rows.length} ${DIM_LABEL[state.allocationDim]} groups`;

  if (state.views.alloc === "table") {
    renderTableView("#alloc-chart", ["Group", "Value", "Weight", "Holdings"],
      rows.map((r) => [
        r.label,
        fmt.currency(r.value, state.currency),
        fmt.pct(r.weight_pct, 1),
        String(r.count),
      ]));
    return;
  }

  barsH($("#alloc-chart"), {
    rows,
    currency: state.currency,
    ariaLabel: `Allocation by ${DIM_LABEL[state.allocationDim]}`,
    secondary: (row) => `${fmt.pct(row.weight_pct, 1)} of book`,
  });
}

function renderHoldings(d) {
  const rows = d.positions.slice(0, 10).map((p) => ({
    label: p.symbol,
    value: p.market_value,
    weight_pct: p.weight_pct,
    count: 1,
  }));
  $("#holdings-sub").textContent = `Top ${rows.length} of ${d.positions.length} positions`;

  if (state.views.holdings === "table") {
    renderTableView("#holdings-chart", ["Symbol", "Market value", "Weight"],
      rows.map((r) => [r.label, fmt.currency(r.value, state.currency), fmt.pct(r.weight_pct, 1)]));
    return;
  }

  barsH($("#holdings-chart"), {
    rows,
    currency: state.currency,
    ariaLabel: "Top holdings by market value",
    secondary: (row) => `${fmt.pct(row.weight_pct, 1)} of book`,
  });
}

function renderPnl(d) {
  const rows = d.positions
    .slice()
    .sort((a, b) => b.unrealized_pnl - a.unrealized_pnl)
    .slice(0, 14);

  const gains = rows.filter((r) => r.unrealized_pnl >= 0).length;
  $("#pnl-sub").textContent = `${gains} in profit · ${rows.length - gains} in loss`;

  if (state.views.pnl === "table") {
    renderTableView("#pnl-chart", ["Symbol", "Unrealized P&L", "Return", "Market value"],
      rows.map((r) => [
        r.symbol,
        fmt.currency(r.unrealized_pnl, state.currency),
        fmt.signedPct(r.unrealized_pnl_pct),
        fmt.currency(r.market_value, state.currency),
      ]));
    return;
  }

  divergingBars($("#pnl-chart"), { rows, currency: state.currency });
}

/** The table view every chart falls back to -- identity is never color-only. */
function renderTableView(selector, headers, rows) {
  const container = $(selector);
  container.querySelector("svg")?.remove();
  container.querySelector(".tooltip")?.remove();
  container.innerHTML = `<div class="table-scroll"><table>
      <thead><tr>${headers.map((h) => `<th>${h}</th>`).join("")}</tr></thead>
      <tbody>${rows
        .map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`)
        .join("")}</tbody>
    </table></div>`;
}

/* ----------------------------------------------------------------- tables */

const POSITION_COLUMNS = [
  { key: "symbol", label: "Symbol", type: "text" },
  { key: "description", label: "Name", type: "text", cls: "desc" },
  { key: "asset_class", label: "Class", type: "badge" },
  { key: "currency", label: "Ccy", type: "text" },
  { key: "quantity", label: "Qty", type: "number", digits: 0 },
  { key: "mark_price", label: "Mark", type: "price" },
  { key: "cost_basis_price", label: "Avg cost", type: "price" },
  { key: "market_value", label: "Market value", type: "money" },
  { key: "weight_pct", label: "Weight", type: "pct" },
  { key: "unrealized_pnl", label: "Unrealized P&L", type: "money", signed: true },
  { key: "unrealized_pnl_pct", label: "Return", type: "pct", signed: true },
];

function renderPositionsTable(d) {
  const { key, dir } = state.positionSort;
  const rows = d.positions.slice().sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    const cmp = typeof av === "string" ? av.localeCompare(bv) : (av ?? 0) - (bv ?? 0);
    return dir === "asc" ? cmp : -cmp;
  });

  $("#positions-sub").textContent =
    `${rows.length} open positions · click a column to sort`;

  const head = POSITION_COLUMNS.map((c) => {
    const active = c.key === key;
    const sortAttr = active ? ` aria-sort="${dir === "asc" ? "ascending" : "descending"}"` : "";
    const arrow = active ? (dir === "asc" ? "▲" : "▼") : "▾";
    return `<th class="sortable" data-key="${c.key}"${sortAttr}>${c.label}<span class="arrow">${arrow}</span></th>`;
  }).join("");

  const body = rows
    .map((r) => `<tr>${POSITION_COLUMNS.map((c) => cell(r, c)).join("")}</tr>`)
    .join("");

  $("#positions-table").innerHTML =
    `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;

  $$("#positions-table th.sortable").forEach((th) => {
    th.addEventListener("click", () => {
      const nextKey = th.dataset.key;
      state.positionSort =
        state.positionSort.key === nextKey
          ? { key: nextKey, dir: state.positionSort.dir === "asc" ? "desc" : "asc" }
          : { key: nextKey, dir: "desc" };
      renderPositionsTable(state.data);
    });
  });
}

function cell(row, col) {
  const value = row[col.key];
  const c = state.currency;
  switch (col.type) {
    case "badge":
      return `<td><span class="badge">${escapeHtml(value ?? "")}</span></td>`;
    case "money": {
      const cls = col.signed ? (value >= 0 ? "up" : "down") : "";
      return `<td class="${cls}">${fmt.currency(value, c)}</td>`;
    }
    case "price":
      return `<td>${fmt.number(value, 2)}</td>`;
    case "number":
      return `<td>${fmt.number(value, col.digits ?? 0)}</td>`;
    case "pct": {
      const cls = col.signed ? (value >= 0 ? "up" : "down") : "";
      const text = col.signed ? fmt.signedPct(value, 1) : fmt.pct(value, 1);
      return `<td class="${cls}">${text}</td>`;
    }
    default: {
      const cls = col.cls || (col.key === "symbol" ? "sym" : "");
      return `<td class="${cls}" title="${escapeHtml(value ?? "")}">${escapeHtml(value ?? "")}</td>`;
    }
  }
}

function renderCashTable(d) {
  const c = state.currency;
  const total = d.cash.reduce((sum, r) => sum + r.amount_base, 0);
  if (!d.cash.length) {
    $("#cash-table").innerHTML = `<p class="empty">No cash balances reported.</p>`;
    return;
  }
  $("#cash-table").innerHTML = `<table>
    <thead><tr><th>Currency</th><th>Balance</th><th>In ${escapeHtml(c)}</th><th>Share</th></tr></thead>
    <tbody>${d.cash
      .slice()
      .sort((a, b) => b.amount_base - a.amount_base)
      .map(
        (r) => `<tr>
          <td class="sym">${escapeHtml(r.currency)}</td>
          <td>${fmt.number(r.amount, 2)}</td>
          <td>${fmt.currency(r.amount_base, c)}</td>
          <td>${fmt.pct(total ? (r.amount_base / total) * 100 : 0, 1)}</td>
        </tr>`,
      )
      .join("")}</tbody></table>`;
}

function renderTradesTable(d) {
  const trades = (d.trades || []).slice(0, 40);
  if (!trades.length) {
    $("#trades-table").innerHTML =
      `<p class="empty">No trades in the synced period. Add the Trades section to your Flex query to see them here.</p>`;
    $("#trades-sub").textContent = "";
    return;
  }
  $("#trades-sub").textContent = `Most recent ${trades.length} of ${d.trades.length}`;
  $("#trades-table").innerHTML = `<table>
    <thead><tr>
      <th>Date</th><th>Symbol</th><th>Side</th><th>Qty</th>
      <th>Price</th><th>Proceeds</th><th>Commission</th><th>Realized P&L</th>
    </tr></thead>
    <tbody>${trades
      .map(
        (t) => `<tr>
          <td>${fmt.date(t.trade_date, { year: "numeric", month: "short", day: "numeric" })}</td>
          <td class="sym">${escapeHtml(t.symbol)}</td>
          <td><span class="badge">${escapeHtml(t.side)}</span></td>
          <td>${fmt.number(Math.abs(t.quantity), 0)}</td>
          <td>${fmt.number(t.price, 2)}</td>
          <td>${fmt.currency(t.proceeds, t.currency)}</td>
          <td>${fmt.currency(t.commission, t.currency)}</td>
          <td class="${t.realized_pnl >= 0 ? "up" : "down"}">${t.realized_pnl ? fmt.currency(t.realized_pnl, t.currency) : "--"}</td>
        </tr>`,
      )
      .join("")}</tbody></table>`;
}

function renderFooter(d) {
  const parts = [];
  if (d.nav.caveat) parts.push(d.nav.caveat);
  if (d.storage) {
    parts.push(
      `${d.storage.nav_points} NAV rows and ${d.storage.snapshots} snapshots cached locally.`,
    );
  }
  parts.push("Values are shown in the account's base currency as reported by IBKR.");
  $("#foot").textContent = parts.join(" ");
}

/* ---------------------------------------------------------------- wiring */

function initControls() {
  $("#sync").addEventListener("click", () => loadDashboard({ refresh: true }));

  $$("[data-range]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.navRange = btn.dataset.range;
      $$("[data-range]").forEach((b) =>
        b.setAttribute("aria-pressed", String(b === btn)),
      );
      renderNav(state.data);
    });
  });

  $$("[data-dim]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.allocationDim = btn.dataset.dim;
      $$("[data-dim]").forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
      renderAllocation(state.data);
    });
  });

  $$("[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const chart = btn.dataset.view;
      const next = state.views[chart] === "table" ? "chart" : "table";
      state.views[chart] = next;
      btn.setAttribute("aria-pressed", String(next === "table"));
      btn.textContent = next === "table" ? "Chart" : "Table";
      ({ nav: renderNav, alloc: renderAllocation, holdings: renderHoldings, pnl: renderPnl }[
        chart
      ])(state.data);
    });
  });
}

initTheme();
initControls();
loadDashboard();
