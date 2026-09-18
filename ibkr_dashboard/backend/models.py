"""Normalized portfolio types.

Every provider (demo / Flex / Client Portal) converts its own wire format into
these shapes, so the analytics and the UI never have to care where the data
came from.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from typing import Any


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _f(value: Any, default: float = 0.0) -> float:
    """Tolerant float parse -- IBKR emits '', '--' and comma'd numbers."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "")
    if text in {"", "-", "--", "N/A", "n/a"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _s(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


@dataclass
class Position:
    """One open position, valued in the account's base currency."""

    symbol: str
    description: str = ""
    asset_class: str = "STK"
    currency: str = "USD"
    exchange: str = ""
    sector: str = "Unclassified"
    country: str = ""
    conid: str = ""
    quantity: float = 0.0
    multiplier: float = 1.0
    mark_price: float = 0.0
    cost_basis_price: float = 0.0
    market_value: float = 0.0
    cost_basis: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    fx_rate_to_base: float = 1.0

    def __post_init__(self) -> None:
        self.quantity = _f(self.quantity)
        self.multiplier = _f(self.multiplier, 1.0) or 1.0
        self.mark_price = _f(self.mark_price)
        self.cost_basis_price = _f(self.cost_basis_price)
        self.fx_rate_to_base = _f(self.fx_rate_to_base, 1.0) or 1.0
        self.market_value = _f(self.market_value)
        self.cost_basis = _f(self.cost_basis)

        # Fill in whatever the source left blank.
        if not self.market_value:
            self.market_value = (
                self.quantity * self.mark_price * self.multiplier * self.fx_rate_to_base
            )
        if not self.cost_basis:
            self.cost_basis = (
                self.quantity
                * self.cost_basis_price
                * self.multiplier
                * self.fx_rate_to_base
            )
        self.unrealized_pnl = _f(self.unrealized_pnl) or (
            self.market_value - self.cost_basis
        )
        self.realized_pnl = _f(self.realized_pnl)
        self.symbol = _s(self.symbol, "?")
        self.asset_class = _s(self.asset_class, "STK").upper()
        self.currency = _s(self.currency, "USD").upper()
        self.sector = _s(self.sector, "Unclassified")

    @property
    def unrealized_pnl_pct(self) -> float:
        if not self.cost_basis:
            return 0.0
        return self.unrealized_pnl / abs(self.cost_basis) * 100.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["unrealized_pnl_pct"] = round(self.unrealized_pnl_pct, 4)
        return data


@dataclass
class CashBalance:
    currency: str
    amount: float = 0.0
    amount_base: float = 0.0

    def __post_init__(self) -> None:
        self.currency = _s(self.currency, "USD").upper()
        self.amount = _f(self.amount)
        self.amount_base = _f(self.amount_base) or self.amount

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Trade:
    trade_date: str
    symbol: str
    side: str = ""
    quantity: float = 0.0
    price: float = 0.0
    proceeds: float = 0.0
    commission: float = 0.0
    realized_pnl: float = 0.0
    currency: str = "USD"
    asset_class: str = "STK"

    def __post_init__(self) -> None:
        self.quantity = _f(self.quantity)
        self.price = _f(self.price)
        self.proceeds = _f(self.proceeds)
        self.commission = _f(self.commission)
        self.realized_pnl = _f(self.realized_pnl)
        self.currency = _s(self.currency, "USD").upper()
        self.side = _s(self.side) or ("BUY" if self.quantity >= 0 else "SELL")
        self.trade_date = normalize_date(self.trade_date)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class NavPoint:
    """One end-of-day net-asset-value observation."""

    as_of: str
    nav: float = 0.0
    cash: float = 0.0
    securities: float = 0.0

    def __post_init__(self) -> None:
        self.as_of = normalize_date(self.as_of)
        self.nav = _f(self.nav)
        self.cash = _f(self.cash)
        self.securities = _f(self.securities)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AccountSummary:
    account_id: str = ""
    account_alias: str = ""
    account_type: str = ""
    base_currency: str = "USD"
    net_liquidation: float = 0.0
    total_cash: float = 0.0
    securities_gross_value: float = 0.0
    unrealized_pnl: float = 0.0
    realized_pnl: float = 0.0
    buying_power: float = 0.0
    excess_liquidity: float = 0.0
    day_change: float = 0.0
    day_change_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PortfolioSnapshot:
    """Everything one sync pulled, in one object."""

    provider: str
    fetched_at: str = field(default_factory=utcnow_iso)
    summary: AccountSummary = field(default_factory=AccountSummary)
    positions: list[Position] = field(default_factory=list)
    cash: list[CashBalance] = field(default_factory=list)
    trades: list[Trade] = field(default_factory=list)
    nav_history: list[NavPoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "fetched_at": self.fetched_at,
            "summary": self.summary.to_dict(),
            "positions": [p.to_dict() for p in self.positions],
            "cash": [c.to_dict() for c in self.cash],
            "trades": [t.to_dict() for t in self.trades],
            "nav_history": [n.to_dict() for n in self.nav_history],
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PortfolioSnapshot":
        summary_fields = {f for f in AccountSummary.__dataclass_fields__}
        summary_data = {
            k: v for k, v in (data.get("summary") or {}).items() if k in summary_fields
        }
        pos_fields = set(Position.__dataclass_fields__)
        cash_fields = set(CashBalance.__dataclass_fields__)
        trade_fields = set(Trade.__dataclass_fields__)
        nav_fields = set(NavPoint.__dataclass_fields__)
        return cls(
            provider=data.get("provider", "unknown"),
            fetched_at=data.get("fetched_at", utcnow_iso()),
            summary=AccountSummary(**summary_data),
            positions=[
                Position(**{k: v for k, v in p.items() if k in pos_fields})
                for p in data.get("positions", [])
            ],
            cash=[
                CashBalance(**{k: v for k, v in c.items() if k in cash_fields})
                for c in data.get("cash", [])
            ],
            trades=[
                Trade(**{k: v for k, v in t.items() if k in trade_fields})
                for t in data.get("trades", [])
            ],
            nav_history=[
                NavPoint(**{k: v for k, v in n.items() if k in nav_fields})
                for n in data.get("nav_history", [])
            ],
            warnings=list(data.get("warnings", [])),
        )


def normalize_date(value: Any) -> str:
    """Coerce IBKR's assorted date spellings into ISO ``YYYY-MM-DD``."""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()

    text = _s(value)
    if not text:
        return date.today().isoformat()

    # Flex sometimes emits "20260917;093000" or "2026-09-17 09:30:00".
    text = text.split(";")[0].split(" ")[0].split("T")[0]
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%b-%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text
