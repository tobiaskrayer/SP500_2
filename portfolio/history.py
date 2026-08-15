"""
Berechnet die tägliche Portfolio-Wertentwicklung (EUR) und vergleicht sie mit SPY.
Ergebnis wird in cache/portfolio_history.json gecacht.
"""

import json
import os
from datetime import date, datetime, timedelta

import yfinance as yf
import pandas as pd

from storage import write_json_atomic

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
# Erhöhen wenn die Berechnungslogik sich ändert → Cache-Invalidierung.
# v4: user_id-Suffix aus der Supabase-Zeit entfernt (Ein-Nutzer-Setup) — der Bump
# sorgt dafür, dass alte "portfolio_history_<uid>.json" nicht weiterverwendet werden.
_CACHE_VERSION = "v4"

_CACHE_FILE = os.path.join(_CACHE_DIR, "portfolio_history.json")


def get_portfolio_history(positions: list[dict], realized: list[dict] | None = None) -> dict | None:
    """
    Berechnet die tägliche Portfolio-Wertentwicklung ab dem ersten Kauf.

    positions: Output von evaluate_positions() (offene Lots)
    realized:  Output von load_realized() — nötig, damit verkaufte Stücke in der
               Vergangenheit korrekt enthalten sind. Ohne sie würden vergangene
               Portfolio-Werte mit den HEUTIGEN (reduzierten) Stückzahlen berechnet.

    Returns:
        {
            "dates": ["2025-12-01", ...],
            "portfolio_values_eur": [10000.0, ...],
            "portfolio_indexed": [100.0, ...],   # auf 100 normalisiert
            "spy_indexed": [100.0, ...],          # SPY auf gleichem Startdatum normalisiert
            "start_date": "2025-12-01",
            "total_return_pct": 12.5,
            "vs_spy_pct": 3.2,
            "max_drawdown_pct": -8.1,
        }
        Oder None wenn nicht genug Daten.
    """
    # Bestände als Intervalle: (buy_date, sell_date|None, shares, price_eur) je Ticker.
    # Offene Lots laufen bis heute, realisierte Trades von buy_date bis sell_date.
    holdings = _build_holdings(positions, realized or [])
    if not holdings:
        return None

    all_dates = [iv[0] for ivs in holdings.values() for iv in ivs]
    if not all_dates:
        return None

    start = min(all_dates)
    today = date.today()

    if (today - start).days < 3:
        return None

    start_str = start.isoformat()
    tickers_needed = sorted(holdings) + ["EURUSD=X", "SPY"]

    # Cache prüfen — Fingerprint enthält auch die realisierten Trades
    n_lots = sum(len(ivs) for ivs in holdings.values())
    cache_key = f"{_CACHE_VERSION}_{start_str}_{','.join(sorted(holdings))}_{n_lots}_{len(realized or [])}"
    cached = _load_cache()
    if cached and cached.get("cache_key") == cache_key and cached.get("end_date") == today.isoformat():
        return cached.get("result")

    try:
        # Alle Kursdaten auf einmal laden
        raw = yf.download(
            tickers_needed,
            start=start_str,
            end=(today + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            progress=False,
        )
        if raw is None or raw.empty:
            return None

        # Close-Spalten extrahieren
        if isinstance(raw.columns, pd.MultiIndex):
            closes = raw["Close"]
        else:
            closes = raw[["Close"]] if "Close" in raw.columns else raw

        closes = closes.ffill().dropna(how="all")

        if closes.empty:
            return None

        # EUR/USD-Kurs — ohne FX-Daten keine History (ein fixer Fallback-Kurs
        # würde das Portfolio um bis zu ~10 % falsch bewerten).
        eurusd_series = closes.get("EURUSD=X") if "EURUSD=X" in closes.columns else None
        if eurusd_series is None:
            return None
        # FX-Kalender weicht vom Aktienkalender ab → Lücken am Serienanfang füllen
        eurusd_series = eurusd_series.ffill().bfill()
        spy_series = closes.get("SPY") if "SPY" in closes.columns else None

        # Tägliche Portfolio-Werte berechnen
        daily_values = []
        dates_out = []

        for dt, row in closes.iterrows():
            dt_date = dt.date() if hasattr(dt, "date") else dt
            eurusd = float(eurusd_series.get(dt, float("nan")))
            if pd.isna(eurusd) or eurusd <= 0:
                continue

            day_value_eur = 0.0
            for ticker, intervals in holdings.items():
                if ticker not in closes.columns:
                    continue
                price_usd = row.get(ticker)
                if price_usd is None or pd.isna(price_usd):
                    continue
                # Stücke, die an diesem Tag gehalten wurden (inkl. später verkaufter)
                shares_held = _shares_held_on(intervals, dt_date)
                if shares_held > 0:
                    day_value_eur += float(price_usd) / eurusd * shares_held

            if day_value_eur > 0:
                daily_values.append(round(day_value_eur, 2))
                dates_out.append(dt_date.isoformat())

        if len(daily_values) < 2:
            return None

        # Normalisierung: Portfolio-Wert / Einstandswert der an diesem Tag gehaltenen
        # Stücke × 100. Vermeidet, dass neue Käufe als "Gewinn" gewertet werden, und
        # zählt verkauftes Kapital nach dem Verkauf nicht mehr mit.
        def _invested_on(d_str: str) -> float:
            d = datetime.strptime(d_str, "%Y-%m-%d").date()
            total = 0.0
            for intervals in holdings.values():
                for buy_d, sell_d, shares, price_eur in intervals:
                    if buy_d <= d and (sell_d is None or d < sell_d):
                        total += shares * price_eur
            return total

        total_invested = _invested_on(dates_out[-1])
        portfolio_indexed = []
        for v, d in zip(daily_values, dates_out):
            invested = _invested_on(d)
            portfolio_indexed.append(round(v / invested * 100, 2) if invested > 0 else 100.0)

        # SPY normalisieren auf 100 ab erstem Kaufdatum
        spy_indexed = None
        if spy_series is not None:
            spy_dates = [pd.Timestamp(d) for d in dates_out]
            spy_vals = [float(spy_series.get(d, float("nan"))) for d in spy_dates]
            spy_vals_clean = [v for v in spy_vals if not pd.isna(v)]
            if spy_vals_clean:
                spy_base = spy_vals_clean[0]
                spy_indexed = [
                    round(v / spy_base * 100, 2) if not pd.isna(v) else None
                    for v in spy_vals
                ]

        # KPIs: Gesamtrendite = (aktueller Wert / investiertes Kapital - 1) × 100
        total_return = round((daily_values[-1] / total_invested - 1) * 100, 2) if total_invested > 0 else 0.0
        unrealized_pnl_eur = round(daily_values[-1] - total_invested, 2)
        max_dd = _max_drawdown(portfolio_indexed)

        vs_spy = None
        if spy_indexed:
            last_spy = next((v for v in reversed(spy_indexed) if v is not None), None)
            if last_spy:
                # Portfolio-Index vs. SPY-Index (beide starten bei 100)
                vs_spy = round(portfolio_indexed[-1] - last_spy, 2)

        result = {
            "dates": dates_out,
            "portfolio_values_eur": daily_values,
            "portfolio_indexed": portfolio_indexed,
            "spy_indexed": spy_indexed,
            "start_date": dates_out[0],
            "total_return_pct": total_return,
            "unrealized_pnl_eur": unrealized_pnl_eur,
            "vs_spy_pct": vs_spy,
            "max_drawdown_pct": max_dd,
        }

        _save_cache({"cache_key": cache_key, "end_date": today.isoformat(), "result": result})
        return result

    except Exception:
        return None


def _build_holdings(positions: list[dict], realized: list[dict]) -> dict[str, list[tuple]]:
    """
    Baut je Ticker eine Liste von Halte-Intervallen:
        (buy_date, sell_date | None, shares, price_eur)
    Offene Lots haben sell_date=None, realisierte Trades enden am Verkaufstag.
    """
    holdings: dict[str, list[tuple]] = {}
    for pos in positions:
        for lot in pos.get("lots", []):
            try:
                buy_d = datetime.strptime(lot["date"], "%Y-%m-%d").date()
                entry = (buy_d, None, float(lot["shares"]), float(lot["price_eur"]))
            except Exception:
                continue
            holdings.setdefault(pos["ticker"], []).append(entry)
    for trade in realized:
        try:
            buy_d = datetime.strptime(trade["buy_date"], "%Y-%m-%d").date()
            sell_d = datetime.strptime(trade["sell_date"], "%Y-%m-%d").date()
            entry = (buy_d, sell_d, float(trade["shares"]), float(trade["buy_price_eur"]))
        except Exception:
            continue
        holdings.setdefault(trade["ticker"], []).append(entry)
    return holdings


def _shares_held_on(intervals: list[tuple], on_date: date) -> float:
    """Anzahl Stücke, die an `on_date` gehalten wurden (verkaufte zählen bis exkl. Verkaufstag)."""
    total = 0.0
    for buy_d, sell_d, shares, _price in intervals:
        if buy_d <= on_date and (sell_d is None or on_date < sell_d):
            total += shares
    return total


def _max_drawdown(indexed: list[float]) -> float:
    """Maximaler Drawdown in Prozent (negativ)."""
    peak = indexed[0]
    max_dd = 0.0
    for v in indexed:
        if v > peak:
            peak = v
        dd = (v - peak) / peak * 100
        if dd < max_dd:
            max_dd = dd
    return round(max_dd, 2)


def _load_cache() -> dict | None:
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_cache(data: dict):
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        write_json_atomic(_CACHE_FILE, data)
    except Exception:
        pass
