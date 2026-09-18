import pytest

from backend.models import AccountSummary, NavPoint, PortfolioSnapshot, Position
from backend.store import SnapshotStore


def snapshot(nav: float = 1000.0, account: str = "U1") -> PortfolioSnapshot:
    return PortfolioSnapshot(
        provider="demo",
        summary=AccountSummary(account_id=account, net_liquidation=nav, total_cash=100.0),
        positions=[Position(symbol="A", quantity=1, mark_price=nav - 100)],
    )


def test_latest_snapshot_round_trips(store):
    store.save_snapshot(snapshot())
    loaded = store.latest_snapshot()
    assert loaded.summary.net_liquidation == 1000.0
    assert loaded.positions[0].symbol == "A"


def test_latest_snapshot_is_the_newest(store):
    store.save_snapshot(snapshot(nav=1000.0))
    store.save_snapshot(snapshot(nav=2000.0))
    assert store.latest_snapshot().summary.net_liquidation == 2000.0


def test_empty_store_returns_none(store):
    assert store.latest_snapshot() is None
    assert store.last_sync() is None
    assert store.nav_series() == []


def test_a_live_snapshot_seeds_one_nav_row(store):
    """cpapi has no history of its own, so saving must record today's value."""
    store.save_snapshot(snapshot())
    assert len(store.nav_series(account_id="U1")) == 1


def test_nav_rows_upsert_on_the_same_date(store):
    store.record_nav([NavPoint("2026-01-01", 100.0)], account_id="U1")
    store.record_nav([NavPoint("2026-01-01", 250.0)], account_id="U1")
    series = store.nav_series(account_id="U1")
    assert len(series) == 1 and series[0].nav == 250.0


def test_nav_series_is_ordered_by_date(store):
    store.record_nav(
        [NavPoint("2026-03-01", 3.0), NavPoint("2026-01-01", 1.0), NavPoint("2026-02-01", 2.0)],
        account_id="U1",
    )
    assert [p.as_of for p in store.nav_series("U1")] == [
        "2026-01-01", "2026-02-01", "2026-03-01",
    ]


def test_nav_rows_are_scoped_per_account(store):
    store.record_nav([NavPoint("2026-01-01", 10.0)], account_id="U1")
    store.record_nav([NavPoint("2026-01-01", 20.0)], account_id="U2")
    assert len(store.nav_series("U1")) == 1
    assert len(store.nav_series()) == 2


def test_zero_nav_rows_are_not_recorded(store):
    assert store.record_nav([NavPoint("2026-01-01", 0.0)], account_id="U1") == 0


def test_prune_keeps_recent_snapshots_but_never_nav_history(store):
    for i in range(6):
        store.save_snapshot(snapshot(nav=1000.0 + i))
    store.prune(keep=2)
    assert store.counts()["snapshots"] == 2
    assert store.counts()["nav_points"] >= 1
    assert store.latest_snapshot().summary.net_liquidation == 1005.0


def test_sync_log_records_success_and_failure(store):
    store.log_sync("flex", ok=False, message="token expired")
    last = store.last_sync()
    assert last["ok"] == 0 and "token expired" in last["message"]
    store.log_sync("demo", ok=True, message="fine")
    assert store.last_sync()["ok"] == 1


def test_schema_is_created_on_a_fresh_path(tmp_path):
    nested = tmp_path / "deep" / "dir" / "ibkr.sqlite3"
    assert SnapshotStore(nested).counts() == {"snapshots": 0, "nav_points": 0}
    assert nested.exists()
