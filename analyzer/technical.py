"""
Gate 3 — Technische Analyse
Score muss >= config.TECHNICAL["min_score"] sein (Standard: 70%).
"""

import pandas as pd
import logging
from config import TECHNICAL
from analyzer.indicators import rsi as _rsi_val, rsi_series, macd, bollinger

logger = logging.getLogger(__name__)


def check_technical(hist: pd.DataFrame) -> dict:
    """
    hist: yfinance DataFrame mit Spalten Close, Volume

    Gibt zurück:
    {
        "passed": bool,
        "score": float,       # 0.0 – 1.0
        "signals": dict,      # Details zu jedem Signal
        "indicators": dict,   # Rohdaten für Charts
    }
    """
    result = {
        "passed": False,
        "score": 0.0,
        "signals": {},
        "indicators": {},
    }

    if hist is None or len(hist) < 50:
        return result

    try:
        close = hist["Close"].dropna()
        volume = hist["Volume"].dropna()

        # Gleitende Durchschnitte
        ma50 = close.rolling(50).mean().iloc[-1]
        ma200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
        price = close.iloc[-1]

        sig_above_ma50 = price > ma50
        sig_above_ma200 = (price > ma200) if ma200 is not None else False

        # RSI
        rsi_val = _rsi_val(close) or 50.0
        sig_rsi = TECHNICAL["rsi_min"] <= rsi_val <= TECHNICAL["rsi_max"]

        # MACD
        macd_line, signal_line, histogram = macd(close)
        sig_macd = (histogram.iloc[-1] > 0) and (macd_line.iloc[-1] > signal_line.iloc[-1])

        # Bollinger Bands
        bb_ma, bb_upper, bb_lower = bollinger(close)
        bb_pct = (price - bb_lower.iloc[-1]) / (bb_upper.iloc[-1] - bb_lower.iloc[-1] + 1e-9)
        sig_bb = bb_pct < TECHNICAL["bb_upper_pct"]

        # Volumen
        vol_avg = volume.rolling(TECHNICAL["volume_lookback"]).mean().iloc[-1]
        vol_recent = volume.iloc[-5:].mean()
        sig_volume = vol_recent >= vol_avg * TECHNICAL["volume_factor"]

        signals = {
            "Kurs über 50-Tage-MA": sig_above_ma50,
            "Kurs über 200-Tage-MA": sig_above_ma200,
            "RSI im optimalen Bereich": sig_rsi,
            "MACD bullisch": sig_macd,
            "Nicht überkauft (Bollinger)": sig_bb,
            "Erhöhtes Volumen": sig_volume,
        }

        score = sum(signals.values()) / len(signals)

        result["signals"] = signals
        result["score"] = round(score, 3)
        result["passed"] = score >= TECHNICAL["min_score"]
        result["indicators"] = {
            "close": close,
            "ma50": close.rolling(50).mean(),
            "ma200": close.rolling(200).mean() if len(close) >= 200 else None,
            "rsi": rsi_series(close),
            "macd_line": macd_line,
            "signal_line": signal_line,
            "histogram": histogram,
            "bb_upper": bb_upper,
            "bb_lower": bb_lower,
            "bb_ma": bb_ma,
            "rsi_value": round(rsi_val, 1),
            "bb_pct": round(bb_pct * 100, 1),
            "price": round(price, 2),
            "ma50_val": round(ma50, 2),
            "ma200_val": round(ma200, 2) if ma200 else None,
        }

    except Exception as e:
        logger.warning(f"Technische Analyse fehlgeschlagen: {e}")

    return result


