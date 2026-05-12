"""
Konfidenz-Ranking für empfohlene Aktien.
Berechnet einen combined_score aus tech_score, fund_score und relativer Stärke.
Die 4-Gate-Logik (recommended-Flag) bleibt unverändert.
"""

import numpy as np
from config import CONFIDENCE


def compute_confidence(tech_score: float, fund_score: float, rs: dict) -> dict:
    """
    Berechnet combined_score und confidence_label aus vorhandenen Gate-Ergebnissen.

    rs erwartet Felder rs_3m und rs_6m (Outperformance vs. S&P500 in Prozent).
    Gibt zurück: {"combined_score": float, "confidence_label": str}
    """
    rs_3m = rs.get("rs_3m", 0) or 0
    rs_6m = rs.get("rs_6m", 0) or 0

    # RS-Stärke: normiert auf [0,1], 10% Outperformance in beiden Perioden = 1.0
    rs_strength = float(np.clip((rs_3m + rs_6m) / 20.0, 0.0, 1.0))

    combined = 0.4 * (tech_score or 0) + 0.4 * (fund_score or 0) + 0.2 * rs_strength

    if combined >= CONFIDENCE["strong_buy_threshold"]:
        label = "Strong Buy"
    elif combined >= CONFIDENCE["moderate_buy_threshold"]:
        label = "Moderate Buy"
    else:
        label = "Watch"

    return {
        "combined_score": round(combined, 4),
        "confidence_label": label,
    }
