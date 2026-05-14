"""
Portfolio-Verwaltung: eigene Kaufpositionen speichern und überwachen.
Daten liegen in portfolio.json im Projekt-Root (nicht im Cache).

Schema (neu):
  {
    "positions": [
      {
        "ticker": "AAPL",
        "company_name": "Apple Inc.",
        "lots": [
          {"date": "2025-12-01", "shares": 10, "price_eur": 165.50, "notes": ""},
          {"date": "2026-02-15", "shares":  5, "price_eur": 180.00, "notes": "Nachkauf"}
        ]
      }
    ],
    "realized": [
      {
        "ticker": "AAPL", "company_name": "Apple Inc.",
        "buy_date": "2025-12-01", "sell_date": "2026-03-10",
        "shares": 5, "buy_price_eur": 165.50, "sell_price_eur": 190.00,
        "pnl_eur": 122.50, "pnl_pct": 14.8, "days_held": 99, "notes": ""
      }
    ]
  }

Ältere portfolio.json ohne 'lots' werden beim ersten Lesen automatisch migriert.
Kaufpreise und Verkaufspreise werden in EUR gespeichert.
P&L-Berechnung über EUR/USD-Kurs (aktueller Kurs).
"""

import json
import os
from datetime import date, datetime
import yfinance as yf

from analyzer.exits import compute_exits, inject_external_signals

PORTFOLIO_FILE = os.path.join(os.path.dirname(__file__), "..", "portfolio.json")


# ── Persistenz ────────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    """Lädt portfolio.json und migriert altes Schema automatisch."""
    if not os.path.exists(PORTFOLIO_FILE):
        return {"positions": [], "realized": []}
    try:
        with open(PORTFOLIO_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if "positions" not in data:
            data["positions"] = []
        if "realized" not in data:
            data["realized"] = []
        # Migration: alte Positionen ohne 'lots' in neues Format überführen
        data["positions"] = [_migrate_position(p) for p in data["positions"]]
        return data
    except Exception:
        return {"positions": [], "realized": []}


def _migrate_position(pos: dict) -> dict:
    """Konvertiert eine alte Position (entry_price_eur, shares, entry_date) in Lot-Format."""
    if "lots" in pos:
        return pos  # bereits neues Format
    lot = {
        "date": pos.get("entry_date", str(date.today())),
        "shares": float(pos.get("shares", 0)),
        "price_eur": float(pos.get("entry_price_eur") or pos.get("entry_price") or 0),
        "notes": pos.get("notes", ""),
    }
    return {
        "ticker": pos.get("ticker", ""),
        "company_name": pos.get("company_name", pos.get("ticker", "")),
        "lots": [lot],
    }


def _save_portfolio(data: dict):
    with open(PORTFOLIO_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ── Hilfsfunktionen ───────────────────────────────────────────────────────────

def _total_shares(pos: dict) -> float:
    return sum(float(lot["shares"]) for lot in pos.get("lots", []))


def _avg_price(pos: dict) -> float | None:
    """Gewichteter Durchschnittseinstiegspreis in EUR."""
    lots = pos.get("lots", [])
    total_s = sum(float(l["shares"]) for l in lots)
    if not total_s:
        return None
    return sum(float(l["shares"]) * float(l["price_eur"]) for l in lots) / total_s


def _earliest_lot_date(pos: dict) -> date | None:
    lots = pos.get("lots", [])
    dates = []
    for l in lots:
        try:
            dates.append(datetime.strptime(l["date"], "%Y-%m-%d").date())
        except Exception:
            pass
    return min(dates) if dates else None


# ── Käufe ─────────────────────────────────────────────────────────────────────

def add_position(ticker: str, company_name: str, entry_date: str,
                 entry_price_eur: float, shares: float, notes: str = "") -> dict:
    """
    Fügt einen Kauf hinzu.
    - Existiert bereits eine Position mit diesem Ticker → neues Lot anhängen.
    - Existiert noch nicht → neue Position anlegen.
    Rückgabe: die aktualisierte Position.
    """
    ticker = ticker.upper().strip()
    data = load_portfolio()

    lot = {
        "date": str(entry_date),
        "shares": float(shares),
        "price_eur": float(entry_price_eur),
        "notes": notes,
    }

    for pos in data["positions"]:
        if pos["ticker"] == ticker:
            pos["lots"].append(lot)
            if company_name:
                pos["company_name"] = company_name
            _save_portfolio(data)
            return pos

    # Neue Position
    pos = {
        "ticker": ticker,
        "company_name": company_name or ticker,
        "lots": [lot],
    }
    data["positions"].append(pos)
    _save_portfolio(data)
    return pos


def remove_position(ticker: str):
    """Entfernt eine Position komplett (ohne realized-Eintrag)."""
    data = load_portfolio()
    data["positions"] = [p for p in data["positions"] if p["ticker"] != ticker]
    _save_portfolio(data)


def remove_position_by_index(index: int):
    """Kompatibilitäts-Wrapper für alten Code der mit Index arbeitet."""
    data = load_portfolio()
    if 0 <= index < len(data["positions"]):
        data["positions"].pop(index)
        _save_portfolio(data)


# ── Verkäufe ──────────────────────────────────────────────────────────────────

def sell_position(ticker: str, shares: float, sell_price_eur: float,
                  sell_date: str, notes: str = "") -> tuple[list[dict], str | None]:
    """
    Verkauft (Teil-)Anteile einer Position nach FIFO-Prinzip.

    Returns:
        (realized_entries, error_message)
        Bei Erfolg: (Liste der neuen realized-Einträge, None)
        Bei Fehler: ([], Fehlermeldung als String)
    """
    ticker = ticker.upper().strip()
    data = load_portfolio()

    # Position finden
    pos = next((p for p in data["positions"] if p["ticker"] == ticker), None)
    if pos is None:
        return [], f"Position '{ticker}' nicht gefunden."

    total = _total_shares(pos)

    # Validierungen
    if shares <= 0:
        return [], "Stückzahl muss größer als 0 sein."
    if shares > total + 0.0001:
        return [], f"Nur {total:g} Stück vorhanden, aber {shares:g} angegeben."
    if sell_price_eur <= 0:
        return [], "Verkaufskurs muss größer als 0 sein."

    try:
        sell_dt = datetime.strptime(sell_date, "%Y-%m-%d").date()
    except Exception:
        return [], f"Ungültiges Datum: {sell_date} (Format YYYY-MM-DD erwartet)."

    if sell_dt > date.today():
        return [], "Verkaufsdatum darf nicht in der Zukunft liegen."

    earliest = _earliest_lot_date(pos)
    if earliest and sell_dt < earliest:
        return [], (
            f"Verkaufsdatum {sell_date} liegt vor dem frühesten Kaufdatum "
            f"{earliest.isoformat()} dieser Position."
        )

    # FIFO: Lots von ältesten zu neuesten abarbeiten
    lots = sorted(pos["lots"], key=lambda l: l["date"])
    remaining_to_sell = float(shares)
    realized_entries = []

    for lot in lots:
        if remaining_to_sell <= 0.0001:
            break
        lot_shares = float(lot["shares"])
        sold_from_lot = min(lot_shares, remaining_to_sell)

        pnl_eur = round((float(sell_price_eur) - float(lot["price_eur"])) * sold_from_lot, 2)
        pnl_pct = round((float(sell_price_eur) / float(lot["price_eur"]) - 1) * 100, 2) if lot["price_eur"] else None

        try:
            buy_dt = datetime.strptime(lot["date"], "%Y-%m-%d").date()
            days_held = (sell_dt - buy_dt).days
        except Exception:
            days_held = None

        realized_entries.append({
            "ticker": ticker,
            "company_name": pos.get("company_name", ticker),
            "buy_date": lot["date"],
            "sell_date": sell_date,
            "shares": round(sold_from_lot, 6),
            "buy_price_eur": float(lot["price_eur"]),
            "sell_price_eur": float(sell_price_eur),
            "pnl_eur": pnl_eur,
            "pnl_pct": pnl_pct,
            "days_held": days_held,
            "notes": notes,
        })

        lot["shares"] = round(lot_shares - sold_from_lot, 6)
        remaining_to_sell -= sold_from_lot

    # Lots mit 0 Stück entfernen
    pos["lots"] = [l for l in lots if float(l["shares"]) > 0.0001]

    # Position entfernen wenn leer
    if not pos["lots"]:
        data["positions"] = [p for p in data["positions"] if p["ticker"] != ticker]
    else:
        # Aktualisierte Lots zurückschreiben (FIFO-Reihenfolge beibehalten, re-sort nach Datum)
        pos["lots"] = sorted(pos["lots"], key=lambda l: l["date"])
        for p in data["positions"]:
            if p["ticker"] == ticker:
                p["lots"] = pos["lots"]
                break

    data["realized"].extend(realized_entries)
    _save_portfolio(data)
    return realized_entries, None


def load_realized() -> list[dict]:
    """Gibt alle realisierten Trades zurück (neueste zuerst)."""
    data = load_portfolio()
    return sorted(data.get("realized", []), key=lambda r: r.get("sell_date", ""), reverse=True)


# ── Live-Daten ────────────────────────────────────────────────────────────────

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
    Lädt alle offenen Positionen und berechnet für jede:
    - aktueller Kurs in USD (live) und EUR (umgerechnet)
    - P&L in EUR absolut und Prozent (bezogen auf Durchschnittseinstand)
    - Tage gehalten (ab erstem Lot)
    - Exit-Signale & Empfehlung
    """
    data = load_portfolio()
    eurusd = get_eurusd_rate()

    # Marktumfeld einmalig abrufen für alle Positionen
    market_bearish = False
    try:
        from analyzer.market_filter import check_market
        mkt = check_market()
        market_bearish = not mkt.get("passed", True) or mkt.get("warning", False)
    except Exception:
        pass

    results = []
    for pos in data["positions"]:
        ticker = pos["ticker"]
        total_shares = _total_shares(pos)
        avg_entry_eur = _avg_price(pos)
        earliest_dt = _earliest_lot_date(pos)
        days_held = (date.today() - earliest_dt).days if earliest_dt else None

        current_price_usd = None
        current_price_eur = None
        exits = {"atr": None, "stop_loss": None, "take_profit": None,
                 "signals": {}, "signal_count": 0, "recommendation": "Keine Daten"}
        sector = pos.get("sector")

        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="3mo")
            if hist is not None and len(hist) >= 15:
                current_price_usd = float(hist["Close"].iloc[-1])
                if eurusd:
                    current_price_eur = round(current_price_usd / eurusd, 2)
                exits = compute_exits(hist, entry_price=current_price_usd)
                if exits["signals"]:
                    inject_external_signals(
                        exits, **{"Marktumfeld bearish": market_bearish}
                    )
            if not sector:
                try:
                    sector = stock.info.get("sector")
                    if sector:
                        pos["sector"] = sector
                except Exception:
                    pass
        except Exception:
            pass

        pnl_abs_eur = None
        pnl_pct = None
        if avg_entry_eur is not None and current_price_eur is not None:
            pnl_abs_eur = round((current_price_eur - avg_entry_eur) * total_shares, 2)
            pnl_pct = round((current_price_eur / avg_entry_eur - 1) * 100, 2)

        results.append({
            "ticker": ticker,
            "company_name": pos.get("company_name", ticker),
            "lots": pos.get("lots", []),
            "total_shares": total_shares,
            "avg_entry_price_eur": round(avg_entry_eur, 2) if avg_entry_eur else None,
            "entry_date": earliest_dt.isoformat() if earliest_dt else None,
            "sector": sector,
            "current_price_usd": current_price_usd,
            "current_price_eur": current_price_eur,
            "eurusd": eurusd,
            "days_held": days_held,
            "pnl_abs_eur": pnl_abs_eur,
            "pnl_pct": pnl_pct,
            "exits": exits,
            "notes": pos.get("lots", [{}])[-1].get("notes", "") if pos.get("lots") else "",
        })
    return results
