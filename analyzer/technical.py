"""
Gate 3 — Technische Analyse
Score muss >= config.TECHNICAL["min_score"] sein (Standard: 70%).
"""

import pandas as pd
import numpy as np
import logging
from config import TECHNICAL

logger = logging.getLogger(__name__)


def _rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi.iloc[-1]


def _macd(close: pd.Series):
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def _bollinger(close: pd.Series, period: int = 20):
    ma = close.rolling(period).mean()
    std = close.rolling(period).std()
    upper = ma + 2 * std
    lower = ma - 2 * std
    return ma, upper, lower


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
        rsi_val = _rsi(close)
        sig_rsi = TECHNICAL["rsi_min"] <= rsi_val <= TECHNICAL["rsi_max"]

        # MACD
        macd_line, signal_line, histogram = _macd(close)
        sig_macd = (histogram.iloc[-1] > 0) and (macd_line.iloc[-1] > signal_line.iloc[-1])

        # Bollinger Bands
        bb_ma, bb_upper, bb_lower = _bollinger(close)
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
            "rsi": _compute_rsi_series(close),
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


def _compute_rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))
