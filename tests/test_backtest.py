"""Backtest-Regressionen: Forward-Return (B1), bt_dates-Generierung, DD-Cache."""
from datetime import date

import numpy as np
import pandas as pd

from backtest.runner import _forward_return, _make_bt_dates


def _price_df():
    # Handelstage Mo-Fr, 100 Tage ab 2024-01-01, Kurs steigt 1/Tag (100..199)
    idx = pd.bdate_range("2024-01-01", periods=100)
    return pd.DataFrame({"close": np.arange(100, 200, dtype=float)}, index=idx)


class TestForwardReturn:
    def test_weekend_takes_first_trading_day_after_target(self):
        # from 2024-01-05 (Fr, Kurs 104), +30 Tage = So 2024-02-04
        # -> erster Handelstag >= target ist Mo 2024-02-05 (Kurs 125)
        r = _forward_return(_price_df(), date(2024, 1, 5), 30)
        assert r == round((125 / 104 - 1) * 100, 2)

    def test_delisting_returns_none(self):
        # Daten enden vor target -> None statt verkuerzter Periode als 1M-Return
        assert _forward_return(_price_df(), date(2024, 5, 1), 30) is None

    def test_target_on_trading_day_is_exact(self):
        # +31 Tage = Mo 2024-02-05 -> exakt dieser Tag
        r = _forward_return(_price_df(), date(2024, 1, 5), 31)
        assert r == round((125 / 104 - 1) * 100, 2)


class TestBtDates:
    def test_weekend_start_yields_nonempty(self):
        # Regression: Mit Wochentagsfilter war die Liste LEER, wenn das
        # Startdatum auf ein Wochenende fiel (14-Tage-Schritt = fixer Wochentag).
        dates = _make_bt_dates(10, 2, end_date=date(2026, 5, 5))  # Start = Sa 2016-05-07
        assert len(dates) == 261
        assert dates[0] == date(2016, 5, 7)

    def test_step_width(self):
        dates = _make_bt_dates(1, 2, end_date=date(2026, 1, 1))
        assert all((b - a).days == 14 for a, b in zip(dates, dates[1:]))


class TestDDCacheValidation:
    def test_empty_cache_blob_rejected(self, tmp_path, monkeypatch):
        # Regression: leeres/korruptes Pickle wurde als gueltig akzeptiert
        import pickle
        import backtest.compare as cmp

        blob = {"years": 10, "step_weeks": 2, "bt_dates": [], "date_data": {}}
        p = tmp_path / "enriched_dd.pkl"
        with open(p, "wb") as f:
            pickle.dump(blob, f)
        monkeypatch.setattr(cmp, "_DD_CACHE", str(p))

        called = {}

        def fake_build(years, step_weeks, progress_callback=None):
            called["rebuilt"] = True
            raise RuntimeError("rebuild ausgeloest")  # reicht: Cache wurde verworfen

        monkeypatch.setattr(cmp, "_build_precomputed", fake_build)
        try:
            cmp.get_date_data(10, 2)
        except RuntimeError:
            pass
        assert called.get("rebuilt"), "Leerer DD-Cache wurde faelschlich akzeptiert"
