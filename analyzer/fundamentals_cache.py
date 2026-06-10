"""
Persistenter Cache für yfinance-Fundamentaldaten (Ticker.info).

Ticker.info ist der teuerste Einzelcall im Scan (~1-2 s pro Titel, einer je
Gate-3-Passer). Die Kennzahlen ändern sich aber nur quartalsweise — ein
mehrtägiger Cache ist fachlich unkritisch und spart bei jedem Folge-Scan
50-150 HTTP-Calls.

Gespeichert wird nur das von Gate 4 benötigte Feld-Subset (eine JSON-Datei,
atomar via os.replace, threadsicher über ein Modul-Lock).
"""

import json
import logging
import os
import threading
import time

import yfinance as yf

logger = logging.getLogger(__name__)

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "cache", "fundamentals.json")
_TTL_DAYS = 3

# Nur diese Felder braucht check_fundamental() + Anzeige (name/sector)
_FIELDS = (
    "trailingPE", "revenueGrowth", "earningsGrowth", "profitMargins",
    "debtToEquity", "freeCashflow", "marketCap", "sector", "longName", "shortName",
)

_lock = threading.Lock()
_cache: dict | None = None   # lazy geladen: {ticker: {"ts": epoch, "info": {...}}}


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
    except Exception:
        _cache = {}
    return _cache


def _save():
    try:
        os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_cache, f, ensure_ascii=False)
        os.replace(tmp, _CACHE_FILE)
    except Exception as e:
        logger.debug(f"Fundamentals-Cache Schreibfehler: {e}")


def get_info_cached(ticker: str, ttl_days: int = _TTL_DAYS) -> dict:
    """
    Gibt das Gate-4-Feld-Subset für einen Ticker zurück — aus dem Cache wenn
    jünger als ttl_days, sonst frisch via yfinance (und cached das Ergebnis).
    Bei Fetch-Fehler: leeres Dict (Gate 4 wertet das als "nicht bestanden").
    """
    now = time.time()
    with _lock:
        entry = _load().get(ticker)
        if entry and (now - entry.get("ts", 0)) < ttl_days * 86400:
            return entry.get("info", {})

    # Fetch außerhalb des Locks — Netzwerk darf andere Threads nicht blockieren
    try:
        raw = yf.Ticker(ticker).info or {}
    except Exception as e:
        logger.debug(f"info-Fetch {ticker} fehlgeschlagen: {e}")
        return {}

    info = {k: raw.get(k) for k in _FIELDS if raw.get(k) is not None}

    with _lock:
        _load()[ticker] = {"ts": now, "info": info}
        _save()
    return info
