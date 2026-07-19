"""Technical indicators from the agent spec (§3), implemented on pandas only.

All functions take/return pandas Series aligned to the input index. Wilder
smoothing (ewm alpha=1/n) is used where the classic definition calls for it
(RSI, ATR, ADX) so values match standard charting platforms.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9):
    line = ema(close, fast) - ema(close, slow)
    signal = line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal


def true_range(df: pd.DataFrame) -> pd.Series:
    prev_close = df["Close"].shift()
    return pd.concat(
        [df["High"] - df["Low"],
         (df["High"] - prev_close).abs(),
         (df["Low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def adx(df: pd.DataFrame, n: int = 14):
    """Returns (adx, +di, -di)."""
    up = df["High"].diff()
    down = -df["Low"].diff()
    plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=df.index)
    minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=df.index)
    tr_smooth = true_range(df).ewm(alpha=1 / n, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=1 / n, adjust=False).mean() / tr_smooth
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    return dx.ewm(alpha=1 / n, adjust=False).mean(), plus_di, minus_di


def bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    """Returns (upper, mid, lower, bandwidth). bandwidth = (upper-lower)/mid."""
    mid = close.rolling(n).mean()
    sd = close.rolling(n).std()
    upper, lower = mid + k * sd, mid - k * sd
    return upper, mid, lower, (upper - lower) / mid


def relative_strength(close: pd.Series, index_close: pd.Series, n: int) -> float:
    """Stock return minus index return over n sessions, in percent points."""
    if len(close) <= n or len(index_close) <= n:
        return float("nan")
    stock_ret = close.iloc[-1] / close.iloc[-n - 1] - 1
    index_ret = index_close.iloc[-1] / index_close.iloc[-n - 1] - 1
    return round(100 * (stock_ret - index_ret), 2)
