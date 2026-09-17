"""Derived portfolio metrics.

Everything here is a pure function of a :class:`PortfolioSnapshot` (plus, for
the NAV series, whatever history the store has accumulated). No I/O, so it is
straightforward to test.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date
from typing import Any, Callable, Iterable

from .models import NavPoint, PortfolioSnapshot, Position

TRADING_DAYS_PER_YEAR = 252

ASSET_CLASS_LABELS = {
    "STK": "Stocks",
    "ETF": "ETFs",
    "FUND": "Funds",
    "OPT": "Options",
    "FUT": "Futures",
    "FOP": "Futures options",
    "CASH": "Forex",
    "BOND": "Bonds",
    "WAR": "Warrants",
    "CFD": "CFDs",
    "CRYPTO": "Crypto",
}


# --------------------------------------------------------------------- buckets


def _bucket(
    positions: Iterable[Position],
    key: Callable[[Position], str],
    label: Callable[[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Group market value by a positional attribute, largest first."""
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    pnl: dict[str, float] = defaultdict(float)

    for position in positions:
        bucket = key(position) or "Unclassified"
        totals[bucket] += position.market_value
        counts[bucket] += 1
        pnl[bucket] += position.unrealized_pnl

    grand_total = sum(abs(v) for v in totals.values())
    rows = [
        {
            "key": name,
            "label": label(name) if label else name,
            "value": round(value, 2),
            "weight_pct": round(abs(value) / grand_total * 100.0, 4)
            if grand_total
            else 0.0,
            "count": counts[name],
            "unrealized_pnl": round(pnl[name], 2),
        }
        for name, value in totals.items()
    ]
    rows.sort(key=lambda r: abs(r["value"]), reverse=True)
    return rows


def allocation(snapshot: PortfolioSnapshot) -> dict[str, list[dict[str, Any]]]:
    """Allocation broken out four ways, plus cash as its own slice."""
    positions = snapshot.positions
    cash_total = sum(c.amount_base for c in snapshot.cash)

    by_asset_class = _bucket(
        positions,
        key=lambda p: p.asset_class,
        label=lambda k: ASSET_CLASS_LABELS.get(k, k.title()),
    )
    if cash_total:
        by_asset_class = _reweight(
            by_asset_class
            + [
                {
                    "key": "CASH_BALANCE",
                    "label": "Cash",
                    "value": round(cash_total, 2),
                    "weight_pct": 0.0,
                    "count": len(snapshot.cash),
                    "unrealized_pnl": 0.0,
                }
            ]
        )

    currency_rows = _bucket(positions, key=lambda p: p.currency)
    for balance in snapshot.cash:
        row = next((r for r in currency_rows if r["key"] == balance.currency), None)
        if row:
            row["value"] = round(row["value"] + balance.amount_base, 2)
        else:
            currency_rows.append(
                {
                    "key": balance.currency,
                    "label": balance.currency,
                    "value": round(balance.amount_base, 2),
                    "weight_pct": 0.0,
                    "count": 0,
                    "unrealized_pnl": 0.0,
                }
            )
    currency_rows = _reweight(currency_rows)

    return {
        "by_asset_class": by_asset_class,
        "by_sector": _bucket(positions, key=lambda p: p.sector),
        "by_currency": currency_rows,
        "by_country": _bucket(positions, key=lambda p: p.country or "Unknown"),
    }


def _reweight(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total = sum(abs(r["value"]) for r in rows)
    for row in rows:
        row["weight_pct"] = round(abs(row["value"]) / total * 100.0, 4) if total else 0.0
    rows.sort(key=lambda r: abs(r["value"]), reverse=True)
    return rows


# ------------------------------------------------------------------- holdings


def ranked_positions(snapshot: PortfolioSnapshot) -> list[dict[str, Any]]:
    """Positions with portfolio weight attached, largest position first."""
    total = sum(abs(p.market_value) for p in snapshot.positions)
    rows = []
    for position in snapshot.positions:
        row = position.to_dict()
        row["weight_pct"] = (
            round(abs(position.market_value) / total * 100.0, 4) if total else 0.0
        )
        rows.append(row)
    rows.sort(key=lambda r: abs(r["market_value"]), reverse=True)
    return rows


def concentration(snapshot: PortfolioSnapshot) -> dict[str, Any]:
    """How lopsided is the book?

    ``hhi`` is the Herfindahl-Hirschman index over position weights, expressed
    on 0-10,000. Its reciprocal, ``effective_holdings``, reads as "this book
    behaves like N equally sized positions".
    """
    total = sum(abs(p.market_value) for p in snapshot.positions)
    if not total:
        return {
            "hhi": 0.0,
            "effective_holdings": 0.0,
            "top1_pct": 0.0,
            "top5_pct": 0.0,
            "top10_pct": 0.0,
            "position_count": 0,
        }

    weights = sorted(
        (abs(p.market_value) / total for p in snapshot.positions), reverse=True
    )
    hhi = sum((w * 100.0) ** 2 for w in weights)
    return {
        "hhi": round(hhi, 2),
        "effective_holdings": round(10_000.0 / hhi, 2) if hhi else 0.0,
        "top1_pct": round(weights[0] * 100.0, 2),
        "top5_pct": round(sum(weights[:5]) * 100.0, 2),
        "top10_pct": round(sum(weights[:10]) * 100.0, 2),
        "position_count": len(weights),
    }


def winners_and_losers(
    snapshot: PortfolioSnapshot, limit: int = 8
) -> dict[str, list[dict[str, Any]]]:
    rows = [
        {
            "symbol": p.symbol,
            "description": p.description,
            "unrealized_pnl": round(p.unrealized_pnl, 2),
            "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 2),
            "market_value": round(p.market_value, 2),
        }
        for p in snapshot.positions
    ]
    ranked = sorted(rows, key=lambda r: r["unrealized_pnl"], reverse=True)
    return {
        "winners": [r for r in ranked if r["unrealized_pnl"] > 0][:limit],
        "losers": [r for r in reversed(ranked) if r["unrealized_pnl"] < 0][:limit],
    }


# ------------------------------------------------------------------ NAV series


def nav_metrics(points: list[NavPoint]) -> dict[str, Any]:
    """Return, volatility and drawdown from the NAV series.

    Returns are computed on the NAV itself, so deposits and withdrawals show up
    as performance. That is the honest caveat for any statement-derived series:
    it is a money-weighted picture, not a time-weighted one.
    """
    series = [p for p in sorted(points, key=lambda p: p.as_of) if p.nav]
    if len(series) < 2:
        return {
            "points": [p.to_dict() for p in series],
            "start_nav": series[0].nav if series else 0.0,
            "end_nav": series[-1].nav if series else 0.0,
            "total_return_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "max_drawdown_date": None,
            "volatility_annualized_pct": 0.0,
            "best_day_pct": 0.0,
            "worst_day_pct": 0.0,
            "observations": len(series),
            "caveat": "Not enough history yet -- sync again tomorrow to build the series.",
        }

    navs = [p.nav for p in series]
    daily_returns = [
        (navs[i] / navs[i - 1] - 1.0) for i in range(1, len(navs)) if navs[i - 1]
    ]

    peak = navs[0]
    max_dd = 0.0
    max_dd_date = series[0].as_of
    drawdown_series = []
    for point in series:
        peak = max(peak, point.nav)
        dd = (point.nav / peak - 1.0) if peak else 0.0
        drawdown_series.append({"as_of": point.as_of, "drawdown_pct": round(dd * 100.0, 4)})
        if dd < max_dd:
            max_dd = dd
            max_dd_date = point.as_of

    volatility = 0.0
    if len(daily_returns) > 1:
        mean = sum(daily_returns) / len(daily_returns)
        variance = sum((r - mean) ** 2 for r in daily_returns) / (
            len(daily_returns) - 1
        )
        volatility = math.sqrt(variance) * math.sqrt(TRADING_DAYS_PER_YEAR) * 100.0

    return {
        "points": [p.to_dict() for p in series],
        "drawdown": drawdown_series,
        "start_nav": round(navs[0], 2),
        "end_nav": round(navs[-1], 2),
        "start_date": series[0].as_of,
        "end_date": series[-1].as_of,
        "total_return_pct": round((navs[-1] / navs[0] - 1.0) * 100.0, 4)
        if navs[0]
        else 0.0,
        "max_drawdown_pct": round(max_dd * 100.0, 4),
        "max_drawdown_date": max_dd_date,
        "volatility_annualized_pct": round(volatility, 4),
        "best_day_pct": round(max(daily_returns) * 100.0, 4) if daily_returns else 0.0,
        "worst_day_pct": round(min(daily_returns) * 100.0, 4) if daily_returns else 0.0,
        "observations": len(series),
        "caveat": (
            "Return is money-weighted: deposits and withdrawals move the NAV line "
            "and are not stripped out."
        ),
    }


def trade_activity(snapshot: PortfolioSnapshot, months: int = 12) -> list[dict[str, Any]]:
    """Realized P&L and commissions grouped by month, oldest first."""
    buckets: dict[str, dict[str, float]] = defaultdict(
        lambda: {"realized_pnl": 0.0, "commission": 0.0, "trades": 0.0, "volume": 0.0}
    )
    for trade in snapshot.trades:
        month = trade.trade_date[:7]
        if len(month) != 7:
            continue
        bucket = buckets[month]
        bucket["realized_pnl"] += trade.realized_pnl
        bucket["commission"] += trade.commission
        bucket["trades"] += 1
        bucket["volume"] += abs(trade.quantity * trade.price)

    rows = [
        {
            "month": month,
            "realized_pnl": round(values["realized_pnl"], 2),
            "commission": round(values["commission"], 2),
            "trades": int(values["trades"]),
            "volume": round(values["volume"], 2),
        }
        for month, values in buckets.items()
    ]
    rows.sort(key=lambda r: r["month"])
    return rows[-months:]


# ----------------------------------------------------------------- top-level


def build_dashboard(
    snapshot: PortfolioSnapshot, nav_points: list[NavPoint] | None = None
) -> dict[str, Any]:
    """Assemble the single payload the frontend renders."""
    points = nav_points if nav_points else snapshot.nav_history
    return {
        "generated_at": date.today().isoformat(),
        "provider": snapshot.provider,
        "fetched_at": snapshot.fetched_at,
        "summary": snapshot.summary.to_dict(),
        "positions": ranked_positions(snapshot),
        "cash": [c.to_dict() for c in snapshot.cash],
        "trades": [t.to_dict() for t in snapshot.trades],
        "allocation": allocation(snapshot),
        "concentration": concentration(snapshot),
        "movers": winners_and_losers(snapshot),
        "nav": nav_metrics(points),
        "activity": trade_activity(snapshot),
        "warnings": list(snapshot.warnings),
    }
