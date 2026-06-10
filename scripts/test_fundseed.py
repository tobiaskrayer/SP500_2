"""Test: Seed-Fallback des Fundamentals-Caches + Export-Merge."""
import sys
import os
import json
import time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import analyzer.fundamentals_cache as fc

# Frischer Zustand
for p in (fc._CACHE_FILE, fc._SEED_FILE):
    if os.path.exists(p):
        os.remove(p)
fc._cache = None
fc._seed = None

# Seed mit einem Fake-Ticker anlegen (frisch) + einem abgelaufenen
now = time.time()
seed = {
    "FAKE_FRESH": {"ts": now - 3600, "info": {"trailingPE": 12.3, "longName": "Fresh Corp"}},
    "FAKE_STALE": {"ts": now - 10 * 86400, "info": {"trailingPE": 99.0, "longName": "Stale Corp"}},
}
os.makedirs(os.path.dirname(fc._SEED_FILE), exist_ok=True)
with open(fc._SEED_FILE, "w", encoding="utf-8") as f:
    json.dump(seed, f)

# 1. Frischer Seed-Eintrag: muss ohne Netz-Fetch zurueckkommen
t0 = time.time()
info = fc.get_info_cached("FAKE_FRESH")
assert info.get("longName") == "Fresh Corp", f"Seed-Hit fehlgeschlagen: {info}"
assert time.time() - t0 < 0.5, "Seed-Hit hat Netz kontaktiert?"
print("Seed-Hit OK (ohne Netz)")

# 2. Durchschreiben: Eintrag muss jetzt im Laufzeit-Cache liegen
with fc._lock:
    assert "FAKE_FRESH" in fc._load(), "Seed-Hit nicht in Laufzeit-Cache uebernommen"
print("Write-Through OK")

# 3. Abgelaufener Seed-Eintrag: darf NICHT verwendet werden.
#    (Fake-Ticker -> yfinance liefert nichts -> leeres Dict, nicht 'Stale Corp')
info = fc.get_info_cached("FAKE_STALE")
assert info.get("longName") != "Stale Corp", "Abgelaufener Seed-Eintrag wurde verwendet!"
print("TTL auf Seed OK (abgelaufen ignoriert)")

# 4. Export-Merge: Laufzeit gewinnt; Eintraege aelter als TTL fliegen raus.
#    FAKE_OLD liegt nur im Seed (4 Tage alt > TTL 3 Tage) -> muss verschwinden.
with open(fc._SEED_FILE, "r", encoding="utf-8") as f:
    cur_seed = json.load(f)
cur_seed["FAKE_OLD"] = {"ts": now - 4 * 86400, "info": {"longName": "Old Corp"}}
with open(fc._SEED_FILE, "w", encoding="utf-8") as f:
    json.dump(cur_seed, f)
with fc._lock:
    fc._load()["FAKE_FRESH"] = {"ts": now, "info": {"longName": "Fresh Corp v2"}}
    fc._save()
from scripts.export_fundamentals_seed import main as export_main
export_main()
with open(fc._SEED_FILE, "r", encoding="utf-8") as f:
    new_seed = json.load(f)
assert new_seed["FAKE_FRESH"]["info"]["longName"] == "Fresh Corp v2", "Merge: Laufzeit gewinnt nicht"
assert "FAKE_OLD" not in new_seed, "Pruning entfernt abgelaufene Eintraege nicht"
print("Export-Merge + Pruning OK")

# Aufraeumen (Fake-Daten nicht liegen lassen)
for p in (fc._CACHE_FILE, fc._SEED_FILE):
    if os.path.exists(p):
        os.remove(p)
print("ALLE CHECKS OK")
