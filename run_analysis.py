"""
Headless-Analyse-Skript für GitHub Actions.
Führt den vollständigen S&P500-Scan durch und speichert den Cache.
Kein Streamlit notwendig — reines Python.

Verwendung:
    python run_analysis.py
"""

import logging
import sys
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


def progress(done: int, total: int, ticker: str):
    if done % 50 == 0 or done == total:
        pct = done / total * 100
        print(f"  [{pct:5.1f}%] {done}/{total} — zuletzt: {ticker}", flush=True)


def main():
    print("=" * 60)
    print(f"  S&P500 Analyse — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 60)

    from analyzer.scorer import run_full_scan
    from scheduler import save_cache

    result = run_full_scan(progress_callback=progress)
    save_cache(result)

    market = result.get("market", {})
    recommendations = result.get("recommendations", [])
    all_results = result.get("all_results", [])
    duration = result.get("scan_duration_s", 0)

    print("\n" + "=" * 60)
    print("  ERGEBNIS")
    print("=" * 60)
    print(f"  Markt:          {'BULLISCH ✓' if market.get('passed') else 'BEARISCH ✗'}")
    if not market.get("passed"):
        print(f"  Grund:          {market.get('reason', '')}")
    print(f"  VIX:            {market.get('vix', 'N/A')}")
    print(f"  Analysiert:     {len(all_results)} Aktien")
    print(f"  Empfehlungen:   {len(recommendations)}")
    print(f"  Scan-Dauer:     {duration:.0f}s")

    if recommendations:
        print("\n  EMPFOHLENE AKTIEN:")
        for r in recommendations:
            tech_score = r.get("tech_score", 0) * 100
            fund_score = r.get("fund_score", 0) * 100
            price = r.get("price")
            price_str = f"${price:.2f}" if price else "N/A"
            print(f"    → {r['ticker']:6s}  {r.get('name', '')[:35]:35s}  "
                  f"Kurs: {price_str:8s}  Tech: {tech_score:.0f}%  Fund: {fund_score:.0f}%")
    else:
        print("\n  Keine Empfehlungen — System wartet auf klarere Signale.")

    print("=" * 60)

    # Exit-Code 0 auch ohne Empfehlungen (kein CI-Fehler)
    sys.exit(0)


if __name__ == "__main__":
    main()
