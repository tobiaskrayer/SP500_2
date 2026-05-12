"""
Portfolio-Verwaltung: eigene Kaufpositionen speichern und überwachen.
Daten liegen in portfolio.json im Projekt-Root (nicht im Cache).
Kaufpreise werden in EUR gespeichert; P&L-Berechnung über EUR/USD-Kurs.
"""

import json
import os
from datetime import date, datetime
import yfinance as yf

from analyzer.exits import compute_exits

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "..", "portfolio.json")


def load_portfolio() -> dict:
    if not os.path.exists(PORTFOLIO_FILE):
        return {"positions": []}
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "positions" not in data:
            data["positions"] = []
        return data
    except Exception:
        return {"positions": []}


def _save_portfolio(data: dict):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_position(ticker: str, company_name: str, entry_date: str,
                 entry_price_eur: float, shares: float, notes: str = "") -> dict:
    """Fügt eine neue Position hinzu. Kaufpreis in EUR."""
    data = load_portfolio()
    pos = {
        "ticker": ticker.upper().strip(),
        "company_name": company_name,
        "entry_date": str(entry_date),
        "entry_price_eur": float(entry_price_eur),
        "shares": float(shares),
        "notes": notes,
    }
    data["positions"].append(pos)
    _save_portfolio(data)
    return pos


def remove_position(index: int):
    data = load_portfolio()
    if 0 <= index < len(data["positions"]):
        data["positions"].pop(index)
        _save_portfolio(data)


def get_eurusd_rate() -> float | None:
    """Aktueller EUR/USD-Kurs (1 EUR = X USD). None bei Fehler."""
    try:
        hist = yf.Ticker("EURUSD=X").history(period="5d")
        if hist is not None and len(hist) > 0:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def evaluate_positions() -> list[dict]:
    """
    Lädt alle Positionen und berechnet für jede:
    - aktueller Kurs in USD (live) und EUR (umgerechnet)
    - P&L in EUR absolut und Prozent
    - Tage gehalten
    - Exit-Signale & Empfehlung
    """
    data = load_portfolio()
    eurusd = get_eurusd_rate()  # einmalig für alle Positionen laden

    results = []
    for pos in data["positions"]:
        ticker = pos["ticker"]
        shares = pos["shares"]
        entry_date_str = pos["entry_date"]

        # Rückwärtskompatibilität: alte Positionen hatten entry_price (USD)
        entry_price_eur = pos.get("entry_price_eur")
        entry_price_usd_legacy = pos.get("entry_price")  # alte Positionen

        try:
            entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        except Exception:
            entry_dt = None
        days_held = (date.today() - entry_dt).days if entry_dt else None

        # Live-Kurs (USD) + History für Exit-Signale
        current_price_usd = None
        current_price_eur = None
        exits = {"atr": None, "stop_loss": None, "take_profit": None,
                 "signals": {}, "signal_count": 0, "recommendation": "Keine Daten"}
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="3mo")
            if hist is not None and len(hist) >= 15:
                current_price_usd = float(hist["Close"].iloc[-1])
                if eurusd:
                    current_price_eur = round(current_price_usd / eurusd, 2)
                # Exit-Signale auf USD-Basis berechnen
                exits = compute_exits(hist, entry_price=current_price_usd)
        except Exception:
            pass

        # P&L in EUR
        pnl_abs_eur = None
        pnl_pct = None
        if entry_price_eur is not None and current_price_eur is not None:
            pnl_abs_eur = round((current_price_eur - entry_price_eur) * shares, 2)
            pnl_pct = round((current_price_eur / entry_price_eur - 1) * 100, 2)
        elif entry_price_usd_legacy is not None and current_price_usd is not None:
            # Fallback für alte USD-Positionen
            pnl_abs_eur = round((current_price_usd - entry_price_usd_legacy) * shares, 2)
            pnl_pct = round((current_price_usd / entry_price_usd_legacy - 1) * 100, 2)

        results.append({
            "ticker": ticker,
            "company_name": pos.get("company_name", ticker),
            "entry_date": entry_date_str,
            "entry_price_eur": entry_price_eur,
            "entry_price_usd_legacy": entry_price_usd_legacy,
            "shares": shares,
            "notes": pos.get("notes", ""),
            "current_price_usd": current_price_usd,
            "current_price_eur": current_price_eur,
            "eurusd": eurusd,
            "days_held": days_held,
            "pnl_abs_eur": pnl_abs_eur,
            "pnl_pct": pnl_pct,
            "exits": exits,
        })
    return results
