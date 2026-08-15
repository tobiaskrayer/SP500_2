"""Scan-Rueckgabeschema bei rotem Markt + Scan-Qualitaets-Banner (scorer/app)."""
import pytest

from analyzer import scorer


_EXPECTED_KEYS = {"timestamp", "market", "recommendations", "recommendations_v2",
                  "all_results", "scan_duration_s", "universe", "scan_stats"}


def test_red_market_returns_full_schema(monkeypatch):
    """
    Der Frueh-Return bei rotem Gate 1 muss dieselben Keys liefern wie der
    Erfolgspfad — sonst greift die UI still daneben (Universum-Banner faellt aus,
    v2-Panel meldet faelschlich "aelterer Cache").
    """
    monkeypatch.setattr(scorer, "check_market",
                        lambda: {"passed": False, "reason": "VIX zu hoch", "vix": 30.0})

    def _no_network():
        raise AssertionError("get_sp500_tickers darf bei rotem Markt nicht laufen")

    monkeypatch.setattr(scorer, "get_sp500_tickers", _no_network)

    result = scorer.run_full_scan()

    assert set(result.keys()) == _EXPECTED_KEYS
    assert result["recommendations"] == []
    assert result["recommendations_v2"] == [], "None wuerde als 'alter Cache' gelesen"
    assert result["all_results"] == []
    assert result["universe"] == {"source": None, "n": 0}
    assert result["scan_stats"]["skipped_market_gate"] is True


@pytest.mark.parametrize("analyzed,requested,expect", [
    (300, 503, "error"),     # 60 % — RS-Ranking massiv verzerrt
    (440, 503, "warning"),   # 87 %
    (495, 503, None),        # 98 % — normal
])
def test_scan_quality_banner_levels(monkeypatch, analyzed, requested, expect):
    import app

    calls = []
    for level in ("error", "warning"):
        monkeypatch.setattr(app.st, level,
                            lambda *a, _l=level, **k: calls.append(_l))

    app._render_scan_quality_warning({
        "universe": {"source": "wikipedia", "n": requested},
        "scan_stats": {"requested": requested, "analyzed": analyzed,
                       "rs_ranked": analyzed, "skipped_market_gate": False},
    })

    assert calls == ([expect] if expect else [])


def test_scan_quality_banner_silent_for_old_caches(monkeypatch):
    """Caches ohne scan_stats duerfen keine Warnung ausloesen."""
    import app

    calls = []
    for level in ("error", "warning"):
        monkeypatch.setattr(app.st, level, lambda *a, **k: calls.append(level))

    app._render_scan_quality_warning({"universe": {"source": "wikipedia", "n": 503}})
    app._render_scan_quality_warning(None)

    assert calls == []


def test_scan_quality_banner_silent_when_market_gate_skipped(monkeypatch):
    """Rotes Gate 1: kein Scan gelaufen, also nichts zu bemaengeln."""
    import app

    calls = []
    for level in ("error", "warning"):
        monkeypatch.setattr(app.st, level, lambda *a, **k: calls.append(level))

    app._render_scan_quality_warning({
        "universe": {"source": None, "n": 0},
        "scan_stats": {"requested": 0, "analyzed": 0, "skipped_market_gate": True},
    })

    assert calls == []
