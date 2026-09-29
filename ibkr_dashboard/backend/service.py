"""Sync orchestration: provider -> store -> dashboard payload."""

from __future__ import annotations

import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

from . import analytics
from .config import Settings
from .models import PortfolioSnapshot
from .providers import ProviderError, get_provider
from .providers import benchmarks as benchmarks_provider
from .store import SnapshotStore

# Daily-close data doesn't change intraday -- refetching more than once a day
# would just be hammering a free, keyless source for the same numbers.
BENCHMARK_REFRESH_HOURS = 20


class DashboardService:
    def __init__(self, settings: Settings, store: SnapshotStore | None = None) -> None:
        self.settings = settings
        self.store = store or SnapshotStore(settings.db_path)
        # One sync at a time: IBKR rate-limits, and concurrent syncs would race
        # on the same NAV rows.
        self._sync_lock = threading.Lock()

    # ------------------------------------------------------------------- sync

    def sync(self, provider_name: str | None = None) -> PortfolioSnapshot:
        if not self._sync_lock.acquire(blocking=False):
            raise ProviderError("A sync is already running. Try again in a moment.")
        try:
            provider = get_provider(self.settings, provider_name)
            try:
                snapshot = provider.fetch()
            except ProviderError as exc:
                self.store.log_sync(provider.name, ok=False, message=str(exc))
                raise
            except Exception as exc:  # noqa: BLE001 - surface anything as a clean error
                message = f"Unexpected error while syncing: {exc!r}"
                self.store.log_sync(provider.name, ok=False, message=message)
                raise ProviderError(message) from exc

            self.store.save_snapshot(snapshot)
            self.store.prune()
            self.store.log_sync(
                provider.name,
                ok=True,
                message=(
                    f"{len(snapshot.positions)} positions, "
                    f"{len(snapshot.nav_history)} NAV rows"
                ),
            )
            return snapshot
        finally:
            self._sync_lock.release()

    # ------------------------------------------------------------------ reads

    def current_snapshot(self, allow_sync: bool = True) -> PortfolioSnapshot:
        snapshot = self.store.latest_snapshot()
        if snapshot is None and allow_sync:
            snapshot = self.sync()
        if snapshot is None:
            raise ProviderError("No data cached yet. Run a sync first.")
        return snapshot

    def dashboard(self, allow_sync: bool = True) -> dict[str, Any]:
        snapshot = self.current_snapshot(allow_sync=allow_sync)
        account_id = snapshot.summary.account_id or ""

        # Prefer the accumulated series -- it spans more than one sync.
        stored = self.store.nav_series(account_id=account_id)
        if len(stored) < len(snapshot.nav_history):
            stored = snapshot.nav_history

        payload = analytics.build_dashboard(snapshot, nav_points=stored)
        payload["base_currency"] = (
            snapshot.summary.base_currency or self.settings.base_currency
        )
        payload["total_deposited"] = self.settings.total_deposited
        payload["last_sync"] = self.store.last_sync()
        payload["storage"] = self.store.counts()
        return payload

    # --------------------------------------------------------------- benchmarks

    def benchmarks(
        self,
        symbols: list[str] | None = None,
        force: bool = False,
        fetch_fn: Callable[[str, int], list[dict]] | None = None,
    ) -> dict[str, Any]:
        """S&P 500 / Nasdaq daily closes for the NAV chart's comparison
        overlay, cached in SQLite and refetched at most once a day (or when
        the cached history doesn't reach back far enough for what's asked).

        fetch_fn defaults to the real network fetch, looked up on the module
        rather than bound as a default argument, so tests can monkeypatch
        backend.providers.benchmarks.fetch_benchmark_series and have it take
        effect on every call site, not just ones that pass fetch_fn directly.
        """
        fetch = fetch_fn or benchmarks_provider.fetch_benchmark_series
        wanted = [s for s in (symbols or benchmarks_provider.BENCHMARKS) if s in benchmarks_provider.BENCHMARKS]
        days_needed = self._benchmark_days_needed()

        series: dict[str, list[dict]] = {}
        warnings: list[str] = []
        for symbol in wanted:
            if force or self._benchmark_needs_refresh(symbol, days_needed):
                try:
                    points = fetch(symbol, days_needed)
                    self.store.save_benchmark_series(symbol, points)
                except ProviderError as exc:
                    warnings.append(str(exc))
            series[symbol] = self.store.benchmark_series(symbol)

        return {"series": series, "warnings": warnings}

    def _benchmark_days_needed(self) -> int:
        """At least enough to cover every NAV point on record, so the "All"
        time range has something to compare against too."""
        nav_points = self.store.nav_series()
        if not nav_points:
            return 800
        earliest = min(p.as_of for p in nav_points)
        try:
            span = (date.today() - date.fromisoformat(earliest)).days + 5
        except ValueError:
            return 800
        return max(span, 30)

    def _benchmark_needs_refresh(self, symbol: str, days_needed: int) -> bool:
        last_fetched = self.store.benchmark_last_fetched(symbol)
        if not last_fetched:
            return True
        try:
            fetched_at = datetime.fromisoformat(last_fetched)
        except ValueError:
            return True
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) - fetched_at > timedelta(hours=BENCHMARK_REFRESH_HOURS):
            return True

        earliest = self.store.benchmark_earliest(symbol)
        if not earliest:
            return True
        needed_from = (date.today() - timedelta(days=days_needed)).isoformat()
        return earliest > needed_from

    def status(self) -> dict[str, Any]:
        snapshot = self.store.latest_snapshot()
        return {
            "provider": self.settings.provider,
            "has_data": snapshot is not None,
            "fetched_at": snapshot.fetched_at if snapshot else None,
            "account_id": snapshot.summary.account_id if snapshot else None,
            "last_sync": self.store.last_sync(),
            "storage": self.store.counts(),
            "db_path": str(self.settings.db_path),
        }
