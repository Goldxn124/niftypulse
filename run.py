"""NiftyPulse CLI — run a full NIFTY 50 scan.

Usage:
    python run.py                 # full scan, text report + JSON to reports/
    python run.py --top 8         # show more actionable setups
    python run.py --symbols RELIANCE,TCS   # subset scan (faster)

Analysis only. Never places orders (spec §8.1).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Windows consoles default to cp1252; reports use unicode punctuation
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from niftypulse.data import fetch_history, fetch_index_data
from niftypulse.engine import run_scan
from niftypulse.report import render_text, save_json, update_ledger
from niftypulse.universe import get_constituents

ROOT = Path(__file__).parent


def main() -> int:
    ap = argparse.ArgumentParser(description="NiftyPulse NIFTY 50 scan")
    ap.add_argument("--top", type=int, default=5, help="actionable setups to detail")
    ap.add_argument("--symbols", type=str, default=None,
                    help="comma-separated subset instead of full NIFTY 50")
    args = ap.parse_args()

    if args.symbols:
        symbols, source = [s.strip().upper() for s in args.symbols.split(",")], "cli-arg"
    else:
        symbols, source = get_constituents()

    print(f"Fetching index data + {len(symbols)} stocks (source: {source})...",
          file=sys.stderr)
    nifty, vix = fetch_index_data()
    if nifty.empty:
        print("SYSTEM ALERT: index data unavailable from all sources — aborting "
              "per spec §9 (no analysis without data).", file=sys.stderr)
        return 1
    histories = fetch_history(symbols)

    regime, signals = run_scan(histories, nifty, vix)

    json_path = save_json(regime, signals, ROOT / "reports", universe_source=source)
    added = update_ledger(signals, ROOT / "ledger.json")

    print(render_text(regime, signals, top=args.top, constituents_source=source))
    print(f"\nJSON report: {json_path}", file=sys.stderr)
    print(f"Ledger: {added} stance change(s) recorded.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
