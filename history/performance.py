"""
Performance-Berechnung für historische Empfehlungen.
Lädt historische Kurse via yfinance und berechnet 1W/1M/3M-Performance vs. SPY.
Ergebnisse werden gecacht um API-Calls zu minimieren.
"""

import json
import logging
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
import yfinance as yf

logger = logging.getLogger(__name__)

# Kurs-Cache nutzen wenn verfügbar
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from analyzer.price_cache import load as _price_cache_load, save as _price_cache_save
    _CACHE_AVAILABLE = True
except ImportError:
    _CACHE_AVAILABLE = False

PERF_CACHE_FILE = os.path.join(os.path.dirname(__file__), "performance_cache.json")

# Haltezeiträume in Tagen
PERIODS = {"1w": 7, "1m": 30, "3m": 91}


def enrich_with_performance(log: list[dict]) -> list[dict]:
    """
    Reichert alle Empfehlungen im Log mit Performance-Daten an.
    Gibt eine flache Liste aller Empfehlungen (über alle Log-Einträge) zurück,
    jede ergänzt um: performance_1w, performance_1m, performance_3m,
                      perf_vs_spy_1m, hit_1m, days_since
    """
    cache = _load_cache()

    flat = []
    for entry in log:
        rec_date = entry.get("date", "")
        market_ctx = entry.get("market_context", {})
        for rec in entry.get("recommendations", []):
            ticker = rec.get("ticker")
            entry_price = rec.get("price")
            if not ticker or not entry_price:
                continue

            cache_key = f"{ticker}_{rec_date}"
            if cache_key in cache and _cache_complete(cache[cache_key], rec_date):
                perf_data = cache[cache_key]
            else:
                perf_data = _compute_performance(ticker, rec_date, entry_price)
                if perf_data:
                    cache[cache_key] = perf_data

            flat.append({
                **rec,
                "rec_date": rec_date,
                "market_context": market_ctx,
                **(perf_data or {}),
            })

    _save_cache(cache)
    return flat


def _compute_performance(ticker: str, rec_date_str: str, entry_price: float) -> dict:
    """Berechnet Performance-Kennzahlen für eine Empfehlung."""
    try:
        rec_date = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
        today = date.today()
        days_since = (today - rec_date).days

        # Kursdaten — gecachte 1J-Daten slicen wenn verfügbar, sonst neu laden
        end_date = min(today, rec_date + timedelta(days=100))
        hist = _load_hist_for_perf(ticker, rec_date_str, end_date)
        spy_hist = _load_hist_for_perf("SPY", rec_date_str, end_date)

        if hist is None or len(hist) < 2:
            return {}

        def perf_after(days: int):
            target = rec_date + timedelta(days=days)
            if target > today:
                return None
            idx = hist.index.searchsorted(str(target))
            idx = min(idx, len(hist) - 1)
            price = float(hist["Close"].iloc[idx])
            return round((price / entry_price - 1) * 100, 2)

        def spy_perf_after(days: int):
            if len(spy_hist) < 2:
                return None
            target = rec_date + timedelta(days=days)
            if target > today:
                return None
            spy_entry = float(spy_hist["Close"].iloc[0])
            idx = spy_hist.index.searchsorted(str(target))
            idx = min(idx, len(spy_hist) - 1)
            spy_later = float(spy_hist["Close"].iloc[idx])
            return round((spy_later / spy_entry - 1) * 100, 2)

        p1w = perf_after(PERIODS["1w"])
        p1m = perf_after(PERIODS["1m"])
        p3m = perf_after(PERIODS["3m"])
        spy1m = spy_perf_after(PERIODS["1m"])

        perf_vs_spy = round(p1m - spy1m, 2) if (p1m is not None and spy1m is not None) else None

        # Max-Drawdown seit Empfehlung (bis heute oder 3M)
        max_drawdown = None
        if len(hist) > 1:
            prices = hist["Close"]
            peak = float(prices.iloc[0])
            dd_values = []
            for p in prices:
                peak = max(peak, float(p))
                dd_values.append((float(p) / peak - 1) * 100)
            max_drawdown = round(min(dd_values), 2)

        return {
            "performance_1w": p1w,
            "performance_1m": p1m,
            "performance_3m": p3m,
            "perf_vs_spy_1m": perf_vs_spy,
            "spy_perf_1m": spy1m,
            "hit_1m": bool(p1m is not None and p1m > 0),
            "max_drawdown": max_drawdown,
            "days_since": days_since,
        }

    except Exception as e:
        logger.warning(f"Performance-Berechnung fehlgeschlagen ({ticker} @ {rec_date_str}): {e}")
        return {}


def _cache_complete(entry: dict, rec_date_str: str) -> bool:
    """True wenn 3M abgelaufen (keine Updates mehr nötig) oder alle aktuell berechenbaren Felder vorhanden."""
    try:
        rec_date = datetime.strptime(rec_date_str, "%Y-%m-%d").date()
        if (date.today() - rec_date).days >= PERIODS["3m"]:
            return entry.get("performance_3m") is not None
        if (date.today() - rec_date).days >= PERIODS["1m"]:
            return entry.get("performance_1m") is not None
        return entry.get("performance_1w") is not None
    except Exception:
        return False


def _load_cache() -> dict:
    if not os.path.exists(PERF_CACHE_FILE):
        return {}
    try:
        with open(PERF_CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Performance-Cache konnte nicht gelesen werden: {e}")
        return {}


def _save_cache(cache: dict):
    # Atomischer Schreibvorgang: erst temp-Datei, dann umbenennen.
    # Verhindert korrupte Lesungen wenn die Performance-Seite gleichzeitig lädt.
    tmp_path = None
    try:
        dir_ = os.path.dirname(PERF_CACHE_FILE)
        os.makedirs(dir_, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=dir_, suffix=".tmp",
                                         delete=False, encoding="utf-8") as tmp:
            json.dump(cache, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name
        os.replace(tmp_path, PERF_CACHE_FILE)
    except Exception as e:
        logger.warning(f"Performance-Cache konnte nicht gespeichert werden: {e}")
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _load_hist_for_perf(ticker: str, start_str: str, end_date) -> object:
    """
    Lädt Kursdaten für die Performance-Berechnung.
    Nutzt gecachte 1J-Daten (slice) wenn verfügbar, sonst direkter yfinance-Call.
    """
    from datetime import timedelta
    if _CACHE_AVAILABLE:
        cached = _price_cache_load(ticker)
        if cached is not None:
            try:
                sliced = cached[cached.index >= start_str]
                if len(sliced) >= 2:
                    return sliced
            except Exception:
                pass
    # Fallback: direkter Download
    hist = yf.Ticker(ticker).history(start=start_str, end=str(end_date + timedelta(days=1)))
    if _CACHE_AVAILABLE and hist is not None and len(hist) >= 60:
        _price_cache_save(ticker, hist)
    return hist
