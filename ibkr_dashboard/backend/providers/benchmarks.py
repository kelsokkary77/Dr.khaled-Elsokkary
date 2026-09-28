"""Benchmark index prices for the "compare to the market" overlay on the NAV
chart.

QQQ tracks the Nasdaq-100 and is the standard tradable stand-in for "the
Nasdaq" in a portfolio comparison -- the raw Composite Index isn't a security
anyone can actually hold, so it doesn't answer "how did I do against the
market" the way an ETF a reader could have bought instead does.

Yahoo Finance's public chart endpoint needs no signup, no API key and no
CAPTCHA -- unlike Stooq (this module's original source), whose free CSV
export started requiring an API key obtained through an on-site CAPTCHA in
April 2026, which defeats the point of a background sync nobody has to
babysit. adjclose (dividend/split-adjusted) is used rather than the raw
close, since SPY and QQQ both pay dividends and an un-adjusted price would
understate their real total return next to the portfolio's own NAV, which
already reflects any dividend cash received.
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .base import ProviderError

# A generic browser UA -- Yahoo's endpoint is more prone to blocking requests
# that identify as a bare script than IBKR's own APIs are.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}
_YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"

# symbol -> (Yahoo ticker, display label)
BENCHMARKS: dict[str, tuple[str, str]] = {
    "SPY": ("SPY", "S&P 500 (SPY)"),
    "QQQ": ("QQQ", "Nasdaq-100 (QQQ)"),
}


def fetch_benchmark_series(symbol: str, days: int = 800) -> list[dict]:
    """Daily closes for one benchmark, oldest first, as [{"as_of", "close"}]."""
    if symbol not in BENCHMARKS:
        raise ProviderError(f"Unknown benchmark {symbol!r}.")
    yahoo_symbol, label = BENCHMARKS[symbol]

    period2 = int(datetime.now(timezone.utc).timestamp())
    period1 = period2 - max(days, 1) * 86400
    url = _YAHOO_CHART_URL.format(symbol=yahoo_symbol)
    params = {"period1": period1, "period2": period2, "interval": "1d"}

    try:
        response = httpx.get(
            url, params=params, headers=_HEADERS, timeout=20, follow_redirects=True
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not fetch {label} data: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError(
            f"Benchmark source returned an unreadable response for {label}."
        ) from exc

    results = ((payload or {}).get("chart") or {}).get("result") or []
    if not results:
        chart_error = ((payload or {}).get("chart") or {}).get("error") or {}
        detail = chart_error.get("description") or chart_error.get("code") or ""
        suffix = f": {detail}" if detail else ""
        raise ProviderError(f"Benchmark source returned no data for {label}{suffix}.")

    row = results[0]
    timestamps = row.get("timestamp") or []
    adjclose_blocks = (row.get("indicators") or {}).get("adjclose") or [{}]
    closes = adjclose_blocks[0].get("adjclose") or []

    out: list[dict] = []
    for ts, close in zip(timestamps, closes):
        if ts is None or close is None:
            continue
        as_of = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()
        out.append({"as_of": as_of, "close": float(close)})

    if not out:
        raise ProviderError(f"Benchmark source returned no usable rows for {label}.")

    out.sort(key=lambda p: p["as_of"])
    return out
