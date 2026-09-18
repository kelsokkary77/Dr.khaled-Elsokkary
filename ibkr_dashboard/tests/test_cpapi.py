"""Client Portal payload parsing and the TLS-verification guard."""

import pytest

from backend.config import Settings
from backend.models import PortfolioSnapshot
from backend.providers.cpapi import (
    CpApiProvider,
    _finalize_summary,
    _num,
    _position_from_row,
    _value,
)

POSITION_ROW = {
    "conid": 265598, "ticker": "AAPL", "name": "APPLE INC", "assetClass": "STK",
    "currency": "USD", "position": 30, "mktPrice": 250.0, "mktValue": 7500.0,
    "avgCost": 180.0, "unrealizedPnl": 2100.0, "multiplier": 1, "sector": "Technology",
}


def test_position_row_is_normalized():
    p = _position_from_row(POSITION_ROW)
    assert (p.symbol, p.market_value, p.cost_basis, p.unrealized_pnl) == (
        "AAPL", 7500.0, 5400.0, 2100.0,
    )
    assert p.sector == "Technology"


def test_avg_cost_is_divided_by_the_multiplier():
    """IBKR reports avgCost per contract, but cost_basis_price is per unit."""
    row = {**POSITION_ROW, "multiplier": 100, "avgCost": 18_000.0}
    assert _position_from_row(row).cost_basis_price == 180.0


def test_summary_value_reads_both_payload_shapes():
    assert _value({"netliquidation": {"amount": 123.45}}, "netliquidation") == 123.45
    assert _value({"NetLiquidation": 99.0}, "netliquidation") == 99.0
    assert _value({}, "netliquidation") == 0.0


def test_summary_value_falls_through_to_the_next_key():
    data = {"netliquidation": {"amount": 0.0}, "netliquidationvalue": {"amount": 7.0}}
    assert _value(data, "netliquidation", "netliquidationvalue") == 7.0


@pytest.mark.parametrize(
    "raw,expected",
    [(1, 1.0), ("1,234.5", 1234.5), ("$42", 42.0), ("--", 0.0), (None, 0.0), ("", 0.0)],
)
def test_number_parsing_is_tolerant(raw, expected):
    assert _num(raw) == expected


def test_finalize_backfills_totals_and_seeds_one_nav_point():
    snapshot = PortfolioSnapshot(provider="cpapi")
    snapshot.positions.append(_position_from_row(POSITION_ROW))
    _finalize_summary(snapshot, "USD")
    assert snapshot.summary.securities_gross_value == 7500.0
    assert snapshot.summary.net_liquidation == 7500.0
    # A live pull is a point in time; the store turns repeats into a series.
    assert len(snapshot.nav_history) == 1


def test_tls_verification_is_only_relaxed_for_loopback():
    loopback = Settings(cpapi_base_url="https://localhost:5000/v1/api", cpapi_verify_ssl=False)
    assert loopback.effective_verify_ssl is False

    remote = Settings(cpapi_base_url="https://gateway.example.com/v1/api", cpapi_verify_ssl=False)
    assert remote.effective_verify_ssl is True, "must never skip TLS checks off-box"


def test_gateway_root_is_derived_from_the_api_base():
    provider = CpApiProvider(Settings(cpapi_base_url="https://localhost:5000/v1/api"))
    assert provider._gateway_root() == "https://localhost:5000"
