"""
Zentrale Indikator-Bibliothek.
Beide Gate-3 (technical.py) und Exit-Signale (exits.py) importieren von hier,
um Drift durch doppelten Code zu vermeiden.

RSI verwendet Wilder-Glättung (Standard in allen Charting-Tools).
ATR bleibt bei einfachem Rolling-Mean (bewussste Entscheidung: Wilder-ATR würde
alle getunten Stop-Loss/Take-Profit-Werte verschieben).
"""

import pandas as pd
import numpy as np


# ── RSI ───────────────────────────────────────────────────────────────────────

def rsi(close: pd.Series, period: int = 14) -> float | None:
    """RSI (letzter Wert) mit Wilder-Glättung."""
    val = rsi_series(close, period).iloc[-1]
    return float(val) if not pd.isna(val) else None


def rsi_series(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI als vollständige Series mit Wilder-Glättung (ewm alpha=1/period)."""
    if len(close) < period + 1:
        return pd.Series([float("nan")] * len(close), index=close.index)
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = gain / loss.replace(0, float("nan"))
    return 100 - (100 / (1 + rs))


# ── MACD ──────────────────────────────────────────────────────────────────────

def macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Gibt (macd_line, signal_line, histogram) zurück."""
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def macd_sustained_bearish(close: pd.Series, days: int = 3) -> bool:
    """True wenn MACD mindestens `days` Handelstage in Folge unter der Signallinie."""
    if len(close) < 35 + days:
        return False
    macd_line, signal_line, _ = macd(close)
    if len(macd_line) < days:
        return False
    return all(float(macd_line.iloc[-i]) < float(signal_line.iloc[-i]) for i in range(1, days + 1))


# ── Bollinger Bands ───────────────────────────────────────────────────────────

def bollinger(
    close: pd.Series,
    period: int = 20,
    std: int = 2,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Gibt (ma, upper, lower) zurück."""
    ma = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    return ma, ma + std * sigma, ma - std * sigma


def bb_position(close: pd.Series, period: int = 20, std: int = 2) -> float | None:
    """Kursposition im Bollinger-Band: 0 = unteres Band, 1 = oberes Band."""
    if len(close) < period:
        return None
    _, upper, lower = bollinger(close, period, std)
    u, l = upper.iloc[-1], lower.iloc[-1]
    if pd.isna(u) or pd.isna(l) or (u - l) == 0:
        return None
    return float((close.iloc[-1] - l) / (u - l))


# ── ATR ───────────────────────────────────────────────────────────────────────

def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    """ATR(14) mit einfachem Rolling-Mean (bewusst nicht Wilder, um Stops stabil zu halten)."""
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if not pd.isna(val) else float(tr.mean())
