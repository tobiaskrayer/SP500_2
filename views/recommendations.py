"""Seite: Empfehlungen (v1-Karten + v2-Panel)."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from views.common import _render_exit_signals


def _render_v2_panel(result: dict, recommendations: list):
    """
    Zeigt die parallele v2-Empfehlungsliste (datengetrieben optimiert) und die
    Überschneidung mit v1. v2 ändert v1 nicht — reiner Vergleich.
    """
    v2 = result.get("recommendations_v2")
    if v2 is None:
        return  # älterer Cache ohne v2 — nichts anzeigen

    v1_tickers = {r.get("ticker") for r in recommendations}
    v2_tickers = {r.get("ticker") for r in v2}
    both = v1_tickers & v2_tickers
    v2_only = v2_tickers - v1_tickers
    v1_only = v1_tickers - v2_tickers

    with st.expander(f"🔬 Paralleler v2-Algorithmus — {len(v2_tickers)} Empfehlungen "
                     f"({len(both)} Überschneidung mit v1)", expanded=False):
        st.caption(
            "**v2** ist eine datengetriebene Alternative aus dem 10-Jahres-Backtest: strengerer "
            "RS-Schnitt (Top 20 %), Trend-Pflicht (über MA50 & MA200), nicht überkauft, begrenzt "
            "auf die **10 RS-stärksten** (Top-N-Befund) — **ohne** die Tech-Score-Schwelle (die "
            "historisch keine Vorhersagekraft hatte). Im Backtest (Top-10): +2,12 % vs SPY/Monat "
            "(v1-Korb: +0,27 %), ⭐ Top-5 sogar +3,19 %. Achtung: absolute Zahlen wegen "
            "Survivorship-Bias optimistisch. Läuft parallel, ändert die v1-Empfehlungen oben nicht."
        )
        if not v2_tickers:
            st.info("v2 hat aktuell keine Empfehlungen (strengerer Filter als v1).")
            return

        rows = []
        for r in sorted(v2, key=lambda x: (x.get("v2_rank") or 99,
                                           -(x.get("rs", {}).get("rs_score") or 0))):
            tk = r.get("ticker")
            rs = r.get("rs", {})
            rank = r.get("v2_rank")
            macd = r.get("macd_bull")
            rows.append({
                "Rang": rank if rank is not None else "—",
                "Ticker": ("⭐ " if (rank is not None and rank <= 5) else "") + tk,
                "Name": (r.get("name") or "")[:28],
                "Sektor": r.get("sector") or "—",
                "RS-Score": round(rs.get("rs_score") or 0, 1),
                "MACD": "🟢" if macd else ("🔴" if macd is not None else "—"),
                "Tech": f"{(r.get('tech_score') or 0)*100:.0f}%",
                "Fund": f"{(r.get('fund_score') or 0)*100:.0f}%",
                "auch in v1": "✅" if tk in both else "—",
            })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        c1, c2, c3 = st.columns(3)
        c1.metric("Nur v2", len(v2_only), help="Titel, die v2 empfiehlt, v1 aber nicht.")
        c2.metric("Beide", len(both))
        c3.metric("Nur v1", len(v1_only), help="Titel, die v1 empfiehlt, v2 aber nicht (z.B. nicht im Top-20%-RS).")


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

    _render_v2_panel(result, recommendations)
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


def _series_values(obj) -> list | None:
    """Normalisiert Chart-Daten: pd.Series / dict / list → Werte-Liste.
    Der Tages-Cache speichert Serien als kompakte Listen (scheduler._slim_for_cache),
    frische Scans liefern pd.Series, alte Caches Dicts mit Datums-Keys."""
    if obj is None:
        return None
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, dict):
        return list(obj.values())
    if isinstance(obj, list):
        return obj
    return None


def _render_stock_charts(ticker: str, hist, tech: dict):
    if isinstance(hist, dict):
        close = _series_values(hist.get("Close")) or []
    elif hasattr(hist, "to_dict"):
        close = hist["Close"].tolist()
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
    fig.add_trace(go.Scatter(y=close, name="Kurs", line=dict(color="#2196F3", width=2)), row=1, col=1)

    def _add_ma(key, label, color, dash):
        ma_data = _series_values(indicators.get(key))
        if ma_data is not None:
            fig.add_trace(go.Scatter(y=ma_data, name=label, line=dict(color=color, width=1.5, dash=dash)), row=1, col=1)

    _add_ma("ma50", "50-MA", "#FF9800", "dot")
    _add_ma("ma200", "200-MA", "#F44336", "dash")

    # Bollinger Bands
    for key, label in [("bb_upper", "BB Oben"), ("bb_lower", "BB Unten")]:
        vals = _series_values(indicators.get(key))
        if vals is not None:
            fig.add_trace(go.Scatter(y=vals, name=label, line=dict(color="#9E9E9E", width=1, dash="dot"), opacity=0.5), row=1, col=1)

    # RSI
    vals = _series_values(indicators.get("rsi"))
    if vals is not None:
        fig.add_trace(go.Scatter(y=vals, name="RSI", line=dict(color="#9C27B0", width=1.5)), row=2, col=1)
        fig.add_hline(y=70, line_dash="dash", line_color="red", opacity=0.5, row=2, col=1)
        fig.add_hline(y=45, line_dash="dash", line_color="green", opacity=0.5, row=2, col=1)

    # MACD
    mv = _series_values(indicators.get("macd_line"))
    sv = _series_values(indicators.get("signal_line"))
    hv = _series_values(indicators.get("histogram"))
    if mv is not None and sv is not None and hv is not None:
        fig.add_trace(go.Scatter(y=mv, name="MACD", line=dict(color="#2196F3")), row=3, col=1)
        fig.add_trace(go.Scatter(y=sv, name="Signal", line=dict(color="#FF9800")), row=3, col=1)
        colors = ["#4CAF50" if (v or 0) >= 0 else "#F44336" for v in hv]
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

