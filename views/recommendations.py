"""Details zur gleichen aktiven Auswahl wie auf der Kandidatenseite."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def _series_values(series):
    if series is None:
        return None
    if isinstance(series, dict):
        return list(series.values())
    return list(series)


def page_recommendations(result):
    st.header("Empfehlungen im Detail")
    if result is None:
        st.info("Noch keine Analysedaten. Starte die Analyse über die Seitenleiste.")
        return
    from views.candidates import candidate_rows
    candidates = candidate_rows(result) if result.get("market", {}).get("passed") else []
    if not candidates:
        st.info("Keine aktiven Kandidaten. Marktstatus und Datenstand stehen oben.")
        return
    ticker = st.selectbox("Aktie", [r["ticker"] for r in candidates], key="recommendation_detail")
    _render_stock_card(next(r for r in candidates if r["ticker"] == ticker), expanded=True)
    with st.expander("Methode und Vergleich"):
        st.write("v2 bewertet relative Stärke über das gesamte verfügbare Universum vor den weiteren Filtern. Trend, Überkauft-Grenze und Fundamentalgate bestimmen anschließend die Auswahl.")
        st.caption("v1 bleibt als Diagnose in den Scandaten erhalten. Historische Ergebnisse ohne zeitgenössisches Universum und Fundamentaldaten sind kein Nachweis künftiger Renditen.")


def _render_stock_card(stock, expanded=False):
    with st.expander(f"{stock['ticker']} · {stock.get('name') or ''}", expanded=expanded):
        c1, c2, c3 = st.columns(3)
        price = stock.get("price")
        c1.metric("Kurs (USD)", f"{price:.2f}" if price is not None else "—")
        c2.metric("v2-Rang", stock.get("v2_rank") or "—")
        score = stock.get("combined_score")
        c3.metric("Kriterienwert", f"{score * 100:.0f}/100" if isinstance(score, (int, float)) else "—")
        st.caption(f"Kursstand: {stock.get('data_as_of') or 'im alten Snapshot nicht gespeichert'}. Kriterienwerte sind keine Gewinnwahrscheinlichkeit.")
        exits = stock.get("exits") or {}
        if exits.get("recommendation") and exits["recommendation"] != "Halten":
            st.warning("Beobachtung für Bestandstitel: " + exits["recommendation"])
        chart, evidence = st.tabs(["Kursverlauf", "Auswahlgrundlagen"])
        with chart:
            _render_stock_charts(stock)
        with evidence:
            rs = stock.get("rs") or {}
            st.dataframe(pd.DataFrame([{"Kennzahl": key, "Wert": value}
                                      for key, value in rs.items() if isinstance(value, (int, float))]), hide_index=True)
            for label, data in (("Technik", stock.get("tech") or {}), ("Fundamentaldaten", stock.get("fund") or {})):
                st.write(label)
                signals = data.get("signals") or {}
                if signals:
                    st.dataframe(pd.DataFrame([{"Kriterium": key, "Erfüllt": bool(value)}
                                              for key, value in signals.items()]), hide_index=True)
                if data.get("missing_metrics"):
                    st.warning("Fehlende Kennzahlen (zählen nicht als erfüllt): " + ", ".join(data["missing_metrics"]))
            st.caption("Automatische Stop- und Zielkurse werden ohne validierte Ausführungsregel nicht abgeleitet.")


def _render_stock_charts(stock):
    hist = stock.get("hist")
    close = _series_values(hist.get("Close")) if hist is not None else None
    if not close:
        st.info("Kein Kursverlauf im Snapshot verfügbar.")
        return
    dates = stock.get("chart_dates")
    if dates is None and isinstance(hist, pd.DataFrame):
        dates = list(hist.index)
    if dates is None or len(dates) != len(close):
        dates = list(range(len(close)))
        st.caption("Alter Snapshot ohne Datumsachse: Handelstage relativ zum Beginn.")
    fig = go.Figure(go.Scatter(x=dates, y=close, name="Schlusskurs"))
    for key, label in (("ma50", "MA50"), ("ma200", "MA200")):
        values = _series_values((stock.get("tech") or {}).get("indicators", {}).get(key))
        if values is not None and len(values) == len(close):
            fig.add_trace(go.Scatter(x=dates, y=values, name=label))
    fig.update_layout(height=400, yaxis_title="USD", margin=dict(l=10, r=10, t=20, b=10))
    st.plotly_chart(fig, use_container_width=True)
