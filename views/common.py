"""Seitenübergreifende Render-Helfer."""

import streamlit as st
from datetime import datetime


def _fmt_ts(ts: str) -> str:
    """ISO-Zeitstempel → lesbares deutsches Format (Europe/Berlin)."""
    try:
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(ts).replace(tzinfo=ZoneInfo("UTC"))
        return dt.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M") + " (DE)"
    except Exception:
        return ts



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
    sl = exits.get("stop_loss")
    tp = exits.get("take_profit")
    stop_label = exits.get("stop_label") or "Stop-Loss"
    with col1:
        ep_str = f"€{entry_price:.2f}" if entry_price else "—"
        st.metric("Aktueller Kurs", ep_str)
    with col2:
        sl_delta = f"-{abs(sl - entry_price):.2f}" if sl is not None and entry_price else None
        st.metric(stop_label, f"€{sl:.2f}" if sl is not None else "N/A",
                  delta=sl_delta, delta_color="inverse")
    with col3:
        tp_delta = f"+{abs(tp - entry_price):.2f}" if tp is not None and entry_price else None
        st.metric("Take-Profit (ATR×3, dynamisch)", f"€{tp:.2f}" if tp is not None else "N/A",
                  delta=tp_delta, delta_color="normal")

    if atr:
        st.caption(f"ATR(14): {atr:.4f} USD — Stop und Take-Profit passen sich täglich an den aktuellen Kurs an.")

    st.divider()
    signals = exits.get("signals", {})
    if signals:
        st.write("**Aktive Exit-Signale:**")
        for signal, active in signals.items():
            icon = "🔴" if active else "🟢"
            st.write(f"{icon} {signal}")

