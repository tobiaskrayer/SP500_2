"""
Exit-Signale und Stop-Loss/Take-Profit-Vorschläge.
Wird additiv zu empfohlenen Aktien und Portfolio-Positionen berechnet.
Die 4-Gate-Filterlogik bleibt unverändert.
"""

import pandas as pd

from analyzer.indicators import rsi as _ind_rsi, macd_sustained_bearish, bb_position, atr as _ind_atr

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


def compute_exits(hist: pd.DataFrame, entry_price: float = None,
                  avg_entry_price: float = None, vix: float = None) -> dict:
    """
    Berechnet ATR-basierte Stop-Loss/Take-Profit-Vorschläge und Exit-Signale
    aus dem übergebenen hist-DataFrame (OHLCV).

    entry_price:     Kaufkurs (historisch, für Rückwärtskompatibilität).
    avg_entry_price: Durchschnittlicher Einstandskurs (USD) über alle Lots.
                     Aktiviert Tier-basierte Trailing-Stop-Logik:
                       <+5%  P&L → initialer ATR-Stop unter Einstand
                       +5-15% P&L → Break-Even-Stop (am Einstandskurs)
                       >+15% P&L → Trailing-Stop vom aktuellen Kurs (nie unter Break-Even)

    Take-Profit ist immer dynamisch: aktueller Kurs + ATR×3.

    Gibt zurück:
    {
        "atr": float,
        "stop_loss": float | None,
        "take_profit": float | None,
        "stop_label": str,            # erklärender Text zur Stop-Stufe
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
    ma50 = close.rolling(50).mean().iloc[-1]

    # ATR(14) — roh für die Anzeige, gekappt für Berechnungen
    atr = _ind_atr(high, low, close, period=14)
    # Volatilitäts-Cap: verhindert übermäßig weite Stop/TP durch Spike-ATR
    atr_calc = min(atr, current_price * 0.06)

    # Stop-Loss und Take-Profit: Tier-basiert wenn avg_entry_price bekannt
    if avg_entry_price is not None and avg_entry_price > 0:
        pnl_pct = (current_price - avg_entry_price) / avg_entry_price
        sl_trailing = current_price - EXITS["atr_stop_multiplier"] * atr_calc
        sl_initial = avg_entry_price - EXITS["atr_stop_multiplier"] * atr_calc

        if pnl_pct >= 0.15:
            # Trailing: nie unter Einstand absinken lassen
            stop_loss = float(max(sl_trailing, avg_entry_price))
            stop_label = "Trailing Stop (>15% im Plus) — zieht mit dem Kurs nach"
        elif pnl_pct >= 0.05:
            stop_loss = float(avg_entry_price)
            stop_label = "Break-Even Stop (+5–15% im Plus) — Einstand absichern"
        else:
            stop_loss = float(sl_initial)
            stop_label = "Initialer Stop (unter Einstand) — unter 5% Gewinn"

        # Take-Profit vom Einstandskurs (Option 2); mindestens 1×ATR über aktuellem Kurs
        tp_from_entry = avg_entry_price + EXITS["atr_target_multiplier"] * atr_calc
        take_profit = float(max(tp_from_entry, current_price + atr_calc))
    else:
        # Fallback: klassisch vom aktuellen Kurs
        use_entry = entry_price if entry_price is not None else current_price
        stop_loss = float(use_entry - EXITS["atr_stop_multiplier"] * atr_calc)
        stop_label = "ATR-Stop (kein Einstandskurs hinterlegt)"
        take_profit = float(current_price + EXITS["atr_target_multiplier"] * atr_calc)

    # Regime-abhängige Schwellen: bei erhöhtem VIX früher aussteigen
    try:
        from config import MARKET as _MARKET
        _vix_max = _MARKET.get("vix_max", 20)
    except ImportError:
        _vix_max = 20
    _elevated = vix is not None and vix > _vix_max
    dd_pct = EXITS.get("trailing_drawdown_pct_elevated", 0.10) if _elevated else EXITS.get("trailing_drawdown_pct", 0.15)
    sell_threshold = EXITS.get("sell_signals_elevated", 2) if _elevated else EXITS["sell_signals"]

    # Exit-Signale berechnen
    signals = {}

    # 1. Kurs unter MA50
    signals["Kurs unter 50-Tage-MA"] = bool(not pd.isna(ma50) and current_price < float(ma50))

    # 2. RSI überkauft
    rsi_val = _ind_rsi(close)
    signals[f"RSI überkauft (>{EXITS['rsi_overbought']})"] = bool(
        rsi_val is not None and rsi_val > EXITS["rsi_overbought"]
    )

    # 3. MACD ≥ N Tage unter Signallinie (robuster als einmaliger Crossover)
    macd_days = EXITS.get("macd_bearish_days", 3)
    signals[f"MACD {macd_days}+ Tage bearish"] = macd_sustained_bearish(close, days=macd_days)

    # 4. Bollinger-Band oben (≥ exit-Schwelle)
    bb_pct = bb_position(close)
    signals[f"Am oberen Bollinger-Band (≥{int(EXITS['bb_exit_pct']*100)}%)"] = bool(
        bb_pct is not None and bb_pct >= EXITS["bb_exit_pct"]
    )

    # 5. Trailing Drawdown: Kurs ≥ X% unter 50-Tage-Hoch (Schwelle regime-abhängig)
    signals[f"Trailing Drawdown (≥{int(dd_pct*100)}% vom 50T-Hoch)"] = _trailing_drawdown(
        close, threshold=dd_pct
    )

    # 6. 6M-Rendite negativ (Kurs tiefer als vor 6 Monaten)
    # In scorer.py wird dieses Feld ggf. mit RS-Vergleich gegen S&P500 überschrieben
    signals["6M-Rendite negativ"] = _rs_negative_6m(close)

    # 7. Marktumfeld bearish/warning — wird extern gesetzt (scorer.py / manager.py)
    signals["Marktumfeld bearish"] = False

    signal_count = sum(1 for v in signals.values() if v)

    if signal_count >= sell_threshold:
        recommendation = "Verkaufen erwägen"
    elif signal_count >= EXITS["warn_signals"]:
        recommendation = "Beobachten"
    else:
        recommendation = "Halten"

    return {
        "atr": round(atr, 4),
        "stop_loss": round(stop_loss, 2),
        "take_profit": round(take_profit, 2),
        "stop_label": stop_label,
        "signals": signals,
        "signal_count": signal_count,
        "recommendation": recommendation,
    }


def inject_external_signals(exits: dict, sell_threshold: int = None, **signals: bool) -> dict:
    """
    Setzt externe Signale (RS, Markt) und berechnet signal_count + recommendation neu.
    sell_threshold überschreibt EXITS["sell_signals"] (für Regime-Bewusstsein).
    Gibt das exits-Dict zurück (in-place modifiziert).
    """
    if not exits.get("signals"):
        return exits
    for key, val in signals.items():
        exits["signals"][key] = bool(val)
    exits["signal_count"] = sum(1 for v in exits["signals"].values() if v)
    threshold = sell_threshold if sell_threshold is not None else EXITS["sell_signals"]
    if exits["signal_count"] >= threshold:
        exits["recommendation"] = "Verkaufen erwägen"
    elif exits["signal_count"] >= EXITS["warn_signals"]:
        exits["recommendation"] = "Beobachten"
    else:
        exits["recommendation"] = "Halten"
    return exits


def _empty_exits() -> dict:
    return {
        "atr": None,
        "stop_loss": None,
        "take_profit": None,
        "stop_label": None,
        "signals": {},
        "signal_count": 0,
        "recommendation": "Keine Daten",
    }


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
