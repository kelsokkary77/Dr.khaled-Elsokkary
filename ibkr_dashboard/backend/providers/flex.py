"""IBKR Flex Web Service provider.

The Flex Web Service is the simplest way to sync an IBKR account: it is
read-only, token-authenticated, and needs no software running locally. The
trade-off is that it serves *statement* data (refreshed roughly daily), not a
live tick.

Two-step protocol, both GET:

    1. ``{base}/SendRequest?t={token}&q={queryId}&v=3``
       -> XML with ``<Status>Success</Status>`` and a ``<ReferenceCode>``.
    2. ``{base}/GetStatement?t={token}&q={referenceCode}&v=3``
       -> the statement XML (or a ``Fail`` telling you to wait and retry).

Statements are generated asynchronously, so step 2 is polled.

Setup in Client Portal: Performance & Reports -> Flex Queries. Create an
*Activity* Flex Query with the sections listed in SECTIONS_NEEDED below, set
its format to XML, then Settings -> Flex Web Service to generate the token.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Iterable
from urllib.parse import urlencode

import httpx

from ..models import (
    AccountSummary,
    CashBalance,
    NavPoint,
    PortfolioSnapshot,
    Position,
    Trade,
)
from .base import BaseProvider, ProviderError

SECTIONS_NEEDED = (
    "Account Information",
    "Open Positions",
    "Cash Report",
    "Net Asset Value (NAV) in Base",
    "Trades",
)

# IBKR rejects requests without a real User-Agent.
_HEADERS = {"User-Agent": "ibkr-dashboard/1.0 (+python-httpx)"}

# Error codes that mean "not ready yet, poll again" rather than "give up".
_RETRYABLE_CODES = {"1019", "1021"}


class FlexProvider(BaseProvider):
    name = "flex"
    label = "IBKR Flex Web Service (token-based, read-only, no gateway needed)"

    def check(self) -> tuple[bool, str]:
        if not self.settings.flex_token:
            return False, "IBKR_FLEX_TOKEN is not set."
        if not self.settings.flex_query_ids:
            return False, "IBKR_FLEX_QUERY_IDS is not set."
        return True, "configured"

    # ------------------------------------------------------------------ public

    def fetch(self) -> PortfolioSnapshot:
        ok, reason = self.check()
        if not ok:
            raise ProviderError(
                f"Flex Web Service is not configured: {reason} "
                "See README.md > 'Connect via Flex Web Service'."
            )

        snapshot = PortfolioSnapshot(provider=self.name)
        with httpx.Client(timeout=60, headers=_HEADERS, follow_redirects=True) as client:
            for query_id in self.settings.flex_query_ids:
                xml_text = self._run_query(client, query_id)
                self._merge(snapshot, xml_text, query_id)

        if not snapshot.positions and not snapshot.nav_history:
            snapshot.warnings.append(
                "The Flex query returned no positions and no NAV rows. Check that the "
                f"query includes these sections: {', '.join(SECTIONS_NEEDED)}."
            )
        _finalize_summary(snapshot, self.settings.base_currency)
        return snapshot

    # ----------------------------------------------------------------- network

    def _run_query(self, client: httpx.Client, query_id: str) -> str:
        reference_code = self._send_request(client, query_id)
        return self._get_statement(client, reference_code, query_id)

    def _send_request(self, client: httpx.Client, query_id: str) -> str:
        url = f"{self.settings.flex_base_url}/SendRequest?" + urlencode(
            {
                "t": self.settings.flex_token,
                "q": query_id,
                "v": self.settings.flex_version,
            }
        )
        root = _parse(_get(client, url, f"SendRequest (query {query_id})"))
        status = _text(root, "Status")
        if status and status.lower() != "success":
            raise ProviderError(_describe_failure(root, f"query {query_id}"))
        reference_code = _text(root, "ReferenceCode")
        if not reference_code:
            raise ProviderError(
                f"Flex SendRequest for query {query_id} returned no ReferenceCode. "
                "Confirm the query ID is correct and the query format is XML."
            )
        return reference_code

    def _get_statement(
        self, client: httpx.Client, reference_code: str, query_id: str
    ) -> str:
        url = f"{self.settings.flex_base_url}/GetStatement?" + urlencode(
            {
                "t": self.settings.flex_token,
                "q": reference_code,
                "v": self.settings.flex_version,
            }
        )
        attempts = max(1, self.settings.flex_poll_attempts)
        last_reason = ""
        for attempt in range(attempts):
            body = _get(client, url, f"GetStatement (query {query_id})")
            root = _parse(body)
            # A ready statement is <FlexQueryResponse>; a not-ready one is a
            # <FlexStatementResponse> carrying Status=Fail.
            if root.tag == "FlexQueryResponse" or root.find(".//FlexStatement") is not None:
                return body
            code = _text(root, "ErrorCode")
            last_reason = _describe_failure(root, f"query {query_id}")
            if code not in _RETRYABLE_CODES:
                raise ProviderError(last_reason)
            if attempt < attempts - 1:
                time.sleep(max(1, self.settings.flex_poll_seconds))
        raise ProviderError(
            f"Flex statement for query {query_id} was still generating after "
            f"{attempts} attempts. {last_reason} Try raising IBKR_FLEX_POLL_ATTEMPTS."
        )

    # ------------------------------------------------------------------ parsing

    def _merge(self, snapshot: PortfolioSnapshot, xml_text: str, query_id: str) -> None:
        root = _parse(xml_text)
        statements = root.findall(".//FlexStatement") or [root]

        for statement in statements:
            info = statement.find(".//AccountInformation")
            if info is not None:
                snapshot.summary.account_id = (
                    _attr(info, "accountId") or snapshot.summary.account_id
                )
                snapshot.summary.account_alias = (
                    _attr(info, "acctAlias", "alias") or snapshot.summary.account_alias
                )
                snapshot.summary.account_type = (
                    _attr(info, "accountType") or snapshot.summary.account_type
                )
                snapshot.summary.base_currency = (
                    _attr(info, "currency") or snapshot.summary.base_currency
                )

            snapshot.positions.extend(_parse_positions(statement))
            snapshot.cash.extend(_parse_cash(statement))
            snapshot.trades.extend(_parse_trades(statement))
            snapshot.nav_history.extend(_parse_nav(statement))

        _dedupe(snapshot)
        if not statements or statements == [root]:
            snapshot.warnings.append(
                f"Flex query {query_id} returned no <FlexStatement> element."
            )


def _parse_positions(statement: ET.Element) -> list[Position]:
    out: list[Position] = []
    for node in statement.findall(".//OpenPosition"):
        quantity = _num(node, "position", "quantity")
        if not quantity:
            continue
        out.append(
            Position(
                symbol=_attr(node, "symbol"),
                description=_attr(node, "description"),
                asset_class=_attr(node, "assetCategory") or "STK",
                currency=_attr(node, "currency") or "USD",
                exchange=_attr(node, "listingExchange", "exchange"),
                sector=_attr(node, "subCategory") or "Unclassified",
                country=_attr(node, "issuerCountryCode", "countryCode"),
                conid=_attr(node, "conid"),
                quantity=quantity,
                multiplier=_num(node, "multiplier") or 1.0,
                mark_price=_num(node, "markPrice"),
                cost_basis_price=_num(node, "costBasisPrice", "openPrice"),
                market_value=_num(node, "positionValue", "marketValue"),
                cost_basis=_num(node, "costBasisMoney"),
                unrealized_pnl=_num(node, "fifoPnlUnrealized", "unrealizedPnl"),
                fx_rate_to_base=_num(node, "fxRateToBase") or 1.0,
            )
        )
    return out


def _parse_cash(statement: ET.Element) -> list[CashBalance]:
    out: list[CashBalance] = []
    for node in statement.findall(".//CashReportCurrency"):
        currency = _attr(node, "currency")
        # Flex emits a synthetic "BASE_SUMMARY" row -- that is a total, not a
        # currency, and adding it would double-count the cash.
        if not currency or currency.upper() == "BASE_SUMMARY":
            continue
        amount = _num(node, "endingCash", "endingSettledCash", "total")
        if not amount:
            continue
        out.append(
            CashBalance(
                currency=currency,
                amount=amount,
                amount_base=_num(node, "endingCashInBase") or amount,
            )
        )
    return out


def _parse_trades(statement: ET.Element) -> list[Trade]:
    out: list[Trade] = []
    for node in statement.findall(".//Trade"):
        symbol = _attr(node, "symbol")
        if not symbol:
            continue
        out.append(
            Trade(
                trade_date=_attr(node, "tradeDate", "dateTime", "settleDateTarget"),
                symbol=symbol,
                side=_attr(node, "buySell"),
                quantity=_num(node, "quantity"),
                price=_num(node, "tradePrice", "price"),
                proceeds=_num(node, "proceeds"),
                commission=_num(node, "ibCommission", "commission"),
                realized_pnl=_num(node, "fifoPnlRealized", "realizedPnl"),
                currency=_attr(node, "currency") or "USD",
                asset_class=_attr(node, "assetCategory") or "STK",
            )
        )
    out.sort(key=lambda t: t.trade_date, reverse=True)
    return out


def _parse_nav(statement: ET.Element) -> list[NavPoint]:
    out: list[NavPoint] = []
    for node in statement.findall(".//EquitySummaryByReportDateInBase"):
        total = _num(node, "total")
        if not total:
            continue
        out.append(
            NavPoint(
                as_of=_attr(node, "reportDate", "date"),
                nav=total,
                cash=_num(node, "cash", "cashLong"),
                securities=_num(node, "stock", "stockLong"),
            )
        )
    out.sort(key=lambda p: p.as_of)
    return out


def _dedupe(snapshot: PortfolioSnapshot) -> None:
    """Multiple Flex queries can overlap; keep one row per natural key."""
    seen_pos: dict[tuple[str, str], Position] = {}
    for pos in snapshot.positions:
        seen_pos[(pos.conid or pos.symbol, pos.currency)] = pos
    snapshot.positions = list(seen_pos.values())

    seen_cash: dict[str, CashBalance] = {c.currency: c for c in snapshot.cash}
    snapshot.cash = list(seen_cash.values())

    seen_nav: dict[str, NavPoint] = {n.as_of: n for n in snapshot.nav_history}
    snapshot.nav_history = sorted(seen_nav.values(), key=lambda n: n.as_of)

    seen_trade: dict[tuple, Trade] = {
        (t.trade_date, t.symbol, t.quantity, t.price): t for t in snapshot.trades
    }
    snapshot.trades = sorted(
        seen_trade.values(), key=lambda t: t.trade_date, reverse=True
    )


def _finalize_summary(snapshot: PortfolioSnapshot, base_currency: str) -> None:
    summary = snapshot.summary
    summary.base_currency = summary.base_currency or base_currency
    summary.securities_gross_value = sum(p.market_value for p in snapshot.positions)
    summary.total_cash = sum(c.amount_base for c in snapshot.cash)
    summary.unrealized_pnl = sum(p.unrealized_pnl for p in snapshot.positions)
    summary.realized_pnl = sum(t.realized_pnl for t in snapshot.trades)

    if snapshot.nav_history:
        summary.net_liquidation = snapshot.nav_history[-1].nav
        if len(snapshot.nav_history) > 1:
            previous = snapshot.nav_history[-2].nav
            summary.day_change = summary.net_liquidation - previous
            summary.day_change_pct = (
                summary.day_change / previous * 100.0 if previous else 0.0
            )
    else:
        summary.net_liquidation = (
            summary.securities_gross_value + summary.total_cash
        )


# --------------------------------------------------------------------- helpers


def _get(client: httpx.Client, url: str, what: str) -> str:
    try:
        response = client.get(url)
    except httpx.HTTPError as exc:
        raise ProviderError(
            f"Could not reach the IBKR Flex Web Service for {what}: {exc}"
        ) from exc
    if response.status_code != 200:
        raise ProviderError(
            f"IBKR Flex {what} returned HTTP {response.status_code}. "
            "A 403 usually means the token is wrong or has expired "
            "(Flex tokens expire one year after creation)."
        )
    return response.text


def _parse(xml_text: str) -> ET.Element:
    try:
        return ET.fromstring(xml_text.strip())
    except ET.ParseError as exc:
        preview = xml_text.strip()[:200]
        raise ProviderError(
            f"IBKR returned a response that is not valid XML: {exc}. Starts with: {preview!r}"
        ) from exc


def _describe_failure(root: ET.Element, what: str) -> str:
    code = _text(root, "ErrorCode") or "?"
    message = _text(root, "ErrorMessage") or "no message returned"
    return f"IBKR Flex rejected {what}: [{code}] {message}"


def _text(root: ET.Element, tag: str) -> str:
    node = root.find(f".//{tag}")
    if node is None or node.text is None:
        return ""
    return node.text.strip()


def _attr(node: ET.Element, *names: str) -> str:
    for name in names:
        value = node.get(name)
        if value is not None and str(value).strip() not in {"", "--"}:
            return str(value).strip()
    return ""


def _num(node: ET.Element, *names: str) -> float:
    raw = _attr(node, *names)
    if not raw:
        return 0.0
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return 0.0


def describe_setup() -> Iterable[str]:
    """Human-readable checklist shown by ``GET /api/providers``."""
    return (
        "In Client Portal open Performance & Reports > Flex Queries.",
        "Create an Activity Flex Query with format XML and these sections: "
        + ", ".join(SECTIONS_NEEDED)
        + ".",
        "Set the period to 'Last 365 Calendar Days' so the NAV chart has history.",
        "Open Settings > Flex Web Service and generate a token.",
        "Put the token in IBKR_FLEX_TOKEN and the query ID in IBKR_FLEX_QUERY_IDS.",
    )
