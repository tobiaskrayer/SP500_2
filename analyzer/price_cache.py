"""
Persistenter Tages-Cache für yfinance-Kursdaten.

Speichert OHLCV-DataFrames pro Ticker als Pickle unter cache/prices/<TICKER>.pkl.
Freshnesscheck: Datei von heute → Treffer; älter → neu laden.

Vorteil: innerhalb eines Tages (mehrfache Scans, Performance-Seitenaufrufe)
werden keine redundanten yfinance-Calls gemacht.

cache/prices/ ist gitignored — reiner Laufzeit-Cache.
"""

import os
import pickle
import logging
from datetime import date

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache", "prices")


def _ensure_dir():
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _path(ticker: str) -> str:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return os.path.join(_CACHE_DIR, f"{safe}.pkl")


def load(ticker: str) -> pd.DataFrame | None:
    """Gibt gecachte Daten zurück wenn die Datei von heute ist, sonst None."""
    p = _path(ticker)
    if not os.path.exists(p):
        return None
    try:
        mtime = date.fromtimestamp(os.path.getmtime(p))
        if mtime < date.today():
            return None
        with open(p, "rb") as f:
            df = pickle.load(f)
        if isinstance(df, pd.DataFrame) and len(df) >= 60:
            return df
    except Exception as e:
        logger.debug(f"Cache-Lesefehler {ticker}: {e}")
    return None


def save(ticker: str, df: pd.DataFrame):
    """Speichert DataFrame als Pickle."""
    if df is None or len(df) < 60:
        return
    try:
        _ensure_dir()
        with open(_path(ticker), "wb") as f:
            pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as e:
        logger.debug(f"Cache-Schreibfehler {ticker}: {e}")


def load_many(tickers: list[str]) -> tuple[dict, list[str]]:
    """
    Gibt (cache_hits, missing) zurück.
    cache_hits: {ticker: DataFrame} für Ticker mit frischen Daten.
    missing: Liste von Tickern die heruntergeladen werden müssen.
    """
    hits = {}
    missing = []
    for t in tickers:
        df = load(t)
        if df is not None:
            hits[t] = df
        else:
            missing.append(t)
    return hits, missing


def save_many(data: dict):
    """Speichert alle Ticker aus einem {ticker: DataFrame}-Dict."""
    for ticker, df in data.items():
        save(ticker, df)
