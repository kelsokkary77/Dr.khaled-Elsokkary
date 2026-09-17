"""SQLite-backed snapshot cache.

Two jobs:

1. Serve the dashboard instantly from the last sync instead of re-hitting IBKR
   on every page load (the Flex service is rate-limited, and the Client Portal
   gateway throttles ``/portfolio/accounts`` to 1 request / 5s).
2. Accumulate a NAV time series. Flex "Activity" queries give you history for
   free, but a live Client Portal pull is a point-in-time reading -- storing
   one row per day is what turns it into a chart.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Iterator

from .models import NavPoint, PortfolioSnapshot, utcnow_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT    NOT NULL,
    account_id  TEXT    NOT NULL DEFAULT '',
    fetched_at  TEXT    NOT NULL,
    payload     TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_fetched
    ON snapshots (fetched_at DESC);

CREATE TABLE IF NOT EXISTS nav_history (
    account_id  TEXT    NOT NULL DEFAULT '',
    as_of       TEXT    NOT NULL,
    nav         REAL    NOT NULL,
    cash        REAL    NOT NULL DEFAULT 0,
    securities  REAL    NOT NULL DEFAULT 0,
    source      TEXT    NOT NULL DEFAULT '',
    PRIMARY KEY (account_id, as_of)
);

CREATE TABLE IF NOT EXISTS sync_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at  TEXT    NOT NULL,
    provider    TEXT    NOT NULL,
    ok          INTEGER NOT NULL,
    message     TEXT    NOT NULL DEFAULT ''
);
"""


class SnapshotStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=15)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------ writes

    def save_snapshot(self, snapshot: PortfolioSnapshot) -> int:
        payload = json.dumps(snapshot.to_dict(), separators=(",", ":"))
        account_id = snapshot.summary.account_id or ""
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO snapshots (provider, account_id, fetched_at, payload)"
                " VALUES (?, ?, ?, ?)",
                (snapshot.provider, account_id, snapshot.fetched_at, payload),
            )
            snapshot_id = int(cur.lastrowid or 0)

        points = list(snapshot.nav_history)
        if not points and snapshot.summary.net_liquidation:
            # A live provider has no history of its own -- record today's value.
            points = [
                NavPoint(
                    as_of=snapshot.fetched_at,
                    nav=snapshot.summary.net_liquidation,
                    cash=snapshot.summary.total_cash,
                    securities=snapshot.summary.securities_gross_value,
                )
            ]
        self.record_nav(points, account_id=account_id, source=snapshot.provider)
        return snapshot_id

    def record_nav(
        self, points: list[NavPoint], account_id: str = "", source: str = ""
    ) -> int:
        if not points:
            return 0
        rows = [
            (account_id, p.as_of, p.nav, p.cash, p.securities, source)
            for p in points
            if p.nav
        ]
        if not rows:
            return 0
        with self._connect() as conn:
            conn.executemany(
                "INSERT INTO nav_history (account_id, as_of, nav, cash, securities, source)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(account_id, as_of) DO UPDATE SET"
                "   nav=excluded.nav, cash=excluded.cash,"
                "   securities=excluded.securities, source=excluded.source",
                rows,
            )
        return len(rows)

    def log_sync(self, provider: str, ok: bool, message: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sync_log (started_at, provider, ok, message)"
                " VALUES (?, ?, ?, ?)",
                (utcnow_iso(), provider, 1 if ok else 0, message[:2000]),
            )

    def prune(self, keep: int = 200) -> int:
        """Keep only the most recent ``keep`` snapshots; NAV history is kept."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM snapshots WHERE id NOT IN"
                " (SELECT id FROM snapshots ORDER BY id DESC LIMIT ?)",
                (keep,),
            )
            return cur.rowcount or 0

    # ------------------------------------------------------------------- reads

    def latest_snapshot(self) -> PortfolioSnapshot | None:
        with self._connect() as conn, closing(
            conn.execute(
                "SELECT payload FROM snapshots ORDER BY id DESC LIMIT 1"
            )
        ) as cur:
            row = cur.fetchone()
        if not row:
            return None
        return PortfolioSnapshot.from_dict(json.loads(row["payload"]))

    def nav_series(self, account_id: str | None = None) -> list[NavPoint]:
        sql = "SELECT as_of, nav, cash, securities FROM nav_history"
        params: tuple[Any, ...] = ()
        if account_id is not None:
            sql += " WHERE account_id = ?"
            params = (account_id,)
        sql += " ORDER BY as_of ASC"
        with self._connect() as conn, closing(conn.execute(sql, params)) as cur:
            return [
                NavPoint(
                    as_of=r["as_of"],
                    nav=r["nav"],
                    cash=r["cash"],
                    securities=r["securities"],
                )
                for r in cur.fetchall()
            ]

    def last_sync(self) -> dict[str, Any] | None:
        with self._connect() as conn, closing(
            conn.execute(
                "SELECT started_at, provider, ok, message FROM sync_log"
                " ORDER BY id DESC LIMIT 1"
            )
        ) as cur:
            row = cur.fetchone()
        return dict(row) if row else None

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                "snapshots": conn.execute(
                    "SELECT COUNT(*) FROM snapshots"
                ).fetchone()[0],
                "nav_points": conn.execute(
                    "SELECT COUNT(*) FROM nav_history"
                ).fetchone()[0],
            }
