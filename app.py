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
            ["Marktübersicht", "Empfehlungen", "Mein Portfolio", "Performance", "Vollständiger Scan"],
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

    # Sortierung nach combined_score (Strong Buy zuerst)
    # Falls Score im Cache fehlt, aus tech/fund-Score nachberechnen
    from analyzer.confidence import compute_confidence
    for r in recommendations:
        if not r.get("combined_score") and (r.get("tech", {}).get("score") or r.get("fund", {}).get("score")):
            conf = compute_confidence(r.get("tech", {}).get("score", 0), r.get("fund", {}).get("score", 0), r.get("rs") or {})
            r["combined_score"] = conf["combined_score"]
            r["confidence_label"] = conf["confidence_label"]
    recommendations_sorted = sorted(recommendations, key=lambda x: x.get("combined_score", 0), reverse=True)

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

    header = (
        f"**{ticker}** — {name}  |  {sector}  |  ${price:.2f}  |  {conf_icon} {confidence_label}"
        if price else
        f"**{ticker}** — {name}  |  {conf_icon} {confidence_label}"
    )

    with st.expander(header, expanded=False):

        # Konfidenz-Banner
        col_conf1, col_conf2 = st.columns([3, 1])
        with col_conf1:
            st.progress(combined_score, text=f"Konfidenz-Score: {combined_score*100:.0f}% — {confidence_label}")
        with col_conf2:
            exits = stock.get("exits", {})
            rec = exits.get("recommendation", "Halten")
            rec_colors = {"Halten": "✅", "Beobachten": "⚠️", "Verkaufen erwägen": "🚫"}
            st.write(f"Exit: {rec_colors.get(rec, '')} **{rec}**")

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

    from portfolio.manager import load_portfolio, add_position, remove_position, evaluate_positions

    # Positionen auswerten
    with st.spinner("Lade aktuelle Kurse..."):
        positions = evaluate_positions()

    if not positions:
        st.info("Noch keine Positionen eingetragen. Füge deine erste Position unten hinzu.")
    else:
        # Übersichtstabelle
        rows = []
        for p in positions:
            exits = p.get("exits", {})
            rec = exits.get("recommendation", "—")
            rec_icon = {"Halten": "✅", "Beobachten": "⚠️", "Verkaufen erwägen": "🚫"}.get(rec, "—")
            rows.append({
                "Ticker": p["ticker"],
                "Einstieg": f"${p['entry_price']:.2f}",
                "Datum": p["entry_date"],
                "Tage": p["days_held"] if p["days_held"] is not None else "—",
                "Kurs aktuell": f"${p['current_price']:.2f}" if p["current_price"] else "N/A",
                "P&L %": f"{p['pnl_pct']:+.1f}%" if p["pnl_pct"] is not None else "N/A",
                "P&L €/$": f"{p['pnl_abs']:+.2f}" if p["pnl_abs"] is not None else "N/A",
                "Signale": exits.get("signal_count", 0),
                "Empfehlung": f"{rec_icon} {rec}",
            })

        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        st.divider()

        # Detail-Expander pro Position
        for i, p in enumerate(positions):
            exits = p.get("exits", {})
            rec = exits.get("recommendation", "—")
            with st.expander(f"**{p['ticker']}** — Details & Exit-Signale", expanded=False):
                _render_exit_signals(exits, entry_price=p["entry_price"])
                st.divider()
                if st.button(f"Position entfernen ({p['ticker']})", key=f"remove_{i}", type="secondary"):
                    remove_position(i)
                    st.rerun()

    st.divider()
    st.subheader("Position hinzufügen")
    with st.form("add_position_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            ticker_in = st.text_input("Ticker (z.B. AAPL)", max_chars=10)
            price_in = st.number_input("Kaufkurs ($)", min_value=0.01, step=0.01, format="%.2f")
        with col2:
            date_in = st.date_input("Kaufdatum", value=datetime.today())
            shares_in = st.number_input("Anzahl Aktien", min_value=0.01, step=1.0, format="%.2f")
        notes_in = st.text_input("Notiz (optional)", max_chars=200)
        submitted = st.form_submit_button("Position speichern", type="primary")
        if submitted:
            if ticker_in and price_in > 0 and shares_in > 0:
                add_position(ticker_in, str(date_in), price_in, shares_in, notes_in)
                st.success(f"{ticker_in.upper()} hinzugefügt!")
                st.rerun()
            else:
                st.error("Bitte Ticker, Kaufkurs und Anzahl angeben.")


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
    tab1, tab2, tab3, tab4, tab5 = st.tabs([
        "📊 Konfidenz-Kalibrierung",
        "🔬 Signal-Wirksamkeit",
        "🏭 Sektoren",
        "📈 Alle Empfehlungen",
        "📥 Export für Claude",
    ])

    with tab1:
        _render_confidence_chart(ana.by_confidence(enriched))

    with tab2:
        st.subheader("Technische Signale")
        _render_signal_table(ana.signal_effectiveness(enriched, "tech"))
        st.subheader("Fundamentals-Signale")
        _render_signal_table(ana.signal_effectiveness(enriched, "fund"))

    with tab3:
        col_a, col_b = st.columns(2)
        with col_a:
            _render_sector_chart(ana.by_sector(enriched))
        with col_b:
            _render_vix_chart(ana.by_vix(enriched))

    with tab4:
        _render_all_recommendations_table(enriched)

    with tab5:
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
    page = render_sidebar()
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
