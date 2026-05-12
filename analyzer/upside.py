"""
Berechnet das erwartete Upside-Potential einer Empfehlung als separate Kennzahl.
Unabhängig vom Konfidenz-Score — ergänzt "Wie sicher?" um "Wie viel?".

Drei Komponenten:
  1. ATR-basiert:      3 * ATR(14) / Kurs — technisches Kursziel
  2. 52-Wochen-Hoch:  (52w-Hoch - Kurs) / Kurs — Mean-Reversion-Potenzial
  3. Wachstum:        Mittelwert Umsatz-/Gewinnwachstum (fundamental)
"""

import pandas as pd

try:
    from config import UPSIDE as _UPSIDE_CFG
except Exception:
    _UPSIDE_CFG = {}

_W_ATR     = _UPSIDE_CFG.get("weight_atr", 0.40)
_W_52W     = _UPSIDE_CFG.get("weight_52w", 0.40)
_W_GROWTH  = _UPSIDE_CFG.get("weight_growth", 0.20)
_THR_HIGH  = _UPSIDE_CFG.get("threshold_high", 15.0)
_THR_MID   = _UPSIDE_CFG.get("threshold_mid", 7.0)


def compute_upside(
    hist,
    current_price: float | None,
    ma50: float | None,
    atr: float | None,
    metrics: dict | None,
) -> dict:
    """
    Berechnet das erwartete Upside.

    hist:          pandas DataFrame mit mindestens 'Close'-Spalte (52w-Daten)
    current_price: aktueller Kurs (USD)
    ma50:          50-Tage-Moving-Average (kann None sein)
    atr:           ATR(14)-Wert aus compute_exits (kann None sein)
    metrics:       Dict aus check_fundamental -> metrics (revenue_growth, earnings_growth etc.)

    Returns:
        {
            "upside_atr_pct":      float | None,
            "upside_52w_pct":      float | None,
            "upside_growth_pct":   float | None,
            "expected_upside_pct": float | None,
            "upside_label":        str,
        }
    """
    result = {
        "upside_atr_pct":      None,
        "upside_52w_pct":      None,
        "upside_growth_pct":   None,
        "expected_upside_pct": None,
        "upside_label":        "Unbekannt",
    }

    if not current_price or current_price <= 0:
        return result

    # ── 1. ATR-basiert ────────────────────────────────────────────────────────
    if atr and atr > 0:
        result["upside_atr_pct"] = round(3 * atr / current_price * 100, 2)

    # ── 2. 52-Wochen-Hoch ─────────────────────────────────────────────────────
    try:
        if hist is not None and len(hist) >= 20:
            close = hist["Close"] if hasattr(hist, "__getitem__") else None
            if close is not None and len(close) > 0:
                # DataFrame/Series: .max(); dict/list: max()
                high_52w = float(close.max() if hasattr(close, "max") else max(close))
                if high_52w > current_price:
                    result["upside_52w_pct"] = round(
                        (high_52w - current_price) / current_price * 100, 2
                    )
                else:
                    result["upside_52w_pct"] = 0.0
    except Exception:
        pass

    # ── 3. Wachstumserwartung (fundamental) ───────────────────────────────────
    try:
        m = metrics or {}
        growth_pcts = []
        for key in ("revenue_growth", "earnings_growth"):
            val = m.get(key)
            if val is None:
                continue
            if isinstance(val, str) and "%" in val:
                try:
                    val = float(val.replace("%", "").replace(",", ".").strip())
                except Exception:
                    continue
            elif isinstance(val, (int, float)):
                # yfinance liefert Dezimalwerte (0.08 = 8%)
                if abs(val) <= 1.5:
                    val = val * 100
            if isinstance(val, float) and 0 < val <= 200:
                growth_pcts.append(val)
        if growth_pcts:
            avg_growth = sum(growth_pcts) / len(growth_pcts)
            result["upside_growth_pct"] = round(min(avg_growth, 50.0), 2)
    except Exception:
        pass

    # ── 4. Gewichteter Mittelwert ─────────────────────────────────────────────
    components = [
        (_W_ATR,    result["upside_atr_pct"]),
        (_W_52W,    result["upside_52w_pct"]),
        (_W_GROWTH, result["upside_growth_pct"]),
    ]
    available = [(w, v) for w, v in components if v is not None]
    if available:
        total_w = sum(w for w, _ in available)
        weighted = sum(w * v for w, v in available) / total_w
        result["expected_upside_pct"] = round(weighted, 2)

    # ── 5. Label ──────────────────────────────────────────────────────────────
    u = result["expected_upside_pct"]
    if u is not None:
        if u >= _THR_HIGH:
            result["upside_label"] = "Hoch"
        elif u >= _THR_MID:
            result["upside_label"] = "Mittel"
        else:
            result["upside_label"] = "Gering"

    return result
