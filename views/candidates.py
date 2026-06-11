"""Seite: Kauf-Kandidaten (v1∩v2, Top-N-Ranking)."""

import streamlit as st
import pandas as pd


def page_buy_candidates(result: dict | None):
    """
    Kauf-Kandidaten — wendet die evidenzbasierte Entscheidungslogik automatisch an:
    nur bei grünem Markt, v1∩v2-Schnittmenge (höchste Konfidenz), parabolische
    RS-Ausreißer markiert, nach Sektor gruppiert, mit Stop-Loss + Gleichgewichtung.
    """
    st.header("🛒 Kauf-Kandidaten")
    st.caption(
        "Automatische Priorisierung nach den Backtest-Befunden: gestreuter Korb aus der "
        "Schnittmenge beider Algorithmen, hoher (aber nicht parabolischer) RS, mit Stop-Loss. "
        "Keine Anlageberatung — der Edge ist statistisch und moderat."
    )

    if result is None:
        st.info("Noch keine Analysedaten. Starte die Analyse über die Seitenleiste.")
        return

    market = result.get("market", {})

    # Schritt 1: Markt-Gate
    if not market.get("passed"):
        st.error(
            f"**Roter Markt — keine Kauf-Kandidaten.**\n\n"
            f"Grund: {market.get('reason', 'Unbekannt')}\n\n"
            f"Die Disziplin, bei ungünstigem Marktregime auszusetzen, ist Teil des Edges.",
            icon="🚫",
        )
        return
    if market.get("warning"):
        st.warning(f"⚠️ Markt grün, aber vorsichtig: {market.get('reason', '')}", icon="⚠️")

    recommendations = result.get("recommendations", [])
    v2 = result.get("recommendations_v2")

    if v2 is None:
        st.info(
            "Dieser Scan enthält noch keine v2-Daten (älterer Cache). Bitte einmal **Scan starten** "
            "(Seitenleiste) — danach wird die Schnittmenge v1∩v2 berechnet."
        )
        return

    v2_tickers = {r.get("ticker") for r in v2}
    # v2-Rang (1..top_n) + MACD je Ticker — für Top-5-Markierung und Tiebreaker-Anzeige
    v2_rank_by_ticker = {r.get("ticker"): r.get("v2_rank") for r in v2}
    macd_by_ticker = {r.get("ticker"): r.get("macd_bull") for r in v2}
    try:
        from config import RECOMMENDER_V2 as _rec_v2_cfg
        parabolic_thr = _rec_v2_cfg.get("parabolic_rs_warn", 150.0)
        top_n_strong = _rec_v2_cfg.get("top_n_strong", 5)
    except Exception:
        parabolic_thr = 150.0
        top_n_strong = 5

    # Schritt 2: v1∩v2-Schnittmenge (volle v1-Dicts haben exits/rs/sector)
    candidates = []
    watch_only = []
    for r in recommendations:
        if r.get("ticker") not in v2_tickers:
            continue
        exits = r.get("exits", {}) or {}
        exit_rec = exits.get("recommendation", "Halten")
        # Was das Tool selbst zum Verkauf flaggt, ist kein Kauf-Kandidat
        if exit_rec == "Verkaufen erwägen":
            continue
        rs = r.get("rs", {}) or {}
        rs_score = rs.get("rs_score")
        price = r.get("price")
        stop = exits.get("stop_loss")
        stop_pct = round((stop / price - 1) * 100, 1) if (stop and price) else None
        v2_rank = v2_rank_by_ticker.get(r.get("ticker"))
        macd_bull = r.get("macd_bull")
        if macd_bull is None:
            macd_bull = macd_by_ticker.get(r.get("ticker"))
        entry = {
            "ticker": r.get("ticker"),
            "name": (r.get("name") or "")[:26],
            "sector": r.get("sector") or "—",
            "rs_score": round(rs_score, 1) if rs_score is not None else None,
            "parabolic": bool(rs_score is not None and rs_score > parabolic_thr),
            "confidence": r.get("confidence_label") or "—",
            "price": price,
            "stop": stop,
            "stop_pct": stop_pct,
            "exit_rec": exit_rec,
            "v2_rank": v2_rank,
            "top5": bool(v2_rank is not None and v2_rank <= top_n_strong),
            "macd_bull": macd_bull,
        }
        if exit_rec == "Beobachten":
            watch_only.append(entry)
        else:
            candidates.append(entry)

    n_v1 = len(recommendations)
    if not candidates and not watch_only:
        st.info(
            f"Heute keine Hochkonvikt-Kandidaten. v1 hat {n_v1} Empfehlung(en), aber keine davon "
            f"liegt auch in der strengeren v2-Schnittmenge mit sauberem Einstieg. "
            f"Lieber abwarten als erzwingen."
        )
        return

    clean = [c for c in candidates if not c["parabolic"]]
    n_total = len(candidates)
    n_top5 = sum(1 for c in candidates if c["top5"])

    # ── Kopf-Kennzahlen ────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Kandidaten (v1∩v2)", n_total,
              help="v2 ist auf die 10 RS-stärksten begrenzt (Top-N-Befund im 10J-Backtest).")
    c2.metric("⭐ davon Top-5", n_top5,
              help="Die 5 RS-stärksten v2-Picks — im Backtest die stärkste Gruppe (+3,2 % vs SPY/Monat).")
    c3.metric("davon sauber (nicht parabolisch)", len(clean))
    c4.metric("⚠️ Beobachten", len(watch_only),
              help="In der Schnittmenge, zeigen aber bereits erste Exit-Signale — nachrangig.")

    # ── Gleichgewichtungs-Rechner ───────────────────────────────────────────────
    with st.expander("⚖️ Gleichgewichtung berechnen", expanded=False):
        st.caption(
            "Der Edge liegt im **Korb**, nicht im Einzeltitel (Einzeltitel schlagen den SPY nur "
            "~50 %, der Korb ~62 %). Daher gleichgewichtet streuen."
        )
        cap = st.number_input("Einzusetzendes Kapital", min_value=0.0, value=10000.0, step=500.0)
        n_for_alloc = len(clean) if clean else n_total
        if n_for_alloc > 0 and cap > 0:
            per = cap / n_for_alloc
            st.write(f"Bei **{n_for_alloc}** sauberen Kandidaten gleichgewichtet: "
                     f"**{per:,.0f}** pro Position ({100/n_for_alloc:.1f} % je Titel).")

    st.divider()

    # ── Gesamt-Rangliste (primär) ────────────────────────────────────────────────
    st.subheader("📊 Rangliste")
    st.caption(
        "Rang nach **RS-Score** — das einzige im 10-Jahres-Backtest vorhersagestarke Signal "
        "(relative Stärke vs. Markt). ⭐ = Top-5 des v2-Rankings (stärkste Gruppe im Backtest). "
        "Saubere Titel zuerst, parabolische (⚡) ans Ende demotet, da sie trotz hohem RS "
        "crash-anfällig sind. MACD ist reine Zusatz-Info (Tiebreaker): bullisch reduziert "
        "historisch das Worst-Case-Risiko, kostet als harter Filter aber Rendite. "
        "**Zum Stop-Loss:** Die Stop-Simulation (backtest/stop_sim.py) zeigt, dass enge "
        "ATR-Stops bei 1–8-Wochen-Momentum mehr Rendite kosten als sie schützen — der "
        "angezeigte Stop taugt als *weiter Katastrophen-Schutz*, nicht als enge Reißleine. "
        "Risikokontrolle primär über Korbbreite (gleichgewichtet streuen) und das Markt-Gate."
    )

    # Sortierung: erst saubere nach RS absteigend, dann parabolische nach RS absteigend.
    ranked = sorted(candidates, key=lambda x: (x["parabolic"], -(x["rs_score"] or 0)))
    rows = []
    for i, c in enumerate(ranked, 1):
        macd = c.get("macd_bull")
        rows.append({
            "Rang": i,
            "Ticker": ("⭐ " if c["top5"] else "") + ("⚡ " if c["parabolic"] else "") + c["ticker"],
            "Name": c["name"],
            "Sektor": c["sector"],
            "v2-Rang": c["v2_rank"] if c["v2_rank"] is not None else "—",
            "RS-Score": c["rs_score"],
            "MACD": "🟢" if macd else ("🔴" if macd is not None else "—"),
            "Konfidenz": c["confidence"],
            "Kurs": f"${c['price']:.2f}" if c["price"] else "—",
            "Stop-Loss": f"${c['stop']:.2f}" if c["stop"] else "—",
            "Stop %": f"{c['stop_pct']:+.1f}%" if c["stop_pct"] is not None else "—",
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if any(c["parabolic"] for c in candidates):
        st.warning(
            "⚡ markierte Titel sind sehr stark gelaufen (hoher RS-Score) und stehen daher trotz "
            "des hohen RS am Ende der Rangliste. Im 10-Jahres-Backtest lieferten genau solche "
            "überdehnten Namen die schlimmsten Einbrüche. Wenn überhaupt, nur kleiner gewichten "
            "und Stop eng setzen."
        )

    # ── Sektor-Aufschlüsselung (sekundär) ─────────────────────────────────────────
    with st.expander("🏭 Nach Sektor aufgeschlüsselt"):
        from collections import defaultdict
        by_sector = defaultdict(list)
        for c in ranked:
            by_sector[c["sector"]].append(c)
        for sector in sorted(by_sector):
            st.markdown(f"**{sector}** ({len(by_sector[sector])})")
            st.dataframe(pd.DataFrame([{
                "Ticker": ("⚡ " if c["parabolic"] else "") + c["ticker"],
                "RS-Score": c["rs_score"],
                "Konfidenz": c["confidence"],
                "Kurs": f"${c['price']:.2f}" if c["price"] else "—",
                "Stop-Loss": f"${c['stop']:.2f}" if c["stop"] else "—",
            } for c in by_sector[sector]]), use_container_width=True, hide_index=True)

    if watch_only:
        with st.expander(f"⚠️ {len(watch_only)} Kandidaten mit ersten Exit-Signalen (nachrangig)"):
            st.dataframe(pd.DataFrame([{
                "Ticker": c["ticker"], "Name": c["name"], "Sektor": c["sector"],
                "RS-Score": c["rs_score"], "Exit-Status": c["exit_rec"],
            } for c in watch_only]), use_container_width=True, hide_index=True)

