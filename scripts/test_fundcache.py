"""Smoke-Test: Fundamentals-Cache (Miss -> Netz, Hit -> lokal, TTL)."""
import sys
import os
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import analyzer.fundamentals_cache as fc

# Frischer Zustand fuer den Test
if os.path.exists(fc._CACHE_FILE):
    os.remove(fc._CACHE_FILE)
fc._cache = None

t0 = time.time()
info1 = fc.get_info_cached("AAPL")
t_miss = time.time() - t0
assert info1.get("trailingPE") or info1.get("marketCap"), f"Leere info: {info1}"
print(f"Miss (Netz): {t_miss:.2f}s — Felder: {sorted(info1.keys())}")

t0 = time.time()
info2 = fc.get_info_cached("AAPL")
t_hit = time.time() - t0
assert info2 == info1, "Hit liefert andere Daten als Miss"
assert t_hit < 0.05, f"Hit zu langsam ({t_hit:.3f}s) — Cache greift nicht"
print(f"Hit (Cache): {t_hit*1000:.1f}ms")

# TTL: abgelaufener Eintrag wird neu geholt (Timestamp muss sich erneuern;
# Timing ist kein verlaessliches Signal, da yfinance prozessintern cached)
old_ts = time.time() - 10 * 86400
with fc._lock:
    fc._load()["AAPL"]["ts"] = old_ts
info3 = fc.get_info_cached("AAPL")
with fc._lock:
    new_ts = fc._load()["AAPL"]["ts"]
assert new_ts > old_ts + 9 * 86400, "Abgelaufener Eintrag wurde nicht neu geholt"
print("TTL-Refresh OK (Timestamp erneuert)")

# Persistenz: neue Instanz liest die Datei
fc._cache = None
t0 = time.time()
info4 = fc.get_info_cached("AAPL")
assert time.time() - t0 < 0.1, "Persistierter Cache greift nicht"
assert info4 == info3
print("Persistenz OK")

# check_fundamental akzeptiert das Subset
from analyzer.fundamental import check_fundamental
fund = check_fundamental(info4)
assert "score" in fund and fund["metrics"].get("name"), f"Gate 4 kaputt: {fund}"
print(f"Gate 4 mit Cache-Subset: score={fund['score']}, name={fund['metrics']['name']}")

print("ALLE CHECKS OK")
