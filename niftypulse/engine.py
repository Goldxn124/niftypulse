"""Signal engine — implements §3 (analysis) and §4 (signal rules) of the spec.

Scoring model: evidence adds/subtracts points around a neutral 50; stance is
derived from the total, then §4's completeness rules are enforced (a BUY
without 1:2 risk:reward degrades to HOLD with a wait-for note). The regime
filter caps BUY confidence at 60 in a bearish tape (§3).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict

import pandas as pd

from . import indicators as ta
from .data import data_quality, now_ist

MIN_HISTORY = 60          # bars needed before we trust any signal
MIN_RISK_REWARD = 2.0     # spec §4
BEARISH_BUY_CONF_CAP = 60  # spec §3 regime filter


@dataclass
class Signal:
    symbol: str
    as_of: str
    ltp: float | None = None
    stance: str = "AVOID"
    timeframe: str = "swing"
    entry_zone: list[float] | None = None
    trigger: str | None = None
    stop_loss: float | None = None
    targets: list[float] | None = None
    risk_reward: str | None = None
    confidence: int = 0
    regime: str = "unknown"
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    data_quality: str = "unavailable"

    def to_dict(self) -> dict:
        return asdict(self)


def assess_regime(nifty: pd.DataFrame, vix: float | None) -> dict:
    """Spec §3 regime filter: NIFTY vs 200-day EMA plus India VIX bands."""
    close = nifty["Close"]
    ema200 = ta.ema(close, 200).iloc[-1]
    last = float(close.iloc[-1])
    above = last > float(ema200)
    if above and (vix is None or vix < 20):
        label = "bullish"
    elif not above or (vix is not None and vix > 25):
        label = "bearish"
    else:
        label = "neutral"
    return {
        "label": label,
        "nifty_close": round(last, 2),
        "nifty_ema200": round(float(ema200), 2),
        "vix": round(vix, 2) if vix is not None else None,
        "vix_note": "India VIX unavailable — regime from trend only" if vix is None else None,
    }


def analyze(symbol: str, df: pd.DataFrame, nifty_close: pd.Series, regime: dict) -> Signal:
    sig = Signal(symbol=symbol, as_of=now_ist().isoformat(timespec="seconds"),
                 regime=regime["label"])
    if df.empty or len(df) < MIN_HISTORY:
        sig.risks.append("data unavailable or insufficient history — no signal (spec §8.5)")
        return sig

    sig.data_quality = data_quality(df)
    close = df["Close"]
    ltp = float(close.iloc[-1])
    sig.ltp = round(ltp, 2)

    ema20 = ta.ema(close, 20)
    ema50 = ta.ema(close, 50)
    ema200 = ta.ema(close, 200)
    rsi = ta.rsi(close)
    _, _, macd_hist = ta.macd(close)
    adx, plus_di, minus_di = ta.adx(df)
    atr = float(ta.atr(df).iloc[-1])
    bb_up, _, bb_lo, bb_width = ta.bollinger(close)
    vol_ratio = float(df["Volume"].iloc[-1] / max(df["Volume"].rolling(20).mean().iloc[-1], 1))
    rs20 = ta.relative_strength(close, nifty_close, 20)
    rs60 = ta.relative_strength(close, nifty_close, 60)
    high52 = float(df["High"].rolling(min(252, len(df))).max().iloc[-1])
    low52 = float(df["Low"].rolling(min(252, len(df))).min().iloc[-1])

    e20, e50, e200 = float(ema20.iloc[-1]), float(ema50.iloc[-1]), float(ema200.iloc[-1])
    rsi_now = float(rsi.iloc[-1])
    adx_now = float(adx.iloc[-1])
    hist_now, hist_prev = float(macd_hist.iloc[-1]), float(macd_hist.iloc[-2])

    score = 0
    ev: list[tuple[int, str]] = []  # (|points|, text) so we can report top-3

    # Trend (§3)
    if e20 > e50 > e200:
        score += 20; ev.append((20, f"Bullish EMA stack (20>50>200), ADX {adx_now:.0f}"))
    elif e20 < e50 < e200:
        score -= 20; ev.append((20, f"Bearish EMA stack (20<50<200), ADX {adx_now:.0f}"))
    if adx_now > 25:
        pts = 8 if float(plus_di.iloc[-1]) > float(minus_di.iloc[-1]) else -8
        score += pts; ev.append((8, f"Trending market (ADX {adx_now:.0f})"))
    elif adx_now < 20:
        ev.append((0, f"Range-bound (ADX {adx_now:.0f}) — mean-reversion tape"))

    # Momentum (§3)
    if 45 <= rsi_now <= 65:
        score += 8; ev.append((8, f"RSI {rsi_now:.0f} in healthy zone"))
    elif rsi_now > 70:
        score -= 8; ev.append((8, f"RSI {rsi_now:.0f} overbought")); sig.risks.append("Overbought — chase risk")
    elif rsi_now < 30:
        ev.append((4, f"RSI {rsi_now:.0f} oversold — watch for reversal, not a buy by itself"))
    if hist_now > 0 and hist_now > hist_prev:
        score += 8; ev.append((8, "MACD histogram positive and rising"))
    elif hist_now < 0 and hist_now < hist_prev:
        score -= 8; ev.append((8, "MACD histogram negative and falling"))

    # Relative strength vs index (§3)
    if not pd.isna(rs20) and rs20 > 2:
        score += 8; ev.append((8, f"Outperforming NIFTY by {rs20:+.1f}pp / 20d"))
    elif not pd.isna(rs20) and rs20 < -2:
        score -= 8; ev.append((8, f"Lagging NIFTY by {rs20:+.1f}pp / 20d"))
    if not pd.isna(rs60) and rs60 > 5:
        score += 4; ev.append((4, f"Outperforming NIFTY by {rs60:+.1f}pp / 60d"))

    # Volatility & levels (§3)
    width_now = float(bb_width.iloc[-1])
    width_decile = float(bb_width.dropna().rank(pct=True).iloc[-1])
    if width_decile < 0.10:
        ev.append((6, "Bollinger squeeze (width in bottom decile) — breakout watch"))
        score += 3
    dist_high = 100 * (high52 - ltp) / high52
    if dist_high < 3:
        score += 5; ev.append((5, f"Within {dist_high:.1f}% of 52-week high"))
    if ltp < low52 * 1.03:
        score -= 5; sig.risks.append("Near 52-week low — falling knife risk")

    # Volume confirmation (§3): breakout w/o volume downgrades one tier
    if vol_ratio >= 1.5:
        score += 6; ev.append((6, f"Volume {vol_ratio:.1f}x 20-day average"))
    elif vol_ratio < 0.6:
        sig.risks.append(f"Thin volume ({vol_ratio:.1f}x avg) — low conviction tape")
        score -= 4

    # Stance from score
    if score >= 25:
        sig.stance = "BUY"
    elif score <= -25:
        sig.stance = "SELL"
    else:
        sig.stance = "HOLD"

    confidence = max(5, min(95, 50 + score))

    # Regime filter (§3): never fight the tape
    if regime["label"] == "bearish" and sig.stance == "BUY":
        confidence = min(confidence, BEARISH_BUY_CONF_CAP)
        sig.risks.append("Index in bearish regime — BUY confidence capped, half size (spec §3)")
    sig.confidence = int(confidence)

    # Entry/exit plan (§4): only for directional stances, and only if 1:2 RR holds
    if sig.stance == "BUY":
        entry_lo = round(max(e20, ltp - 0.5 * atr), 2)
        entry_hi = round(ltp + 0.25 * atr, 2)
        if entry_lo >= entry_hi:  # price is below its 20-EMA — anchor zone to price, not the EMA
            entry_lo = round(ltp - 0.5 * atr, 2)
        entry_mid = (entry_lo + entry_hi) / 2
        stop = round(entry_lo - 2 * atr, 2)
        risk = entry_mid - stop
        t1, t2 = round(entry_mid + 2 * risk, 2), round(entry_mid + 3 * risk, 2)
        rr = (t1 - entry_mid) / risk if risk > 0 else 0
        if rr >= MIN_RISK_REWARD and risk > 0:
            sig.entry_zone = [entry_lo, entry_hi]
            sig.stop_loss = stop
            sig.targets = [t1, t2]
            sig.risk_reward = f"1:{rr:.1f}"
            near_high = round(min(high52, ltp + atr), 2)
            sig.trigger = (f"enter in zone; add on daily close above {near_high} "
                           f"with volume >= 1.5x 20d avg; invalid below {stop}")
        else:
            sig.stance = "HOLD"
            sig.trigger = f"wait for pullback toward 20-EMA near {round(e20, 2)} (RR below 1:2 here)"
    elif sig.stance == "SELL":
        stop = round(ltp + 2 * atr, 2)
        sig.stop_loss = stop
        sig.trigger = f"exit/avoid longs; reassess on daily close above {round(e50, 2)} (50-EMA)"

    if sig.data_quality == "STALE":
        sig.risks.insert(0, "STALE DATA — price >15 min old during market hours (spec §2)")

    ev.sort(key=lambda t: -t[0])
    sig.evidence = [text for _, text in ev[:3]]
    sig.risks.append("Earnings/news calendar not wired yet — event risk unchecked (see data.py TODO)")
    return sig


def run_scan(histories: dict[str, pd.DataFrame], nifty: pd.DataFrame,
             vix: float | None) -> tuple[dict, list[Signal]]:
    regime = assess_regime(nifty, vix)
    nifty_close = nifty["Close"]
    signals = []
    for sym, df in histories.items():
        try:
            signals.append(analyze(sym, df, nifty_close, regime))
        except Exception as exc:  # spec §9: one bad stock never kills the run
            s = Signal(symbol=sym, as_of=now_ist().isoformat(timespec="seconds"),
                       regime=regime["label"])
            s.risks.append(f"indicator computation failed: {exc}")
            signals.append(s)
    signals.sort(key=lambda s: (-s.confidence, s.symbol))
    return regime, signals
