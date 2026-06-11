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
