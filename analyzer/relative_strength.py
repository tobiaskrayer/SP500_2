"""
Gate 2 — Relative Stärke
Aktie muss den S&P500 in beiden Zeiträumen (3M + 6M) outperformen.
"""

import pandas as pd
import logging
from config import RELATIVE_STRENGTH

logger = logging.getLogger(__name__)


def check_relative_strength(stock_hist: pd.Series, sp500_hist: pd.Series) -> dict:
    """
    stock_hist, sp500_hist: pandas Series mit Schlusskursen (DatetimeIndex)

    Gibt zurück:
    {
        "passed": bool,
        "rs_3m": float,   # relative Performance über 3 Monate (positiv = outperform)
        "rs_6m": float,
        "stock_3m": float,
        "stock_6m": float,
        "sp500_3m": float,
        "sp500_6m": float,
    }
    """
    result = {
        "passed": False,
        "rs_3m": None,
        "rs_6m": None,
        "stock_3m": None,
        "stock_6m": None,
        "sp500_3m": None,
        "sp500_6m": None,
    }

    try:
        short = RELATIVE_STRENGTH["period_short_days"]
        long = RELATIVE_STRENGTH["period_long_days"]

        def perf(series: pd.Series, days: int) -> float | None:
            if len(series) < days + 1:
                return None
            return (series.iloc[-1] / series.iloc[-days] - 1) * 100

        stock_3m = perf(stock_hist, short)
        stock_6m = perf(stock_hist, long)
        sp_3m = perf(sp500_hist, short)
        sp_6m = perf(sp500_hist, long)

        if None in (stock_3m, stock_6m, sp_3m, sp_6m):
            return result

        rs_3m = stock_3m - sp_3m
        rs_6m = stock_6m - sp_6m

        result["rs_3m"] = round(rs_3m, 2)
        result["rs_6m"] = round(rs_6m, 2)
        result["stock_3m"] = round(stock_3m, 2)
        result["stock_6m"] = round(stock_6m, 2)
        result["sp500_3m"] = round(sp_3m, 2)
        result["sp500_6m"] = round(sp_6m, 2)
        result["passed"] = rs_3m > 0 and rs_6m > 0

    except Exception as e:
        logger.warning(f"RS-Berechnung fehlgeschlagen: {e}")

    return result
