"""
Einmalige Migration: history/recommendations_log.json -> history/log/<YYYY-MM>.json

Idempotent und offline. Die Alt-Datei wird NICHT gelöscht — erst prüfen, dass
load_log() unverändert dieselben Einträge liefert, dann von Hand `git rm`.
(load_log() mergt beide Quellen, ein Doppellauf schadet also nicht.)

Verwendung:
    python -m scripts.migrate_recommendations_log
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from history.logger import LEGACY_LOG_FILE, SHARD_DIR, _load_shard, _json_default  # noqa: E402
from storage import write_json_atomic  # noqa: E402


def main() -> int:
    if not os.path.exists(LEGACY_LOG_FILE):
        print(f"Keine Alt-Datei gefunden ({LEGACY_LOG_FILE}) — nichts zu tun.")
        return 0

    entries = _load_shard(LEGACY_LOG_FILE)
    if not entries:
        print("Alt-Datei ist leer oder unlesbar — Abbruch (nichts geschrieben).")
        return 1

    by_month = defaultdict(dict)
    skipped = 0
    for entry in entries:
        d = entry.get("date")
        if not d or len(d) < 7:
            skipped += 1
            continue
        by_month[d[:7]][d] = entry

    print(f"Alt-Datei: {len(entries)} Einträge, {os.path.getsize(LEGACY_LOG_FILE) / 1e6:.2f} MB")
    if skipped:
        print(f"  {skipped} Einträge ohne gültiges Datum übersprungen")

    total_out = 0
    for month in sorted(by_month):
        path = os.path.join(SHARD_DIR, f"{month}.json")

        # Bereits vorhandene Shard-Einträge gewinnen (Idempotenz + kein Datenverlust,
        # falls seit der Migration schon ein neuer Scan gelaufen ist).
        merged = {e["date"]: e for e in _load_shard(path) if e.get("date")}
        for d, entry in by_month[month].items():
            merged.setdefault(d, entry)

        shard = [merged[d] for d in sorted(merged)]
        write_json_atomic(path, shard, default=_json_default)
        total_out += len(shard)
        print(f"  {month}.json  {len(shard):3d} Einträge  {os.path.getsize(path) / 1e6:.2f} MB")

    print(f"\n{total_out} Einträge in {len(by_month)} Shards geschrieben.")
    print("Prüfen:  python -c \"from history.logger import load_log; print(len(load_log()))\"")
    print(f"Danach:  git rm {os.path.relpath(LEGACY_LOG_FILE)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
