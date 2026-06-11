"""Test: Universum-Fallback-Kette + Metadaten."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import analyzer.universe as u

# 1. Live-Abruf: muss >= 400 Titel liefern und den Cache schreiben
tickers = u.get_sp500_tickers()
info = u.get_universe_info()
print(f"Live: {info['source']} / {info['n']} Titel")
assert info["source"] == "wikipedia" and info["n"] >= 400, f"Live-Abruf degradiert: {info}"
assert os.path.exists(u._UNIVERSE_CACHE), "Universum-Cache nicht geschrieben"

# 2. Wikipedia kaputt -> Cache-Fallback
orig_url = u.SP500_WIKI_URL
u.SP500_WIKI_URL = "https://en.wikipedia.org/wiki/DoesNotExist_404_xyz"
t2 = u.get_sp500_tickers()
info2 = u.get_universe_info()
print(f"Wiki kaputt: {info2['source']} / {info2['n']} Titel")
assert info2["source"] == "cache" and info2["n"] >= 400, f"Cache-Fallback griff nicht: {info2}"
assert set(t2) == set(tickers), "Cache-Liste weicht von Live-Liste ab"

# 3. Wikipedia kaputt UND kein Cache -> Top-100-Fallback
cache_path = u._UNIVERSE_CACHE
backup = cache_path + ".bak"
os.replace(cache_path, backup)
try:
    t3 = u.get_sp500_tickers()
    info3 = u.get_universe_info()
    print(f"Ohne Cache: {info3['source']} / {info3['n']} Titel")
    # Die "Top-100"-Liste hat historisch 99 Eintraege — Quelle zaehlt, nicht die Zahl
    assert info3["source"] == "fallback" and 90 <= info3["n"] <= 110, f"Fallback kaputt: {info3}"
finally:
    os.replace(backup, cache_path)
    u.SP500_WIKI_URL = orig_url

print("ALLE CHECKS OK")
