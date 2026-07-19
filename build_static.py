"""Build the static site (site/) for free hosting on GitHub Pages.

Runs a full scan, then writes:
  site/index.html   -- the same dashboard the Flask app serves
  site/latest.json  -- the scan payload the page fetches
  site/.nojekyll    -- tells GitHub Pages to serve files as-is

The page auto-detects static hosting (latest.json present) and hides the
live-rescan button. The GitHub Action in .github/workflows/scan.yml rebuilds
and redeploys this every market morning, which is what keeps the hosted site
fresh without a server.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from niftypulse.data import fetch_history, fetch_index_data, now_ist
from niftypulse.engine import run_scan
from niftypulse.report import DISCLAIMER
from niftypulse.universe import get_constituents

ROOT = Path(__file__).parent
SITE = ROOT / "site"


def main() -> int:
    symbols, source = get_constituents()
    nifty, vix = fetch_index_data()
    if nifty.empty:  # spec §9: never publish fabricated data; keep the old site
        print("SYSTEM ALERT: index data unavailable - aborting build, previous site kept")
        return 1
    histories = fetch_history(symbols)
    regime, signals = run_scan(histories, nifty, vix)

    SITE.mkdir(exist_ok=True)
    payload = {
        "generated_at": now_ist().isoformat(timespec="seconds"),
        "regime": regime,
        "universe_source": source,
        "disclaimer": DISCLAIMER,
        "signals": [s.to_dict() for s in signals],
    }
    (SITE / "latest.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    shutil.copyfile(ROOT / "templates" / "index.html", SITE / "index.html")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site/ built: {len(signals)} signals, regime={regime['label']}, "
          f"universe={source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
