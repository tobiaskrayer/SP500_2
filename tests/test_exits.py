"""Exit-Signal-Regression (B6): 6M-Lookback exakt 126 Handelstage."""
import pandas as pd

from analyzer.exits import _rs_negative_6m


def test_lookback_sees_value_126_days_back():
    # 127 Punkte: erster Wert 100, Rest 99 -> Kurs vor 126 Handelstagen war hoeher
    s = pd.Series([100.0] + [99.0] * 126)
    assert _rs_negative_6m(s) is True


def test_lookback_not_off_by_one():
    # erster Wert 98 (vor 126 Tagen), Rest 99 -> nicht negativ
    s = pd.Series([98.0] + [99.0] * 126)
    assert _rs_negative_6m(s) is False
