"""
Exit-Signale und Stop-Loss/Take-Profit-Vorschläge.
Wird additiv zu empfohlenen Aktien und Portfolio-Positionen berechnet.
Die 4-Gate-Filterlogik bleibt unverändert.
"""

import pandas as pd
import numpy as np
from config import EXITS


def compute_exits(hist: pd.DataFrame, entry_price: float = None) -> dict:
    """
    Berechnet ATR-basierte Stop-Loss/Take-Profit-Vorschläge und Exit-Signale
    aus dem übergebenen hist-DataFrame (OHLCV).

    entry_price: Kaufkurs (für SL/TP). Falls None, wird der aktuelle Kurs verwendet.

    Gibt zurück:
    {
        "atr": float,
        "stop_loss": float | None,
        "take_profit": float | None,
        "signals": dict[str, bool],   # aktive Exit-Signale
        "signal_count": int,
        "recommendation": str,        # "Halten" / "Beobachten" / "Verkaufen erwägen"
    }
    """
    if hist is None or len(hist) < 15:
        return _empty_exits()

    close = hist["Close"]
    high = hist["High"]
    low = hist["Low"]

    current_price = float(close.iloc[-1])
    use_entry = entry_price if entry_price is not None else current_price

    # ATR(14)
    atr = _compute_atr(high, low, close, period=14)

    # Stop-Loss und Take-Profit
    sl_atr = use_entry - EXITS["atr_stop_multiplier"] * atr
    ma50 = close.rolling(50).mean().iloc[-1]
    stop_loss = float(min(sl_atr, ma50)) if not pd.isna(ma50) else float(sl_atr)
    take_profit = float(use_entry + EXITS["atr_target_multiplier"] * atr)

    # Exit-Signale berechnen
    signals = {}

    # 1. Kurs unter MA50
    signals["Kurs unter 50-Tage-MA"] = bool(not pd.isna(ma50) and current_price < float(ma50))

    # 2. RSI überkauft
    rsi_val = _compute_rsi(close)
    signals[f"RSI überkauft (>{EXITS['rsi_overbought']})"] = bool(
        rsi_val is not None and rsi_val > EXITS["rsi_overbought"]
    )

    # 3. MACD bearish crossover (MACD-Linie kreuzt unter Signallinie)
    signals["MACD bearish Crossover"] = _macd_bearish(close)

    # 4. Bollinger-Band oben (≥ exit-Schwelle)
    bb_pct = _bb_position(close)
    signals[f"Am oberen Bollinger-Band (≥{int(EXITS['bb_exit_pct']*100)}%)"] = bool(
        bb_pct is not None and bb_pct >= EXITS["bb_exit_pct"]
    )

    # 5. 6M-Relative Stärke negativ — wird extern gesetzt, hier Platzhalter False
    # (wird in scorer.py nach RS-Check gesetzt)
    signals["6M-Relative Stärke negativ"] = False

    signal_count = sum(1 for v in signals.values() if v)

    if signal_count >= EXITS["sell_signals"]:
        recommendation = "Verkaufen erwägen"
    elif signal_count >= EXITS["warn_signals"]:
        recommendation = "Beobachten"
    else:
        recommendation = "Halten"

    return {
        "atr": round(atr, 4),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "signals": signals,
        "signal_count": signal_count,
        "recommendation": recommendation,
    }


def _empty_exits() -> dict:
    return {
        "atr": None,
        "stop_loss": None,
        "take_profit": None,
        "signals": {},
        "signal_count": 0,
        "recommendation": "Keine Daten",
    }


def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> float:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return float(atr) if not pd.isna(atr) else float(tr.mean())


def _compute_rsi(close: pd.Series, period: int = 14) -> float | None:
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if not pd.isna(val) else None


def _macd_bearish(close: pd.Series) -> bool:
    if len(close) < 35:
        return False
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    # Bearish crossover: im vorletzten Bar war MACD über Signal, jetzt darunter
    if len(macd) < 2:
        return False
    was_above = float(macd.iloc[-2]) >= float(signal.iloc[-2])
    now_below = float(macd.iloc[-1]) < float(signal.iloc[-1])
    return bool(was_above and now_below)


def _bb_position(close: pd.Series, period: int = 20, std: int = 2) -> float | None:
    if len(close) < period:
        return None
    ma = close.rolling(period).mean()
    upper = ma + std * close.rolling(period).std()
    lower = ma - std * close.rolling(period).std()
    u = upper.iloc[-1]
    l = lower.iloc[-1]
    if pd.isna(u) or pd.isna(l) or (u - l) == 0:
        return None
    return float((close.iloc[-1] - l) / (u - l))
