"""Schnellcheck: enthaelt das juengste Scan-Ergebnis die v2-Raenge?"""
import glob
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

latest = sorted(glob.glob(os.path.join(os.path.dirname(__file__), "..", "cache", "results_*.json")))[-1]
with open(latest, encoding="utf-8") as f:
    r = json.load(f)

v2 = r.get("recommendations_v2") or []
print(f"Datei: {os.path.basename(latest)}")
print(f"Markt passed: {r.get('market', {}).get('passed')}")
print(f"v1-Empfehlungen: {len(r.get('recommendations') or [])}")
print(f"v2-Empfehlungen: {len(v2)}")
for x in v2:
    rank = x.get("v2_rank")
    star = "*" if (rank or 99) <= 5 else " "
    rs = (x.get("rs") or {}).get("rs_score")
    rs_s = f"{rs:.1f}" if rs is not None else "?"
    print(f"  {star} Rang {rank}: {x.get('ticker'):6} rs={rs_s} macd_bull={x.get('macd_bull')}")
