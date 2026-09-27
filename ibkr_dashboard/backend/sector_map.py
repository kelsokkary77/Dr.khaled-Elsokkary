"""Built-in ticker -> sector lookup.

Neither the Flex Web Service nor the Client Portal's Flex export includes a
security's actual sector (Technology, Healthcare, ...) -- only an asset-type
classification (Common Stock, ETF, ADR, ...), which lands on
``Position.security_type`` instead. The Client Portal Web API's live
``/portfolio/{accountId}/positions`` endpoint *does* return a real sector, and
that value is used as-is when present (see ``providers/cpapi.py``); this table
is the fallback for everyone else -- Flex, and any cpapi row IBKR leaves
blank.

It is necessarily incomplete: a fixed table can't know every ticker that
exists. Anything missing renders as "Unclassified" rather than a guess. To add
one, add a line below -- key is the ticker as your broker prints it (this
module normalizes case, spaces, dots and dashes, so "BRK.B", "BRK-B" and
"BRK B" all match one entry).
"""

from __future__ import annotations

# Real, GICS-style sectors for individual stocks; a few practical buckets
# (Diversified, Commodities, Fixed Income) for funds that don't have one
# sector to call their own.
_RAW: dict[str, str] = {
    # --- Technology ---
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology",
    "AVGO": "Technology", "ORCL": "Technology", "CRM": "Technology",
    "ADBE": "Technology", "AMD": "Technology", "QCOM": "Technology",
    "TXN": "Technology", "INTC": "Technology", "IBM": "Technology",
    "NOW": "Technology", "INTU": "Technology", "AMAT": "Technology",
    "MU": "Technology", "PANW": "Technology", "SNPS": "Technology",
    "CDNS": "Technology", "ASML": "Technology", "SAP": "Technology",
    "CSCO": "Technology", "ACN": "Technology", "TSM": "Technology",
    "ARM": "Technology", "PLTR": "Technology", "SHOP": "Technology",
    "UBER": "Technology", "ADSK": "Technology", "FTNT": "Technology",
    "INFY": "Technology", "INFY.NS": "Technology", "WIT": "Technology",
    "STM": "Technology", "NXPI": "Technology", "MRVL": "Technology",
    "APH": "Technology", "KLAC": "Technology", "LRCX": "Technology",
    "ANET": "Technology", "DELL": "Technology", "HPQ": "Technology",
    "ERIC": "Technology", "NOK": "Technology",

    # --- Communication Services ---
    "GOOGL": "Communication Services", "GOOG": "Communication Services",
    "META": "Communication Services", "NFLX": "Communication Services",
    "DIS": "Communication Services", "CMCSA": "Communication Services",
    "TMUS": "Communication Services", "VZ": "Communication Services",
    "T": "Communication Services", "SPOT": "Communication Services",
    "WBD": "Communication Services", "EA": "Communication Services",
    "TTWO": "Communication Services", "SNAP": "Communication Services",
    "PINS": "Communication Services", "MTCH": "Communication Services",
    "BABA": "Communication Services", "BIDU": "Communication Services",
    "TCEHY": "Communication Services",

    # --- Healthcare ---
    "UNH": "Healthcare", "LLY": "Healthcare", "JNJ": "Healthcare",
    "ABBV": "Healthcare", "MRK": "Healthcare", "TMO": "Healthcare",
    "ABT": "Healthcare", "PFE": "Healthcare", "DHR": "Healthcare",
    "AMGN": "Healthcare", "ISRG": "Healthcare", "BMY": "Healthcare",
    "VRTX": "Healthcare", "GILD": "Healthcare", "MDT": "Healthcare",
    "CVS": "Healthcare", "CI": "Healthcare", "ELV": "Healthcare",
    "REGN": "Healthcare", "ZTS": "Healthcare", "BSX": "Healthcare",
    "SYK": "Healthcare", "HCA": "Healthcare", "NVO": "Healthcare",
    "AZN": "Healthcare", "GSK": "Healthcare", "SNY": "Healthcare",
    "NVS": "Healthcare", "MRNA": "Healthcare", "IDXX": "Healthcare",

    # --- Financials ---
    "BRKB": "Financials", "JPM": "Financials", "V": "Financials",
    "MA": "Financials", "BAC": "Financials", "WFC": "Financials",
    "GS": "Financials", "MS": "Financials", "SPGI": "Financials",
    "AXP": "Financials", "BLK": "Financials", "C": "Financials",
    "SCHW": "Financials", "CB": "Financials", "PGR": "Financials",
    "MMC": "Financials", "PYPL": "Financials", "ICE": "Financials",
    "CME": "Financials", "AON": "Financials", "USB": "Financials",
    "PNC": "Financials", "TFC": "Financials", "COF": "Financials",
    "AIG": "Financials", "MET": "Financials", "PRU": "Financials",
    "HSBC": "Financials", "UBS": "Financials", "TD": "Financials",
    "RY": "Financials", "ADYEY": "Financials",

    # --- Consumer Discretionary ---
    "AMZN": "Consumer Discretionary", "TSLA": "Consumer Discretionary",
    "HD": "Consumer Discretionary", "MCD": "Consumer Discretionary",
    "NKE": "Consumer Discretionary", "LOW": "Consumer Discretionary",
    "SBUX": "Consumer Discretionary", "BKNG": "Consumer Discretionary",
    "TJX": "Consumer Discretionary", "MAR": "Consumer Discretionary",
    "GM": "Consumer Discretionary", "F": "Consumer Discretionary",
    "RCL": "Consumer Discretionary", "CCL": "Consumer Discretionary",
    "ABNB": "Consumer Discretionary", "EBAY": "Consumer Discretionary",
    "ETSY": "Consumer Discretionary", "LVMUY": "Consumer Discretionary",
    "MELI": "Consumer Discretionary", "JD": "Consumer Discretionary",
    "PDD": "Consumer Discretionary",

    # --- Consumer Staples ---
    "WMT": "Consumer Staples", "PG": "Consumer Staples", "COST": "Consumer Staples",
    "KO": "Consumer Staples", "PEP": "Consumer Staples", "PM": "Consumer Staples",
    "MO": "Consumer Staples", "MDLZ": "Consumer Staples", "CL": "Consumer Staples",
    "KMB": "Consumer Staples", "GIS": "Consumer Staples", "STZ": "Consumer Staples",
    "TGT": "Consumer Staples", "KDP": "Consumer Staples", "UL": "Consumer Staples",
    "NSRGY": "Consumer Staples", "DEO": "Consumer Staples",

    # --- Industrials ---
    "GE": "Industrials", "RTX": "Industrials", "CAT": "Industrials",
    "HON": "Industrials", "UNP": "Industrials", "BA": "Industrials",
    "DE": "Industrials", "LMT": "Industrials", "UPS": "Industrials",
    "ADP": "Industrials", "ETN": "Industrials", "GD": "Industrials",
    "NOC": "Industrials", "MMM": "Industrials", "CSX": "Industrials",
    "FDX": "Industrials", "EMR": "Industrials", "ITW": "Industrials",
    "WM": "Industrials", "PH": "Industrials", "TT": "Industrials",
    "NSC": "Industrials", "PCAR": "Industrials", "ROP": "Industrials",
    "SIEGY": "Industrials", "AIR": "Industrials",

    # --- Energy ---
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy",
    "EOG": "Energy", "PSX": "Energy", "MPC": "Energy", "OXY": "Energy",
    "WMB": "Energy", "KMI": "Energy", "VLO": "Energy", "HES": "Energy",
    "BP": "Energy", "SHEL": "Energy", "TTE": "Energy", "EQNR": "Energy",

    # --- Utilities ---
    "NEE": "Utilities", "SO": "Utilities", "DUK": "Utilities", "AEP": "Utilities",
    "SRE": "Utilities", "D": "Utilities", "EXC": "Utilities", "XEL": "Utilities",
    "ED": "Utilities", "PEG": "Utilities", "WEC": "Utilities",

    # --- Real Estate ---
    "PLD": "Real Estate", "AMT": "Real Estate", "EQIX": "Real Estate",
    "PSA": "Real Estate", "O": "Real Estate", "SPG": "Real Estate",
    "WELL": "Real Estate", "DLR": "Real Estate", "CCI": "Real Estate",
    "AVB": "Real Estate", "VICI": "Real Estate",

    # --- Materials ---
    "LIN": "Materials", "APD": "Materials", "SHW": "Materials", "FCX": "Materials",
    "ECL": "Materials", "NEM": "Materials", "NUE": "Materials", "DOW": "Materials",
    "PPG": "Materials", "VALE": "Materials", "RIO": "Materials", "BHP": "Materials",
    "GLEN": "Materials", "AA": "Materials",

    # --- Broad-market / index funds: no single sector, kept together ---
    "SPY": "Diversified", "VOO": "Diversified", "IVV": "Diversified",
    "VTI": "Diversified", "VT": "Diversified", "VXUS": "Diversified",
    "QQQ": "Diversified", "DIA": "Diversified", "IWM": "Diversified",
    "CSPX": "Diversified", "EIMI": "Diversified", "IWDA": "Diversified",
    "VWRA": "Diversified", "VWCE": "Diversified", "ACWI": "Diversified",
    "EFA": "Diversified", "EEM": "Diversified", "SWDA": "Diversified",
    "AGGH": "Diversified",

    # --- Sector ETFs (kept as their sector, not "Diversified") ---
    "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
    "XLV": "Healthcare", "XLY": "Consumer Discretionary", "XLP": "Consumer Staples",
    "XLI": "Industrials", "XLU": "Utilities", "XLB": "Materials",
    "XLRE": "Real Estate", "XLC": "Communication Services",
    "SMH": "Technology", "SOXX": "Technology",

    # --- Commodities ---
    "GLD": "Commodities", "IAU": "Commodities", "SLV": "Commodities",
    "USO": "Commodities", "DBC": "Commodities", "PDBC": "Commodities",
    "SGOL": "Commodities",

    # --- Fixed income funds ---
    "AGG": "Fixed Income", "BND": "Fixed Income", "TLT": "Fixed Income",
    "IEF": "Fixed Income", "SHY": "Fixed Income", "LQD": "Fixed Income",
    "HYG": "Fixed Income", "TIP": "Fixed Income",
}


def _normalize(symbol: str) -> str:
    return "".join(ch for ch in str(symbol).upper() if ch.isalnum())


SECTOR_MAP: dict[str, str] = {_normalize(k): v for k, v in _RAW.items()}


def lookup_sector(symbol: str) -> str:
    """The real sector for a ticker, or "Unclassified" if not in the table."""
    return SECTOR_MAP.get(_normalize(symbol), "Unclassified")
