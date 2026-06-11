"""Seite: Backtest (Ergebnisse, Sweep, Spielwiese)."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go


def page_backtest():
    st.header("Backtest — Historische Signal-Validierung")
    st.caption(
        "Simuliert den wöchentlichen Scan über historische Kursdaten. "
        "**Backtested:** Gate 1 (Markt), Gate 2 (Relative Stärke), Gate 3 (Technik). "
        "**Nicht backtested:** Gate 4 (Fundamentaldaten — keine historischen yfinance-Snapshots verfügbar)."
    )

    from backtest.runner import (run_backtest, load_cached_results, run_param_sweep,
                                 run_custom_backtest, apply_overrides, clear_overrides,
                                 load_sweep_results, load_overrides)

    cached = load_cached_results()

    # Konfiguration
    with st.expander("Einstellungen", expanded=cached is None):
        col1, col2 = st.columns(2)
        with col1:
            years = st.slider("Zeitraum (Jahre)", min_value=1, max_value=10, value=2,
                              help="Mehr Jahre = mehr Simulationsdaten. Aber: yfinance liefert nur die "
                                   "aktuelle S&P500-Zusammensetzung → stärkerer Survivorship-Bias "
                                   "je weiter zurück. Erster Lauf mit vielen Jahren dauert länger.")
        with col2:
            step_weeks = st.slider("Scan-Intervall (Wochen)", min_value=1, max_value=4, value=2,
                                   help="Wie oft pro Monat wird ein Scan simuliert.")

    run_button = st.button(
        "Backtest starten" if cached is None else "Backtest neu berechnen",
        type="primary",
        help="Erster Lauf lädt historische Kursdaten für alle S&P500-Aktien (je nach Jahreszahl 5–30 min). "
             "Folgeanläufe nutzen Cache.",
    )

    if run_button:
        progress_bar = st.progress(0.0)
        status_text = st.empty()
        phase_map = {"download": "Lade Kursdaten", "precompute": "Berechne Indikatoren", "simulate": "Simuliere Scans"}

        def _cb(phase, current, total, info=""):
            label = phase_map.get(phase, phase)
            pct = current / total if total > 0 else 0
            progress_bar.progress(min(pct, 1.0))
            status_text.caption(f"{label}: {info} ({current}/{total})")

        with st.spinner("Backtest läuft — bitte nicht die Seite wechseln..."):
            cached = run_backtest(years=years, step_weeks=step_weeks, progress_callback=_cb)
        progress_bar.progress(1.0)
        status_text.caption("Abgeschlossen.")
        st.rerun()

    if cached is None:
        st.info(
            "Noch kein Backtest berechnet. Klicke auf **Backtest starten** — der erste Lauf lädt "
            "historische Kursdaten für alle S&P500-Titel (~5–30 Minuten je nach Zeitraum, wird dann gecacht)."
        )
        return

    # Ergebnisse anzeigen
    _render_backtest_results(cached)

    # Optimierung + Spielwiese
    st.divider()
    opt_tab, play_tab = st.tabs(["🤖 Auto-Optimierung", "🎚️ Spielwiese"])
    with opt_tab:
        _render_sweep_section(years, step_weeks)
    with play_tab:
        _render_playground(years, step_weeks)


def _render_backtest_results(res: dict):
    from datetime import datetime as _dt

    computed_at = res.get("computed_at", "")
    try:
        age_h = (_dt.now() - _dt.fromisoformat(computed_at)).total_seconds() / 3600
        age_str = f"{int(age_h)}h alt" if age_h < 48 else f"{int(age_h/24)}d alt"
    except Exception:
        age_str = ""

    years = res.get("years", "?")
    step = res.get("step_weeks", "?")
    st.caption(
        f"Berechnet: {computed_at[:10]} {age_str} | "
        f"Zeitraum: {years} Jahre | Scan alle {step} Wochen | "
        f"Simulations-Dates: {res.get('dates_simulated', 0)} "
        f"({res.get('dates_skipped_bearish', 0)} bearische Marktphasen übersprungen)"
    )

    # KPI-Zeile
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Simulierte Trades", res.get("total_trades", 0))
    hit1m = res.get("hit_rate_1m")
    c2.metric("Trefferquote 1M", f"{hit1m:.1f}%" if hit1m is not None else "—",
              delta_color="normal" if (hit1m or 0) >= 50 else "inverse",
              delta="≥50% = gut" if hit1m is not None else None)
    avg1m = res.get("avg_return_1m")
    c3.metric("Ø Return 1M", f"{avg1m:+.2f}%" if avg1m is not None else "—",
              delta_color="normal" if (avg1m or 0) >= 0 else "inverse")
    vs_spy = res.get("avg_vs_spy_1m")
    c4.metric("Ø vs SPY 1M", f"{vs_spy:+.2f}%" if vs_spy is not None else "—",
              delta_color="normal" if (vs_spy or 0) >= 0 else "inverse")
    sharpe = res.get("sharpe_1m")
    c5.metric("Sharpe (1M)", f"{sharpe:.2f}" if sharpe is not None else "—",
              help="Ø Return / Standardabweichung. > 0.5 = gut, > 1.0 = sehr gut.")
    hit3m = res.get("hit_rate_3m")
    c6.metric("Trefferquote 3M", f"{hit3m:.1f}%" if hit3m is not None else "—",
              delta_color="normal" if (hit3m or 0) >= 50 else "inverse")

    st.divider()

    # Tabs
    tab1, tab2, tab3 = st.tabs(["📅 Monatsübersicht", "📊 Return-Verteilung", "📋 Alle Trades"])

    # Tab 1: Monatliche Übersicht
    with tab1:
        by_month = res.get("by_month", [])
        if not by_month:
            st.info("Keine Monatsdaten verfügbar.")
        else:
            months = [m["month"] for m in by_month]
            avgs = [m.get("avg_perf_1m") or 0 for m in by_month]
            hit_rates = [m.get("hit_rate") or 0 for m in by_month]
            vs_spys = [m.get("avg_vs_spy") or 0 for m in by_month]
            ns = [m["n"] for m in by_month]

            fig1 = go.Figure()
            fig1.add_trace(go.Bar(
                x=months, y=avgs,
                name="Ø Return 1M",
                marker_color=["#4CAF50" if v >= 0 else "#F44336" for v in avgs],
                text=[f"{v:+.1f}% (n={n})" for v, n in zip(avgs, ns)],
                textposition="outside",
            ))
            if any(v != 0 for v in vs_spys):
                fig1.add_trace(go.Scatter(
                    x=months, y=vs_spys, name="vs SPY",
                    line=dict(color="#FF9800", width=2, dash="dot"),
                    yaxis="y",
                ))
            fig1.add_hline(y=0, line_color="gray")
            fig1.update_layout(
                title="Monatliche Durchschnittsrendite (simulierte Trades)",
                yaxis_title="Return %", height=400,
                margin=dict(l=0, r=0, t=50, b=0),
                legend=dict(orientation="h", y=-0.15),
            )
            st.plotly_chart(fig1, use_container_width=True)

            # Trefferquote
            fig2 = go.Figure(go.Scatter(
                x=months, y=hit_rates, mode="lines+markers",
                line=dict(color="#2196F3", width=2),
                marker=dict(size=6),
                name="Trefferquote %",
            ))
            fig2.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="50%")
            fig2.update_layout(
                title="Monatliche Trefferquote (Perf 1M > 0)",
                yaxis_title="Trefferquote %", height=280,
                margin=dict(l=0, r=0, t=50, b=0),
            )
            st.plotly_chart(fig2, use_container_width=True)

    # Tab 2: Return-Verteilung
    with tab2:
        trades = res.get("trades", [])
        perfs_1m = [t["perf_1m"] for t in trades if t.get("perf_1m") is not None]
        if not perfs_1m:
            st.info("Keine Return-Daten verfügbar.")
        else:
            fig3 = go.Figure(go.Histogram(
                x=perfs_1m, nbinsx=40,
                marker_color="#2196F3", opacity=0.7,
                name="1M-Returns",
            ))
            fig3.add_vline(x=0, line_color="gray", line_dash="dash")
            mean_val = sum(perfs_1m) / len(perfs_1m)
            fig3.add_vline(x=mean_val, line_color="#FF9800", line_dash="dot",
                           annotation_text=f"Ø {mean_val:+.2f}%")
            fig3.update_layout(
                title=f"Return-Verteilung 1M (n={len(perfs_1m)})",
                xaxis_title="Return %", yaxis_title="Häufigkeit",
                height=350, margin=dict(l=0, r=0, t=50, b=0),
            )
            st.plotly_chart(fig3, use_container_width=True)

            # Kennzahlen
            import statistics as _stats
            perfs_arr = sorted(perfs_1m)
            n = len(perfs_arr)
            kc1, kc2, kc3, kc4 = st.columns(4)
            kc1.metric("Median 1M", f"{_stats.median(perfs_arr):+.2f}%")
            kc2.metric("Best Trade", f"{max(perfs_arr):+.1f}%")
            kc3.metric("Worst Trade", f"{min(perfs_arr):+.1f}%")
            kc4.metric("Std Dev", f"{_stats.stdev(perfs_arr):.2f}%")

    # Tab 3: Alle simulierten Trades
    with tab3:
        trades = res.get("trades", [])
        if not trades:
            st.info("Keine Trade-Daten verfügbar.")
        else:
            rows = []
            for t in sorted(trades, key=lambda x: x["date"], reverse=True):
                rows.append({
                    "Datum": t["date"],
                    "Ticker": t["ticker"],
                    "Einstieg": f"${t.get('entry_price', 0):.2f}",
                    "Tech-Score": f"{t.get('tech_score', 0)*100:.0f}%",
                    "RS-Score": f"{t.get('rs_score', 0):+.1f}",
                    "Perf 1M": f"{t['perf_1m']:+.1f}%" if t.get("perf_1m") is not None else "—",
                    "Perf 3M": f"{t['perf_3m']:+.1f}%" if t.get("perf_3m") is not None else "—",
                    "vs SPY 1M": f"{t['vs_spy_1m']:+.1f}%" if t.get("vs_spy_1m") is not None else "—",
                    "Hit 1M": "✅" if t.get("hit_1m") else ("❌" if t.get("hit_1m") is not None else "—"),
                })
            df_trades = pd.DataFrame(rows)
            col_f1, col_f2 = st.columns([2, 1])
            with col_f1:
                tickers_all = ["Alle"] + sorted(df_trades["Ticker"].unique())
                sel_bt_ticker = st.selectbox("Ticker filtern", tickers_all, key="bt_ticker_filter")
            with col_f2:
                only_bt_hits = st.checkbox("Nur Treffer (1M > 0)", key="bt_only_hits")
            df_f = df_trades.copy()
            if sel_bt_ticker != "Alle":
                df_f = df_f[df_f["Ticker"] == sel_bt_ticker]
            if only_bt_hits:
                df_f = df_f[df_f["Hit 1M"] == "✅"]
            st.caption(f"{len(df_f)} Trades")
            st.dataframe(df_f, use_container_width=True, hide_index=True)


def _render_sweep_section(years: int, step_weeks: int):
    """Auto-Optimierung: Grid-Search über Gate-2/3-Parameter."""
    from backtest.runner import run_param_sweep, load_sweep_results, apply_overrides, clear_overrides, load_overrides

    st.warning(
        "**Hinweise zum Sweep:** Optimiert nur Gates 1–3 (Technik + Relative Stärke). "
        "Gate 4 (Fundamentals) hat keine historischen Daten. "
        "**Survivorship-Bias:** Das Universum ist die *heutige* S&P500-Zusammensetzung — "
        "mehr Jahre = mehr Daten, aber stärkerer Bias. "
        "**Train/Test-Split** zeigt ob gefundene Parameter wirklich generalisieren "
        "(hoher Overfit-Gap → verdächtig)."
    )

    active = load_overrides()
    if active:
        st.success(
            "**Aktive Overrides:** " + ", ".join(f"`{k}={v}`" for k, v in active.items())
        )
        if st.button("🔄 Zurück auf Standard-Werte (config.py)", key="sweep_clear_overrides"):
            clear_overrides()
            st.success("Overrides entfernt — config.py-Defaults wiederhergestellt.")
            st.rerun()

    with st.expander("Sweep-Einstellungen", expanded=True):
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            objective = st.selectbox(
                "Zielmetrik",
                options=["avg_vs_spy_1m", "sharpe_1m", "hit_rate_1m"],
                format_func={"avg_vs_spy_1m": "Ø vs SPY 1M", "sharpe_1m": "Sharpe (1M)", "hit_rate_1m": "Trefferquote 1M"}.get,
                key="sweep_objective",
            )
        with sc2:
            grid_mode = st.radio(
                "Grid-Granularität",
                ["Grob (486 Kombis)", "Fein (2592 Kombis)"],
                key="sweep_grid_mode", horizontal=True,
                help="Fein dauert ~4× länger, testet mehr Zwischenwerte.",
            )
        with sc3:
            min_trades = st.number_input(
                "Min. Trades (Train)", min_value=10, max_value=100, value=30, step=5,
                key="sweep_min_trades",
                help="Kombinationen mit weniger messbaren Trades werden verworfen.",
            )

    if st.button("🔍 Beste Parameter finden", type="primary", key="sweep_run"):
        _grid = None
        if "Fein" in grid_mode:
            _grid = {
                "min_score":         [0.50, 0.67, 0.83, 1.0],
                "rsi_min":           [35, 40, 45, 50],
                "rsi_max":           [65, 70, 75, 80],
                "volume_factor":     [0.8, 1.0, 1.2, 1.5],
                "rs_top_percentile": [0.15, 0.20, 0.25, 0.33],
                "rs_min_6m":         [0.0, 2.0, 5.0],
            }

        pb = st.progress(0.0)
        st_txt = st.empty()
        _phase_labels = {
            "download": "Lade Kursdaten",
            "precompute": "Berechne Indikatoren",
            "sweep_precompute": "Vorberechnung (einmalig)",
            "sweep": "Teste Kombinationen",
        }

        def _cb_sweep(phase, current, total, info=""):
            pct = current / total if total > 0 else 0
            pb.progress(min(pct, 1.0))
            st_txt.caption(f"{_phase_labels.get(phase, phase)}: {info} ({current}/{total})")

        with st.spinner("Sweep läuft — kann mehrere Minuten dauern..."):
            sweep = run_param_sweep(
                years=years, step_weeks=step_weeks,
                grid=_grid, objective=objective,
                min_trades=int(min_trades),
                progress_callback=_cb_sweep,
            )
        pb.progress(1.0)
        st_txt.caption("Abgeschlossen.")
        st.session_state["sweep_results"] = sweep
        st.rerun()

    sweep = st.session_state.get("sweep_results") or load_sweep_results()
    if sweep:
        _render_sweep_results(sweep)


def _render_sweep_results(sweep: dict):
    """Zeigt Sweep-Rangliste, Diff und Übernahme-Buttons."""
    from backtest.runner import apply_overrides, clear_overrides

    ranked = sweep.get("ranked", [])
    best = sweep.get("best")
    current = sweep.get("current_config", {})
    obj = sweep.get("objective", "avg_vs_spy_1m")
    obj_label = {"avg_vs_spy_1m": "vs SPY 1M", "sharpe_1m": "Sharpe (1M)", "hit_rate_1m": "Treffer %"}.get(obj, obj)

    st.caption(
        f"Berechnet: {sweep.get('computed_at','')[:10]} | "
        f"{sweep.get('years','?')} Jahre | Ziel: {obj_label} | "
        f"Train {int(sweep.get('train_frac', 0.6)*100)}% / Test {int((1-sweep.get('train_frac',0.6))*100)}% | "
        f"{sweep.get('valid_combos',0)}/{sweep.get('total_combos_tested',0)} gültige Kombis"
    )

    if not ranked:
        st.warning("Keine gültigen Kombinationen gefunden (zu wenig Trades pro Kombi — mehr Jahre oder kleineres Grid).")
        return

    train_key = f"train_{obj}"
    test_key = f"test_{obj}"

    rows = []
    for i, r in enumerate(ranked[:20]):
        gap = r.get("overfit_gap")
        overfit_flag = " ⚠️" if (gap is not None and gap > 5) else ""
        rows.append({
            "#": i + 1,
            "min_score": r.get("min_score"),
            "rsi_min":   r.get("rsi_min"),
            "rsi_max":   r.get("rsi_max"),
            "vol_f":     r.get("volume_factor"),
            "rs_pct":    r.get("rs_top_percentile"),
            "rs_6m":     r.get("rs_min_6m"),
            f"Train {obj_label}": r.get(train_key),
            f"Test {obj_label}":  r.get(test_key),
            "Gap":        f"{gap:+.1f}{overfit_flag}" if gap is not None else "—",
            "Trades (Tr)": r.get("train_trades"),
        })

    st.subheader("Top-20 Kombinationen")
    st.caption("Gap = Train − Test-Metrik. ⚠️ bei Gap > 5 (mögliches Overfitting).")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if not best:
        return

    # Diff Aktuell vs. Empfohlen
    st.subheader("Aktuell vs. Empfohlen")
    diff_rows = []
    for k, v_curr in current.items():
        v_best = best.get(k, v_curr)
        diff_rows.append({
            "Parameter":               k,
            "Aktuell (config.py)":     v_curr,
            "Empfohlen (beste Kombi)": v_best,
            "Geändert":                "✏️" if v_best != v_curr else "",
        })
    st.dataframe(pd.DataFrame(diff_rows), use_container_width=True, hide_index=True)

    bc1, bc2 = st.columns(2)
    with bc1:
        if st.button("✅ Beste Werte übernehmen", type="primary", key="apply_sweep_best"):
            apply_overrides(best)
            st.success("Übernommen! Wirkt ab dem nächsten Scan (Seite neu laden).")
            st.rerun()
    with bc2:
        if st.button("🔄 Zurück auf Standard-Werte", key="reset_sweep"):
            clear_overrides()
            st.success("Reset — config.py-Defaults werden wieder verwendet.")
            st.rerun()

    with st.expander("📋 Als config.py-Eintrag (für dauerhaften git-Commit)"):
        snippet = (
            "# In config.py → TECHNICAL:\n"
            f'    "min_score":    {best.get("min_score")},\n'
            f'    "rsi_min":      {best.get("rsi_min")},\n'
            f'    "rsi_max":      {best.get("rsi_max")},\n'
            f'    "volume_factor":{best.get("volume_factor")},\n\n'
            "# In config.py → RELATIVE_STRENGTH:\n"
            f'    "rs_top_percentile": {best.get("rs_top_percentile")},\n'
            f'    "rs_min_6m":         {best.get("rs_min_6m")},'
        )
        st.code(snippet, language="python")


def _snap_to_options(val, options):
    """Rundet einen Wert auf die nächstliegende Option (für select_slider)."""
    return min(options, key=lambda x: abs(x - val))


def _render_playground(years: int, step_weeks: int):
    """Interaktive Spielwiese: Parameter selbst wählen, historische Performance simulieren."""
    from backtest.runner import run_custom_backtest, apply_overrides, clear_overrides, load_overrides
    import config as _cfg

    st.write(
        "Stelle die Parameter selbst ein und sieh, wie das System damit historisch abgeschnitten hätte. "
        "Nutzt den vorhandenen Preis-Cache — nach dem ersten Backtest sehr schnell."
    )

    active = load_overrides()

    _score_opts = [0.50, 0.67, 0.83, 1.0]
    _rs_pct_opts = [0.10, 0.15, 0.20, 0.25, 0.33, 0.40, 0.50]

    with st.form("playground_form"):
        st.subheader("Gate 3 — Technische Analyse")
        pg1, pg2, pg3, pg4 = st.columns(4)
        with pg1:
            _ms_raw = float(active.get("min_score", _cfg.TECHNICAL.get("min_score", 0.70)))
            p_min_score = st.select_slider(
                "Min. Tech-Score",
                options=_score_opts,
                value=_snap_to_options(_ms_raw, _score_opts),
                format_func=lambda x: f"{int(x*100)}% ({int(x*6)}/6 Signale)",
            )
        with pg2:
            p_rsi_min = st.number_input(
                "RSI Min", min_value=20, max_value=60, step=5,
                value=int(active.get("rsi_min", _cfg.TECHNICAL.get("rsi_min", 45))),
            )
        with pg3:
            p_rsi_max = st.number_input(
                "RSI Max", min_value=50, max_value=90, step=5,
                value=int(active.get("rsi_max", _cfg.TECHNICAL.get("rsi_max", 70))),
            )
        with pg4:
            p_vol = st.number_input(
                "Volumen-Faktor", min_value=0.5, max_value=3.0, step=0.1,
                value=float(active.get("volume_factor", _cfg.TECHNICAL.get("volume_factor", 1.2))),
                format="%.1f",
                help="Volumen muss X-fach über dem 20-Tage-Durchschnitt liegen.",
            )

        st.subheader("Gate 2 — Relative Stärke")
        pg5, pg6 = st.columns(2)
        with pg5:
            _rsp_raw = float(active.get("rs_top_percentile", _cfg.RELATIVE_STRENGTH.get("rs_top_percentile", 0.33)))
            p_rs_pct = st.select_slider(
                "RS-Perzentil (Top-X% nach rs_score)",
                options=_rs_pct_opts,
                value=_snap_to_options(_rsp_raw, _rs_pct_opts),
                format_func=lambda x: f"Top {int(x*100)}%",
            )
        with pg6:
            p_rs_min6 = st.number_input(
                "6M-Momentum Mindest-Floor (%)",
                min_value=-10.0, max_value=20.0, step=1.0,
                value=float(active.get("rs_min_6m", _cfg.RELATIVE_STRENGTH.get("rs_min_6m", 0.0))),
                format="%.1f",
                help="6M-Rendite vs. S&P500 muss mindestens diesen Wert haben.",
            )

        submitted = st.form_submit_button("▶️ Mit diesen Werten testen", type="primary")

    if submitted:
        _pg_params = {
            "min_score":         float(p_min_score),
            "rsi_min":           int(p_rsi_min),
            "rsi_max":           int(p_rsi_max),
            "volume_factor":     round(float(p_vol), 2),
            "rs_top_percentile": float(p_rs_pct),
            "rs_min_6m":         round(float(p_rs_min6), 2),
        }
        pb2 = st.progress(0.0)
        st2 = st.empty()
        _pm = {"download": "Lade Kursdaten", "precompute": "Berechne Indikatoren"}

        def _cb_pg(phase, current, total, info=""):
            pct = current / total if total > 0 else 0
            pb2.progress(min(pct, 1.0))
            st2.caption(f"{_pm.get(phase, phase)}: {info} ({current}/{total})")

        with st.spinner("Simuliere..."):
            _res = run_custom_backtest(years=years, step_weeks=step_weeks,
                                       params=_pg_params, progress_callback=_cb_pg)
        pb2.progress(1.0)
        st2.caption("Abgeschlossen.")
        st.session_state["playground_result"] = _res
        st.session_state["playground_params"] = _pg_params

    _pg_res = st.session_state.get("playground_result")
    if _pg_res:
        st.subheader("Simulations-Ergebnis")
        pc1, pc2, pc3, pc4, pc5, pc6 = st.columns(6)
        _h1m = _pg_res.get("hit_rate_1m")
        _a1m = _pg_res.get("avg_return_1m")
        _vs  = _pg_res.get("avg_vs_spy_1m")
        _sh  = _pg_res.get("sharpe_1m")
        _h3m = _pg_res.get("hit_rate_3m")
        pc1.metric("Simulierte Trades", _pg_res.get("total_trades", 0))
        pc2.metric("Trefferquote 1M",  f"{_h1m:.1f}%" if _h1m is not None else "—",
                   delta_color="normal" if (_h1m or 0) >= 50 else "inverse")
        pc3.metric("Ø Return 1M",      f"{_a1m:+.2f}%" if _a1m is not None else "—",
                   delta_color="normal" if (_a1m or 0) >= 0 else "inverse")
        pc4.metric("Ø vs SPY 1M",      f"{_vs:+.2f}%" if _vs is not None else "—",
                   delta_color="normal" if (_vs or 0) >= 0 else "inverse")
        pc5.metric("Sharpe (1M)",      f"{_sh:.2f}" if _sh is not None else "—")
        pc6.metric("Trefferquote 3M",  f"{_h3m:.1f}%" if _h3m is not None else "—",
                   delta_color="normal" if (_h3m or 0) >= 50 else "inverse")

        _pg_p = st.session_state.get("playground_params", {})
        pp1, pp2 = st.columns(2)
        with pp1:
            if st.button("✅ Diese Werte übernehmen", type="primary", key="apply_playground"):
                apply_overrides(_pg_p)
                st.success("Übernommen! Wirkt ab dem nächsten Scan.")
                st.rerun()
        with pp2:
            if st.button("🔄 Zurück auf Standard-Werte", key="reset_playground"):
                clear_overrides()
                st.success("Reset — config.py-Defaults werden wieder verwendet.")
                st.rerun()

