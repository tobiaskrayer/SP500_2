"""
Historisierung der täglichen Scan-Empfehlungen.
Hängt bei jedem Scan einen Eintrag an history/recommendations_log.json an.
"""

import json
import os
from datetime import date

LOG_FILE = os.path.join(os.path.dirname(__file__), "recommendations_log.json")


def append_scan_result(result: dict):
    """
    Speichert die heutigen Empfehlungen (Ticker, Preis, combined_score) im Log.
    Existierende Einträge desselben Datums werden überschrieben.
    """
    today = str(date.today())
    entry = {
        "date": today,
        "recommendations": [
            {
                "ticker": r["ticker"],
                "price": r.get("price"),
                "combined_score": r.get("combined_score"),
                "confidence_label": r.get("confidence_label"),
            }
            for r in result.get("recommendations", [])
        ],
    }

    log = _load_log()
    # Vorhandenen Eintrag desselben Datums ersetzen
    log = [e for e in log if e.get("date") != today]
    log.append(entry)
    # Chronologisch sortieren
    log.sort(key=lambda e: e["date"])

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def load_log() -> list[dict]:
    """Gibt alle Log-Einträge zurück (älteste zuerst)."""
    return _load_log()


def _load_log() -> list[dict]:
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []
