# ============================================================
#  Zentrale Konfiguration — alle Schwellenwerte hier anpassen
# ============================================================

# --- Gate 1: Marktfilter ---
MARKET = {
    "vix_max": 20,          # VIX über diesem Wert → Warnung
    "vix_stop": 25,         # VIX über diesem Wert → keine Empfehlungen
    "sp500_below_200ma_pct": 0.05,  # Max. Abstand unter 200-Tage-MA (5%)
    "sp500_below_50ma_pct": 0.05,   # Max. Abstand unter 50-Tage-MA (5%)
}

# --- Gate 2: Relative Stärke ---
RELATIVE_STRENGTH = {
    "period_short_days": 63,    # ~3 Monate
    "period_long_days": 126,    # ~6 Monate
    "rs_top_percentile": 0.33,  # Aktie muss zu den besten 33% nach RS-Score (rs_3m+rs_6m) zählen
    "rs_min_6m": 0.0,           # absoluter Floor: 6M-Momentum muss ≥ 0 sein
}

# --- Gate 3: Technische Analyse ---
TECHNICAL = {
    "rsi_min": 45,         # RSI nicht zu schwach
    "rsi_max": 70,         # RSI nicht überkauft
    "bb_upper_pct": 0.95,  # Kurs darf nicht über 95% des BB-Bandes sein
    "volume_lookback": 20, # Tage für Volumen-Durchschnitt
    "volume_factor": 1.2,  # Volumen muss mindestens 1.2x des Durchschnitts sein (echtes Interesse)
    "min_score": 0.70,     # Mindest-Score für Gate 3 (70%)
}

# --- Gate 4: Fundamentalanalyse ---
FUNDAMENTAL = {
    "pe_max": 35,              # Maximales KGV
    "revenue_growth_min": 0.05, # Mindest-Umsatzwachstum (5%)
    "profit_margin_min": 0.08,  # Mindest-Gewinnmarge (8%)
    "debt_to_equity_max": 150,  # Max. Verschuldungsgrad in % (yfinance-Format, 150 = 1,5x D/E-Ratio)
    "min_score": 0.60,          # Mindest-Score für Gate 4 (60%)
}

# --- Konfidenz-Ranking ---
CONFIDENCE = {
    "strong_buy_threshold": 0.85,   # combined_score ≥ 0.85 → "Strong Buy"
    "moderate_buy_threshold": 0.70, # combined_score ≥ 0.70 → "Moderate Buy"
    # darunter (aber alle Gates bestanden) → "Watch"
}

# --- Regime-bewusstes Scoring ---
# Wenn VIX > MARKET["vix_max"] (>20): erhöhtes Regime → Fundamentals stärker gewichten,
# technische Momentum-Signale weniger (kurzfristig unzuverlässiger), RS etwas mehr
# (Titel die trotz Marktdruck outperformen sind robuster).
REGIME = {
    "normal":   {"w_tech": 0.40, "w_fund": 0.40, "w_rs": 0.20},
    "elevated": {"w_tech": 0.30, "w_fund": 0.45, "w_rs": 0.25},
}

# --- Exit-Signale ---
EXITS = {
    "atr_stop_multiplier": 2.0,      # Stop-Loss = entry - 2 * ATR(14)
    "atr_target_multiplier": 3.0,    # Take-Profit = entry + 3 * ATR(14) (Risk/Reward 1:1.5)
    "rsi_overbought": 75,            # RSI-Grenze für Exit-Signal
    "bb_exit_pct": 0.95,             # Kurs ≥ 95% BB-Band → Exit-Signal
    "macd_bearish_days": 3,          # MACD muss X Tage durchgehend unter Signallinie liegen
    "trailing_drawdown_pct": 0.15,   # Kurs ≥ 15% unter 50-Tage-Hoch → Exit-Signal (normal)
    "trailing_drawdown_pct_elevated": 0.10,  # Strenger bei erhöhtem VIX-Regime
    "warn_signals": 1,               # Ab X aktiven Signalen → "Beobachten"
    "sell_signals": 3,               # Ab X aktiven Signalen → "Verkaufen erwägen" (normal)
    "sell_signals_elevated": 2,      # Strenger bei erhöhtem VIX-Regime
}

# --- Erwartetes Upside (separate Magnitude-Kennzahl) ---
UPSIDE = {
    "weight_atr":    0.40,   # Gewicht: ATR-basiertes Kursziel (3*ATR/Kurs)
    "weight_52w":    0.40,   # Gewicht: Distanz zum 52-Wochen-Hoch
    "weight_growth": 0.20,   # Gewicht: Umsatz-/Gewinnwachstum (fundamental)
    "threshold_high": 15.0,  # expected_upside_pct ≥ 15% → "Hoch"
    "threshold_mid":   7.0,  # expected_upside_pct ≥  7% → "Mittel"
    # darunter → "Gering"
}

# --- Cache ---
CACHE = {
    "dir": "cache",
    "max_age_days": 7,      # Cache-Dateien älter als X Tage löschen
    "refresh_hour": 18,     # Tägliche Aktualisierung um 18:00 Uhr (nach US-Marktschluss)
}

# --- Analyse ---
ANALYSIS = {
    "history_days": 365,   # Kursdaten der letzten 365 Tage laden
    "max_workers": 3,      # Parallele Downloads (yfinance) — niedrig halten gegen Rate-Limit
}

# --- Parameter-Overrides (aus Backtest-Sweep oder Spielwiese) ---
# backtest/param_overrides.json überschreibt die obigen Werte wenn vorhanden.
# Schreiben via backtest.runner.apply_overrides(); Löschen via clear_overrides().
import json as _json
import os as _os
_overrides_path = _os.path.join(_os.path.dirname(__file__), "backtest", "param_overrides.json")
if _os.path.exists(_overrides_path):
    try:
        with open(_overrides_path, "r", encoding="utf-8") as _f:
            _ov = _json.load(_f)
        for _k in ("min_score", "rsi_min", "rsi_max", "volume_factor"):
            if _k in _ov:
                TECHNICAL[_k] = _ov[_k]
        for _k in ("rs_top_percentile", "rs_min_6m"):
            if _k in _ov:
                RELATIVE_STRENGTH[_k] = _ov[_k]
    except Exception:
        pass
