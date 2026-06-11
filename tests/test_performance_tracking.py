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


def test_tz_aware_index_normalized(fake_hists):
    rec_date = date.today() - timedelta(days=60)
    fake_hists["YYYY"] = pd.DataFrame(
        {"Close": np.linspace(50, 60, 45)},
        index=pd.bdate_range(rec_date.isoformat(), periods=45, tz="America/New_York"))
    fake_hists["SPY"] = pd.DataFrame(
        {"Close": np.linspace(500, 520, 45)}, index=pd.bdate_range(rec_date.isoformat(), periods=45))

    res = perf_mod._compute_performance("YYYY", rec_date.isoformat(), 50.0)
    assert res.get("performance_1m") is not None
