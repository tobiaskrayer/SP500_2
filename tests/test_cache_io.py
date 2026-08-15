"""Tages-Cache: fester Pfad, atomares Schreiben, Cleanup (scheduler)."""
import json
import os

import pytest

import scheduler
from storage import write_json_atomic


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Leitet CACHE['dir'] auf ein tmp-Verzeichnis um."""
    d = tmp_path / "cache"
    d.mkdir()
    monkeypatch.setitem(scheduler.CACHE, "dir", str(d))
    return d


def test_save_writes_to_stable_filename(cache_dir):
    scheduler.save_cache({"timestamp": "2026-08-07T21:35:00", "recommendations": []})

    assert (cache_dir / "results_latest.json").exists()
    # Kein Datum im Namen — sonst kehrt der Wochenend-Bug zurueck
    assert not list(cache_dir.glob("results_20*.json"))


def test_load_returns_last_scan_regardless_of_date(cache_dir):
    """
    Der Actions-Job laeuft nur Mo-Fr. Ein am Freitag geschriebener Cache muss am
    Samstag weiterhin geladen werden — genau das war der Wochenend-Ausfall der
    deployten App (frueher: results_<heute>.json, sonst None).
    """
    write_json_atomic(cache_dir / "results_latest.json",
                      {"timestamp": "2026-08-07T21:35:00", "recommendations": [{"ticker": "AAPL"}]})

    loaded = scheduler.load_cache()
    assert loaded is not None, "Cache vom letzten Handelstag muss geladen werden"
    assert loaded["recommendations"][0]["ticker"] == "AAPL"


def test_load_falls_back_to_legacy_dated_file(cache_dir):
    """Checkouts aus der Zeit datierter Dateinamen duerfen nicht leer starten."""
    write_json_atomic(cache_dir / "results_2026-08-07.json", {"timestamp": "alt"})
    write_json_atomic(cache_dir / "results_2026-08-05.json", {"timestamp": "aelter"})

    loaded = scheduler.load_cache()
    assert loaded["timestamp"] == "alt", "neueste Legacy-Datei gewinnt"


def test_load_without_any_cache_returns_none(cache_dir):
    assert scheduler.load_cache() is None


def test_load_today_cache_alias_points_to_load_cache():
    # app.py und tests/test_app_boot.py patchen diesen Namen
    assert scheduler.load_today_cache is scheduler.load_cache


def test_failed_write_leaves_previous_file_intact(cache_dir, monkeypatch):
    """
    Abbruch mitten im Schreiben darf die alte Datei nicht zerstoeren und keine
    .tmp-Leiche hinterlassen (frueher: direktes open(path, "w")).
    """
    path = cache_dir / "results_latest.json"
    write_json_atomic(path, {"timestamp": "gut", "recommendations": []})
    before = path.read_bytes()

    def _boom(*args, **kwargs):
        raise OSError("Platte voll")

    monkeypatch.setattr(json, "dump", _boom)
    scheduler.save_cache({"timestamp": "kaputt"})   # faengt intern, wirft nicht

    assert path.read_bytes() == before, "alte Cache-Datei wurde beschaedigt"
    assert not list(cache_dir.glob("*.tmp")), "tmp-Datei nicht aufgeraeumt"


def test_cleanup_removes_old_dated_files_but_never_latest(cache_dir):
    write_json_atomic(cache_dir / "results_latest.json", {"timestamp": "neu"})
    write_json_atomic(cache_dir / "results_2020-01-01.json", {"timestamp": "uralt"})

    scheduler._cleanup_old_cache()

    assert (cache_dir / "results_latest.json").exists(), "results_latest.json geloescht!"
    assert not (cache_dir / "results_2020-01-01.json").exists()


def test_write_json_atomic_is_compact_by_default(tmp_path):
    path = tmp_path / "x.json"
    write_json_atomic(path, {"a": [1, 2], "b": "c"})
    raw = path.read_text(encoding="utf-8")

    assert raw == '{"a":[1,2],"b":"c"}', "Default muss kompakt sein (Git-Historie)"
    assert json.loads(raw) == {"a": [1, 2], "b": "c"}


def test_write_json_atomic_creates_missing_directory(tmp_path):
    path = tmp_path / "neu" / "tief" / "x.json"
    write_json_atomic(path, {"ok": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_write_json_atomic_tmp_lives_in_target_dir(tmp_path, monkeypatch):
    """
    os.replace ist nur innerhalb eines Dateisystems atomar und scheitert unter
    Windows ueber Verzeichnisgrenzen — die tmp-Datei muss im Zielverzeichnis liegen.
    """
    target = tmp_path / "ziel"
    target.mkdir()
    seen = {}

    real_replace = os.replace

    def _spy(src, dst):
        seen["src_dir"] = os.path.dirname(os.path.abspath(src))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", _spy)
    write_json_atomic(target / "x.json", {"ok": True})

    assert seen["src_dir"] == str(target)
