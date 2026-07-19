# NiftyPulse

Runnable scaffold of the **NIFTY 50 Market Tracking & Trade-Timing Agent** specified in
[`../nifty50-market-agent-prompt.md`](../nifty50-market-agent-prompt.md). Analysis only —
it never places orders.

> This is automated technical analysis for informational purposes, not investment advice.
> Not a SEBI-registered investment adviser. Markets carry risk of loss; past signals do
> not predict future results.

## Quickstart

```powershell
python -m pip install -r requirements.txt
python app.py                          # web dashboard -> http://127.0.0.1:5057
```

The dashboard (`app.py` + `templates/index.html`) is the beginner-friendly way in:
market-mood banner in plain English, a "how to read this page" glossary, buy-setup
cards with entry/stop/target in ₹ and %, filterable table of all 50 stocks, and a
"Run fresh scan" button (takes ~1 minute; one scan at a time).

CLI alternative:

```powershell
python run.py                          # full 50-stock scan in the terminal
python run.py --top 8                  # detail more setups
python run.py --symbols RELIANCE,TCS   # fast subset scan
```

Each run prints the human report (regime line → actionable setups → full table →
disclaimer), writes machine-readable JSON to `reports/`, and appends stance changes to
`ledger.json` for the weekly scorecard.

## Layout (spec section → module)

| Module | Spec | What it does |
|---|---|---|
| `niftypulse/universe.py` | §2 | Constituents: NSE API → NSE archives CSV → verified snapshot (flags which source was used) |
| `niftypulse/data.py` | §2 | Yahoo Finance history (adjusted OHLCV), NIFTY + India VIX, IST timestamps, bar validation, staleness labels |
| `niftypulse/indicators.py` | §3 | EMA / RSI / MACD / ADX / ATR / Bollinger / relative-strength, Wilder-smoothed |
| `niftypulse/engine.py` | §3–§4 | Evidence scoring → stance; regime filter caps BUYs in bearish tape; 1:2 RR enforced or signal degrades to HOLD |
| `niftypulse/report.py` | §5–§6, §8 | Text + JSON reports, signal ledger, standing disclaimer |
| `run.py` | §5, §9 | CLI entry; system-alert abort if index data unavailable |

## Implemented vs. TODO

Implemented: daily-bar swing signals for all 50 constituents, regime filter,
entry-zone/stop/target/RR construction, confidence scoring with top-3 evidence,
per-stock failure isolation, JSON + ledger persistence.

Not yet wired (marked in `data.py`): broker API quotes with delivery-% (keep read-only),
NSE holiday + earnings calendar (until then the pre-earnings suppression rule from §3
cannot fire — reports say so), news scan, intraday 15-minute mode, scheduled runs
(§5 — pair `run.py` with Task Scheduler or a Claude Code scheduled task), and the
weekly scorecard rollup over `ledger.json`.

## Constituent snapshot note

The bundled fallback list was verified 2026-07-19: Sept-2025 rebalance applied
(INDIGO, MAXHEALTH in; HEROMOTOCO, INDUSINDBK out), Mar-2026 review made no changes,
and TMPV holds the ex-Tata Motors slot post-demerger. Refresh it at each semi-annual
rebalance if NSE endpoints are unreachable from your network.
