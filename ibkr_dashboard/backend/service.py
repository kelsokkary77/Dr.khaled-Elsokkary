"""Sync orchestration: provider -> store -> dashboard payload."""

from __future__ import annotations

import threading
from typing import Any

from . import analytics
from .config import Settings
from .models import PortfolioSnapshot
from .providers import ProviderError, get_provider
from .store import SnapshotStore


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
        payload["last_sync"] = self.store.last_sync()
        payload["storage"] = self.store.counts()
        return payload

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
