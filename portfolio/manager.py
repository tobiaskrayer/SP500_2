"""
Portfolio-Verwaltung: eigene Kaufpositionen speichern und überwachen.
Daten liegen in portfolio.json im Projekt-Root (nicht im Cache).
"""

import json
import os
from datetime import date, datetime
import yfinance as yf
import pandas as pd

from analyzer.exits import compute_exits
from config import EXITS as _EXITS

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


def add_position(ticker: str, entry_date: str, entry_price: float,
                 shares: float, notes: str = "") -> dict:
    """Fügt eine neue Position hinzu. Gibt das gespeicherte Position-Dict zurück."""
    data = load_portfolio()
    pos = {
        "ticker": ticker.upper().strip(),
        "entry_date": str(entry_date),
        "entry_price": float(entry_price),
        "shares": float(shares),
        "notes": notes,
    }
    data["positions"].append(pos)
    _save_portfolio(data)
    return pos


def remove_position(index: int):
    """Entfernt Position an Index i (0-basiert)."""
    data = load_portfolio()
    if 0 <= index < len(data["positions"]):
        data["positions"].pop(index)
        _save_portfolio(data)


def evaluate_positions() -> list[dict]:
    """
    Lädt alle Positionen und berechnet für jede:
    - aktueller Kurs (live via yfinance)
    - P&L absolut und in Prozent
    - Tage gehalten
    - Exit-Signale & Empfehlung
    """
    data = load_portfolio()
    results = []
    for pos in data["positions"]:
        ticker = pos["ticker"]
        entry_price = pos["entry_price"]
        shares = pos["shares"]
        entry_date_str = pos["entry_date"]

        try:
            entry_dt = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
        except Exception:
            entry_dt = None
        days_held = (date.today() - entry_dt).days if entry_dt else None

        # Live-Kurs + History für Exit-Signale
        current_price = None
        exits = {"atr": None, "stop_loss": None, "take_profit": None,
                 "signals": {}, "signal_count": 0, "recommendation": "Keine Daten"}
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="3mo")
            if hist is not None and len(hist) >= 15:
                current_price = float(hist["Close"].iloc[-1])
                exits = compute_exits(hist, entry_price=entry_price)
                # RS-6M-Signal hier nicht verfügbar → belassen wie berechnet
        except Exception:
            pass

        pnl_abs = None
        pnl_pct = None
        if current_price is not None:
            pnl_abs = round((current_price - entry_price) * shares, 2)
            pnl_pct = round((current_price / entry_price - 1) * 100, 2)

        results.append({
            "ticker": ticker,
            "entry_date": entry_date_str,
            "entry_price": entry_price,
            "shares": shares,
            "notes": pos.get("notes", ""),
            "current_price": current_price,
            "days_held": days_held,
            "pnl_abs": pnl_abs,
            "pnl_pct": pnl_pct,
            "exits": exits,
        })
    return results
