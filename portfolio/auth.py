"""
Supabase Auth: Login, Signup, Logout und Session-Handling für Streamlit.
"""

import streamlit as st
from portfolio.supabase_client import get_supabase


def current_user_id() -> str | None:
    """Gibt die UUID des eingeloggten Nutzers zurück, oder None."""
    user = st.session_state.get("sb_user")
    if user:
        return user.id
    return None


def render_auth_gate() -> bool:
    """
    Zeigt Login/Signup-Formular wenn kein Nutzer eingeloggt ist.
    Gibt True zurück wenn Nutzer eingeloggt, False wenn nicht (App soll anhalten).
    """
    if "sb_user" not in st.session_state:
        # Session aus dem Supabase-Client dieser Session wiederherstellen (normaler Rerun).
        # Kein Auto-Login über Secrets mehr: der loggte jeden anonymen Besucher als das
        # Secrets-Konto ein — bei mehreren Nutzern ein Datenleck. Nach einem Redeploy
        # ist daher ein erneuter Login nötig.
        try:
            sb = get_supabase()
            session = sb.auth.get_session()
            if session and session.user:
                st.session_state.sb_user = session.user
        except Exception:
            pass

    if st.session_state.get("sb_user"):
        return True

    # Login/Signup UI
    st.title("📈 S&P500 Analyse")
    st.markdown("---")

    tab_login, tab_signup = st.tabs(["Einloggen", "Registrieren"])

    with tab_login:
        with st.form("login_form"):
            email = st.text_input("Email")
            password = st.text_input("Passwort", type="password")
            submitted = st.form_submit_button("Einloggen", type="primary", use_container_width=True)
            if submitted:
                if not email or not password:
                    st.error("Email und Passwort eingeben.")
                else:
                    try:
                        sb = get_supabase()
                        res = sb.auth.sign_in_with_password({"email": email, "password": password})
                        st.session_state.sb_user = res.user
                        st.rerun()
                    except Exception as e:
                        st.error(f"Login fehlgeschlagen: {e}")

    with tab_signup:
        st.caption("Registriere dich, um dein eigenes Portfolio zu tracken.")
        with st.form("signup_form"):
            new_email = st.text_input("Email", key="su_email")
            new_pw = st.text_input("Passwort (mind. 6 Zeichen)", type="password", key="su_pw")
            new_pw2 = st.text_input("Passwort wiederholen", type="password", key="su_pw2")
            submitted = st.form_submit_button("Registrieren", type="primary", use_container_width=True)
            if submitted:
                if not new_email or not new_pw:
                    st.error("Alle Felder ausfüllen.")
                elif new_pw != new_pw2:
                    st.error("Passwörter stimmen nicht überein.")
                elif len(new_pw) < 6:
                    st.error("Passwort muss mindestens 6 Zeichen haben.")
                else:
                    try:
                        sb = get_supabase()
                        res = sb.auth.sign_up({"email": new_email, "password": new_pw})
                        if res.user:
                            # Falls Email-Bestätigung deaktiviert → direkt einloggen
                            if res.session:
                                st.session_state.sb_user = res.user
                                st.rerun()
                            else:
                                st.success(
                                    "Registrierung erfolgreich! Bestätige deine Email-Adresse "
                                    "und logge dich dann ein."
                                )
                        else:
                            st.error("Registrierung fehlgeschlagen — versuche es erneut.")
                    except Exception as e:
                        st.error(f"Registrierung fehlgeschlagen: {e}")

    return False


def render_logout_button():
    """Logout-Button für die Sidebar."""
    user = st.session_state.get("sb_user")
    if not user:
        return
    email = getattr(user, "email", "")
    st.caption(f"Eingeloggt als: **{email}**")
    if st.button("Ausloggen", use_container_width=True):
        try:
            get_supabase().auth.sign_out()
        except Exception:
            pass
        st.session_state.pop("sb_user", None)
        st.session_state.pop("sb_client", None)  # Client mit Auth-Token verwerfen
        st.rerun()
