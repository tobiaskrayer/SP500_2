"""End-to-End-Smoke-Test: run_full_scan mit verkleinertem Universum (15 Ticker)."""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import analyzer.scorer as scorer

TICKERS = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "AVGO", "LLY",
           "JPM", "V", "XOM", "UNH", "COST", "HD", "MRK"]
scorer.get_sp500_tickers = lambda: TICKERS

t0 = time.time()
result = scorer.run_full_scan()
dur = time.time() - t0

market = result["market"]
print(f"Markt: passed={market.get('passed')} ({market.get('reason', '')})")
print(f"Dauer: {dur:.1f}s fuer {len(TICKERS)} Ticker")

if not market.get("passed"):
    print("Gate 1 rot — Scan-Logik nach Gate 1 nicht testbar (kein Fehler).")
    sys.exit(0)

allr = result["all_results"]
print(f"analysiert: {len(allr)}, v1-Empf.: {len(result['recommendations'])}, "
      f"v2-Empf.: {len(result['recommendations_v2'])}")
assert len(allr) >= 12, f"Zu viele Ticker fehlen: {len(allr)}/15"

# v2-Invarianten: max top_n, Raenge konsistent
v2 = result["recommendations_v2"]
assert len(v2) <= 10, f"v2 > top_n: {len(v2)}"
for r in v2:
    assert r.get("v2_rank") is not None and 1 <= r["v2_rank"] <= 10, f"Rang kaputt: {r}"
    assert "macd_bull" in r, "macd_bull fehlt im Slim-Datensatz"

# Cache-Wirkung: zweiter Lauf muss deutlich schneller sein (Preis- + Fund-Cache)
t0 = time.time()
scorer.run_full_scan()
dur2 = time.time() - t0
print(f"Zweiter Lauf (Caches warm): {dur2:.1f}s")
assert dur2 < dur, "Zweiter Lauf nicht schneller — Caches wirkungslos?"

print("ALLE CHECKS OK")
