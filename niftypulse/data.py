"""Data layer (§2 of the agent spec).

Implements `fetch_history` / `fetch_index_data` on Yahoo Finance (source #3
in the spec's fallback chain). Broker APIs (Kite/Upstox) and NSE delivery-%
belong in this module too — add them behind the same interface when
credentials are available; see TODOs at the bottom.

All timestamps are converted to IST. Prices come auto-adjusted for
splits/bonuses/dividends (spec §2 data rules).
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

from .universe import INDEX_TICKER, VIX_TICKER, to_yahoo

IST = ZoneInfo("Asia/Kolkata")

MARKET_OPEN = dt.time(9, 15)
MARKET_CLOSE = dt.time(15, 30)


def now_ist() -> dt.datetime:
    return dt.datetime.now(tz=IST)


def market_is_open(ts: dt.datetime | None = None) -> bool:
    """Weekday/hours check only — NSE holiday calendar is a TODO (fetch_calendar)."""
    ts = ts or now_ist()
    return ts.weekday() < 5 and MARKET_OPEN <= ts.time() <= MARKET_CLOSE


def fetch_history(symbols: list[str], lookback: str = "1y") -> dict[str, pd.DataFrame]:
    """Daily adjusted OHLCV per NSE symbol. Symbols that fail come back empty
    and are reported by the engine as 'data unavailable' — never estimated."""
    tickers = [to_yahoo(s) for s in symbols]
    raw = yf.download(
        tickers, period=lookback, interval="1d",
        group_by="ticker", auto_adjust=True, progress=False, threads=True,
    )
    out: dict[str, pd.DataFrame] = {}
    for sym, tkr in zip(symbols, tickers):
        try:
            df = raw[tkr].dropna(how="all") if len(tickers) > 1 else raw.dropna(how="all")
        except KeyError:
            out[sym] = pd.DataFrame()
            continue
        out[sym] = _validate(df)
    return out


def fetch_index_data(lookback: str = "1y") -> tuple[pd.DataFrame, float | None]:
    """Returns (NIFTY daily OHLCV, latest India VIX or None if unavailable)."""
    nifty = yf.download(INDEX_TICKER, period=lookback, interval="1d",
                        auto_adjust=True, progress=False)
    if isinstance(nifty.columns, pd.MultiIndex):
        nifty.columns = nifty.columns.get_level_values(0)
    vix_val: float | None = None
    try:
        vix = yf.download(VIX_TICKER, period="1mo", interval="1d",
                          auto_adjust=True, progress=False)
        if isinstance(vix.columns, pd.MultiIndex):
            vix.columns = vix.columns.get_level_values(0)
        if not vix.empty:
            vix_val = float(vix["Close"].dropna().iloc[-1])
    except Exception:
        pass
    return _validate(nifty), vix_val


def _validate(df: pd.DataFrame) -> pd.DataFrame:
    """Spec §2: reject impossible bars rather than analyze corrupt data."""
    if df.empty:
        return df
    ok = (
        (df["Low"] > 0)
        & (df["High"] >= df["Low"])
        & (df["Close"] <= df["High"]) & (df["Close"] >= df["Low"])
        & (df["Open"] <= df["High"]) & (df["Open"] >= df["Low"])
    )
    return df[ok]


def data_quality(df: pd.DataFrame) -> str:
    """'eod' when market is closed; 'STALE' if we're in-session and the last
    bar is not from today (spec: >15 min old during market hours)."""
    if df.empty:
        return "unavailable"
    last = df.index[-1]
    last_date = last.date() if hasattr(last, "date") else last
    if not market_is_open():
        return "eod (market closed)"
    return "intraday" if last_date == now_ist().date() else "STALE"


# TODO(spec §10): fetch_quotes() with delivery-% — needs NSE bhavcopy or a
# broker API; wire credentials via env vars, keep access READ-ONLY (spec §8.1).
# TODO(spec §10): fetch_calendar() — NSE holiday list + earnings dates; until
# then the engine cannot enforce the pre-earnings signal suppression rule.
# TODO(spec §10): search_news() — bind a news API; until then event-awareness
# checks (§3) are skipped and reports say so.
