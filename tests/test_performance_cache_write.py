"""Performance-Cache wird nur bei echten Aenderungen geschrieben (history/performance)."""
import pytest

from history import performance as perf


@pytest.fixture
def log():
    return [{
        "date": "2026-05-07",
        "market_context": {"vix": 15.0},
        "recommendations": [{"ticker": "AAPL", "price": 100.0}],
    }]


def _warm_cache_entry():
    return {
        "performance_1w": 1.0, "performance_1m": 2.0, "performance_3m": 3.0,
        "perf_vs_spy_1m": 0.5, "spy_perf_1m": 1.5, "hit_1m": True,
        "max_drawdown": -4.0, "days_since": 100, "split_rebased": False,
    }


def test_warm_cache_does_not_write(monkeypatch, log):
    """
    Frueher schrieb jeder Seitenaufruf den ~320-KB-Cache neu — zweimal, weil die
    Performance-Seite v1 und v2 getrennt anreichert.
    """
    monkeypatch.setattr(perf, "_load_cache", lambda: {"AAPL_2026-05-07": _warm_cache_entry()})
    writes = []
    monkeypatch.setattr(perf, "_save_cache", lambda c: writes.append(c))
    monkeypatch.setattr(perf, "_compute_performance",
                        lambda *a: pytest.fail("Cache-Treffer haette reichen muessen"))

    flat = perf.enrich_with_performance(log)

    assert len(flat) == 1 and flat[0]["performance_1m"] == 2.0
    assert writes == [], "warmer Cache darf nicht schreiben"


def test_cache_miss_writes_exactly_once(monkeypatch, log):
    monkeypatch.setattr(perf, "_load_cache", dict)
    writes = []
    monkeypatch.setattr(perf, "_save_cache", lambda c: writes.append(c))
    monkeypatch.setattr(perf, "_compute_performance", lambda *a: _warm_cache_entry())

    perf.enrich_with_performance(log)

    assert len(writes) == 1
    assert "AAPL_2026-05-07" in writes[0]


def test_failed_computation_does_not_write(monkeypatch, log):
    """Leeres Ergebnis (z. B. Ticker delisted) landet nicht im Cache."""
    monkeypatch.setattr(perf, "_load_cache", dict)
    writes = []
    monkeypatch.setattr(perf, "_save_cache", lambda c: writes.append(c))
    monkeypatch.setattr(perf, "_compute_performance", lambda *a: {})

    perf.enrich_with_performance(log)

    assert writes == []
