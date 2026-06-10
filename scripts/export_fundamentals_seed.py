"""
Exportiert den Fundamentals-Laufzeit-Cache als git-getrackten Seed.

Wird von GitHub Actions nach dem täglichen Scan ausgeführt (daily_analysis.yml):
der Scan füllt cache/fundamentals.json (gitignored), dieses Skript merged ihn
über den bestehenden Seed (cache/fundamentals_seed.json) und committed wird der
Seed mit dem ohnehin stattfindenden Tages-Commit — kein zusätzlicher Redeploy.

Pruning: Einträge älter als die Cache-TTL fliegen raus — die könnte die App
ohnehin nie verwenden, sie wären totes Gewicht im Repo.

Ausführen:  python -X utf8 -m scripts.export_fundamentals_seed
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyzer.fundamentals_cache import _CACHE_FILE, _SEED_FILE, _TTL_DAYS


def main():
    def _read(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    seed = _read(_SEED_FILE)
    runtime = _read(_CACHE_FILE)

    merged = {**seed, **runtime}   # Laufzeit-Daten gewinnen (frischer)
    cutoff = time.time() - _TTL_DAYS * 86400
    merged = {t: e for t, e in merged.items() if e.get("ts", 0) >= cutoff}

    os.makedirs(os.path.dirname(_SEED_FILE), exist_ok=True)
    tmp = _SEED_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(merged, f, ensure_ascii=False)
    os.replace(tmp, _SEED_FILE)

    print(f"Seed exportiert: {len(merged)} Ticker "
          f"(Laufzeit: {len(runtime)}, alter Seed: {len(seed)})")


if __name__ == "__main__":
    main()
