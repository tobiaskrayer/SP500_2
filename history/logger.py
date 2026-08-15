"""
Historisierung der täglichen Scan-Empfehlungen.

Speicherung in Monats-Shards: history/log/<YYYY-MM>.json.

Warum geschnitten: Vorher lag alles in einer einzigen Datei, die bei jedem Scan
komplett neu geschrieben und von GitHub Actions committet wurde. Bei ~46 KB pro
Tag wäre sie nach einem Jahr ~13 MB groß gewesen — und jeder Tages-Commit hätte
diese 13 MB erneut in die Historie gelegt. Mit Monats-Shards wird nur der
laufende Monat angefasst (≤ 0,8 MB); abgeschlossene Monate ändern sich nie wieder
und liegen genau einmal im Objektspeicher.

load_log() liest zusätzlich eine noch vorhandene Alt-Datei
(history/recommendations_log.json) mit, damit nicht migrierte Checkouts weiterlaufen.
"""

import glob
import json
import os
import time
from datetime import date, datetime

from storage import write_json_atomic


def _json_default(obj):
    """Fallback-Serialisierung für numpy-Typen, die json nicht nativ kennt."""
    try:
        import numpy as np
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return None if np.isnan(obj) else float(obj)
    except ImportError:
        pass
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

SHARD_DIR = os.path.join(os.path.dirname(__file__), "log")
# Monolith aus der Zeit vor dem Sharding — wird nur noch gelesen.
LEGACY_LOG_FILE = os.path.join(os.path.dirname(__file__), "recommendations_log.json")


def _shard_path(date_str: str) -> str:
    """history/log/<YYYY-MM>.json für ein Datum im Format YYYY-MM-DD."""
    return os.path.join(SHARD_DIR, f"{date_str[:7]}.json")


def _shard_files() -> list[str]:
    return sorted(glob.glob(os.path.join(SHARD_DIR, "*.json")))


def log_fingerprint() -> tuple:
    """
    Billiger Fingerabdruck aller Log-Dateien ((Name, mtime, Größe), ...).

    Die Performance-Seite nutzt ihn als @st.cache_data-Key: ein frischer Scan
    ändert den Fingerabdruck und invalidiert den Cache sofort, statt bis zum
    TTL-Ablauf veraltete Zahlen zu zeigen.
    """
    out = []
    for path in _shard_files() + [LEGACY_LOG_FILE]:
        try:
            st = os.stat(path)
            out.append((os.path.basename(path), st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return tuple(out)


def append_scan_result(result: dict):
    """
    Speichert die heutigen Empfehlungen vollständig im Log.
    Existierende Einträge desselben Datums werden überschrieben.
    """
    # Datum aus dem Scan-Timestamp nehmen, Fallback auf heute
    ts = result.get("timestamp", "")
    try:
        today = datetime.fromisoformat(ts).strftime("%Y-%m-%d")
    except Exception:
        today = str(date.today())
    market = result.get("market", {})

    entry = {
        "date": today,
        "market_context": {
            "vix": market.get("vix"),
            "sp500_price": market.get("sp500_price"),
            "sp500_above_ma50": market.get("sp500_above_ma50"),
            "sp500_above_ma200": market.get("sp500_above_ma200"),
        },
        "recommendations": [
            _extract_recommendation(r)
            for r in result.get("recommendations", [])
        ],
        # Paralleler v2-Algorithmus — für den Live-/Out-of-Sample-Vergleich v1 vs v2.
        # Diese Datensätze sind bereits geslimmt (kein tech/fund-Detail), daher ein
        # kompakter Extractor. Ältere Log-Einträge haben dieses Feld nicht.
        "recommendations_v2": [
            _extract_v2_recommendation(r)
            for r in result.get("recommendations_v2", [])
        ],
    }

    # Nur den Shard des betroffenen Monats laden und neu schreiben.
    path = _shard_path(today)
    shard = [e for e in _load_shard(path) if e.get("date") != today]
    shard.append(entry)
    shard.sort(key=lambda e: e["date"])

    # Atomisch (tmp + os.replace): verhindert eine Race Condition, wenn Streamlit
    # gleichzeitig load_log() aufruft. Kompakt statt indent=2 — die Datei wird
    # täglich committet, Einrückung kostet ~38 % der Bytes ohne Gegenwert.
    write_json_atomic(path, shard, default=_json_default)


def _extract_recommendation(r: dict) -> dict:
    """Extrahiert alle relevanten Felder aus einem Scan-Ergebnis-Dict."""
    tech = r.get("tech", {})
    fund = r.get("fund", {})
    rs = r.get("rs", {})
    indicators = tech.get("indicators", {}) or {}
    metrics = fund.get("metrics", {}) or {}

    # Roh-Indikatorwerte (nur skalare, keine pandas-Objekte)
    raw_indicators = {
        "rsi": indicators.get("rsi_value"),
        "bb_pct": indicators.get("bb_pct"),
        "ma50": indicators.get("ma50_val"),
        "ma200": indicators.get("ma200_val"),
        "price": indicators.get("price"),
    }

    # Fundamentals-Rohwerte (aus metrics-Dict, das bereits formatierte Strings enthält)
    raw_metrics = {
        "pe": metrics.get("pe"),
        "revenue_growth": metrics.get("revenue_growth"),
        "profit_margin": metrics.get("profit_margin"),
        "debt_to_equity": metrics.get("debt_to_equity"),
        "sector": metrics.get("sector"),
    }

    upside = r.get("upside") or {}
    return {
        "ticker": r.get("ticker"),
        "sector": r.get("sector") or metrics.get("sector"),
        "price": r.get("price"),
        "combined_score": r.get("combined_score"),
        "confidence_label": r.get("confidence_label"),
        "tech_score": tech.get("score"),
        "fund_score": fund.get("score"),
        "tech_signals": {k: bool(v) for k, v in tech.get("signals", {}).items()},
        "fund_signals": {k: bool(v) for k, v in fund.get("signals", {}).items()},
        "indicators": raw_indicators,
        "metrics": raw_metrics,
        "rs_3m": rs.get("rs_3m"),
        "rs_6m": rs.get("rs_6m"),
        "upside_pct": upside.get("expected_upside_pct"),
        "upside_label": upside.get("upside_label"),
    }


def _extract_v2_recommendation(r: dict) -> dict:
    """
    Kompakter Datensatz für v2-Parallelempfehlungen. r ist bereits geslimmt
    (siehe scorer._slim), enthält also kein tech/fund-Detail — für den
    Performance-Vergleich genügen Ticker, Einstiegskurs und Score-Metadaten.
    """
    rs = r.get("rs", {}) or {}
    return {
        "ticker": r.get("ticker"),
        "sector": r.get("sector"),
        "price": r.get("price"),
        "combined_score": r.get("combined_score"),
        "confidence_label": r.get("confidence_label"),
        "tech_score": r.get("tech_score"),
        "fund_score": r.get("fund_score"),
        "rs_3m": rs.get("rs_3m"),
        "rs_6m": rs.get("rs_6m"),
        # Top-N-Rang (1..10) — erlaubt Out-of-Sample-Vergleich Top-5 vs Top-10
        "v2_rank": r.get("v2_rank"),
        "macd_bull": r.get("macd_bull"),
    }


def load_log() -> list[dict]:
    """
    Gibt alle Log-Einträge zurück (älteste zuerst).

    Mergt die Monats-Shards mit einer eventuell noch vorhandenen Alt-Datei.
    Bei doppeltem Datum gewinnt der Shard — dadurch ist die Migration in beide
    Richtungen gefahrlos und ein nicht migrierter Checkout läuft normal weiter.
    """
    by_date: dict[str, dict] = {}
    for entry in _load_shard(LEGACY_LOG_FILE):
        if entry.get("date"):
            by_date[entry["date"]] = entry
    for path in _shard_files():
        for entry in _load_shard(path):
            if entry.get("date"):
                by_date[entry["date"]] = entry
    return [by_date[d] for d in sorted(by_date)]


def _load_shard(path: str) -> list[dict]:
    """Liest eine Log-Datei. Leere Liste, wenn sie fehlt oder unlesbar ist."""
    if not os.path.exists(path):
        return []
    for attempt in range(3):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, ValueError):
            # Datei könnte gerade geschrieben werden — kurz warten
            if attempt < 2:
                time.sleep(0.2)
        except Exception:
            break
    return []
