"""Seite: Performance-Tracking der Empfehlungen."""

import streamlit as st
import pandas as pd
from datetime import datetime


def _render_v1_v2_performance(stats_v1: dict, stats_v2: dict):
    """
    Live-/Out-of-Sample-Vergleich der realisierten Performance v1 vs v2.
    Wird nur gezeigt, sobald v2-Empfehlungen im Log mitprotokolliert wurden.
    Im Gegensatz zum Backtest ist dieser Vergleich frei von Survivorship-Bias.
    """
    with st.expander("🔬 v1 vs v2 — realisierte Performance (Out-of-Sample)", expanded=True):
        st.caption(
            "Vergleich der tatsächlich protokollierten Empfehlungen beider Algorithmen ab "
            "Einführung von v2. Anfangs dünn — je länger getrackt, desto aussagekräftiger. "
            "Dies ist der ehrlichste Test (keine Survivorship-Verzerrung wie im Backtest)."
        )

        def _row(label, s):
            n = s.get("total", 0)
            meas = s.get("measurable", 0)
            hit = s.get("hit_rate")
            perf = s.get("avg_perf_1m")
            vs = s.get("avg_vs_spy_1m")
            return {
                "Algorithmus": label,
                "Empfehlungen": n,
                "messbar (≥30T)": meas,
                "Trefferquote 1M": f"{hit:.1f}%" if hit is not None and meas else "—",
                "Ø Perf 1M": f"{perf:+.2f}%" if perf is not None else "—",
                "Ø vs SPY 1M": f"{vs:+.2f}%" if vs is not None else "—",
            }

        st.dataframe(
            pd.DataFrame([_row("v1 (aktuell)", stats_v1), _row("v2 (optimiert)", stats_v2)]),
            use_container_width=True, hide_index=True,
        )

        m1, m2 = stats_v1.get("measurable", 0), stats_v2.get("measurable", 0)
        if m1 < 10 or m2 < 10:
            st.info(
                f"Noch zu wenig messbare Out-of-Sample-Daten (v1: {m1}, v2: {m2} mit ≥30 Tagen) "
                "für ein belastbares Urteil. Der Vergleich wird mit jedem Scan aussagekräftiger. "
                "Die historische A/B-Evidenz steht in `backtest/FINDINGS.md`."
            )


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

    # Aktuelle Exit-Signale für noch offene Empfehlungen (≤91 Tage)
    from history.performance import enrich_with_current_exits
    with st.spinner("Prüfe aktuelle Exit-Signale..."):
        enriched = enrich_with_current_exits(enriched)

    # Warn-Banner für aktive Verkaufssignale
    sell_alerts = [
        r for r in enriched
        if r.get("current_exit_rec") == "Verkaufen erwägen"
        and (r.get("days_since") or 999) <= 91
    ]
    watch_alerts = [
        r for r in enriched
        if r.get("current_exit_rec") == "Beobachten"
        and (r.get("days_since") or 999) <= 91
    ]
    if sell_alerts:
        with st.expander(
            f"🚫 {len(sell_alerts)} aktive Verkaufssignale für Empfehlungen der letzten 3 Monate",
            expanded=True,
        ):
            for a in sorted(sell_alerts, key=lambda x: x.get("current_exit_signals", 0), reverse=True):
                pnl = a.get("current_pnl_pct")
                pnl_str = f"{pnl:+.1f}%" if pnl is not None else "—"
                stop = "⛔ Stop-Loss unterschritten! " if a.get("stop_hit") else ""
                st.write(
                    f"**{a['ticker']}** (empfohlen {a['rec_date']}, {a.get('days_since')} Tage) — "
                    f"{a.get('current_exit_signals', 0)}/7 Signale — aktuelle P&L: {pnl_str} {stop}"
                )
    elif watch_alerts:
        st.warning(
            f"⚠️ {len(watch_alerts)} Empfehlungen aus den letzten 3 Monaten zeigen erste Exit-Signale "
            f"('Beobachten'): {', '.join(a['ticker'] for a in watch_alerts)}",
        )

    if not enriched:
        st.info("Keine Empfehlungen in der Historie gefunden.")
        return

    stats = ana.summary_stats(enriched)

    # ── v1-vs-v2-Vergleich (Out-of-Sample, sobald v2-Historie existiert) ───────
    if any(e.get("recommendations_v2") for e in log):
        enriched_v2 = enrich_with_performance(log, key="recommendations_v2")
        _render_v1_v2_performance(ana.summary_stats(enriched), ana.summary_stats(enriched_v2))

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
    _EXIT_ICONS = {"Halten": "✅", "Beobachten": "⚠️", "Verkaufen erwägen": "🚫"}
    for r in enriched:
        exit_rec = r.get("current_exit_rec")
        exit_str = (
            f"{_EXIT_ICONS.get(exit_rec, '')} {exit_rec} ({r.get('current_exit_signals', 0)}/7)"
            if exit_rec else "—"
        )
        cur_pnl = r.get("current_pnl_pct")
        rows.append({
            "Datum": r.get("rec_date", ""),
            "Ticker": r.get("ticker", ""),
            "Konfidenz": r.get("confidence_label", "—"),
            "Sektor": r.get("sector", "N/A"),
            "Einstieg": f"${r['price']:.2f}" if r.get("price") else "—",
            "Akt. P&L": f"{cur_pnl:+.1f}%" if cur_pnl is not None else "—",
            "Exit-Status": exit_str,
            "Stop-Hit": "⛔" if r.get("stop_hit") else ("—" if r.get("current_exit_rec") else ""),
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

