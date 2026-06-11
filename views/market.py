"""Seite: Marktübersicht."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from views.common import _fmt_ts


def page_market_overview(result: dict | None):
    st.header("Marktübersicht")

    if result is None:
        st.caption("Kein gecachter Scan vorhanden — lade aktuelle Marktdaten live.")
        _show_quick_market()
        return

    # Gecachte Daten anzeigen, aber Alter des Scans kennzeichnen
    ts = result.get("timestamp", "")
    if ts:
        try:
            from datetime import datetime as _dt
            scan_age = (_dt.now() - _dt.fromisoformat(ts)).total_seconds() / 3600
            if scan_age > 20:
                st.caption(f"⏱ Scan-Daten vom {_fmt_ts(ts)} — live-Daten werden heute Abend aktualisiert.")
        except Exception:
            pass

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
        if vix is None:
            st.write("➖ VIX-Daten nicht verfügbar")
        else:
            icon = "✅" if vix <= 25 else "❌"
            st.write(f"{icon} VIX unter 25")

    # Regime-Indikator
    if vix is not None:
        try:
            from config import MARKET as _MARKET_CFG
            _vix_max = _MARKET_CFG.get("vix_max", 20)
        except ImportError:
            _vix_max = 20
        if vix > _vix_max:
            st.info(
                f"Erhöhtes VIX-Regime (VIX {vix:.1f} > {_vix_max}) — Scoring gewichtet "
                "Fundamentals stärker, Exit-Schwellen sind enger.",
                icon="⚡",
            )
        else:
            st.caption(f"Normales VIX-Regime (VIX {vix:.1f} ≤ {_vix_max}) — Standardgewichtung aktiv.")


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

