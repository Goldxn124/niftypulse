"""NIFTY 50 constituent universe.

Per the agent spec (§2), the list must not be treated as static: we try the
official NSE endpoint first and fall back to a bundled snapshot only if NSE
is unreachable. The snapshot must be refreshed periodically — index
rebalances happen semi-annually (March/September).
"""

from __future__ import annotations

import requests

NSE_INDEX_URL = "https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050"
NSE_HOME = "https://www.nseindia.com"
NSE_ARCHIVES_CSV = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"

# Fallback snapshot of NIFTY 50 constituents (NSE symbols), verified against
# the Sept-2025 rebalance (INDIGO/MAXHEALTH in, HEROMOTOCO/INDUSINDBK out) and
# the Mar-2026 review (no changes). TMPV holds the ex-Tata Motors slot after
# the demerger. Refresh at each semi-annual rebalance; get_constituents()
# flags which source was actually used.
FALLBACK_CONSTITUENTS = [
    "ADANIENT", "ADANIPORTS", "APOLLOHOSP", "ASIANPAINT", "AXISBANK",
    "BAJAJ-AUTO", "BAJFINANCE", "BAJAJFINSV", "BEL", "BHARTIARTL",
    "CIPLA", "COALINDIA", "DRREDDY", "EICHERMOT", "ETERNAL",
    "GRASIM", "HCLTECH", "HDFCBANK", "HDFCLIFE", "HINDALCO",
    "HINDUNILVR", "ICICIBANK", "INDIGO", "INFY", "ITC",
    "JIOFIN", "JSWSTEEL", "KOTAKBANK", "LT", "M&M",
    "MARUTI", "MAXHEALTH", "NESTLEIND", "NTPC", "ONGC",
    "POWERGRID", "RELIANCE", "SBILIFE", "SBIN", "SHRIRAMFIN",
    "SUNPHARMA", "TATACONSUM", "TATASTEEL", "TCS", "TECHM",
    "TITAN", "TMPV", "TRENT", "ULTRACEMCO", "WIPRO",
]

INDEX_TICKER = "^NSEI"
VIX_TICKER = "^INDIAVIX"


def to_yahoo(symbol: str) -> str:
    """NSE symbol -> Yahoo Finance ticker."""
    return f"{symbol}.NS"


def get_constituents(timeout: float = 10.0) -> tuple[list[str], str]:
    """Return (symbols, source). source: 'nse-api', 'nse-archives-csv', or
    'fallback-snapshot'. NSE geo/bot-blocks many clients, hence the chain."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "*/*",
    }
    try:
        s = requests.Session()
        s.headers.update(headers)
        s.get(NSE_HOME, timeout=timeout)  # prime cookies; NSE rejects cold API hits
        r = s.get(NSE_INDEX_URL, timeout=timeout)
        r.raise_for_status()
        rows = r.json()["data"]
        symbols = sorted(
            row["symbol"] for row in rows
            if row.get("symbol") and row["symbol"] != "NIFTY 50"
        )
        if len(symbols) == 50:
            return symbols, "nse-api"
    except Exception:
        pass
    try:
        r = requests.get(NSE_ARCHIVES_CSV, headers=headers, timeout=timeout)
        r.raise_for_status()
        lines = r.text.strip().splitlines()
        symbols = sorted(line.split(",")[2] for line in lines[1:] if line.count(",") >= 2)
        if len(symbols) == 50:
            return symbols, "nse-archives-csv"
    except Exception:
        pass
    return list(FALLBACK_CONSTITUENTS), "fallback-snapshot"
