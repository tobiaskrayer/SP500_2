"""
Exit-Signale und Stop-Loss/Take-Profit-Vorschläge.
Wird additiv zu empfohlenen Aktien und Portfolio-Positionen berechnet.
Die 4-Gate-Filterlogik bleibt unverändert.
"""

import pandas as pd
import numpy as np

try:
    from config import EXITS
except ImportError:
    EXITS = {
        "atr_stop_multiplier": 2.0,
        "atr_target_multiplier": 3.0,
        "rsi_overbought": 75,
        "bb_exit_pct": 0.95,
        "macd_bearish_days": 3,
        "trailing_drawdown_pct": 0.15,
        "warn_signals": 1,
        "sell_signals": 3,
    }


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

    # 3. MACD ≥ N Tage unter Signallinie (robuster als einmaliger Crossover)
    macd_days = EXITS.get("macd_bearish_days", 3)
    signals[f"MACD {macd_days}+ Tage bearish"] = _macd_sustained_bearish(close, days=macd_days)

    # 4. Bollinger-Band oben (≥ exit-Schwelle)
    bb_pct = _bb_position(close)
    signals[f"Am oberen Bollinger-Band (≥{int(EXITS['bb_exit_pct']*100)}%)"] = bool(
        bb_pct is not None and bb_pct >= EXITS["bb_exit_pct"]
    )

    # 5. Trailing Drawdown: Kurs ≥ X% unter 50-Tage-Hoch
    dd_pct = EXITS.get("trailing_drawdown_pct", 0.15)
    signals[f"Trailing Drawdown (≥{int(dd_pct*100)}% vom 50T-Hoch)"] = _trailing_drawdown(
        close, threshold=dd_pct
    )

    # 6. 6M-Rendite negativ (Kurs tiefer als vor 6 Monaten)
    # In scorer.py wird dieses Feld ggf. mit RS-Vergleich gegen S&P500 überschrieben
    signals["6M-Rendite negativ"] = _rs_negative_6m(close)

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


def _macd_sustained_bearish(close: pd.Series, days: int = 3) -> bool:
    """MACD liegt mindestens `days` Handelstage in Folge unter der Signallinie."""
    if len(close) < 35 + days:
        return False
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    if len(macd) < days:
        return False
    return all(float(macd.iloc[-i]) < float(signal.iloc[-i]) for i in range(1, days + 1))


def _trailing_drawdown(close: pd.Series, lookback: int = 50, threshold: float = 0.15) -> bool:
    """Kurs ist mindestens `threshold` % unter dem Hoch der letzten `lookback` Tage."""
    n = min(lookback, len(close))
    recent_high = float(close.iloc[-n:].max())
    if recent_high <= 0:
        return False
    drawdown = (recent_high - float(close.iloc[-1])) / recent_high
    return drawdown >= threshold


def _rs_negative_6m(close: pd.Series) -> bool:
    """Kurs liegt tiefer als vor ~6 Monaten (126 Handelstage)."""
    if len(close) < 63:
        return False
    lookback = min(126, len(close) - 1)
    return float(close.iloc[-1]) < float(close.iloc[-lookback])


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
