"""
Render-Smoke-Test: bootet die Streamlit-App headless (AppTest) und rendert
die datengetriebenen Seiten mit einem committeten Scan-Ergebnis — komplett
offline (Auth gemockt, Scheduler aus, kein yfinance).

Fängt genau die Fehlerklasse, die reine Import-Tests nicht sehen:
NameError/AttributeError im Render-Pfad nach dem app.py-Split.
"""
import glob
import json
import os

import pytest
from streamlit.testing.v1 import AppTest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def offline_app(monkeypatch):
    monkeypatch.setenv("IS_STREAMLIT_CLOUD", "1")   # kein apscheduler-Thread

    import portfolio.auth as auth
    monkeypatch.setattr(auth, "render_auth_gate", lambda: True)
    monkeypatch.setattr(auth, "render_logout_button", lambda: None)

    results = sorted(glob.glob(os.path.join(ROOT, "cache", "results_*.json")))
    if not results:
        pytest.skip("kein committetes Scan-Ergebnis im Repo")
    with open(results[-1], encoding="utf-8") as f:
        cached = json.load(f)

    import scheduler
    monkeypatch.setattr(scheduler, "load_today_cache", lambda: cached)

    return AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)


def _assert_clean(at):
    assert not at.exception, f"Render-Exception: {at.exception[0].value if at.exception else ''}"


def test_default_page_market_overview(offline_app):
    at = offline_app.run()
    _assert_clean(at)


@pytest.mark.parametrize("nav_label", [
    "🛒 Kauf-Kandidaten",
    "🎯 Empfehlungen",
    "🔍 Vollständiger Scan",
])
def test_offline_pages_render(offline_app, nav_label):
    at = offline_app
    at.session_state["top_nav"] = nav_label
    at.run()
    _assert_clean(at)


@pytest.mark.parametrize("nav_label", ["🛒 Kauf-Kandidaten", "🎯 Empfehlungen"])
def test_active_v2_pages_and_cache_refresh(monkeypatch, nav_label):
    """Synthetic bullish data ensures detail/chart code actually executes."""
    monkeypatch.setenv("IS_STREAMLIT_CLOUD", "1")
    import portfolio.auth as auth
    import scheduler
    from analyzer.strategy import strategy_metadata
    from analyzer.sessions import last_completed_session
    monkeypatch.setattr(auth, "render_auth_gate", lambda: True)
    monkeypatch.setattr(auth, "render_logout_button", lambda: None)
    def result(ticker):
        return {"timestamp": "2026-09-25T21:00:00Z", "strategy": strategy_metadata(),
                "market": {"passed": True, "data_as_of": str(last_completed_session())},
                "recommendations_v2": [{"ticker": ticker, "v2_rank": 1, "price": 100.,
                    "combined_score": .85, "rs": {"rs_score": 20., "rs_6m": 10.},
                    "hist": {"Close": [99., 100.]}, "chart_dates": ["2026-09-24", "2026-09-25"],
                    "tech": {"indicators": {"ma50": [98., 99.]}}}]}
    state = {"result": result("AAA"), "fingerprint": (1, 1)}
    monkeypatch.setattr(scheduler, "load_today_cache", lambda: state["result"])
    monkeypatch.setattr(scheduler, "cache_fingerprint", lambda: state["fingerprint"])
    at = AppTest.from_file(os.path.join(ROOT, "app.py"), default_timeout=60)
    at.session_state["top_nav"] = nav_label
    at.run()
    _assert_clean(at)
    assert at.selectbox[0].value == "AAA"
    assert any(metric.value == "85/100" for metric in at.metric)
    state.update(result=result("BBB"), fingerprint=(2, 2))
    at.run()
    _assert_clean(at)
    assert at.selectbox[0].value == "BBB"
