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
    initial_sidebar_state="expanded",
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


# ── Sidebar ───────────────────────────────────────────────────────────────────

def render_sidebar():
    with st.sidebar:
        st.title("📈 S&P500 Analyse")
        st.caption("Sehr konservative Kaufempfehlungen")
        st.divider()

        page = st.radio(
            "Navigation",
            ["Marktübersicht", "Empfehlungen", "Vollständiger Scan"],
            index=0,
        )

        st.divider()

        # Scan-Button (nur lokal — auf Streamlit Cloud läuft GitHub Actions)
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

        # Letzte Aktualisierung
        if st.session_state.scan_result:
            ts = st.session_state.scan_result.get("timestamp", "")
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                    st.caption(f"Letzte Analyse: {dt.strftime('%d.%m.%Y %H:%M')}")
                except Exception:
                    pass

        st.divider()
        st.caption("Datenquelle: Yahoo Finance (yfinance)")
        st.caption("Kein Anlageberater — nur zur Information")

    return page


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

    st.success(f"{len(recommendations)} Kaufempfehlung{'en' if len(recommendations) > 1 else ''} gefunden", icon="✅")
    st.divider()

    for stock in recommendations:
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

    with st.expander(f"**{ticker}** — {name}  |  {sector}  |  ${price:.2f}" if price else f"**{ticker}** — {name}", expanded=False):

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

        tab1, tab2, tab3, tab4 = st.tabs(["📈 Charts", "📊 Technische Signale", "📋 Fundamentaldaten", "↗️ Relative Stärke"])

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


# ── Hauptschleife ─────────────────────────────────────────────────────────────

def main():
    init_app()
    page = render_sidebar()
    result = st.session_state.scan_result

    if page == "Marktübersicht":
        page_market_overview(result)
    elif page == "Empfehlungen":
        page_recommendations(result)
    elif page == "Vollständiger Scan":
        page_full_scan(result)


if __name__ == "__main__":
    main()
