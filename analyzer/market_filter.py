"""
Gate 1 — Marktfilter
Prüft das globale Marktregime. Wenn dieser Gate nicht besteht,
werden KEINE Aktienempfehlungen ausgegeben.
"""

import yfinance as yf
import pandas as pd
import logging
from config import MARKET
from analyzer.strategy import evaluate_market
from analyzer.sessions import completed_bars, last_completed_session

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
        sp_hist = completed_bars(sp.history(period="1y"))
        if len(sp_hist) < 200 or sp_hist.index[-1].date() != last_completed_session():
            result["reason"] = "S&P500-Daten unvollständig oder veraltet"
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

        # VIX Daten — 3-Tage-Mittel glättet Eintages-Spikes
        vix = yf.Ticker("^VIX")
        vix_hist = completed_bars(vix.history(period="1mo"))
        if len(vix_hist) < 3 or vix_hist.index[-1].date() != last_completed_session():
            logger.warning("VIX-Daten fehlen oder sind veraltet — Marktfilter bleibt geschlossen")
            vix_level = None
        else:
            vix_level = float(vix_hist["Close"].tail(3).mean())
        result["vix"] = round(vix_level, 2) if vix_level is not None else None

        result.update(evaluate_market(float(sp_price), float(ma50), float(ma200), vix_level))
        result["data_as_of"] = str(sp_hist.index[-1].date())
        if not result["data_complete"]:
            result["reason"] = "Marktdaten unvollständig — keine neue Auswahl"
        elif not result["passed"]:
            result["reason"] = "VIX oder Abstand zum 50/200-Tage-Mittel außerhalb der Grenzen"
        elif result["warning"]:
            result["reason"] = "VIX erhöht — Marktrisiko beachten"

    except Exception as e:
        logger.error(f"Marktfilter-Fehler: {e}")
        result["reason"] = f"Fehler beim Abrufen der Marktdaten: {e}"

    return result
