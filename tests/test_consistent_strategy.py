"""Offline regression checks for selection, execution and capital constraints."""
from datetime import date
import pandas as pd
import pytest

from analyzer.strategy import SelectionInput, select, evaluate_market
from analyzer.sessions import last_completed_session
from analyzer.allocation import allocate
from backtest.equity import simulate_equity


def test_v2_does_not_require_v1_technical_score():
    decisions = select([SelectionInput("A", 50, 10, False, True, True)])
    assert decisions["A"].recommended_v2
    assert not decisions["A"].recommended


def test_percentiles_include_technically_ineligible_stocks():
    inputs = [SelectionInput(str(i), i, 10, i == 0, i == 0, True) for i in range(10)]
    assert not any(d.recommended_v2 for d in select(inputs).values())
    assert not any(d.recommended for d in select(inputs).values())


def test_missing_market_input_fails_closed():
    assert not evaluate_market(100, 100, 100, None)["passed"]
    assert evaluate_market(99, 100, 100, 15)["passed"]


@pytest.mark.parametrize("timestamp, expected", [
    ("2026-07-03 23:00:00Z", date(2026, 7, 2)),
    ("2026-11-27 18:14:00Z", date(2026, 11, 25)),
    ("2026-11-27 18:16:00Z", date(2026, 11, 27)),
    ("2026-03-09 20:14:00Z", date(2026, 3, 6)),
    ("2026-03-09 20:16:00Z", date(2026, 3, 9)),
])
def test_completed_session_holidays_early_close_dst(timestamp, expected):
    assert last_completed_session(timestamp) == expected


def test_allocation_existing_exposure_and_cash():
    candidates = [{"ticker": tk, "sector": "Tech"} for tk in ("A", "B", "C", "D")]
    result = allocate(candidates, 8000, [{"ticker": "A", "sector": "Tech", "value": 2000}])
    assert result["positions"]["A"] == 0
    assert sum(result["positions"].values()) <= 1000
    assert sum(result["positions"].values()) + result["cash_remaining"] == 8000


def test_equity_next_open_costs_cash_and_drawdown():
    dates = pd.bdate_range("2026-01-05", periods=5)
    spy = pd.DataFrame({"open": 100., "close": 100.}, index=dates)
    stock = pd.DataFrame({"open": [1, 100, 100, 80, 80],
                          "close": [1, 100, 80, 80, 80]}, index=dates)
    result = simulate_equity({"SPY": spy, "A": stock},
                            [{"date": "2026-01-05", "ticker": "A"}],
                            dates[0], dates[-1], holding_days=2, cost_bps=10)
    trade = result["trades"][0]
    assert trade["entry_date"] == "2026-01-06"
    assert trade["exit_date"] == "2026-01-08"
    assert trade["return_pct"] == pytest.approx((80 * .999 / (100 * 1.001) - 1) * 100)
    assert min(x["cash"] for x in result["curve"]) >= 9000 - 1e-8
    assert result["max_drawdown_pct"] == pytest.approx(result["return_pct"])
    assert result["return_pct"] == pytest.approx(trade["return_pct"] * .1)


def test_missing_open_does_not_invent_entry():
    dates = pd.bdate_range("2026-01-05", periods=3)
    spy = pd.DataFrame({"open": 100., "close": 100.}, index=dates)
    result = simulate_equity({"SPY": spy, "A": spy.drop(columns="open")},
                            [{"date": str(dates[0].date()), "ticker": "A"}], dates[0], dates[-1])
    assert result["open_positions"] == 0
    assert result["return_pct"] == 0


def test_versioned_history_keeps_previous_scan(tmp_path, monkeypatch):
    from history import logger
    monkeypatch.setattr(logger, "SHARD_DIR", str(tmp_path))
    first = {"timestamp": "2026-09-25T21:00:00Z", "strategy": {"version": "a"}}
    second = {"timestamp": "2026-09-25T22:00:00Z", "strategy": {"version": "b"}}
    logger.append_scan_result(first)
    logger.append_scan_result(second)
    import json
    data = json.loads((tmp_path / "2026-09.json").read_text())
    assert data[0]["strategy"]["version"] == "b"
    assert data[0]["revisions"][0]["strategy"]["version"] == "a"


def test_price_cache_rejects_short_overwrite_and_stale_data(tmp_path, monkeypatch):
    from analyzer import price_cache
    monkeypatch.setattr(price_cache, "_CACHE_DIR", str(tmp_path))
    monkeypatch.setattr(price_cache, "last_completed_session", lambda: date(2026, 1, 5))
    index = pd.bdate_range(end="2026-01-05", periods=220)
    full = pd.DataFrame({"Close": 100.}, index=index)
    price_cache.save("A", full)
    price_cache.save("A", full.tail(20))
    assert len(price_cache.load("A")) == 220
    monkeypatch.setattr(price_cache, "last_completed_session", lambda: date(2026, 1, 6))
    assert price_cache.load("A") is None


def test_v2_only_analysis_loads_fundamentals(monkeypatch):
    from analyzer import scorer
    index = pd.bdate_range(end="2026-01-05", periods=220)
    hist = pd.DataFrame({"Close": 100.}, index=index)
    monkeypatch.setattr(scorer, "last_completed_session", lambda: date(2026, 1, 5))
    monkeypatch.setattr(scorer, "check_relative_strength", lambda *a: {"passed": True, "rs_score": 20, "rs_6m": 10})
    monkeypatch.setattr(scorer, "check_technical", lambda *a: {
        "passed": False, "score": .5,
        "signals": {"Kurs über 50-Tage-MA": True, "Kurs über 200-Tage-MA": True,
                    "Nicht überkauft (Bollinger)": True},
        "indicators": {"rsi_value": 60, "price": 100}})
    fetched = []
    def info(ticker):
        fetched.append(ticker)
        return {"longName": "Example", "trailingPE": 10, "revenueGrowth": .2,
                "profitMargins": .2, "debtToEquity": 10, "freeCashflow": 100}
    monkeypatch.setattr(scorer, "get_info_cached", info)
    monkeypatch.setattr(scorer, "compute_exits", lambda *a, **kw: {"signals": {}, "atr": 1})
    monkeypatch.setattr(scorer, "compute_upside", lambda **kw: {})
    result = scorer._analyze_ticker("A", hist["Close"], hist, {"passed": True})
    assert result is not None
    decisions = scorer._apply_rs_percentile([result], {"passed": True})
    assert fetched == ["A"]
    assert decisions[0]["recommended_v2"]
    assert not decisions[0]["recommended"]


def test_backtest_selection_matches_live_for_complete_inputs():
    from backtest.compare import _select_v2, PARAMS_V2
    data = {str(i): {"rs_score": i, "rs_6m": 10,
                    "row": {"above_ma50": i % 2 == 0, "above_ma200": True,
                            "rsi": 60, "bb_ok": True, "macd_bull": False, "vol_ratio": 0}}
            for i in range(10)}
    live = select([SelectionInput(tk, td["rs_score"], 10, False,
                                  td["row"]["above_ma50"], True) for tk, td in data.items()])
    assert [tk for tk, _ in _select_v2(data, PARAMS_V2)] == [
        tk for tk, decision in live.items() if decision.recommended_v2]


def test_standard_backtest_includes_v2_equity(monkeypatch):
    from backtest import runner, compare
    dates = pd.bdate_range("2026-01-05", periods=40)
    frame = pd.DataFrame({"open": 100., "close": 100.}, index=dates)
    signal_date = dates[0].date()
    monkeypatch.setattr(runner, "_build_precomputed", lambda *a: ({"A": frame}, frame, [signal_date], ["A"]))
    row = {"above_ma50": True, "above_ma200": True, "rsi": 60,
           "bb_ok": True, "macd_bull": False, "vol_ratio": 0}
    monkeypatch.setattr(compare, "_build_enriched_date_data", lambda *a: {signal_date: {
        "ticker_data": {"A": {"row": row, "price": 100., "rs_score": 20, "rs_6m": 10, "p1m": 0, "p3m": None}},
        "spy_perf_1m": 0, "spy_perf_3m": None}})
    monkeypatch.setattr(runner, "_save_results", lambda *a: None)
    result = runner.run_backtest()
    assert result["selection"] == "v2"
    assert result["total_trades"] == 1
    assert len(result["equity"]["trades"]) == 1
    assert result["equity"]["return_pct"] < 0  # flat prices, positive trading costs
