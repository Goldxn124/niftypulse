"""NiftyPulse web dashboard — beginner-friendly view of the scanner.

Run:  python app.py   ->  http://127.0.0.1:5057

Serves the latest saved scan and can trigger a fresh one. Analysis only —
this server never talks to a broker and never places orders (spec §8.1).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from flask import Flask, jsonify, render_template

from niftypulse.data import fetch_history, fetch_index_data
from niftypulse.engine import run_scan
from niftypulse.report import save_json, update_ledger
from niftypulse.universe import get_constituents

ROOT = Path(__file__).parent
REPORTS = ROOT / "reports"

app = Flask(__name__)
_scan_lock = threading.Lock()  # one scan at a time; concurrent refresh gets a 409


def latest_report() -> dict | None:
    files = sorted(REPORTS.glob("scan_*.json"))
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/latest")
def api_latest():
    rep = latest_report()
    if rep is None:
        return jsonify({"error": "no-scan-yet"}), 404
    return jsonify(rep)


@app.post("/api/refresh")
def api_refresh():
    if not _scan_lock.acquire(blocking=False):
        return jsonify({"error": "scan-already-running"}), 409
    try:
        symbols, source = get_constituents()
        nifty, vix = fetch_index_data()
        if nifty.empty:  # spec §9: loud system alert, never silent
            return jsonify({"error": "index-data-unavailable"}), 503
        histories = fetch_history(symbols)
        regime, signals = run_scan(histories, nifty, vix)
        save_json(regime, signals, REPORTS, universe_source=source)
        update_ledger(signals, ROOT / "ledger.json")
        return jsonify(latest_report())
    finally:
        _scan_lock.release()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5057, debug=False)
