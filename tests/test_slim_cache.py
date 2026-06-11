"""Cache-Slimming (scheduler._slim_for_cache) auf synthetischen Daten."""
import json

import pandas as pd

from scheduler import _slim_for_cache, _make_serializable


def _fake_result():
    idx = pd.bdate_range("2025-01-01", periods=250)
    series = pd.Series([100.123456789 + i for i in range(250)], index=idx)
    rec = {
        "ticker": "AAPL",
        "hist": pd.DataFrame({"Close": series, "Volume": series * 1000,
                              "High": series, "Low": series, "Open": series}),
        "tech": {"score": 0.83, "indicators": {
            **{k: series for k in ("close", "ma50", "ma200", "rsi", "macd_line",
                                   "signal_line", "histogram", "bb_upper", "bb_lower", "bb_ma")},
            "rsi_value": 55.3, "price": 349.12, "bb_pct": 61.0, "ma50_val": 330.0,
        }},
    }
    return {
        "recommendations": [rec],
        "market": {"sp500_hist": series},
        "all_results": [{"ticker": "AAPL"}],
    }


def test_slimming_shrinks_and_keeps_chart_data():
    data = _make_serializable(_fake_result())
    before = len(json.dumps(data))
    _slim_for_cache(data)
    after = len(json.dumps(data))
    assert after < before * 0.45, f"nur {before} -> {after}"

    rec = data["recommendations"][0]
    # hist: nur noch Close, als Liste gerundeter Werte
    assert list(rec["hist"].keys()) == ["Close"]
    assert isinstance(rec["hist"]["Close"], list) and len(rec["hist"]["Close"]) == 250
    assert rec["hist"]["Close"][0] == round(100.123456789, 4)

    ind = rec["tech"]["indicators"]
    assert "close" not in ind and "bb_ma" not in ind
    for key in ("ma50", "ma200", "rsi", "macd_line", "signal_line",
                "histogram", "bb_upper", "bb_lower"):
        assert isinstance(ind[key], list) and len(ind[key]) == 250
    # Skalare bleiben
    assert ind["rsi_value"] == 55.3 and ind["price"] == 349.12


def test_market_chart_keys_untouched():
    # Der Markt-Chart nutzt die Datums-Keys als x-Achse — duerfen nicht wegfallen
    data = _make_serializable(_fake_result())
    _slim_for_cache(data)
    sp = data["market"]["sp500_hist"]
    assert isinstance(sp, dict)
    assert all("-" in k for k in list(sp.keys())[:3])


def test_app_chart_normalizer_handles_all_forms():
    # _series_values: pd.Series / dict / list -> Liste
    from views.recommendations import _series_values
    s = pd.Series([1.0, 2.0])
    assert _series_values(s) == [1.0, 2.0]
    assert _series_values({"a": 1.0, "b": 2.0}) == [1.0, 2.0]
    assert _series_values([1.0, 2.0]) == [1.0, 2.0]
    assert _series_values(None) is None
