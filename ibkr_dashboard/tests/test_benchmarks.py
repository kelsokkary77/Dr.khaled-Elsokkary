"""Benchmark CSV parsing, driven by representative Stooq responses."""

import httpx
import pytest

from backend.providers import benchmarks
from backend.providers.base import ProviderError

CSV = "Date,Open,High,Low,Close,Volume\n2026-01-01,467.0,469.0,466.0,468.0,1000\n2026-01-02,468.0,471.0,467.5,470.0,1200\n"


class _FakeResponse:
    def __init__(self, text: str):
        self.text = text

    def raise_for_status(self) -> None:
        pass


def test_unknown_symbol_is_rejected():
    with pytest.raises(ProviderError, match="Unknown benchmark"):
        benchmarks.fetch_benchmark_series("MSFT")


def test_csv_is_parsed_into_sorted_close_prices(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(CSV))
    points = benchmarks.fetch_benchmark_series("SPY")
    assert points == [
        {"as_of": "2026-01-01", "close": 468.0},
        {"as_of": "2026-01-02", "close": 470.0},
    ]


def test_network_failure_is_a_readable_provider_error(monkeypatch):
    def _raise(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", _raise)
    with pytest.raises(ProviderError, match="Could not fetch"):
        benchmarks.fetch_benchmark_series("SPY")


def test_empty_response_is_a_readable_provider_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(""))
    with pytest.raises(ProviderError, match="no usable data"):
        benchmarks.fetch_benchmark_series("QQQ")


def test_a_maintenance_page_is_not_mistaken_for_csv(monkeypatch):
    """A proxy or error page must not surface as a parser crash."""
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _FakeResponse("<html><body>503</body></html>")
    )
    with pytest.raises(ProviderError, match="no usable data"):
        benchmarks.fetch_benchmark_series("SPY")


def test_rows_missing_a_close_are_skipped(monkeypatch):
    csv_text = "Date,Open,High,Low,Close,Volume\n2026-01-01,467.0,469.0,466.0,,1000\n2026-01-02,468.0,471.0,467.5,470.0,1200\n"
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(csv_text))
    points = benchmarks.fetch_benchmark_series("SPY")
    assert points == [{"as_of": "2026-01-02", "close": 470.0}]
