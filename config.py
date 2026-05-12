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
    "period_short_days": 63,   # ~3 Monate
    "period_long_days": 126,   # ~6 Monate
    # Aktie muss den S&P500 in BEIDEN Zeiträumen übertreffen
}

# --- Gate 3: Technische Analyse ---
TECHNICAL = {
    "rsi_min": 45,         # RSI nicht zu schwach
    "rsi_max": 70,         # RSI nicht überkauft
    "bb_upper_pct": 0.95,  # Kurs darf nicht über 95% des BB-Bandes sein
    "volume_lookback": 20, # Tage für Volumen-Durchschnitt
    "volume_factor": 1.0,  # Volumen muss mindestens 1.0x des Durchschnitts sein
    "min_score": 0.70,     # Mindest-Score für Gate 3 (70%)
}

# --- Gate 4: Fundamentalanalyse ---
FUNDAMENTAL = {
    "pe_max": 35,              # Maximales KGV
    "revenue_growth_min": 0.05, # Mindest-Umsatzwachstum (5%)
    "profit_margin_min": 0.08,  # Mindest-Gewinnmarge (8%)
    "debt_to_equity_max": 100,  # Maximaler Verschuldungsgrad
    "min_score": 0.60,          # Mindest-Score für Gate 4 (60%)
}

# --- Konfidenz-Ranking ---
CONFIDENCE = {
    "strong_buy_threshold": 0.85,   # combined_score ≥ 0.85 → "Strong Buy"
    "moderate_buy_threshold": 0.70, # combined_score ≥ 0.70 → "Moderate Buy"
    # darunter (aber alle Gates bestanden) → "Watch"
}

# --- Exit-Signale ---
EXITS = {
    "atr_stop_multiplier": 2.0,    # Stop-Loss = entry - 2 * ATR(14)
    "atr_target_multiplier": 3.0,  # Take-Profit = entry + 3 * ATR(14) (Risk/Reward 1:1.5)
    "rsi_overbought": 75,          # RSI-Grenze für Exit-Signal
    "bb_exit_pct": 0.95,           # Kurs ≥ 95% BB-Band → Exit-Signal
    "warn_signals": 1,             # Ab X aktiven Signalen → "Beobachten"
    "sell_signals": 3,             # Ab X aktiven Signalen → "Verkaufen erwägen"
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
    "max_workers": 10,     # Parallele Downloads (yfinance)
}
