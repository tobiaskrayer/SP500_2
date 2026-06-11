"""Seite: Vollständiger Scan (alle Titel mit Gate-Ergebnissen)."""

import streamlit as st
import pandas as pd

from views.common import _fmt_ts


def page_full_scan(result: dict | None):
    st.header("Vollständiger Scan")

    if result is None:
        st.info("Noch keine Analysedaten. Starte die Analyse über die Seitenleiste.")
        return

    all_results = result.get("all_results", [])
    if not all_results:
        market_passed = result.get("market", {}).get("passed", False)
        reason = result.get("market", {}).get("reason", "")
        if not market_passed:
            st.warning(
                f"Gate 1 hat diesen Scan blockiert — Markt war zum Scan-Zeitpunkt bearisch.\n\n"
                f"Grund: {reason}\n\n"
                "Der nächste automatische Scan läuft nach Marktschluss. "
                "Sobald Gate 1 besteht, erscheinen hier die Ergebnisse.",
                icon="🚫",
            )
        else:
            ts = result.get("timestamp", "")
            st.warning(
                f"Der Scan lief (Gate 1 ✅), aber es konnten keine Aktien analysiert werden.\n\n"
                f"Mögliche Ursache: yfinance-Ratenlimit oder Netzwerkfehler. "
                f"Scan vom: {_fmt_ts(ts)}\n\n"
                "Klicke **Analyse neu starten** — der Scan läuft jetzt mit weniger parallelen "
                "Anfragen und sollte durchkommen.",
                icon="⚠️",
            )
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

