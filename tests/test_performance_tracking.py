"""Performance-Tracking-Regressionen (B2): kein Clamping, tz-Normalisierung."""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import history.performance as perf_mod


@pytest.fixture
def fake_hists(monkeypatch):
    hists = {}

    def _fake_load(ticker, start_str, end_date):
        return hists[ticker]

    monkeypatch.setattr(perf_mod, "_load_hist_for_perf", _fake_load)
    return hists


def test_no_clamping_when_history_too_short(fake_hists):
    # Empfehlung vor 60 Tagen, Tickerdaten enden nach 8 Handelstagen (Delisting):
    # 1W-Performance ist messbar, 1M muss None sein (vorher: letzter Kurs als '1M').
    rec_date = date.today() - timedelta(days=60)
    fake_hists["XXXX"] = pd.DataFrame(
        {"Close": np.linspace(50, 55, 8)}, index=pd.bdate_range(rec_date.isoformat(), periods=8))
    fake_hists["SPY"] = pd.DataFrame(
        {"Close": np.linspace(500, 520, 45)}, index=pd.bdate_range(rec_date.isoformat(), periods=45))

    res = perf_mod._compute_performance("XXXX", rec_date.isoformat(), 50.0)
    assert res.get("performance_1w") is not None
    assert res.get("performance_1m") is None


def test_split_rebased_uses_adjusted_entry(fake_hists):
    # Split-Szenario (KLAC, Juni 2026): roh gespeicherter entry_price ~1000 (vor 10:1),
    # die rückwirkend adjustierte Serie startet bei ~100 und steigt auf 110.
    # Alt (Bug): 110/1000-1 = -89 %. Korrekt: 110/100-1 = +10 %, split_rebased=True.
    rec_date = date.today() - timedelta(days=60)
    fake_hists["KLAC"] = pd.DataFrame(
        {"Close": np.linspace(100, 110, 45)}, index=pd.bdate_range(rec_date.isoformat(), periods=45))
    fake_hists["SPY"] = pd.DataFrame(
        {"Close": np.linspace(500, 520, 45)}, index=pd.bdate_range(rec_date.isoformat(), periods=45))

    res = perf_mod._compute_performance("KLAC", rec_date.isoformat(), 1000.0)
    assert res.get("split_rebased") is True
    # Rendite auf adjustierter Basis (~+9–10 %), NICHT der ~-89 %-Artefakt.
    assert res["performance_1m"] > 0
    assert res["performance_1m"] < 20


def test_no_split_flag_for_consistent_entry(fake_hists):
    # Normalfall: entry_price stimmt mit dem adjustierten Einstieg überein → kein Flag.
    rec_date = date.today() - timedelta(days=60)
    fake_hists["AMAT"] = pd.DataFrame(
        {"Close": np.linspace(400, 440, 45)}, index=pd.bdate_range(rec_date.isoformat(), periods=45))
    fake_hists["SPY"] = pd.DataFrame(
        {"Close": np.linspace(500, 520, 45)}, index=pd.bdate_range(rec_date.isoformat(), periods=45))

    res = perf_mod._compute_performance("AMAT", rec_date.isoformat(), 400.0)
    assert res.get("split_rebased") is False
    assert res["performance_1m"] > 0


def test_tz_aware_index_normalized(fake_hists):
    rec_date = date.today() - timedelta(days=60)
    fake_hists["YYYY"] = pd.DataFrame(
        {"Close": np.linspace(50, 60, 45)},
        index=pd.bdate_range(rec_date.isoformat(), periods=45, tz="America/New_York"))
    fake_hists["SPY"] = pd.DataFrame(
        {"Close": np.linspace(500, 520, 45)}, index=pd.bdate_range(rec_date.isoformat(), periods=45))

    res = perf_mod._compute_performance("YYYY", rec_date.isoformat(), 50.0)
    assert res.get("performance_1m") is not None
