"""
Täglicher Hintergrund-Job: Führt den Scan einmal täglich durch
und speichert das Ergebnis im Cache.
Wird von app.py beim Start gestartet.
"""

import json
import os
import time
import logging
import threading
from datetime import datetime, date
from pathlib import Path

from config import CACHE

logger = logging.getLogger(__name__)

_scan_running = False
_scan_started_at: float | None = None  # time.time() bei Start des laufenden Scans
_scan_epoch = 0                         # Generations-Zähler; steigt bei force-Restart
_scan_lock = threading.Lock()

# Ein Scan, der länger als das hier läuft, gilt als "möglicherweise verhakt".
# Ein normaler Full-Scan über das S&P500-Universum dauert nur wenige Minuten.
SCAN_STALE_AFTER_SEC = 15 * 60


def get_cache_path(for_date: date = None) -> Path:
    d = for_date or date.today()
    return Path(CACHE["dir"]) / f"results_{d.isoformat()}.json"


def load_today_cache() -> dict | None:
    """Lädt den Cache von heute, falls vorhanden. Sonst None."""
    path = get_cache_path()
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            logger.info(f"Cache geladen: {path}")
            return data
        except Exception as e:
            logger.warning(f"Cache-Lesefehler: {e}")
    return None


def save_cache(data: dict):
    """Speichert die Scan-Ergebnisse in den Tages-Cache."""
    Path(CACHE["dir"]).mkdir(exist_ok=True)
    path = get_cache_path()
    try:
        # Serialisierbare Kopie erstellen (pandas-Objekte entfernen)
        serializable = _make_serializable(data)
        _slim_for_cache(serializable)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False)
        logger.info(f"Cache gespeichert: {path}")
        _cleanup_old_cache()
    except Exception as e:
        logger.error(f"Cache-Schreibfehler: {e}")


# Chart-Serien in tech.indicators, die die App tatsächlich zeichnet.
# "close" (redundant zu hist.Close) und "bb_ma" (ungenutzt) fliegen raus.
_CHART_SERIES = ("ma50", "ma200", "rsi", "macd_line", "signal_line",
                 "histogram", "bb_upper", "bb_lower")


def _slim_for_cache(serializable: dict):
    """
    Verschlankt die Empfehlungs-Dicts für die Cache-Datei (in-place).

    Die Detail-Charts brauchen nur Werte-Listen (geplottet wird über die
    Position, nicht das Datum) — als Series→Dict serialisiert schleppen sie
    aber ~27 Zeichen Datums-Key pro Punkt mit. Listen + Rundung auf 4
    Nachkommastellen reduzieren die Datei von ~6 MB auf unter 1 MB; das zählt,
    weil GitHub Actions sie täglich ins Repo committed (Git-Historie wächst
    sonst unbegrenzt). Der Markt-Chart nutzt die Datums-Keys als x-Achse —
    market bleibt deshalb unberührt.
    """
    def _vals(obj) -> list | None:
        if isinstance(obj, dict):
            obj = list(obj.values())
        if isinstance(obj, list):
            return [None if v is None else round(v, 4) for v in obj]
        return None

    for rec in serializable.get("recommendations", []):
        hist = rec.get("hist")
        if isinstance(hist, dict):
            close = _vals(hist.get("Close"))
            rec["hist"] = {"Close": close} if close is not None else None

        ind = (rec.get("tech") or {}).get("indicators")
        if isinstance(ind, dict):
            ind.pop("close", None)
            ind.pop("bb_ma", None)
            for key in _CHART_SERIES:
                vals = _vals(ind.get(key))
                if vals is not None:
                    ind[key] = vals


def _make_serializable(data: dict) -> dict:
    """Wandelt nicht-serialisierbare Objekte (pandas, numpy) in JSON-kompatible um."""
    import numpy as np
    import pandas as pd

    if isinstance(data, dict):
        return {k: _make_serializable(v) for k, v in data.items()}
    if isinstance(data, list):
        return [_make_serializable(v) for v in data]
    if isinstance(data, pd.Series):
        return {str(k): (None if (pd.isna(v) or not np.isfinite(v)) else float(v)) for k, v in data.items()}
    if isinstance(data, pd.DataFrame):
        return data.to_dict(orient="list")
    if isinstance(data, (np.integer,)):
        return int(data)
    if isinstance(data, (np.floating,)):
        return None if not np.isfinite(data) else float(data)
    if isinstance(data, (np.bool_,)):
        return bool(data)
    if isinstance(data, np.ndarray):
        return [_make_serializable(v) for v in data.tolist()]
    if isinstance(data, (pd.Timestamp, np.datetime64)):
        return str(data)
    if isinstance(data, float) and not np.isfinite(data):
        return None
    return data


def _cleanup_old_cache():
    """Löscht Cache-Dateien älter als CACHE['max_age_days'] Tage."""
    cache_dir = Path(CACHE["dir"])
    if not cache_dir.exists():
        return
    today = date.today()
    for f in cache_dir.glob("results_*.json"):
        try:
            file_date = date.fromisoformat(f.stem.replace("results_", ""))
            if (today - file_date).days > CACHE["max_age_days"]:
                f.unlink()
                logger.info(f"Alter Cache gelöscht: {f}")
        except Exception:
            pass


def is_scan_running() -> bool:
    return _scan_running


def scan_runtime_seconds() -> float | None:
    """Sekunden seit Start des laufenden Scans, oder None wenn keiner läuft."""
    if not _scan_running or _scan_started_at is None:
        return None
    return max(0.0, time.time() - _scan_started_at)


def scan_looks_stale() -> bool:
    """True, wenn der laufende Scan ungewöhnlich lange dauert (vermutlich verhakt)."""
    rt = scan_runtime_seconds()
    return rt is not None and rt > SCAN_STALE_AFTER_SEC


def force_reset_scan():
    """
    Setzt den Scan-Status hart zurück — Notausstieg, falls sich ein Scan verhakt hat.

    Der laufende Hintergrund-Thread wird per Epoch-Wechsel entkoppelt: Er kann den
    Status danach nicht mehr verändern und seine Ergebnisse werden verworfen. Python
    kann den Thread nicht hart killen — ein an einem Netzwerk-Call hängender Scan läuft
    als Zombie weiter, bis der Call zurückkehrt, beeinflusst den Status aber nicht mehr.
    """
    global _scan_running, _scan_started_at, _scan_epoch
    with _scan_lock:
        _scan_epoch += 1
        _scan_running = False
        _scan_started_at = None
    logger.info("Scan-Status zurückgesetzt (force reset)")


def trigger_scan_background(on_complete=None, force=False):
    """
    Startet den Scan in einem Hintergrund-Thread.

    force=True bricht einen evtl. verhakten laufenden Scan ab und startet frisch:
    Der alte Thread wird per Epoch entkoppelt und kann Status/Ergebnis nicht mehr
    beeinflussen.
    """
    global _scan_running, _scan_started_at, _scan_epoch

    with _scan_lock:
        if _scan_running and not force:
            logger.info("Scan läuft bereits")
            return
        if force:
            _scan_epoch += 1  # laufenden Thread entkoppeln
        my_epoch = _scan_epoch
        _scan_running = True  # innerhalb des Locks setzen — verhindert Race Condition
        _scan_started_at = time.time()

    def _run():
        global _scan_running, _scan_started_at
        try:
            from analyzer.scorer import run_full_scan
            logger.info("Hintergrund-Scan gestartet")
            result = run_full_scan()
            # Nur committen, wenn dieser Scan noch der aktuelle ist (kein force-Restart dazwischen).
            with _scan_lock:
                superseded = my_epoch != _scan_epoch
            if superseded:
                logger.info("Scan-Ergebnis verworfen — durch Neustart ersetzt")
                return
            save_cache(result)
            # Empfehlungen für Performance-Tracking historisieren
            try:
                from history.logger import append_scan_result
                append_scan_result(result)
            except Exception as hist_err:
                logger.warning(f"History-Logging fehlgeschlagen: {hist_err}")
            if on_complete:
                on_complete(result)
        except Exception as e:
            logger.error(f"Hintergrund-Scan fehlgeschlagen: {e}")
        finally:
            # Status nur freigeben, wenn dieser Thread noch der aktuelle ist — ein
            # zwischenzeitlicher force-Restart hat sonst schon einen neuen Scan gesetzt.
            with _scan_lock:
                if my_epoch == _scan_epoch:
                    _scan_running = False
                    _scan_started_at = None

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def start_daily_scheduler(app_state: dict):
    """
    Startet einen täglichen Scheduler (apscheduler).
    Führt täglich um config.CACHE['refresh_hour'] Uhr einen neuen Scan durch.
    """
    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        def daily_job():
            logger.info("Täglicher Scan gestartet (Scheduler)")
            trigger_scan_background(
                on_complete=lambda r: app_state.update({"scan_result": r, "last_update": datetime.now().isoformat()})
            )

        scheduler = BackgroundScheduler()
        scheduler.add_job(
            daily_job,
            trigger="cron",
            hour=CACHE["refresh_hour"],
            minute=0,
        )
        scheduler.start()
        logger.info(f"Täglicher Scheduler aktiv (täglich um {CACHE['refresh_hour']}:00 Uhr)")
        return scheduler
    except ImportError:
        logger.warning("apscheduler nicht installiert — kein automatischer Scheduler")
        return None
