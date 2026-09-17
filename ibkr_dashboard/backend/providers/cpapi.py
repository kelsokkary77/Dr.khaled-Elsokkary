"""IBKR Client Portal Web API provider (live data via the local gateway).

Unlike Flex, this reads *live* positions and balances. The cost is that IBKR's
Client Portal Gateway -- a small Java process -- has to be running and
authenticated on this machine:

    1. Download the gateway from IBKR and run ``bin/run.sh root/conf.yaml``.
    2. Open https://localhost:5000 and log in with your IBKR credentials.
    3. The session stays alive as long as something calls ``/tickle``
       periodically; this provider does that on every sync.

Endpoints used (all under ``{base}``, default ``https://localhost:5000/v1/api``):

    POST /tickle                                  keep the session alive
    POST /iserver/auth/status                     is the session authenticated?
    GET  /portfolio/accounts                      list accounts (must be called first)
    GET  /portfolio/{accountId}/summary           balances, NAV, buying power
    GET  /portfolio/{accountId}/ledger            cash by currency
    GET  /portfolio/{accountId}/positions/{page}  positions, 30 per page

The gateway serves a self-signed certificate, so TLS verification is disabled
for loopback addresses only (see ``Settings.effective_verify_ssl``).
"""

from __future__ import annotations

from typing import Any

import httpx

from ..models import (
    AccountSummary,
    CashBalance,
    NavPoint,
    PortfolioSnapshot,
    Position,
    utcnow_iso,
)
from .base import BaseProvider, ProviderError

_MAX_POSITION_PAGES = 40  # 30 positions per page -> 1200 positions
_HEADERS = {"User-Agent": "ibkr-dashboard/1.0", "Accept": "application/json"}


class CpApiProvider(BaseProvider):
    name = "cpapi"
    label = "IBKR Client Portal Web API (live data, needs the local gateway running)"

    def check(self) -> tuple[bool, str]:
        try:
            with self._client() as client:
                status = self._post(client, "/iserver/auth/status", required=False)
        except ProviderError as exc:
            return False, str(exc)
        if not isinstance(status, dict):
            return False, "The gateway returned an unexpected auth status payload."
        if not status.get("authenticated"):
            return False, (
                "The Client Portal Gateway is running but not authenticated. "
                f"Open {self._gateway_root()} in a browser and log in."
            )
        if status.get("competing"):
            return False, (
                "Another session is competing for this IBKR login. "
                "Log out of other Client Portal / TWS sessions and retry."
            )
        return True, "authenticated"

    # ------------------------------------------------------------------ public

    def fetch(self) -> PortfolioSnapshot:
        snapshot = PortfolioSnapshot(provider=self.name)

        with self._client() as client:
            self._post(client, "/tickle", required=False)

            status = self._post(client, "/iserver/auth/status", required=False)
            if isinstance(status, dict) and not status.get("authenticated"):
                raise ProviderError(
                    "The Client Portal Gateway is not authenticated. Open "
                    f"{self._gateway_root()} in a browser, log in, then sync again."
                )

            account_id = self._resolve_account(client, snapshot)
            self._load_summary(client, account_id, snapshot)
            self._load_ledger(client, account_id, snapshot)
            self._load_positions(client, account_id, snapshot)

        _finalize_summary(snapshot, self.settings.base_currency)
        return snapshot

    # ----------------------------------------------------------------- loaders

    def _resolve_account(
        self, client: httpx.Client, snapshot: PortfolioSnapshot
    ) -> str:
        # IBKR requires /portfolio/accounts before any other portfolio call.
        accounts = self._get(client, "/portfolio/accounts")
        if not isinstance(accounts, list) or not accounts:
            raise ProviderError(
                "The gateway returned no accounts. Confirm you are logged in at "
                f"{self._gateway_root()}."
            )

        configured = self.settings.cpapi_account_id
        chosen: dict[str, Any] | None = None
        if configured:
            chosen = next(
                (a for a in accounts if str(a.get("accountId")) == configured), None
            )
            if chosen is None:
                available = ", ".join(str(a.get("accountId")) for a in accounts)
                raise ProviderError(
                    f"IBKR_CPAPI_ACCOUNT_ID={configured} was not found. "
                    f"Available accounts: {available}"
                )
        else:
            chosen = accounts[0]
            if len(accounts) > 1:
                snapshot.warnings.append(
                    f"{len(accounts)} accounts found; showing "
                    f"{chosen.get('accountId')}. Set IBKR_CPAPI_ACCOUNT_ID to pick "
                    "a different one."
                )

        snapshot.summary.account_id = str(chosen.get("accountId", ""))
        snapshot.summary.account_alias = str(
            chosen.get("displayName") or chosen.get("accountAlias") or ""
        )
        snapshot.summary.account_type = str(chosen.get("type") or "")
        snapshot.summary.base_currency = str(
            chosen.get("currency") or self.settings.base_currency
        )
        return snapshot.summary.account_id

    def _load_summary(
        self, client: httpx.Client, account_id: str, snapshot: PortfolioSnapshot
    ) -> None:
        data = self._get(
            client, f"/portfolio/{account_id}/summary", required=False
        )
        if not isinstance(data, dict):
            snapshot.warnings.append("Account summary was unavailable from the gateway.")
            return

        summary = snapshot.summary
        summary.net_liquidation = _value(data, "netliquidation", "netliquidationvalue")
        summary.total_cash = _value(data, "totalcashvalue", "availablefunds")
        summary.securities_gross_value = _value(
            data, "grosspositionvalue", "stockmarketvalue"
        )
        summary.buying_power = _value(data, "buyingpower")
        summary.excess_liquidity = _value(data, "excessliquidity")
        summary.unrealized_pnl = _value(data, "unrealizedpnl")
        summary.realized_pnl = _value(data, "realizedpnl")

    def _load_ledger(
        self, client: httpx.Client, account_id: str, snapshot: PortfolioSnapshot
    ) -> None:
        data = self._get(client, f"/portfolio/{account_id}/ledger", required=False)
        if not isinstance(data, dict):
            snapshot.warnings.append("Cash ledger was unavailable from the gateway.")
            return

        for key, entry in data.items():
            if not isinstance(entry, dict):
                continue
            # The ledger includes a "BASE" roll-up row alongside real currencies.
            currency = str(entry.get("currency") or key).upper()
            if currency == "BASE":
                continue
            amount = _num(entry.get("cashbalance"))
            if not amount:
                continue
            fx = _num(entry.get("exchangerate")) or 1.0
            snapshot.cash.append(
                CashBalance(
                    currency=currency,
                    amount=amount,
                    amount_base=_num(entry.get("cashbalancefxsegment")) or amount * fx,
                )
            )

    def _load_positions(
        self, client: httpx.Client, account_id: str, snapshot: PortfolioSnapshot
    ) -> None:
        seen: set[str] = set()
        for page in range(_MAX_POSITION_PAGES):
            rows = self._get(
                client, f"/portfolio/{account_id}/positions/{page}", required=False
            )
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                if not isinstance(row, dict):
                    continue
                quantity = _num(row.get("position"))
                if not quantity:
                    continue
                conid = str(row.get("conid") or "")
                key = conid or str(row.get("contractDesc") or "")
                if key in seen:
                    continue
                seen.add(key)
                snapshot.positions.append(_position_from_row(row))
            if len(rows) < 30:
                break
        else:
            snapshot.warnings.append(
                f"Stopped after {_MAX_POSITION_PAGES} position pages."
            )

    # ------------------------------------------------------------------- http

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.settings.cpapi_base_url,
            timeout=self.settings.cpapi_timeout_seconds,
            verify=self.settings.effective_verify_ssl,
            headers=_HEADERS,
            follow_redirects=True,
        )

    def _gateway_root(self) -> str:
        return self.settings.cpapi_base_url.split("/v1/api")[0]

    def _get(self, client: httpx.Client, path: str, required: bool = True) -> Any:
        return self._request(client, "GET", path, required)

    def _post(self, client: httpx.Client, path: str, required: bool = True) -> Any:
        return self._request(client, "POST", path, required)

    def _request(
        self, client: httpx.Client, method: str, path: str, required: bool
    ) -> Any:
        try:
            response = client.request(method, path)
        except httpx.HTTPError as exc:
            message = (
                f"Could not reach the Client Portal Gateway at "
                f"{self.settings.cpapi_base_url} ({exc}). Start it with "
                "`bin/run.sh root/conf.yaml` and log in at "
                f"{self._gateway_root()}."
            )
            if required:
                raise ProviderError(message) from exc
            return None

        if response.status_code == 401:
            raise ProviderError(
                "The gateway rejected the request as unauthenticated (HTTP 401). "
                f"Log in again at {self._gateway_root()}."
            )
        if response.status_code >= 400:
            if required:
                raise ProviderError(
                    f"Gateway returned HTTP {response.status_code} for {path}: "
                    f"{response.text[:300]}"
                )
            return None
        try:
            return response.json()
        except ValueError:
            if required:
                raise ProviderError(
                    f"Gateway returned non-JSON for {path}: {response.text[:200]!r}"
                )
            return None


# --------------------------------------------------------------------- parsing


def _position_from_row(row: dict[str, Any]) -> Position:
    quantity = _num(row.get("position"))
    market_value = _num(row.get("mktValue"))
    avg_cost = _num(row.get("avgCost"))
    multiplier = _num(row.get("multiplier")) or 1.0
    return Position(
        symbol=str(row.get("ticker") or row.get("contractDesc") or "?"),
        description=str(row.get("name") or row.get("contractDesc") or ""),
        asset_class=str(row.get("assetClass") or "STK"),
        currency=str(row.get("currency") or "USD"),
        exchange=str(row.get("listingExchange") or ""),
        sector=str(row.get("sector") or row.get("group") or "Unclassified"),
        country=str(row.get("countryCode") or ""),
        conid=str(row.get("conid") or ""),
        quantity=quantity,
        multiplier=multiplier,
        mark_price=_num(row.get("mktPrice")),
        cost_basis_price=avg_cost / multiplier if multiplier else avg_cost,
        market_value=market_value,
        cost_basis=quantity * avg_cost,
        unrealized_pnl=_num(row.get("unrealizedPnl")),
        realized_pnl=_num(row.get("realizedPnl")),
    )


def _finalize_summary(snapshot: PortfolioSnapshot, base_currency: str) -> None:
    summary = snapshot.summary
    summary.base_currency = summary.base_currency or base_currency

    if not summary.securities_gross_value:
        summary.securities_gross_value = sum(p.market_value for p in snapshot.positions)
    if not summary.total_cash:
        summary.total_cash = sum(c.amount_base for c in snapshot.cash)
    if not summary.unrealized_pnl:
        summary.unrealized_pnl = sum(p.unrealized_pnl for p in snapshot.positions)
    if not summary.net_liquidation:
        summary.net_liquidation = summary.securities_gross_value + summary.total_cash

    # A live pull is a point in time; the SQLite store turns repeated pulls
    # into the NAV series the chart draws.
    if summary.net_liquidation:
        snapshot.nav_history = [
            NavPoint(
                as_of=utcnow_iso(),
                nav=summary.net_liquidation,
                cash=summary.total_cash,
                securities=summary.securities_gross_value,
            )
        ]


def _num(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if value is None:
        return 0.0
    text = str(value).strip().replace(",", "").replace("$", "")
    if not text or text in {"--", "N/A"}:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def _value(data: dict[str, Any], *keys: str) -> float:
    """Read one metric out of the summary payload.

    The gateway returns ``{"netliquidation": {"amount": 123.0, "currency": "USD"}}``
    but older builds return a bare number, so handle both.
    """
    lowered = {str(k).lower(): v for k, v in data.items()}
    for key in keys:
        entry = lowered.get(key.lower())
        if entry is None:
            continue
        if isinstance(entry, dict):
            amount = _num(entry.get("amount"))
            if amount:
                return amount
            continue
        amount = _num(entry)
        if amount:
            return amount
    return 0.0
