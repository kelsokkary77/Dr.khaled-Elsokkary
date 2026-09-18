from backend.models import (
    AccountSummary,
    CashBalance,
    NavPoint,
    PortfolioSnapshot,
    Position,
    Trade,
    normalize_date,
)


def test_position_derives_values_when_source_omits_them():
    p = Position(symbol="AAPL", quantity=100, mark_price=250.0, cost_basis_price=180.0)
    assert p.market_value == 25_000.0
    assert p.cost_basis == 18_000.0
    assert p.unrealized_pnl == 7_000.0
    assert round(p.unrealized_pnl_pct, 2) == 38.89


def test_position_applies_fx_and_multiplier():
    p = Position(
        symbol="ASML", quantity=2, mark_price=700.0, cost_basis_price=600.0,
        currency="eur", fx_rate_to_base=1.08,
    )
    assert p.market_value == 2 * 700 * 1.08
    assert p.currency == "EUR"  # normalized to upper case


def test_position_keeps_values_the_source_supplied():
    p = Position(
        symbol="X", quantity=10, mark_price=5.0, cost_basis_price=4.0,
        market_value=999.0, cost_basis=500.0, unrealized_pnl=111.0,
    )
    assert (p.market_value, p.cost_basis, p.unrealized_pnl) == (999.0, 500.0, 111.0)


def test_position_zero_cost_basis_does_not_divide_by_zero():
    assert Position(symbol="FREE", quantity=1, mark_price=10.0).unrealized_pnl_pct == 0.0


def test_multiplier_of_zero_falls_back_to_one():
    assert Position(symbol="OPT", quantity=1, mark_price=2.0, multiplier=0).multiplier == 1.0


def test_normalize_date_handles_ibkr_spellings():
    assert normalize_date("20260917") == "2026-09-17"
    assert normalize_date("20260917;093000") == "2026-09-17"
    assert normalize_date("2026-09-17 09:30:00") == "2026-09-17"
    assert normalize_date("2026-09-17T09:30:00") == "2026-09-17"


def test_normalize_date_passes_through_unparseable_text():
    assert normalize_date("not-a-date") == "not-a-date"


def test_tolerant_number_parsing():
    p = Position(symbol="X", quantity="1,000", mark_price="12.5", cost_basis_price="--")
    assert p.quantity == 1000.0
    assert p.cost_basis_price == 0.0


def test_trade_infers_side_from_signed_quantity():
    assert Trade(trade_date="2026-01-02", symbol="A", quantity=-5).side == "SELL"
    assert Trade(trade_date="2026-01-02", symbol="A", quantity=5).side == "BUY"


def test_snapshot_round_trips_through_dict():
    snap = PortfolioSnapshot(
        provider="demo",
        summary=AccountSummary(account_id="U1", net_liquidation=1000.0),
        positions=[Position(symbol="A", quantity=1, mark_price=10.0)],
        cash=[CashBalance(currency="usd", amount=5.0)],
        trades=[Trade(trade_date="20260101", symbol="A", quantity=1, price=10.0)],
        nav_history=[NavPoint(as_of="2026-01-01", nav=1000.0)],
        warnings=["careful"],
    )
    restored = PortfolioSnapshot.from_dict(snap.to_dict())
    assert restored.summary.account_id == "U1"
    assert restored.positions[0].symbol == "A"
    assert restored.cash[0].currency == "USD"
    assert restored.trades[0].trade_date == "2026-01-01"
    assert restored.nav_history[0].nav == 1000.0
    assert restored.warnings == ["careful"]


def test_from_dict_ignores_unknown_keys():
    payload = PortfolioSnapshot(provider="demo").to_dict()
    payload["positions"] = [{"symbol": "A", "quantity": 1, "bogus_field": 42}]
    assert PortfolioSnapshot.from_dict(payload).positions[0].symbol == "A"
