"""
S&P500 Aktienanalyse-Dashboard
Streamlit Web-App — starten mit: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging
from datetime import datetime
import json

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


# ── Navigation ────────────────────────────────────────────────────────────────

_PAGES = ["Marktübersicht", "Empfehlungen", "Mein Portfolio", "Performance", "Vollständiger Scan"]
_PAGE_ICONS = {
    "Marktübersicht": "📊",
    "Empfehlungen": "🎯",
    "Mein Portfolio": "💼",
    "Performance": "📈",
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
            scan_running = False
            try:
                from scheduler import is_scan_running
                scan_running = is_scan_running()
            except Exception:
                pass
            if scan_running:
                st.info("Scan läuft...")
            else:
                if st.button("Analyse neu starten", use_container_width=True, type="primary"):
                    _start_scan()

        if st.session_state.scan_result:
            ts = st.session_state.scan_result.get("timestamp", "")
            if ts:
                try:
                    from zoneinfo import ZoneInfo
                    dt_utc = datetime.fromisoformat(ts).replace(tzinfo=ZoneInfo("UTC"))
                    dt_berlin = dt_utc.astimezone(ZoneInfo("Europe/Berlin"))
                    st.caption(f"Letzte Analyse: {dt_berlin.strftime('%d.%m.%Y %H:%M')} (DE)")
                except Exception:
                    pass

        st.divider()
        st.caption("Datenquelle: Yahoo Finance (yfinance)")
        st.caption("Kein Anlageberater — nur zur Information")


def _start_scan():
    from scheduler import trigger_scan_background

    progress_bar = st.sidebar.progress(0, text="Starte Scan...")
    status_text = st.sidebar.empty()

    def on_progress(done, total, ticker):
        pct = done / total
        progress_bar.progress(pct, text=f"{done}/{total} — {ticker}")

    def on_complete(result):
        st.session_state.scan_result = result
        progress_bar.empty()
        status_text.success("Scan abgeschlossen!")

    trigger_scan_background(on_complete=on_complete)
    st.rerun()


# ── Seite 1: Marktübersicht ───────────────────────────────────────────────────

def page_market_overview(result: dict | None):
    st.header("Marktübersicht")

    if result is None:
        st.info(
            "Noch keine Analysedaten vorhanden.\n\n"
            "Die erste Analyse wird automatisch von **GitHub Actions** durchgeführt "
            "(täglich Mo–Fr um 22:30 Uhr). "
            "Du kannst den Scan auch manuell über **GitHub → Actions → Run workflow** starten.",
            icon="⏳"
        )
        return

    market = result.get("market", {})
    _render_market_status(market)


def _show_quick_market():
    """Zeigt Echtzeit-Marktdaten ohne vorherigen Scan."""
    with st.spinner("Lade aktuelle Marktdaten..."):
        try:
            from analyzer.market_filter import check_market
            market = check_market()
            _render_market_status(market)
        except Exception as e:
            st.error(f"Fehler beim Laden: {e}")


def _render_market_status(market: dict):
    passed = market.get("passed", False)
    warning = market.get("warning", False)
    vix = market.get("vix")
    sp_price = market.get("sp500_price")
    ma50 = market.get("sp500_ma50")
    ma200 = market.get("sp500_ma200")
    reason = market.get("reason", "")
    sp_hist = market.get("sp500_hist")

    # Status-Banner
    if passed and not warning:
        st.success("MARKT BULLISCH — Empfehlungen möglich", icon="✅")
    elif passed and warning:
        st.warning(f"MARKT VORSICHTIG — {reason}", icon="⚠️")
    else:
        st.error(f"MARKT BEARISCH — Keine Empfehlungen | {reason}", icon="🚫")

    st.divider()

    # Metriken
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        vix_delta = None
        color = "normal"
        if vix:
            if vix > 25:
                color = "inverse"
            elif vix > 20:
                color = "off"
        st.metric("VIX (Volatilität)", f"{vix:.1f}" if vix else "N/A",
                  delta="Kritisch" if vix and vix > 25 else ("Erhöht" if vix and vix > 20 else "Normal"),
                  delta_color="inverse" if vix and vix > 25 else ("off" if vix and vix > 20 else "normal"))

    with col2:
        st.metric("S&P500", f"{sp_price:,.0f}" if sp_price else "N/A")

    with col3:
        above = market.get("sp500_above_ma50", False)
        if sp_price and ma50:
            diff_pct = (sp_price / ma50 - 1) * 100
            st.metric("50-Tage-MA", f"{ma50:,.0f}",
                      delta=f"{diff_pct:+.1f}%",
                      delta_color="normal" if above else "inverse")

    with col4:
        above200 = market.get("sp500_above_ma200", False)
        if sp_price and ma200:
            diff_pct = (sp_price / ma200 - 1) * 100
            st.metric("200-Tage-MA", f"{ma200:,.0f}",
                      delta=f"{diff_pct:+.1f}%",
                      delta_color="normal" if above200 else "inverse")

    # S&P500 Chart
    if sp_hist is not None:
        if isinstance(sp_hist, dict):
            sp_hist = pd.Series(sp_hist)
        _render_sp500_chart(sp_hist, ma50, ma200)

    # Gate-Details
    st.subheader("Gate 1 — Marktbedingungen")
    col1, col2, col3 = st.columns(3)
    with col1:
        icon = "✅" if market.get("sp500_above_ma200") else "❌"
        st.write(f"{icon} S&P500 über 200-Tage-MA")
    with col2:
        icon = "✅" if market.get("sp500_above_ma50") else "❌"
        st.write(f"{icon} S&P500 über 50-Tage-MA")
    with col3:
        vix_ok = vix is not None and vix <= 25
        icon = "✅" if vix_ok else "❌"
        st.write(f"{icon} VIX unter 25")


def _render_sp500_chart(hist: pd.Series, ma50: float, ma200: float):
    if isinstance(hist, dict):
        dates = list(hist.keys())
        values = list(hist.values())
    else:
        dates = hist.index.tolist()
        values = hist.values.tolist()

    # Gleitende Durchschnitte berechnen
    s = pd.Series(values, index=dates)
    ma50_series = s.rolling(50).mean()
    ma200_series = s.rolling(200).mean()

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=values, name="S&P500", line=dict(color="#2196F3", width=2)))
    fig.add_trace(go.Scatter(x=dates, y=ma50_series.tolist(), name="50-Tage-MA",
                             line=dict(color="#FF9800", width=1.5, dash="dot")))
    fig.add_trace(go.Scatter(x=dates, y=ma200_series.tolist(), name="200-Tage-MA",
                             line=dict(color="#F44336", width=1.5, dash="dash")))
    fig.update_layout(
        title="S&P500 — letztes Jahr",
        height=350,
        margin=dict(l=0, r=0, t=40, b=0),
        legend=dict(orientation="h", y=1.02),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


# ── Seite 2: Empfehlungen ─────────────────────────────────────────────────────

def page_recommendations(result: dict | None):
    st.header("Kaufempfehlungen")

    if result is None:
        st.info("Noch keine Analysedaten. Starte die Analyse über die Seitenleiste.")
        return

    market = result.get("market", {})
    recommendations = result.get("recommendations", [])
    scan_duration = result.get("scan_duration_s", 0)

    # Scan-Info
    total_analyzed = len(result.get("all_results", []))
    st.caption(f"Analysiert: {total_analyzed} Aktien | Scan-Dauer: {scan_duration:.0f}s")

    if not market.get("passed"):
        st.error(
            f"Marktbedingungen nicht erfüllt — keine Empfehlungen.\n\n"
            f"**Grund:** {market.get('reason', 'Unbekannt')}",
            icon="🚫"
        )
        _render_market_status_compact(market)
        return

    if not recommendations:
        st.warning(
            "Keine Aktie erfüllt aktuell alle 4 Kriterien (Relative Stärke, Technik, Fundamentals).\n\n"
            "Das ist ein gutes Zeichen — das System filtert sehr konservativ. "
            "Warte auf klarere Signale.",
            icon="⚠️"
        )
        return

    # Fehlende Felder im Cache on-the-fly nachberechnen — VOR der Sortierung
    import pandas as pd
    from analyzer.confidence import compute_confidence
    from analyzer.upside import compute_upside as _compute_upside

    for r in recommendations:
        # Konfidenz-Fallback
        if not r.get("combined_score") and (r.get("tech", {}).get("score") or r.get("fund", {}).get("score")):
            conf = compute_confidence(r.get("tech", {}).get("score", 0), r.get("fund", {}).get("score", 0), r.get("rs") or {})
            r["combined_score"] = conf["combined_score"]
            r["confidence_label"] = conf["confidence_label"]
        # Upside-Fallback
        if not r.get("upside") and r.get("price"):
            try:
                hist_raw = r.get("hist")
                hist_df = pd.DataFrame(hist_raw) if isinstance(hist_raw, dict) else hist_raw
                r["upside"] = _compute_upside(
                    hist=hist_df,
                    current_price=r.get("price"),
                    ma50=(r.get("tech", {}).get("indicators") or {}).get("ma50_val"),
                    atr=(r.get("exits") or {}).get("atr"),
                    metrics=(r.get("fund", {}).get("metrics") or {}),
                )
            except Exception:
                r["upside"] = {}

    sort_options = {
        "Konfidenz (Standard)": lambda x: x.get("combined_score", 0),
        "Upside": lambda x: (x.get("upside") or {}).get("expected_upside_pct") or 0,
        "Konfidenz × Upside": lambda x: x.get("combined_score", 0) * ((x.get("upside") or {}).get("expected_upside_pct") or 0),
    }
    sort_choice = st.selectbox(
        "Sortieren nach", list(sort_options.keys()), key="rec_sort_order"
    )
    recommendations_sorted = sorted(
        recommendations, key=sort_options[sort_choice], reverse=True
    )

    st.success(f"{len(recommendations_sorted)} Kaufempfehlung{'en' if len(recommendations_sorted) > 1 else ''} gefunden", icon="✅")
    st.divider()

    for stock in recommendations_sorted:
        _render_stock_card(stock)


def _render_market_status_compact(market: dict):
    col1, col2, col3 = st.columns(3)
    vix = market.get("vix")
    with col1:
        st.metric("VIX", f"{vix:.1f}" if vix else "N/A")
    with col2:
        st.metric("S&P500 über 200-MA", "Nein" if not market.get("sp500_above_ma200") else "Ja")
    with col3:
        st.metric("S&P500 über 50-MA", "Nein" if not market.get("sp500_above_ma50") else "Ja")


def _render_stock_card(stock: dict):
    ticker = stock["ticker"]
    name = stock.get("name", ticker)
    sector = stock.get("sector", "N/A")
    price = stock.get("price")
    rs = stock.get("rs", {})
    tech = stock.get("tech", {})
    fund = stock.get("fund", {})

    combined_score = stock.get("combined_score") or 0
    confidence_label = stock.get("confidence_label", "")
    # Fallback: Score aus Cache fehlt → on-the-fly nachberechnen
    if not combined_score and (tech.get("score") or fund.get("score")):
        from analyzer.confidence import compute_confidence
        conf = compute_confidence(tech.get("score", 0), fund.get("score", 0), rs or {})
        combined_score = conf["combined_score"]
        confidence_label = conf["confidence_label"]
    _CONF_COLORS = {"Strong Buy": "🟢", "Moderate Buy": "🟡", "Watch": "🔵"}
    conf_icon = _CONF_COLORS.get(confidence_label, "")

    upside = stock.get("upside") or {}
    # Fallback: upside fehlt im Cache → on-the-fly nachberechnen
    if not upside and stock.get("price"):
        try:
            import pandas as pd
            from analyzer.upside import compute_upside as _compute_upside
            hist_raw = stock.get("hist")
            hist_df = pd.DataFrame(hist_raw) if isinstance(hist_raw, dict) else hist_raw
            upside = _compute_upside(
                hist=hist_df,
                current_price=stock.get("price"),
                ma50=(tech.get("indicators") or {}).get("ma50_val"),
                atr=(stock.get("exits") or {}).get("atr"),
                metrics=(fund.get("metrics") or {}),
            )
        except Exception:
            upside = {}
    upside_pct = upside.get("expected_upside_pct")
    upside_label = upside.get("upside_label", "")
    _UPSIDE_ICONS = {"Hoch": "⬆️", "Mittel": "➡️", "Gering": "⬇️"}
    upside_icon = _UPSIDE_ICONS.get(upside_label, "")
    upside_str = (
        f"  |  {upside_icon} Upside: +{upside_pct:.1f}% ({upside_label})"
        if upside_pct is not None else ""
    )

    header = (
        f"**{ticker}** — {name}  |  {sector}  |  ${price:.2f}  |  {conf_icon} {confidence_label}{upside_str}"
        if price else
        f"**{ticker}** — {name}  |  {conf_icon} {confidence_label}{upside_str}"
    )

    with st.expander(header, expanded=False):

        # Konfidenz + Upside Banner
        col_conf1, col_conf2 = st.columns([3, 1])
        with col_conf1:
            st.progress(combined_score, text=f"Konfidenz-Score: {combined_score*100:.0f}% — {confidence_label}")
        with col_conf2:
            exits = stock.get("exits", {})
            rec = exits.get("recommendation", "Halten")
            rec_colors = {"Halten": "✅", "Beobachten": "⚠️", "Verkaufen erwägen": "🚫"}
            st.write(f"Exit: {rec_colors.get(rec, '')} **{rec}**")

        # Upside-Block
        if upside_pct is not None:
            col_u1, col_u2, col_u3, col_u4 = st.columns(4)
            with col_u1:
                st.metric(
                    "Erwartetes Upside",
                    f"+{upside_pct:.1f}%",
                    help="Gewichteter Mittelwert aus ATR-Kursziel, Distanz zum 52-Wochen-Hoch und Wachstumserwartung.",
                )
            with col_u2:
                atr_pct = upside.get("upside_atr_pct")
                st.metric("ATR-Kursziel", f"+{atr_pct:.1f}%" if atr_pct is not None else "—",
                          help="3 × ATR(14) / aktueller Kurs — technisches Take-Profit-Potential.")
            with col_u3:
                w52_pct = upside.get("upside_52w_pct")
                st.metric("Distanz 52w-Hoch", f"+{w52_pct:.1f}%" if w52_pct is not None else "—",
                          help="Wie weit ist der Kurs noch vom 52-Wochen-Hoch entfernt.")
            with col_u4:
                gr_pct = upside.get("upside_growth_pct")
                st.metric("Wachstum", f"+{gr_pct:.1f}%" if gr_pct is not None else "—",
                          help="Durchschnitt aus Umsatz- und Gewinnwachstum (fundamental).")

        st.divider()

        # Gate-Übersicht
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Gate 1 Markt", "✅ Bestanden")
        with col2:
            st.metric("Gate 2 Rel. Stärke", "✅ Bestanden")
        with col3:
            score_tech = tech.get("score", 0)
            st.metric("Gate 3 Technik", f"✅ {score_tech*100:.0f}%")
        with col4:
            score_fund = fund.get("score", 0)
            st.metric("Gate 4 Fundamentals", f"✅ {score_fund*100:.0f}%")

        st.divider()

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["📈 Charts", "📊 Technische Signale", "📋 Fundamentaldaten", "↗️ Relative Stärke", "⛔ Exit-Signale"])

        with tab1:
            hist = stock.get("hist")
            if hist is not None:
                _render_stock_charts(ticker, hist, tech)

        with tab2:
            _render_technical_signals(tech)

        with tab3:
            _render_fundamental_data(fund)

        with tab4:
            _render_relative_strength(rs)

        with tab5:
            _render_exit_signals(exits)


def _render_stock_charts(ticker: str, hist, tech: dict):
    if isinstance(hist, dict):
        close = pd.Series(hist.get("Close", []))
        volume = pd.Series(hist.get("Volume", []))
    elif hasattr(hist, "to_dict"):
        close = hist["Close"]
        volume = hist["Volume"]
    else:
        st.info("Chart-Daten nicht verfügbar.")
        return

    indicators = tech.get("indicators", {})
    fig = make_subplots(
        rows=3, cols=1,
        shared_xaxes=True,
        row_heights=[0.55, 0.25, 0.20],
        subplot_titles=[f"{ticker} — Kursverlauf", "RSI (14)", "MACD"],
        vertical_spacing=0.06,
    )

    # Kurs + MAs
    fig.add_trace(go.Scatter(y=close.tolist(), name="Kurs", line=dict(color="#2196F3", width=2)), row=1, col=1)

    def _add_ma(key, label, color, dash):
        ma_data = indicators.get(key)
        if ma_data is not None:
            if hasattr(ma_data, "tolist"):
                ma_data = ma_data.tolist()
            elif isinstance(ma_data, dict):
                ma_data = list(ma_data.values())
            fig.add_trace(go.Scatter(y=ma_data, name=label, line=dict(color=color, width=1.5, dash=dash)), row=1, col=1)

    _add_ma("ma50", "50-MA", "#FF9800", "dot")
    _add_ma("ma200", "200-MA", "#F44336", "dash")

    # Bollinger Bands
    for key, label in [("bb_upper", "BB Oben"), ("bb_lower", "BB Unten")]:
        bb = indicators.get(key)
        if bb is not None:
            vals = list(bb.values()) if isinstance(bb, dict) else bb.tolist()
            fig.add_trace(go.Scatter(y=vals, name=label, line=dict(color="#9E9E9E", width=1, dash="dot"), opacity=0.5), row=1, col=1)

    # RSI
    rsi = indicators.get("rsi")
    if rsi is not None:
        vals = list(rsi.values()) if isinstance(rsi, dict) else rsi.tolist()
        fig.add_trace(go.Scatter(y=vals, name="RSI", line=dict(color="#9C27B0", width=1.5)), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
        fig.add_hline(y=45, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)

    # MACD
    macd = indicators.get("macd_line")
    signal = indicators.get("signal_line")
    histo = indicators.get("histogram")
    if macd is not None:
        mv = list(macd.values()) if isinstance(macd, dict) else macd.tolist()
        sv = list(signal.values()) if isinstance(signal, dict) else signal.tolist()
        hv = list(histo.values()) if isinstance(histo, dict) else histo.tolist()
        fig.add_trace(go.Scatter(y=mv, name="MACD", line=dict(color="#2196F3")), row=3, col=1)
        fig.add_trace(go.Scatter(y=sv, name="Signal", line=dict(color="#FF9800")), row=3, col=1)
        colors = ["#4CAF50" if v >= 0 else "#F44336" for v in hv]
        fig.add_trace(go.Bar(y=hv, name="Histogramm", marker_color=colors, opacity=0.7), row=3, col=1)

    fig.update_layout(height=550, margin=dict(l=0, r=0, t=40, b=0), showlegend=True,
                      legend=dict(orientation="h", y=1.02), hovermode="x unified")
    st.plotly_chart(fig, use_container_width=True)


def _render_technical_signals(tech: dict):
    signals = tech.get("signals", {})
    indicators = tech.get("indicators", {})

    if not signals:
        st.info("Keine technischen Signale verfügbar.")
        return

    score = tech.get("score", 0)
    st.progress(score, text=f"Technischer Score: {score*100:.0f}%")
    st.divider()

    for signal, passed in signals.items():
        icon = "✅" if passed else "❌"
        st.write(f"{icon} {signal}")

    st.divider()
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("RSI", indicators.get("rsi_value", "N/A"))
    with col2:
        st.metric("Kurs", f"${indicators.get('price', 'N/A')}")
    with col3:
        bb_pct = indicators.get("bb_pct")
        st.metric("Bollinger-Position", f"{bb_pct}%" if bb_pct is not None else "N/A")


def _render_fundamental_data(fund: dict):
    signals = fund.get("signals", {})
    metrics = fund.get("metrics", {})

    if not signals:
        st.info("Keine Fundamentaldaten verfügbar.")
        return

    score = fund.get("score", 0)
    st.progress(score, text=f"Fundamentaler Score: {score*100:.0f}%")
    st.divider()

    for signal, passed in signals.items():
        icon = "✅" if passed else "❌"
        st.write(f"{icon} {signal}")

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.metric("KGV (trailing)", metrics.get("pe", "N/A"))
        st.metric("Umsatzwachstum", metrics.get("revenue_growth", "N/A"))
        st.metric("Gewinnmarge", metrics.get("profit_margin", "N/A"))
    with col2:
        st.metric("Verschuldungsgrad", metrics.get("debt_to_equity", "N/A"))
        st.metric("Free Cashflow", metrics.get("free_cashflow", "N/A"))
        st.metric("Marktkapitalisierung", metrics.get("market_cap", "N/A"))
    st.caption(f"Sektor: {metrics.get('sector', 'N/A')}")


def _render_relative_strength(rs: dict):
    if not rs or rs.get("rs_3m") is None:
        st.info("Keine Relative-Stärke-Daten verfügbar.")
        return

    rs_3m = rs.get("rs_3m", 0)
    rs_6m = rs.get("rs_6m", 0)

    col1, col2 = st.columns(2)
    with col1:
        st.metric("RS vs. S&P500 (3M)",
                  f"{rs.get('stock_3m', 0):+.1f}%",
                  delta=f"{rs_3m:+.1f}% vs Index",
                  delta_color="normal" if rs_3m > 0 else "inverse")
        st.caption(f"S&P500 3M: {rs.get('sp500_3m', 0):+.1f}%")
    with col2:
        st.metric("RS vs. S&P500 (6M)",
                  f"{rs.get('stock_6m', 0):+.1f}%",
                  delta=f"{rs_6m:+.1f}% vs Index",
                  delta_color="normal" if rs_6m > 0 else "inverse")
        st.caption(f"S&P500 6M: {rs.get('sp500_6m', 0):+.1f}%")

    status_3m = "✅ Outperform" if rs_3m > 0 else "❌ Underperform"
    status_6m = "✅ Outperform" if rs_6m > 0 else "❌ Underperform"
    st.write(f"3 Monate: {status_3m}  |  6 Monate: {status_6m}")


# ── Seite 3: Vollständiger Scan ───────────────────────────────────────────────

def page_full_scan(result: dict | None):
    st.header("Vollständiger Scan")

    if result is None:
        st.info("Noch keine Analysedaten. Starte die Analyse über die Seitenleiste.")
        return

    all_results = result.get("all_results", [])
    if not all_results:
        st.info("Keine Scan-Ergebnisse vorhanden (Gate 1 hat den Scan blockiert).")
        return

    # Tabelle aufbauen
    rows = []
    for s in all_results:
        rs = s.get("rs", {})
        rows.append({
            "Ticker": s["ticker"],
            "Name": s.get("name", ""),
            "Sektor": s.get("sector", "N/A"),
            "Empfohlen": "✅" if s["recommended"] else "—",
            "Gate RS": "✅" if s.get("gate_rs") else "❌",
            "Gate Technik": "✅" if s.get("gate_tech") else "❌",
            "Gate Fundamentals": "✅" if s.get("gate_fund") else "❌",
            "Tech-Score": f"{s.get('tech_score', 0)*100:.0f}%",
            "Fund-Score": f"{s.get('fund_score', 0)*100:.0f}%",
            "RS 3M": f"{rs.get('rs_3m', 0):+.1f}%" if rs.get("rs_3m") is not None else "N/A",
            "RS 6M": f"{rs.get('rs_6m', 0):+.1f}%" if rs.get("rs_6m") is not None else "N/A",
            "Kurs": f"${s['price']:.2f}" if s.get("price") else "N/A",
        })

    df = pd.DataFrame(rows)

    # Filter
    sectors = ["Alle"] + sorted(df["Sektor"].dropna().unique().tolist())
    col1, col2 = st.columns([2, 1])
    with col1:
        selected_sector = st.selectbox("Sektor filtern", sectors)
    with col2:
        only_recommended = st.checkbox("Nur Empfehlungen", value=False)

    filtered = df.copy()
    if selected_sector != "Alle":
        filtered = filtered[filtered["Sektor"] == selected_sector]
    if only_recommended:
        filtered = filtered[filtered["Empfohlen"] == "✅"]

    st.caption(f"{len(filtered)} Aktien angezeigt")
    st.dataframe(filtered, use_container_width=True, hide_index=True)


# ── Exit-Signal-Anzeige ───────────────────────────────────────────────────────

def _render_exit_signals(exits: dict, entry_price: float = None):
    if not exits or exits.get("recommendation") == "Keine Daten":
        st.info("Keine Exit-Daten verfügbar (zu wenig Kurshistorie).")
        return

    rec = exits.get("recommendation", "Halten")
    rec_map = {
        "Halten": ("success", "✅ Halten — keine kritischen Exit-Signale"),
        "Beobachten": ("warning", "⚠️ Beobachten — erste Exit-Signale aktiv"),
        "Verkaufen erwägen": ("error", "🚫 Verkaufen erwägen — mehrere Exit-Signale aktiv"),
    }
    fn_name, msg = rec_map.get(rec, ("info", rec))
    getattr(st, fn_name)(msg)

    st.divider()
    col1, col2, col3 = st.columns(3)
    atr = exits.get("atr")
    sl = exits.get("stop_loss")
    tp = exits.get("take_profit")
    with col1:
        ep_str = f"${entry_price:.2f}" if entry_price else "Kaufkurs"
        st.metric("Einstieg", ep_str)
    with col2:
        st.metric("Stop-Loss (ATR×2)", f"${sl:.2f}" if sl is not None else "N/A",
                  delta=f"-{abs(sl - entry_price):.2f}" if sl is not None and entry_price else None,
                  delta_color="inverse")
    with col3:
        st.metric("Take-Profit (ATR×3)", f"${tp:.2f}" if tp is not None else "N/A",
                  delta=f"+{abs(tp - entry_price):.2f}" if tp is not None and entry_price else None,
                  delta_color="normal")

    if atr:
        st.caption(f"ATR(14): {atr:.2f}")

    st.divider()
    signals = exits.get("signals", {})
    if signals:
        st.write("**Aktive Exit-Signale:**")
        for signal, active in signals.items():
            icon = "🔴" if active else "🟢"
            st.write(f"{icon} {signal}")


# ── Seite: Mein Portfolio ─────────────────────────────────────────────────────

def page_portfolio():
    st.header("Mein Portfolio")
    st.caption("Eigene Käufe überwachen — mit Exit-Empfehlung")

    from portfolio.manager import (
        add_position, remove_position, evaluate_positions,
        sell_position, load_realized, edit_lot, delete_lot, edit_realized,
    )
    from portfolio.auth import current_user_id

    # Positionen auswerten
    with st.spinner("Lade aktuelle Kurse und EUR/USD-Kurs..."):
        positions = evaluate_positions()

    realized = load_realized()

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_open, tab_realized, tab_perf, tab_add = st.tabs([
        "📋 Offene Positionen",
        "✅ Realisierte Trades",
        "📈 Performance",
        "➕ Kauf eintragen",
    ])

    # ── Tab 1: Offene Positionen ───────────────────────────────────────────────
    with tab_open:
        if not positions:
            st.info("Noch keine offenen Positionen. Trage deinen ersten Kauf im Tab '➕ Kauf eintragen' ein.")
        else:
            if positions[0].get("eurusd"):
                st.caption(f"EUR/USD: {positions[0]['eurusd']:.4f}")

            # Risiko-Banner
            total_value_eur = sum(
                (p.get("current_price_eur") or 0) * p.get("total_shares", 0)
                for p in positions
            )
            worst_case_eur = 0.0
            eurusd = positions[0].get("eurusd") or 1.0
            for p in positions:
                sl_usd = (p.get("exits") or {}).get("stop_loss")
                curr_usd = p.get("current_price_usd")
                if sl_usd and curr_usd:
                    loss_usd = (curr_usd - sl_usd) * p.get("total_shares", 0)
                    worst_case_eur += loss_usd / eurusd
            if total_value_eur > 0 and worst_case_eur > 0:
                worst_pct = worst_case_eur / total_value_eur * 100
                st.warning(
                    f"⚠️ Max. Risiko bei Stop-Loss-Hit aller Positionen: "
                    f"**-€{worst_case_eur:,.0f}** ({worst_pct:.1f}% des Portfoliowerts)"
                )

            # Positions-Donut: Anteil je Aktie am Gesamtportfolio
            if len(positions) >= 1 and total_value_eur > 0:
                pos_labels = []
                pos_values = []
                for p in positions:
                    val = (p.get("current_price_eur") or 0) * p.get("total_shares", 0)
                    if val > 0:
                        name = p.get("company_name") or p["ticker"]
                        pos_labels.append(f"{name} ({p['ticker']})")
                        pos_values.append(round(val, 2))

                fig_donut = go.Figure(go.Pie(
                    labels=pos_labels,
                    values=pos_values,
                    hole=0.45,
                    textinfo="label+percent",
                ))
                fig_donut.update_layout(
                    title="Portfolio-Verteilung (nach Marktwert)",
                    height=300, margin=dict(l=0, r=0, t=40, b=0),
                    showlegend=False,
                )
                col_d1, col_d2 = st.columns([2, 1])
                with col_d1:
                    st.plotly_chart(fig_donut, use_container_width=True)
                with col_d2:
                    st.metric("Portfoliowert", f"€{total_value_eur:,.0f}")

            # Übersichtstabelle
            rows = []
            for p in positions:
                exits = p.get("exits", {})
                rec = exits.get("recommendation", "—")
                rec_icon = {"Halten": "✅", "Beobachten": "⚠️", "Verkaufen erwägen": "🚫"}.get(rec, "—")
                name = p.get("company_name") or p["ticker"]
                rows.append({
                    "Aktie": f"{name} ({p['ticker']})",
                    "Ø Einstieg (€)": f"€{p['avg_entry_price_eur']:.2f}" if p.get("avg_entry_price_eur") else "—",
                    "Stück": p.get("total_shares", 0),
                    "Datum": p.get("entry_date", "—"),
                    "Tage": p["days_held"] if p["days_held"] is not None else "—",
                    "Kurs (€)": f"€{p['current_price_eur']:.2f}" if p.get("current_price_eur") else "N/A",
                    "P&L %": f"{p['pnl_pct']:+.1f}%" if p["pnl_pct"] is not None else "N/A",
                    "P&L (€)": f"€{p['pnl_abs_eur']:+.2f}" if p.get("pnl_abs_eur") is not None else "N/A",
                    "Exit": f"{rec_icon} {rec} ({exits.get('signal_count', 0)}/7)",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            st.divider()

            # Detail-Expander pro Position
            for i, p in enumerate(positions):
                exits = p.get("exits", {})
                name = p.get("company_name") or p["ticker"]
                with st.expander(
                    f"**{p['ticker']}** — {name}  |  "
                    f"{'P&L: ' + str(p['pnl_pct']) + '%' if p.get('pnl_pct') is not None else ''}",
                    expanded=False,
                ):
                    # Lot-Tabelle
                    lots = p.get("lots", [])
                    if lots:
                        st.caption("Käufe (Lots):")
                        lot_rows = [{
                            "Kaufdatum": l["date"],
                            "Stück": l["shares"],
                            "Kurs (€)": f"€{l['price_eur']:.2f}",
                            "Notiz": l.get("notes", ""),
                        } for l in sorted(lots, key=lambda l: l["date"])]
                        st.dataframe(pd.DataFrame(lot_rows), use_container_width=True, hide_index=True)
                        avg = p.get("avg_entry_price_eur")
                        if avg and len(lots) > 1:
                            st.caption(f"Ø Einstandspreis: **€{avg:.2f}**")

                    # Lot bearbeiten / löschen
                    if lots:
                        with st.expander("✏️ Kauf bearbeiten oder löschen"):
                            sorted_lots = sorted(lots, key=lambda l: l["date"])
                            lot_labels = [
                                f"{l['date']} — {l['shares']:g} Stück @ €{l['price_eur']:.2f}"
                                for l in sorted_lots
                            ]
                            sel_lot_idx = st.selectbox(
                                "Welchen Kauf bearbeiten?", range(len(lot_labels)),
                                format_func=lambda x: lot_labels[x],
                                key=f"edit_lot_sel_{i}",
                            )
                            sel_lot = sorted_lots[sel_lot_idx]
                            sel_lot_id = sel_lot.get("id", "")
                            with st.form(f"edit_lot_form_{p['ticker']}_{sel_lot_id}"):
                                el1, el2, el3 = st.columns(3)
                                with el1:
                                    new_lot_date = st.date_input(
                                        "Kaufdatum",
                                        value=datetime.strptime(sel_lot["date"], "%Y-%m-%d"),
                                        max_value=datetime.today(),
                                        key=f"el_date_{sel_lot_id}",
                                    )
                                with el2:
                                    new_lot_shares = st.number_input(
                                        "Stückzahl", min_value=0.0001,
                                        value=float(sel_lot["shares"]),
                                        step=1.0, format="%.4f",
                                        key=f"el_shares_{sel_lot_id}",
                                    )
                                with el3:
                                    new_lot_price = st.number_input(
                                        "Kaufkurs (€)", min_value=0.01,
                                        value=float(sel_lot["price_eur"]),
                                        step=0.01, format="%.2f",
                                        key=f"el_price_{sel_lot_id}",
                                    )
                                new_lot_notes = st.text_input(
                                    "Notiz", value=sel_lot.get("notes", ""), max_chars=200,
                                    key=f"el_notes_{sel_lot_id}",
                                )
                                ec1, ec2 = st.columns(2)
                                with ec1:
                                    save_lot = st.form_submit_button("💾 Speichern", type="primary")
                                with ec2:
                                    del_lot = st.form_submit_button("🗑️ Lot löschen", type="secondary")
                                if save_lot:
                                    err = edit_lot(
                                        sel_lot_id,
                                        str(new_lot_date), new_lot_shares,
                                        new_lot_price, new_lot_notes,
                                    )
                                    if err:
                                        st.error(err)
                                    else:
                                        st.success("Kauf aktualisiert.")
                                        st.rerun()
                                if del_lot:
                                    err = delete_lot(sel_lot_id, p["ticker"])
                                    if err:
                                        st.error(err)
                                    else:
                                        st.success("Lot gelöscht.")
                                        st.rerun()

                    st.divider()
                    _render_exit_signals(exits, entry_price=p.get("current_price_usd"))

                    st.divider()

                    # Verkaufs-Form
                    st.subheader("Verkauf nachtragen")
                    st.caption("Das Verkaufsdatum kann auch in der Vergangenheit liegen — trage Verkäufe in Ruhe nach.")
                    with st.form(f"sell_form_{p['ticker']}_{i}", clear_on_submit=True):
                        total_s = p.get("total_shares", 0)
                        sc1, sc2, sc3 = st.columns(3)
                        with sc1:
                            sell_shares = st.number_input(
                                f"Stückzahl (max {total_s:g})",
                                min_value=0.01, max_value=float(total_s),
                                step=1.0, format="%.4f",
                                key=f"sell_shares_{i}",
                            )
                        with sc2:
                            sell_price = st.number_input(
                                "Verkaufskurs (€)", min_value=0.01, step=0.01, format="%.2f",
                                key=f"sell_price_{i}",
                            )
                        with sc3:
                            sell_date = st.date_input(
                                "Verkaufsdatum",
                                value=datetime.today(),
                                max_value=datetime.today(),
                                key=f"sell_date_{i}",
                            )
                        sell_notes = st.text_input("Notiz (optional)", max_chars=200, key=f"sell_notes_{i}")
                        sell_submitted = st.form_submit_button("💰 Verkauf speichern", type="primary")
                        if sell_submitted:
                            entries, err = sell_position(
                                p["ticker"], sell_shares, sell_price,
                                str(sell_date), sell_notes,
                            )
                            if err:
                                st.error(err)
                            else:
                                total_pnl = sum(e["pnl_eur"] for e in entries)
                                st.success(
                                    f"Verkauf gespeichert — {sell_shares:g} Stück {p['ticker']} "
                                    f"zu €{sell_price:.2f} am {sell_date}. "
                                    f"P&L: €{total_pnl:+.2f}"
                                )
                                st.rerun()

                    st.divider()
                    st.caption("⚠️ 'Position löschen' entfernt den Eintrag ohne Gewinn/Verlust zu speichern. Für Buchführung bitte Verkaufs-Form oben nutzen.")
                    if st.button(f"🗑️ Position löschen ({p['ticker']})", key=f"remove_{i}", type="secondary"):
                        remove_position(p["ticker"])
                        st.rerun()

    # ── Tab 2: Realisierte Trades ──────────────────────────────────────────────
    with tab_realized:
        if not realized:
            st.info("Noch keine realisierten Trades vorhanden.")
        else:
            total_pnl = sum(r.get("pnl_eur", 0) or 0 for r in realized)
            hits = sum(1 for r in realized if (r.get("pnl_eur") or 0) > 0)
            avg_days = sum(r.get("days_held") or 0 for r in realized if r.get("days_held")) / max(len(realized), 1)

            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Trades gesamt", len(realized))
            kc2.metric("Gesamt P&L", f"€{total_pnl:+,.2f}", delta_color="normal" if total_pnl >= 0 else "inverse")
            kc3.metric("Trefferquote", f"{hits/len(realized)*100:.0f}%")
            kc4.metric("Ø Haltedauer", f"{avg_days:.0f} Tage")

            st.divider()

            # Filter
            fc1, fc2 = st.columns(2)
            with fc1:
                all_tickers = sorted(set(r.get("ticker", "") for r in realized))
                sel_ticker = st.selectbox("Ticker filtern", ["Alle"] + all_tickers, key="realized_ticker_filter")
            with fc2:
                all_years = sorted(set(
                    r.get("sell_date", "")[:4] for r in realized if r.get("sell_date")
                ), reverse=True)
                sel_year = st.selectbox("Jahr filtern (für Steuer)", ["Alle"] + all_years, key="realized_year_filter")

            filtered = realized
            if sel_ticker != "Alle":
                filtered = [r for r in filtered if r.get("ticker") == sel_ticker]
            if sel_year != "Alle":
                filtered = [r for r in filtered if r.get("sell_date", "").startswith(sel_year)]

            rows = []
            for r in filtered:
                pnl = r.get("pnl_eur")
                rows.append({
                    "Verkauf": r.get("sell_date", "—"),
                    "Kauf": r.get("buy_date", "—"),
                    "Ticker": r.get("ticker", ""),
                    "Name": r.get("company_name", ""),
                    "Stück": r.get("shares", 0),
                    "Kauf (€)": f"€{r['buy_price_eur']:.2f}" if r.get("buy_price_eur") else "—",
                    "Verk. (€)": f"€{r['sell_price_eur']:.2f}" if r.get("sell_price_eur") else "—",
                    "P&L (€)": f"€{pnl:+.2f}" if pnl is not None else "—",
                    "P&L %": f"{r['pnl_pct']:+.1f}%" if r.get("pnl_pct") is not None else "—",
                    "Tage": r.get("days_held", "—"),
                    "Notiz": r.get("notes", ""),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            if sel_year != "Alle":
                year_pnl = sum(r.get("pnl_eur", 0) or 0 for r in filtered)
                st.caption(f"P&L gesamt {sel_year}: **€{year_pnl:+,.2f}**")

            # Realisierten Trade bearbeiten
            st.divider()
            with st.expander("✏️ Realisierten Trade bearbeiten"):
                trade_labels = [
                    f"{r.get('sell_date','?')} — {r.get('ticker','')} "
                    f"{r.get('shares',0):g} Stück @ €{r.get('sell_price_eur',0):.2f}"
                    for r in realized
                ]
                sel_trade_idx = st.selectbox(
                    "Welchen Trade bearbeiten?", range(len(trade_labels)),
                    format_func=lambda x: trade_labels[x],
                    key="edit_realized_sel",
                )
                sel_trade = realized[sel_trade_idx]
                sel_trade_id = sel_trade.get("id", "")
                with st.form(f"edit_realized_form_{sel_trade_id}"):
                    rt1, rt2, rt3 = st.columns(3)
                    with rt1:
                        new_sell_date = st.date_input(
                            "Verkaufsdatum",
                            value=datetime.strptime(sel_trade["sell_date"], "%Y-%m-%d"),
                            max_value=datetime.today(),
                            key=f"er_sell_date_{sel_trade_id}",
                        )
                    with rt2:
                        new_sell_shares = st.number_input(
                            "Stückzahl", min_value=0.0001,
                            value=float(sel_trade.get("shares", 1)),
                            step=1.0, format="%.4f",
                            key=f"er_shares_{sel_trade_id}",
                        )
                    with rt3:
                        new_sell_price = st.number_input(
                            "Verkaufskurs (€)", min_value=0.01,
                            value=float(sel_trade.get("sell_price_eur", 0.01)),
                            step=0.01, format="%.2f",
                            key=f"er_price_{sel_trade_id}",
                        )
                    new_trade_notes = st.text_input(
                        "Notiz", value=sel_trade.get("notes", ""), max_chars=200,
                        key=f"er_notes_{sel_trade_id}",
                    )
                    if st.form_submit_button("💾 Trade speichern", type="primary"):
                        err = edit_realized(
                            sel_trade_id, str(new_sell_date),
                            new_sell_shares, new_sell_price, new_trade_notes,
                        )
                        if err:
                            st.error(err)
                        else:
                            st.success("Trade aktualisiert.")
                            st.rerun()

    # ── Tab 3: Performance vs. SPY ─────────────────────────────────────────────
    with tab_perf:
        if not positions:
            st.info("Keine offenen Positionen — Performance-Chart setzt mindestens einen Kauf voraus.")
        else:
            with st.spinner("Lade historische Kursdaten für Performance-Chart..."):
                from portfolio.history import get_portfolio_history
                hist_data = get_portfolio_history(positions, user_id=current_user_id())

            if not hist_data:
                st.info("Nicht genug Kursdaten (mindestens 3 Tage Haltedauer nötig).")
            else:
                realized_pnl = sum(r.get("pnl_eur", 0) or 0 for r in realized)
                unrealized_pnl = hist_data.get("unrealized_pnl_eur", 0) or 0
                total_pnl_eur = round(unrealized_pnl + realized_pnl, 2)

                kp1, kp2, kp3, kp4 = st.columns(4)
                kp1.metric(
                    "Gesamtrendite (offen)",
                    f"{hist_data['total_return_pct']:+.1f}%",
                    delta=f"€{unrealized_pnl:+,.2f}",
                    delta_color="normal" if unrealized_pnl >= 0 else "inverse",
                    help="Offene Positionen: aktueller Wert minus eingesetztes Kapital.",
                )
                kp2.metric(
                    "Realisiert",
                    f"€{realized_pnl:+,.2f}",
                    delta=f"{len(realized)} Trade{'s' if len(realized) != 1 else ''}",
                    delta_color="normal" if realized_pnl >= 0 else "inverse",
                    help="Summe aller abgeschlossenen Verkäufe.",
                )
                kp3.metric(
                    "Gesamt P&L",
                    f"€{total_pnl_eur:+,.2f}",
                    help="Offene Positionen + realisierte Trades zusammen.",
                    delta_color="normal" if total_pnl_eur >= 0 else "inverse",
                )
                if hist_data.get("vs_spy_pct") is not None:
                    kp4.metric("vs. SPY", f"{hist_data['vs_spy_pct']:+.1f}%",
                               delta_color="normal" if hist_data["vs_spy_pct"] >= 0 else "inverse")
                else:
                    kp4.metric("Max. Drawdown", f"{hist_data['max_drawdown_pct']:.1f}%", delta_color="inverse")

                st.caption(f"Max. Drawdown: {hist_data['max_drawdown_pct']:.1f}%")

                fig_perf = go.Figure()
                fig_perf.add_trace(go.Scatter(
                    x=hist_data["dates"], y=hist_data["portfolio_indexed"],
                    name="Mein Portfolio", line=dict(color="#2196F3", width=2),
                ))
                if hist_data.get("spy_indexed"):
                    fig_perf.add_trace(go.Scatter(
                        x=hist_data["dates"], y=hist_data["spy_indexed"],
                        name="SPY", line=dict(color="#FF9800", width=1.5, dash="dash"),
                    ))
                fig_perf.add_hline(y=100, line_dash="dot", line_color="gray", opacity=0.5)
                fig_perf.update_layout(
                    title=f"Portfolio vs. SPY (normalisiert auf 100 ab {hist_data['start_date']})",
                    yaxis_title="Indexiert (Start = 100)",
                    height=400, margin=dict(l=0, r=0, t=50, b=0),
                    legend=dict(orientation="h", y=-0.1),
                )
                st.plotly_chart(fig_perf, use_container_width=True)
                st.caption("Der Chart zeigt nur offene Positionen. Verkaufte Positionen fließen nicht ein.")

    # ── Tab 4: Kauf eintragen ──────────────────────────────────────────────────
    with tab_add:
        st.subheader("Neuen Kauf eintragen")
        st.caption("Käufe können auch rückwirkend eingetragen werden — Kaufdatum frei wählbar.")

        # Firmennamen laden (gecacht in session_state)
        _cached = st.session_state.get("sp500_names", {})
        _cache_has_names = any(n != t for t, n in _cached.items())
        if not _cached or not _cache_has_names:
            with st.spinner("Lade Aktienliste..."):
                try:
                    from analyzer.universe import get_sp500_names
                    st.session_state.sp500_names = get_sp500_names()
                except Exception:
                    st.session_state.sp500_names = {}

        names_dict = st.session_state.sp500_names
        options = sorted(
            [f"{n} ({t})" for t, n in names_dict.items()],
            key=lambda x: x.lower(),
        )
        if not options:
            options = ["(Liste nicht verfügbar — Ticker manuell eingeben)"]

        with st.form("add_position_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                selected = st.selectbox(
                    "Aktie suchen (Name oder Ticker eintippen)",
                    options=options, index=None,
                    placeholder="z.B. Apple oder AAPL...",
                )
                price_in = st.number_input("Kaufkurs (€)", min_value=0.01, step=0.01, format="%.2f")
            with col2:
                date_in = st.date_input("Kaufdatum", value=datetime.today(), max_value=datetime.today())
                shares_in = st.number_input("Anzahl Aktien", min_value=0.01, step=1.0, format="%.2f")
            notes_in = st.text_input("Notiz (optional)", max_chars=200)
            submitted = st.form_submit_button("Position speichern", type="primary")
            if submitted:
                ticker_in = ""
                company_in = ""
                if selected and "(" in selected:
                    ticker_in = selected.rsplit("(", 1)[-1].rstrip(")")
                    company_in = selected.rsplit("(", 1)[0].strip()
                if ticker_in and price_in > 0 and shares_in > 0:
                    add_position(ticker_in, company_in, str(date_in), price_in, shares_in, notes_in)
                    st.success(f"{company_in} ({ticker_in}) hinzugefügt!")
                    st.rerun()
                else:
                    st.error("Bitte eine Aktie auswählen, Kaufkurs und Anzahl angeben.")


# ── Seite: Performance-Tracking ───────────────────────────────────────────────

def page_performance():
    st.header("Performance historischer Empfehlungen")
    st.caption("Wie gut haben die Empfehlungen der letzten Monate abgeschnitten?")

    from history.logger import load_log
    from history.performance import enrich_with_performance
    from history import analytics as ana
    from history.export import generate_markdown_report, generate_json_export

    log = load_log()
    if not log:
        st.info(
            "Noch keine historischen Empfehlungen gespeichert.\n\n"
            "Nach dem nächsten Scan werden die Empfehlungen automatisch archiviert."
        )
        return

    # Performance-Daten laden (mit Spinner, da yfinance-Calls)
    with st.spinner("Lade historische Performance-Daten..."):
        enriched = enrich_with_performance(log)

    if not enriched:
        st.info("Keine Empfehlungen in der Historie gefunden.")
        return

    stats = ana.summary_stats(enriched)

    # ── Aggregierte Kennzahlen ────────────────────────────────────────────────
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Empfehlungen gesamt", stats["total"])
    with col2:
        if stats.get("measurable", 0) > 0:
            st.metric("Trefferquote 1M", f"{stats['hit_rate']}%",
                      delta_color="normal" if stats["hit_rate"] >= 50 else "inverse")
        else:
            st.metric("Trefferquote 1M", "—", help="Weniger als 30 Tage Daten")
    with col3:
        if stats.get("avg_perf_1m") is not None:
            st.metric("Ø Performance 1M", f"{stats['avg_perf_1m']:+.1f}%",
                      delta_color="normal" if stats["avg_perf_1m"] >= 0 else "inverse")
        else:
            st.metric("Ø Performance 1M", "—")
    with col4:
        if stats.get("avg_vs_spy_1m") is not None:
            st.metric("vs. SPY 1M", f"{stats['avg_vs_spy_1m']:+.1f}%",
                      delta_color="normal" if stats["avg_vs_spy_1m"] >= 0 else "inverse")
        else:
            st.metric("vs. SPY 1M", "—")

    st.divider()

    # ── Analyse-Tabs ──────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
        "📊 Konfidenz-Kalibrierung",
        "⬆️ Upside-Validierung",
        "🔬 Signal-Wirksamkeit",
        "🏭 Sektoren",
        "📈 Alle Empfehlungen",
        "📥 Export für Claude",
    ])

    with tab1:
        _render_confidence_chart(ana.by_confidence(enriched))

    with tab2:
        _render_upside_chart(ana.by_upside_label(enriched))

    with tab3:
        st.subheader("Technische Signale")
        _render_signal_table(ana.signal_effectiveness(enriched, "tech"))
        st.subheader("Fundamentals-Signale")
        _render_signal_table(ana.signal_effectiveness(enriched, "fund"))

    with tab4:
        col_a, col_b = st.columns(2)
        with col_a:
            _render_sector_chart(ana.by_sector(enriched))
        with col_b:
            _render_vix_chart(ana.by_vix(enriched))

    with tab5:
        _render_all_recommendations_table(enriched)

    with tab6:
        _render_export_section(enriched, generate_markdown_report, generate_json_export)


def _render_confidence_chart(conf_data: list[dict]):
    if not conf_data:
        st.info("Noch keine auswertbaren Daten (mindestens 30 Tage Haltedauer nötig).")
        return

    import plotly.graph_objects as go

    labels = [c["label"] for c in conf_data]
    hit_rates = [c["hit_rate"] for c in conf_data]
    avg_perfs = [c["avg_perf"] for c in conf_data]
    ns = [c["n"] for c in conf_data]

    colors = {"Strong Buy": "#4CAF50", "Moderate Buy": "#FF9800", "Watch": "#2196F3", "Unbekannt": "#9E9E9E"}
    bar_colors = [colors.get(l, "#9E9E9E") for l in labels]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Trefferquote %",
        x=labels, y=hit_rates,
        marker_color=bar_colors, opacity=0.8,
        text=[f"{v:.0f}% (n={n})" for v, n in zip(hit_rates, ns)],
        textposition="outside",
    ))
    fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50% Break-Even")
    fig.update_layout(
        title="Trefferquote je Konfidenz-Label (1M positiv)",
        yaxis_title="Trefferquote %", height=350,
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        name="Ø Performance 1M",
        x=labels, y=avg_perfs,
        marker_color=[c if p >= 0 else "#F44336" for c, p in zip(bar_colors, avg_perfs)],
        text=[f"{v:+.1f}%" for v in avg_perfs],
        textposition="outside",
    ))
    fig2.add_hline(y=0, line_color="gray")
    fig2.update_layout(
        title="Ø Performance nach 1M je Konfidenz-Label",
        yaxis_title="Performance %", height=300,
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig2, use_container_width=True)


def _render_upside_chart(upside_data: list[dict]):
    if not upside_data:
        st.info(
            "Noch keine auswertbaren Daten. Das Upside-Label wird erst ab dem nächsten Scan gespeichert "
            "(ältere Log-Einträge haben kein Upside-Label)."
        )
        return

    import plotly.graph_objects as go

    labels = [u["label"] for u in upside_data]
    hit_rates = [u["hit_rate"] for u in upside_data]
    avg_perfs = [u["avg_perf"] for u in upside_data]
    ns = [u["n"] for u in upside_data]

    colors = {"Hoch": "#4CAF50", "Mittel": "#FF9800", "Gering": "#9E9E9E", "Unbekannt": "#607D8B"}
    bar_colors = [colors.get(l, "#9E9E9E") for l in labels]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name="Trefferquote %",
        x=labels, y=hit_rates,
        marker_color=bar_colors, opacity=0.85,
        text=[f"{v:.0f}% (n={n})" for v, n in zip(hit_rates, ns)],
        textposition="outside",
    ))
    fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50% Break-Even")
    fig.update_layout(
        title="Trefferquote je Upside-Label (1M positiv)",
        yaxis_title="Trefferquote %", height=350,
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        name="Ø Performance 1M",
        x=labels, y=avg_perfs,
        marker_color=[c if p >= 0 else "#F44336" for c, p in zip(bar_colors, avg_perfs)],
        text=[f"{v:+.1f}%" for v in avg_perfs],
        textposition="outside",
    ))
    fig2.add_hline(y=0, line_color="gray")
    fig2.update_layout(
        title="Ø Performance 1M je Upside-Label",
        yaxis_title="Performance %", height=300,
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig2, use_container_width=True)

    st.caption(
        "Wenn 'Hoch' nicht deutlich besser abschneidet als 'Gering', "
        "können die Gewichte in `config.UPSIDE` angepasst werden."
    )


def _render_signal_table(sig_data: list[dict]):
    if not sig_data:
        st.info("Noch keine auswertbaren Daten.")
        return

    rows = []
    for s in sig_data:
        delta = s["delta"]
        warn = " ⚠️" if (delta is not None and delta < 0) else ""
        rows.append({
            "Signal": s["signal"],
            "Aktiv (n)": s["active_n"],
            "Ø Perf aktiv": f"{s['active_avg_perf']:+.1f}%" if s["active_avg_perf"] is not None else "—",
            "Inaktiv (n)": s["inactive_n"],
            "Ø Perf inaktiv": f"{s['inactive_avg_perf']:+.1f}%" if s["inactive_avg_perf"] is not None else "—",
            "Delta": f"{delta:+.1f}%{warn}" if delta is not None else "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption("⚠️ = Signal mit negativem Delta — Aktiv-Empfehlungen schnitten schlechter ab als Inaktiv-Empfehlungen.")


def _render_sector_chart(sector_data: list[dict]):
    if not sector_data:
        st.info("Noch keine Sektor-Daten.")
        return

    import plotly.graph_objects as go

    sectors = [s["sector"] for s in sector_data]
    avg_perfs = [s["avg_perf"] for s in sector_data]
    ns = [s["n"] for s in sector_data]

    fig = go.Figure(go.Bar(
        x=avg_perfs, y=sectors, orientation="h",
        marker_color=["#4CAF50" if p >= 0 else "#F44336" for p in avg_perfs],
        text=[f"{v:+.1f}% (n={n})" for v, n in zip(avg_perfs, ns)],
        textposition="outside",
    ))
    fig.add_vline(x=0, line_color="gray")
    fig.update_layout(
        title="Ø Performance 1M je Sektor",
        xaxis_title="Performance %", height=max(300, 40 * len(sectors)),
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_vix_chart(vix_data: list[dict]):
    if not vix_data:
        st.info("Noch keine VIX-Kontext-Daten (ältere Log-Einträge haben keinen Marktkontext).")
        return

    import plotly.graph_objects as go

    buckets = [v["vix_bucket"] for v in vix_data]
    perfs = [v["avg_perf"] for v in vix_data]
    ns = [v["n"] for v in vix_data]

    fig = go.Figure(go.Bar(
        x=buckets, y=perfs,
        marker_color=["#4CAF50" if p >= 0 else "#F44336" for p in perfs],
        text=[f"{v:+.1f}% (n={n})" for v, n in zip(perfs, ns)],
        textposition="outside",
    ))
    fig.add_hline(y=0, line_color="gray")
    fig.update_layout(
        title="Ø Performance 1M je VIX-Bereich",
        yaxis_title="Performance %", height=300,
        margin=dict(l=0, r=0, t=50, b=0),
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_all_recommendations_table(enriched: list[dict]):
    rows = []
    for r in enriched:
        rows.append({
            "Datum": r.get("rec_date", ""),
            "Ticker": r.get("ticker", ""),
            "Konfidenz": r.get("confidence_label", "—"),
            "Sektor": r.get("sector", "N/A"),
            "Einstieg": f"${r['price']:.2f}" if r.get("price") else "—",
            "Perf 1W": f"{r['performance_1w']:+.1f}%" if r.get("performance_1w") is not None else "—",
            "Perf 1M": f"{r['performance_1m']:+.1f}%" if r.get("performance_1m") is not None else "—",
            "Perf 3M": f"{r['performance_3m']:+.1f}%" if r.get("performance_3m") is not None else "—",
            "vs SPY": f"{r['perf_vs_spy_1m']:+.1f}%" if r.get("perf_vs_spy_1m") is not None else "—",
            "Hit (1M)": "✅" if r.get("hit_1m") else ("❌" if r.get("performance_1m") is not None else "—"),
        })

    df = pd.DataFrame(rows).sort_values(["Datum", "Konfidenz"], ascending=[False, True])

    col1, col2 = st.columns([2, 1])
    with col1:
        label_opts = ["Alle"] + sorted(df["Konfidenz"].dropna().unique().tolist())
        sel_label = st.selectbox("Konfidenz filtern", label_opts, key="perf_label_filter")
    with col2:
        only_measurable = st.checkbox("Nur auswertbare (≥30d)", value=False)

    filtered = df.copy()
    if sel_label != "Alle":
        filtered = filtered[filtered["Konfidenz"] == sel_label]
    if only_measurable:
        filtered = filtered[filtered["Perf 1M"] != "—"]

    st.caption(f"{len(filtered)} Einträge")
    st.dataframe(filtered, use_container_width=True, hide_index=True)


def _render_export_section(enriched, generate_markdown_report, generate_json_export):
    st.subheader("Export für Claude — Code-Verbesserungsanalyse")
    st.write(
        "Generiere einen vollständigen Performance-Report, den du direkt an Claude geben kannst. "
        "Claude analysiert, welche Signale funktionieren, welche Schwellen angepasst werden sollten "
        "und wo die Strategie systematische Schwächen hat."
    )

    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**Markdown-Report** (für Claude empfohlen)")
        st.caption("Strukturierter Bericht mit Tabellen, Signalanalyse, Konfiguration und konkretem Auftrag an Claude.")
        if st.button("📄 Markdown generieren", type="primary"):
            with st.spinner("Erstelle Report..."):
                md = generate_markdown_report(enriched)
            st.download_button(
                label="⬇️ performance_report.md herunterladen",
                data=md.encode("utf-8"),
                file_name=f"performance_report_{datetime.today().strftime('%Y-%m-%d')}.md",
                mime="text/markdown",
            )
            with st.expander("Vorschau (erste 3000 Zeichen)"):
                st.code(md[:3000] + ("..." if len(md) > 3000 else ""), language="markdown")

    with col2:
        st.markdown("**Roh-JSON** (Rohdaten)")
        st.caption("Alle angereicherten Empfehlungsdaten mit Performance-Werten. Für eigene Auswertung.")
        if st.button("📦 JSON generieren"):
            with st.spinner("Erstelle JSON..."):
                js = generate_json_export(enriched)
            st.download_button(
                label="⬇️ performance_export.json herunterladen",
                data=js.encode("utf-8"),
                file_name=f"performance_export_{datetime.today().strftime('%Y-%m-%d')}.json",
                mime="application/json",
            )

    st.divider()
    st.info(
        "**Workflow:** Report herunterladen → In Claude (claude.ai oder Claude Code) hochladen → "
        "Fragen: *'Analysiere diesen Performance-Report und schlage konkrete Verbesserungen für config.py vor.'*",
        icon="💡"
    )


# ── Hauptschleife ─────────────────────────────────────────────────────────────

def main():
    init_app()

    from portfolio.auth import render_auth_gate
    if not render_auth_gate():
        return

    # Einmalige Migration aus portfolio.json falls noch vorhanden
    if not st.session_state.get("migration_checked"):
        st.session_state.migration_checked = True
        try:
            from portfolio.manager import auto_migrate_from_json
            msg = auto_migrate_from_json()
            if msg:
                st.success(f"✅ {msg}", icon="📦")
        except Exception:
            pass

    render_sidebar_secondary()
    page = render_top_nav()
    result = st.session_state.scan_result

    if page == "Marktübersicht":
        page_market_overview(result)
    elif page == "Empfehlungen":
        page_recommendations(result)
    elif page == "Mein Portfolio":
        page_portfolio()
    elif page == "Performance":
        page_performance()
    elif page == "Vollständiger Scan":
        page_full_scan(result)


if __name__ == "__main__":
    main()
