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
    Speichert die heutigen Empfehlungen vollständig im Log.
    Existierende Einträge desselben Datums werden überschrieben.
    """
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
    }

    log = _load_log()
    log = [e for e in log if e.get("date") != today]
    log.append(entry)
    log.sort(key=lambda e: e["date"])

    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


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
        "tech_signals": tech.get("signals", {}),
        "fund_signals": fund.get("signals", {}),
        "indicators": raw_indicators,
        "metrics": raw_metrics,
        "rs_3m": rs.get("rs_3m"),
        "rs_6m": rs.get("rs_6m"),
        "upside_pct": upside.get("expected_upside_pct"),
        "upside_label": upside.get("upside_label"),
    }


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
