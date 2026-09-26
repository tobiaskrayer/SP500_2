"""Seitenübergreifende Render-Helfer."""

import streamlit as st
from datetime import datetime


def _fmt_ts(ts: str) -> str:
    """ISO-Zeitstempel → lesbares deutsches Format (Europe/Berlin)."""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M") + " (DE)"
    except Exception:
        return ts


def render_data_status(result):
    if not result:
        st.info("Noch kein gespeicherter Scan verfügbar.")
        return
    from analyzer.sessions import last_completed_session
    from analyzer.strategy import strategy_metadata
    st.caption(f"Letzter erfolgreicher Scan: {_fmt_ts(result.get('timestamp', '—'))}")
    strategy = result.get("strategy") or {}
    current = strategy_metadata()
    if strategy.get("version") != current["version"] or strategy.get("config_hash") != current["config_hash"]:
        st.warning("Archivierte Auswahl mit früheren Regeln. Ein neuer Scan ist erforderlich.")
    data_date = (result.get("market") or {}).get("data_as_of")
    if not data_date or data_date < str(last_completed_session()):
        st.warning("Kursdaten sind nicht auf dem Stand der letzten abgeschlossenen US-Handelssitzung.")



@st.cache_data(ttl=900, show_spinner=False)
def cached_market() -> dict:
    """
    Gate-1-Marktcheck, 15 Minuten gecacht.

    check_market() macht zwei yfinance-Calls (^GSPC, ^VIX). Ohne Cache liefe das
    bei jedem Streamlit-Rerun neu — also bei jedem Klick auf der Portfolio- und
    der Marktübersichtsseite.
    """
    from analyzer.market_filter import check_market
    return check_market()


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
    with col1:
        ep_str = f"€{entry_price:.2f}" if entry_price else "—"
        st.metric("Aktueller Kurs", ep_str)
    with col2:
        st.metric("Automatischer Stop", "—")
    with col3:
        st.metric("Automatisches Kursziel", "—")

    if atr:
        st.caption(f"ATR(14): {atr:.4f} USD — Volatilitätsmaß, kein automatischer Verkaufsauftrag.")

    st.divider()
    signals = exits.get("signals", {})
    if signals:
        st.write("**Aktive Exit-Signale:**")
        for signal, active in signals.items():
            icon = "🔴" if active else "🟢"
            st.write(f"{icon} {signal}")

