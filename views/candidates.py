"""Kandidaten der aktiven v2-Auswahl ohne zusätzliche versteckte Filter."""
import pandas as pd
import streamlit as st
from analyzer.allocation import allocate
from config import PORTFOLIO_RISK, RECOMMENDER_V2


def candidate_rows(result):
    return sorted(result.get("recommendations_v2", []),
                  key=lambda r: (r.get("v2_rank") or 999, r["ticker"]))


def page_buy_candidates(result):
    st.header("🛒 Kauf-Kandidaten")
    st.caption("Aktive v2-Auswahl: relative Stärke, Trend und Einstieg. Rangfolge wie im Scan.")
    if result is None:
        st.info("Noch keine Analysedaten. Starte die Analyse über die Seitenleiste.")
        return
    if not result.get("market", {}).get("passed"):
        st.warning("Keine Kauf-Kandidaten: " + result.get("market", {}).get("reason", "Marktfilter nicht erfüllt."))
        return
    candidates = candidate_rows(result)
    if not candidates:
        st.info("Heute keine Kandidaten der aktiven Strategie.")
        return
    rows = []
    for r in candidates:
        score = (r.get("rs") or {}).get("rs_score")
        rows.append({"Rang": r.get("v2_rank"), "Aktie": r["ticker"],
                     "Name": r.get("name"), "Sektor": r.get("sector"),
                     "RS-Score": score, "Kurs (USD)": r.get("price"),
                     "Kursstand": r.get("data_as_of"),
                     "Hinweis": "Stark gelaufen" if score is not None and score > RECOMMENDER_V2.get("parabolic_rs_warn", 150) else ""})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.caption("Risikohinweise verändern die Rangfolge nicht. Ein Kriterienwert ist keine Gewinnwahrscheinlichkeit.")
    ticker = st.selectbox("Details zu einer Aktie", [r["ticker"] for r in candidates], key="candidate_detail")
    from views.recommendations import _render_stock_card
    _render_stock_card(next(r for r in candidates if r["ticker"] == ticker), expanded=True)
    with st.expander("Budget und bestehende Positionen"):
        st.caption("Grenzen beziehen sich auf das verfügbare Budget plus den Wert einbezogener Bestände.")
        cash = st.number_input("Verfügbares Budget (EUR)", min_value=0.0, value=10000.0, step=500.0)
        include_holdings = st.checkbox("Bestehendes Portfolio berücksichtigen", value=True)
        if not st.button("Verteilung berechnen"):
            return
        holdings = []
        if include_holdings:
            try:
                from portfolio.manager import evaluate_positions
                positions = evaluate_positions(market_bearish=False)
                if any(p.get("current_price_eur") is None for p in positions):
                    st.error("Für mindestens eine Position fehlt ein EUR-Kurs. Keine verlässliche Verteilung möglich.")
                    return
                holdings = [{"ticker": p["ticker"], "sector": p.get("sector"),
                             "value": p["current_price_eur"] * p["total_shares"]} for p in positions]
            except Exception:
                st.error("Bestehende Positionen konnten nicht bewertet werden.")
                return
        try:
            allocation = allocate(candidates, cash, holdings)
        except ValueError as exc:
            st.error(str(exc))
            return
        st.dataframe(pd.DataFrame([{"Aktie": tk, "Budget (EUR)": value}
                                  for tk, value in allocation["positions"].items()]), hide_index=True)
        st.write(f"Cash verbleibend: {allocation['cash_remaining']:,.2f} EUR")
        st.caption(f"Maximal {PORTFOLIO_RISK['max_position_weight']:.0%} pro Titel und {PORTFOLIO_RISK['max_sector_weight']:.0%} pro Sektor. Keine automatische Order.")
