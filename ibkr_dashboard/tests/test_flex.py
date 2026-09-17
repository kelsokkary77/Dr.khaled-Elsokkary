"""Flex Web Service parsing, driven by representative statement XML."""

import pytest

from backend.config import Settings
from backend.models import PortfolioSnapshot
from backend.providers import flex
from backend.providers.base import ProviderError

STATEMENT = """<FlexQueryResponse queryName="Dash" type="AF">
 <FlexStatements count="1">
  <FlexStatement accountId="U1234567" fromDate="2026-01-01" toDate="2026-09-16">
   <AccountInformation accountId="U1234567" acctAlias="Main" currency="USD"
                       accountType="INDIVIDUAL"/>
   <EquitySummaryInBase>
     <EquitySummaryByReportDateInBase reportDate="2026-09-15" cash="1000" stock="9000" total="10000"/>
     <EquitySummaryByReportDateInBase reportDate="2026-09-16" cash="1000" stock="9500" total="10500"/>
   </EquitySummaryInBase>
   <CashReport>
     <CashReportCurrency currency="BASE_SUMMARY" endingCash="1200"/>
     <CashReportCurrency currency="USD" endingCash="1000" endingCashInBase="1000"/>
     <CashReportCurrency currency="EUR" endingCash="184.5" endingCashInBase="200"/>
   </CashReport>
   <OpenPositions>
     <OpenPosition currency="USD" fxRateToBase="1" assetCategory="STK" symbol="AAPL"
       description="APPLE INC" conid="265598" listingExchange="NASDAQ" position="30"
       markPrice="250" positionValue="7500" costBasisPrice="180" costBasisMoney="5400"
       fifoPnlUnrealized="2100" multiplier="1" subCategory="COMMON" issuerCountryCode="US"/>
     <OpenPosition currency="EUR" fxRateToBase="1.08" assetCategory="STK" symbol="ASML"
       position="2" markPrice="700" costBasisPrice="600" multiplier="1"/>
     <OpenPosition currency="USD" assetCategory="STK" symbol="CLOSED" position="0" markPrice="5"/>
   </OpenPositions>
   <Trades>
     <Trade symbol="AAPL" tradeDate="20260910" buySell="BUY" quantity="10" tradePrice="240"
            proceeds="-2400" ibCommission="-1.0" fifoPnlRealized="0" currency="USD"
            assetCategory="STK"/>
     <Trade symbol="MSFT" tradeDate="2026-09-11" buySell="SELL" quantity="-5" tradePrice="500"
            proceeds="2500" ibCommission="-1.0" fifoPnlRealized="340" currency="USD"
            assetCategory="STK"/>
   </Trades>
  </FlexStatement>
 </FlexStatements>
</FlexQueryResponse>"""

FAILURE = """<FlexStatementResponse timestamp="17 September, 2026">
  <Status>Fail</Status><ErrorCode>1012</ErrorCode>
  <ErrorMessage>Token has expired.</ErrorMessage></FlexStatementResponse>"""

GENERATING = """<FlexStatementResponse timestamp="17 September, 2026">
  <Status>Fail</Status><ErrorCode>1019</ErrorCode>
  <ErrorMessage>Statement generation in progress.</ErrorMessage></FlexStatementResponse>"""


@pytest.fixture
def parsed() -> PortfolioSnapshot:
    snapshot = PortfolioSnapshot(provider="flex")
    flex.FlexProvider(Settings())._merge(snapshot, STATEMENT, "999")
    flex._finalize_summary(snapshot, "USD")
    return snapshot


def test_account_information(parsed):
    assert parsed.summary.account_id == "U1234567"
    assert parsed.summary.account_alias == "Main"
    assert parsed.summary.base_currency == "USD"


def test_zero_quantity_positions_are_dropped(parsed):
    assert [p.symbol for p in parsed.positions] == ["AAPL", "ASML"]


def test_non_base_position_is_converted_to_base_currency(parsed):
    asml = next(p for p in parsed.positions if p.symbol == "ASML")
    assert asml.market_value == pytest.approx(2 * 700 * 1.08)
    assert asml.unrealized_pnl == pytest.approx(2 * 100 * 1.08)


def test_base_summary_cash_row_is_excluded(parsed):
    """That row is a roll-up total; counting it would double the cash."""
    assert {c.currency for c in parsed.cash} == {"USD", "EUR"}
    assert parsed.summary.total_cash == pytest.approx(1200.0)


def test_nav_history_is_sorted_and_drives_day_change(parsed):
    assert [p.as_of for p in parsed.nav_history] == ["2026-09-15", "2026-09-16"]
    assert parsed.summary.net_liquidation == 10_500.0
    assert parsed.summary.day_change == pytest.approx(500.0)
    assert parsed.summary.day_change_pct == pytest.approx(5.0)


def test_trades_are_newest_first_with_normalized_dates(parsed):
    assert [t.trade_date for t in parsed.trades] == ["2026-09-11", "2026-09-10"]
    assert parsed.summary.realized_pnl == pytest.approx(340.0)


def test_merging_the_same_statement_twice_does_not_duplicate():
    snapshot = PortfolioSnapshot(provider="flex")
    provider = flex.FlexProvider(Settings())
    provider._merge(snapshot, STATEMENT, "999")
    provider._merge(snapshot, STATEMENT, "999")
    assert len(snapshot.positions) == 2
    assert len(snapshot.cash) == 2
    assert len(snapshot.nav_history) == 2
    assert len(snapshot.trades) == 2


def test_failure_response_is_described_for_a_human():
    message = flex._describe_failure(flex._parse(FAILURE), "query 1")
    assert "1012" in message and "Token has expired" in message


def test_generating_is_a_retryable_code():
    assert flex._text(flex._parse(GENERATING), "ErrorCode") in flex._RETRYABLE_CODES
    assert flex._text(flex._parse(FAILURE), "ErrorCode") not in flex._RETRYABLE_CODES


def test_non_xml_response_raises_a_readable_error():
    """A proxy or maintenance page must not surface as a parser traceback."""
    with pytest.raises(ProviderError, match="not valid XML"):
        flex._parse("<html><body>503 Service Unavailable<br></body></html>")


def test_fetch_without_credentials_explains_what_is_missing():
    provider = flex.FlexProvider(Settings(provider="flex"))
    ok, reason = provider.check()
    assert not ok and "IBKR_FLEX_TOKEN" in reason
    with pytest.raises(ProviderError, match="IBKR_FLEX_TOKEN"):
        provider.fetch()


def test_query_id_present_but_token_missing_is_still_rejected():
    provider = flex.FlexProvider(
        Settings(provider="flex", flex_token="", flex_query_ids=["123"])
    )
    assert provider.check()[0] is False
