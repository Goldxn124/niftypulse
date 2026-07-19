"""Report rendering + signal ledger (§5 output structure, §4 self-scoring).

Every run writes the full JSON to reports/ (machine-readable, spec §6) and
appends stance changes to ledger.json so the weekly scorecard can be computed
honestly — winners and losers alike (spec §8.4).
"""

from __future__ import annotations

import json
from pathlib import Path

from .data import now_ist
from .engine import Signal

DISCLAIMER = (
    "This is automated technical analysis for informational purposes, not "
    "investment advice. I am not a SEBI-registered investment adviser. Markets "
    "carry risk of loss; past signals do not predict future results."
)


def save_json(regime: dict, signals: list[Signal], outdir: Path,
              universe_source: str = "?") -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    stamp = now_ist().strftime("%Y-%m-%d_%H%M")
    path = outdir / f"scan_{stamp}.json"
    payload = {
        "generated_at": now_ist().isoformat(timespec="seconds"),
        "regime": regime,
        "universe_source": universe_source,
        "disclaimer": DISCLAIMER,
        "signals": [s.to_dict() for s in signals],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def update_ledger(signals: list[Signal], ledger_path: Path) -> int:
    """Append signals whose stance changed since last run. Returns count added."""
    ledger = []
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    last_stance = {}
    for entry in ledger:
        last_stance[entry["symbol"]] = entry["stance"]
    added = 0
    for s in signals:
        if last_stance.get(s.symbol) != s.stance:
            ledger.append(s.to_dict())
            added += 1
    ledger_path.write_text(json.dumps(ledger, indent=2), encoding="utf-8")
    return added


def render_text(regime: dict, signals: list[Signal], top: int = 5,
                constituents_source: str = "?") -> str:
    lines: list[str] = []
    vix = regime["vix"] if regime["vix"] is not None else "n/a"
    buys = sum(1 for s in signals if s.stance == "BUY")
    sells = sum(1 for s in signals if s.stance == "SELL")
    lines.append("=" * 78)
    lines.append(f"NIFTYPULSE SCAN — {now_ist().strftime('%a %d %b %Y %H:%M IST')}")
    lines.append(f"Regime: {regime['label'].upper()}  |  NIFTY {regime['nifty_close']} "
                 f"vs 200-EMA {regime['nifty_ema200']}  |  India VIX: {vix}")
    if regime.get("vix_note"):
        lines.append(f"Note: {regime['vix_note']}")
    lines.append(f"Stances: {buys} BUY / {sells} SELL / {len(signals)-buys-sells} HOLD-AVOID "
                 f"(universe source: {constituents_source})")
    lines.append("=" * 78)

    actionable = [s for s in signals if s.stance == "BUY" and s.entry_zone][:top]
    lines.append(f"\nACTIONABLE SETUPS (top {len(actionable)} by confidence)")
    lines.append("-" * 78)
    if not actionable:
        lines.append("None meeting the 1:2 risk:reward bar today — standing aside is a position.")
    for s in actionable:
        lines.append(f"\n{s.symbol}  [{s.stance} / {s.timeframe}]  LTP {s.ltp}  "
                     f"conf {s.confidence}  data: {s.data_quality}")
        lines.append(f"  entry {s.entry_zone[0]}-{s.entry_zone[1]}  stop {s.stop_loss}  "
                     f"targets {s.targets[0]} / {s.targets[1]}  RR {s.risk_reward}")
        lines.append(f"  trigger: {s.trigger}")
        for e in s.evidence:
            lines.append(f"  + {e}")
        for r in s.risks:
            lines.append(f"  ! {r}")

    lines.append("\nFULL TABLE (all constituents, sorted by confidence)")
    lines.append("-" * 78)
    lines.append(f"{'SYMBOL':<12}{'LTP':>10}  {'STANCE':<6}{'CONF':>5}  {'KEY LEVEL':<26}NOTE")
    for s in signals:
        ltp = f"{s.ltp:.2f}" if s.ltp else "n/a"
        if s.stance == "BUY" and s.entry_zone:
            key = f"entry {s.entry_zone[0]}-{s.entry_zone[1]}"
        elif s.stop_loss:
            key = f"reassess {s.stop_loss}"
        else:
            key = "-"
        note = (s.evidence[0] if s.evidence else (s.risks[0] if s.risks else ""))[:34]
        lines.append(f"{s.symbol:<12}{ltp:>10}  {s.stance:<6}{s.confidence:>5}  {key:<26}{note}")

    lines.append("\n" + "=" * 78)
    lines.append(DISCLAIMER)
    lines.append("=" * 78)
    return "\n".join(lines)
