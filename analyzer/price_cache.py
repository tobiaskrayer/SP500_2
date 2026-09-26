"""
Persistenter Tages-Cache für yfinance-Kursdaten.

Speichert OHLCV-DataFrames pro Ticker als Pickle unter cache/prices/<TICKER>.pkl.
Freshnesscheck: letzte abgeschlossene NYSE-Sitzung und mindestens 200 Balken.

Vorteil: innerhalb eines Tages (mehrfache Scans, Performance-Seitenaufrufe)
werden keine redundanten yfinance-Calls gemacht.

cache/prices/ ist gitignored — reiner Laufzeit-Cache.
"""

import os
import pickle
import logging
import tempfile

import pandas as pd
from analyzer.sessions import completed_bars, last_completed_session

logger = logging.getLogger(__name__)

_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "cache", "prices")


def _ensure_dir():
    os.makedirs(_CACHE_DIR, exist_ok=True)


def _path(ticker: str) -> str:
    safe = ticker.replace("/", "_").replace("\\", "_")
    return os.path.join(_CACHE_DIR, f"{safe}.pkl")


def load(ticker: str) -> pd.DataFrame | None:
    """Akzeptiert nur vollständige, adjustierte Kurshistorien bis zur letzten Sitzung."""
    p = _path(ticker)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "rb") as f:
            df = pickle.load(f)
        if isinstance(df, pd.DataFrame) and df.attrs.get("adjustment") == "auto_adjust":
            df = completed_bars(df)
            if (len(df) >= 200 and df.index[-1].date() == last_completed_session()
                    and df.index.is_monotonic_increasing and df.index.is_unique):
                return df
    except Exception as e:
        logger.debug(f"Cache-Lesefehler {ticker}: {e}")
    return None


def save(ticker: str, df: pd.DataFrame):
    """Speichert DataFrame als Pickle."""
    if df is None or len(df) < 200:
        return
    tmp_path = None
    try:
        _ensure_dir()
        df = completed_bars(df)
        if len(df) < 200:
            return
        df.attrs["adjustment"] = "auto_adjust"
        with tempfile.NamedTemporaryFile("wb", dir=_CACHE_DIR, suffix=".tmp", delete=False) as f:
            tmp_path = f.name
            pickle.dump(df, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp_path, _path(ticker))
    except Exception as e:
        logger.debug(f"Cache-Schreibfehler {ticker}: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


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
