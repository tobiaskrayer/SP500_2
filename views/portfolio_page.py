"""Seite: Mein Portfolio (Lots aus data/portfolio.json, Bewertung, History)."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from views.common import _render_exit_signals


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
                    textinfo="percent",
                    textposition="inside",
                ))
                fig_donut.update_layout(
                    title="Portfolio-Verteilung (nach Marktwert)",
                    height=320, margin=dict(l=0, r=0, t=40, b=0),
                    showlegend=True,
                    legend=dict(orientation="h", y=-0.15, x=0.5, xanchor="center"),
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
                    _render_exit_signals(exits, entry_price=p.get("current_price_eur"))

                    st.divider()

                    with st.expander("💰 Verkauf nachtragen", expanded=False):
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
                # realized mitgeben: verkaufte Stücke zählen in der Vergangenheit mit,
                # sonst wäre die History nach jedem Verkauf rückwirkend falsch.
                hist_data = get_portfolio_history(positions, realized=realized,
                                                  user_id=current_user_id())

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

