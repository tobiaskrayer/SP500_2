"""
Konfidenz-Ranking für empfohlene Aktien.
Berechnet einen combined_score aus tech_score, fund_score und relativer Stärke.
Wenn VIX > MARKET["vix_max"] (erhöhtes Regime), werden Fundamentals stärker
und technische Signale schwächer gewichtet — Quality over Momentum.
Die 4-Gate-Logik (recommended-Flag) bleibt unverändert.
"""

import numpy as np

try:
    from config import CONFIDENCE, REGIME, MARKET
except ImportError:
    CONFIDENCE = {"strong_buy_threshold": 0.85, "moderate_buy_threshold": 0.70}
    REGIME = {
        "normal":   {"w_tech": 0.40, "w_fund": 0.40, "w_rs": 0.20},
        "elevated": {"w_tech": 0.30, "w_fund": 0.45, "w_rs": 0.25},
    }
    MARKET = {"vix_max": 20}


def compute_confidence(tech_score: float, fund_score: float, rs: dict,
                       vix: float = None) -> dict:
    """
    Berechnet combined_score und confidence_label aus vorhandenen Gate-Ergebnissen.

    rs erwartet Felder rs_3m und rs_6m (Outperformance vs. S&P500 in Prozent).
    vix: aktueller VIX-Wert — bestimmt das Gewichtungsregime.
    Gibt zurück: {"combined_score": float, "confidence_label": str, "regime": str}
    """
    rs_3m = rs.get("rs_3m", 0) or 0
    rs_6m = rs.get("rs_6m", 0) or 0

    # RS-Stärke: normiert auf [0,1], 10% Outperformance in beiden Perioden = 1.0
    rs_strength = float(np.clip((rs_3m + rs_6m) / 20.0, 0.0, 1.0))

    # Regime bestimmen
    vix_max = MARKET.get("vix_max", 20)
    if vix is not None and vix > vix_max:
        weights = REGIME["elevated"]
        regime = "elevated"
    else:
        weights = REGIME["normal"]
        regime = "normal"

    combined = (
        weights["w_tech"] * (tech_score or 0)
        + weights["w_fund"] * (fund_score or 0)
        + weights["w_rs"] * rs_strength
    )

    if combined >= CONFIDENCE["strong_buy_threshold"]:
        label = "Strong Buy"
    elif combined >= CONFIDENCE["moderate_buy_threshold"]:
        label = "Moderate Buy"
    else:
        label = "Watch"

    return {
        "combined_score": round(combined, 4),
        "confidence_label": label,
        "regime": regime,
    }
