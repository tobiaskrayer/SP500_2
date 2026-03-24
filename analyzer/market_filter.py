"""
Gate 1 — Marktfilter
Prüft das globale Marktregime. Wenn dieser Gate nicht besteht,
werden KEINE Aktienempfehlungen ausgegeben.
"""

import yfinance as yf
import pandas as pd
import logging
from config import MARKET

logger = logging.getLogger(__name__)


def check_market() -> dict:
    """
    Gibt ein Dict zurück:
    {
        "passed": bool,        # True = Markt OK für Empfehlungen
        "warning": bool,       # True = Markt ist vorsichtig (VIX 20-25)
        "vix": float,
        "sp500_price": float,
        "sp500_ma50": float,
        "sp500_ma200": float,
        "sp500_above_ma50": bool,
        "sp500_above_ma200": bool,
        "sp500_hist": pd.Series,  # Kursverlauf für Chart
        "reason": str,         # Erklärung bei Nichtbestehen
    }
    """
    result = {
        "passed": False,
        "warning": False,
        "vix": None,
        "sp500_price": None,
        "sp500_ma50": None,
        "sp500_ma200": None,
        "sp500_above_ma50": False,
        "sp500_above_ma200": False,
        "sp500_hist": None,
        "reason": "",
    }

    try:
        # S&P500 Daten
        sp = yf.Ticker("^GSPC")
        sp_hist = sp.history(period="1y")
        if sp_hist.empty:
            result["reason"] = "Keine S&P500-Daten verfügbar"
            return result

        sp_close = sp_hist["Close"]
        sp_price = sp_close.iloc[-1]
        ma50 = sp_close.rolling(50).mean().iloc[-1]
        ma200 = sp_close.rolling(200).mean().iloc[-1]

        result["sp500_price"] = round(sp_price, 2)
        result["sp500_ma50"] = round(ma50, 2)
        result["sp500_ma200"] = round(ma200, 2)
        result["sp500_hist"] = sp_close
        result["sp500_above_ma50"] = sp_price >= ma50 * (1 - MARKET["sp500_below_50ma_pct"])
        result["sp500_above_ma200"] = sp_price >= ma200 * (1 - MARKET["sp500_below_200ma_pct"])

        # VIX Daten
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="5d")
        vix_level = vix_hist["Close"].iloc[-1] if not vix_hist.empty else 99
        result["vix"] = round(vix_level, 2)

        # Entscheidung
        reasons = []
        if vix_level > MARKET["vix_stop"]:
            reasons.append(f"VIX zu hoch ({vix_level:.1f} > {MARKET['vix_stop']})")
        if not result["sp500_above_ma200"]:
            reasons.append(f"S&P500 unter 200-Tage-MA ({sp_price:.0f} vs {ma200:.0f})")
        if not result["sp500_above_ma50"]:
            reasons.append(f"S&P500 stark unter 50-Tage-MA ({sp_price:.0f} vs {ma50:.0f})")

        if reasons:
            result["passed"] = False
            result["reason"] = " | ".join(reasons)
        else:
            result["passed"] = True
            result["warning"] = vix_level > MARKET["vix_max"]
            if result["warning"]:
                result["reason"] = f"VIX erhöht ({vix_level:.1f}) — vorsichtig handeln"

    except Exception as e:
        logger.error(f"Marktfilter-Fehler: {e}")
        result["reason"] = f"Fehler beim Abrufen der Marktdaten: {e}"

    return result
