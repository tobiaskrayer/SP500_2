"""
Persistenter Cache für yfinance-Fundamentaldaten (Ticker.info).

Ticker.info ist der teuerste Einzelcall im Scan (~1-2 s pro Titel, einer je
Gate-3-Passer). Die Kennzahlen ändern sich aber nur quartalsweise — ein
mehrtägiger Cache ist fachlich unkritisch und spart bei jedem Folge-Scan
50-150 HTTP-Calls.

Gespeichert wird nur das von Gate 4 benötigte Feld-Subset (eine JSON-Datei,
atomar via os.replace, threadsicher über ein Modul-Lock).

Zweistufig:
  1. Laufzeit-Cache (cache/fundamentals.json, gitignored) — wird beim Scannen
     geschrieben.
  2. Seed (cache/fundamentals_seed.json, git-getrackt) — wird täglich von
     GitHub Actions exportiert (scripts/export_fundamentals_seed.py). Nach
     einem Deploy/Checkout ist der Laufzeit-Cache leer, der Seed aber da →
     der erste Scan spart sich die 50–150 langsamen Ticker.info-Calls.
     Lokal nur lesend genutzt — kein Dirty-Working-Tree durch App-Läufe.
"""

import atexit
import json
import logging
import os
import threading
import time

import yfinance as yf

from storage import write_json_atomic

logger = logging.getLogger(__name__)

_CACHE_FILE = os.path.join(os.path.dirname(__file__), "..", "cache", "fundamentals.json")
_SEED_FILE = os.path.join(os.path.dirname(__file__), "..", "cache", "fundamentals_seed.json")
_TTL_DAYS = 3

# Nur diese Felder braucht check_fundamental() + Anzeige (name/sector)
_FIELDS = (
    "trailingPE", "revenueGrowth", "earningsGrowth", "profitMargins",
    "debtToEquity", "freeCashflow", "marketCap", "sector", "longName", "shortName",
)

_lock = threading.Lock()
_cache: dict | None = None   # lazy geladen: {ticker: {"ts": epoch, "info": {...}}}
_seed: dict | None = None    # lazy geladen, nur lesend

# Schreib-Drosselung: früher schrieb JEDER gecachte Ticker die komplette Datei neu
# (50-150 Rewrites pro Scan, jeweils im Lock). Jetzt wird höchstens alle
# _SAVE_INTERVAL_SEC geschrieben; flush() am Scan-Ende und via atexit sichert den Rest.
_SAVE_INTERVAL_SEC = 30
_dirty = False
_last_save = 0.0


def _load() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(_CACHE_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        # Defensiv: eine beschädigte Datei (z. B. "null") darf nicht dazu führen,
        # dass _load() etwas zurückgibt, auf dem .get() fehlschlägt.
        _cache = loaded if isinstance(loaded, dict) else {}
    except Exception:
        _cache = {}
    return _cache


def _load_seed() -> dict:
    global _seed
    if _seed is not None:
        return _seed
    try:
        with open(_SEED_FILE, "r", encoding="utf-8") as f:
            _seed = json.load(f)
    except Exception:
        _seed = {}
    return _seed


def _save():
    """Schreibt den Cache sofort auf Platte. Aufrufer hält das Lock."""
    global _dirty, _last_save
    if not isinstance(_cache, dict):
        _dirty = False      # nichts Sinnvolles zu schreiben (z. B. nach einem Reset)
        return
    try:
        write_json_atomic(_CACHE_FILE, _cache)
        _dirty = False
        _last_save = time.time()
    except Exception as e:
        logger.debug(f"Fundamentals-Cache Schreibfehler: {e}")


def _mark_dirty():
    """Merkt eine Änderung vor; schreibt höchstens alle _SAVE_INTERVAL_SEC."""
    global _dirty
    _dirty = True
    if time.time() - _last_save > _SAVE_INTERVAL_SEC:
        _save()


def flush():
    """
    Schreibt ausstehende Änderungen. Nach dem Scan aufgerufen (scorer) und via
    atexit — Letzteres ist wichtig, weil scripts/export_fundamentals_seed.py die
    Datei in einem SEPARATEN Prozess liest, nachdem run_analysis.py beendet ist.
    """
    with _lock:
        if _dirty:
            _save()


atexit.register(flush)


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
        # Seed-Fallback: von GitHub Actions committed — frische Einträge
        # übernehmen statt Netz-Fetch (in den Laufzeit-Cache durchschreiben).
        seed_entry = _load_seed().get(ticker)
        if seed_entry and (now - seed_entry.get("ts", 0)) < ttl_days * 86400:
            _load()[ticker] = seed_entry
            _mark_dirty()
            return seed_entry.get("info", {})

    # Fetch außerhalb des Locks — Netzwerk darf andere Threads nicht blockieren.
    # yfinance begrenzt jeden Request intern auf 30 s (config.retries=0), daher kann
    # .info zwar langsam sein, aber nicht unbegrenzt hängen.
    try:
        raw = yf.Ticker(ticker).info or {}
    except Exception as e:
        logger.debug(f"info-Fetch {ticker} fehlgeschlagen: {e}")
        return {}

    info = {k: raw.get(k) for k in _FIELDS if raw.get(k) is not None}

    with _lock:
        _load()[ticker] = {"ts": now, "info": info}
        _mark_dirty()
    return info
