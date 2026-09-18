"""Offline sample portfolio.

Exists so the dashboard is inspectable before any IBKR credentials are wired
up, and so the test-suite never touches the network. The numbers are
deterministic (seeded) but shaped like a real multi-currency IBKR account:
US-listed stocks, Irish-domiciled UCITS ETFs, a non-USD holding, and cash in
three currencies.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from ..models import (
    AccountSummary,
    CashBalance,
    NavPoint,
    PortfolioSnapshot,
    Position,
    Trade,
)
from .base import BaseProvider

# symbol, description, asset class, currency, sector, country, qty, mark, cost
_HOLDINGS = [
    ("AAPL", "APPLE INC", "STK", "USD", "Technology", "US", 180, 246.30, 171.42),
    ("MSFT", "MICROSOFT CORP", "STK", "USD", "Technology", "US", 95, 512.75, 388.10),
    ("NVDA", "NVIDIA CORP", "STK", "USD", "Technology", "US", 140, 184.20, 108.65),
    ("CSPX", "ISHARES CORE S&P 500 UCITS ETF", "ETF", "USD", "Broad Equity", "IE", 210, 648.90, 512.33),
    ("EIMI", "ISHARES CORE MSCI EM IMI UCITS", "ETF", "USD", "Broad Equity", "IE", 900, 38.44, 33.10),
    ("IWDA", "ISHARES CORE MSCI WORLD UCITS", "ETF", "USD", "Broad Equity", "IE", 320, 112.68, 92.75),
    ("UNH", "UNITEDHEALTH GROUP INC", "STK", "USD", "Healthcare", "US", 60, 336.10, 402.88),
    ("LLY", "ELI LILLY & CO", "STK", "USD", "Healthcare", "US", 35, 812.40, 645.20),
    ("ASML", "ASML HOLDING NV", "STK", "EUR", "Technology", "NL", 25, 742.60, 610.15),
    ("BRK B", "BERKSHIRE HATHAWAY INC-CL B", "STK", "USD", "Financials", "US", 70, 498.25, 412.90),
    ("XOM", "EXXON MOBIL CORP", "STK", "USD", "Energy", "US", 150, 119.85, 104.30),
    ("GLD", "SPDR GOLD SHARES", "ETF", "USD", "Commodities", "US", 80, 331.70, 248.55),
]

_FX_TO_USD = {"USD": 1.0, "EUR": 1.0842, "GBP": 1.2710, "SAR": 0.2666}

_CASH = [("USD", 48_320.55), ("EUR", 12_040.00), ("SAR", 31_500.00)]


class DemoProvider(BaseProvider):
    name = "demo"
    label = "Built-in sample portfolio (no IBKR connection, safe to explore)"

    def fetch(self) -> PortfolioSnapshot:
        positions = [
            Position(
                symbol=sym,
                description=desc,
                asset_class=asset_class,
                currency=ccy,
                sector=sector,
                country=country,
                exchange="NASDAQ" if ccy == "USD" else "AEB",
                conid=f"{abs(hash(sym)) % 900000 + 100000}",
                quantity=qty,
                mark_price=mark,
                cost_basis_price=cost,
                fx_rate_to_base=_FX_TO_USD.get(ccy, 1.0),
            )
            for sym, desc, asset_class, ccy, sector, country, qty, mark, cost in _HOLDINGS
        ]

        cash = [
            CashBalance(
                currency=ccy,
                amount=amount,
                amount_base=amount * _FX_TO_USD.get(ccy, 1.0),
            )
            for ccy, amount in _CASH
        ]

        securities = sum(p.market_value for p in positions)
        total_cash = sum(c.amount_base for c in cash)
        nav = securities + total_cash

        nav_history = _synthetic_nav(nav, days=180)
        prev_nav = nav_history[-2].nav if len(nav_history) > 1 else nav

        summary = AccountSummary(
            account_id="U0000000",
            account_alias="Demo portfolio",
            account_type="INDIVIDUAL",
            base_currency=self.settings.base_currency,
            net_liquidation=nav,
            total_cash=total_cash,
            securities_gross_value=securities,
            unrealized_pnl=sum(p.unrealized_pnl for p in positions),
            realized_pnl=18_430.12,
            buying_power=total_cash * 4,
            excess_liquidity=total_cash * 1.8,
            day_change=nav - prev_nav,
            day_change_pct=((nav - prev_nav) / prev_nav * 100.0) if prev_nav else 0.0,
        )

        return PortfolioSnapshot(
            provider=self.name,
            summary=summary,
            positions=positions,
            cash=cash,
            trades=_synthetic_trades(positions),
            nav_history=nav_history,
            warnings=[
                "Showing the built-in sample portfolio. "
                "Set IBKR_PROVIDER=flex or cpapi in .env to connect your real account."
            ],
        )


def _synthetic_nav(final_nav: float, days: int) -> list[NavPoint]:
    """Walk backwards from today's NAV with a seeded random walk."""
    rng = random.Random(20260917)
    values: list[float] = [final_nav]
    for _ in range(days - 1):
        # Walking backwards: dividing by (1 + drift) makes earlier values
        # smaller, so a positive drift yields a forward series that rises.
        drift = 0.0006
        shock = rng.gauss(0.0, 0.0085)
        values.append(values[-1] / (1.0 + drift + shock))
    values.reverse()

    today = date.today()
    points: list[NavPoint] = []
    cursor = today - timedelta(days=days - 1)
    idx = 0
    while cursor <= today and idx < len(values):
        if cursor.weekday() < 5:  # trading days only
            nav = round(values[idx], 2)
            points.append(
                NavPoint(
                    as_of=cursor.isoformat(),
                    nav=nav,
                    cash=round(nav * 0.09, 2),
                    securities=round(nav * 0.91, 2),
                )
            )
        cursor += timedelta(days=1)
        idx += 1
    return points


def _synthetic_trades(positions: list[Position]) -> list[Trade]:
    rng = random.Random(4894)
    trades: list[Trade] = []
    today = date.today()
    for i in range(24):
        pos = positions[rng.randrange(len(positions))]
        side = "BUY" if rng.random() < 0.62 else "SELL"
        qty = rng.randrange(5, 80)
        price = round(pos.mark_price * rng.uniform(0.88, 1.06), 2)
        signed_qty = qty if side == "BUY" else -qty
        trades.append(
            Trade(
                trade_date=(today - timedelta(days=i * 3 + rng.randrange(3))).isoformat(),
                symbol=pos.symbol,
                side=side,
                quantity=signed_qty,
                price=price,
                proceeds=round(-signed_qty * price, 2),
                commission=round(-max(1.0, qty * 0.005), 2),
                realized_pnl=round(rng.uniform(-900, 2400), 2) if side == "SELL" else 0.0,
                currency=pos.currency,
                asset_class=pos.asset_class,
            )
        )
    trades.sort(key=lambda t: t.trade_date, reverse=True)
    return trades
