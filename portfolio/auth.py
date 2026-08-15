"""
Einfaches Passwort-Gate für die App (Ein-Nutzer-Setup).

Ersetzt die frühere Supabase-Auth: Da nur ein Nutzer das Portfolio pflegt,
genügt ein Passwortvergleich gegen st.secrets["PORTFOLIO_PASSWORD"]. Ohne
gesetztes Passwort ist die App offen (praktisch für rein lokale Nutzung).
"""

import hmac
import streamlit as st


def _configured_password() -> str | None:
    try:
        pw = st.secrets["PORTFOLIO_PASSWORD"]
    except (KeyError, FileNotFoundError):
        import os
        pw = os.environ.get("PORTFOLIO_PASSWORD")
    return str(pw) if pw else None


def render_auth_gate() -> bool:
    """
    Zeigt ein Passwortfeld, wenn ein PORTFOLIO_PASSWORD konfiguriert ist und die
    Session noch nicht freigeschaltet wurde.
    Gibt True zurück, wenn Zugriff erlaubt ist (App läuft weiter), sonst False.
    """
    password = _configured_password()

    # Kein Passwort gesetzt → App offen (z. B. lokale Entwicklung).
    if not password:
        return True

    if st.session_state.get("portfolio_unlocked"):
        return True

    st.title("📈 S&P500 Analyse")
    st.markdown("---")
    with st.form("unlock_form"):
        entered = st.text_input("Passwort", type="password")
        submitted = st.form_submit_button("Entsperren", type="primary", use_container_width=True)
        if submitted:
            if entered and hmac.compare_digest(entered, password):
                st.session_state.portfolio_unlocked = True
                st.rerun()
            else:
                st.error("Falsches Passwort.")

    return False


def render_logout_button():
    """Sperr-Button für die Sidebar (nur sinnvoll, wenn ein Passwort gesetzt ist)."""
    if not _configured_password():
        return
    if not st.session_state.get("portfolio_unlocked"):
        return
    if st.button("Sperren", use_container_width=True):
        st.session_state.pop("portfolio_unlocked", None)
        st.rerun()
