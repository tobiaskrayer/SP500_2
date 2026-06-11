"""Universum-Fallback-Kette — offline (Wikipedia-Abruf gemockt)."""
import json

import pytest

import analyzer.universe as u


@pytest.fixture
def universe_env(tmp_path, monkeypatch):
    cache = str(tmp_path / "sp500_universe.json")
    monkeypatch.setattr(u, "_UNIVERSE_CACHE", cache)
    monkeypatch.setattr(u, "_last_info", {"source": None, "n": 0})
    return {"cache": cache, "monkeypatch": monkeypatch}


def _break_wikipedia(monkeypatch):
    def _raise(*a, **kw):
        raise ConnectionError("offline")
    monkeypatch.setattr(u.pd, "read_html", _raise)


def test_cache_fallback_when_wikipedia_down(universe_env):
    table = [[f"TK{i:03d}", f"Firma {i}"] for i in range(450)]
    with open(universe_env["cache"], "w", encoding="utf-8") as f:
        json.dump(table, f)
    _break_wikipedia(universe_env["monkeypatch"])

    tickers = u.get_sp500_tickers()
    info = u.get_universe_info()
    assert info["source"] == "cache" and info["n"] == 450
    assert len(tickers) == 450


def test_hardcoded_fallback_without_cache(universe_env):
    _break_wikipedia(universe_env["monkeypatch"])
    tickers = u.get_sp500_tickers()
    info = u.get_universe_info()
    assert info["source"] == "fallback"
    assert 90 <= len(tickers) <= 110


def test_tiny_cache_rejected(universe_env):
    # Cache mit Mini-Universum (<400) darf nicht verwendet werden
    with open(universe_env["cache"], "w", encoding="utf-8") as f:
        json.dump([["A", "A Corp"]], f)
    _break_wikipedia(universe_env["monkeypatch"])
    u.get_sp500_tickers()
    assert u.get_universe_info()["source"] == "fallback"


def test_partial_wikipedia_response_rejected(universe_env, monkeypatch):
    # Wikipedia liefert nur 50 Zeilen (Layout-Aenderung) -> Fallback statt Mini-Universum
    import pandas as pd
    df = pd.DataFrame({"Symbol": [f"T{i}" for i in range(50)],
                       "Security": [f"Firma {i}" for i in range(50)]})
    monkeypatch.setattr(u.pd, "read_html", lambda *a, **kw: [df])
    u.get_sp500_tickers()
    assert u.get_universe_info()["source"] == "fallback"
