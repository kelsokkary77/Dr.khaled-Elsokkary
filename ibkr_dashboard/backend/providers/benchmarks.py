"""Benchmark index prices for the "compare to the market" overlay on the NAV
chart.

QQQ tracks the Nasdaq-100 and is the standard tradable stand-in for "the
Nasdaq" in a portfolio comparison -- the raw Composite Index isn't a security
anyone can actually hold, so it doesn't answer "how did I do against the
market" the way an ETF a reader could have bought instead does.

Stooq's plain-CSV endpoint needs no API key and no account, which matches
this app's other read-only, credential-light data sources.
"""

from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import httpx

from .base import ProviderError

_HEADERS = {"User-Agent": "ibkr-dashboard/1.0 (+python-httpx)"}
_STOOQ_URL = "https://stooq.com/q/d/l/"

# symbol -> (Stooq ticker, display label)
BENCHMARKS: dict[str, tuple[str, str]] = {
    "SPY": ("spy.us", "S&P 500 (SPY)"),
    "QQQ": ("qqq.us", "Nasdaq-100 (QQQ)"),
}


def fetch_benchmark_series(symbol: str, days: int = 800) -> list[dict]:
    """Daily closes for one benchmark, oldest first, as [{"as_of", "close"}]."""
    if symbol not in BENCHMARKS:
        raise ProviderError(f"Unknown benchmark {symbol!r}.")
    stooq_symbol, label = BENCHMARKS[symbol]
    start = (date.today() - timedelta(days=max(days, 1))).strftime("%Y%m%d")
    url = f"{_STOOQ_URL}?s={stooq_symbol}&d1={start}&i=d"

    try:
        response = httpx.get(url, headers=_HEADERS, timeout=20, follow_redirects=True)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"Could not fetch {label} data: {exc}") from exc

    text = response.text.strip()
    if not text or "," not in text.splitlines()[0]:
        raise ProviderError(f"Benchmark source returned no usable data for {label}.")

    out: list[dict] = []
    for row in csv.DictReader(io.StringIO(text)):
        as_of = (row.get("Date") or "").strip()
        close = (row.get("Close") or "").strip()
        if not as_of or not close:
            continue
        try:
            out.append({"as_of": as_of, "close": float(close)})
        except ValueError:
            continue

    if not out:
        raise ProviderError(f"Benchmark source returned no rows for {label}.")

    out.sort(key=lambda p: p["as_of"])
    return out
