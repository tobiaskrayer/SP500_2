"""
S&P500 Aktienanalyse-Dashboard
Streamlit Web-App — starten mit: streamlit run app.py
"""

import streamlit as st
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="S&P500 Analyse",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Initialisierung ──────────────────────────────────────────────────────────

def init_app():
    if "scan_result" not in st.session_state:
        st.session_state.scan_result = None
    if "scheduler_started" not in st.session_state:
        st.session_state.scheduler_started = False
    if "scan_progress" not in st.session_state:
        st.session_state.scan_progress = None

    # Cache laden
    if st.session_state.scan_result is None:
        from scheduler import load_today_cache
        cached = load_today_cache()
        if cached:
            st.session_state.scan_result = cached

    # Scheduler nur lokal starten, nicht auf Streamlit Cloud
    # (auf Streamlit Cloud übernimmt GitHub Actions die tägliche Aktualisierung)
    if not st.session_state.scheduler_started:
        import os
        is_streamlit_cloud = os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("IS_STREAMLIT_CLOUD")
        if not is_streamlit_cloud:
            from scheduler import start_daily_scheduler
            app_state = {}
            start_daily_scheduler(app_state)
        st.session_state.scheduler_started = True



# Seiten-Module (eine Datei pro Seite)
from views.common import _fmt_ts
from views.market import page_market_overview
from views.candidates import page_buy_candidates
from views.recommendations import page_recommendations
from views.full_scan import page_full_scan
from views.portfolio_page import page_portfolio
from views.performance import page_performance
from views.backtest_page import page_backtest

# ── Navigation ────────────────────────────────────────────────────────────────

_PAGES = ["Marktübersicht", "Empfehlungen", "Kauf-Kandidaten", "Mein Portfolio", "Performance", "Backtest", "Vollständiger Scan"]
_PAGE_ICONS = {
    "Marktübersicht": "📊",
    "Empfehlungen": "🎯",
    "Kauf-Kandidaten": "🛒",
    "Mein Portfolio": "💼",
    "Performance": "📈",
    "Backtest": "🔬",
    "Vollständiger Scan": "🔍",
}
_PAGE_LABELS = [f"{_PAGE_ICONS[p]} {p}" for p in _PAGES]


def render_top_nav() -> str:
    """Horizontale Top-Navigation (Pills). Funktioniert auf Handy ohne Sidebar-Fummelei."""
    try:
        choice = st.pills(
            "Navigation",
            _PAGE_LABELS,
            default=_PAGE_LABELS[0],
            label_visibility="collapsed",
            key="top_nav",
        )
    except AttributeError:
        # Fallback für ältere Streamlit-Versionen ohne st.pills
        choice = st.radio(
            "Navigation",
            _PAGE_LABELS,
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            key="top_nav",
        )
    if choice is None:
        choice = _PAGE_LABELS[0]
    return _PAGES[_PAGE_LABELS.index(choice)]


def render_sidebar_secondary():
    """Sidebar: nur noch sekundäre Infos (Scan-Button lokal, Timestamp, Disclaimer)."""
    with st.sidebar:
        st.title("📈 S&P500 Analyse")
        st.caption("Sehr konservative Kaufempfehlungen")
        st.divider()

        from portfolio.auth import render_logout_button
        render_logout_button()
        st.divider()

        import os
        on_cloud = bool(os.environ.get("STREAMLIT_SHARING_MODE") or os.environ.get("IS_STREAMLIT_CLOUD"))
        if on_cloud:
            st.caption("Aktualisierung täglich via GitHub Actions")
        else:
            # Alle Scheduler-Funktionen in EINEM Import — schlägt er fehl (z. B. weil
            # Streamlit Cloud nach einem Deploy ein veraltetes scheduler-Modul gecacht
            # hat), degradiert die UI sauber auf den Start-Button statt zu crashen.
            scan_running = False
            runtime_fn = stale_fn = None
            try:
                from scheduler import is_scan_running, scan_runtime_seconds, scan_looks_stale
                scan_running = is_scan_running()
                runtime_fn, stale_fn = scan_runtime_seconds, scan_looks_stale
            except Exception:
                pass
            if scan_running:
                rt = runtime_fn() if runtime_fn else None
                mins = int(rt // 60) if rt else 0
                if stale_fn and stale_fn():
                    st.warning(
                        f"Scan läuft seit {mins} min — das dauert ungewöhnlich lange "
                        "und hängt vermutlich. Starte ihn unten neu.",
                        icon="⚠️",
                    )
                else:
                    st.info(f"Scan läuft… (seit {mins} min)")
                # Immer anklickbar — Notausstieg, falls sich der Scan verhakt hat.
                if st.button("Scan abbrechen & neu starten", use_container_width=True):
                    _force_restart_scan()
            else:
                if st.button("Analyse neu starten", use_container_width=True, type="primary"):
                    _start_scan()

        if st.session_state.scan_result:
            ts = st.session_state.scan_result.get("timestamp", "")
            if ts:
                st.caption(f"Letzte Analyse: {_fmt_ts(ts)}")

        st.divider()
        st.caption("Datenquelle: Yahoo Finance (yfinance)")
        st.caption("Kein Anlageberater — nur zur Information")


def _start_scan():
    from scheduler import trigger_scan_background

    trigger_scan_background()
    st.rerun()


def _force_restart_scan():
    """Verhakten Scan abbrechen und komplett von vorne starten."""
    from scheduler import trigger_scan_background

    trigger_scan_background(force=True)
    st.rerun()


# ── Hauptschleife ─────────────────────────────────────────────────────────────

def _render_scan_quality_warning(result: dict | None):
    """
    Banner, wenn der Scan auf einer geschrumpften Datenbasis lief.

    Zwei Ursachen, gleiche Folge: Das RS-Perzentil-Ranking (Gate 2) wird relativ
    zur tatsächlich ausgewerteten Menge berechnet — jede Lücke verschiebt alle
    Schwellen.
      1. Tickerliste degradiert (Wikipedia-Abruf gescheitert → Cache/Top-100).
      2. Viele Titel an Datenfehlern gescheitert (yfinance-Ausfälle); die fallen
         nach einem Retry still weg.
    """
    if not result:
        return

    uni = result.get("universe") or {}
    source, n = uni.get("source"), uni.get("n", 0)
    if source is None:
        return  # kein Scan gelaufen (rotes Gate 1) oder älterer Cache ohne Metadaten

    if source == "fallback" or (n and n < 400):
        st.error(
            f"⚠️ **Degradiertes Universum:** Dieser Scan lief nur über {n} Titel "
            f"(Quelle: {source}). Das RS-Ranking ist dadurch verzerrt — Empfehlungen "
            f"mit Vorsicht behandeln und Scan später wiederholen.",
            icon="🚨",
        )
    elif source == "cache":
        st.warning(
            f"Wikipedia war beim Scan nicht erreichbar — Tickerliste kam aus dem "
            f"letzten erfolgreichen Abruf ({n} Titel). Unkritisch, solange sich die "
            f"Index-Zusammensetzung nicht gerade geändert hat."
        )

    stats = result.get("scan_stats") or {}
    requested, analyzed = stats.get("requested", 0), stats.get("analyzed", 0)
    if not requested or stats.get("skipped_market_gate"):
        return  # ältere Caches ohne scan_stats / kein Scan gelaufen
    ratio = analyzed / requested
    if ratio < 0.75:
        st.error(
            f"⚠️ **Unvollständiger Scan:** Nur {analyzed} von {requested} Titeln "
            f"konnten ausgewertet werden ({ratio:.0%}). Das RS-Perzentil-Ranking "
            f"wird relativ zu dieser Restmenge berechnet und ist entsprechend "
            f"verzerrt — Scan wiederholen.",
            icon="🚨",
        )
    elif ratio < 0.90:
        st.warning(
            f"{analyzed} von {requested} Titeln ausgewertet ({ratio:.0%}) — einige "
            f"Kursabrufe sind gescheitert. Das RS-Ranking ist leicht verzerrt."
        )


def main():
    init_app()

    from portfolio.auth import render_auth_gate
    if not render_auth_gate():
        return

    render_sidebar_secondary()
    page = render_top_nav()
    result = st.session_state.scan_result
    _render_scan_quality_warning(result)

    if page == "Marktübersicht":
        page_market_overview(result)
    elif page == "Empfehlungen":
        page_recommendations(result)
    elif page == "Kauf-Kandidaten":
        page_buy_candidates(result)
    elif page == "Mein Portfolio":
        page_portfolio()
    elif page == "Performance":
        page_performance()
    elif page == "Backtest":
        page_backtest()
    elif page == "Vollständiger Scan":
        page_full_scan(result)


if __name__ == "__main__":
    main()
