"""Benchmark fetching, driven by representative Yahoo Finance chart responses."""

import httpx
import pytest

from backend.providers import benchmarks
from backend.providers.base import ProviderError

# Two trading days, unix timestamps for 2026-01-01 and 2026-01-02 UTC.
CHART_PAYLOAD = {
    "chart": {
        "result": [
            {
                "timestamp": [1767225600, 1767312000],
                "indicators": {"adjclose": [{"adjclose": [468.0, 470.0]}]},
            }
        ],
        "error": None,
    }
}


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self):
        return self._payload


def test_unknown_symbol_is_rejected():
    with pytest.raises(ProviderError, match="Unknown benchmark"):
        benchmarks.fetch_benchmark_series("MSFT")


def test_chart_payload_is_parsed_into_sorted_close_prices(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(CHART_PAYLOAD))
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


def test_non_json_response_is_a_readable_provider_error(monkeypatch):
    class _NotJson:
        def raise_for_status(self):
            pass

        def json(self):
            raise ValueError("not json")

    monkeypatch.setattr(httpx, "get", lambda *a, **k: _NotJson())
    with pytest.raises(ProviderError, match="unreadable response"):
        benchmarks.fetch_benchmark_series("SPY")


def test_an_error_payload_with_no_result_is_a_readable_provider_error(monkeypatch):
    payload = {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(payload))
    with pytest.raises(ProviderError, match="No data found"):
        benchmarks.fetch_benchmark_series("QQQ")


def test_rows_with_a_null_close_are_skipped(monkeypatch):
    payload = {
        "chart": {
            "result": [
                {
                    "timestamp": [1767225600, 1767312000],
                    "indicators": {"adjclose": [{"adjclose": [None, 470.0]}]},
                }
            ],
            "error": None,
        }
    }
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(payload))
    points = benchmarks.fetch_benchmark_series("SPY")
    assert points == [{"as_of": "2026-01-02", "close": 470.0}]


def test_no_rows_at_all_is_a_readable_provider_error(monkeypatch):
    payload = {"chart": {"result": [{"timestamp": [], "indicators": {"adjclose": [{"adjclose": []}]}}], "error": None}}
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse(payload))
    with pytest.raises(ProviderError, match="no usable rows"):
        benchmarks.fetch_benchmark_series("SPY")
