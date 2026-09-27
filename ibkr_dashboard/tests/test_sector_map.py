"""The built-in ticker -> sector lookup table used as a fallback wherever the
broker itself doesn't supply a real sector (Flex, always; Client Portal, when
its own live sector field is blank)."""

from backend.sector_map import lookup_sector


def test_known_ticker_returns_its_sector():
    assert lookup_sector("AAPL") == "Technology"
    assert lookup_sector("XOM") == "Energy"


def test_unknown_ticker_is_unclassified():
    assert lookup_sector("ZZZZNOTATICKER") == "Unclassified"


def test_lookup_is_case_insensitive():
    assert lookup_sector("aapl") == "Technology"


def test_share_class_punctuation_is_normalized():
    """"BRK.B", "BRK-B" and "BRK B" are the same security under three
    different brokers' spellings -- all three must resolve to one entry."""
    assert lookup_sector("BRK B") == "Financials"
    assert lookup_sector("BRK.B") == "Financials"
    assert lookup_sector("BRK-B") == "Financials"


def test_broad_index_funds_are_diversified_not_a_single_sector():
    assert lookup_sector("SPY") == "Diversified"
    assert lookup_sector("CSPX") == "Diversified"


def test_sector_etfs_keep_their_sector():
    assert lookup_sector("XLK") == "Technology"
