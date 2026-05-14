"""
Berechnet die tägliche Portfolio-Wertentwicklung (EUR) und vergleicht sie mit SPY.
Ergebnis wird in cache/portfolio_history.json gecacht.
"""

import json
import os
from datetime import date, datetime, timedelta

import yfinance as yf
import pandas as pd

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache")
_CACHE_VERSION = "v2"  # erhöhen wenn Berechnungslogik sich ändert → Cache-Invalidierung


def _cache_file(user_id: str | None = None) -> str:
    suffix = f"_{user_id}" if user_id else ""
    return os.path.join(_CACHE_DIR, f"portfolio_history{suffix}.json")


def get_portfolio_history(positions: list[dict], user_id: str | None = None) -> dict | None:
    """
    Berechnet die tägliche Portfolio-Wertentwicklung ab dem ersten Kauf.

    positions: Output von evaluate_positions() (offene + für History-Zwecke auch geschlossene Lots)

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
    if not positions:
        return None

    # Frühestes Kaufdatum über alle Positionen bestimmen
    all_dates = []
    for pos in positions:
        for lot in pos.get("lots", []):
            try:
                all_dates.append(datetime.strptime(lot["date"], "%Y-%m-%d").date())
            except Exception:
                pass
    if not all_dates:
        return None

    start = min(all_dates)
    today = date.today()

    if (today - start).days < 3:
        return None

    start_str = start.isoformat()
    tickers_needed = [pos["ticker"] for pos in positions] + ["EURUSD=X", "SPY"]

    # Cache prüfen
    cache_key = f"{_CACHE_VERSION}_{start_str}_{','.join(sorted(p['ticker'] for p in positions))}"
    cached = _load_cache(user_id)
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

        # EUR/USD-Kurs
        eurusd_series = closes.get("EURUSD=X") if "EURUSD=X" in closes.columns else None
        spy_series = closes.get("SPY") if "SPY" in closes.columns else None

        # Tägliche Portfolio-Werte berechnen
        daily_values = []
        dates_out = []

        for dt, row in closes.iterrows():
            dt_date = dt.date() if hasattr(dt, "date") else dt
            eurusd = float(eurusd_series.get(dt, 1.1)) if eurusd_series is not None else 1.1

            day_value_eur = 0.0
            for pos in positions:
                ticker = pos["ticker"]
                if ticker not in closes.columns:
                    continue
                price_usd = row.get(ticker)
                if price_usd is None or pd.isna(price_usd):
                    continue
                # Stücke, die an diesem Tag bereits gehalten wurden
                shares_held = _shares_held_on(pos, dt_date)
                if shares_held > 0:
                    day_value_eur += float(price_usd) / eurusd * shares_held

            if day_value_eur > 0:
                daily_values.append(round(day_value_eur, 2))
                dates_out.append(dt_date.isoformat())

        if len(daily_values) < 2:
            return None

        # Normalisierung: Portfolio-Wert / investiertes Kapital bis zu diesem Tag × 100
        # Vermeidet den Fehler, dass neue Käufe als "Gewinn" gewertet werden
        def _invested_on(d_str: str) -> float:
            total = 0.0
            for pos in positions:
                for lot in pos.get("lots", []):
                    if lot["date"] <= d_str:
                        total += float(lot["shares"]) * float(lot["price_eur"])
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

        _save_cache({"cache_key": cache_key, "end_date": today.isoformat(), "result": result}, user_id)
        return result

    except Exception:
        return None


def _shares_held_on(pos: dict, on_date: date) -> float:
    """Gibt die Anzahl Stücke zurück, die an `on_date` bereits in diesem Lot lagen."""
    total = 0.0
    for lot in pos.get("lots", []):
        try:
            lot_date = datetime.strptime(lot["date"], "%Y-%m-%d").date()
            if lot_date <= on_date:
                total += float(lot["shares"])
        except Exception:
            pass
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


def _load_cache(user_id: str | None = None) -> dict | None:
    try:
        path = _cache_file(user_id)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_cache(data: dict, user_id: str | None = None):
    try:
        path = _cache_file(user_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except Exception:
        pass
