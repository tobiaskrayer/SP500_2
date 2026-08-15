"""Fundamentals-Cache: TTL, Seed-Fallback, Schreib-Drosselung, Export-Merge — offline."""
import json
import os
import time

import pytest

import analyzer.fundamentals_cache as fc
import scripts.export_fundamentals_seed as exp


@pytest.fixture
def cache_env(tmp_path, monkeypatch):
    """Isoliert Cache-/Seed-Dateien und blockt Netzwerkzugriffe."""
    cache_file = str(tmp_path / "fundamentals.json")
    seed_file = str(tmp_path / "fundamentals_seed.json")
    monkeypatch.setattr(fc, "_CACHE_FILE", cache_file)
    monkeypatch.setattr(fc, "_SEED_FILE", seed_file)
    monkeypatch.setattr(fc, "_cache", None)
    monkeypatch.setattr(fc, "_seed", None)
    # Schreib-Drosselung zuruecksetzen: sonst haengt das Verhalten davon ab, wie
    # lange der letzte Test her ist (und der atexit-Flush wuerde Testdaten in den
    # echten Cache schreiben).
    monkeypatch.setattr(fc, "_dirty", False)
    monkeypatch.setattr(fc, "_last_save", 0.0)
    # export-Modul bindet die Pfade beim Import -> dort ebenfalls patchen
    monkeypatch.setattr(exp, "_CACHE_FILE", cache_file)
    monkeypatch.setattr(exp, "_SEED_FILE", seed_file)

    fetches = []

    class FakeTicker:
        def __init__(self, ticker):
            fetches.append(ticker)
            self.info = {"trailingPE": 10.0, "longName": f"{ticker} Corp", "sector": "Tech"}

    monkeypatch.setattr(fc.yf, "Ticker", FakeTicker)
    return {"cache": cache_file, "seed": seed_file, "fetches": fetches}


def test_miss_fetches_then_hit_serves_from_cache(cache_env):
    info1 = fc.get_info_cached("AAA")
    assert info1["longName"] == "AAA Corp"
    assert cache_env["fetches"] == ["AAA"]

    info2 = fc.get_info_cached("AAA")
    assert info2 == info1
    assert cache_env["fetches"] == ["AAA"], "Hit hat erneut gefetcht"


def test_expired_entry_refetched(cache_env):
    fc.get_info_cached("AAA")
    with fc._lock:
        fc._load()["AAA"]["ts"] = time.time() - 10 * 86400
    fc.get_info_cached("AAA")
    assert cache_env["fetches"] == ["AAA", "AAA"]


def test_fresh_seed_entry_used_without_fetch(cache_env):
    seed = {"BBB": {"ts": time.time() - 3600, "info": {"longName": "Seed Corp"}}}
    with open(cache_env["seed"], "w", encoding="utf-8") as f:
        json.dump(seed, f)

    info = fc.get_info_cached("BBB")
    assert info["longName"] == "Seed Corp"
    assert cache_env["fetches"] == [], "Seed-Hit hat Netz kontaktiert"
    with fc._lock:
        assert "BBB" in fc._load(), "Seed-Hit nicht in Laufzeit-Cache uebernommen"


def test_stale_seed_entry_ignored(cache_env):
    seed = {"CCC": {"ts": time.time() - 10 * 86400, "info": {"longName": "Stale Corp"}}}
    with open(cache_env["seed"], "w", encoding="utf-8") as f:
        json.dump(seed, f)

    info = fc.get_info_cached("CCC")
    assert info["longName"] == "CCC Corp"   # frisch gefetcht, nicht der Seed
    assert cache_env["fetches"] == ["CCC"]


def test_many_lookups_write_file_at_most_once(cache_env, monkeypatch):
    """
    Frueher schrieb JEDER gecachte Ticker die komplette Datei neu — 50-150
    Rewrites pro Scan, jeweils im Lock. Jetzt drosselt _mark_dirty.
    """
    writes = []
    real_save = fc._save
    monkeypatch.setattr(fc, "_save", lambda: (writes.append(1), real_save())[1])

    for i in range(20):
        fc.get_info_cached(f"T{i}")

    assert len(cache_env["fetches"]) == 20, "alle 20 muessen gefetcht werden"
    assert len(writes) <= 1, f"{len(writes)} Schreibvorgaenge statt hoechstens 1"


def test_flush_writes_pending_changes(cache_env):
    fc._last_save = time.time()     # Drossel aktiv -> _mark_dirty schreibt nicht
    fc.get_info_cached("AAA")
    assert not os.path.exists(cache_env["cache"]), "Drossel hat nicht gegriffen"

    fc.flush()

    with open(cache_env["cache"], encoding="utf-8") as f:
        assert "AAA" in json.load(f)


def test_flush_on_clean_cache_writes_nothing(cache_env, monkeypatch):
    writes = []
    monkeypatch.setattr(fc, "_save", lambda: writes.append(1))

    fc.flush()

    assert writes == []


def test_corrupt_cache_file_does_not_break_lookup(cache_env):
    """Eine kaputte Datei (z. B. "null") darf _load() nicht vergiften."""
    with open(cache_env["cache"], "w", encoding="utf-8") as f:
        f.write("null")
    fc._cache = None

    info = fc.get_info_cached("AAA")
    assert info["longName"] == "AAA Corp"


def test_export_merges_runtime_over_seed_and_prunes(cache_env):
    now = time.time()
    with open(cache_env["seed"], "w", encoding="utf-8") as f:
        json.dump({
            "OLD": {"ts": now - 4 * 86400, "info": {"longName": "Old"}},      # > TTL -> raus
            "DUP": {"ts": now - 3600, "info": {"longName": "Seed-Version"}},
        }, f)
    with open(cache_env["cache"], "w", encoding="utf-8") as f:
        json.dump({
            "DUP": {"ts": now, "info": {"longName": "Runtime-Version"}},
            "NEW": {"ts": now, "info": {"longName": "New"}},
        }, f)

    exp.main()

    with open(cache_env["seed"], encoding="utf-8") as f:
        merged = json.load(f)
    assert "OLD" not in merged
    assert merged["DUP"]["info"]["longName"] == "Runtime-Version"
    assert "NEW" in merged
