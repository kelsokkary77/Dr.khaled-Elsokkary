import pytest

from backend import analytics
from backend.models import (
    AccountSummary,
    CashBalance,
    NavPoint,
    PortfolioSnapshot,
    Position,
    Trade,
)


def make_snapshot() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        provider="test",
        summary=AccountSummary(account_id="U1", base_currency="USD"),
        positions=[
            Position(symbol="A", asset_class="STK", currency="USD", sector="Tech",
                     country="US", quantity=10, mark_price=60.0, cost_basis_price=40.0),
            Position(symbol="B", asset_class="ETF", currency="USD", sector="Broad",
                     country="IE", quantity=10, mark_price=30.0, cost_basis_price=35.0),
            Position(symbol="C", asset_class="STK", currency="EUR", sector="Tech",
                     country="NL", quantity=10, mark_price=10.0, cost_basis_price=8.0),
        ],
        cash=[CashBalance(currency="USD", amount=100.0, amount_base=100.0)],
        trades=[
            Trade(trade_date="2026-01-15", symbol="A", quantity=1, price=50.0,
                  realized_pnl=10.0, commission=-1.0),
            Trade(trade_date="2026-02-20", symbol="A", quantity=-1, price=60.0,
                  realized_pnl=-4.0, commission=-1.0),
            Trade(trade_date="2026-02-25", symbol="B", quantity=2, price=30.0,
                  realized_pnl=6.0, commission=-1.0),
        ],
    )


# ------------------------------------------------------------------ allocation


def test_allocation_weights_sum_to_one_hundred():
    alloc = analytics.allocation(make_snapshot())
    for dimension, rows in alloc.items():
        assert sum(r["weight_pct"] for r in rows) == pytest.approx(100.0, abs=0.01), dimension


def test_cash_appears_as_its_own_asset_class_slice():
    rows = analytics.allocation(make_snapshot())["by_asset_class"]
    cash = next(r for r in rows if r["key"] == "CASH_BALANCE")
    assert cash["value"] == 100.0
    assert cash["label"] == "Cash"


def test_asset_class_codes_get_readable_labels():
    rows = analytics.allocation(make_snapshot())["by_asset_class"]
    assert {"Stocks", "ETFs", "Cash"} <= {r["label"] for r in rows}


def test_currency_allocation_merges_positions_and_cash():
    rows = analytics.allocation(make_snapshot())["by_currency"]
    usd = next(r for r in rows if r["key"] == "USD")
    # 600 (A) + 300 (B) + 100 cash
    assert usd["value"] == pytest.approx(1000.0)


def test_allocation_rows_are_sorted_largest_first():
    rows = analytics.allocation(make_snapshot())["by_asset_class"]
    values = [abs(r["value"]) for r in rows]
    assert values == sorted(values, reverse=True)


def test_empty_portfolio_does_not_divide_by_zero():
    empty = PortfolioSnapshot(provider="test")
    assert analytics.allocation(empty)["by_asset_class"] == []
    assert analytics.concentration(empty)["hhi"] == 0.0
    assert analytics.build_dashboard(empty)["positions"] == []


# --------------------------------------------------------------- concentration


def test_concentration_of_an_equal_weight_book():
    positions = [
        Position(symbol=s, quantity=1, mark_price=100.0, cost_basis_price=100.0)
        for s in "ABCD"
    ]
    conc = analytics.concentration(PortfolioSnapshot(provider="t", positions=positions))
    assert conc["hhi"] == pytest.approx(2500.0)           # 4 x 25^2
    assert conc["effective_holdings"] == pytest.approx(4.0)
    assert conc["top1_pct"] == pytest.approx(25.0)


def test_concentration_top_slices_are_capped_at_the_book():
    conc = analytics.concentration(make_snapshot())
    assert conc["top5_pct"] == pytest.approx(100.0)
    assert conc["position_count"] == 3


# ----------------------------------------------------------------- NAV metrics


def test_nav_metrics_return_and_drawdown():
    points = [
        NavPoint("2026-01-01", 100.0),
        NavPoint("2026-01-02", 110.0),
        NavPoint("2026-01-03", 88.0),   # -20% from the 110 peak
        NavPoint("2026-01-04", 121.0),
    ]
    m = analytics.nav_metrics(points)
    assert m["total_return_pct"] == pytest.approx(21.0)
    assert m["max_drawdown_pct"] == pytest.approx(-20.0)
    assert m["max_drawdown_date"] == "2026-01-03"
    assert m["best_day_pct"] == pytest.approx(37.5)
    assert m["observations"] == 4


def test_nav_metrics_sorts_unordered_input():
    shuffled = [NavPoint("2026-01-03", 120.0), NavPoint("2026-01-01", 100.0)]
    assert analytics.nav_metrics(shuffled)["total_return_pct"] == pytest.approx(20.0)


def test_nav_metrics_with_one_point_reports_insufficient_history():
    m = analytics.nav_metrics([NavPoint("2026-01-01", 100.0)])
    assert m["total_return_pct"] == 0.0
    assert "Not enough history" in m["caveat"]


def test_nav_metrics_with_no_points_is_safe():
    assert analytics.nav_metrics([])["observations"] == 0


def test_nav_metrics_states_the_money_weighted_caveat():
    points = [NavPoint("2026-01-01", 100.0), NavPoint("2026-01-02", 110.0)]
    assert "money-weighted" in analytics.nav_metrics(points)["caveat"]


# -------------------------------------------------------------------- activity


def test_trade_activity_groups_by_month_oldest_first():
    rows = analytics.trade_activity(make_snapshot())
    assert [r["month"] for r in rows] == ["2026-01", "2026-02"]
    assert rows[1]["realized_pnl"] == pytest.approx(2.0)   # -4 + 6
    assert rows[1]["trades"] == 2


def test_ranked_positions_carry_weights_and_sort_by_size():
    rows = analytics.ranked_positions(make_snapshot())
    assert [r["symbol"] for r in rows] == ["A", "B", "C"]
    assert sum(r["weight_pct"] for r in rows) == pytest.approx(100.0, abs=0.01)


def test_winners_and_losers_are_split_by_sign():
    movers = analytics.winners_and_losers(make_snapshot())
    assert [w["symbol"] for w in movers["winners"]] == ["A", "C"]
    assert [l["symbol"] for l in movers["losers"]] == ["B"]


def test_build_dashboard_exposes_every_section_the_ui_reads():
    payload = analytics.build_dashboard(make_snapshot())
    assert {
        "summary", "positions", "cash", "trades", "allocation",
        "concentration", "movers", "nav", "activity", "warnings",
    } <= set(payload)
