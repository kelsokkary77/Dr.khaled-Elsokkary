"""DashboardService.benchmarks(): caching, staleness, and history coverage."""

from datetime import datetime, timedelta, timezone

import pytest

from backend.service import DashboardService


def _fake_fetch(calls):
    def fetch(symbol: str, days: int) -> list[dict]:
        calls.append((symbol, days))
        # Far enough in the past that it satisfies whatever lookback the
        # test asked for -- these tests are about the freshness/force
        # decision, not the "does the cache reach back far enough" one
        # (that's covered by test_lookback_covers_the_full_nav_history_on_record).
        return [{"as_of": "2000-01-01", "close": 100.0}]

    return fetch


@pytest.fixture
def service(settings, store) -> DashboardService:
    return DashboardService(settings, store)


def test_first_call_fetches_every_requested_symbol(service):
    calls = []
    result = service.benchmarks(["SPY", "QQQ"], fetch_fn=_fake_fetch(calls))
    assert {c[0] for c in calls} == {"SPY", "QQQ"}
    assert result["series"]["SPY"] == [{"as_of": "2000-01-01", "close": 100.0}]
    assert result["warnings"] == []


def test_fresh_cache_is_not_refetched(service):
    service.benchmarks(["SPY"], fetch_fn=_fake_fetch([]))
    calls = []
    service.benchmarks(["SPY"], fetch_fn=_fake_fetch(calls))
    assert calls == []


def test_force_refetches_even_when_fresh(service):
    service.benchmarks(["SPY"], fetch_fn=_fake_fetch([]))
    calls = []
    service.benchmarks(["SPY"], force=True, fetch_fn=_fake_fetch(calls))
    assert len(calls) == 1


def test_stale_cache_is_refetched(service, store):
    service.benchmarks(["SPY"], fetch_fn=_fake_fetch([]))
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    with store._connect() as conn:
        conn.execute("UPDATE benchmark_history SET fetched_at = ?", (old,))
    calls = []
    service.benchmarks(["SPY"], fetch_fn=_fake_fetch(calls))
    assert len(calls) == 1


def test_a_symbol_outside_the_known_set_is_ignored(service):
    calls = []
    result = service.benchmarks(["MSFT"], fetch_fn=_fake_fetch(calls))
    assert calls == []
    assert result["series"] == {}


def test_fetch_failure_is_reported_as_a_warning_not_an_exception(service):
    def failing_fetch(symbol, days):
        from backend.providers.base import ProviderError

        raise ProviderError(f"could not reach {symbol}")

    result = service.benchmarks(["SPY"], fetch_fn=failing_fetch)
    assert "could not reach SPY" in result["warnings"][0]
    assert result["series"]["SPY"] == []


def test_lookback_covers_the_full_nav_history_on_record(service, store):
    from backend.models import NavPoint

    store.record_nav([NavPoint("2024-01-01", 1000.0)], account_id="U1")
    calls = []
    service.benchmarks(["SPY"], fetch_fn=_fake_fetch(calls))
    # However many days it is from 2024-01-01 to today, it must be well past
    # the 800-day default -- the point is that NAV history, not a fixed
    # window, drives how far back the benchmark fetch reaches.
    assert calls[0][1] > 800
