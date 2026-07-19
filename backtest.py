"""Walk-forward backtest of the live NiftyPulse rules.

Calls the SAME engine.analyze() the dashboard uses on an expanding window —
no reimplemented logic, so what's tested is what's deployed. Long-only
(the dashboard treats SELL as "avoid", not "short").

Trade simulation per BUY signal, mirroring the card's plan:
  - Fill next session if price trades into the entry zone (at open if it
    opens inside/below the zone top, else at the zone top). No fill in
    MAX_WAIT sessions -> setup expires.
  - Exit half at Target 1, stop moves to breakeven for the rest; remainder
    exits at Target 2, stop, or after MAX_HOLD sessions at close.
  - Stop assumed to fill BEFORE targets on same-day conflicts; opening gaps
    through the stop fill at the open (worse than the stop) — honest.
  - Costs: COST_PCT per side on every fill.

Usage:
  python backtest.py                     # full NIFTY 50, 2 years
  python backtest.py --years 3
  python backtest.py --symbols TCS,INFY  # quick subset
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd
import yfinance as yf

from niftypulse import engine
from niftypulse.data import fetch_history
from niftypulse.indicators import ema
from niftypulse.universe import INDEX_TICKER, VIX_TICKER, get_constituents

sys.stdout.reconfigure(encoding="utf-8")
ROOT = Path(__file__).parent

COST_PCT = 0.001   # 0.1% per side: STT + slippage, discount-broker world
MAX_HOLD = 20      # sessions — the spec's swing timeframe upper bound
MAX_WAIT = 5       # sessions a pending entry stays valid
WARMUP = 300       # sessions of history before the first signal is trusted
SLICE = 280        # trailing window passed to analyze() (mirrors live 1y fetch ≈ 252 rows)


def fetch_series(years: int):
    period = f"{years + 2}y"
    nifty = yf.download(INDEX_TICKER, period=period, interval="1d",
                        auto_adjust=True, progress=False)
    if isinstance(nifty.columns, pd.MultiIndex):
        nifty.columns = nifty.columns.get_level_values(0)
    vix = None
    try:
        v = yf.download(VIX_TICKER, period=period, interval="1d",
                        auto_adjust=True, progress=False)
        if isinstance(v.columns, pd.MultiIndex):
            v.columns = v.columns.get_level_values(0)
        if not v.empty:
            vix = v["Close"]
    except Exception:
        pass
    return nifty, vix


def daily_regimes(nifty: pd.DataFrame, vix: pd.Series | None) -> pd.Series:
    """Same thresholds as engine.assess_regime, evaluated per historical day.
    EWM at day t depends only on data up to t — no lookahead. Returns a label
    Series on the index's calendar; callers reindex+ffill onto each stock's
    own calendar (sessions can differ between feeds)."""
    e200 = ema(nifty["Close"], 200)
    vix_aligned = vix.reindex(nifty.index).ffill() if vix is not None else None
    labels = {}
    for ts in nifty.index:
        close, e = float(nifty["Close"].loc[ts]), float(e200.loc[ts])
        v = float(vix_aligned.loc[ts]) if vix_aligned is not None and pd.notna(vix_aligned.loc[ts]) else None
        above = close > e
        if above and (v is None or v < 20):
            label = "bullish"
        elif (not above) or (v is not None and v > 25):
            label = "bearish"
        else:
            label = "neutral"
        labels[ts] = label
    return pd.Series(labels)


def simulate_symbol(sym: str, df: pd.DataFrame, nifty_close: pd.Series,
                    regime_labels: pd.Series, sessions: int) -> list[dict]:
    trades: list[dict] = []
    if len(df) < WARMUP + 20:
        return trades
    labels = regime_labels.reindex(df.index).ffill().bfill()
    start = max(len(df) - sessions, WARMUP)
    pos = None
    pending = None

    for i in range(start, len(df) - 1):
        today = df.index[i]
        nxt = df.iloc[i + 1]
        o, h, l, c = (float(nxt["Open"]), float(nxt["High"]),
                      float(nxt["Low"]), float(nxt["Close"]))

        if pos:
            entry, stop0 = pos["entry"], pos["stop0"]
            risk = entry - stop0
            stop = pos["stop"]
            exits = pos["exits"]

            def close_out(px: float, frac: float):
                exits.append((px * (1 - COST_PCT), frac))

            done = False
            if o <= stop:                      # gap through the stop
                close_out(o, 1.0 - pos["scaled_frac"]); done = True
            elif l <= stop:
                close_out(stop, 1.0 - pos["scaled_frac"]); done = True
            elif not pos["scaled"] and h >= pos["t1"]:
                close_out(pos["t1"], 0.5)
                pos.update(scaled=True, scaled_frac=0.5, stop=entry)  # breakeven
                if h >= pos["t2"] and l > entry:   # same-day T2, stop untouched
                    close_out(pos["t2"], 0.5); done = True
            elif pos["scaled"] and h >= pos["t2"]:
                close_out(pos["t2"], 0.5); done = True
            elif i + 1 - pos["opened_i"] >= MAX_HOLD:  # time stop
                close_out(c, 1.0 - pos["scaled_frac"]); done = True

            if done:
                gross = sum(px * fr for px, fr in exits)
                cost_in = entry * COST_PCT
                r_mult = (gross - entry - cost_in) / risk
                trades.append({
                    "symbol": sym,
                    "entry_date": str(pos["entry_date"].date()),
                    "exit_date": str(df.index[i + 1].date()),
                    "entry": round(entry, 2), "stop": round(stop0, 2),
                    "r": round(r_mult, 3),
                    "win": r_mult > 0,
                    "hold_days": i + 1 - pos["opened_i"],
                    "confidence": pos["conf"],
                    "regime": pos["regime"],
                })
                pos = None
            continue

        if pending:
            lo, hi, stop = pending["lo"], pending["hi"], pending["stop"]
            fill = None
            if o <= hi and o > stop:
                fill = max(o, lo * 0.995)      # fill at open when it opens in/below zone
            elif l <= hi and o > stop:
                fill = hi                      # traded down into the zone
            if fill and fill > stop:
                pos = {"entry": fill * (1 + COST_PCT), "stop0": pending["stop"],
                       "stop": pending["stop"], "t1": pending["t1"], "t2": pending["t2"],
                       "opened_i": i + 1, "entry_date": df.index[i + 1],
                       "scaled": False, "scaled_frac": 0.0, "exits": [],
                       "conf": pending["conf"], "regime": pending["regime"]}
                pending = None
                continue
            pending["age"] += 1
            if pending["age"] >= MAX_WAIT:
                pending = None

        if pos is None and pending is None:
            hist = df.iloc[max(0, i - SLICE + 1): i + 1]
            # relative_strength needs only the last ~60 index closes
            sig = engine.analyze(sym, hist, nifty_close.loc[:today].tail(90),
                                 {"label": labels.loc[today]})
            if sig.stance == "BUY" and sig.entry_zone and sig.stop_loss and sig.targets:
                pending = {"lo": sig.entry_zone[0], "hi": sig.entry_zone[1],
                           "stop": sig.stop_loss, "t1": sig.targets[0],
                           "t2": sig.targets[1], "conf": sig.confidence,
                           "regime": sig.regime, "age": 0}
    return trades


def portfolio_sim(trades: list[dict], start_equity: float = 100_000.0,
                  risk_frac: float = 0.01, max_slots: int = 5) -> dict:
    """Replay trades chronologically under the spec's money rules:
    1% of current equity risked per trade, max 5 concurrent positions."""
    ordered = sorted(trades, key=lambda t: (t["entry_date"], -t["confidence"]))
    equity = start_equity
    open_until: list[str] = []
    curve = []
    taken = skipped = 0
    peak, max_dd = equity, 0.0
    for t in ordered:
        open_until = [d for d in open_until if d > t["entry_date"]]
        if len(open_until) >= max_slots:
            skipped += 1
            continue
        taken += 1
        open_until.append(t["exit_date"])
        equity += equity * risk_frac * t["r"]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
        curve.append({"date": t["exit_date"], "equity": round(equity, 2)})
    return {"start": start_equity, "end": round(equity, 2),
            "return_pct": round(100 * (equity / start_equity - 1), 2),
            "max_drawdown_pct": round(100 * max_dd, 2),
            "trades_taken": taken, "trades_skipped_slots": skipped,
            "curve": curve}


def summarize(trades: list[dict]) -> dict:
    if not trades:
        return {"trades": 0}
    rs = [t["r"] for t in trades]
    wins = [r for r in rs if r > 0]
    losses = [r for r in rs if r <= 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    by_regime = {}
    for label in ("bullish", "neutral", "bearish"):
        sub = [t["r"] for t in trades if t["regime"] == label]
        if sub:
            by_regime[label] = {"n": len(sub),
                                "win_rate_pct": round(100 * sum(1 for r in sub if r > 0) / len(sub), 1),
                                "avg_r": round(sum(sub) / len(sub), 3)}
    return {
        "trades": len(trades),
        "win_rate_pct": round(100 * len(wins) / len(rs), 1),
        "avg_r": round(sum(rs) / len(rs), 3),
        "median_r": round(sorted(rs)[len(rs) // 2], 3),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
        "best_r": round(max(rs), 2), "worst_r": round(min(rs), 2),
        "avg_hold_days": round(sum(t["hold_days"] for t in trades) / len(trades), 1),
        "by_regime": by_regime,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward backtest of live NiftyPulse rules")
    ap.add_argument("--years", type=int, default=2)
    ap.add_argument("--symbols", type=str, default=None)
    args = ap.parse_args()

    sessions = args.years * 252
    if args.symbols:
        symbols, src = [s.strip().upper() for s in args.symbols.split(",")], "cli-arg"
    else:
        symbols, src = get_constituents()

    print(f"Backtest: {len(symbols)} symbols ({src}), ~{args.years}y window, "
          f"costs {COST_PCT:.2%}/side", file=sys.stderr)
    nifty, vix = fetch_series(args.years)
    if nifty.empty:
        print("index data unavailable — aborting", file=sys.stderr)
        return 1
    regimes = daily_regimes(nifty, vix)
    histories = fetch_history(symbols, lookback=f"{args.years + 2}y")

    all_trades: list[dict] = []
    skipped: list[str] = []
    for n, (sym, df) in enumerate(histories.items(), 1):
        if df.empty or len(df) < WARMUP + 20:
            skipped.append(sym)
            print(f"[{n:2}/{len(histories)}] {sym}: skipped (short history)", file=sys.stderr)
            continue
        t = simulate_symbol(sym, df, nifty["Close"], regimes, sessions)
        all_trades.extend(t)
        print(f"[{n:2}/{len(histories)}] {sym}: {len(t)} trades", file=sys.stderr)

    summary = summarize(all_trades)
    port = portfolio_sim(all_trades)
    nifty_window = nifty["Close"].iloc[-min(sessions, len(nifty)):]
    nifty_ret = round(100 * (float(nifty_window.iloc[-1]) / float(nifty_window.iloc[0]) - 1), 2)

    outdir = ROOT / "reports"
    outdir.mkdir(exist_ok=True)
    pd.DataFrame(all_trades).to_csv(outdir / "backtest_trades.csv", index=False)
    payload = {"window_years": args.years, "cost_per_side": COST_PCT,
               "skipped_symbols": skipped, "signal_stats": summary,
               "portfolio_1pct_risk_5_slots": {k: v for k, v in port.items() if k != "curve"},
               "nifty_buy_and_hold_return_pct": nifty_ret}
    (outdir / "backtest_summary.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print(json.dumps(payload, indent=2))
    print(f"\ntrade log: {outdir / 'backtest_trades.csv'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
